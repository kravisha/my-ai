"""An agent reading its own record and acting on it (TQ-103, corrected at TQ-104;
docs/SPEC_RECONCILIATION.md §146, §147; organization-model declared gap 1).

**This file previously encoded a misreading, and the correction is the point.**

A grade is a ruling about the **upstream report** — `agents/analysis.py`'s own
prompt says *"a grade of the upstream report"*, and its scores are relevance,
novelty, evidence quality and worth-the-compute, which are properties of the lead
Explorer or Speculator filed. So the agent a grade judges is the **report's
filer**, and the agent that writes it is Analysis.

TQ-102 and TQ-103 read that party off `analysis_results.producer_identity` — the
agent that *wrote* the grade. Every conclusion drawn from it was inverted, and the
live demonstration at §146 was of a condition manufactured by the misreading.
§147 has the whole correction.

What the tests here now hold:

- the graded party is the report's filer, and only they may appeal;
- the grounds are facts in the record, and **neither currently fires**, which is
  the honest state rather than a gap;
- a peer of the *author* hears it, and the COO staffs one when it waits.
"""

from __future__ import annotations

import pytest

from agents import analysis, base
from backend import appeal, fi_db

FILER = "explorer-1"
GRADER = "analysis-1"
PEER = "analysis-2"


def _register(conn, identity, role):
    fi_db.register_agent(conn, identity, role, pid=1000 + len(identity))


def _graded(conn, *, filer=FILER, grader=GRADER, worth=False, rationale="thin") -> int:
    """The shape the organization actually produces: Explorer files, Analysis
    consumes and grades. Built through the production API (§128)."""
    report = fi_db.enqueue_report(
        conn, filer, "t0", "lead", "SYN1", summary="s", evidence_ids=[])
    result = fi_db.record_analysis_result(
        conn, grader, "t0", report, "SYN1", "thesis", "e", 0.5, "some")
    return fi_db.record_grade(
        conn, grader, "t0", report, result, .2, .2, .2, worth, .2, rationale)


def _grade_without_rationale(conn, *, filer=FILER, grader=GRADER) -> int:
    """A grade that got in before `record_grade` required a reason. Written
    directly because the production API now refuses it - which is the fix - and
    the ground still has to cover what is already on the record."""
    report = fi_db.enqueue_report(
        conn, filer, "t0", "lead", "SYN2", summary="s", evidence_ids=[])
    result = fi_db.record_analysis_result(
        conn, grader, "t0", report, "SYN2", "thesis", "e", 0.5, "some")
    return conn.execute_returning_id(
        "INSERT INTO grades (created_at, grader_identity, grader_spawned_at, report_id,"
        " analysis_result_id, relevance_score, novelty_score, evidence_quality_score,"
        " worth_the_compute, overall_score, rationale, schema_version)"
        " VALUES ('2026-08-28T00:00:00+00:00', ?, 't0', ?, ?, .2, .2, .2, 0, .2, NULL, 1)",
        (grader, report, result))


@pytest.fixture
def pipeline(conn):
    _register(conn, FILER, "explorer")
    _register(conn, GRADER, "analysis")
    return conn


# --- whose ruling it is -----------------------------------------------------------------

def test_the_graded_party_is_the_agent_that_filed_the_report(pipeline):
    """**The correction.** A grade judges the report, so it is the filer's
    record — not the record of the agent that wrote the grade."""
    grade = _graded(pipeline)
    assert [r["id"] for r in appeal.rulings_about(pipeline, FILER)] == [grade]
    assert appeal.rulings_about(pipeline, GRADER) == [], (
        "the agent that wrote the grade was handed it as a ruling about itself")


def test_a_ruling_survives_its_report_being_completed(pipeline):
    """A judged report moves to the archive, and an agent's right to know how its
    work was graded must survive the work finishing — §132's defect, in the place
    it would do the most damage."""
    grade = _graded(pipeline)
    report = pipeline.fetchone("SELECT report_id FROM grades WHERE id = ?", (grade,))["report_id"]
    fi_db.complete_report(pipeline, report, "analyzed",
                          handled_by_identity=GRADER, handled_by_spawned_at="t0")
    assert [r["id"] for r in appeal.rulings_about(pipeline, FILER)] == [grade]


