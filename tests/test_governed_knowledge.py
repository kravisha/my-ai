"""The governed knowledge layer (TQ-82; addendum 46 §4, §5, §17, §18;
docs/SPEC_RECONCILIATION.md §125).

Almost every test here is about the same sentence — *"lower-level material cannot
silently override higher-level authority"* — approached from a different
direction, because the word `silently` has more ways to fail than it looks.
"""

from __future__ import annotations

import pytest

from backend import governed_knowledge as governed, parliament, portfolios

OWNER = portfolios.for_superuser("krish")
ROLL = {"broad": ["coo", "explorer", "speculator", "analysis"],
        "representative": ["coo", "analysis"]}


@pytest.fixture
def governed_conn(conn):
    parliament.adopt_genesis_articles(
        conn, owner=OWNER, text="The Articles.", roll=ROLL,
        quorum="1/2", ordinary_threshold="1/2")
    return conn


def _enact(conn, level: str, title: str = "A resolution") -> int:
    """Carry a resolution at `level` so something can be adopted under it."""
    resolution = parliament.propose(conn, title=title, rationale="r",
                                    proposed_by="coo", affects=level)
    roll = ROLL["representative"] if parliament.get_resolution(
        conn, resolution)["tier"] == parliament.TIER_REPRESENTATIVE else ROLL["broad"]
    for voter in roll:
        parliament.cast_vote(conn, resolution, voter=voter, value="for")
    parliament.close(conn, resolution)
    return resolution


# --- precedence, which is the whole module ------------------------------------------

def test_the_highest_authority_on_a_subject_is_what_governs(governed_conn):
    policy = _enact(governed_conn, "organization_policy")
    procedure = _enact(governed_conn, "procedure")
    governed.adopt(governed_conn, subject="requests", level="procedure",
                   text="Send requests by email.", adopted_by="coo",
                   resolution_id=procedure, binds="*")
    governed.adopt(governed_conn, subject="requests", level="organization_policy",
                   text="Requests carry acceptance criteria.", adopted_by="coo",
                   resolution_id=policy, binds="*")

    assert governed.effective(governed_conn, "requests") == "Requests carry acceptance criteria."


def test_the_subordinate_item_is_reachable_but_never_the_answer(governed_conn):
    """A procedure under a policy is ordinary and useful. A procedure returned as
    *the rule* is the silent override."""
    policy = _enact(governed_conn, "organization_policy")
    procedure = _enact(governed_conn, "procedure")
    governed.adopt(governed_conn, subject="requests", level="organization_policy",
                   text="Policy text.", adopted_by="coo", resolution_id=policy, binds="*")
    governed.adopt(governed_conn, subject="requests", level="procedure",
                   text="Procedure text.", adopted_by="coo", resolution_id=procedure, binds="*")

    assert governed.effective(governed_conn, "requests") == "Policy text."
    below = governed.subordinate(governed_conn, "requests")
    assert [item["text"] for item in below] == ["Procedure text."]


def test_order_of_adoption_does_not_decide_which_governs(governed_conn):
    """The failure mode this module exists for: a store answering with whichever
    row the query ordered first. Adopting the weaker item *last* must not make it
    the answer."""
    policy = _enact(governed_conn, "organization_policy")
    suggestion_first = governed.adopt(
        governed_conn, subject="requests", level="suggestion",
        text="Maybe use a form.", adopted_by="explorer")
    governed.adopt(governed_conn, subject="requests", level="organization_policy",
                   text="Policy text.", adopted_by="coo", resolution_id=policy, binds="*")
    late = governed.adopt(governed_conn, subject="requests", level="knowledge",
                          text="Teams historically used email.", adopted_by="explorer")

    assert governed.effective(governed_conn, "requests") == "Policy text."
    assert {item["id"] for item in governed.subordinate(governed_conn, "requests")} == {
        suggestion_first, late}


def test_an_item_claiming_to_replace_something_above_it_is_refused_and_escalated(governed_conn):
    """The silent override with its intent declared out loud, which is the only
    version of it this layer can see."""
    policy = _enact(governed_conn, "organization_policy")
    policy_item = governed.adopt(
        governed_conn, subject="requests", level="organization_policy",
        text="Policy text.", adopted_by="coo", resolution_id=policy, binds="*")

    with pytest.raises(governed.AdoptionRefused) as refusal:
        governed.adopt(governed_conn, subject="requests", level="suggestion",
                       text="Ignore the policy.", adopted_by="explorer",
                       replaces=policy_item)
    assert str(refusal.value) == governed.REFUSAL
    assert parliament.outstanding_escalations(governed_conn), "it must reach the owner"


