"""Mission control's backend registry (this increment; addendum 25 SS4, SS22,
SS23; docs/SPEC_RECONCILIATION.md SS39: "the mission-control interface is
panel work not yet built; until it exists, the engine is activated
programmatically with run_mode='simulation' required - the rule enforced at
the engine boundary, the UI to follow"). This module is that UI's backend: a
row per mission, the pipeline counts a dashboard would read, and the
orchestration entry point that turns a config dict into a stored (or
refused, or blocked) mission.

**Not fi_db.** backend/fi_db.py imports this module (registered in
init_schema, added to apply_additive_migrations' schema tuple) the same way
it imports backend/reference_data.py - so this module must not import fi_db,
or the import graph closes a cycle. backend.db, backend.reference_data and
simulation.* are fine (precedent: backend/canonical.py imports
simulation.cadences).

## Status vocabulary (addendum 25 SS22)

Addendum 25 SS22 lists AGENTS_RUNNING/RETRY_REQUIRED/COMPLETED/FAILED among
the dashboard's suggested states. simulation.parity_world.STATES already
defines WAITING_FOR_REFERENCE_DATA, RETRY_REQUIRED, COMPLETED and FAILED -
reused here by name, not re-declared, so the two modules can never drift on
what the same word means - but it has no AGENTS_RUNNING: its own generation
states (CONFIGURING through READY) describe run_parity_exercise's in-memory
scenario-building traversal, which store_world (this mission's actual entry
point) never performs. store_world is a synchronous, millisecond-scale
database write, the same argument docs/SPEC_RECONCILIATION.md SS40 makes for
the Reference Data Engine's own collapsed progress states - so every one of
those generation states collapses into a single AGENTS_RUNNING here: a
mission whose world is stored and whose agents may now be working it.
Defined fresh in this module since parity_world has no occasion to need it.

Reachable statuses: WAITING_FOR_REFERENCE_DATA, AGENTS_RUNNING,
RETRY_REQUIRED, COMPLETED, FAILED.

## Visible failure, not a transient error (addendum 25 SS23)

A mission blocked on reference data, or one that failed to store, is not an
exception a caller has to catch - it is a row the dashboard shows. That is
why start_mission returns a mission dict in both of those cases instead of
raising: only a genuine refusal to even register the attempt (a bad
run_mode, an already-running mission_id) raises, because those never become
rows at all.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from backend import db as db_module
from simulation import parity_evaluation
from simulation import parity_world as pw

# simulation.parity_diagnosis is imported lazily, inside evaluate() below,
# rather than at module scope like parity_evaluation - it imports backend.fi_db
# itself, and fi_db.init_schema imports this module (module docstring), so an
# eager import here would close exactly the import cycle that docstring warns
# against. parity_evaluation has no such import and is safe at module scope.

SCHEMA_VERSION = 1

# --- status vocabulary (module docstring) ------------------------------------

WAITING_FOR_REFERENCE_DATA = pw.WAITING_FOR_REFERENCE_DATA
RETRY_REQUIRED = pw.RETRY_REQUIRED
COMPLETED = pw.COMPLETED
FAILED = pw.FAILED
# Not one of parity_world.STATES (module docstring): store_world has no
# generation states to traverse, so the whole generation phase is this one
# status rather than several parity_world never produces for a stored mission.
AGENTS_RUNNING = "AGENTS_RUNNING"

STATUSES = (WAITING_FOR_REFERENCE_DATA, AGENTS_RUNNING, RETRY_REQUIRED, COMPLETED, FAILED)

# A mission in one of these two statuses stored no world (WAITING) or failed
# before storing one (FAILED, e.g. n_scenarios > focus assets) - so a second
# start_mission call against the same mission_id is a legitimate retry, not
# an overwrite of running or completed work.
_RETRYABLE_STATUSES = (WAITING_FOR_REFERENCE_DATA, FAILED)


class ActivationRefused(ValueError):
    """start_mission's refusal when run_mode is not 'simulation' (addendum 25
    SS2's activation rule, already enforced inside MissionConfig itself -
    this is the honest message mission control shows for the other two
    offered modes, distinguished from an ordinary bad-config ValueError so
    the route can answer 400 with SS2's actual reasoning rather than
    MissionConfig's internal wording)."""


class MissionConflict(Exception):
    """start_mission's refusal when mission_id names a mission that already
    stored a world or is otherwise not in a retryable status - never turned
    into a row update, so the route answers 409 rather than silently
    re-storing over running or completed work."""


