"""Tests for the knowledge store (constitution §3, addendum 13 §9-§10).

Gap analysis §4.1's distinction is the thing under test: every other table
records *what happened*, this one records *what is believed*. The tests that
matter are the ones asserting it does not become either a duplicate of the
event tables or a pile of repeated assertions.
"""

from unittest.mock import MagicMock

import pytest

from backend import fi_db


def test_a_record_must_say_who_produced_it(conn):
    """A lesson from COO's health check and one from a human are different
    claims. A store that could not say which is which would be a pile of
    assertions rather than knowledge."""
    record_id = fi_db.record_knowledge(
        conn, fi_db.KNOWLEDGE_LESSON, "Coordinated posting precedes poor grades.",
        recorded_by="coo", subject="pump_channel",
    )
    assert fi_db.list_knowledge(conn)[0]["recorded_by"] == "coo"
    assert fi_db.list_knowledge(conn)[0]["id"] == record_id


def test_the_same_statement_is_not_relearned(conn):
    """COO re-evaluates health every cycle. Without this guard one stale lens
    would generate an identical lesson every second until the store was noise."""
    fi_db.record_knowledge(conn, fi_db.KNOWLEDGE_LESSON, "X failed.", recorded_by="coo")
    assert fi_db.knowledge_exists(conn, fi_db.KNOWLEDGE_LESSON, "X failed.")
    assert not fi_db.knowledge_exists(conn, fi_db.KNOWLEDGE_OPEN_QUESTION, "X failed.")


def test_superseding_preserves_the_belief_that_was_wrong(conn):
    """A belief that turned out wrong is itself knowledge, and the trail from it
    to its replacement is the part worth keeping (addendum 13 §9)."""
    old_id = fi_db.record_knowledge(conn, fi_db.KNOWLEDGE_LESSON, "Threshold 2.0 works.", recorded_by="coo")
    new_id = fi_db.record_knowledge(conn, fi_db.KNOWLEDGE_LESSON, "Threshold 2.0 fails in high vol.", recorded_by="coo")
    fi_db.supersede_knowledge(conn, old_id, replacement_id=new_id)

    assert [r["id"] for r in fi_db.list_knowledge(conn)] == [new_id]  # active view
    history = fi_db.list_knowledge(conn, status=None)
    superseded = [r for r in history if r["id"] == old_id][0]
    assert superseded["status"] == fi_db.KNOWLEDGE_SUPERSEDED
    assert superseded["superseded_by"] == new_id
    assert superseded["statement"] == "Threshold 2.0 works."  # not deleted


def test_a_resolved_question_is_distinct_from_a_superseded_belief(conn):
    """A resolved question was settled; a superseded belief was wrong. Merging
    them would lose which of those happened."""
    question_id = fi_db.record_knowledge(conn, fi_db.KNOWLEDGE_OPEN_QUESTION, "Why did SYN1 move?", recorded_by="analysis-1")
    fi_db.resolve_knowledge(conn, question_id)
    record = fi_db.list_knowledge(conn, status=None)[0]
    assert record["status"] == fi_db.KNOWLEDGE_RESOLVED
    assert record["superseded_by"] is None


def test_records_are_traceable_back_to_what_caused_them(conn):
    """A belief has to be traceable to the event that produced it, or it is an
    assertion the organization cannot check."""
    fi_db.record_knowledge(
        conn, fi_db.KNOWLEDGE_LESSON, "Lens failed.", recorded_by="coo",
        evidence_ref="intelligence_artifacts:7", rationale="mean IV moved 0.08",
    )
    record = fi_db.list_knowledge(conn)[0]
    assert record["evidence_ref"] == "intelligence_artifacts:7"
    assert record["rationale"] == "mean IV moved 0.08"


def test_open_questions_are_scoped_to_their_subject(conn):
    fi_db.record_knowledge(conn, fi_db.KNOWLEDGE_OPEN_QUESTION, "About SYN1", recorded_by="a", subject="SYN1")
    fi_db.record_knowledge(conn, fi_db.KNOWLEDGE_OPEN_QUESTION, "About SYN2", recorded_by="a", subject="SYN2")
    assert [q["statement"] for q in fi_db.open_questions_for(conn, "SYN1")] == ["About SYN1"]


def test_a_resolved_question_stops_being_carried_forward(conn):
    question_id = fi_db.record_knowledge(
        conn, fi_db.KNOWLEDGE_OPEN_QUESTION, "Answered later", recorded_by="a", subject="SYN1")
    assert fi_db.open_questions_for(conn, "SYN1")
    fi_db.resolve_knowledge(conn, question_id)
    assert fi_db.open_questions_for(conn, "SYN1") == []


