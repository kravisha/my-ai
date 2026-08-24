"""Tests for simulation/parity_evaluation.py - the Evaluator's grading pass
(addendum 25 SS16-SS19). Every test builds the organization's records
directly against the org's own functions (agents/explorer.py's
`_parity_work`/`_file_cross_checked_reports`, backend/fi_db.py's
cross-check/report/analysis functions) rather than through a subprocess or a
real LLM - the parity detector path itself makes no LLM calls
(`_parity_work`'s own docstring), and the analysis/cross-check steps are
planted the same way tests/test_explorer.py plants them."""

import json
from pathlib import Path

from agents.explorer import _file_cross_checked_reports, _parity_work
from backend import fi_db
from backend import reference_data as rd
from simulation import parity_evaluation as pe
from simulation import parity_world as pw


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
    """Complete every pending report and record an analysis result for it -
    the record agents/analysis.py leaves behind, planted directly rather
    than through the real agent."""
    for report in fi_db.list_pending_reports(conn):
        fi_db.complete_report(conn, report["id"], "analyzed", "analysis-1", "T0", detail="ok")
        fi_db.record_analysis_result(
            conn, "analysis-1", "T0", report["id"], report["security"],
            thesis="t", evidence_summary="e", confidence=0.8, uncertainty="u",
            peer_classification="not_applicable",
        )


def _by_scenario_id(evaluation):
    return {entry["scenario_id"]: entry for entry in evaluation["scenarios"]}


# --- full completion loop -----------------------------------------------------


def test_full_chain_reaches_pass(conn, tmp_path):
    """detected -> escalated -> cross-checked -> reported -> analyzed, every
    genuine scenario's direction matching ground truth: PASS end to end."""
    config, summary_path = _store_parity_world(
        conn, "m-eval-full", seed=11, tmp_path=tmp_path, n_scenarios=4, scenario_mix={"genuine": 1.0},
    )
    _parity_work(conn, "explorer-1", "T0")
    _answer_all_cross_checks(conn)
    _file_cross_checked_reports(conn, "explorer-1", "T0")
    _complete_all_reports_with_analysis(conn)

    evaluation = pe.evaluate_mission(conn, summary_path)

    assert evaluation["mission_id"] == "m-eval-full"
    assert len(evaluation["scenarios"]) == 4
    for entry in evaluation["scenarios"]:
        assert entry["outcome"] == "PASS", entry
        assert entry["reasons"] == []
        assert entry["counts"]["detections"] >= 1
        assert entry["counts"]["reports"] >= 1
        assert entry["counts"]["analyses"] >= 1
        assert entry["detected_direction"] == entry["expected_direction"] == "conversion"

    metrics = evaluation["metrics"]
    assert metrics["pass_rate"] == 1.0
    assert metrics["genuine_detected"] == 4
    assert metrics["genuine_missed"] == 0
    assert metrics["false_positives"] == 0
    assert metrics["strategy_exercised"] is True
    assert metrics["retry_required"] is False
    assert metrics["by_outcome"] == {"PASS": 4, "PARTIAL": 0, "FAIL": 0, "INCONCLUSIVE": 0}

    # the evaluation file lands beside the summary, loadable, and does not
    # itself carry evaluation_path (that's only in the returned dict).
    evaluation_path = Path(evaluation["evaluation_path"])
    assert evaluation_path.parent == Path(summary_path).parent
    assert evaluation_path.name == Path(summary_path).stem + ".evaluation.json"
    reloaded = json.loads(evaluation_path.read_text(encoding="utf-8"))
    assert reloaded["mission_id"] == "m-eval-full"
    assert reloaded["scenarios"] == evaluation["scenarios"]
    assert reloaded["metrics"] == evaluation["metrics"]
    assert "evaluation_path" not in reloaded


# --- nothing ran ---------------------------------------------------------------


