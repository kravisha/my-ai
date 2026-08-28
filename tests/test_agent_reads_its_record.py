"""An agent reading its own record and acting on it (TQ-103;
docs/SPEC_RECONCILIATION.md §146; organization-model declared gap 1).

TQ-102 built the read path and the right, and nothing used either. This is the
increment that turns them into behaviour, so the tests are written against
**§118's trap**: an agent that reads its grades and changes nothing has closed
declared gap 1 on paper. Every test below requires the reading to *appear* in
what the agent does.

The finding that made a deterministic ground possible is at §146:
`agents/analysis.py` records the analysis and the grade under one identity, so
**every grade this organization has ever produced was written by its own
producer** — nine of nine in the last full run before this was written.
"""

from __future__ import annotations

import pytest

from agents import analysis
from backend import appeal, fi_db

PRODUCER = "analysis-1"
PEER = "analysis-2"


def _register(conn, identity, role="analysis"):
    fi_db.register_agent(conn, identity, role, pid=1000 + len(identity))


def _self_graded(conn, *, identity=PRODUCER, worth=False, score=0.2) -> int:
    """The condition this system actually produces: one identity records the
    analysis and the grade. Built through the production API (§128)."""
    report = fi_db.enqueue_report(
        conn, identity, "t0", "lead", "SYN1", summary="s", evidence_ids=[])
    result = fi_db.record_analysis_result(
        conn, identity, "t0", report, "SYN1", "thesis", "e", 0.5, "some")
    return fi_db.record_grade(
        conn, identity, "t0", report, result, score, score, score, worth, score, "thin")


def _independently_graded(conn, *, producer=PRODUCER, grader=PEER, worth=False) -> int:
    report = fi_db.enqueue_report(
        conn, producer, "t0", "lead", "SYN1", summary="s", evidence_ids=[])
    result = fi_db.record_analysis_result(
        conn, producer, "t0", report, "SYN1", "thesis", "e", 0.5, "some")
    return fi_db.record_grade(
        conn, grader, "t0", report, result, .1, .1, .1, worth, .1, "poor")


@pytest.fixture
def solo(conn):
    _register(conn, PRODUCER)
    return conn


# --- the ground is deterministic, and it is not vacuous --------------------------------

def test_a_self_graded_unfavourable_ruling_is_contestable(solo):
    """Both facts are in the data and neither is an opinion: the grader was the
    producer, and the grade declared the work not worth the compute."""
    grade = _self_graded(solo, worth=False)
    contestable = appeal.contestable_by(solo, PRODUCER)
    assert [c["id"] for c in contestable] == [grade]
    assert "no independent information" in contestable[0]["grounds"]


def test_a_self_graded_favourable_ruling_is_not_a_grievance(solo):
    """The owner's words are the right to appeal an *unfavourable* ruling. A
    generous self-evaluation is still improper, and it is not something the agent
    it favoured has standing to complain about."""
    _self_graded(solo, worth=True)
    assert appeal.contestable_by(solo, PRODUCER) == []


def test_an_independently_graded_ruling_is_not_contestable_on_this_ground(solo):
    """Whether the score was *fair* is a judgement, and an agent appealing every
    low score would be appealing rather than disagreeing."""
    _register(solo, PEER)
    _independently_graded(solo)
    assert appeal.contestable_by(solo, PRODUCER) == []


def test_a_contested_ruling_is_not_offered_again(solo):
    """An agent calling this every cycle converges rather than refiling."""
    grade = _self_graded(solo, worth=False)
    appeal.file_appeal(solo, ruling_kind="grade", ruling_id=grade,
                       appellant=PRODUCER, grounds="g")
    assert appeal.contestable_by(solo, PRODUCER) == []


# --- the reading appears in what the agent does (§118) ----------------------------------

def test_the_agents_cycle_files_an_appeal_rather_than_merely_reading(solo):
    """**The property §118 demands.** An agent that consulted its record and did
    nothing would look identical to one that never looked."""
    grade = _self_graded(solo, worth=False)
    assert appeal.summary(solo)["filed"] == 0

    analysis._contest_own_rulings(solo, PRODUCER)

    assert appeal.summary(solo)["filed"] == 1, "the agent read its record and changed nothing"
    row = appeal.require(solo, 1)
    assert row["appellant"] == PRODUCER and row["ruling_id"] == grade


def test_a_cycle_with_nothing_contestable_files_nothing(solo):
    """The other half. A cycle that always filed something would be an agent
    appealing on a schedule rather than on a ground."""
    _self_graded(solo, worth=True)
    assert analysis._contest_own_rulings(solo, PRODUCER) == 0
    assert appeal.summary(solo)["filed"] == 0


