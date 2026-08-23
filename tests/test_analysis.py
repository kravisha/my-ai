"""Unit tests for agents/analysis.py - call_reasoning_model mocked with
canned JSON (no real network call). The one real-subprocess/real-LLM
integration test at the bottom is gated behind @pytest.mark.real_llm,
excluded from the default pytest run (see pyproject.toml)."""

import json
import os
import subprocess
import sys
import time
from unittest.mock import MagicMock

import pytest
from dotenv import dotenv_values

from agents.analysis import _analysis_work, _assemble_context, _run_challenge
from backend import fi_db
from backend.controller import PROJECT_ROOT


class FakeBlock:
    def __init__(self, type, text=None):
        self.type = type
        self.text = text


class FakeResponse:
    def __init__(self, content):
        self.content = content


VALID_RESULT = {
    "thesis": "IV looks overpriced here; could normalize post-earnings. Could be wrong if a real catalyst is coming.",
    "evidence_summary": "Peak IV 2.4x local baseline.",
    "confidence": 0.6,
    "uncertainty": "Earnings date proximity could be a legitimate driver, not just dislocation.",
    "relevance_score": 0.8,
    "novelty_score": 0.7,
    "evidence_quality_score": 0.75,
    "worth_the_compute": True,
    "rationale": "Clean deterministic signal, no confounding social noise.",
    "peer_classification": "idiosyncratic",
}


def analysis_response(payload: dict):
    return FakeResponse([FakeBlock("text", text=json.dumps(payload))])


def test_analysis_work_idle_when_no_pending_report(conn, monkeypatch):
    call_model = MagicMock()
    monkeypatch.setattr("agents.analysis.call_reasoning_model", call_model)
    _analysis_work(conn, "analysis-1", "2026-01-01T00:00:00+00:00")
    call_model.assert_not_called()


def test_analysis_work_success_path_creates_result_and_grade(conn, monkeypatch):
    monkeypatch.setattr("agents.analysis.call_reasoning_model", MagicMock(return_value=analysis_response(VALID_RESULT)))
    event_id = fi_db.record_detector_event(
        conn, "explorer-1", "2026-01-01T00:00:00+00:00", "SYN1", "iv_surface_peak_ratio",
        0.6, 0.25, 2.4, 2.0,
    )
    report_id = fi_db.enqueue_report(
        conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1",
        summary="anomaly", detector_event_id=event_id, evidence_ids=[],
    )

    _analysis_work(conn, "analysis-1", "2026-01-01T00:01:00+00:00")

    assert fi_db.fetch_next_pending_report(conn) is None
    completed = fi_db.list_completed_reports(conn)
    assert completed[0]["outcome"] == "analyzed"
    assert completed[0]["handled_by_identity"] == "analysis-1"

    results = fi_db.list_recent_analysis_results(conn, "SYN1", since_seconds=999)
    assert len(results) == 1
    assert results[0]["thesis"] == VALID_RESULT["thesis"]
    assert results[0]["report_id"] == report_id

    grades = fi_db.list_grades_for_identity(conn, "explorer-1")
    assert len(grades) == 1
    assert grades[0]["analysis_result_id"] == results[0]["id"]
    assert grades[0]["worth_the_compute"] == 1
    expected_overall = round((0.8 + 0.7 + 0.75) / 3, 4)
    assert grades[0]["overall_score"] == expected_overall
    assert results[0]["peer_classification"] == "idiosyncratic"


