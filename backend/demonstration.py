"""The Demonstration Engine's own record of what it ran
(Demonstration Engine Specification; docs/SPEC_RECONCILIATION.md §158).

The specification asks for a *demo event model* with eighteen fields. Most of it
already exists: `status_events` carries event id, timestamp, source department,
source engine, source agent, event type, severity, status, message, task id and
correlation id, and it is written by the real system during ordinary operation.
The specification's own rule — *"avoid invasive instrumentation where ordinary
system telemetry is sufficient"* — therefore says not to build a second event
table, and this module does not.

What genuinely does not exist is the record of a **demonstration** as a thing:
which acts were performed, which real scenario run each one orchestrated, and
what the Superuser was shown. That is what is here, and nothing else.

## What this deliberately does not store

**No demo results.** An act points at the run directory and the run id of a real
scenario run, and every number about that run is read back out of the run's own
database by `simulation/metrics.py`. Copying metrics into a demo table would
create a second answer to *what happened*, and the demo's whole claim is that it
shows the real system rather than a retelling of it.

**No Superuser score.** The specification asks for one and directive §10 asks for
a general feedback store attached to *"the relevant system state, feature,
department, demo, or change"* — five subjects, of which a demo is one. A
demo-only score table would be the wrong shape for four of them and would have to
be replaced. It is named as absent rather than half-built (§158 §5).

Sits below the `demonstration` package, which orchestrates. This module only
records.
"""

from __future__ import annotations

import json

from backend.db import Database, now_iso

SCHEMA = """
-- One row per demonstration the Superuser asked for.
CREATE TABLE IF NOT EXISTS demo_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    demo_id TEXT NOT NULL UNIQUE,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    -- Which commit was demonstrated. Read from git, never chosen: the same
    -- prevention-by-absence that keeps the organization from deploying itself.
    code_version TEXT NOT NULL,
    -- The specification requires a demo to state what kind of data it used.
    -- Today there is exactly one honest value and it is not a placeholder for a
    -- richer one: every price in this system is synthetic (§113).
    data_mode TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);

-- One row per act. An act is a thing the demo set out to show, and the real
-- scenario run it used to show it.
CREATE TABLE IF NOT EXISTS demo_acts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    demo_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    -- What this act is meant to demonstrate, in the registry's vocabulary.
    capability TEXT NOT NULL,
    title TEXT NOT NULL,
    scenario_id TEXT,
    -- The real run. Everything measurable about this act is read from here
    -- rather than copied to a column, so the demo cannot drift from the run.
    run_id TEXT,
    run_directory TEXT,
    outcome TEXT NOT NULL,
    detail TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS demo_acts_by_demo ON demo_acts (demo_id, sequence);
"""

SCHEMA_VERSION = 1

STATUS_RUNNING = "running"
STATUS_COMPLETE = "complete"
STATUS_FAILED = "failed"

OUTCOME_SHOWN = "shown"
OUTCOME_FAILED = "failed"
# The act ran and the thing it exists to show did not happen. Distinct from
# failed on purpose: the specification says a demo must report failure honestly,
# and "the organization did not do the thing" is not the same as "the demo
# broke".
OUTCOME_NOT_OBSERVED = "not_observed"
# Named and not attempted, because what it demonstrates does not exist yet.
OUTCOME_UNAVAILABLE = "unavailable"
OUTCOMES = (OUTCOME_SHOWN, OUTCOME_FAILED, OUTCOME_NOT_OBSERVED, OUTCOME_UNAVAILABLE)

DATA_MODE_SYNTHETIC = "synthetic"


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)


def open_demo(conn: Database, *, demo_id: str, mode: str, code_version: str,
              data_mode: str = DATA_MODE_SYNTHETIC) -> int:
    return conn.execute_returning_id(
        "INSERT INTO demo_runs (demo_id, mode, started_at, code_version, data_mode, status,"
        " schema_version) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (demo_id, mode, now_iso(), code_version, data_mode, STATUS_RUNNING, SCHEMA_VERSION))


def record_act(conn: Database, *, demo_id: str, sequence: int, capability: str, title: str,
               outcome: str, scenario_id: str | None = None, run_id: str | None = None,
               run_directory: str | None = None, detail: str | None = None) -> int:
    """Write down one act.

    `outcome` is refused rather than defaulted if unknown: an act whose result
    could not be determined must not read as one that succeeded."""
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown act outcome {outcome!r}; known are {list(OUTCOMES)}")
    return conn.execute_returning_id(
        "INSERT INTO demo_acts (demo_id, sequence, capability, title, scenario_id, run_id,"
        " run_directory, outcome, detail, schema_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (demo_id, sequence, capability, title, scenario_id, run_id, run_directory, outcome,
         detail if isinstance(detail, str) or detail is None else json.dumps(detail),
         SCHEMA_VERSION))


def close_demo(conn: Database, demo_id: str, *, status: str, detail: str | None = None) -> None:
    conn.execute(
        "UPDATE demo_runs SET finished_at = ?, status = ?, detail = ? WHERE demo_id = ?",
        (now_iso(), status, detail, demo_id))


def get_demo(conn: Database, demo_id: str) -> dict | None:
    return conn.fetchone("SELECT * FROM demo_runs WHERE demo_id = ?", (demo_id,))


def acts_of(conn: Database, demo_id: str) -> list[dict]:
    return conn.fetchall(
        "SELECT * FROM demo_acts WHERE demo_id = ? ORDER BY sequence", (demo_id,))


def recent_demos(conn: Database, limit: int = 20) -> list[dict]:
    return conn.fetchall("SELECT * FROM demo_runs ORDER BY id DESC LIMIT ?", (limit,))