def test_nothing_ran_genuine_missed_others_pass(conn, tmp_path):
    """store_world only, no detector cycle at all: every genuine scenario
    FAIL('missed') since ARB-001 never ran; every trap/none scenario PASS
    since nothing false-fired either. seed=13 with this mix is a fixed,
    deterministic draw of 5 genuine + 1 none (checked directly), so both
    branches are exercised without relying on chance."""
    config, summary_path = _store_parity_world(
        conn, "m-eval-idle", seed=13, tmp_path=tmp_path, n_scenarios=6,
        scenario_mix={"genuine": 1.0, "none": 1.0},
    )

    evaluation = pe.evaluate_mission(conn, summary_path)

    genuine = [s for s in evaluation["scenarios"] if s["variant"] == pw.VARIANT_GENUINE]
    others = [s for s in evaluation["scenarios"] if s["variant"] != pw.VARIANT_GENUINE]
    assert genuine, "expected at least one genuine scenario in this fixed draw"
    assert others, "expected at least one non-genuine scenario in this fixed draw"
    for entry in genuine:
        assert entry["outcome"] == "FAIL"
        assert entry["reasons"] == ["missed"]
        assert entry["counts"] == {"detections": 0, "reports": 0, "analyses": 0}
    for entry in others:
        assert entry["outcome"] == "PASS"
        assert entry["reasons"] == []

    metrics = evaluation["metrics"]
    assert metrics["strategy_exercised"] is False
    assert metrics["retry_required"] is True
    assert metrics["genuine_detected"] == 0
    assert metrics["genuine_missed"] == len(genuine)
    assert metrics["false_positives"] == 0
    assert sum(metrics["by_outcome"].values()) == len(evaluation["scenarios"]) == config.n_scenarios


# --- detected but not escalated -------------------------------------------------


def test_detected_not_escalated_is_partial(conn, tmp_path):
    """_parity_work runs and opens the cross-check, but nothing answers it
    and no report is ever filed: a real detection with no escalation."""
    _store_parity_world_result = _store_parity_world(
        conn, "m-eval-partial", seed=3, tmp_path=tmp_path, n_scenarios=2, scenario_mix={"genuine": 1.0},
    )
    config, summary_path = _store_parity_world_result
    _parity_work(conn, "explorer-1", "T0")

    evaluation = pe.evaluate_mission(conn, summary_path)

    for entry in evaluation["scenarios"]:
        assert entry["outcome"] == "PARTIAL"
        assert entry["reasons"] == ["detected_not_escalated"]
        assert entry["counts"]["detections"] >= 1
        assert entry["counts"]["reports"] == 0
        assert entry["counts"]["analyses"] == 0
    assert evaluation["metrics"]["strategy_exercised"] is False
    assert evaluation["metrics"]["retry_required"] is True


# --- report filed, analysis still pending --------------------------------------


def test_report_without_analysis_is_inconclusive(conn, tmp_path):
    config, summary_path = _store_parity_world(
        conn, "m-eval-inflight", seed=3, tmp_path=tmp_path, n_scenarios=2, scenario_mix={"genuine": 1.0},
    )
    _parity_work(conn, "explorer-1", "T0")
    _answer_all_cross_checks(conn)
    _file_cross_checked_reports(conn, "explorer-1", "T0")
    # deliberately no complete_report/record_analysis_result

    evaluation = pe.evaluate_mission(conn, summary_path)

    for entry in evaluation["scenarios"]:
        assert entry["outcome"] == "INCONCLUSIVE"
        assert entry["reasons"] == ["analysis_in_flight"]
        assert entry["counts"]["reports"] >= 1
        assert entry["counts"]["analyses"] == 0
    assert evaluation["metrics"]["strategy_exercised"] is False
    assert evaluation["metrics"]["retry_required"] is True
    assert evaluation["metrics"]["by_outcome"]["INCONCLUSIVE"] == 2


# --- trap leak -------------------------------------------------------------------