# --- fail closed on read ------------------------------------------------------------

def test_two_equal_authorities_on_one_subject_cannot_be_created(governed_conn):
    first = _enact(governed_conn, "organization_policy", "first")
    second = _enact(governed_conn, "organization_policy", "second")
    governed.adopt(governed_conn, subject="requests", level="organization_policy",
                   text="One.", adopted_by="coo", resolution_id=first, binds="*")
    with pytest.raises(governed.AdoptionRefused):
        governed.adopt(governed_conn, subject="requests", level="organization_policy",
                       text="Two.", adopted_by="coo", resolution_id=second, binds="*")


def test_a_read_that_finds_two_equal_authorities_refuses_to_choose(governed_conn):
    """Constructed directly, because `adopt` prevents it — and the read path must
    still fail closed if a row ever arrives another way (a migration, a restore, a
    future writer). A store that answered here would resolve a governance
    conflict through the least visible door in the system."""
    for text in ("One.", "Two."):
        governed_conn.execute(
            "INSERT INTO governed_items (adopted_at, subject, level, text, adopted_by)"
            " VALUES ('2026-01-01T00:00:00+00:00', 'requests', 'knowledge', ?, 'explorer')",
            (text,))
    with pytest.raises(governed.AmbiguousAuthority):
        governed.effective(governed_conn, "requests")
    assert governed.conflicts(governed_conn) == [
        {"subject": "requests", "level": "knowledge", "items": [1, 2]}]


def test_nothing_governing_a_subject_is_an_error_and_not_an_empty_string(governed_conn):
    with pytest.raises(governed.NotGoverned):
        governed.effective(governed_conn, "requests")


# --- authority requires provenance --------------------------------------------------

def test_a_governing_level_needs_an_enacted_resolution(governed_conn):
    with pytest.raises(governed.AdoptionRefused):
        governed.adopt(governed_conn, subject="requests", level="organization_policy",
                       text="Policy text.", adopted_by="coo")


def test_an_open_resolution_authorizes_nothing(governed_conn):
    resolution = parliament.propose(governed_conn, title="x", rationale="r",
                                    proposed_by="coo", affects="organization_policy")
    with pytest.raises(governed.AdoptionRefused):
        governed.adopt(governed_conn, subject="requests", level="organization_policy",
                       text="Policy text.", adopted_by="coo", resolution_id=resolution)


def test_a_resolution_cannot_be_spent_on_a_level_it_was_not_enacted_for(governed_conn):
    """The authority granted is the authority given. Without this, one carried
    vote on a procedure becomes a licence to write a law."""
    procedure = _enact(governed_conn, "procedure")
    with pytest.raises(governed.AdoptionRefused) as refusal:
        governed.adopt(governed_conn, subject="requests", level="law",
                       text="A law.", adopted_by="coo", resolution_id=procedure, binds="*")
    assert "cannot be spent" in str(refusal.value)


def test_material_that_carries_no_authority_needs_no_vote(governed_conn):
    """And in the absence of a rule, the best available knowledge is what the
    organization has — so this is a legitimate answer, not a loophole."""
    governed.adopt(governed_conn, subject="requests", level="knowledge",
                   text="Teams historically used email.", adopted_by="explorer")
    assert governed.effective(governed_conn, "requests") == "Teams historically used email."


def test_a_resolution_cannot_be_spent_on_material_that_carries_no_authority(governed_conn):
    """A vote attached to a suggestion would make it look governed while the
    hierarchy still ranks it last — an item whose provenance and authority
    disagree."""
    policy = _enact(governed_conn, "organization_policy")
    with pytest.raises(governed.AdoptionRefused):
        governed.adopt(governed_conn, subject="requests", level="suggestion",
                       text="A suggestion.", adopted_by="explorer", resolution_id=policy, binds="*")


# --- the boundary at level 0 --------------------------------------------------------

def test_the_constitution_cannot_be_adopted_here_and_the_attempt_escalates(governed_conn):
    with pytest.raises(governed.AdoptionRefused) as refusal:
        governed.adopt(governed_conn, subject="axioms", level="constitution",
                       text="New axioms.", adopted_by="explorer")
    assert str(refusal.value) == governed.REFUSAL
    assert len(parliament.outstanding_escalations(governed_conn)) == 1


