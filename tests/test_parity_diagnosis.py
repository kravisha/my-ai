"""Tests for simulation/parity_diagnosis.py - addendum 25 SS19's diagnosis
stage. Follows tests/test_parity_evaluation.py's idioms directly: every test
builds the organization's records against the org's own functions
(agents/explorer.py's `_parity_work`/`_file_cross_checked_reports`,
backend/fi_db.py's cross-check/report/analysis functions) rather than a
subprocess or a real LLM, then grades with the real Evaluator before handing
the resulting evaluation to `diagnose_mission`."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agents.explorer import _file_cross_checked_reports, _parity_work
from backend import fi_db
from backend import reference_data as rd
from simulation import parity_diagnosis as pdiag
from simulation import parity_evaluation as pe
from simulation import parity_world as pw
from simulation.__main__ import main as cli_main


def _store_parity_world(conn, mission_id, seed, tmp_path, **overrides):
    rd.run_reference_engine(conn)
    config = pw.MissionConfig(
        mission_id=mission_id, run_mode="simulation", strategy="put_call_parity_arbitrage",
        seed=seed, **overrides,
    )
    result = pw.store_world(conn, config, runs_dir=tmp_path)
    return config, result["summary_path"]


def _answer_all_cross_checks(conn):
    while True:
        request = fi_db.fetch_next_pending_cross_check(conn, "speculator")
        if request is None:
            break
        fi_db.answer_cross_check(
            conn, request["id"], "speculator-1", "T0", fi_db.CROSS_CHECK_NO_EVIDENCE, {"posts": 0},
        )


def _complete_all_reports_with_analysis(conn):
    for report in fi_db.list_pending_reports(conn):
        fi_db.complete_report(conn, report["id"], "analyzed", "analysis-1", "T0", detail="ok")
        fi_db.record_analysis_result(
            conn, "analysis-1", "T0", report["id"], report["security"],
            thesis="t", evidence_summary="e", confidence=0.8, uncertainty="u",
            peer_classification="not_applicable",
        )


def _by_scenario_id(diagnosis):
    return {entry["scenario_id"]: entry for entry in diagnosis["scenarios"]}


def _corrective_by_cause(diagnosis):
    return {item["cause"]: item for item in diagnosis["corrective_items"]}


# --- 1. all-PASS mission --------------------------------------------------------


def test_all_pass_mission_certified_complete(conn, tmp_path):
    config, summary_path = _store_parity_world(
        conn, "m-diag-allpass", seed=11, tmp_path=tmp_path, n_scenarios=4, scenario_mix={"genuine": 1.0},
    )
    _parity_work(conn, "explorer-1", "T0")
    _answer_all_cross_checks(conn)
    _file_cross_checked_reports(conn, "explorer-1", "T0")
    _complete_all_reports_with_analysis(conn)

    evaluation = pe.evaluate_mission(conn, summary_path)
    assert evaluation["metrics"]["by_outcome"] == {"PASS": 4, "PARTIAL": 0, "FAIL": 0, "INCONCLUSIVE": 0}

    diagnosis = pdiag.diagnose_mission(conn, evaluation["evaluation_path"])

    assert diagnosis["scenarios"] == []
    assert diagnosis["corrective_items"] == []
    assert diagnosis["mission_certified_complete"] is True
    assert diagnosis["retry_recommended"] is False
    assert diagnosis["wait_and_reevaluate"] is False

    # 11: written beside the evaluation, json-loadable, correctly named.
    evaluation_path = Path(evaluation["evaluation_path"])
    diagnosis_path = Path(diagnosis["diagnosis_path"])
    assert diagnosis_path.parent == evaluation_path.parent
    assert diagnosis_path.name == evaluation_path.stem[: -len(".evaluation")] + ".diagnosis.json"
    reloaded = json.loads(diagnosis_path.read_text(encoding="utf-8"))
    assert reloaded["mission_certified_complete"] is True
    assert "diagnosis_path" not in reloaded


# --- 2. explorer_missed, and (10) corrective grouping -------------------------


def test_explorer_missed_and_corrective_grouping(conn, tmp_path):
    """store_world only, nothing run: the injected genuine edge is sitting
    on the stored chain and Explorer's scan never ran at all, so the offline
    differential finds it while parity_events stays empty. Two scenarios
    share the cause, which must collapse to one corrective item (#10)."""
    config, summary_path = _store_parity_world(
        conn, "m-diag-missed", seed=11, tmp_path=tmp_path, n_scenarios=2, scenario_mix={"genuine": 1.0},
    )

    evaluation = pe.evaluate_mission(conn, summary_path)
    for entry in evaluation["scenarios"]:
        assert entry["outcome"] == "FAIL"
        assert entry["reasons"] == ["missed"]

    diagnosis = pdiag.diagnose_mission(conn, evaluation["evaluation_path"])

    assert len(diagnosis["scenarios"]) == 2
    for entry in diagnosis["scenarios"]:
        assert entry["causes"] == [pdiag.CAUSE_EXPLORER_MISSED]
        assert entry["component"] == pdiag.COMPONENT_EXPLORER
        assert entry["notes"]["offline_opportunity_count"] >= 1

    items = _corrective_by_cause(diagnosis)
    assert set(items) == {pdiag.CAUSE_EXPLORER_MISSED}
    item = items[pdiag.CAUSE_EXPLORER_MISSED]
    assert item["classification"] == pdiag.CLASS_AGENT
    assert sorted(item["scenarios"]) == sorted(e["scenario_id"] for e in evaluation["scenarios"])

    assert diagnosis["mission_certified_complete"] is False
    assert diagnosis["retry_recommended"] is True
    assert diagnosis["retry_guidance"]["rerun_same_seed"] is True
    assert diagnosis["retry_guidance"]["adjust_world_first"] is False
    assert diagnosis["wait_and_reevaluate"] is False


# --- 3. insufficient_signal ------------------------------------------------------


def test_insufficient_signal(conn, tmp_path):
    """A clean ('none') world, with the summary's own ground truth doctored
    to claim a genuine opportunity that was never actually injected. The
    Evaluator grades FAIL('missed') against the doctored expectation; the
    offline detector, re-run over the (truly clean) stored chain, agrees
    with the chain rather than the doctored ground truth - insufficient
    signal, not a missed detection."""
    config, summary_path = _store_parity_world(
        conn, "m-diag-insufficient", seed=9, tmp_path=tmp_path, n_scenarios=1, scenario_mix={"none": 1.0},
    )
    summary_path = Path(summary_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    gt = summary["scenarios"][0]["ground_truth"]
    assert gt["variant"] == pw.VARIANT_NONE
    gt["variant"] = pw.VARIANT_GENUINE
    gt["expected_executable"] = True
    gt["expected_direction"] = "conversion"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    evaluation = pe.evaluate_mission(conn, str(summary_path))
    assert evaluation["scenarios"][0]["outcome"] == "FAIL"
    assert evaluation["scenarios"][0]["reasons"] == ["missed"]

    diagnosis = pdiag.diagnose_mission(conn, evaluation["evaluation_path"])
    entry = diagnosis["scenarios"][0]
    assert entry["causes"] == [pdiag.CAUSE_INSUFFICIENT_SIGNAL]
    assert entry["component"] == pdiag.COMPONENT_SIMULATION_ENGINE
    assert entry["notes"]["offline_opportunity_count"] == 0

    item = diagnosis["corrective_items"][0]
    assert item["cause"] == pdiag.CAUSE_INSUFFICIENT_SIGNAL
    assert item["classification"] == pdiag.CLASS_WORLD
    assert diagnosis["retry_recommended"] is True
    assert diagnosis["retry_guidance"]["adjust_world_first"] is True
    assert diagnosis["retry_guidance"]["rerun_same_seed"] is False


# --- 4. trap_not_erased / world_not_clean -----------------------------------------


def test_trap_not_erased_and_world_not_clean(conn, tmp_path):
    """The converse doctoring: a genuinely-injected world (the stored chain
    truly carries an executable edge), with the summary relabelling one
    scenario as a trap and another as 'none', each with a parity_events row
    planted directly - simulating something having detected on what ground
    truth now claims should have been clean. The offline detector, run over
    the real (still genuine) chain, still finds the edge: the erasure this
    cause names never happened, because there was never anything erasing it."""
    config, summary_path = _store_parity_world(
        conn, "m-diag-trapnotclean", seed=11, tmp_path=tmp_path, n_scenarios=2, scenario_mix={"genuine": 1.0},
    )
    summary_path = Path(summary_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    trap_entry, none_entry = summary["scenarios"][0], summary["scenarios"][1]
    trap_entry["ground_truth"]["variant"] = pw.VARIANT_SPREAD_ARTIFACT
    none_entry["ground_truth"]["variant"] = pw.VARIANT_NONE
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    for entry in (trap_entry, none_entry):
        gt = entry["ground_truth"]
        fi_db.record_parity_event(
            conn, "explorer-1", "T0", gt["entity_id"], gt["symbol"],
            strike=gt["affected_strike"] or 100.0, expiry_days=gt["affected_expiry_days"] or 30,
            direction="conversion", gross_edge_per_share=1.0, net_edge_per_share=0.5,
            classification="A", capacity_units=10.0, observed_at="2026-01-05T14:30:00+00:00",
            run_id=config.mission_id, scenario_id=entry["scenario_id"],
        )

    evaluation = pe.evaluate_mission(conn, str(summary_path))
    by_id = _by_scenario_id_eval(evaluation)
    assert by_id[trap_entry["scenario_id"]]["outcome"] == "FAIL"
    assert by_id[trap_entry["scenario_id"]]["reasons"] == ["trap_leaked"]
    assert by_id[none_entry["scenario_id"]]["outcome"] == "FAIL"
    assert by_id[none_entry["scenario_id"]]["reasons"] == ["false_positive"]

    diagnosis = pdiag.diagnose_mission(conn, evaluation["evaluation_path"])
    diag_by_id = _by_scenario_id(diagnosis)
    assert diag_by_id[trap_entry["scenario_id"]]["causes"] == [pdiag.CAUSE_TRAP_NOT_ERASED]
    assert diag_by_id[none_entry["scenario_id"]]["causes"] == [pdiag.CAUSE_WORLD_NOT_CLEAN]
    for scenario_id in (trap_entry["scenario_id"], none_entry["scenario_id"]):
        assert diag_by_id[scenario_id]["component"] == pdiag.COMPONENT_SIMULATION_ENGINE
        assert diag_by_id[scenario_id]["notes"]["offline_opportunity_count"] >= 1

    items = _corrective_by_cause(diagnosis)
    assert items[pdiag.CAUSE_TRAP_NOT_ERASED]["classification"] == pdiag.CLASS_WORLD
    assert items[pdiag.CAUSE_WORLD_NOT_CLEAN]["classification"] == pdiag.CLASS_WORLD


def _by_scenario_id_eval(evaluation):
    return {entry["scenario_id"]: entry for entry in evaluation["scenarios"]}


# --- 5. detector_interface_drift --------------------------------------------------


def test_detector_interface_drift(conn, tmp_path):
    """A genuinely clean world, honest ground truth, but a parity_events row
    planted directly for the scenario - a phantom detection with nothing on
    the stored chain to back it. The offline detector, re-run over the same
    rows, finds nothing: the disagreement is between Explorer's recorded
    detection and the detector itself, not between the world and the agent."""
    config, summary_path = _store_parity_world(
        conn, "m-diag-interfacedrift", seed=9, tmp_path=tmp_path, n_scenarios=1, scenario_mix={"none": 1.0},
    )
    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    scenario = summary["scenarios"][0]
    gt = scenario["ground_truth"]
    assert gt["variant"] == pw.VARIANT_NONE

    fi_db.record_parity_event(
        conn, "explorer-1", "T0", gt["entity_id"], gt["symbol"],
        strike=100.0, expiry_days=30, direction="conversion", gross_edge_per_share=1.0,
        net_edge_per_share=0.5, classification="A", capacity_units=10.0,
        observed_at="2026-01-05T14:30:00+00:00", run_id=config.mission_id,
        scenario_id=scenario["scenario_id"],
    )

    evaluation = pe.evaluate_mission(conn, summary_path)
    assert evaluation["scenarios"][0]["outcome"] == "FAIL"
    assert evaluation["scenarios"][0]["reasons"] == ["false_positive"]

    diagnosis = pdiag.diagnose_mission(conn, evaluation["evaluation_path"])
    entry = diagnosis["scenarios"][0]
    assert entry["causes"] == [pdiag.CAUSE_DETECTOR_INTERFACE_DRIFT]
    assert entry["component"] == pdiag.COMPONENT_INTERFACE
    assert entry["notes"]["offline_opportunity_count"] == 0

    item = diagnosis["corrective_items"][0]
    assert item["classification"] == pdiag.CLASS_WORLD


# --- 6. cross_check_in_flight ------------------------------------------------------


def test_cross_check_in_flight(conn, tmp_path):
    config, summary_path = _store_parity_world(
        conn, "m-diag-crosscheckflight", seed=3, tmp_path=tmp_path, n_scenarios=2, scenario_mix={"genuine": 1.0},
    )
    _parity_work(conn, "explorer-1", "T0")

    evaluation = pe.evaluate_mission(conn, summary_path)
    for entry in evaluation["scenarios"]:
        assert entry["outcome"] == "PARTIAL"
        assert entry["reasons"] == ["detected_not_escalated"]

    diagnosis = pdiag.diagnose_mission(conn, evaluation["evaluation_path"])
    for entry in diagnosis["scenarios"]:
        assert entry["causes"] == [pdiag.CAUSE_CROSS_CHECK_IN_FLIGHT]
        assert entry["component"] == pdiag.COMPONENT_NONE

    item = diagnosis["corrective_items"][0]
    assert item["classification"] == pdiag.CLASS_IN_FLIGHT
    assert diagnosis["wait_and_reevaluate"] is True
    assert diagnosis["retry_recommended"] is False
    assert diagnosis["mission_certified_complete"] is False


# --- 7. analysis_in_flight, then analysis_stalled after backdating ---------------


def test_analysis_in_flight_then_stalled(conn, tmp_path):
    config, summary_path = _store_parity_world(
        conn, "m-diag-analysisflight", seed=3, tmp_path=tmp_path, n_scenarios=2, scenario_mix={"genuine": 1.0},
    )
    _parity_work(conn, "explorer-1", "T0")
    _answer_all_cross_checks(conn)
    _file_cross_checked_reports(conn, "explorer-1", "T0")
    # deliberately no complete_report/record_analysis_result

    evaluation = pe.evaluate_mission(conn, summary_path)
    for entry in evaluation["scenarios"]:
        assert entry["outcome"] == "INCONCLUSIVE"
        assert entry["reasons"] == ["analysis_in_flight"]

    diagnosis = pdiag.diagnose_mission(conn, evaluation["evaluation_path"])
    for entry in diagnosis["scenarios"]:
        assert entry["causes"] == [pdiag.CAUSE_ANALYSIS_IN_FLIGHT]
        assert entry["component"] == pdiag.COMPONENT_NONE
    item = _corrective_by_cause(diagnosis)[pdiag.CAUSE_ANALYSIS_IN_FLIGHT]
    assert item["classification"] == pdiag.CLASS_IN_FLIGHT
    assert diagnosis["retry_recommended"] is False
    assert diagnosis["wait_and_reevaluate"] is True

    # Backdate every pending report beyond the stall threshold.
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=pdiag.ANALYSIS_STALL_SECONDS + 30)).isoformat()
    conn.execute("UPDATE discovery_reports SET created_at = ?", (cutoff,))

    diagnosis2 = pdiag.diagnose_mission(conn, evaluation["evaluation_path"])
    for entry in diagnosis2["scenarios"]:
        assert entry["causes"] == [pdiag.CAUSE_ANALYSIS_STALLED]
        assert entry["component"] == pdiag.COMPONENT_ANALYSIS
    item2 = _corrective_by_cause(diagnosis2)[pdiag.CAUSE_ANALYSIS_STALLED]
    assert item2["classification"] == pdiag.CLASS_AGENT
    assert diagnosis2["retry_recommended"] is True
    assert diagnosis2["retry_guidance"]["rerun_same_seed"] is True


# --- 8. world_not_stored -----------------------------------------------------------


def test_world_not_stored(conn, tmp_path):
    config, summary_path = _store_parity_world(
        conn, "m-diag-notstored", seed=11, tmp_path=tmp_path, n_scenarios=1, scenario_mix={"genuine": 1.0},
    )
    evaluation = pe.evaluate_mission(conn, summary_path)
    assert evaluation["scenarios"][0]["outcome"] == "FAIL"

    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    entity_id = summary["scenarios"][0]["ground_truth"]["entity_id"]
    conn.execute("DELETE FROM observations WHERE entity_id = ? AND data_class = 'option_chain'", (entity_id,))

    diagnosis = pdiag.diagnose_mission(conn, evaluation["evaluation_path"])
    entry = diagnosis["scenarios"][0]
    assert entry["causes"] == [pdiag.CAUSE_WORLD_NOT_STORED]
    assert entry["component"] == pdiag.COMPONENT_SIMULATION_ENGINE

    item = diagnosis["corrective_items"][0]
    assert item["classification"] == pdiag.CLASS_WORLD
    assert diagnosis["retry_guidance"]["adjust_world_first"] is True


# --- 9. explorer_filing_failure -----------------------------------------------------


def test_explorer_filing_failure(conn, tmp_path):
    """The cross-check is answered directly (fi_db.answer_cross_check),
    leaving it 'resolved' - the honest state for an answer that arrived with
    nothing having consumed it into a report - without ever calling
    _file_cross_checked_reports."""
    config, summary_path = _store_parity_world(
        conn, "m-diag-filingfail", seed=3, tmp_path=tmp_path, n_scenarios=1, scenario_mix={"genuine": 1.0},
    )
    _parity_work(conn, "explorer-1", "T0")
    _answer_all_cross_checks(conn)

    evaluation = pe.evaluate_mission(conn, summary_path)
    assert evaluation["scenarios"][0]["outcome"] == "PARTIAL"
    assert evaluation["scenarios"][0]["reasons"] == ["detected_not_escalated"]

    diagnosis = pdiag.diagnose_mission(conn, evaluation["evaluation_path"])
    entry = diagnosis["scenarios"][0]
    assert entry["causes"] == [pdiag.CAUSE_EXPLORER_FILING_FAILURE]
    assert entry["component"] == pdiag.COMPONENT_EXPLORER

    item = diagnosis["corrective_items"][0]
    assert item["classification"] == pdiag.CLASS_AGENT
    assert diagnosis["retry_recommended"] is True


# --- CLI exit-code semantics --------------------------------------------------------


def test_cli_exit_code_zero_when_certified_complete(tmp_path):
    db_path = tmp_path / "cli-pass.db"
    conn = fi_db.get_connection(db_path)
    fi_db.init_schema(conn)
    try:
        config, summary_path = _store_parity_world(
            conn, "m-diag-cli-pass", seed=11, tmp_path=tmp_path, n_scenarios=4, scenario_mix={"genuine": 1.0},
        )
        _parity_work(conn, "explorer-1", "T0")
        _answer_all_cross_checks(conn)
        _file_cross_checked_reports(conn, "explorer-1", "T0")
        _complete_all_reports_with_analysis(conn)
        evaluation = pe.evaluate_mission(conn, summary_path)
        assert evaluation["metrics"]["strategy_exercised"] is True
    finally:
        conn.close()

    exit_code = cli_main(["parity-diagnose", evaluation["evaluation_path"], "--db", str(db_path)])
    assert exit_code == 0


def test_cli_exit_code_zero_when_only_in_flight(tmp_path):
    db_path = tmp_path / "cli-inflight.db"
    conn = fi_db.get_connection(db_path)
    fi_db.init_schema(conn)
    try:
        config, summary_path = _store_parity_world(
            conn, "m-diag-cli-inflight", seed=3, tmp_path=tmp_path, n_scenarios=1, scenario_mix={"genuine": 1.0},
        )
        _parity_work(conn, "explorer-1", "T0")
        evaluation = pe.evaluate_mission(conn, summary_path)
        assert evaluation["scenarios"][0]["reasons"] == ["detected_not_escalated"]
    finally:
        conn.close()

    exit_code = cli_main(["parity-diagnose", evaluation["evaluation_path"], "--db", str(db_path)])
    assert exit_code == 0


def test_cli_exit_code_two_when_retry_recommended(tmp_path):
    db_path = tmp_path / "cli-retry.db"
    conn = fi_db.get_connection(db_path)
    fi_db.init_schema(conn)
    try:
        config, summary_path = _store_parity_world(
            conn, "m-diag-cli-retry", seed=11, tmp_path=tmp_path, n_scenarios=1, scenario_mix={"genuine": 1.0},
        )
        evaluation = pe.evaluate_mission(conn, summary_path)
        assert evaluation["scenarios"][0]["reasons"] == ["missed"]
    finally:
        conn.close()

    exit_code = cli_main(["parity-diagnose", evaluation["evaluation_path"], "--db", str(db_path)])
    assert exit_code == 2