def test_trap_leak_fails_only_the_leaking_scenario(conn, tmp_path):
    """A trap-only mission, with a parity_events row planted directly for one
    scenario - simulating a detector defect that fired on a trap. Only that
    scenario fails; the untouched trap scenarios still correctly detected
    nothing and PASS."""
    config, summary_path = _store_parity_world(
        conn, "m-eval-trapleak", seed=5, tmp_path=tmp_path, n_scenarios=3,
        scenario_mix={variant: 1.0 for variant in pw.TRAP_VARIANTS},
    )
    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    leaking = summary["scenarios"][0]
    gt = leaking["ground_truth"]
    assert gt["variant"] in pw.TRAP_VARIANTS

    fi_db.record_parity_event(
        conn, "explorer-1", "T0", gt["entity_id"], gt["symbol"],
        strike=gt["affected_strike"] or 100.0, expiry_days=gt["affected_expiry_days"] or 30,
        direction="conversion", gross_edge_per_share=1.0, net_edge_per_share=0.5,
        classification="A", capacity_units=10.0, observed_at="2026-01-05T14:30:00+00:00",
        run_id=config.mission_id, scenario_id=leaking["scenario_id"],
    )

    evaluation = pe.evaluate_mission(conn, summary_path)
    by_id = _by_scenario_id(evaluation)

    assert by_id[leaking["scenario_id"]]["outcome"] == "FAIL"
    assert by_id[leaking["scenario_id"]]["reasons"] == ["trap_leaked"]
    for entry in evaluation["scenarios"]:
        if entry["scenario_id"] != leaking["scenario_id"]:
            assert entry["outcome"] == "PASS"
    assert evaluation["metrics"]["false_positives"] == 1