def test_an_unknown_level_gets_the_same_refusal_as_the_constitution(governed_conn):
    """§123's rule, held here too: a caller able to distinguish the two could map
    the boundary by probing it."""
    with pytest.raises(governed.AdoptionRefused) as unknown:
        governed.adopt(governed_conn, subject="x", level="whatever",
                       text="t", adopted_by="explorer")
    with pytest.raises(governed.AdoptionRefused) as reserved:
        governed.adopt(governed_conn, subject="x", level="constitution",
                       text="t", adopted_by="explorer")
    assert str(unknown.value) == str(reserved.value) == governed.REFUSAL


def test_the_articles_are_parliaments_record_and_not_this_stores(governed_conn):
    with pytest.raises(governed.AdoptionRefused) as refusal:
        governed.adopt(governed_conn, subject="articles", level="articles",
                       text="t", adopted_by="coo")
    assert "Parliament" in str(refusal.value)


def test_the_hierarchy_is_not_restated_here():
    """Two copies of the precedence order is how the two stop agreeing."""
    assert governed.LEVELS is parliament.LEVELS


# --- superseded, never deleted ------------------------------------------------------

def test_replacing_an_instrument_keeps_the_old_one(governed_conn):
    first = _enact(governed_conn, "organization_policy", "first")
    second = _enact(governed_conn, "organization_policy", "second")
    original = governed.adopt(governed_conn, subject="requests", level="organization_policy",
                              text="One.", adopted_by="coo", resolution_id=first, binds="*")
    replacement = governed.adopt(governed_conn, subject="requests", level="organization_policy",
                                 text="Two.", adopted_by="coo", resolution_id=second, binds="*",
                                 replaces=original)

    assert governed.effective(governed_conn, "requests") == "Two."
    past = governed.history(governed_conn, "requests")
    assert [item["id"] for item in past] == [original, replacement]
    assert past[0]["superseded_at"] and past[0]["superseded_by"] == replacement
    assert past[1]["replaces"] == original


def test_an_adopted_item_carries_the_provenance_addendum_46_asks_for(governed_conn):
    policy = _enact(governed_conn, "organization_policy")
    item_id = governed.adopt(governed_conn, subject="requests", level="organization_policy",
                             text="Policy text.", adopted_by="coo", resolution_id=policy, binds="*")
    item = governed.history(governed_conn, "requests")[0]
    assert item["id"] == item_id
    assert item["adopted_by"] == "coo" and item["adopted_at"]
    assert item["resolution_id"] == policy
    assert item["level"] == "organization_policy"


# --- the things it will not pretend to do -------------------------------------------

def test_it_does_not_claim_to_detect_a_contradiction_in_the_words(governed_conn):
    """The limit, asserted so it cannot quietly be believed away.

    A procedure that contradicts its policy in plain English is adopted without
    complaint, because nothing here reads the text. `effective()` still returns
    the policy — precedence holds — but no conflict is reported, and the module
    says so rather than letting a green suite imply otherwise."""
    policy = _enact(governed_conn, "organization_policy")
    procedure = _enact(governed_conn, "procedure")
    governed.adopt(governed_conn, subject="requests", level="organization_policy",
                   text="Requests must carry acceptance criteria.", adopted_by="coo",
                   resolution_id=policy, binds="*")
    governed.adopt(governed_conn, subject="requests", level="procedure",
                   text="Requests need no acceptance criteria.", adopted_by="coo",
                   resolution_id=procedure, binds="*")

    assert governed.conflicts(governed_conn) == [], "no contradiction detection is claimed"
    assert governed.effective(governed_conn, "requests").startswith("Requests must")


def test_the_speaker_reports_an_unsettled_subject(governed_conn):
    """A conflict nobody can see is a conflict nobody escalates.

    Addendum 46 §5 says conflicts are escalated *through governance*, and
    governance's voice is the Speaker (§124). So a subject with two equal
    authorities appears in the Speaker's report and in the words it says —
    read-only, because settling it is a vote and the Speaker does not vote."""
    from agents import speaker
    for text in ("One.", "Two."):
        governed_conn.execute(
            "INSERT INTO governed_items (adopted_at, subject, level, text, adopted_by)"
            " VALUES ('2026-01-01T00:00:00+00:00', 'requests', 'knowledge', ?, 'explorer')",
            (text,))
    report = speaker.compose_report(governed_conn)
    assert [c["subject"] for c in report["governance_conflicts"]] == ["requests"]
    assert "equal authority" in report["says"] and "requests" in report["says"]
