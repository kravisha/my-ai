"""Unit tests for agents/explorer.py - detector math as a pure function,
plus the judgment-gate/report-filing branch with call_reasoning_model
mocked (no real network call). The one real-subprocess/real-LLM
integration test at the bottom is gated behind @pytest.mark.real_llm,
excluded from the default pytest run (see pyproject.toml)."""

import json
import os
import random
import subprocess
import sys
import time
from unittest.mock import MagicMock

import pytest
from dotenv import dotenv_values

from agents.explorer import (
    PARITY_DETECTOR_TYPE, _explorer_work, _file_cross_checked_reports, _local_baseline, _parity_work,
    scan_for_anomaly,
)
from backend import fi_db
from backend import reference_data as rd
from backend.controller import PROJECT_ROOT
from providers.market_data import SyntheticMarketDataProvider
from simulation import parity_world as pw


class FakeBlock:
    def __init__(self, type, text=None):
        self.type = type
        self.text = text


class FakeResponse:
    def __init__(self, content):
        self.content = content


def judgment_response(passed: bool, note: str = "note"):
    return FakeResponse([FakeBlock("text", text=json.dumps({"passed": passed, "note": note}))])


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
    """Single security, no co-triggering peer -> scope='individual'.

    Two cycles now, not one: a candidate that passes the judgment gate becomes
    a *cross-check request* rather than a report (addendum 12 section 14 -
    investigate independently, then cross-check). The report is filed on a
    later cycle once an answer or a timeout comes back."""
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", ["SYN1"])
    monkeypatch.setattr("agents.explorer.call_reasoning_model", MagicMock(return_value=judgment_response(True, "coherent")))
    provider = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}})

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)
    assert fi_db.fetch_next_pending_report(conn) is None  # still awaiting corroboration

    fi_db.answer_cross_check(
        conn, 1, "speculator-1", "2026-01-01T00:00:00+00:00",
        fi_db.CROSS_CHECK_EVIDENCE, {"posts": 6, "distinct_authors": 6, "stance": "supports"},
    )
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
    # not called again - an unconsumed cross-check on this security now guards
    # the gate as well as an unconsumed report does
    assert call_model.call_count == 1

    # but a new detector_events row was still logged the second cycle - a
    # genuine repeated detection is a real fact even if we don't re-file
    assert fi_db.get_detector_event(conn, 2) is not None


def test_explorer_work_origination_cooldown_skips_the_gate_entirely(conn, monkeypatch):
    """§58: a persisting dislocation on a security whose analysis chain
    completed recently does not re-buy the judgment gate, let alone the
    chain behind it - checked before the gate for the same reason the
    pending-report guard is. The detector event is still recorded:
    observation is free, only the paid chain waits."""
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", ["SYN1"])
    call_model = MagicMock(return_value=judgment_response(True))
    monkeypatch.setattr("agents.explorer.call_reasoning_model", call_model)
    report_id = fi_db.enqueue_report(conn, "someone-else", "T0", "explorer", "SYN1")
    fi_db.record_analysis_result(
        conn, "analysis-1", "T0", report_id, "SYN1",
        thesis="t", evidence_summary="e", confidence=0.5, uncertainty="u",
    )
    provider = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}})

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)

    assert call_model.call_count == 0
    assert conn.fetchall("SELECT * FROM cross_check_requests") == []
    assert fi_db.get_detector_event(conn, 1) is not None


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
    """Spawns a real agents.explorer subprocess (not through Controller -
    this test is scoped to Explorer alone, COO/Controller orchestration
    is covered separately in test_controller.py) against a forced anomaly,
    and confirms it makes a real Anthropic call for the judgment gate and
    files a real report - proving the whole detector -> LLM gate -> queue
    path works end to end, not just each mocked piece in isolation.

    No Speculator runs here, so the cross-check this now opens is answered by
    nobody. A short FI_CROSS_CHECK_TIMEOUT_SECONDS makes the test exercise the
    path that matters most for a single-agent deployment: silence must resolve
    to 'unanswered' and the lead must still be filed."""
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
        "FI_CROSS_CHECK_TIMEOUT_SECONDS": "2",
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

        # the unanswered cross-check is recorded on the report, not omitted -
        # Analysis must be able to tell "nobody corroborated this" apart from
        # "this was never cross-checked"
        assert report["cross_check_id"] is not None
        assert fi_db.get_cross_check(conn, report["cross_check_id"])["outcome"] == fi_db.CROSS_CHECK_UNANSWERED
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
        # nobody answers the cross-checks in an Explorer-only test
        "FI_CROSS_CHECK_TIMEOUT_SECONDS": "2",
    }
    process = subprocess.Popen([sys.executable, "-m", "agents.explorer", "explorer-1"], cwd=PROJECT_ROOT, env=env)
    try:
        deadline = time.time() + 30
        reports = []
        while time.time() < deadline and len(reports) < 2:
            reports = conn.fetchall("SELECT * FROM discovery_reports")
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