def test_the_cycle_is_idempotent_across_cycles(solo):
    _self_graded(solo, worth=False)
    assert analysis._contest_own_rulings(solo, PRODUCER) == 1
    assert analysis._contest_own_rulings(solo, PRODUCER) == 0
    assert appeal.summary(solo)["filed"] == 1


# --- a peer hears it, and the finding is about independence -----------------------------

def test_a_peer_hears_what_the_author_may_not(solo):
    grade = _self_graded(solo, worth=False)
    analysis._contest_own_rulings(solo, PRODUCER)
    assert analysis._hear_peer_appeals(solo, PRODUCER) == 0, (
        "the appellant heard its own appeal")

    _register(solo, PEER)
    assert analysis._hear_peer_appeals(solo, PEER) == 1
    row = appeal.require(solo, 1)
    assert row["heard_by"] == PEER
    assert row["outcome"] == appeal.OUTCOME_OVERTURNED
    assert row["ruling_id"] == grade


def test_the_finding_reaches_independence_and_says_it_is_not_about_quality(solo):
    """**Overturned does not mean the work was good.** A reader inferring quality
    from a true record would have learned something false, so the rationale says
    what the finding covers."""
    _self_graded(solo, worth=False)
    analysis._contest_own_rulings(solo, PRODUCER)
    _register(solo, PEER)
    analysis._hear_peer_appeals(solo, PEER)

    rationale = appeal.require(solo, 1)["rationale"]
    assert "no independent judgement" in rationale
    assert "says nothing about the quality" in rationale
    assert "ungraded rather than well graded" in rationale


def test_a_ground_that_no_longer_holds_is_upheld(solo):
    """The peer re-checks rather than rubber-stamping. Upheld here means the
    ruling *was* independent, which is a finding and not a formality."""
    _register(solo, PEER)
    grade = _independently_graded(solo)
    appeal.file_appeal(solo, ruling_kind="grade", ruling_id=grade,
                       appellant=PRODUCER, grounds="I believe it was self-evaluated")

    finding = appeal.independence_finding(solo, 1)
    assert finding["outcome"] == appeal.OUTCOME_UPHELD
    assert "did not produce the work it graded" in finding["rationale"]


def test_a_peer_never_hears_its_own_ruling(solo):
    """Structural, from `eligible_adjudicators` rather than from a check written
    in the agent."""
    _register(solo, PEER)
    _self_graded(solo, identity=PEER, worth=False)
    analysis._contest_own_rulings(solo, PEER)
    assert analysis._hear_peer_appeals(solo, PEER) == 0
    assert appeal.summary(solo)["heard"] == 0


# --- the COO staffs the peer a hearing needs ---------------------------------------------

def test_a_waiting_appeal_names_the_role_that_would_hear_it(solo):
    """46 §10's *work determines staffing*, as a signal whoever staffs can read."""
    assert appeal.roles_awaiting_a_peer(solo) == []
    _self_graded(solo, worth=False)
    analysis._contest_own_rulings(solo, PRODUCER)
    assert appeal.roles_awaiting_a_peer(solo) == ["analysis"]


def test_the_role_stops_awaiting_once_a_peer_exists(solo):
    _self_graded(solo, worth=False)
    analysis._contest_own_rulings(solo, PRODUCER)
    _register(solo, PEER)
    assert appeal.roles_awaiting_a_peer(solo) == []


def test_many_waiting_appeals_ask_for_one_peer_and_not_many(solo):
    """One agent hears all of them. A role per appeal would ask for five agents
    to do one agent's work, which is 46 §9's warning."""
    for _ in range(4):
        _self_graded(solo, worth=False)
    analysis._contest_own_rulings(solo, PRODUCER)
    assert appeal.summary(solo)["filed"] == 4
    assert appeal.roles_awaiting_a_peer(solo) == ["analysis"]


def test_the_coo_staffs_the_peer_a_hearing_needs(solo):
    """Read from what the COO actually enqueues rather than asserted about its
    intent: the directive is what staffs anybody."""
    from agents import coo

    _self_graded(solo, worth=False)
    analysis._contest_own_rulings(solo, PRODUCER)
    coo._ensure_baseline_population(solo)

    reasons = [
        (row["reason"] or "")
        for row in solo.fetchall("SELECT reason FROM coo_directives WHERE target_role = 'analysis'")
    ]
    assert any("appeal waiting" in reason for reason in reasons), (
        f"the COO did not staff the peer a hearing needs; reasons were {reasons}")


def test_the_coo_asks_for_nothing_extra_when_no_appeal_waits(solo):
    """The other half, and the one that keeps this from being a permanent
    headcount rise wearing an appeal's name."""
    from agents import coo

    coo._ensure_baseline_population(solo)
    reasons = [
        (row["reason"] or "")
        for row in solo.fetchall("SELECT reason FROM coo_directives WHERE target_role = 'analysis'")
    ]
    assert not any("appeal waiting" in reason for reason in reasons)
