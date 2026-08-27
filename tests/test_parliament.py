"""Parliament (TQ-81; addendum 32; addendum 46 §5, §6, §17;
docs/SPEC_RECONCILIATION.md §120, §123).

The tests are organised by the rule each one defends, because most of what this
module does is refuse - and a refusal nobody tests is a refusal that stops
happening the first time somebody finds it inconvenient.
"""

from __future__ import annotations

import inspect

import pytest

from backend import parliament, portfolios

OWNER = portfolios.for_superuser("krish")
ROLL = {"broad": ["coo", "explorer", "speculator", "analysis"],
        "representative": ["coo", "analysis"]}


def _genesis(conn, *, quorum="1/2", ordinary_threshold="1/2", roll=None):
    return parliament.adopt_genesis_articles(
        conn, owner=OWNER, text="The organization governs itself under these Articles.",
        roll=roll if roll is not None else ROLL,
        quorum=quorum, ordinary_threshold=ordinary_threshold)


@pytest.fixture
def governed(conn):
    _genesis(conn)
    return conn


# --- the Articles -------------------------------------------------------------------

def test_the_genesis_articles_come_from_the_owner_and_not_from_a_vote():
    """A vote needs an electorate, a quorum and a threshold. Until the Articles
    say what those are, the organization cannot decide anything - including what
    they should be. So the first text comes from level 0's holder."""
    from backend import fi_db
    conn = fi_db.get_connection(":memory:")
    fi_db.init_schema(conn)
    assert parliament.current_articles(conn) is None
    assert _genesis(conn) == 1
    articles = parliament.current_articles(conn)
    assert articles["adopted_via"] == "genesis"
    assert articles["adopted_by"] == "krish"
    assert articles["roll"] == ROLL


def test_a_second_genesis_is_refused(governed):
    """It would be an amendment wearing a different name and skipping the
    threshold."""
    with pytest.raises(parliament.ParliamentRefused):
        _genesis(governed)


def test_only_the_superuser_may_adopt_the_genesis_articles(conn):
    with pytest.raises(parliament.ParliamentRefused):
        parliament.adopt_genesis_articles(
            conn, owner=portfolios.for_client("someone"), text="x",
            roll=ROLL, quorum="1/2", ordinary_threshold="1/2")


def test_articles_with_nobody_on_the_roll_are_refused(conn):
    """A body that cannot vote is not a governance layer, it is a shape that
    looks like one."""
    with pytest.raises(parliament.ParliamentRefused):
        _genesis(conn, roll={"broad": [], "representative": []})


@pytest.mark.parametrize("quorum", ["0", "3/2", "not-a-fraction"])
def test_arithmetic_that_cannot_be_satisfied_is_refused_at_adoption(conn, quorum):
    with pytest.raises(parliament.ParliamentRefused):
        _genesis(conn, quorum=quorum)


# --- level 0 ------------------------------------------------------------------------

def test_a_proposal_aimed_at_the_constitution_is_refused_and_escalated(governed):
    """§120: level 0 is where the votes stop. The escalation ends at a person and
    nothing in this system can discharge it."""
    with pytest.raises(parliament.ParliamentRefused) as refusal:
        parliament.propose(governed, title="Amend the axioms", rationale="because",
                           proposed_by="coo", affects=parliament.LEVEL_CONSTITUTION)
    assert str(refusal.value) == parliament.REFUSAL
    outstanding = parliament.outstanding_escalations(governed)
    assert len(outstanding) == 1 and outstanding[0]["raised_by"] == "coo"


def test_an_unknown_level_gets_the_same_refusal_as_the_constitution(governed):
    """One refusal for every reason (addendum 44 §9.3). A caller who could tell
    *"that level does not exist"* from *"that level is out of reach"* could map
    the boundary by probing it, which is reading the governance state without
    being entitled to it."""
    with pytest.raises(parliament.ParliamentRefused) as unknown:
        parliament.propose(governed, title="x", rationale="y", proposed_by="coo",
                           affects="whatever")
    with pytest.raises(parliament.ParliamentRefused) as reserved:
        parliament.propose(governed, title="x", rationale="y", proposed_by="coo",
                           affects=parliament.LEVEL_CONSTITUTION)
    assert str(unknown.value) == str(reserved.value) == parliament.REFUSAL
    assert len(parliament.outstanding_escalations(governed)) == 2


