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

from agents.analysis import _analysis_work, _assemble_context
from backend import fi_db
from backend.coordinator import PROJECT_ROOT


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


# --- real-subprocess / real-LLM integration test ---


@pytest.mark.real_llm
def test_real_analysis_agent_consumes_report_and_produces_result(tmp_path):
    """Pre-seeds a pending report directly via fi_db, spawns a real
    agents.analysis subprocess (not through Coordinator - scoped to
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
