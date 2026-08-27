"""An agent that actually reads the governed data (TQ-86; addendum 46 §3, §8;
docs/SPEC_RECONCILIATION.md §126).

The claim under test is addendum 46's central one — *a behavioral change does not
automatically imply a software change* — so the test that matters most is the one
that carries a resolution and watches behaviour change with no code edited:
`test_a_vote_changes_what_the_register_accepts_without_a_code_change`.

Everything else here defends the ways that claim can be true in appearance and
false in fact.
"""

from __future__ import annotations

import pytest

from backend import (governed_knowledge as governed, operating_context as context,
                     parliament, portfolios, register)

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
    resolution = parliament.propose(conn, title=title, rationale="r",
                                    proposed_by="coo", affects=level)
    tier = parliament.get_resolution(conn, resolution)["tier"]
    for voter in ROLL["representative" if tier == parliament.TIER_REPRESENTATIVE else "broad"]:
        parliament.cast_vote(conn, resolution, voter=voter, value="for")
    parliament.close(conn, resolution)
    return resolution


def _adopt_source_policy(conn, *, binds="*") -> int:
    return governed.adopt(
        conn, subject=register.SUBMISSION_SUBJECT, level="organization_policy",
        text="Every register submission names the source it came from.",
        adopted_by="coo", resolution_id=_enact(conn, "organization_policy"),
        binds=binds, requires={"kind": "required_fields", "fields": ["source_reference"]})


# --- the claim ----------------------------------------------------------------------

def test_a_vote_changes_what_the_register_accepts_without_a_code_change(governed_conn):
    """Addendum 46 §2, executed rather than described.

    Nothing in `register.file_entry` differs between the two halves of this test.
    What differs is an instrument the organization voted into force."""
    before = register.file_entry(governed_conn, "A thing", "want", "explorer",
                                 "because", filed_by="explorer")
    assert before

    _adopt_source_policy(governed_conn)

    with pytest.raises(ValueError) as refusal:
        register.file_entry(governed_conn, "Another thing", "want", "explorer",
                            "because", filed_by="explorer")
    assert "source_reference" in str(refusal.value)

    after = register.file_entry(governed_conn, "Third thing", "want", "explorer",
                                "because", source_reference="addendum 46 §39",
                                filed_by="explorer")
    assert after


def test_the_entry_records_what_it_was_filed_under(governed_conn):
    """Evidence, not a claim. An agent asserting it complied is TQ-80's defect in
    a new costume; a row carrying the instruments it was checked against is a
    fact somebody else can verify."""
    item = _adopt_source_policy(governed_conn)
    entry = register.file_entry(governed_conn, "A thing", "want", "explorer", "because",
                                source_reference="somewhere", filed_by="explorer")
    row = governed_conn.fetchone(
        "SELECT governed_by FROM strategic_register WHERE id = ?", (entry,))
    assert row["governed_by"] == str(item)


def test_an_unattributed_filing_is_recorded_as_ungoverned(governed_conn):
    """`filed_by=None` is not a bypass dressed as a default — it is the honest
    answer for a call with no accountable filer, and the row says so by carrying
    no authority rather than by carrying one it did not earn."""
    _adopt_source_policy(governed_conn)
    entry = register.file_entry(governed_conn, "A thing", "want", "somewhere", "because")
    row = governed_conn.fetchone(
        "SELECT governed_by FROM strategic_register WHERE id = ?", (entry,))
    assert row["governed_by"] is None


# --- an obligation nothing understands ----------------------------------------------

def test_an_obligation_nothing_understands_is_refused_at_adoption(governed_conn):
    """The worst available state is a rule that was proposed, debated, voted
    through, is reported as in force, and changes nobody's behaviour."""
    with pytest.raises(governed.AdoptionRefused) as refusal:
        governed.adopt(governed_conn, subject="requests", level="organization_policy",
                       text="t", adopted_by="coo",
                       resolution_id=_enact(governed_conn, "organization_policy"),
                       binds="*", requires={"kind": "interpret_the_prose"})
    assert "knows how to obey" in str(refusal.value)


def test_an_unintelligible_instrument_that_arrives_anyway_stops_the_work(governed_conn):
    """Constructed directly, because adoption prevents it — the read path has to
    hold on its own for the same reason §125 gave: rows arrive by routes the
    writer does not control."""
    governed_conn.execute(
        "INSERT INTO governed_items (adopted_at, subject, level, text, adopted_by, binds,"
        " requires) VALUES ('2026-01-01T00:00:00+00:00', 'requests', 'organization_policy',"
        " 't', 'coo', '*', '{\"kind\": \"telepathy\"}')")

    built = context.for_role(governed_conn, "explorer")
    assert [item["subject"] for item in built.unmet] == ["requests"]
    with pytest.raises(context.Ungovernable):
        context.require_understood(built)


def test_the_register_refuses_rather_than_filing_under_a_rule_it_cannot_obey(governed_conn):
    """Proceeding as though unbound is indistinguishable from the instrument
    never having been adopted, which would mean a vote had no effect anybody
    could see."""
    governed_conn.execute(
        "INSERT INTO governed_items (adopted_at, subject, level, text, adopted_by, binds,"
        " requires) VALUES ('2026-01-01T00:00:00+00:00', 'anything', 'organization_policy',"
        " 't', 'coo', 'explorer', '{\"kind\": \"telepathy\"}')")
    with pytest.raises(context.Ungovernable):
        register.file_entry(governed_conn, "A thing", "want", "explorer", "because",
                            filed_by="explorer")