# --- the lens comes from the intelligence store, not a constant ---


def test_explorer_uses_the_artifact_value_not_a_constant(conn, monkeypatch):
    """The point of the whole increment: raising the lens's stored threshold
    above the anomaly's ratio must suppress detection. If Explorer were still
    reading a config constant this would detect anyway."""
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", ["SYN1"])
    monkeypatch.setattr("agents.explorer.call_reasoning_model", MagicMock(return_value=judgment_response(True)))
    provider = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}})

    lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    fi_db.supersede_artifact(
        conn, lens["id"],
        fi_db.record_intelligence_artifact(
            conn, fi_db.LENS_KIND, fi_db.LENS_IV_RATIO_NAME, 99.0,
            rationale="test: unreachably high", version=2,
        ),
    )

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)

    assert fi_db.get_detector_event(conn, 1) is None, "a threshold of 99.0 must suppress the detection"


def test_explorer_stamps_the_lens_on_detections_and_reports(conn, monkeypatch):
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", ["SYN1"])
    monkeypatch.setattr("agents.explorer.call_reasoning_model", MagicMock(return_value=judgment_response(True)))
    provider = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}})
    lens_id = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)["id"]

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)
    assert fi_db.get_detector_event(conn, 1)["lens_artifact_id"] == lens_id

    # the lens must survive the cross-check round trip onto the eventual report
    fi_db.answer_cross_check(conn, 1, "speculator-1", "2026-01-01T00:00:00+00:00",
                             fi_db.CROSS_CHECK_NO_EVIDENCE, {"posts": 0})
    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)
    assert fi_db.fetch_next_pending_report(conn)["lens_artifact_id"] == lens_id


def test_explorer_falls_back_to_the_seed_when_the_lens_is_stale(conn, monkeypatch):
    """A stale lens is a signal for review, not a reason to stop detecting -
    Explorer keeps working on the seed value and lets COO's flag stand."""
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", ["SYN1"])
    monkeypatch.setattr("agents.explorer.call_reasoning_model", MagicMock(return_value=judgment_response(True)))
    provider = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}})

    lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    fi_db.mark_artifact_stale(conn, lens["id"], "test")

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)

    event = fi_db.get_detector_event(conn, 1)
    assert event is not None, "detection must continue despite the lens being flagged stale"
    assert event["threshold"] == fi_db.LENS_IV_RATIO_SEED
    assert event["lens_artifact_id"] is None


# --- regime observation: Explorer observes, it does not judge ---


def test_explorer_observes_regime_for_every_security_including_quiet_ones(conn, monkeypatch):
    """Regime is a property of the whole market. Sampling only the securities
    that tripped the detector would characterize anomalies, not conditions."""
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", ["SYN1", "SYN2", "SYN3"])
    monkeypatch.setattr("agents.explorer.call_reasoning_model", MagicMock(return_value=judgment_response(True)))
    provider = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}})

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)

    observed = {row["security"] for row in fi_db.list_market_regime(conn)}
    assert observed == {"SYN1", "SYN2", "SYN3"}


def test_explorer_regime_observation_tracks_the_provider_regime(conn, monkeypatch):
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", ["SYN1"])
    monkeypatch.setattr("agents.explorer.call_reasoning_model", MagicMock())
    provider = SyntheticMarketDataProvider(seed=42, regime={"base_level": 0.45})

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)

    # ~0.45 base + skew/term contributions, nowhere near the 0.25 default
    assert fi_db.get_market_regime(conn, "SYN1")["mean_iv"] > 0.44


def test_explorer_accumulates_regime_observations_across_cycles(conn, monkeypatch):
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", ["SYN1"])
    monkeypatch.setattr("agents.explorer.call_reasoning_model", MagicMock())
    provider = SyntheticMarketDataProvider(seed=42)

    for _ in range(5):
        _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)

    assert fi_db.get_market_regime(conn, "SYN1")["observation_count"] == 5