def test_false_positive_on_none_variant(conn, tmp_path):
    """The 'none' variant's own trap: a detection here is a plain false
    positive, not a trap-leak - distinct reason code, same FAIL outcome."""
    config, summary_path = _store_parity_world(
        conn, "m-eval-falsepos", seed=9, tmp_path=tmp_path, n_scenarios=1, scenario_mix={"none": 1.0},
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


# --- wrong direction -------------------------------------------------------------


def test_wrong_direction_is_partial_not_pass(conn, tmp_path):
    """The full chain completes - detected, escalated, analyzed - but the
    recorded direction is flipped from what ground truth expects. A full
    chain with the wrong answer is not a PASS."""
    config, summary_path = _store_parity_world(
        conn, "m-eval-wrongdir", seed=17, tmp_path=tmp_path, n_scenarios=1, scenario_mix={"genuine": 1.0},
    )
    _parity_work(conn, "explorer-1", "T0")
    _answer_all_cross_checks(conn)
    _file_cross_checked_reports(conn, "explorer-1", "T0")
    _complete_all_reports_with_analysis(conn)

    # every genuine scenario's ground truth expects 'conversion'
    # (simulation/parity_world.py's _build_scenario) - flip the actually
    # recorded detection to 'reversal' so the chain's answer disagrees.
    conn.execute("UPDATE parity_events SET direction = 'reversal' WHERE direction = 'conversion'")

    evaluation = pe.evaluate_mission(conn, summary_path)

    entry = evaluation["scenarios"][0]
    assert entry["outcome"] == "PARTIAL"
    assert entry["reasons"] == ["wrong_direction"]
    assert entry["detected_direction"] == "reversal"
    assert entry["expected_direction"] == "conversion"
    assert evaluation["metrics"]["strategy_exercised"] is False


# --- metrics sanity ---------------------------------------------------------------


def test_metrics_counts_sum_to_scenario_count(conn, tmp_path):
    config, summary_path = _store_parity_world(
        conn, "m-eval-metrics", seed=21, tmp_path=tmp_path, n_scenarios=5,
        scenario_mix={"genuine": 1.0, "spread_artifact": 1.0, "none": 1.0},
    )
    _parity_work(conn, "explorer-1", "T0")
    _answer_all_cross_checks(conn)
    _file_cross_checked_reports(conn, "explorer-1", "T0")
    _complete_all_reports_with_analysis(conn)

    evaluation = pe.evaluate_mission(conn, summary_path)

    assert sum(evaluation["metrics"]["by_outcome"].values()) == config.n_scenarios == 5
    assert len(evaluation["scenarios"]) == 5


# --- cross-strike family (docs/SPEC_RECONCILIATION.md SS45's deferred item) -


def _store_cross_world(conn, mission_id, seed, tmp_path, **overrides):
    rd.run_reference_engine(conn)
    config = pw.MissionConfig(
        mission_id=mission_id, run_mode="simulation", strategy="options_arbitrage_phase1",
        seed=seed, **overrides,
    )
    result = pw.store_world(conn, config, runs_dir=tmp_path)
    return config, result["summary_path"]


def test_cross_genuine_full_chain_reaches_pass(conn, tmp_path):
    """detected (a non-ARB-001 package) -> escalated -> cross-checked ->
    reported -> analyzed: PASS, with no direction to compare (expected_
    direction is None for the cross-strike family)."""
    config, summary_path = _store_cross_world(
        conn, "m-eval-crossbump", seed=1, tmp_path=tmp_path, n_scenarios=4, scenario_mix={"cross_strike_bump": 1.0},
    )
    _parity_work(conn, "explorer-1", "T0")
    _answer_all_cross_checks(conn)
    _file_cross_checked_reports(conn, "explorer-1", "T0")
    _complete_all_reports_with_analysis(conn)

    evaluation = pe.evaluate_mission(conn, summary_path)

    for entry in evaluation["scenarios"]:
        assert entry["outcome"] == "PASS", entry
        assert entry["reasons"] == []
        assert entry["counts"]["detections"] >= 1
        assert entry["detected_direction"] is None
        assert entry["expected_direction"] is None
    assert evaluation["metrics"]["strategy_exercised"] is True


def test_cross_unexpected_parity_hit_planted_fails(conn, tmp_path):
    """A parity_events row planted directly with detector_id='ARB-001' for a
    cross-strike scenario - simulating a world-integrity failure (the
    injector leaked an ARB-001 edge it should never have created) - fails
    the scenario regardless of the real cross-strike detection also
    present."""
    config, summary_path = _store_cross_world(
        conn, "m-eval-unexpected", seed=1, tmp_path=tmp_path, n_scenarios=4, scenario_mix={"cross_strike_bump": 1.0},
    )
    _parity_work(conn, "explorer-1", "T0")

    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    scenario_entry = summary["scenarios"][0]
    gt = scenario_entry["ground_truth"]
    fi_db.record_parity_event(
        conn, "explorer-1", "T0", gt["entity_id"], gt["symbol"],
        strike=gt["affected_strike"], expiry_days=30, direction="conversion",
        gross_edge_per_share=0.10, net_edge_per_share=0.05, classification="A", capacity_units=10.0,
        observed_at="2026-01-05T14:30:00+00:00", run_id=config.mission_id, scenario_id=scenario_entry["scenario_id"],
        detector_id="ARB-001",
    )

    evaluation = pe.evaluate_mission(conn, summary_path)
    by_id = {e["scenario_id"]: e for e in evaluation["scenarios"]}
    assert by_id[scenario_entry["scenario_id"]]["outcome"] == "FAIL"
    assert by_id[scenario_entry["scenario_id"]]["reasons"] == ["unexpected_parity_hit"]


def test_cross_stray_detection_planted_fails(conn, tmp_path):
    """A non-ARB-001 parity_events row planted directly whose strikes do not
    include the scenario's primary affected strike - a stray the injector
    should never have produced - fails distinctly from an unexpected parity
    hit."""
    config, summary_path = _store_cross_world(
        conn, "m-eval-stray", seed=1, tmp_path=tmp_path, n_scenarios=1, scenario_mix={"cross_strike_bump": 1.0},
    )
    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    scenario_entry = summary["scenarios"][0]
    gt = scenario_entry["ground_truth"]
    primary = gt["affected_strike"]
    away_strike = primary + 1000.0  # guaranteed not to equal the primary strike

    fi_db.record_parity_event(
        conn, "explorer-1", "T0", gt["entity_id"], gt["symbol"],
        strike=away_strike, expiry_days=30, direction="monotonicity_calls",
        gross_edge_per_share=0.10, net_edge_per_share=0.05, classification="A", capacity_units=10.0,
        observed_at="2026-01-05T14:30:00+00:00", run_id=config.mission_id, scenario_id=scenario_entry["scenario_id"],
        detector_id="ARB-011", strike2=away_strike + 5.0,
    )

    evaluation = pe.evaluate_mission(conn, summary_path)
    entry = evaluation["scenarios"][0]
    assert entry["outcome"] == "FAIL"
    assert entry["reasons"] == ["stray_detection"]


def test_cross_trap_clean_passes(conn, tmp_path):
    config, summary_path = _store_cross_world(
        conn, "m-eval-crosstrap", seed=1, tmp_path=tmp_path, n_scenarios=4,
        scenario_mix={"cross_strike_spread_artifact": 1.0},
    )
    # No agent work at all - a trap variant's answer key is "detect nothing".

    evaluation = pe.evaluate_mission(conn, summary_path)

    for entry in evaluation["scenarios"]:
        assert entry["outcome"] == "PASS", entry
        assert entry["reasons"] == []
        assert entry["counts"] == {"detections": 0, "reports": 0, "analyses": 0}


# --- calendar family (SPEC_RECONCILIATION.md SS56) ---------------------------


def _store_calendar_world(conn, mission_id, seed, tmp_path, **overrides):
    rd.run_reference_engine(conn)
    config = pw.MissionConfig(
        mission_id=mission_id, run_mode="simulation", strategy=pw.STRATEGY_CALENDAR,
        seed=seed, **overrides,
    )
    result = pw.store_world(conn, config, runs_dir=tmp_path)
    return config, result["summary_path"]


def test_calendar_genuine_full_chain_reaches_pass(conn, tmp_path):
    """detected (an ARB-012 package through the lifted expiry) -> escalated
    -> cross-checked -> reported -> analyzed: PASS, with no direction to
    compare (expected_direction is None for the calendar family too)."""
    config, summary_path = _store_calendar_world(
        conn, "m-eval-calbump", seed=3, tmp_path=tmp_path, n_scenarios=3,
        scenario_mix={pw.VARIANT_CALENDAR_BUMP: 1.0},
    )
    _parity_work(conn, "explorer-1", "T0")
    _answer_all_cross_checks(conn)
    _file_cross_checked_reports(conn, "explorer-1", "T0")
    _complete_all_reports_with_analysis(conn)

    evaluation = pe.evaluate_mission(conn, summary_path)

    for entry in evaluation["scenarios"]:
        assert entry["outcome"] == "PASS", entry
        assert entry["reasons"] == []
        assert entry["counts"]["detections"] >= 1
    assert evaluation["metrics"]["strategy_exercised"] is True


def test_calendar_same_expiry_hit_planted_fails_under_its_own_name(conn, tmp_path):
    """A planted cross-strike detection on a calendar scenario is the world
    drifting from the whole-ladder invariance - FAIL under
    'unexpected_same_expiry_hit', distinct from both the parity alarm and a
    stray ARB-012."""
    config, summary_path = _store_calendar_world(
        conn, "m-eval-calcofire", seed=3, tmp_path=tmp_path, n_scenarios=3,
        scenario_mix={pw.VARIANT_CALENDAR_BUMP: 1.0},
    )
    _parity_work(conn, "explorer-1", "T0")

    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    scenario_entry = summary["scenarios"][0]
    gt = scenario_entry["ground_truth"]
    fi_db.record_parity_event(
        conn, "explorer-1", "T0", gt["entity_id"], gt["symbol"],
        strike=100.0, expiry_days=30, direction="call_vertical_upper",
        gross_edge_per_share=0.10, net_edge_per_share=0.05, classification="A", capacity_units=10.0,
        observed_at="2026-01-05T14:30:00+00:00", run_id=config.mission_id,
        scenario_id=scenario_entry["scenario_id"], detector_id="ARB-007", strike2=105.0,
    )

    evaluation = pe.evaluate_mission(conn, summary_path)
    by_id = {e["scenario_id"]: e for e in evaluation["scenarios"]}
    assert by_id[scenario_entry["scenario_id"]]["outcome"] == "FAIL"
    assert by_id[scenario_entry["scenario_id"]]["reasons"] == ["unexpected_same_expiry_hit"]