def test_an_amendment_cannot_be_routed_through_the_ordinary_path(governed):
    """`articles` and `articles_amendment` are reachable only through
    `propose_amendment`, which sets the level itself. Naming one directly is an
    attempt to get the amendment's effect at the ordinary bar."""
    for level in ("articles", "articles_amendment"):
        with pytest.raises(parliament.ParliamentRefused):
            parliament.propose(governed, title="x", rationale="y", proposed_by="coo",
                               affects=level)


def test_nothing_can_be_proposed_before_the_articles_exist(conn):
    with pytest.raises(parliament.NoArticles):
        parliament.propose(conn, title="x", rationale="y", proposed_by="coo", affects="knowledge")


# --- who decides --------------------------------------------------------------------

def test_the_tier_is_decided_from_the_level_and_not_by_the_proposer(governed):
    """32 §6.3 lists what must go through representative structures. A proposer
    that chose its own electorate would be choosing its own odds."""
    restricted = parliament.propose(governed, title="A new law", rationale="r",
                                    proposed_by="coo", affects="law")
    ordinary = parliament.propose(governed, title="A note", rationale="r",
                                  proposed_by="coo", affects="knowledge")
    assert parliament.get_resolution(governed, restricted)["tier"] == parliament.TIER_REPRESENTATIVE
    assert parliament.get_resolution(governed, ordinary)["tier"] == parliament.TIER_BROAD


def test_a_voter_not_on_the_roll_for_this_tier_is_refused(governed):
    """Refused rather than counted-and-ignored: a tally that silently dropped
    ineligible votes would report a quorum it did not have."""
    resolution = parliament.propose(governed, title="A new law", rationale="r",
                                    proposed_by="coo", affects="law")
    # explorer votes in the broad tier and not in the representative one.
    with pytest.raises(parliament.ParliamentRefused):
        parliament.cast_vote(governed, resolution, voter="explorer", value="for")
    parliament.cast_vote(governed, resolution, voter="coo", value="for")


def test_one_voter_votes_once(governed):
    resolution = parliament.propose(governed, title="A note", rationale="r",
                                    proposed_by="coo", affects="knowledge")
    parliament.cast_vote(governed, resolution, voter="coo", value="for")
    with pytest.raises(parliament.ParliamentRefused):
        parliament.cast_vote(governed, resolution, voter="coo", value="against")


def test_an_unknown_vote_value_is_refused(governed):
    resolution = parliament.propose(governed, title="A note", rationale="r",
                                    proposed_by="coo", affects="knowledge")
    with pytest.raises(parliament.ParliamentRefused):
        parliament.cast_vote(governed, resolution, voter="coo", value="maybe")


# --- the arithmetic -----------------------------------------------------------------

def test_an_abstention_counts_toward_quorum_and_not_toward_the_threshold(governed):
    """Turning up and declining to decide is participation. Counting it as
    opposition would make abstaining a way of voting against without saying so."""
    resolution = parliament.propose(governed, title="A note", rationale="r",
                                    proposed_by="coo", affects="knowledge")
    parliament.cast_vote(governed, resolution, voter="coo", value="for")
    parliament.cast_vote(governed, resolution, voter="explorer", value="abstain")
    parliament.cast_vote(governed, resolution, voter="speculator", value="abstain")
    result = parliament.tally(governed, resolution)

    # Three of four turned out, so quorum is met - the abstentions did that.
    assert result["turnout"] == 3 and result["abstain"] == 2
    assert result["quorum_met"] is True

    # And the threshold sees one vote for, none against, so it carries.
    #
    # The two abstentions are what makes this discriminating: counted as decided
    # votes the ratio would be 1/3, below the 1/2 threshold, and this would fail.
    # An earlier version of this test used a single abstention and passed either
    # way - mutation testing found it, which is the second time here that a test
    # over data failed to test the rule that produced the data.
    assert result["carried"] is True


def test_a_vote_below_quorum_is_rejected_and_says_so(governed):
    resolution = parliament.propose(governed, title="A note", rationale="r",
                                    proposed_by="coo", affects="knowledge")
    parliament.cast_vote(governed, resolution, voter="coo", value="for")
    assert parliament.tally(governed, resolution)["quorum_met"] is False
    parliament.close(governed, resolution)
    row = parliament.get_resolution(governed, resolution)
    assert row["status"] == parliament.STATUS_REJECTED
    assert row["closed_reason"] == "quorum not met"