def test_explorer_never_binds_or_marks_a_lens_stale_itself(conn, monkeypatch):
    """Axiom 4: Explorer observes a deterministic statistic. The judgment
    'these conditions invalidate the lens' belongs to COO - Explorer judging
    the lens it detects with would be the self-certification addendum 11 §8
    forbids."""
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", ["SYN1"])
    monkeypatch.setattr("agents.explorer.call_reasoning_model", MagicMock(return_value=judgment_response(True)))
    provider = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}})

    for _ in range(60):
        _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)

    lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    assert lens is not None  # still active
    assert json.loads(lens["validity_conditions"])["regime"]["observed_under"] is None  # still unbound


# --- cross-check: independence, timeout, and preserved disagreement ---


def test_explorer_records_its_own_finding_before_asking(conn, monkeypatch):
    """"Investigate independently first, then cross-check." The finding must
    exist in full before Speculator has said anything - otherwise the two
    views are not independent and the pair is one reference frame twice."""
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", ["SYN1"])
    monkeypatch.setattr("agents.explorer.call_reasoning_model", MagicMock(return_value=judgment_response(True)))
    provider = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}})

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)

    request = fi_db.fetch_next_pending_cross_check(conn, "speculator")
    finding = json.loads(request["requester_finding"])
    assert finding["ratio"] >= 2.0
    assert finding["detector_event_id"] is not None
    assert request["responder_finding"] is None
    assert "Is there contextual evidence" in request["question"]


def test_explorer_files_the_lead_even_when_the_answer_undercuts_it(conn, monkeypatch):
    """Dropping a lead because the other side disagreed would let the
    originator adjudicate its own case - the suppression failure mode the gap
    analysis §4.2 flags. The dissent is filed, not the verdict."""
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", ["SYN1"])
    monkeypatch.setattr("agents.explorer.call_reasoning_model", MagicMock(return_value=judgment_response(True)))
    provider = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}})

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)
    fi_db.answer_cross_check(conn, 1, "speculator-1", "T1", fi_db.CROSS_CHECK_EVIDENCE,
                             {"posts": 26, "distinct_authors": 25, "stance": "undercuts"})
    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)

    report = fi_db.fetch_next_pending_report(conn)
    assert report is not None
    assert report["cross_check_id"] == 1


def test_an_unanswered_cross_check_never_stalls_explorer(conn, monkeypatch):
    """A dormant or crashed Speculator must not halt the pipeline. The lead is
    filed with the silence recorded as 'unanswered'."""
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", ["SYN1"])
    monkeypatch.setattr("agents.explorer.call_reasoning_model", MagicMock(return_value=judgment_response(True)))
    monkeypatch.setattr("backend.fi_db.CROSS_CHECK_TIMEOUT_SECONDS", 0)
    provider = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}})

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)
    assert fi_db.fetch_next_pending_report(conn) is None  # nobody has answered

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)

    assert fi_db.fetch_next_pending_report(conn) is not None
    assert fi_db.get_cross_check(conn, 1)["outcome"] == fi_db.CROSS_CHECK_UNANSWERED


def test_explorer_answers_speculator_with_bare_detector_facts(conn, monkeypatch):
    """The other direction (§14). Explorer states what its detector saw; it
    does not opine on whether that supports Speculator's social evidence."""
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", [])
    provider = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}})
    request_id = fi_db.open_cross_check(
        conn, "speculator-1", "T0", "speculator", "explorer", "SYN1",
        question="Is there quantitative evidence on SYN1?", requester_finding={"max_confidence": 0.9},
    )

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)

    row = fi_db.get_cross_check(conn, request_id)
    assert row["outcome"] == fi_db.CROSS_CHECK_EVIDENCE
    finding = json.loads(row["responder_finding"])
    assert finding["cleared_threshold"] is True
    assert "stance" not in finding  # Explorer does not judge the asker's evidence


def test_explorer_does_not_re_ask_while_a_question_is_outstanding(conn, monkeypatch):
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", ["SYN1"])
    monkeypatch.setattr("agents.explorer.call_reasoning_model", MagicMock(return_value=judgment_response(True)))
    provider = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}})

    for _ in range(3):
        _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)

    assert len(conn.fetchall("SELECT id FROM cross_check_requests")) == 1