def test_only_the_graded_party_may_appeal(pipeline):
    grade = _graded(pipeline)
    for impostor in (GRADER, "speculator-1"):
        with pytest.raises(appeal.AppealRefused) as refusal:
            appeal.file_appeal(pipeline, ruling_kind="grade", ruling_id=grade,
                               appellant=impostor, grounds="I disagree")
        assert "on another agent's behalf is an opinion" in str(refusal.value)

    filed = appeal.file_appeal(pipeline, ruling_kind="grade", ruling_id=grade,
                               appellant=FILER, grounds="The detector output was not read.")
    row = appeal.require(pipeline, filed)
    assert row["appellant"] == FILER and row["author"] == GRADER


# --- the grounds are facts, and they do not currently fire ------------------------------

def test_an_independently_graded_ruling_with_a_reason_is_not_contestable(pipeline):
    """**The honest state after the correction.** Grading here *is* independent —
    Analysis does not file reports — and `record_grade` now requires a reason. So
    both grounds are correctly aimed and neither occurs, which is why nothing
    files an appeal on a schedule."""
    _graded(pipeline, worth=False)
    assert appeal.contestable_by(pipeline, FILER) == []


def test_a_report_graded_by_its_own_filer_is_contestable(pipeline):
    """The first ground, correctly aimed. It does not arise in the current
    pipeline and it is the duty's actual question, so it is kept rather than
    dropped for being quiet."""
    _register(pipeline, "speculator-1", "speculator")
    grade = _graded(pipeline, filer="speculator-1", grader="speculator-1")
    contestable = appeal.contestable_by(pipeline, "speculator-1")
    assert [c["id"] for c in contestable] == [grade]
    assert "no independent information" in contestable[0]["grounds"]


def test_a_ruling_with_no_reason_is_contestable(pipeline):
    """The second ground, and the reachable one. `record_disposition` has always
    refused a ruling without a rationale; `record_grade` accepted one until
    TQ-104, so the ground covers what is already on the record."""
    grade = _grade_without_rationale(pipeline)
    contestable = appeal.contestable_by(pipeline, FILER)
    assert [c["id"] for c in contestable] == [grade]
    assert "nothing in it for the agent it judges to evaluate" in contestable[0]["grounds"]


def test_a_grade_can_no_longer_be_written_without_a_reason(pipeline):
    """The fix, rather than only the remedy. A grade is a ruling about somebody
    else's work and the agent it judges cannot answer a reason it was not given."""
    with pytest.raises(ValueError) as refusal:
        _graded(pipeline, rationale="   ")
    assert "must carry a rationale" in str(refusal.value)


def test_a_contested_ruling_is_not_offered_again(pipeline):
    grade = _grade_without_rationale(pipeline)
    appeal.file_appeal(pipeline, ruling_kind="grade", ruling_id=grade,
                       appellant=FILER, grounds="g")
    assert appeal.contestable_by(pipeline, FILER) == []


# --- the reading appears in what the agent does (§118) ----------------------------------

def test_reading_the_record_files_an_appeal_when_the_record_warrants_one(pipeline):
    """**§118's property.** An agent that consulted its record and did nothing
    would look identical to one that never looked."""
    grade = _grade_without_rationale(pipeline)
    assert appeal.summary(pipeline)["filed"] == 0

    assert base.read_own_record(pipeline, FILER) == 1

    assert appeal.summary(pipeline)["filed"] == 1
    assert appeal.require(pipeline, 1)["ruling_id"] == grade


def test_reading_a_clean_record_files_nothing(pipeline):
    """The other half. An agent that always filed something would be appealing on
    a schedule rather than on a ground."""
    _graded(pipeline, worth=False)
    assert base.read_own_record(pipeline, FILER) == 0
    assert appeal.summary(pipeline)["filed"] == 0


def test_reading_is_idempotent_across_cycles(pipeline):
    _grade_without_rationale(pipeline)
    assert base.read_own_record(pipeline, FILER) == 1
    assert base.read_own_record(pipeline, FILER) == 0
    assert appeal.summary(pipeline)["filed"] == 1


def test_every_agent_reads_its_own_record_not_only_the_graded_role():
    """It lives in the loop every agent shares. The charter owes this to *agents*,
    and discharging a protection about agents by serving the one role that
    happened to have rulings is the generalisation §147 warns against."""
    import inspect

    source = inspect.getsource(base.run_agent)
    assert "read_own_record(conn, identity)" in source, (
        "reading your own record is not in the loop every agent shares")


