"""Unit tests for agents/explorer.py - detector math as a pure function,
plus the judgment-gate/report-filing branch with call_reasoning_model
mocked (no real network call). The one real-subprocess/real-LLM
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

from agents.explorer import _explorer_work, _local_baseline, scan_for_anomaly
from backend import fi_db
from backend.coordinator import PROJECT_ROOT
from providers.market_data import SyntheticMarketDataProvider


class FakeBlock:
    def __init__(self, type, text=None):
        self.type = type
        self.text = text


class FakeResponse:
    def __init__(self, content):
        self.content = content


def judgment_response(passed: bool, note: str = "note"):
    return FakeResponse([FakeBlock("text", text=json.dumps({"passed": passed, "note": note}))])


@pytest.fixture
def conn():
    connection = fi_db.get_connection(":memory:")
    fi_db.init_schema(connection)
    yield connection
    connection.close()


# --- detector math ---


def test_local_baseline_excludes_the_cell_itself():
    grid = {(0, 0): 10.0, (0, 1): 1.0, (1, 0): 1.0, (1, 1): 1.0}
    baseline = _local_baseline(grid, 0, 0, strike_radius=1, expiry_radius=1)
    assert baseline == 1.0  # not pulled up by the (0,0)=10.0 cell itself


def test_scan_for_anomaly_finds_the_forced_peak():
    provider = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}})
    surface = provider.get_option_surface("SYN1")
    result = scan_for_anomaly(surface)
    ratio, si, ei, peak_iv, baseline_iv = result
    assert ratio >= 2.0
    assert peak_iv > baseline_iv


def test_scan_for_anomaly_low_ratio_without_forced_anomaly():
    provider = SyntheticMarketDataProvider(seed=42)
    surface = provider.get_option_surface("SYN1")
    ratio, *_ = scan_for_anomaly(surface)
    assert ratio < 2.0


# --- work_fn behavior ---


def test_explorer_work_no_report_below_threshold(conn, monkeypatch):
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", ["SYN1"])
    call_model = MagicMock()
    monkeypatch.setattr("agents.explorer.call_reasoning_model", call_model)
    provider = SyntheticMarketDataProvider(seed=42)

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)

    assert fi_db.fetch_next_pending_report(conn) is None
    call_model.assert_not_called()


def test_explorer_work_files_report_when_judgment_passes(conn, monkeypatch):
    """Single security, no co-triggering peer -> scope='individual'."""
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", ["SYN1"])
    monkeypatch.setattr("agents.explorer.call_reasoning_model", MagicMock(return_value=judgment_response(True, "coherent")))
    provider = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}})

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)

    report = fi_db.fetch_next_pending_report(conn)
    assert report is not None
    assert report["report_type"] == "explorer"
    assert report["producer_identity"] == "explorer-1"
    event = fi_db.get_detector_event(conn, report["detector_event_id"])
    assert event is not None
    assert event["judgment_passed"] == 1
    assert event["judgment_note"] == "coherent"
    assert event["scope"] == "individual"


def test_explorer_work_logs_event_but_no_report_when_judgment_fails(conn, monkeypatch):
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", ["SYN1"])
    monkeypatch.setattr("agents.explorer.call_reasoning_model", MagicMock(return_value=judgment_response(False, "not coherent")))
    provider = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}})

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)

    assert fi_db.fetch_next_pending_report(conn) is None
    events = [fi_db.get_detector_event(conn, i) for i in range(1, 2)]
    assert events[0]["judgment_passed"] == 0


def test_explorer_work_skips_judgment_call_while_report_pending(conn, monkeypatch):
    """Dedup guard (project plan decision 5): don't spend an LLM call on the
    judgment gate when a report from this producer+security is already
    unconsumed - a static forced-anomaly surface would otherwise trigger
    every cycle."""
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", ["SYN1"])
    call_model = MagicMock(return_value=judgment_response(True))
    monkeypatch.setattr("agents.explorer.call_reasoning_model", call_model)
    provider = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}})

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)
    assert call_model.call_count == 1

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)
    assert call_model.call_count == 1  # not called again - report still pending

    # but a new detector_events row was still logged the second cycle - a
    # genuine repeated detection is a real fact even if we don't re-file
    assert fi_db.get_detector_event(conn, 2) is not None


def test_explorer_work_malformed_judgment_response_fails_closed(conn, monkeypatch):
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", ["SYN1"])
    monkeypatch.setattr("agents.explorer.call_reasoning_model", MagicMock(return_value=FakeResponse([FakeBlock("text", text="not json")])))
    provider = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}})

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)

    assert fi_db.fetch_next_pending_report(conn) is None
    event = fi_db.get_detector_event(conn, 1)
    assert event["judgment_passed"] == 0
    assert "parse failure" in event["judgment_note"]


# --- peer classification ---


def test_explorer_work_two_cotriggering_securities_are_scoped_peer(conn, monkeypatch):
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", ["SYN1", "SYN2", "SYN3"])
    monkeypatch.setattr("agents.explorer.call_reasoning_model", MagicMock(return_value=judgment_response(True)))
    provider = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}, "SYN2": {}})

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)

    events = {e["security"]: e for e in (fi_db.get_detector_event(conn, i) for i in (1, 2))}
    assert events["SYN1"]["scope"] == "peer"
    assert events["SYN2"]["scope"] == "peer"
    assert json.loads(events["SYN1"]["peer_context"])["co_triggering"] == ["SYN2"]
    assert json.loads(events["SYN2"]["peer_context"])["co_triggering"] == ["SYN1"]
    # SYN3 never triggered - no third detector_events row
    assert fi_db.get_detector_event(conn, 3) is None


def test_explorer_work_isolated_security_is_scoped_individual_with_flat_peers(conn, monkeypatch):
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", ["SYN1", "SYN2", "SYN3"])
    monkeypatch.setattr("agents.explorer.call_reasoning_model", MagicMock(return_value=judgment_response(True)))
    provider = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}})

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)

    event = fi_db.get_detector_event(conn, 1)
    assert event["security"] == "SYN1"
    assert event["scope"] == "individual"
    assert json.loads(event["peer_context"])["co_triggering"] == []
    # only one detector_events row - SYN2/SYN3 never triggered
    assert fi_db.get_detector_event(conn, 2) is None


# --- real-subprocess / real-LLM integration test ---


@pytest.mark.real_llm
def test_real_explorer_agent_detects_and_files_report(tmp_path):
    """Spawns a real agents.explorer subprocess (not through Coordinator -
    this test is scoped to Explorer alone, COO/Coordinator orchestration
    is covered separately in test_coordinator.py) against a forced anomaly,
    and confirms it makes a real Anthropic call for the judgment gate and
    files a real report - proving the whole detector -> LLM gate -> queue
    path works end to end, not just each mocked piece in isolation."""
    db_path = str(tmp_path / "fi_test.db")
    conn = fi_db.get_connection(db_path)
    fi_db.init_schema(conn)

    # conftest.py's os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
    # already ran by the time any test executes (module-level, whole
    # session), so {**os.environ, ...} alone would hand the child a fake
    # key even though a real one is in .env - dotenv_values() reads .env
    # directly without touching os.environ, so this explicitly restores the
    # real key for this one real_llm-marked subprocess.
    real_env_values = dotenv_values(PROJECT_ROOT / ".env")
    env = {
        **os.environ,
        **real_env_values,
        "FI_DB_PATH": db_path,
        "FI_PEER_GROUP_SECURITIES": "SYN1",
        "FI_FORCE_ANOMALY_SECURITIES": "SYN1",
    }
    process = subprocess.Popen([sys.executable, "-m", "agents.explorer", "explorer-1"], cwd=PROJECT_ROOT, env=env)
    try:
        deadline = time.time() + 20
        report = None
        while time.time() < deadline and report is None:
            report = fi_db.fetch_next_pending_report(conn)
            time.sleep(0.5)
        assert report is not None, "explorer never filed a report"
        assert report["report_type"] == "explorer"
        assert report["producer_identity"] == "explorer-1"

        event = fi_db.get_detector_event(conn, report["detector_event_id"])
        assert event is not None
        assert event["ratio"] >= 2.0
        assert event["judgment_passed"] == 1
        assert event["scope"] == "individual"
    finally:
        fi_db.request_retirement(conn, "explorer-1")
        process.wait(timeout=10)
        conn.close()


@pytest.mark.real_llm
def test_real_explorer_agent_classifies_cotriggering_securities_as_peer(tmp_path):
    """Two forced securities (not all four - bounds real API cost/time to
    at most two judgment-gate calls) - proves the real multi-call judgment-
    gate loop doesn't regress the heartbeat-per-call fix (agents/coo.py's
    HEALTH_STALE_THRESHOLD_SECONDS docstring) and that both land as
    scope='peer' with correct peer_context."""
    db_path = str(tmp_path / "fi_test.db")
    conn = fi_db.get_connection(db_path)
    fi_db.init_schema(conn)

    real_env_values = dotenv_values(PROJECT_ROOT / ".env")
    env = {
        **os.environ,
        **real_env_values,
        "FI_DB_PATH": db_path,
        "FI_PEER_GROUP_SECURITIES": "SYN1,SYN2",
        "FI_FORCE_ANOMALY_SECURITIES": "SYN1,SYN2",
    }
    process = subprocess.Popen([sys.executable, "-m", "agents.explorer", "explorer-1"], cwd=PROJECT_ROOT, env=env)
    try:
        deadline = time.time() + 30
        reports = []
        while time.time() < deadline and len(reports) < 2:
            reports = conn.execute("SELECT * FROM discovery_reports").fetchall()
            time.sleep(0.5)
        assert len(reports) == 2, f"expected 2 reports (SYN1+SYN2), got {len(reports)}"

        events = {r["security"]: fi_db.get_detector_event(conn, r["detector_event_id"]) for r in reports}
        assert set(events) == {"SYN1", "SYN2"}
        for security, event in events.items():
            assert event["scope"] == "peer"
            other = "SYN2" if security == "SYN1" else "SYN1"
            assert json.loads(event["peer_context"])["co_triggering"] == [other]
    finally:
        fi_db.request_retirement(conn, "explorer-1")
        process.wait(timeout=10)
        conn.close()