# --- ten securities across explicit peer groups (addendum 8 §4 step 3) ---


def _groups(monkeypatch, groups):
    monkeypatch.setattr("agents.discovery_config.PEER_GROUPS", groups)
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES",
                        [s for members in groups.values() for s in members])
    lookup = {s: name for name, members in groups.items() for s in members}
    monkeypatch.setattr("agents.discovery_config.group_of", lookup.get)
    monkeypatch.setattr("agents.discovery_config.group_members",
                        lambda s: list(groups.get(lookup.get(s), [])))


def test_co_movement_inside_a_group_is_peer(conn, monkeypatch):
    _groups(monkeypatch, {"alpha": ["SYN1", "SYN2"], "beta": ["SYN3", "SYN4"]})
    monkeypatch.setattr("agents.explorer.call_reasoning_model", MagicMock(return_value=judgment_response(True)))
    provider = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}, "SYN2": {}})

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)

    event = fi_db.get_detector_event(conn, 1)
    assert event["scope"] == "peer"
    assert event["peer_group_name"] == "alpha"
    assert json.loads(event["peer_context"])["co_triggering"] == ["SYN2"]


def test_co_movement_across_unrelated_groups_is_not_peer(conn, monkeypatch):
    """The reason grouping exists. Two names moving on two unrelated causes are
    two idiosyncratic events that coincided, not a common factor - and a flat
    single group would call them peers."""
    _groups(monkeypatch, {"alpha": ["SYN1", "SYN2"], "beta": ["SYN3", "SYN4"]})
    monkeypatch.setattr("agents.explorer.call_reasoning_model", MagicMock(return_value=judgment_response(True)))
    provider = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}, "SYN3": {}})

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)

    events = {fi_db.get_detector_event(conn, i)["security"]: fi_db.get_detector_event(conn, i)
              for i in (1, 2)}
    assert events["SYN1"]["scope"] == "individual"
    assert events["SYN3"]["scope"] == "individual"
    # but the wider picture is still recorded, so a market-wide day stays visible
    assert json.loads(events["SYN1"]["peer_context"])["triggering_across_all_groups"] == ["SYN1", "SYN3"]


def test_peer_context_records_the_securitys_own_group_size(conn, monkeypatch):
    """group_size must be the denominator co_triggering is measured against.
    Reporting the total universe there would make one co-trigger out of three
    look like one out of ten."""
    _groups(monkeypatch, {"alpha": ["SYN1", "SYN2"], "beta": ["SYN3", "SYN4", "SYN5"]})
    monkeypatch.setattr("agents.explorer.call_reasoning_model", MagicMock(return_value=judgment_response(True)))
    provider = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}})

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)

    assert json.loads(fi_db.get_detector_event(conn, 1)["peer_context"])["group_size"] == 2


def test_an_ungrouped_security_is_individual_not_a_guess(conn, monkeypatch):
    """A security in no group has no basis for a peer relationship. Classifying
    it 'individual' states that; inventing one would not."""
    _groups(monkeypatch, {"alpha": ["SYN2"]})
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", ["SYN1", "SYN2"])
    monkeypatch.setattr("agents.explorer.call_reasoning_model", MagicMock(return_value=judgment_response(True)))
    provider = SyntheticMarketDataProvider(seed=42, anomalies={"SYN1": {}, "SYN2": {}})

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)

    ungrouped = [fi_db.get_detector_event(conn, i) for i in (1, 2)]
    syn1 = [e for e in ungrouped if e["security"] == "SYN1"][0]
    assert syn1["scope"] == "individual"
    assert syn1["peer_group_name"] is None


def test_the_default_universe_is_ten_securities_in_explicit_groups():
    """Addendum 8 §4 step 3, literally: ten securities, groups plural."""
    from agents import discovery_config

    assert len(discovery_config.PEER_GROUP_SECURITIES) == 10
    assert len(set(discovery_config.PEER_GROUP_SECURITIES)) == 10  # no duplicates
    assert len(discovery_config.PEER_GROUPS) > 1
    for security in discovery_config.PEER_GROUP_SECURITIES:
        assert discovery_config.group_of(security) is not None