# --- a peer of the author hears it -------------------------------------------------------

def test_a_peer_of_the_author_hears_it_and_neither_party_can(pipeline):
    grade = _grade_without_rationale(pipeline)
    base.read_own_record(pipeline, FILER)

    assert analysis._hear_peer_appeals(pipeline, GRADER) == 0, "the author heard its own ruling"
    assert appeal.eligible_adjudicators(pipeline, 1) == []

    _register(pipeline, PEER, "analysis")
    assert appeal.eligible_adjudicators(pipeline, 1) == [PEER]
    assert analysis._hear_peer_appeals(pipeline, PEER) == 1
    assert appeal.require(pipeline, 1)["heard_by"] == PEER
    assert appeal.require(pipeline, 1)["ruling_id"] == grade


def test_the_finding_reaches_independence_and_says_it_is_not_about_quality(pipeline):
    """**Overturned does not mean the work was good.** A reader inferring quality
    from a true record would have learned something false."""
    _register(pipeline, "speculator-1", "speculator")
    _register(pipeline, "speculator-2", "speculator")
    _graded(pipeline, filer="speculator-1", grader="speculator-1")
    base.read_own_record(pipeline, "speculator-1")

    assert analysis._hear_peer_appeals(pipeline, "speculator-2") == 1
    rationale = appeal.require(pipeline, 1)["rationale"]
    assert "no independent judgement" in rationale
    assert "says nothing about the quality" in rationale


def test_a_ground_that_no_longer_holds_is_upheld(pipeline):
    """The peer re-checks rather than rubber-stamping. Upheld means the ruling
    *was* independent, which is a finding and not a formality."""
    grade = _graded(pipeline)
    appeal.file_appeal(pipeline, ruling_kind="grade", ruling_id=grade,
                       appellant=FILER, grounds="I believe it was self-evaluated")
    finding = appeal.independence_finding(pipeline, 1)
    assert finding["outcome"] == appeal.OUTCOME_UPHELD
    assert "did not file the report it graded" in finding["rationale"]


# --- the COO staffs the peer a hearing needs ---------------------------------------------

def test_a_waiting_appeal_names_the_authors_role(pipeline):
    """The peer must be able to make this kind of ruling, so it is the *author's*
    role that is short — not the appellant's."""
    assert appeal.roles_awaiting_a_peer(pipeline) == []
    _grade_without_rationale(pipeline)
    base.read_own_record(pipeline, FILER)
    assert appeal.roles_awaiting_a_peer(pipeline) == ["analysis"]

    _register(pipeline, PEER, "analysis")
    assert appeal.roles_awaiting_a_peer(pipeline) == []


def test_many_waiting_appeals_ask_for_one_peer(pipeline):
    """One agent hears all of them. A role per appeal would ask for five agents
    to do one agent's work (46 §9)."""
    for _ in range(3):
        _grade_without_rationale(pipeline)
    base.read_own_record(pipeline, FILER)
    assert appeal.summary(pipeline)["filed"] == 3
    assert appeal.roles_awaiting_a_peer(pipeline) == ["analysis"]


def test_the_coo_staffs_the_peer_a_hearing_needs(pipeline):
    """Read from what the COO actually enqueues: the directive is what staffs
    anybody."""
    from agents import coo

    _grade_without_rationale(pipeline)
    base.read_own_record(pipeline, FILER)
    coo._ensure_baseline_population(pipeline)

    reasons = [(row["reason"] or "") for row in pipeline.fetchall(
        "SELECT reason FROM coo_directives WHERE target_role = 'analysis'")]
    assert any("appeal waiting" in reason for reason in reasons), (
        f"the COO did not staff the peer a hearing needs; reasons were {reasons}")


def test_the_coo_asks_for_nothing_extra_when_no_appeal_waits(pipeline):
    """The half that keeps this from being a permanent headcount rise wearing an
    appeal's name."""
    from agents import coo

    coo._ensure_baseline_population(pipeline)
    reasons = [(row["reason"] or "") for row in pipeline.fetchall(
        "SELECT reason FROM coo_directives WHERE target_role = 'analysis'")]
    assert not any("appeal waiting" in reason for reason in reasons)
