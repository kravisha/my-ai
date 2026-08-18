"""The Data Store: canonical observations, kept.

Addendum 20 §4 names this store - "raw observations, events, market data, news,
and simulation data" - and PR #19 deliberately did not build it, on the rule that
a table written by nothing is an empty schema. The Historical Market Data Engine
is the first thing with observations to keep, so the store arrives with it.

## What a row is

One canonical `Observation` (backend/canonical.py), flattened. The contract's
promises survive storage on purpose:

- **provenance is columns, not a blob.** `origin` is NOT NULL and CHECK-limited to
  the three values the contract admits, so a row cannot lose its origin on the way
  in or acquire an "unknown" one in a migration. The Manifesto's §15 has to hold
  in the table, because the table outlives every process that promised to behave.
- **`knowable_at` is stored, not derived on read.** It was derived from the
  cadence's publication lag when the Observation was built; storing the answer
  makes replay's lookahead filter a WHERE clause rather than a join against a
  taxonomy that may have been edited since.

## Idempotent ingest, by declaration

`(entity_id, data_class, observed_at, origin, source)` is unique. Re-ingesting a
file is the *normal* case - a re-run after a crash, a refreshed download, an
overlapping date range - and it must converge rather than duplicate. The same
fact from a *different* source is deliberately not a conflict: two vendors
disagreeing about a close is information, and collapsing them would destroy the
disagreement before anything could learn from it.

## Replay reads at a moment

`replay()` answers "what did this entity look like over [start, end], as knowable
by T" - the §2B replay obligation, with the lookahead guard applied in SQL. A
caller that omits `as_knowable_by` gets everything, which is the honest default
for analysis done in hindsight; training against history must pass the clock it
is pretending to be at.
"""

from __future__ import annotations

import json

from backend.canonical import Observation, Provenance
from backend.db import Database

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL,
    data_class TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    knowable_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('synthetic', 'historical', 'live')),
    source TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    run_id TEXT,
    scenario_id TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE UNIQUE INDEX IF NOT EXISTS observations_one_fact_per_source
    ON observations (entity_id, data_class, observed_at, origin, source);
CREATE INDEX IF NOT EXISTS observations_replay
    ON observations (entity_id, data_class, observed_at, knowable_at);
"""


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)


def store(conn: Database, observation: Observation) -> bool:
    """Keep one observation. Returns True if it was new, False if this exact fact
    from this source was already held - which is convergence, not an error."""
    record = observation.as_record()
    existing = conn.fetchone(
        "SELECT 1 FROM observations WHERE entity_id = ? AND data_class = ? "
        "AND observed_at = ? AND origin = ? AND source = ?",
        (record["entity_id"], record["data_class"], record["observed_at"],
         record["origin"], record["source"]),
    )
    if existing is not None:
        return False
    conn.execute(
        "INSERT INTO observations (entity_id, data_class, observed_at, knowable_at, payload, "
        "origin, source, captured_at, run_id, scenario_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (record["entity_id"], record["data_class"], record["observed_at"],
         record["knowable_at"], json.dumps(record["payload"]), record["origin"],
         record["source"], record["captured_at"], record["run_id"], record["scenario_id"]),
    )
    return True


def store_many(conn: Database, observations) -> dict:
    """Bulk ingest. Reports what happened rather than assuming it: an ingest
    summary that cannot say 'kept 240, already held 12' cannot be checked against
    the file it read."""
    kept = duplicate = 0
    for observation in observations:
        if store(conn, observation):
            kept += 1
        else:
            duplicate += 1
    return {"kept": kept, "already_held": duplicate}


def replay(
    conn: Database,
    entity_id: str,
    data_class: str,
    start: str | None = None,
    end: str | None = None,
    as_knowable_by: str | None = None,
    origins: tuple[str, ...] | None = None,
) -> list[Observation]:
    """The engine's read side: observations in observed_at order, optionally
    bounded, optionally as knowable by a moment, optionally restricted by origin.

    `origins` is how a consumer says which worlds it accepts - the deliberate
    mixing §15 permits, made explicit at the query. Training against history
    passes ('historical',) and cannot silently pick up synthetic rows that share
    the table."""
    sql = "SELECT * FROM observations WHERE entity_id = ? AND data_class = ?"
    params: list = [entity_id, data_class]
    if start is not None:
        sql += " AND observed_at >= ?"
        params.append(start)
    if end is not None:
        sql += " AND observed_at <= ?"
        params.append(end)
    if as_knowable_by is not None:
        sql += " AND knowable_at <= ?"
        params.append(as_knowable_by)
    if origins:
        sql += f" AND origin IN ({','.join('?' * len(origins))})"
        params.extend(origins)
    sql += " ORDER BY observed_at"

    return [_to_observation(row) for row in conn.fetchall(sql, tuple(params))]


def coverage(conn: Database, entity_id: str, data_class: str) -> dict | None:
    """What is held for an entity: span and count, per origin. The question an
    ingest is checked against, and the one a training run asks before promising a
    date range it does not have."""
    rows = conn.fetchall(
        "SELECT origin, COUNT(*) AS n, MIN(observed_at) AS first, MAX(observed_at) AS last "
        "FROM observations WHERE entity_id = ? AND data_class = ? GROUP BY origin",
        (entity_id, data_class),
    )
    if not rows:
        return None
    return {row["origin"]: {"count": row["n"], "first": row["first"], "last": row["last"]}
            for row in rows}


def _to_observation(row: dict) -> Observation:
    """A stored row back into the contract type, provenance and all - so replay
    consumers get the same object producers emitted, with `known_by` and the rest
    intact rather than a bare dict that has forgotten its guarantees."""
    return Observation(
        entity_id=row["entity_id"],
        data_class=row["data_class"],
        observed_at=row["observed_at"],
        knowable_at=row["knowable_at"],
        payload=json.loads(row["payload"]),
        provenance=Provenance(
            origin=row["origin"],
            source=row["source"],
            captured_at=row["captured_at"],
            run_id=row["run_id"],
            scenario_id=row["scenario_id"],
        ),
    )