def test_peer_groups_parse_from_the_environment():
    from agents.discovery_config import _parse_peer_groups

    assert _parse_peer_groups("a:S1,S2;b:S3") == {"a": ["S1", "S2"], "b": ["S3"]}
    assert _parse_peer_groups("") == {}
    assert _parse_peer_groups("malformed") == {}  # falls back to the default


# --- ARB-001 parity path (SPEC_RECONCILIATION.md SS39-SS41) -----------------


def _store_parity_world(conn, mission_id, seed, tmp_path, **overrides):
    rd.run_reference_engine(conn)
    config = pw.MissionConfig(
        mission_id=mission_id, run_mode="simulation", strategy="put_call_parity_arbitrage",
        seed=seed, **overrides,
    )
    pw.store_world(conn, config, runs_dir=tmp_path)
    return config


def test_explorer_work_records_parity_events_and_opens_cross_checks(conn, monkeypatch, tmp_path):
    """A genuine-only stored mission world, run through the full
    _explorer_work entry point: every scenario's genuine opportunity becomes
    a parity_events row and a cross-check to Speculator, with no LLM call
    (there is no judgment gate for ARB-001 - see _parity_work's docstring)."""
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", [])
    call_model = MagicMock()
    monkeypatch.setattr("agents.explorer.call_reasoning_model", call_model)
    _store_parity_world(conn, "m-exp-parity", seed=7, tmp_path=tmp_path, n_scenarios=4, scenario_mix={"genuine": 1.0})
    provider = SyntheticMarketDataProvider(seed=42)

    _explorer_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00", provider)

    events = conn.fetchall("SELECT * FROM parity_events")
    assert len(events) > 0
    call_model.assert_not_called()

    cross_checks = conn.fetchall(
        "SELECT * FROM cross_check_requests WHERE requester_role = 'explorer' AND responder_role = 'speculator'"
    )
    assert len(cross_checks) == len(events)
    finding = json.loads(cross_checks[0]["requester_finding"])
    assert finding["detector"] == PARITY_DETECTOR_TYPE
    assert finding["parity_event_id"] in {e["id"] for e in events}
    assert finding["direction"] in ("conversion", "reversal")
    assert "net_edge_per_share" in finding


def test_parity_work_with_no_stored_world_is_a_no_op(conn):
    """Activation is data presence (providers/stored_data.py's module
    docstring): reference data is READY, but nothing was ever stored, so
    every focus asset's latest_chain is None and the whole cycle is a no-op."""
    rd.run_reference_engine(conn)

    _parity_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00")

    assert conn.fetchall("SELECT * FROM parity_events") == []
    assert conn.fetchall("SELECT * FROM cross_check_requests") == []


def test_parity_work_traps_only_mission_produces_zero_parity_events(conn, tmp_path):
    """Every trap variant looks like an opportunity at mid prices but clears
    no executable edge (backend/arbitrage.py's own non-negotiable rule) - a
    mission world built entirely from trap variants must detect nothing, for
    any seed: every TRAP_VARIANTS member is a clean-world variant, and
    simulation/parity_world.py's `_build_scenario` redraw guarantees a clean
    variant never lands on the one skew shape ('localized_distortion') that
    could otherwise leak an unrelated cross-strike violation (see
    tests/test_parity_world.py's own redraw tests for the constraint
    itself)."""
    _store_parity_world(
        conn, "m-exp-traps", seed=1, tmp_path=tmp_path, n_scenarios=4,
        scenario_mix={variant: 1.0 for variant in pw.TRAP_VARIANTS},
    )

    _parity_work(conn, "explorer-1", "2026-01-01T00:00:00+00:00")

    assert conn.fetchall("SELECT * FROM parity_events") == []
    assert conn.fetchall("SELECT * FROM cross_check_requests") == []


def test_parity_work_pending_report_suppresses_a_new_cross_check(conn, tmp_path):
    config = _store_parity_world(
        conn, "m-exp-guard-pending", seed=3, tmp_path=tmp_path, n_scenarios=1, scenario_mix={"genuine": 1.0},
    )
    focus_assets = rd.list_focus_assets(conn)
    scenario = pw._build_scenario(config, focus_assets, 0)
    fi_db.enqueue_report(conn, "explorer-1", "T0", "explorer", scenario.symbol, summary="already queued")

    _parity_work(conn, "explorer-1", "T0")

    # the detection is still a real fact even though it does not escalate -
    # the same discipline agents/explorer.py's IV path follows.
    assert len(conn.fetchall("SELECT * FROM parity_events")) == 1
    assert conn.fetchall("SELECT * FROM cross_check_requests") == []