class MissionNotStored(Exception):
    """evaluate()'s refusal when the mission has no summary_path yet - there
    is no ground truth to grade against, so there is nothing to evaluate."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS missions (
    mission_id TEXT PRIMARY KEY,
    run_mode TEXT NOT NULL,
    strategy TEXT NOT NULL,
    config TEXT NOT NULL,            -- the full MissionConfig as JSON
    status TEXT NOT NULL,
    note TEXT,                       -- why the mission is in this status (refusal detail, failure)
    summary_path TEXT,               -- ground truth lives in the file, never in this table
    evaluation_path TEXT,
    diagnosis_path TEXT,
    metrics TEXT,                    -- latest evaluation metrics JSON, cached for the dashboard
    requested_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);
"""


def init_schema(conn) -> None:
    conn.executescript(SCHEMA)


# --- row shape ----------------------------------------------------------------


def _parse_row(row: dict) -> dict:
    mission = dict(row)
    mission["config"] = json.loads(mission["config"])
    mission["metrics"] = json.loads(mission["metrics"]) if mission["metrics"] else None
    return mission


def get_mission(conn, mission_id: str) -> dict | None:
    row = conn.fetchone("SELECT * FROM missions WHERE mission_id = ?", (mission_id,))
    return _parse_row(row) if row is not None else None


def list_missions(conn) -> list[dict]:
    rows = conn.fetchall("SELECT * FROM missions ORDER BY requested_at DESC, mission_id DESC")
    return [_parse_row(row) for row in rows]


def _upsert_mission(conn, config: pw.MissionConfig, config_json: str, status: str,
                     note: str | None, summary_path: str | None = None) -> None:
    """One row per mission_id, inserted on the first attempt and updated on a
    retry - `requested_at` is deliberately excluded from the conflict clause
    so a retry keeps the mission's original request time, and
    evaluation_path/diagnosis_path/metrics are always reset to NULL here:
    every call to this function follows a fresh store_world attempt, and
    the only two statuses eligible for one (WAITING, FAILED) never had an
    evaluation to preserve in the first place."""
    now = db_module.now_iso()
    conn.execute(
        "INSERT INTO missions "
        "(mission_id, run_mode, strategy, config, status, note, summary_path, "
        "evaluation_path, diagnosis_path, metrics, requested_at, updated_at, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?) "
        "ON CONFLICT(mission_id) DO UPDATE SET "
        "run_mode = excluded.run_mode, strategy = excluded.strategy, config = excluded.config, "
        "status = excluded.status, note = excluded.note, summary_path = excluded.summary_path, "
        "evaluation_path = NULL, diagnosis_path = NULL, metrics = NULL, updated_at = excluded.updated_at",
        (
            config.mission_id, config.run_mode, config.strategy, config_json, status, note,
            summary_path, now, now, SCHEMA_VERSION,
        ),
    )


# --- orchestration entry point -------------------------------------------------


def start_mission(conn, config_data: dict, runs_dir=None) -> dict:
    """Build a MissionConfig, gate it through the reference-data check
    store_world already enforces, and record the outcome as a mission row.

    Raises ActivationRefused or MissionConflict for the two refusals that
    never become a row (module docstring); everything else - including a
    reference-data block, and a bad config like too many scenarios - returns
    a mission dict, because addendum 25 SS23 wants a blocked or failed
    mission to be something the dashboard shows, not an exception a caller
    has to catch."""
    try:
        config = pw.MissionConfig.from_dict(config_data)
    except ValueError as exc:
        # MissionConfig._validate raises this exact message for SS2's
        # activation rule and nothing else - matched by content rather than
        # re-implementing the check here, so the two can never drift on what
        # counts as the run_mode refusal.
        if "run_mode must be 'simulation'" in str(exc):
            raise ActivationRefused(
                f"Run mode {config_data.get('run_mode')!r} is offered by mission control but only "
                "Simulation activates this engine; the Historical and Live engines take their own "
                "missions when they exist."
            ) from exc
        raise

    mission_id = config.mission_id
    existing = get_mission(conn, mission_id)
    if existing is not None and existing["status"] not in _RETRYABLE_STATUSES:
        raise MissionConflict(
            f"mission {mission_id!r} is already {existing['status']} - a mission that stored a "
            "world must not be silently re-stored over."
        )

    config_json = json.dumps(asdict(config))

    try:
        stored = pw.store_world(conn, config, runs_dir=runs_dir)
    except pw.ReferenceNotReady as exc:
        _upsert_mission(conn, config, config_json, WAITING_FOR_REFERENCE_DATA, str(exc))
        return {**get_mission(conn, mission_id), "stored": None}
    except ValueError as exc:
        _upsert_mission(conn, config, config_json, FAILED, str(exc))
        return {**get_mission(conn, mission_id), "stored": None}

    _upsert_mission(conn, config, config_json, AGENTS_RUNNING, None, summary_path=stored["summary_path"])
    return {**get_mission(conn, mission_id), "stored": stored}


# --- dashboard progress (addendum 25 SS22) -------------------------------------