def test_analysis_work_malformed_json_marks_report_failed(conn, monkeypatch):
    monkeypatch.setattr("agents.analysis.call_reasoning_model", MagicMock(return_value=FakeResponse([FakeBlock("text", text="not json")])))
    report_id = fi_db.enqueue_report(conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1")

    _analysis_work(conn, "analysis-1", "2026-01-01T00:01:00+00:00")

    completed = fi_db.list_completed_reports(conn)
    assert completed[0]["id"] == report_id
    assert completed[0]["outcome"] == "failed"
    assert completed[0]["detail"] is not None
    assert fi_db.list_recent_analysis_results(conn, "SYN1", since_seconds=999) == []
    assert fi_db.list_grades_for_identity(conn, "explorer-1") == []


def test_analysis_work_missing_required_field_marks_report_failed(conn, monkeypatch):
    incomplete = dict(VALID_RESULT)
    del incomplete["confidence"]
    monkeypatch.setattr("agents.analysis.call_reasoning_model", MagicMock(return_value=analysis_response(incomplete)))
    fi_db.enqueue_report(conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1")

    _analysis_work(conn, "analysis-1", "2026-01-01T00:01:00+00:00")

    completed = fi_db.list_completed_reports(conn)
    assert completed[0]["outcome"] == "failed"
    assert "confidence" in completed[0]["detail"]


def test_analysis_work_invalid_peer_classification_marks_report_failed(conn, monkeypatch):
    bad_result = dict(VALID_RESULT)
    bad_result["peer_classification"] = "definitely_bullish"  # not one of the three valid enum values
    monkeypatch.setattr("agents.analysis.call_reasoning_model", MagicMock(return_value=analysis_response(bad_result)))
    fi_db.enqueue_report(conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1")

    _analysis_work(conn, "analysis-1", "2026-01-01T00:01:00+00:00")

    completed = fi_db.list_completed_reports(conn)
    assert completed[0]["outcome"] == "failed"
    assert "peer_classification" in completed[0]["detail"]


def test_assemble_context_surfaces_peer_framing_for_peer_scope(conn):
    event_id = fi_db.record_detector_event(
        conn, "explorer-1", "2026-01-01T00:00:00+00:00", "SYN1", "iv_surface_peak_ratio",
        0.6, 0.25, 2.4, 2.0, scope="peer", peer_group_name="synthetic_peer_group_v1",
        peer_group_version=1, peer_context=json.dumps({
            "peer_group_name": "synthetic_peer_group_v1", "peer_group_version": 1,
            "co_triggering": ["SYN2"], "group_size": 4, "triggering_count": 2,
        }),
    )
    fi_db.enqueue_report(conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1", detector_event_id=event_id, evidence_ids=[])
    report = fi_db.fetch_next_pending_report(conn)

    context = _assemble_context(conn, report)

    assert "SYN2" in context
    assert "common-factor" in context.lower() or "common_factor" in context.lower()


def test_assemble_context_surfaces_idiosyncratic_framing_for_individual_scope(conn):
    event_id = fi_db.record_detector_event(
        conn, "explorer-1", "2026-01-01T00:00:00+00:00", "SYN1", "iv_surface_peak_ratio",
        0.6, 0.25, 2.4, 2.0, scope="individual",
    )
    fi_db.enqueue_report(conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1", detector_event_id=event_id, evidence_ids=[])
    report = fi_db.fetch_next_pending_report(conn)

    context = _assemble_context(conn, report)

    assert "isolated" in context.lower()
    assert "idiosyncratic" in context.lower()


def test_assemble_context_includes_detector_event_and_evidence(conn):
    event_id = fi_db.record_detector_event(
        conn, "explorer-1", "2026-01-01T00:00:00+00:00", "SYN1", "iv_surface_peak_ratio",
        0.6, 0.25, 2.4, 2.0,
    )
    fi_db.record_detector_judgment(conn, event_id, True, "looks coherent")
    evidence_id = fi_db.record_evidence_item(
        conn, "speculator-1", "2026-01-01T00:00:00+00:00", "social", "SYN1",
        content="large block trade printed", confidence=0.75,
    )
    report_id = fi_db.enqueue_report(
        conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1",
        summary="combined signal", detector_event_id=event_id, evidence_ids=[evidence_id],
    )
    report = fi_db.fetch_next_pending_report(conn)

    context = _assemble_context(conn, report)

    assert "SYN1" in context
    assert "2.4" in context or "2.400" in context
    assert "looks coherent" in context
    assert "large block trade printed" in context


# --- ARB-001 parity context (SPEC_RECONCILIATION.md SS39-SS41) --------------


def test_assemble_context_renders_the_parity_block_for_a_parity_report(conn):
    parity_event_id = fi_db.record_parity_event(
        conn, "explorer-1", "2026-01-01T00:00:00+00:00", "ENT1", "SYN1",
        strike=100.0, expiry_days=30, direction="conversion",
        gross_edge_per_share=0.65, net_edge_per_share=0.55, classification="A",
        capacity_units=12.0, observed_at="2026-01-05T14:30:00+00:00",
        run_id="m1", scenario_id="m1-s0",
    )
    fi_db.enqueue_report(
        conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1",
        summary="Executable put-call parity violation on SYN1: conversion net edge $0.55/share at K=100.0 30d "
                "(ARB-001, class A); cross-check evidence",
        detector_event_id=None, parity_event_id=parity_event_id, evidence_ids=[],
    )
    report = fi_db.fetch_next_pending_report(conn)

    context = _assemble_context(conn, report)

    assert "conversion" in context
    assert "0.55" in context
    assert "100.0" in context
    assert "30" in context
    assert "ARB-001" in context
    assert "not_applicable" in context


def test_assemble_context_iv_report_is_unchanged_by_the_parity_block(conn):
    """A report with no parity_event_id must not gain a parity block - the
    two are mutually exclusive (backend/fi_db.py's discovery_reports.
    parity_event_id comment)."""
    event_id = fi_db.record_detector_event(
        conn, "explorer-1", "2026-01-01T00:00:00+00:00", "SYN1", "iv_surface_peak_ratio",
        0.6, 0.25, 2.4, 2.0,
    )
    fi_db.enqueue_report(
        conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1",
        detector_event_id=event_id, evidence_ids=[],
    )
    report = fi_db.fetch_next_pending_report(conn)
    assert report["parity_event_id"] is None

    context = _assemble_context(conn, report)

    assert "Parity claim" not in context
    assert "ARB-001" not in context


# --- real-subprocess / real-LLM integration test ---


@pytest.mark.real_llm
def test_real_analysis_agent_consumes_report_and_produces_result(tmp_path):
    """Pre-seeds a pending report directly via fi_db, spawns a real
    agents.analysis subprocess (not through Controller - scoped to
    Analysis alone), and confirms it makes a real Anthropic call and
    produces a real analysis_results row plus a grade for the upstream
    report - proving the queue-consume -> LLM -> persist path works end to
    end, not just each mocked piece in isolation."""
    db_path = str(tmp_path / "fi_test.db")
    conn = fi_db.get_connection(db_path)
    fi_db.init_schema(conn)

    report_id = fi_db.enqueue_report(
        conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1",
        summary="test anomaly for a real Analysis run: unusually elevated implied "
                "volatility on SYN1 relative to its local surface neighborhood",
        detector_event_id=None, evidence_ids=[],
    )

    # see test_explorer.py's equivalent test for why real_env_values is
    # needed - conftest.py's setdefault poisons os.environ with a fake key
    # before any test runs, which would otherwise shadow the real one in .env.
    real_env_values = dotenv_values(PROJECT_ROOT / ".env")
    env = {**os.environ, **real_env_values, "FI_DB_PATH": db_path}
    process = subprocess.Popen([sys.executable, "-m", "agents.analysis", "analysis-1"], cwd=PROJECT_ROOT, env=env)
    try:
        deadline = time.time() + 30
        completed = []
        while time.time() < deadline and not completed:
            completed = fi_db.list_completed_reports(conn)
            time.sleep(0.5)
        assert completed, "analysis never completed the report"
        assert completed[0]["id"] == report_id
        assert completed[0]["outcome"] == "analyzed"

        results = fi_db.list_recent_analysis_results(conn, "SYN1", since_seconds=999)
        assert len(results) == 1
        assert results[0]["thesis"]
        # no detector_event_id on this report -> no peer context in the
        # prompt at all -> the LLM should correctly say not_applicable
        assert results[0]["peer_classification"] == "not_applicable"

        grades = fi_db.list_grades_for_identity(conn, "explorer-1")
        assert len(grades) == 1
        assert grades[0]["analysis_result_id"] == results[0]["id"]
    finally:
        fi_db.request_retirement(conn, "analysis-1")
        process.wait(timeout=10)
        conn.close()


# --- preserved disagreement reaches the only role that reasons ---


def _report_with_cross_check(conn, outcome, responder_finding, requester_finding=None):
    request_id = fi_db.open_cross_check(
        conn, "explorer-1", "T0", "explorer", "speculator", "SYN1",
        question="Is there contextual evidence of unusual attention on SYN1?",
        requester_finding=requester_finding or {"ratio": 2.21, "scope": "individual"},
    )
    if responder_finding is not None:
        fi_db.answer_cross_check(conn, request_id, "speculator-1", "T1", outcome, responder_finding, 0.9)
    else:
        fi_db.expire_stale_cross_checks(conn, timeout_seconds=0)
    fi_db.enqueue_report(conn, "explorer-1", "T0", "explorer", "SYN1",
                         summary="s", cross_check_id=request_id)
    return fi_db.fetch_next_pending_report(conn)


def test_context_carries_both_findings_unreconciled(conn):
    report = _report_with_cross_check(
        conn, fi_db.CROSS_CHECK_EVIDENCE,
        {"posts": 26, "distinct_authors": 25, "stance": "undercuts"},
    )
    context = _assemble_context(conn, report)
    assert '"ratio": 2.21' in context           # Explorer's claim, as stated
    assert '"stance": "undercuts"' in context   # Speculator's, as stated
    assert "NOT been reconciled" in context
    # no upstream agent decided the question for Analysis
    assert "corroborated" not in context


def test_context_surfaces_coordinated_noise_as_a_distinct_signal(conn):
    """Stance says the crowd agrees; the arithmetic says three accounts. Both
    reach Analysis, because neither alone is the answer."""
    report = _report_with_cross_check(
        conn, fi_db.CROSS_CHECK_EVIDENCE,
        {"posts": 36, "distinct_authors": 3, "posts_per_author": 12.0, "stance": "supports"},
    )
    context = _assemble_context(conn, report)
    assert '"posts_per_author": 12.0' in context
    assert "coordinated noise rather than a crowd" in context


def test_context_distinguishes_no_evidence_from_never_asked(conn):
    report = _report_with_cross_check(conn, fi_db.CROSS_CHECK_NO_EVIDENCE, {"posts": 0})
    context = _assemble_context(conn, report)
    assert "looked and found nothing" in context
    assert "distinct from never having been asked" in context


def test_context_marks_an_unanswered_cross_check_as_uncorroborated_not_refuted(conn):
    """Silence is not evidence against a lead. Conflating the two would let a
    dormant agent quietly veto every finding."""
    report = _report_with_cross_check(conn, None, None)
    context = _assemble_context(conn, report)
    assert "nobody answered" in context
    assert "uncorroborated rather than contradicted" in context


def test_context_without_a_cross_check_is_unchanged(conn):
    """Reports predating the cross-check, and any filed without one, must not
    gain empty scaffolding."""
    fi_db.enqueue_report(conn, "explorer-1", "T0", "explorer", "SYN1", summary="s")
    context = _assemble_context(conn, fi_db.fetch_next_pending_report(conn))
    assert "Cross-check" not in context


# --- Iterative Excellence: the adopted 3-pass conclude/challenge/revise budget ---


CHALLENGE_STANDS = {
    "verdict": "stands",
    "challenge_summary": "The confidence looks calibrated to the stated evidence; no material gap found.",
    "material_problems": [],
}

CHALLENGE_REVISE = {
    "verdict": "revise",
    "challenge_summary": "The thesis overweights the IV spike without addressing the upcoming earnings catalyst.",
    "material_problems": ["earnings catalyst not addressed"],
}

REVISED_RESULT = {
    "thesis": "Revised: earnings proximity plausibly explains the IV spike; downgrading conviction accordingly.",
    "evidence_summary": "Peak IV 2.4x local baseline, but earnings print in 3 days.",
    "confidence": 0.35,
    "uncertainty": "Whether the post-earnings IV crush fully explains the move.",
    "relevance_score": 0.5,
    "novelty_score": 0.4,
    "evidence_quality_score": 0.55,
    "worth_the_compute": True,
    "rationale": "Revision after the challenge surfaced the earnings catalyst.",
    "peer_classification": "idiosyncratic",
}

MALFORMED_RESPONSE = FakeResponse([FakeBlock("text", text="not json")])


def _seed_pending_report(conn):
    event_id = fi_db.record_detector_event(
        conn, "explorer-1", "2026-01-01T00:00:00+00:00", "SYN1", "iv_surface_peak_ratio",
        0.6, 0.25, 2.4, 2.0,
    )
    return fi_db.enqueue_report(
        conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1",
        summary="anomaly", detector_event_id=event_id, evidence_ids=[],
    )


def test_a_conclusion_that_stands_costs_two_passes(conn, monkeypatch):
    call_model = MagicMock(side_effect=[
        analysis_response(VALID_RESULT),
        analysis_response(CHALLENGE_STANDS),
    ])
    monkeypatch.setattr("agents.analysis.call_reasoning_model", call_model)
    _seed_pending_report(conn)

    _analysis_work(conn, "analysis-1", "2026-01-01T00:01:00+00:00")

    assert call_model.call_count == 2
    results = fi_db.list_recent_analysis_results(conn, "SYN1", since_seconds=999)
    assert len(results) == 1
    assert results[0]["passes_used"] == 2
    assert results[0]["challenge_summary"] == CHALLENGE_STANDS["challenge_summary"]
    assert results[0]["thesis"] == VALID_RESULT["thesis"]


def test_a_material_challenge_triggers_revision(conn, monkeypatch):
    call_model = MagicMock(side_effect=[
        analysis_response(VALID_RESULT),
        analysis_response(CHALLENGE_REVISE),
        analysis_response(REVISED_RESULT),
    ])
    monkeypatch.setattr("agents.analysis.call_reasoning_model", call_model)
    fi_db.enqueue_report(conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1", summary="anomaly")

    _analysis_work(conn, "analysis-1", "2026-01-01T00:01:00+00:00")

    assert call_model.call_count == 3
    results = fi_db.list_recent_analysis_results(conn, "SYN1", since_seconds=999)
    assert results[0]["passes_used"] == 3
    assert results[0]["thesis"] == REVISED_RESULT["thesis"]
    assert results[0]["confidence"] == REVISED_RESULT["confidence"]

    grades = fi_db.list_grades_for_identity(conn, "explorer-1")
    assert len(grades) == 1
    assert grades[0]["relevance_score"] == REVISED_RESULT["relevance_score"]
    assert grades[0]["novelty_score"] == REVISED_RESULT["novelty_score"]
    assert grades[0]["evidence_quality_score"] == REVISED_RESULT["evidence_quality_score"]


def test_a_failed_challenge_never_destroys_the_primary_result(conn, monkeypatch):
    """Refinement must not destroy the core - only the primary analysis
    failing fails the report."""
    call_model = MagicMock(side_effect=[
        analysis_response(VALID_RESULT),
        MALFORMED_RESPONSE,
    ])
    monkeypatch.setattr("agents.analysis.call_reasoning_model", call_model)
    fi_db.enqueue_report(conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1", summary="anomaly")

    _analysis_work(conn, "analysis-1", "2026-01-01T00:01:00+00:00")

    completed = fi_db.list_completed_reports(conn)
    assert completed[0]["outcome"] == "analyzed"
    results = fi_db.list_recent_analysis_results(conn, "SYN1", since_seconds=999)
    assert results[0]["passes_used"] == 1
    assert results[0]["challenge_summary"] is None
    assert results[0]["thesis"] == VALID_RESULT["thesis"]


def test_a_failed_revision_falls_back_to_the_challenged_conclusion(conn, monkeypatch):
    call_model = MagicMock(side_effect=[
        analysis_response(VALID_RESULT),
        analysis_response(CHALLENGE_REVISE),
        MALFORMED_RESPONSE,
    ])
    monkeypatch.setattr("agents.analysis.call_reasoning_model", call_model)
    fi_db.enqueue_report(conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1", summary="anomaly")

    _analysis_work(conn, "analysis-1", "2026-01-01T00:01:00+00:00")

    results = fi_db.list_recent_analysis_results(conn, "SYN1", since_seconds=999)
    assert results[0]["thesis"] == VALID_RESULT["thesis"]
    assert results[0]["passes_used"] == 2
    assert results[0]["challenge_summary"] == CHALLENGE_REVISE["challenge_summary"]


def test_the_budget_is_a_ceiling_the_environment_can_lower(conn, monkeypatch):
    """For cost-bounded simulation runs - not for quietly unadopting the
    budget."""
    monkeypatch.setattr("agents.analysis.ANALYSIS_MAX_PASSES", 1)
    call_model = MagicMock(side_effect=[analysis_response(VALID_RESULT)])
    monkeypatch.setattr("agents.analysis.call_reasoning_model", call_model)
    fi_db.enqueue_report(conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1", summary="anomaly")

    _analysis_work(conn, "analysis-1", "2026-01-01T00:01:00+00:00")

    assert call_model.call_count == 1
    results = fi_db.list_recent_analysis_results(conn, "SYN1", since_seconds=999)
    assert results[0]["passes_used"] == 1


def test_a_heartbeat_precedes_every_pass(conn, monkeypatch):
    """Three sequential model calls is exactly the duplicate-agent defect
    class already paid for twice; the heartbeat before each pass is what
    keeps a slow-but-alive agent from being declared crashed mid-refinement."""
    real_heartbeat = fi_db.record_heartbeat
    heartbeat_calls = []

    def spy_heartbeat(conn_, identity, *args, **kwargs):
        heartbeat_calls.append(identity)
        return real_heartbeat(conn_, identity, *args, **kwargs)

    monkeypatch.setattr(fi_db, "record_heartbeat", spy_heartbeat)
    call_model = MagicMock(side_effect=[
        analysis_response(VALID_RESULT),
        analysis_response(CHALLENGE_REVISE),
        analysis_response(REVISED_RESULT),
    ])
    monkeypatch.setattr("agents.analysis.call_reasoning_model", call_model)
    fi_db.enqueue_report(conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1", summary="anomaly")

    _analysis_work(conn, "analysis-1", "2026-01-01T00:01:00+00:00")

    assert len(heartbeat_calls) >= 3


def test_verdict_vocabulary_is_enforced(monkeypatch):
    bad_challenge = dict(CHALLENGE_STANDS)
    bad_challenge["verdict"] = "maybe"
    monkeypatch.setattr(
        "agents.analysis.call_reasoning_model",
        MagicMock(return_value=analysis_response(bad_challenge)),
    )
    with pytest.raises(ValueError):
        _run_challenge("some report context", VALID_RESULT)