def test_parity_work_open_cross_check_suppresses_a_new_one(conn, tmp_path):
    config = _store_parity_world(
        conn, "m-exp-guard-open", seed=3, tmp_path=tmp_path, n_scenarios=1, scenario_mix={"genuine": 1.0},
    )
    focus_assets = rd.list_focus_assets(conn)
    scenario = pw._build_scenario(config, focus_assets, 0)
    fi_db.open_cross_check(
        conn, "explorer-1", "T0", "explorer", "speculator", scenario.symbol,
        question="unrelated pending question", requester_finding={"note": "pre-existing"},
    )

    _parity_work(conn, "explorer-1", "T0")

    assert len(conn.fetchall("SELECT * FROM parity_events")) == 1
    # only the pre-seeded cross-check exists - no second one opened
    assert len(conn.fetchall("SELECT * FROM cross_check_requests")) == 1


def test_parity_work_recent_analysis_suppresses_a_new_cross_check(conn, tmp_path):
    """The world is static per mission - without this guard, a security
    Analysis already judged would re-trigger a paid Analysis pass every
    remaining cycle of the mission's life (_parity_work's own comment)."""
    config = _store_parity_world(
        conn, "m-exp-guard-analysis", seed=3, tmp_path=tmp_path, n_scenarios=1, scenario_mix={"genuine": 1.0},
    )
    focus_assets = rd.list_focus_assets(conn)
    scenario = pw._build_scenario(config, focus_assets, 0)
    fi_db.record_analysis_result(
        conn, "analysis-1", "T0", 1, scenario.symbol,
        thesis="t", evidence_summary="e", confidence=0.5, uncertainty="u",
        peer_classification="not_applicable",
    )

    _parity_work(conn, "explorer-1", "T0")

    assert len(conn.fetchall("SELECT * FROM parity_events")) == 1
    assert conn.fetchall("SELECT * FROM cross_check_requests") == []


def test_file_cross_checked_parity_report_carries_the_parity_event_id(conn, tmp_path):
    """The other half of the round trip: once Speculator answers, the
    resulting report must carry parity_event_id (not detector_event_id), and
    a summary naming the parity claim."""
    _store_parity_world(
        conn, "m-exp-file", seed=3, tmp_path=tmp_path, n_scenarios=1, scenario_mix={"genuine": 1.0},
    )
    _parity_work(conn, "explorer-1", "T0")
    request = fi_db.fetch_next_pending_cross_check(conn, "speculator")
    assert request is not None
    fi_db.answer_cross_check(
        conn, request["id"], "speculator-1", "T0", fi_db.CROSS_CHECK_NO_EVIDENCE, {"posts": 0},
    )

    # _file_cross_checked_reports, not another _parity_work cycle: filing a
    # resolved cross-check into a report is _explorer_work's shared plumbing
    # (both the IV and parity paths escalate through it), not something
    # _parity_work does on its own.
    _file_cross_checked_reports(conn, "explorer-1", "T0")

    report = fi_db.fetch_next_pending_report(conn)
    assert report is not None
    assert report["detector_event_id"] is None
    assert report["parity_event_id"] is not None
    assert "ARB-001" in report["summary"]


# --- the chain scan becomes the library scan (SS45's deferred item) ---------