def pipeline_counts(conn, mission_id: str) -> dict:
    """The organization's own records for this mission_id - plain SQL, not
    fi_db functions (the layering rule: this module is imported by fi_db, so
    it cannot import fi_db back).

    Mirrors simulation/parity_evaluation.py's own join path exactly:
    parity_events.run_id is the mission key; discovery_reports and
    discovery_reports_completed both join to it via parity_event_id (a
    report can be in either depending on whether Analysis has finished);
    analysis_results joins to whichever of those two a report's id came
    from, since the archive trigger copies a report's id verbatim."""
    detections_row = conn.fetchone(
        "SELECT COUNT(*) AS n, COUNT(DISTINCT scenario_id) AS scenarios "
        "FROM parity_events WHERE run_id = ?",
        (mission_id,),
    )
    pending_rows = conn.fetchall(
        "SELECT dr.id AS report_id FROM discovery_reports dr "
        "JOIN parity_events pe ON dr.parity_event_id = pe.id WHERE pe.run_id = ?",
        (mission_id,),
    )
    completed_rows = conn.fetchall(
        "SELECT drc.id AS report_id FROM discovery_reports_completed drc "
        "JOIN parity_events pe ON drc.parity_event_id = pe.id WHERE pe.run_id = ?",
        (mission_id,),
    )
    report_ids = [row["report_id"] for row in pending_rows] + [row["report_id"] for row in completed_rows]
    analyses = 0
    if report_ids:
        placeholders = ",".join("?" for _ in report_ids)
        analyses = conn.fetchone(
            f"SELECT COUNT(*) AS n FROM analysis_results WHERE report_id IN ({placeholders})",
            report_ids,
        )["n"]

    return {
        "detections": detections_row["n"] or 0,
        "scenarios_with_detections": detections_row["scenarios"] or 0,
        "reports_pending": len(pending_rows),
        "reports_completed": len(completed_rows),
        "analyses": analyses,
    }


# --- grading pass ---------------------------------------------------------------


def evaluate(conn, mission_id: str) -> dict | None:
    """Run the Evaluator and Diagnosis stage over a stored mission, cache
    the result on the row, and return {mission, evaluation, diagnosis}.

    Returns None for an unknown mission_id (nothing to refuse, nothing to
    grade) and raises MissionNotStored for a known mission with no
    summary_path (module docstring) - the two different "nothing to
    evaluate" cases the route maps to 404 and 409 respectively."""
    from simulation import parity_diagnosis  # lazy - see the import comment at module scope

    mission = get_mission(conn, mission_id)
    if mission is None:
        return None
    if not mission["summary_path"]:
        raise MissionNotStored(
            f"mission {mission_id!r} has no stored world yet (status={mission['status']}) - "
            "nothing to evaluate."
        )

    evaluation = parity_evaluation.evaluate_mission(conn, mission["summary_path"])
    diagnosis = parity_diagnosis.diagnose_mission(conn, evaluation["evaluation_path"])

    if diagnosis["mission_certified_complete"]:
        status = COMPLETED
    elif diagnosis["retry_recommended"]:
        status = RETRY_REQUIRED
    else:
        # wait_and_reevaluate: nothing failed and nothing needs correction,
        # some scenario is merely still in flight (an open cross-check, a
        # report Analysis hasn't picked up yet) - a run that needs time
        # keeps its running status rather than being mislabeled RETRY_REQUIRED.
        status = AGENTS_RUNNING

    conn.execute(
        "UPDATE missions SET status = ?, metrics = ?, evaluation_path = ?, diagnosis_path = ?, "
        "updated_at = ? WHERE mission_id = ?",
        (
            status, json.dumps(evaluation["metrics"]), evaluation["evaluation_path"],
            diagnosis["diagnosis_path"], db_module.now_iso(), mission_id,
        ),
    )
    return {"mission": get_mission(conn, mission_id), "evaluation": evaluation, "diagnosis": diagnosis}


# --- dropdown feed (addendum 25 SS4) --------------------------------------------


def mission_options(conn) -> dict:
    """What mission control's own dropdowns are fed from. Extending the
    mission system (SS4) is extending one of these three sources - a new
    strategy is a parity_world.STRATEGIES addition, a new capable asset
    class is a registry flag flip (backend/reference_data.set_capability) -
    not a change to this function or the UI reading it."""
    asset_classes = conn.fetchall(
        "SELECT asset_class, display_name FROM asset_classes WHERE in_capability = 1 ORDER BY asset_class"
    )
    return {
        # All three run modes are listed because SS4 says the interface must
        # offer them; SS2's activation rule (ActivationRefused above) is what
        # decides what happens once one is actually chosen.
        "run_modes": ["simulation", "historical", "live"],
        "strategies": list(pw.STRATEGIES),
        "asset_classes": asset_classes,
    }