# --- prose the code cannot enforce --------------------------------------------------

def test_an_instrument_without_a_machine_obligation_is_named_as_prose_only(governed_conn):
    """In force, binding, and not enforced by code. Said out loud, because a
    green run over an unenforced policy looks exactly like a green run over an
    enforced one."""
    governed.adopt(governed_conn, subject=register.SUBMISSION_SUBJECT,
                   level="organization_policy",
                   text="Submissions should be written thoughtfully.", adopted_by="coo",
                   resolution_id=_enact(governed_conn, "organization_policy"), binds="*")

    built = context.for_role(governed_conn, "explorer")
    assert [item["subject"] for item in built.prose_only] == [register.SUBMISSION_SUBJECT]

    verdict = context.check(governed_conn, "explorer", register.SUBMISSION_SUBJECT, {})
    assert verdict["governed"] is True and verdict["enforced"] is False
    assert "cannot enforce" in verdict["note"]


def test_an_ungoverned_subject_and_an_unenforced_one_are_different_answers(governed_conn):
    """Collapsing them would hide the case that matters: a rule exists and code
    is not checking it."""
    absent = context.check(governed_conn, "explorer", register.SUBMISSION_SUBJECT, {})
    assert absent["governed"] is False and "nothing governs" in absent["note"]


# --- who is bound -------------------------------------------------------------------

def test_a_governing_instrument_must_say_who_it_binds(governed_conn):
    """A policy that names nobody cannot be obeyed by anybody in particular, and
    cannot be checked at all."""
    with pytest.raises(governed.AdoptionRefused) as refusal:
        governed.adopt(governed_conn, subject="requests", level="organization_policy",
                       text="t", adopted_by="coo",
                       resolution_id=_enact(governed_conn, "organization_policy"))
    assert "say who" in str(refusal.value)


def test_material_that_binds_nobody_may_not_claim_to(governed_conn):
    """Knowledge informs; it does not bind. A `binds` on it would claim an
    authority the hierarchy already denies it."""
    with pytest.raises(governed.AdoptionRefused):
        governed.adopt(governed_conn, subject="requests", level="knowledge",
                       text="t", adopted_by="explorer", binds="explorer")


def test_an_instrument_binding_one_role_does_not_bind_another(governed_conn):
    _adopt_source_policy(governed_conn, binds="speculator")
    assert context.for_role(governed_conn, "speculator").instruments
    assert context.for_role(governed_conn, "explorer").instruments == ()
    # And the unbound role files as it always did.
    assert register.file_entry(governed_conn, "A thing", "want", "explorer",
                               "because", filed_by="explorer")


def test_precedence_holds_inside_a_context(governed_conn):
    """A context is built through the governed layer's own precedence, so a
    procedure superseded on a subject by a policy never reaches the agent —
    otherwise §125's rule would hold in the store and be lost on the way out."""
    governed.adopt(governed_conn, subject=register.SUBMISSION_SUBJECT, level="procedure",
                   text="Procedure.", adopted_by="coo",
                   resolution_id=_enact(governed_conn, "procedure"), binds="*",
                   requires={"kind": "required_fields", "fields": ["need_flag"]})
    _adopt_source_policy(governed_conn)

    built = context.for_role(governed_conn, "explorer")
    assert [item["level"] for item in built.instruments] == ["organization_policy"]
    assert built.obligation(register.SUBMISSION_SUBJECT)["fields"] == ["source_reference"]


# --- the fingerprint ----------------------------------------------------------------

def test_an_ungoverned_context_says_so_rather_than_carrying_an_empty_string(governed_conn):
    assert context.for_role(governed_conn, "explorer").fingerprint == "ungoverned"


def test_the_fingerprint_resolves_back_to_rows(governed_conn):
    """Ids rather than a hash: a fingerprint a reader can look up is worth more
    than one that only proves equality."""
    item = _adopt_source_policy(governed_conn)
    assert context.for_role(governed_conn, "explorer").fingerprint == str(item)


# --- the registry -------------------------------------------------------------------

def test_every_understood_obligation_names_code_that_can_obey_it():
    """`app/capability.py`'s rule, borrowed: a registry claiming a mechanism that
    does not exist would route work to nothing."""
    assert context.UNDERSTOOD_OBLIGATIONS
    for kind, handler in context.UNDERSTOOD_OBLIGATIONS.items():
        assert handler.kind == kind
        assert callable(handler.check_shape) and callable(handler.unmet_by)


def test_a_malformed_obligation_of_a_known_kind_is_still_refused(governed_conn):
    """Knowing the kind is not knowing the payload."""
    for bad in ({"kind": "required_fields"}, {"kind": "required_fields", "fields": []},
                {"kind": "required_fields", "fields": [""]}):
        with pytest.raises(governed.AdoptionRefused):
            governed.adopt(governed_conn, subject="requests", level="organization_policy",
                           text="t", adopted_by="coo",
                           resolution_id=_enact(governed_conn, "organization_policy",
                                                title=f"r{bad}"),
                           binds="*", requires=bad)
