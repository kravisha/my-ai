"""addendum 25 §19's diagnosis stage: what to do about a non-PASS scenario,
run over the records the Evaluator already produced
(simulation/parity_evaluation.py; docs/SPEC_RECONCILIATION.md §41-§42).

## The core idea

The simulator's own offline detector is the differential diagnostic. Explorer
runs backend/arbitrage.py's `scan_chain` over whatever option_chain
observations `providers/stored_data.py`'s `chain_snapshots` hands it - that is
Explorer's read side, not a copy of it (SPEC_RECONCILIATION.md §45's deferred
item: the chain scan, ARB-001 included alongside every cross-strike
detector). Re-running the identical scan, over the identical stored rows,
right here in diagnosis, produces a second, independent answer with nothing
but the passage of time and the identity of the caller changed. If the two
answers agree, whatever went wrong happened after detection - Explorer's own
escalation path, the cross-check, Analysis. If they disagree, the defect is
upstream of Explorer entirely: the world never carried an executable edge to
begin with (or, on a trap/none/cross-strike scenario, still carries one it
should not). That split needs no judgment call, which is why this module -
like `parity_evaluation.py` before it - is a pure function over a database
connection: no LLM, no new agent (§39's Evaluator disposition applies equally
here, and for the same reason).

`simulation/parity_world.py`'s own `answer_key`/`_chain_snapshots_from_scenario`
are not reusable for this: they take an in-memory `ScenarioWorld`, and
diagnosis runs long after that object is gone, against whatever actually got
written to the Data Store. `chain_snapshots` and `scan_chain` are what
Explorer itself calls (`agents/explorer.py`'s `_parity_work`), so re-running
them here is a diagnostic over the same interface Explorer used, not a
reimplementation that could quietly drift from it. One mechanism now covers
both families: a parity scenario's offline scan finds ARB-001 alone (nothing
else survives an arbitrage-free chain), a cross-strike scenario's finds the
cross-strike package instead, and either family's stray or unexpected hits
show up in the same opportunity list.

## Corrective work is per cause, not per finding

`backend/remediation.py`'s module docstring states the reason directly: ten
findings that are one design gap are one piece of corrective work, not ten.
This module groups scenario diagnoses by cause for the same reason, and
follows `remediation.py`'s further discipline of naming what it cannot
dispatch: **there is deliberately no corrective task queue yet.** Addendum 25
§19 says "the appropriate component is then corrected or trained" - naming
the component and the remedy in `corrective_items` IS this increment's
correction step. Building the machinery that would automatically act on a
`world`/`agent` classification (open a task, retrain a component) is future
work with its own design, exactly as `remediation.py` says of its own
`ATTRIBUTABLE` items: not yet justified, because nothing has asked for it.
Diagnosis is read-only, like `parity_evaluation.py` before it and
`backend/remediation.py`/`backend/compliance.py` beside it - "deciding what
work is needed and creating it are separate acts with separate authority"
(`remediation.py`). The only write this module makes is its own JSON file.

## A classification note, made explicit rather than left implicit

Every cause here sorts into one of four classifications - `world`, `agent`,
`in_flight`, `evaluation` - and three of those map straight off the cause's
component (`simulation_engine` -> world, `explorer`/`analysis` -> agent,
`none` -> in_flight). `detector_interface_drift` (component `interface`) does
not name an organizational role, so it needed a judgment call rather than a
literal lookup: it is classified `world`. The reasoning is
`backend/remediation.py`'s own SYSTEMIC test - "if every single opportunity
failed, the compliant path was not available, so nobody in the workforce can
be faulted." Explorer called the same detector, over the same rows, that
this module just called and got a different answer from; no choice Explorer
made explains that gap, so the remedy is a design/interface fix rather than
correction owed to any agent.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from agents.discovery_config import ANALYSIS_RECENCY_WINDOW_SECONDS
from backend import fi_db
from backend import observations as observation_store
from backend.arbitrage import CostConfig, Opportunity, scan_calendar, scan_chain, scan_forward
from providers.stored_data import chain_snapshots, forward_quotes
from simulation.parity_world import FORWARD_EXPECTED_DIRECTIONS
from simulation.parity_evaluation import (
    OUTCOME_FAIL, OUTCOME_INCONCLUSIVE, OUTCOME_PARTIAL, OUTCOME_PASS,
    REASON_STRAY_DETECTION, REASON_UNEXPECTED_CHAIN_HIT, REASON_UNEXPECTED_PARITY_HIT,
    REASON_UNEXPECTED_SAME_EXPIRY_HIT,
)

# How long a report may sit pending before this module calls it stalled
# rather than in flight. Addendum 25's own live-run measurement
# (docs/SPEC_RECONCILIATION.md §42: "Analysis's adopted 3-pass budget spends
# ~2 minutes per deep call") puts three deep calls plus queueing headroom at
# roughly this figure - a convention, not a measurement, in the same
# disclosure discipline as this codebase's other timing constants.
# Overridable per deployment rather than hardcoded, the same reason
# fi_db.CROSS_CHECK_TIMEOUT_SECONDS and CLAIM_TIMEOUT_SECONDS are.
ANALYSIS_STALL_SECONDS = float(os.environ.get("FI_ANALYSIS_STALL_SECONDS", "600.0"))

# --- cause vocabulary (addendum 25 §19) --------------------------------------

CAUSE_WORLD_NOT_STORED = "world_not_stored"
CAUSE_INSUFFICIENT_SIGNAL = "insufficient_signal"
CAUSE_EXPLORER_MISSED = "explorer_missed"
CAUSE_TRAP_NOT_ERASED = "trap_not_erased"
CAUSE_WORLD_NOT_CLEAN = "world_not_clean"
CAUSE_DETECTOR_INTERFACE_DRIFT = "detector_interface_drift"
CAUSE_GROUND_TRUTH_DIRECTION_ERROR = "ground_truth_direction_error"
CAUSE_EXPLORER_SELECTION_ERROR = "explorer_selection_error"
CAUSE_DIRECTION_INDETERMINATE = "direction_indeterminate"
CAUSE_CROSS_CHECK_IN_FLIGHT = "cross_check_in_flight"
CAUSE_EXPLORER_FILING_FAILURE = "explorer_filing_failure"
CAUSE_RECENCY_SUPPRESSED = "recency_suppressed"
CAUSE_EXPLORER_ESCALATION_FAILURE = "explorer_escalation_failure"
CAUSE_ANALYSIS_STALLED = "analysis_stalled"
CAUSE_ANALYSIS_IN_FLIGHT = "analysis_in_flight"
CAUSE_ANALYSIS_LOST = "analysis_lost"
CAUSE_ANALYSIS_FAILED = "analysis_failed"
# The cross-strike family's own world cause (SPEC_RECONCILIATION.md §45's
# deferred item): routes 'unexpected_parity_hit'/'stray_detection' FAILs
# where the offline re-scan agrees with what was recorded - the parallel-
# shift injector genuinely failed to preserve parity, or leaked a violation
# beyond the affected strike. Disagreement between the recorded detection
# and the offline re-scan still routes to the existing
# CAUSE_DETECTOR_INTERFACE_DRIFT below (module docstring's classification
# note applies equally here: no choice Explorer made explains a gap between
# it and the identical detector run again).
CAUSE_WORLD_CROSS_INTEGRITY = "world_cross_integrity"

COMPONENT_SIMULATION_ENGINE = "simulation_engine"
COMPONENT_EXPLORER = "explorer"
COMPONENT_INTERFACE = "interface"
COMPONENT_EVALUATION = "evaluation"
COMPONENT_EVALUATION_OR_SIMULATION_ENGINE = "evaluation/simulation_engine"
COMPONENT_ANALYSIS = "analysis"
COMPONENT_NONE = "none"

CLASS_WORLD = "world"
CLASS_AGENT = "agent"
CLASS_IN_FLIGHT = "in_flight"
CLASS_EVALUATION = "evaluation"

# classification: which of remediation.py's four postures each cause takes -
# see the module docstring's note on detector_interface_drift, the one entry
# here that is not a mechanical read of the cause's component.
_CLASSIFICATION = {
    CAUSE_WORLD_NOT_STORED: CLASS_WORLD,
    CAUSE_INSUFFICIENT_SIGNAL: CLASS_WORLD,
    CAUSE_TRAP_NOT_ERASED: CLASS_WORLD,
    CAUSE_WORLD_NOT_CLEAN: CLASS_WORLD,
    CAUSE_DETECTOR_INTERFACE_DRIFT: CLASS_WORLD,
    CAUSE_WORLD_CROSS_INTEGRITY: CLASS_WORLD,
    CAUSE_EXPLORER_MISSED: CLASS_AGENT,
    CAUSE_EXPLORER_FILING_FAILURE: CLASS_AGENT,
    CAUSE_EXPLORER_ESCALATION_FAILURE: CLASS_AGENT,
    CAUSE_EXPLORER_SELECTION_ERROR: CLASS_AGENT,
    CAUSE_ANALYSIS_STALLED: CLASS_AGENT,
    CAUSE_ANALYSIS_LOST: CLASS_AGENT,
    CAUSE_ANALYSIS_FAILED: CLASS_AGENT,
    CAUSE_GROUND_TRUTH_DIRECTION_ERROR: CLASS_EVALUATION,
    CAUSE_DIRECTION_INDETERMINATE: CLASS_EVALUATION,
    CAUSE_CROSS_CHECK_IN_FLIGHT: CLASS_IN_FLIGHT,
    CAUSE_RECENCY_SUPPRESSED: CLASS_IN_FLIGHT,
    CAUSE_ANALYSIS_IN_FLIGHT: CLASS_IN_FLIGHT,
}

_REMEDY = {
    CAUSE_WORLD_NOT_STORED: (
        "The chain observation for this scenario is missing from the Data Store. Check store_world's "
        "ingest path and whether n_scenarios/focus-asset assignment produced a collision, then re-store "
        "the mission."
    ),
    CAUSE_INSUFFICIENT_SIGNAL: (
        "The injected deviation never cleared executable costs on the chain as stored. Raise "
        "MissionConfig.deviation_range's floor, or investigate _inject_genuine for a regression."
    ),
    CAUSE_EXPLORER_MISSED: (
        "The edge was sitting in the stored chain and Explorer's scan never recorded it. Check "
        "Explorer's cycle timing, the option_chain market-session gate, and the arb001_min_net_edge "
        "lens value."
    ),
    CAUSE_TRAP_NOT_ERASED: (
        "The trap injector's friction (widened spread / borrow fee / staleness) failed to erase the "
        "edge on this chain. Review that variant's injector margin (_inject_spread_artifact / "
        "_inject_borrow_cost / _inject_stale_quote)."
    ),
    CAUSE_WORLD_NOT_CLEAN: (
        "An uninjected ('none' variant) chain carried an executable edge. Parity-by-construction failed "
        "in _build_rows or the pricing kernel - investigate before trusting any 'none' scenario as a "
        "false-positive control."
    ),
    CAUSE_DETECTOR_INTERFACE_DRIFT: (
        "Explorer's live detection and the offline detector disagree over the identical stored rows. "
        "Investigate providers/stored_data.py's snapshot reconstruction and any staleness/clock drift "
        "between Explorer's read and this diagnosis's re-read."
    ),
    CAUSE_WORLD_CROSS_INTEGRITY: (
        "A cross-strike scenario recorded an ARB-001 hit or a detection that does not trace back to the "
        "primary affected strike, and the offline re-scan confirms the chain as stored actually carries "
        "it. The parallel-shift injector (_inject_cross_bump / _inject_cross_dip / "
        "_inject_cross_spread_artifact) failed to preserve parity at the shifted strike, or leaked a "
        "violation beyond it - investigate the injector, not Explorer."
    ),
    CAUSE_GROUND_TRUTH_DIRECTION_ERROR: (
        "The offline detector and the agents' recorded direction agree with each other but not with "
        "ground truth. The world or its expected_direction is wrong, not the agents - re-derive ground "
        "truth for this scenario or review _inject_genuine's direction logic."
    ),
    CAUSE_EXPLORER_SELECTION_ERROR: (
        "The offline detector confirms the expected direction was available on the chain; Explorer "
        "escalated a lower-quality candidate instead. Review the max()-by-net-edge selection in "
        "_parity_work."
    ),
    CAUSE_DIRECTION_INDETERMINATE: (
        "Expected, agent, and offline directions all differ (or the offline detector found nothing to "
        "compare). Records alone cannot support a diagnosis here - this needs manual review, not a guess."
    ),
    CAUSE_CROSS_CHECK_IN_FLIGHT: "A cross-check is still open for this security. No action - wait and re-evaluate once it resolves.",
    CAUSE_EXPLORER_FILING_FAILURE: (
        "The cross-check's answer or timeout arrived, but no report was ever filed from it. Check "
        "_file_cross_checked_reports for an exception or an early return that swallowed this request."
    ),
    CAUSE_RECENCY_SUPPRESSED: (
        "The analysis-recency guard suppressed escalation for this security. Not a failure - "
        "re-evaluate after ANALYSIS_RECENCY_WINDOW_SECONDS elapses."
    ),
    CAUSE_EXPLORER_ESCALATION_FAILURE: (
        "A real detection never opened a cross-check, and the recency guard was not the reason. Check "
        "_parity_work's has_pending_report/has_open_cross_check guards for a stuck state."
    ),
    CAUSE_ANALYSIS_STALLED: (
        "The report has sat pending longer than ANALYSIS_STALL_SECONDS. Check whether Analysis is alive "
        "and whether its claim/heartbeat mechanics are working."
    ),
    CAUSE_ANALYSIS_IN_FLIGHT: "Analysis is still working this report. No action - wait and re-evaluate.",
    CAUSE_ANALYSIS_LOST: (
        "The report completed as 'analyzed' but no analysis_results row was ever recorded for it. Check "
        "record_analysis_result's call site in agents/analysis.py for a path that completes a report "
        "without recording its conclusion."
    ),
    CAUSE_ANALYSIS_FAILED: (
        "The deep-reasoning call failed and the report was completed 'failed' - the detail on the "
        "report carries the error. A transient error (connection/API) is re-tested by a same-seed "
        "rerun; repeated failures implicate the model gateway, not the analysis logic."
    ),
}


def _result(entry: dict, causes: list[str], component: str, notes: dict) -> dict:
    return {
        "scenario_id": entry["scenario_id"],
        "variant": entry["variant"],
        "symbol": entry["symbol"],
        "outcome": entry["outcome"],
        "causes": causes,
        "component": component,
        "notes": notes,
    }


def _offline_differential(conn, entity_id: str, scenario_id: str) -> tuple[list, list]:
    """Stage 0 (world integrity) and Stage 1 (the offline differential) in
    one pass: the scenario's stored chain, filtered to its own provenance,
    then `scan_chain` re-run over every expiry exactly as Explorer calls it
    (`agents/explorer.py`'s `_parity_work`: `scan_chain(chain, costs)`, no
    stale_tolerance_seconds override) - a second, independent reading of the
    identical stored rows. One mechanism now covers both families: ARB-001
    is part of the same scan, not a separate call, so a parity scenario's
    differential and a cross-strike scenario's differential are the same
    code path (SPEC_RECONCILIATION.md §45's deferred item).

    Returns (chain_rows, offline_opportunities). An empty chain_rows means
    Stage 0 already answers the question; the caller checks that before
    trusting offline_opportunities at all."""
    chain_rows = [
        obs for obs in observation_store.replay(conn, entity_id, "option_chain")
        if obs.provenance.scenario_id == scenario_id
    ]
    if not chain_rows:
        return chain_rows, []
    chain_observation = chain_rows[-1]
    costs = CostConfig()
    offline_opportunities: list[Opportunity] = []
    chains = list(chain_snapshots(chain_observation))
    for chain in chains:
        offline_opportunities.extend(scan_chain(chain, costs))
    # The cross-expiry scan too (ARB-012, §56) - Explorer runs scan_calendar
    # over the same chains now, so a differential that skipped it would
    # misdiagnose every calendar miss as a world problem.
    offline_opportunities.extend(scan_calendar(chains, costs))
    # And the forward-leg scan (ARB-013/014, §61), same reasoning - over
    # whatever forwards the stored payload listed (none is a no-op).
    offline_opportunities.extend(scan_forward(chains, forward_quotes(chain_observation), costs))
    return chain_rows, offline_opportunities


def _diagnose_detected_not_escalated(conn, mission_id: str, entry: dict, notes: dict) -> dict:
    """PARTIAL('detected_not_escalated'): the detection is real
    (parity_events carries it - `evaluate_mission`'s own `counts.detections`
    already established that); what happened to escalation is read from this
    explorer identity's cross-check state, then the recency guard
    (`agents/explorer.py`'s `_parity_work` reads
    `config.ANALYSIS_RECENCY_WINDOW_SECONDS`, the same constant read here)."""
    scenario_id = entry["scenario_id"]
    security = entry["symbol"]
    detections = conn.fetchall(
        "SELECT * FROM parity_events WHERE run_id = ? AND scenario_id = ? ORDER BY id",
        (mission_id, scenario_id),
    )
    notes = {**notes, "detection_count": len(detections)}
    identity = detections[-1]["producer_identity"] if detections else None

    request = None
    if identity is not None:
        request = conn.fetchone(
            "SELECT * FROM cross_check_requests WHERE requester_identity = ? AND security = ? "
            "ORDER BY id DESC LIMIT 1",
            (identity, security),
        )

    if request is not None and request["status"] == fi_db.CROSS_CHECK_PENDING:
        return _result(entry, [CAUSE_CROSS_CHECK_IN_FLIGHT], COMPONENT_NONE, notes)
    if request is not None:
        # Resolved (answered or timed out) but never consumed into a report -
        # the answer arrived and the filing path did not run.
        return _result(entry, [CAUSE_EXPLORER_FILING_FAILURE], COMPONENT_EXPLORER, notes)

    recent = fi_db.list_recent_analysis_results(conn, security, ANALYSIS_RECENCY_WINDOW_SECONDS)
    notes = {**notes, "recent_analysis_count": len(recent)}
    if recent:
        return _result(entry, [CAUSE_RECENCY_SUPPRESSED], COMPONENT_NONE, notes)
    return _result(entry, [CAUSE_EXPLORER_ESCALATION_FAILURE], COMPONENT_EXPLORER, notes)


def _diagnose_analysis_in_flight(conn, mission_id: str, entry: dict, notes: dict) -> dict:
    """INCONCLUSIVE('analysis_in_flight'): find the report - pending or
    completed - backing this scenario's detections, by parity_event_id, the
    same join `parity_evaluation._reports_for` makes."""
    scenario_id = entry["scenario_id"]
    detections = conn.fetchall(
        "SELECT id FROM parity_events WHERE run_id = ? AND scenario_id = ? ORDER BY id",
        (mission_id, scenario_id),
    )
    detection_ids = [d["id"] for d in detections]
    notes = {**notes, "detection_count": len(detection_ids)}
    if not detection_ids:
        return _result(entry, [CAUSE_ANALYSIS_LOST], COMPONENT_ANALYSIS,
                        {**notes, "note": "no parity_event found for this scenario despite an "
                                           "INCONCLUSIVE(analysis_in_flight) grade"})

    placeholders = ",".join("?" for _ in detection_ids)
    pending = conn.fetchall(
        f"SELECT * FROM discovery_reports WHERE parity_event_id IN ({placeholders}) ORDER BY id",
        detection_ids,
    )
    if pending:
        report = pending[0]
        age_seconds = (datetime.now(timezone.utc) - fi_db.parse_timestamp(report["created_at"])).total_seconds()
        notes = {**notes, "report_age_seconds": round(age_seconds, 1)}
        if age_seconds > ANALYSIS_STALL_SECONDS:
            return _result(entry, [CAUSE_ANALYSIS_STALLED], COMPONENT_ANALYSIS, notes)
        return _result(entry, [CAUSE_ANALYSIS_IN_FLIGHT], COMPONENT_NONE, notes)

    completed = conn.fetchall(
        f"SELECT * FROM discovery_reports_completed WHERE parity_event_id IN ({placeholders}) ORDER BY id",
        detection_ids,
    )
    if completed:
        report_ids = [r["id"] for r in completed]
        id_placeholders = ",".join("?" for _ in report_ids)
        analyses = conn.fetchall(
            f"SELECT * FROM analysis_results WHERE report_id IN ({id_placeholders})", report_ids,
        )
        if not analyses:
            # Two different facts hide behind "completed, no analysis", and a
            # live run taught the difference: a report completed 'failed'
            # carries the error that stopped it (agents/analysis.py marks the
            # report failed and stays alive - the intended error path, seen
            # for real as 'Connection error.' on both reports of one mission),
            # while a report completed 'analyzed' with no conclusion row would
            # be a genuine code defect. Same records-shape, opposite remedies.
            failed = [r for r in completed if r["outcome"] == "failed"]
            if failed:
                return _result(entry, [CAUSE_ANALYSIS_FAILED], COMPONENT_ANALYSIS,
                                {**notes, "failure_details": [r["detail"] for r in failed]})
            return _result(entry, [CAUSE_ANALYSIS_LOST], COMPONENT_ANALYSIS, notes)
        # A completed report with a recorded analysis contradicts an
        # INCONCLUSIVE grade (evaluate_mission would have graded PASS/PARTIAL
        # instead) - surfaced rather than silently mis-filed under some other
        # cause, the same refusal-to-guess this module states for
        # direction_indeterminate.
        return _result(entry, [], COMPONENT_EVALUATION,
                        {**notes, "note": "a completed report and a recorded analysis both exist for this "
                                           "scenario's detections, which should not coexist with an "
                                           "INCONCLUSIVE grade - refusing to guess a cause"})

    return _result(entry, [CAUSE_ANALYSIS_LOST], COMPONENT_ANALYSIS,
                    {**notes, "note": "no report, pending or completed, found for this scenario's detections"})


def _diagnose_scenario(conn, mission_id: str, entry: dict, ground_truth: dict) -> dict:
    """Walk the differential for one non-PASS scenario (module docstring)."""
    scenario_id = entry["scenario_id"]
    outcome = entry["outcome"]
    reasons = entry.get("reasons") or []
    reason = reasons[0] if reasons else None

    chain_rows, offline_opportunities = _offline_differential(conn, ground_truth["entity_id"], scenario_id)
    if not chain_rows:
        return _result(entry, [CAUSE_WORLD_NOT_STORED], COMPONENT_SIMULATION_ENGINE,
                        {"chain_observations": 0})

    offline_best = max(offline_opportunities, key=lambda o: o.net_edge_per_share, default=None)
    notes = {
        "offline_opportunity_count": len(offline_opportunities),
        "offline_best_net_edge": offline_best.net_edge_per_share if offline_best else None,
        "offline_best_direction": offline_best.direction if offline_best else None,
        "counts": entry.get("counts", {}),
        "detected_direction": entry.get("detected_direction"),
        "expected_direction": entry.get("expected_direction"),
    }

    if outcome == OUTCOME_FAIL and reason == "missed":
        if not offline_opportunities:
            return _result(entry, [CAUSE_INSUFFICIENT_SIGNAL], COMPONENT_SIMULATION_ENGINE, notes)
        return _result(entry, [CAUSE_EXPLORER_MISSED], COMPONENT_EXPLORER, notes)

    if outcome == OUTCOME_FAIL and reason in ("trap_leaked", "false_positive"):
        if offline_opportunities:
            cause = CAUSE_TRAP_NOT_ERASED if reason == "trap_leaked" else CAUSE_WORLD_NOT_CLEAN
            return _result(entry, [cause], COMPONENT_SIMULATION_ENGINE, notes)
        return _result(entry, [CAUSE_DETECTOR_INTERFACE_DRIFT], COMPONENT_INTERFACE, notes)

    if outcome == OUTCOME_FAIL and reason in (
        REASON_UNEXPECTED_PARITY_HIT, REASON_STRAY_DETECTION, REASON_UNEXPECTED_SAME_EXPIRY_HIT,
        REASON_UNEXPECTED_CHAIN_HIT,
    ):
        # SS45's deferred item, extended by §56's calendar family. The
        # offline re-scan (every expiry plus every cross-expiry pair, same
        # mechanism as every other branch here) either confirms the same
        # anomaly Explorer recorded - the injector genuinely failed to
        # preserve its invariance or leaked beyond the affected cell, a
        # world cause - or does not, in which case the disagreement is
        # between Explorer's recorded detection and the identical detector
        # run again, the same detector_interface_drift reasoning the
        # trap/none branch above already uses. What "agrees" means is
        # family-specific, because each reason names a different invariance.
        primary = ground_truth.get("affected_strike")
        affected_expiry = ground_truth.get("affected_expiry_days")
        if reason == REASON_UNEXPECTED_PARITY_HIT:
            offline_agrees = any(o.detector_id == "ARB-001" for o in offline_opportunities)
        elif reason == REASON_UNEXPECTED_SAME_EXPIRY_HIT:
            offline_agrees = any(
                o.detector_id not in ("ARB-001", "ARB-012") for o in offline_opportunities
            )
        elif reason == REASON_UNEXPECTED_CHAIN_HIT:
            # §61's forward family: an option-relation package (anything but
            # parity and the forward detectors) fired on a chain the shift
            # never touched.
            offline_agrees = any(
                o.detector_id not in ("ARB-001", "ARB-013", "ARB-014")
                for o in offline_opportunities
            )
        elif ground_truth.get("expected_family") == "forward":
            # A forward stray: a forward package through the wrong expiry or
            # in a direction the shift sign does not explain (§61).
            expected_directions = FORWARD_EXPECTED_DIRECTIONS[ground_truth["variant"]]
            offline_agrees = any(
                o.detector_id in ("ARB-013", "ARB-014")
                and (o.inputs.get("expiry_days") != affected_expiry
                     or o.direction not in expected_directions)
                for o in offline_opportunities
            )
        elif ground_truth.get("expected_family") == "calendar":
            # A calendar stray is an ARB-012 through the wrong expiry pair,
            # not a strike mismatch - the family has no primary strike.
            offline_agrees = any(
                o.detector_id == "ARB-012" and o.inputs.get("expiry_days") != affected_expiry
                for o in offline_opportunities
            )
        else:
            offline_agrees = any(
                o.detector_id != "ARB-001"
                and primary not in (o.inputs.get("strike", o.inputs.get("k1")), o.inputs.get("k2"), o.inputs.get("k3"))
                for o in offline_opportunities
            )
        if offline_agrees:
            return _result(entry, [CAUSE_WORLD_CROSS_INTEGRITY], COMPONENT_SIMULATION_ENGINE, notes)
        return _result(entry, [CAUSE_DETECTOR_INTERFACE_DRIFT], COMPONENT_INTERFACE, notes)

    if outcome == OUTCOME_PARTIAL and reason == "wrong_direction":
        expected = ground_truth.get("expected_direction")
        agent_direction = entry.get("detected_direction")
        offline_direction = offline_best.direction if offline_best else None
        # A cross-strike scenario has no single "the" direction to compare
        # against (ground_truth['expected_direction'] is None for that
        # family - simulation/parity_evaluation.py's own cross-strike branch
        # never produces 'wrong_direction' as a reason, but this guard keeps
        # the refusal-to-guess honest if that ever changes) - refuse to
        # infer a ground-truth or selection error from a comparison that has
        # no expected answer to compare against.
        if expected is None:
            return _result(entry, [CAUSE_DIRECTION_INDETERMINATE], COMPONENT_EVALUATION, notes)
        if offline_direction is not None and offline_direction == agent_direction and offline_direction != expected:
            return _result(entry, [CAUSE_GROUND_TRUTH_DIRECTION_ERROR], COMPONENT_EVALUATION_OR_SIMULATION_ENGINE, notes)
        if offline_direction is not None and offline_direction == expected:
            return _result(entry, [CAUSE_EXPLORER_SELECTION_ERROR], COMPONENT_EXPLORER, notes)
        return _result(entry, [CAUSE_DIRECTION_INDETERMINATE], COMPONENT_EVALUATION, notes)

    if outcome == OUTCOME_PARTIAL and reason == "detected_not_escalated":
        return _diagnose_detected_not_escalated(conn, mission_id, entry, notes)

    if outcome == OUTCOME_INCONCLUSIVE and reason == "analysis_in_flight":
        return _diagnose_analysis_in_flight(conn, mission_id, entry, notes)

    # Defensive: an outcome/reason pair this differential has no branch for -
    # e.g. a new reason code added to parity_evaluation.py without a matching
    # update here. Surfaced rather than silently mis-filed, the same refusal
    # to guess this module states elsewhere.
    return _result(entry, [], COMPONENT_EVALUATION,
                    {**notes, "note": f"no diagnosis branch for outcome={outcome!r} reason={reason!r}"})


def _corrective_items(scenario_diagnoses: list[dict]) -> list[dict]:
    """Group scenario diagnoses by cause (module docstring: per cause, not
    per finding - `backend/remediation.py`'s rule)."""
    by_cause: dict[str, dict] = {}
    for diag in scenario_diagnoses:
        for cause in diag["causes"]:
            group = by_cause.setdefault(cause, {"scenarios": [], "component": diag["component"]})
            group["scenarios"].append(diag["scenario_id"])

    items = []
    for cause in sorted(by_cause):
        group = by_cause[cause]
        items.append({
            "cause": cause,
            "component": group["component"],
            "scenarios": group["scenarios"],
            "classification": _CLASSIFICATION[cause],
            "remedy": _REMEDY[cause],
        })
    return items


def _mission_certified_complete(evaluation: dict) -> bool:
    """addendum 25 §17's completion certification, as a statement in the
    record - deliberately not a gate. Nothing downstream currently reads
    this to permit or withhold anything, the same disclosed posture
    simulation/certification.py states for its own gates: "a gate described
    as binding when nothing is bound would be the first false clause in a
    system built to avoid them." This is the measurement, not the door."""
    metrics = evaluation["metrics"]
    by_outcome = metrics["by_outcome"]
    return (
        bool(metrics["strategy_exercised"])
        and by_outcome[OUTCOME_FAIL] == 0
        and by_outcome[OUTCOME_PARTIAL] == 0
        and by_outcome[OUTCOME_INCONCLUSIVE] == 0
    )


def _retry_guidance(items: list[dict], retry_recommended: bool, wait_and_reevaluate: bool, certified: bool) -> dict:
    actionable = [item for item in items if item["classification"] != CLASS_IN_FLIGHT]
    has_world = any(item["classification"] == CLASS_WORLD for item in actionable)

    if retry_recommended:
        causes = ", ".join(item["cause"] for item in actionable)
        return {
            "reason": f"{len(actionable)} corrective item(s) outstanding ({causes}) need correction before a rerun would prove anything.",
            "rerun_same_seed": not has_world,
            "adjust_world_first": has_world,
        }
    if wait_and_reevaluate:
        return {
            "reason": "No corrective work outstanding; scenario(s) are still in flight - wait and re-evaluate.",
            "rerun_same_seed": False,
            "adjust_world_first": False,
        }
    if certified:
        return {
            "reason": "Every scenario passed; the mission is certified complete.",
            "rerun_same_seed": False,
            "adjust_world_first": False,
        }
    return {
        "reason": "No outstanding scenarios and no corrective work identified.",
        "rerun_same_seed": False,
        "adjust_world_first": False,
    }


def _diagnosis_path(evaluation_path: Path) -> Path:
    """`X.evaluation.json` -> `X.diagnosis.json`, beside the evaluation - the
    same naming convention `parity_world._write_summary` and
    `evaluate_mission` both use for their own outputs."""
    stem = evaluation_path.stem
    if stem.endswith(".evaluation"):
        stem = stem[: -len(".evaluation")]
    return evaluation_path.with_name(stem + ".diagnosis" + evaluation_path.suffix)


def diagnose_mission(conn, evaluation_path: str | Path) -> dict:
    """The diagnosis stage's one entry point (module docstring): load a
    mission's evaluation and, through it, the ground-truth summary it was
    graded against; walk the differential for every non-PASS scenario; group
    the results into corrective items; write the diagnosis beside the
    evaluation, and return it.

    Read-only against the database - the offline detector is invoked, never
    fed back, and no cross-check/report/analysis row is written or changed.
    The only write this function makes is the diagnosis JSON itself."""
    evaluation_path = Path(evaluation_path)
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    summary = json.loads(Path(evaluation["summary_path"]).read_text(encoding="utf-8"))
    ground_truth_by_id = {entry["scenario_id"]: entry["ground_truth"] for entry in summary["scenarios"]}
    mission_id = evaluation["mission_id"]

    scenario_diagnoses = [
        _diagnose_scenario(conn, mission_id, entry, ground_truth_by_id[entry["scenario_id"]])
        for entry in evaluation["scenarios"]
        if entry["outcome"] != OUTCOME_PASS
    ]

    corrective_items = _corrective_items(scenario_diagnoses)
    certified = _mission_certified_complete(evaluation)
    retry_recommended = any(item["classification"] in (CLASS_WORLD, CLASS_AGENT, CLASS_EVALUATION) for item in corrective_items)
    wait_and_reevaluate = any(item["classification"] == CLASS_IN_FLIGHT for item in corrective_items)
    retry_guidance = _retry_guidance(corrective_items, retry_recommended, wait_and_reevaluate, certified)

    diagnosis = {
        "mission_id": mission_id,
        "evaluation_path": str(evaluation_path),
        "scenarios": scenario_diagnoses,
        "corrective_items": corrective_items,
        "mission_certified_complete": certified,
        "retry_recommended": retry_recommended,
        "retry_guidance": retry_guidance,
        "wait_and_reevaluate": wait_and_reevaluate,
    }

    diagnosis_path = _diagnosis_path(evaluation_path)
    diagnosis_path.write_text(json.dumps(diagnosis, indent=2), encoding="utf-8")
    diagnosis["diagnosis_path"] = str(diagnosis_path)

    return diagnosis