# --- the writers, without which the store would be an empty schema ---


def test_coo_records_what_a_lens_failure_taught(conn):
    """Without this the lesson dies with the lens: staleness_reason lives on the
    artifact, so superseding the artifact loses the record of why the old value
    stopped working."""
    from agents.coo import _evaluate_intelligence_health

    lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    minimum = 10
    for _ in range(minimum):
        report_id = fi_db.enqueue_report(conn, "explorer-1", "T", "explorer", "SYN1",
                                         lens_artifact_id=lens["id"])
        fi_db.complete_report(conn, report_id, "analyzed",
                              handled_by_identity="analysis-1", handled_by_spawned_at="T")
        result_id = fi_db.record_analysis_result(conn, "analysis-1", "T", report_id, "SYN1",
                                                 thesis="t", evidence_summary="e", confidence=0.2, uncertainty="u")
        fi_db.record_grade(conn, "analysis-1", "T", report_id, result_id,
                           relevance_score=0.01, novelty_score=0.01, evidence_quality_score=0.01,
                           worth_the_compute=False, overall_score=0.01, rationale="r")

    _evaluate_intelligence_health(conn)

    lessons = fi_db.list_knowledge(conn, record_kind=fi_db.KNOWLEDGE_LESSON)
    assert len(lessons) == 1
    assert lens["name"] in lessons[0]["statement"]
    assert "mean overall score" in lessons[0]["rationale"]
    assert lessons[0]["evidence_ref"] == f"intelligence_artifacts:{lens['id']}"

    # re-running the health check must not relearn it
    _evaluate_intelligence_health(conn)
    assert len(fi_db.list_knowledge(conn, record_kind=fi_db.KNOWLEDGE_LESSON)) == 1


def _analysis_result(worth_the_compute=True, uncertainty="Could be an index rebalance."):
    return {
        "thesis": "t", "evidence_summary": "e", "confidence": 0.6, "uncertainty": uncertainty,
        "relevance_score": 0.7, "novelty_score": 0.7, "evidence_quality_score": 0.7,
        "worth_the_compute": worth_the_compute, "rationale": "r", "peer_classification": "not_applicable",
    }


def test_analysis_preserves_its_uncertainty_as_an_open_question(conn, monkeypatch):
    """uncertainty has always been recorded and never read again. It is the
    system's only real source of unresolved questions (§4.1)."""
    from agents.analysis import _analysis_work

    monkeypatch.setattr("agents.analysis._run_analysis", lambda ctx: _analysis_result())
    fi_db.enqueue_report(conn, "explorer-1", "T", "explorer", "SYN1", summary="s")

    _analysis_work(conn, "analysis-1", "T")

    questions = fi_db.open_questions_for(conn, "SYN1")
    assert [q["statement"] for q in questions] == ["Could be an index rebalance."]
    assert questions[0]["recorded_by"] == "analysis-1"


def test_hedging_on_work_not_worth_the_compute_is_not_recorded(conn, monkeypatch):
    """Recording every hedge would bury the real questions under routine ones."""
    from agents.analysis import _analysis_work

    monkeypatch.setattr("agents.analysis._run_analysis", lambda ctx: _analysis_result(worth_the_compute=False))
    fi_db.enqueue_report(conn, "explorer-1", "T", "explorer", "SYN1", summary="s")

    _analysis_work(conn, "analysis-1", "T")

    assert fi_db.open_questions_for(conn, "SYN1") == []


def test_prior_open_questions_reach_the_next_analysis(conn):
    """The store's first real consumer, and the thin end of "agreement licenses
    execution; it does not terminate thought" - a question outlives the analysis
    that raised it."""
    from agents.analysis import _assemble_context

    fi_db.record_knowledge(conn, fi_db.KNOWLEDGE_OPEN_QUESTION,
                           "Is the SYN1 flow a hedge roll?", recorded_by="analysis-1", subject="SYN1")
    fi_db.enqueue_report(conn, "explorer-1", "T", "explorer", "SYN1", summary="s")

    context = _assemble_context(conn, fi_db.fetch_next_pending_report(conn))

    assert "Is the SYN1 flow a hedge roll?" in context
    assert "unresolved, not settled" in context


def test_questions_about_other_securities_do_not_leak_in(conn):
    from agents.analysis import _assemble_context

    fi_db.record_knowledge(conn, fi_db.KNOWLEDGE_OPEN_QUESTION,
                           "Something about SYN9", recorded_by="analysis-1", subject="SYN9")
    fi_db.enqueue_report(conn, "explorer-1", "T", "explorer", "SYN1", summary="s")

    assert "SYN9" not in _assemble_context(conn, fi_db.fetch_next_pending_report(conn))
