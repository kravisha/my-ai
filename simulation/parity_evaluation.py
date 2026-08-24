"""The Market Data Simulation Engine's Evaluator (addendum 25 §16-§19;
docs/SPEC_RECONCILIATION.md §39, §41).

**The mission's grading pass, not an agent.** `docs/SPEC_RECONCILIATION.md`
§39 already mapped addendum 23 §7's "Evaluator" onto mechanism that exists
today - the grading chain, Stage 1's planted-ground-truth scoring - and was
explicit that "a distinct Evaluator *agent* is not built and is not needed
until something an existing mechanism cannot evaluate exists." Nothing this
increment adds changes that: comparing organizational records against a
ground-truth summary is a deterministic join over the run database, with no
judgment call an LLM would earn its call by making. So `evaluate_mission`
is a pure function over a database connection, invoked from orchestration
or the CLI, the same shape `backend/reference_data.py` and
`simulation/parity_world.py` already are (both engines, not agents) - and
it never gets its own charter or watcher, for the same reason they don't.

## What it reads, and what it never touches

`simulation/parity_world.py`'s `store_world` writes two things: the mission's
Observations into the Data Store (what the organization is allowed to see)
and a ground-truth summary JSON on disk (what it is not - the module
docstring's ground-truth isolation section). `evaluate_mission` reads the
summary - the answer key no agent ever read - and joins it against three
tables the organization's own agents wrote while working the mission blind:
`parity_events` (Explorer's ARB-001 detections, agents/explorer.py's
`_parity_work`), `discovery_reports`/`discovery_reports_completed` (the
escalation those detections produced, keyed by `parity_event_id`), and
`analysis_results` (Analysis's conclusions, keyed by `report_id`). It writes
nothing back to the database - grading a run must not be indistinguishable
from an event a real agent produced.

## Outcome vocabulary (addendum 25 §16)

PASS, PARTIAL, FAIL, INCONCLUSIVE - the same four words `parity_world.py`'s
own `evaluate()` already uses for the simulator's answer-key comparison, kept
identical here instead of inventing a parallel vocabulary for the
organization's actual run. What differs is the *join*: `evaluate()` compares
the answer key against itself (detect_arb001, run again, right here); this
module compares the ground truth against what Explorer/Speculator/Analysis
actually recorded, several process boundaries away and possibly never
finished.

## The completion loop this closes (addendum 25 §17)

Mission Configuration -> Reference Data READY -> world generated -> Explorer
+ Speculator identify a candidate -> Analyst investigates -> outcome produced
-> **Evaluator compares outcome with ground truth** -> PASS/PARTIAL/FAIL/
INCONCLUSIVE. `evaluate_mission` is that last arrow. Diagnosis and
training/correction (addendum 25 §19) read its output; they are not this
module's job - a grading pass that also decided what to do about a FAIL
would be conflating measurement with response.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from simulation import parity_world as pw

REASON_MISSED = "missed"
REASON_DETECTED_NOT_ESCALATED = "detected_not_escalated"
REASON_ANALYSIS_IN_FLIGHT = "analysis_in_flight"
REASON_WRONG_DIRECTION = "wrong_direction"
REASON_TRAP_LEAKED = "trap_leaked"
REASON_FALSE_POSITIVE = "false_positive"
# The cross-strike family's own reasons (docs/SPEC_RECONCILIATION.md SS45's
# deferred item): a same-strike parallel shift preserves parity by
# construction, so an ARB-001 hit on one of these scenarios is a world-
# integrity alarm, not a second correct answer; a non-ARB-001 hit whose
# strikes do not trace back to the primary affected strike is a stray the
# injector should not have produced.
REASON_UNEXPECTED_PARITY_HIT = "unexpected_parity_hit"
REASON_STRAY_DETECTION = "stray_detection"

OUTCOME_PASS = "PASS"
OUTCOME_PARTIAL = "PARTIAL"
OUTCOME_FAIL = "FAIL"
OUTCOME_INCONCLUSIVE = "INCONCLUSIVE"


def _placeholders(values: list) -> str:
    return ",".join("?" for _ in values)


def _detections_for(conn, mission_id: str, scenario_id: str) -> list[dict]:
    return conn.fetchall(
        "SELECT * FROM parity_events WHERE run_id = ? AND scenario_id = ? ORDER BY id",
        (mission_id, scenario_id),
    )


def _reports_for(conn, parity_event_ids: list[int]) -> list[dict]:
    """Both the pending queue and the completed archive - a report can be in
    either depending on whether Analysis has finished with it, and the
    Evaluator reports the state it finds, it does not wait for one (module
    docstring). The archive trigger (backend/fi_db.py's
    `discovery_reports_archive`) copies `NEW.id` verbatim into
    `discovery_reports_completed.id`, so a report's id - and therefore this
    join key - survives archival unchanged."""
    if not parity_event_ids:
        return []
    placeholders = _placeholders(parity_event_ids)
    pending = conn.fetchall(
        f"SELECT * FROM discovery_reports WHERE parity_event_id IN ({placeholders}) ORDER BY id",
        parity_event_ids,
    )
    completed = conn.fetchall(
        f"SELECT * FROM discovery_reports_completed WHERE parity_event_id IN ({placeholders}) ORDER BY id",
        parity_event_ids,
    )
    return pending + completed


def _analyses_for(conn, report_ids: list[int]) -> list[dict]:
    if not report_ids:
        return []
    placeholders = _placeholders(report_ids)
    return conn.fetchall(
        f"SELECT * FROM analysis_results WHERE report_id IN ({placeholders}) ORDER BY id",
        report_ids,
    )


def _detected_direction(analyses: list[dict], reports: list[dict], detections: list[dict]) -> str | None:
    """The direction ARB-001 actually detected on the chain that fed the
    analysis backing this scenario's PASS candidacy - traced report_id ->
    parity_event_id -> parity_events.direction, not merely "some detection
    exists somewhere in this scenario", so a scenario with more than one
    recorded detection (a mission left running across several cycles,
    agents/explorer.py's `_parity_work` records a fresh row every cycle a
    candidate persists) is graded on the one the completed chain used."""
    if not analyses:
        return None
    reports_by_id = {r["id"]: r for r in reports}
    detections_by_id = {d["id"]: d for d in detections}
    report = reports_by_id.get(analyses[0]["report_id"])
    if report is None or report.get("parity_event_id") is None:
        return None
    detection = detections_by_id.get(report["parity_event_id"])
    return detection["direction"] if detection is not None else None


def _grade_scenario(conn, mission_id: str, scenario_id: str, ground_truth: dict) -> dict:
    detections = _detections_for(conn, mission_id, scenario_id)
    reports = _reports_for(conn, [d["id"] for d in detections])
    analyses = _analyses_for(conn, [r["id"] for r in reports])

    variant = ground_truth["variant"]
    detected_direction = None

    if ground_truth.get("expected_family") == "cross_strike":
        # SS45's deferred item. A same-strike parallel shift leaves every
        # executable ARB-001 edge at the bumped strike invariant (module note
        # above simulation/parity_world.py's _inject_cross_bump) - so an
        # ARB-001 hit here means the world drifted from that invariant, not
        # that a second correct answer was found, and grades FAIL regardless
        # of anything downstream. A non-ARB-001 hit whose strikes do not
        # include the primary affected strike is a stray the injector should
        # not have produced. Direction comparison is skipped throughout -
        # ground_truth['expected_direction'] is None for every cross variant
        # (there is no single "the" direction the way ARB-001's conversion/
        # reversal has one), so the wrong_direction branch below never
        # applies to this family.
        primary = ground_truth.get("affected_strike")
        arb001_hits = [d for d in detections if d["detector_id"] == "ARB-001"]
        cross_hits = [d for d in detections if d["detector_id"] != "ARB-001"]
        stray = [d for d in cross_hits if primary not in (d["strike"], d["strike2"], d["strike3"])]

        if arb001_hits:
            outcome, reasons = OUTCOME_FAIL, [REASON_UNEXPECTED_PARITY_HIT]
        elif stray:
            outcome, reasons = OUTCOME_FAIL, [REASON_STRAY_DETECTION]
        elif not cross_hits:
            outcome, reasons = OUTCOME_FAIL, [REASON_MISSED]
        elif analyses:
            outcome, reasons = OUTCOME_PASS, []
        elif reports:
            outcome, reasons = OUTCOME_INCONCLUSIVE, [REASON_ANALYSIS_IN_FLIGHT]
        else:
            outcome, reasons = OUTCOME_PARTIAL, [REASON_DETECTED_NOT_ESCALATED]
    elif variant == pw.VARIANT_GENUINE:
        if analyses:
            detected_direction = _detected_direction(analyses, reports, detections)
            if detected_direction == ground_truth["expected_direction"]:
                outcome, reasons = OUTCOME_PASS, []
            else:
                outcome, reasons = OUTCOME_PARTIAL, [REASON_WRONG_DIRECTION]
        elif reports:
            outcome, reasons = OUTCOME_INCONCLUSIVE, [REASON_ANALYSIS_IN_FLIGHT]
        elif detections:
            outcome, reasons = OUTCOME_PARTIAL, [REASON_DETECTED_NOT_ESCALATED]
        else:
            outcome, reasons = OUTCOME_FAIL, [REASON_MISSED]
    else:
        # A detection alone fails the scenario regardless of whether it was
        # escalated (module docstring's outcome vocabulary section) - the
        # detector should never have fired on a trap or a clean control, so
        # what happened to the detection afterward is beside the point.
        if not detections:
            outcome, reasons = OUTCOME_PASS, []
        else:
            reason = REASON_TRAP_LEAKED if variant in pw.TRAP_VARIANTS else REASON_FALSE_POSITIVE
            outcome, reasons = OUTCOME_FAIL, [reason]

    return {
        "scenario_id": scenario_id,
        "variant": variant,
        "symbol": ground_truth["symbol"],
        "outcome": outcome,
        "reasons": reasons,
        "counts": {
            "detections": len(detections),
            "reports": len(reports),
            "analyses": len(analyses),
        },
        "detected_direction": detected_direction,
        "expected_direction": ground_truth.get("expected_direction"),
    }


def _metrics(scenarios: list[dict]) -> dict:
    n = len(scenarios)
    by_outcome = {OUTCOME_PASS: 0, OUTCOME_PARTIAL: 0, OUTCOME_FAIL: 0, OUTCOME_INCONCLUSIVE: 0}
    for entry in scenarios:
        by_outcome[entry["outcome"]] += 1

    # "genuine" spans any family (SS45's deferred item): the original
    # VARIANT_GENUINE plus the two cross-strike genuine variants
    # (pw.CROSS_GENUINE_VARIANTS) - a run trained on options_arbitrage_phase1
    # may never draw the classic parity genuine at all and still deserves to
    # count as having exercised its own strategy.
    def _is_genuine(variant: str) -> bool:
        return variant == pw.VARIANT_GENUINE or variant in pw.CROSS_GENUINE_VARIANTS

    genuine = [s for s in scenarios if _is_genuine(s["variant"])]
    non_genuine = [s for s in scenarios if not _is_genuine(s["variant"])]
    genuine_detected = sum(1 for s in genuine if s["outcome"] == OUTCOME_PASS)
    genuine_missed = len(genuine) - genuine_detected
    false_positives = sum(1 for s in non_genuine if s["outcome"] == OUTCOME_FAIL)

    # addendum 25 §18: the strategy was exercised if at least one genuine
    # scenario of any family made it all the way to PASS - detected,
    # escalated, analyzed, and (for ARB-001 material) in the right direction.
    # Anything short of that (missed, detected but not escalated, analysis
    # still in flight, wrong direction, or - cross-strike material only - an
    # unexpected parity hit or a stray detection) is not the strategy being
    # exercised, it is the strategy being tried.
    strategy_exercised = genuine_detected > 0

    return {
        "by_outcome": by_outcome,
        "pass_rate": (by_outcome[OUTCOME_PASS] / n) if n else None,
        "genuine_detected": genuine_detected,
        "genuine_missed": genuine_missed,
        "false_positives": false_positives,
        "strategy_exercised": strategy_exercised,
        "retry_required": not strategy_exercised,
    }


def evaluate_mission(conn, summary_path: str | Path) -> dict:
    """The Evaluator's one entry point (module docstring): load a mission's
    ground-truth summary, grade every scenario against what the organization's
    own records show, write the evaluation beside the summary, and return it.

    Pure read-side against `conn` - detections/reports/analyses are read, never
    written; the only write this function makes is the evaluation JSON itself,
    to a path the summary never named (module docstring's separation between
    what an agent may read and what grades it)."""
    summary_path = Path(summary_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    mission_id = summary["mission_id"]

    scenarios = [
        _grade_scenario(conn, mission_id, entry["scenario_id"], entry["ground_truth"])
        for entry in summary["scenarios"]
    ]
    metrics = _metrics(scenarios)

    evaluation = {
        "mission_id": mission_id,
        "summary_path": str(summary_path),
        # Wall clock is fine here (module docstring): this timestamps a
        # grading record, not simulated world content - it carries no
        # reproducibility obligation the way parity_world's own timestamps do.
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "scenarios": scenarios,
        "metrics": metrics,
    }

    # summary "parity-<mission>-<ts>.json" -> "parity-<mission>-<ts>.evaluation.json",
    # written beside it - the same directory, the same naming convention
    # `parity_world._write_summary` uses for the summary itself.
    evaluation_path = summary_path.with_name(summary_path.stem + ".evaluation" + summary_path.suffix)
    evaluation_path.write_text(json.dumps(evaluation, indent=2), encoding="utf-8")
    evaluation["evaluation_path"] = str(evaluation_path)

    return evaluation