def test_a_resolution_that_is_not_open_cannot_be_closed_twice(governed):
    resolution = parliament.propose(governed, title="A note", rationale="r",
                                    proposed_by="coo", affects="knowledge")
    parliament.cast_vote(governed, resolution, voter="coo", value="for")
    parliament.cast_vote(governed, resolution, voter="explorer", value="for")
    parliament.close(governed, resolution)
    with pytest.raises(parliament.ParliamentRefused):
        parliament.close(governed, resolution)


def test_an_enacted_resolution_carries_the_provenance_addendum_46_asks_for(governed):
    """§17's questions, one column each: what changed, why, who proposed it, what
    evidence, who approved it, when it became active, what it replaced."""
    resolution = parliament.propose(
        governed, title="Structured requests", rationale="Informal ones cause confusion.",
        proposed_by="coo", affects="knowledge", evidence="three months of triage records")
    parliament.cast_vote(governed, resolution, voter="coo", value="for")
    parliament.cast_vote(governed, resolution, voter="explorer", value="for")
    parliament.close(governed, resolution)
    row = parliament.get_resolution(governed, resolution)
    assert row["title"] and row["rationale"] and row["proposed_by"] == "coo"
    assert row["evidence"] == "three months of triage records"
    assert row["became_active_at"] and row["approved_by"]
    assert row["status"] == parliament.STATUS_ENACTED


# --- amending the Articles ----------------------------------------------------------

def test_an_amendment_is_measured_against_the_threshold_in_code(governed):
    """The Articles carry the ordinary threshold. They do not carry the one for
    amending themselves - an instrument that could lower its own amendment bar by
    ordinary vote has no amendment bar at all."""
    amendment = parliament.propose_amendment(
        governed, title="Add a clause", rationale="r", proposed_by="coo",
        articles_text="Version two of the Articles.")
    result = parliament.tally(governed, amendment)
    assert result["threshold"] == str(parliament.ARTICLES_AMENDMENT_THRESHOLD)
    assert result["threshold_source"] == "code"

    ordinary = parliament.propose(governed, title="A note", rationale="r",
                                  proposed_by="coo", affects="knowledge")
    assert parliament.tally(governed, ordinary)["threshold_source"] == "articles"


def test_a_bare_majority_does_not_carry_an_amendment(governed):
    """Two voters on the representative roll: one for, one against is a majority
    of nothing and two-thirds of nothing."""
    amendment = parliament.propose_amendment(
        governed, title="Add a clause", rationale="r", proposed_by="coo",
        articles_text="Version two.")
    parliament.cast_vote(governed, amendment, voter="coo", value="for")
    parliament.cast_vote(governed, amendment, voter="analysis", value="against")
    assert parliament.close(governed, amendment)["carried"] is False
    assert parliament.current_articles(governed)["version"] == 1


def test_a_carried_amendment_adds_a_version_and_keeps_the_old_one(governed):
    amendment = parliament.propose_amendment(
        governed, title="Add a clause", rationale="r", proposed_by="coo",
        articles_text="Version two of the Articles.")
    parliament.cast_vote(governed, amendment, voter="coo", value="for")
    parliament.cast_vote(governed, amendment, voter="analysis", value="for")
    assert parliament.close(governed, amendment)["carried"] is True

    current = parliament.current_articles(governed)
    assert current["version"] == 2
    assert current["adopted_via"] == "amendment"
    assert current["resolution_id"] == amendment
    assert current["text"] == "Version two of the Articles."
    # Addendum 46 §18: nothing about a change erases history.
    history = parliament.articles_history(governed)
    assert [h["version"] for h in history] == [1, 2]
    assert history[0]["adopted_via"] == "genesis"