def test_parity_work_on_a_cross_bump_world_records_a_non_arb001_event_naming_the_detector(conn, tmp_path):
    """A stored cross_strike_bump world: `_parity_work` now runs scan_chain
    (not per-row detect_arb001), so the single event it records for this
    security is the cross-strike package the injector planted - not
    ARB-001, whose executable edge the same-strike shift never touches by
    construction. seed=1 for this mix draws no 'localized_distortion' skew
    (checked directly)."""
    config = pw.MissionConfig(
        mission_id="m-exp-crossbump", run_mode="simulation", strategy="options_arbitrage_phase1",
        seed=1, n_scenarios=1, scenario_mix={"cross_strike_bump": 1.0},
    )
    rd.run_reference_engine(conn)
    focus_assets = rd.list_focus_assets(conn)
    # store_world assigns focus assets via its own seeded sample
    # (forced_asset), not the plain rng.choice draw - rebuild the exact
    # scenario it stores, the same way tests/test_stored_data.py's own
    # round-trip test does, so this test's expectations match what actually
    # landed in the Data Store.
    assignment = random.Random(f"{config.seed}:assignment").sample(focus_assets, k=config.n_scenarios)
    scenario = pw._build_scenario(config, focus_assets, 0, forced_asset=assignment[0])
    assert scenario.ground_truth.skew_shape != "localized_distortion"
    pw.store_world(conn, config, runs_dir=tmp_path)

    _parity_work(conn, "explorer-1", "T0")

    events = conn.fetchall("SELECT * FROM parity_events")
    assert len(events) == 1
    event = events[0]
    assert event["detector_id"] != "ARB-001"
    k_prev, k_mid = scenario.ground_truth.affected_strikes
    strikes = {event["strike"], event["strike2"], event["strike3"]}
    strikes.discard(None)
    assert k_mid in strikes

    cross_checks = conn.fetchall("SELECT * FROM cross_check_requests")
    assert len(cross_checks) == 1
    finding = json.loads(cross_checks[0]["requester_finding"])
    assert finding["detector_id"] == event["detector_id"]
    assert finding["parity_event_id"] == event["id"]
    question = cross_checks[0]["question"]
    assert event["detector_id"] in question


def test_parity_work_on_a_genuine_world_still_prefers_arb001_unchanged(conn, monkeypatch, tmp_path):
    """Regression: the classic 'genuine' variant's one-legged shift also
    breaks cross-strike bounds against its neighbor as an accepted side
    effect (docs/SPEC_RECONCILIATION.md SS45's second finding) - once
    _parity_work started scanning the whole library, a bigger box/vertical
    edge born from that side effect could otherwise outrank ARB-001's own
    edge and get escalated in its place. `_parity_work`'s ARB-001-preferred
    tiebreak keeps this world's own recorded event exactly what it was
    before this increment: an ARB-001 conversion/reversal, not a
    cross-strike package."""
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", [])
    _store_parity_world(
        conn, "m-exp-parity-unchanged", seed=7, tmp_path=tmp_path, n_scenarios=4, scenario_mix={"genuine": 1.0},
    )

    _parity_work(conn, "explorer-1", "T0")

    events = conn.fetchall("SELECT * FROM parity_events")
    assert len(events) > 0
    for event in events:
        assert event["detector_id"] == "ARB-001"
        assert event["direction"] in ("conversion", "reversal")
        assert event["strike2"] is None
        assert event["strike3"] is None


def test_parity_work_on_a_calendar_world_records_an_arb012_event_with_both_expiries(conn, tmp_path):
    """A stored calendar_bump world (§56): `_parity_work` now also runs
    scan_calendar over the same chains, so the event it records is an
    ARB-012 package carrying both legs' expiries - the near leg in the
    historical expiry_days slot, the far leg in expiry2_days - and the
    escalated finding names the detector."""
    config = pw.MissionConfig(
        mission_id="m-exp-calendar", run_mode="simulation", strategy=pw.STRATEGY_CALENDAR,
        seed=3, n_scenarios=1, scenario_mix={pw.VARIANT_CALENDAR_BUMP: 1.0},
    )
    rd.run_reference_engine(conn)
    pw.store_world(conn, config, runs_dir=tmp_path)

    _parity_work(conn, "explorer-1", "T0")

    events = conn.fetchall("SELECT * FROM parity_events")
    assert len(events) == 1
    event = events[0]
    assert event["detector_id"] == "ARB-012"
    assert event["classification"] == "C"
    assert event["expiry_days"] == pw.EXPIRY_DAYS[0]
    assert event["expiry2_days"] in pw.EXPIRY_DAYS[1:]
    assert event["direction"] in ("put_calendar", "call_calendar")

    cross_checks = conn.fetchall("SELECT * FROM cross_check_requests")
    assert len(cross_checks) == 1
    finding = json.loads(cross_checks[0]["requester_finding"])
    assert finding["detector_id"] == "ARB-012"
    assert finding["expiry2_days"] == event["expiry2_days"]
    question = cross_checks[0]["question"]
    assert "ARB-012" in question
    # Both legs' expiries reach the analyst - §57's live finding: presenting
    # only the near leg made the first live thesis doubt the structure.
    assert f"{event['expiry_days']}d vs {event['expiry2_days']}d" in question
