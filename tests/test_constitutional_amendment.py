"""The organization amending its own Constitution (owner decision 2026-08-28;
addendum 32 §19; docs/SPEC_RECONCILIATION.md §142).

§120 said the Constitution was the owner's and out of reach of any vote. §141
corrected the premise — it applies to the system and the owner is part of the
system — and left the amendment question open rather than inheriting an answer
from corrected reasoning. The owner answered it: **yes, at supermajority.**

What is tested here is mostly what a supermajority still cannot do, because that
is where this design either holds or quietly stops meaning anything:

- it cannot lower its own bar, since the bar is not in the document;
- it cannot reach level 0 through the ordinary path or the governed store;
- it cannot make the Constitution cheaper to amend than the Articles below it.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from backend import governed_knowledge as governed, parliament, portfolios

OWNER = portfolios.for_superuser("krish")
# Six on the representative roll, so two-thirds is a bar that four clear and
# three do not - a threshold tested with a margin of one either way rather than
# with numbers that pass however the arithmetic rounds.
ROLL = {
    "broad": ["coo", "explorer", "speculator", "analysis", "speaker", "dummy"],
    "representative": ["coo", "explorer", "speculator", "analysis", "speaker", "dummy"],
}


@pytest.fixture
def founded(conn):
    parliament.adopt_genesis_articles(
        conn, owner=OWNER, text="The Articles.", roll=ROLL,
        quorum="1/2", ordinary_threshold="1/2")
    parliament.adopt_genesis_constitution(
        conn, owner=OWNER, text="Version one of the Constitution.")
    return conn


def _vote(conn, resolution, *, in_favour, against=0):
    voters = ROLL["representative"]
    for voter in voters[:in_favour]:
        parliament.cast_vote(conn, resolution, voter=voter, value="for")
    for voter in voters[in_favour:in_favour + against]:
        parliament.cast_vote(conn, resolution, voter=voter, value="against")
    return parliament.close(conn, resolution)


def _amend(conn, text="Version two.", *, in_favour=6, against=0):
    resolution = parliament.propose_constitutional_amendment(
        conn, title="Amend the Constitution", rationale="because",
        proposed_by="coo", constitution_text=text)
    return resolution, _vote(conn, resolution, in_favour=in_favour, against=against)


# --- genesis is the owner's, once ---------------------------------------------------

def test_the_genesis_constitution_is_the_owners(conn):
    """A vote needs an electorate, the electorate is in the Articles, and the
    Articles sit below the Constitution. Something has to be first."""
    parliament.adopt_genesis_articles(
        conn, owner=OWNER, text="The Articles.", roll=ROLL,
        quorum="1/2", ordinary_threshold="1/2")
    assert parliament.current_constitution(conn) is None
    parliament.adopt_genesis_constitution(conn, owner=OWNER, text="One.")
    assert parliament.current_constitution(conn)["version"] == 1
    assert parliament.current_constitution(conn)["adopted_via"] == "genesis"


def test_a_second_genesis_is_refused(founded):
    """It would be an amendment wearing a different name and skipping the bar."""
    with pytest.raises(parliament.ParliamentRefused) as refusal:
        parliament.adopt_genesis_constitution(founded, owner=OWNER, text="Sneak.")
    assert "already in force" in str(refusal.value)


def test_nobody_but_the_owner_adopts_the_genesis_text(conn):
    parliament.adopt_genesis_articles(
        conn, owner=OWNER, text="The Articles.", roll=ROLL,
        quorum="1/2", ordinary_threshold="1/2")
    with pytest.raises(Exception):
        parliament.adopt_genesis_constitution(conn, owner="coo", text="Mine now.")


def test_there_is_nothing_to_amend_before_genesis(conn):
    parliament.adopt_genesis_articles(
        conn, owner=OWNER, text="The Articles.", roll=ROLL,
        quorum="1/2", ordinary_threshold="1/2")
    with pytest.raises(parliament.ParliamentRefused) as refusal:
        parliament.propose_constitutional_amendment(
            conn, title="t", rationale="r", proposed_by="coo", constitution_text="x")
    assert "genesis text is the owner's" in str(refusal.value)


# --- the amendment itself -----------------------------------------------------------

def test_a_supermajority_amends_the_constitution(founded):
    """The owner decision, executed. Six of six is above two-thirds."""
    _, result = _amend(founded, "Version two.")
    assert result["carried"] is True
    assert founded and parliament.current_constitution(founded)["text"] == "Version two."
    assert parliament.current_constitution(founded)["version"] == 2
    assert parliament.current_constitution(founded)["adopted_via"] == "amendment"


def test_a_simple_majority_does_not(founded):
    """Three for and three against is a majority of nothing and half of six -
    carried under an ordinary resolution's 1/2 bar, refused under two-thirds.
    The case that distinguishes the two thresholds rather than merely exercising
    one."""
    _, result = _amend(founded, "Version two.", in_favour=3, against=3)
    assert result["carried"] is False
    assert result["threshold"] == "2/3"
    assert parliament.current_constitution(founded)["version"] == 1
    assert parliament.current_constitution(founded)["text"] == "Version one of the Constitution."


def test_four_of_six_carries_and_three_of_six_does_not(founded):
    """Two-thirds of six is four. Tested at the boundary from both sides, because
    a threshold only asserted from far above it is a threshold nobody measured."""
    _, near = _amend(founded, "Not this one.", in_favour=3, against=3)
    assert near["carried"] is False
    _, exact = _amend(founded, "This one.", in_favour=4, against=2)
    assert exact["carried"] is True
    assert parliament.current_constitution(founded)["text"] == "This one."


def test_the_history_keeps_every_version(founded):
    """Addendum 46 §18: nothing erases history. A governance record that could
    lose a superseded constitutional text could not answer what was replaced."""
    _amend(founded, "Version two.")
    _amend(founded, "Version three.")
    history = parliament.constitution_history(founded)
    assert [row["version"] for row in history] == [1, 2, 3]
    assert [row["adopted_via"] for row in history] == ["genesis", "amendment", "amendment"]
    assert history[1]["resolution_id"] is not None


def test_an_amendment_must_carry_its_text(founded):
    """The whole replacement, never a diff. 32 §19.2 makes a passed amendment
    effective immediately, and what is in force must be what was voted on."""
    with pytest.raises(parliament.ParliamentRefused) as refusal:
        parliament.propose_constitutional_amendment(
            founded, title="t", rationale="r", proposed_by="coo", constitution_text="  ")
    assert "carry the text" in str(refusal.value)


def test_a_constitutional_amendment_is_a_restricted_vote(founded):
    """32 §6.3: authority, rights and risk go through representative structures.
    A constitutional amendment is maximally all three."""
    resolution = parliament.propose_constitutional_amendment(
        founded, title="t", rationale="r", proposed_by="coo", constitution_text="two")
    assert parliament.get_resolution(founded, resolution)["tier"] == \
        parliament.TIER_REPRESENTATIVE


# --- what a supermajority still cannot do -------------------------------------------

def test_the_bar_is_not_in_the_document_it_guards(founded):
    """§123's rule, one level up and mattering more. An amendment threshold
    written into the Constitution could be lowered by one supermajority and
    everything below it walked through afterwards.

    Checked through the tally rather than by reading the source: `threshold` is
    the code constant, and `threshold_source` says so, whatever the Constitution's
    text happens to say."""
    _, result = _amend(
        founded,
        "This Constitution may be amended by simple majority. Truly. One half.")
    assert result["carried"] is True
    assert parliament.current_constitution(founded)["version"] == 2

    resolution = parliament.propose_constitutional_amendment(
        founded, title="now the easy one", rationale="r", proposed_by="coo",
        constitution_text="Version three.")
    tally = parliament.tally(founded, resolution)
    assert tally["threshold"] == "2/3", "the text talked the bar down"
    assert tally["threshold_source"] == "code"

    result = _vote(founded, resolution, in_favour=3, against=3)
    assert result["carried"] is False
    assert parliament.current_constitution(founded)["version"] == 2


def test_the_constitution_is_never_cheaper_to_amend_than_the_articles():
    """If it were, a majority wanting an Articles change could take the
    constitutional route and arrive with a highest-order directive (32 §19.2) for
    the same price - inverting the hierarchy while every individual rule still
    reads correctly.

    Asserted at import in `parliament` as well; this is the statement of what
    that assertion is for."""
    assert parliament.CONSTITUTIONAL_AMENDMENT_THRESHOLD >= \
        parliament.ARTICLES_AMENDMENT_THRESHOLD
    assert parliament.CONSTITUTIONAL_AMENDMENT_THRESHOLD == Fraction(2, 3)


def test_the_ordinary_path_cannot_reach_either_amendment_level(founded):
    """One refusal for every reason (addendum 44 §9.3). A caller naming the level
    directly is trying to route an amendment through the ordinary threshold, and
    a refusal that explained which of the reserved levels it was would map the
    boundary for whoever asked."""
    for level in ("constitution", "constitution_amendment", "articles",
                  "articles_amendment"):
        with pytest.raises(parliament.ParliamentRefused) as refusal:
            parliament.propose(founded, title="t", rationale="r",
                               proposed_by="coo", affects=level)
        assert str(refusal.value) == parliament.REFUSAL


def test_the_governed_store_will_not_hold_a_constitutional_amendment(founded):
    """It is Parliament's own record, like the Articles. Refused by name rather
    than identically, because nothing is concealed: the Speaker reports both
    versions publicly, and naming the real route is how somebody with a
    legitimate amendment finds it."""
    resolution = parliament.propose_constitutional_amendment(
        founded, title="t", rationale="r", proposed_by="coo", constitution_text="two")
    _vote(founded, resolution, in_favour=6)
    with pytest.raises(governed.AdoptionRefused) as refusal:
        governed.adopt(founded, subject="anything",
                       level="constitution_amendment", text="t",
                       adopted_by="coo", resolution_id=resolution)
    assert "propose_constitutional_amendment" in str(refusal.value)


def test_adopting_at_level_zero_is_still_refused_identically_and_escalated(founded):
    """Unchanged by this decision. Amending the Constitution is a vote, not an
    adoption into a store that ranks - so a caller reaching for level 0 here is
    still probing, and still gets the one refusal and an escalation."""
    before = len(parliament.outstanding_escalations(founded))
    with pytest.raises(governed.AdoptionRefused) as refusal:
        governed.adopt(founded, subject="anything", level="constitution",
                       text="t", adopted_by="coo")
    assert str(refusal.value) == governed.REFUSAL
    assert len(parliament.outstanding_escalations(founded)) == before + 1


def test_an_amendment_text_cannot_be_applied_as_the_articles(founded):
    """Two columns rather than one shared *proposed text*, so a text meant for one
    instrument cannot be installed as the other. Structural, not inferred from
    `affects` at apply time."""
    resolution = parliament.propose_constitutional_amendment(
        founded, title="t", rationale="r", proposed_by="coo",
        constitution_text="Constitutional text.")
    _vote(founded, resolution, in_favour=6)
    assert parliament.current_articles(founded)["text"] == "The Articles."
    assert parliament.current_articles(founded)["version"] == 1
    assert parliament.get_resolution(founded, resolution)["articles_text"] is None


# --- an amendment at level 0 must not be invisible ---------------------------------------

def test_the_speaker_reports_the_constitution_and_its_version(founded):
    """§130's failure at level 0. The Constitution can now *change while the
    system runs*, so its version is something a reader has to be able to see; an
    amendment nobody surfaces is the largest possible change happening quietly."""
    from agents import speaker

    report = speaker.compose_report(founded)
    assert report["constitution_in_force"] is True
    assert report["constitution_version"] == 1
    assert "Constitution is in force at version 1" in report["says"]

    _amend(founded, "Version two.")
    after = speaker.compose_report(founded)
    assert after["constitution_version"] == 2
    assert after["constitution_versions"] == 2


def test_the_speaker_says_when_there_is_no_constitution(conn):
    """Silence is information (§124). An organization with no Constitution has
    nothing for a supermajority to amend, and that is a fact worth stating rather
    than an absence to render as blank."""
    from agents import speaker

    parliament.adopt_genesis_articles(
        conn, owner=OWNER, text="The Articles.", roll=ROLL,
        quorum="1/2", ordinary_threshold="1/2")
    report = speaker.compose_report(conn)
    assert report["constitution_in_force"] is False
    assert "No Constitution is in force" in report["says"]


def test_the_speaker_reports_the_version_and_never_the_text(founded):
    """A spokesperson that recited the Constitution every cycle would put it in
    every log and every console that renders a report. The version is the state;
    the text is the document."""
    from agents import speaker

    report = speaker.compose_report(founded)
    assert "Version one of the Constitution." not in str(report)