def test_articles_text_claiming_its_own_amendment_threshold_does_not_get_one(governed):
    """Data has no authority over the mechanism.

    An amendment whose text says the bar is one third still faces two thirds,
    because the tally never reads a threshold out of the Articles for an
    amendment. This is §120's argument one level down: a rule that a vote can
    reach is not a rule."""
    amendment = parliament.propose_amendment(
        governed, title="Lower the bar", rationale="r", proposed_by="coo",
        articles_text="Amendments require one third. ordinary_threshold: 1/3")
    parliament.cast_vote(governed, amendment, voter="coo", value="for")
    parliament.cast_vote(governed, amendment, voter="analysis", value="for")
    parliament.close(governed, amendment)

    following = parliament.propose_amendment(
        governed, title="And again", rationale="r", proposed_by="coo",
        articles_text="Version three.")
    assert parliament.tally(governed, following)["threshold"] == str(
        parliament.ARTICLES_AMENDMENT_THRESHOLD)


def test_an_amendment_needs_articles_to_amend(conn):
    with pytest.raises(parliament.NoArticles):
        parliament.propose_amendment(conn, title="x", rationale="r", proposed_by="coo",
                                     articles_text="text")


# --- escalations nothing inside can clear -------------------------------------------

def test_an_escalation_needs_the_owner_and_a_record_to_close(governed):
    escalation = parliament.escalate(governed, summary="something", raised_by="coo")
    with pytest.raises(parliament.ParliamentRefused):
        parliament.record_owner_decision(
            governed, escalation, owner=portfolios.for_client("someone"),
            record_reference="§123")
    with pytest.raises(parliament.ParliamentRefused):
        parliament.record_owner_decision(governed, escalation, owner=OWNER, record_reference="")
    parliament.record_owner_decision(governed, escalation, owner=OWNER,
                                     record_reference="SPEC_RECONCILIATION §123")
    assert parliament.outstanding_escalations(governed) == []


def test_nothing_else_in_the_module_can_clear_an_escalation():
    """Structural, because this is the property that makes the queue mean
    anything. If a second function could write `decided_at`, an agent would have
    a way to make a level-0 escalation disappear without the owner ever seeing
    it."""
    source = inspect.getsource(parliament)
    writers = [line for line in source.splitlines()
               if "owner_escalations SET" in line or "DELETE FROM owner_escalations" in line]
    assert len(writers) == 1, f"more than one path writes a terminal state: {writers}"
    assert "decided_at = ?" in writers[0]
    assert "decided_at = ?" in inspect.getsource(parliament.record_owner_decision)


def test_there_is_no_resolve_or_dismiss(governed):
    """Named absences. A `dismiss` added later would look like tidying and would
    be the whole guarantee, removed."""
    for forbidden in ("resolve_escalation", "dismiss_escalation", "clear_escalations",
                      "purge_escalations"):
        assert not hasattr(parliament, forbidden)


# --- what it says about itself ------------------------------------------------------

def test_the_summary_names_what_is_still_unbuilt(governed):
    """Addendum 32 is not finished, and a status surface reporting a working vote
    without saying so would read as though it were."""
    state = parliament.summary(governed)
    assert state["articles_in_force"] is True and state["articles_version"] == 1
    assert set(state["not_built"]) == {"elections", "ministers", "committees", "weekly_session"}


def test_the_coo_is_told_which_parts_of_parliament_are_still_missing(conn):
    """The re-aimed half of `test_digest_names_what_is_deliberately_unbuilt`.

    That test asserted the digest called parliament *deferred*, which was true
    until TQ-81. The rule it defends — rule 3 of the COO's prompt, that absence
    looks identical to quiet from inside a snapshot — did not change, so the
    tripwire moved to the new absence rather than being deleted (§105, §110,
    §116). Addendum 32's elections, ministers, committees and weekly session are
    still unbuilt, and a COO told only that parliament exists would report a
    finished governance layer."""
    from backend import coo_chat
    unbuilt = coo_chat.state_digest(conn)["not_built_yet"]["parliament"]
    for absent in ("elections", "ministers", "committees", "weekly session"):
        assert absent in unbuilt
    # And it must point at the Speaker rather than invite the COO to describe
    # Parliament from the digest itself (§124).
    assert "Speaker" in unbuilt and "/console/overview" in unbuilt


def test_before_adoption_the_machinery_exists_and_governs_nothing(conn):
    """Different from the machinery being absent, and the distinction is the one
    the old `/health` sentence could not make."""
    state = parliament.summary(conn)
    assert state["articles_in_force"] is False
    assert state["articles_version"] is None
