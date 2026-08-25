"""The status event stream (addendum 38 §4.3/§4.4/§4.5/§4.6/§12/§13;
TASK_QUEUE TQ-24, docs/SPEC_RECONCILIATION.md §73).

The observability spine of Pre-Alpha Milestone 1: the durable record of what
the system did, which the COO's live feed renders, its filters slice, and its
chat answers from. §70's finding was that Milestone 1's real gap is
observability rather than persistence — this is that gap.

## What belongs here, and what emphatically does not

Addendum 38 §13 is blunt: "Avoid excessive high-frequency logging. The
objective is useful observability, not log flooding." So the rule this module
is written under, stated once:

**State transitions and narration belong here. Heartbeats do not.**

Agents already heartbeat every second into `agent_registry`, and health
samples already land in `health_metrics`. Copying those into this table would
add ~86,400 rows per agent per day, drown every real event, and duplicate two
mechanisms that already work — the "two models of one fact" error the Conflict
Rule forbids, with flooding on top. A component that is *still* healthy has
nothing to narrate; a component that *becomes* unhealthy has an event.

## The schema is the specification's, minus what would be invented

§4.3 lists twelve fields. All twelve are here, and the ones a given publisher
cannot honestly fill stay NULL rather than being padded with placeholders —
an engine is not an agent, and startup is not a task. `event_id` is the row
id: sortable, unique, and already durable, where a generated uuid would be a
second identity for the same row.

## Filters are derived, never enumerated

§4.4 lists the filters Milestone 1 needs and then adds the requirement that
actually matters: "Architecture should allow new departments to appear without
rewriting the UI." A hardcoded filter list fails that on the day a department
is added. So `sources()` returns what the stream *actually contains*, and a
new department appears in the UI because it published, not because someone
edited a list.

## Durable, bounded, and honest about being neither exhaustive nor forever

§4.6 asks for enough history for recent queries, debugging, restart continuity
and post-mortem — and explicitly says "a full enterprise event store is not
required for pre-alpha. A simple durable implementation is sufficient." This
is a SQLite table with a retention cap, pruned oldest-first, following the
same shape `continuity.prune_backups` already uses. Retention is a disclosed
convention, not a measurement.
"""

from __future__ import annotations

import os

from backend.db import Database, now_iso

# --- vocabulary (addendum 38 §4.3) -------------------------------------------

SEVERITY_DEBUG = "DEBUG"
SEVERITY_INFO = "INFO"
SEVERITY_WARNING = "WARNING"
SEVERITY_ERROR = "ERROR"
SEVERITY_CRITICAL = "CRITICAL"
SEVERITIES = (SEVERITY_DEBUG, SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_ERROR, SEVERITY_CRITICAL)

# Ordered worst-last, so "at least WARNING" is a slice rather than a lookup
# table somebody has to keep in step with the tuple above.
_SEVERITY_RANK = {name: rank for rank, name in enumerate(SEVERITIES)}

# §4.4's "Errors/Warnings" filter, named once here rather than reconstructed
# by every caller that wants it.
ATTENTION_SEVERITIES = (SEVERITY_WARNING, SEVERITY_ERROR, SEVERITY_CRITICAL)

STATUS_STARTING = "STARTING"
STATUS_RUNNING = "RUNNING"
STATUS_WAITING = "WAITING"
STATUS_IDLE = "IDLE"
STATUS_READY = "READY"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"
STATUS_STOPPING = "STOPPING"
STATUS_STOPPED = "STOPPED"
STATUS_RESTORED = "RESTORED"
STATUSES = (
    STATUS_STARTING, STATUS_RUNNING, STATUS_WAITING, STATUS_IDLE, STATUS_READY,
    STATUS_COMPLETED, STATUS_FAILED, STATUS_STOPPING, STATUS_STOPPED, STATUS_RESTORED,
)

# How many events the stream keeps. A disclosed convention (the
# TIMING_CONSTANTS.md discipline), not a measured requirement: large enough
# that a whole startup plus a working session survives for post-mortem, small
# enough that the table never becomes the reason a restore is slow.
RETENTION_ENV = "STATUS_EVENT_RETENTION"
DEFAULT_RETENTION = 20_000

SCHEMA = """
-- Addendum 38 §4.3's status event, durable (§4.6). Read by the COO's live
-- feed, its filters, and its state-grounded chat. See the module docstring
-- for what deliberately does NOT get published here: heartbeats, which
-- agent_registry and health_metrics already carry and which would flood this.
CREATE TABLE IF NOT EXISTS status_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,   -- §4.3's event_id: already unique and sortable
    timestamp TEXT NOT NULL,
    lifecycle_stage TEXT,
    -- The three-part source §4.3 names. All nullable because a given
    -- publisher honestly fills only some: an engine has no agent, an agent
    -- may have no department yet. Filters read whichever is present.
    source_department TEXT,
    source_engine TEXT,
    source_agent TEXT,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL,
    task_id TEXT,
    correlation_id TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);
-- The feed is always read newest-first, and filtered by severity or source.
CREATE INDEX IF NOT EXISTS status_events_recent ON status_events (id DESC);
CREATE INDEX IF NOT EXISTS status_events_by_severity ON status_events (severity, id DESC);
CREATE INDEX IF NOT EXISTS status_events_by_correlation ON status_events (correlation_id, id);
"""


def retention_limit() -> int:
    """Resolved at call time so a reconfigured process sees the current value
    - the convention every other tunable in this codebase follows."""
    raw = os.environ.get(RETENTION_ENV)
    if raw is None or raw == "":
        return DEFAULT_RETENTION
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(
            f"{RETENTION_ENV}={raw!r} is not an integer. Refusing to guess a retention limit."
        ) from None
    if value < 1:
        raise ValueError(f"{RETENTION_ENV} must keep at least one event; got {value}")
    return value


def publish(
    conn: Database,
    event_type: str,
    message: str,
    *,
    severity: str = SEVERITY_INFO,
    status: str = STATUS_RUNNING,
    lifecycle_stage: str | None = None,
    department: str | None = None,
    engine: str | None = None,
    agent: str | None = None,
    task_id: str | None = None,
    correlation_id: str | None = None,
    timestamp: str | None = None,
) -> int:
    """Record one event and return its id (§4.3's event_id).

    Vocabulary is fail-closed: an unknown severity or status raises rather
    than being stored. A stream containing severities nobody defined cannot
    be filtered by severity, which is most of what a stream is for - the
    same reasoning `backend/register.py` applies to its own vocabulary.

    At least one source must be named. An event from nowhere cannot be
    filtered, cannot be attributed, and is exactly the "failed component
    silently disappearing" §12 forbids - it would still be in the table and
    still be invisible in every filtered view."""
    if severity not in SEVERITIES:
        raise ValueError(f"unknown severity {severity!r}; known: {SEVERITIES}")
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}; known: {STATUSES}")
    if not (department or engine or agent):
        raise ValueError(
            f"status event {event_type!r} names no source; give at least one of "
            "department, engine or agent so it can be filtered and attributed"
        )
    if not message:
        raise ValueError(f"status event {event_type!r} has an empty message")

    conn.execute(
        "INSERT INTO status_events (timestamp, lifecycle_stage, source_department, source_engine, "
        "source_agent, event_type, severity, status, message, task_id, correlation_id, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
        (timestamp or now_iso(), lifecycle_stage, department, engine, agent,
         event_type, severity, status, message, task_id, correlation_id),
    )
    return conn.fetchone("SELECT last_insert_rowid() AS id")["id"]


def publish_many(conn: Database, events: list[dict]) -> list[int]:
    """Publish a batch - what an engine that produced its narration as data
    (backend/metadata_engine.py's `run`) hands over once its work is done.

    Each dict uses the same keys `publish` takes; unknown keys are refused
    rather than ignored, because a typo'd 'sevrity' silently becoming INFO
    would be a stream that lies quietly."""
    allowed = {
        "event_type", "message", "severity", "status", "lifecycle_stage",
        "department", "engine", "agent", "task_id", "correlation_id", "timestamp",
    }
    ids = []
    for event in events:
        unknown = set(event) - allowed
        if unknown:
            raise ValueError(f"status event carries unknown field(s) {sorted(unknown)}; known: {sorted(allowed)}")
        payload = dict(event)
        ids.append(publish(conn, payload.pop("event_type"), payload.pop("message"), **payload))
    return ids


def _row_to_event(row) -> dict:
    event = dict(row)
    event["event_id"] = event.pop("id")  # §4.3's own field name
    return event


def recent(
    conn: Database,
    *,
    limit: int = 50,
    source: str | None = None,
    severities: tuple[str, ...] | list[str] | None = None,
    since: str | None = None,
    correlation_id: str | None = None,
) -> list[dict]:
    """The feed, newest first (§4.2), with §4.4's filters.

    `source` matches any of the three source columns, because §4.4's filter
    list mixes departments, engines and agents in one control and an operator
    picking "Explorer" does not care which column it lives in."""
    clauses, params = [], []
    if source is not None:
        clauses.append("(source_department = ? OR source_engine = ? OR source_agent = ?)")
        params += [source, source, source]
    if severities:
        unknown = sorted(set(severities) - set(SEVERITIES))
        if unknown:
            raise ValueError(f"unknown severity filter {unknown}; known: {SEVERITIES}")
        clauses.append(f"severity IN ({','.join('?' * len(severities))})")
        params += list(severities)
    if since is not None:
        clauses.append("timestamp >= ?")
        params.append(since)
    if correlation_id is not None:
        clauses.append("correlation_id = ?")
        params.append(correlation_id)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    rows = conn.fetchall(f"SELECT * FROM status_events {where} ORDER BY id DESC LIMIT ?", tuple(params))
    return [_row_to_event(row) for row in rows]


def sources(conn: Database) -> list[dict]:
    """Every source the stream actually contains, with its event count and
    how much of it wants attention - the filter list §4.4 requires be
    derivable rather than enumerated, so a new department appears because it
    published rather than because somebody edited a list."""
    found: dict[tuple[str, str], dict] = {}
    for kind, column in (("department", "source_department"),
                         ("engine", "source_engine"),
                         ("agent", "source_agent")):
        for row in conn.fetchall(
            f"SELECT {column} AS name, COUNT(*) AS events, "
            f"SUM(CASE WHEN severity IN ('WARNING','ERROR','CRITICAL') THEN 1 ELSE 0 END) AS attention "
            f"FROM status_events WHERE {column} IS NOT NULL GROUP BY {column}"
        ):
            found[(kind, row["name"])] = {
                "kind": kind, "name": row["name"],
                "events": row["events"], "attention": row["attention"] or 0,
            }
    return sorted(found.values(), key=lambda item: (item["kind"], item["name"]))


def failures(conn: Database, *, limit: int = 50, since: str | None = None) -> list[dict]:
    """"What failed during startup?" (§4.5) as a query rather than a scroll.
    ERROR and CRITICAL only - a WARNING is a thing worth seeing, not a
    thing that failed."""
    return recent(conn, limit=limit, since=since,
                  severities=(SEVERITY_ERROR, SEVERITY_CRITICAL))


def current_status(conn: Database) -> list[dict]:
    """The latest event per source: what every component is doing *now*,
    which is the question §4.5's "which departments are idle?" and "what is
    waiting for work?" actually ask.

    A feed answers "what happened"; this answers "where does everything
    stand", and the two are different questions on the same data."""
    rows = conn.fetchall(
        "SELECT * FROM status_events WHERE id IN ("
        "  SELECT MAX(id) FROM status_events"
        "  WHERE COALESCE(source_agent, source_engine, source_department) IS NOT NULL"
        "  GROUP BY COALESCE(source_agent, source_engine, source_department)"
        ") ORDER BY id DESC"
    )
    return [_row_to_event(row) for row in rows]


def prune(conn: Database, keep: int | None = None) -> int:
    """Drop the oldest events beyond the retention limit; returns how many
    were removed. Oldest-first by id, which is insertion order - the same
    retention shape `continuity.prune_backups` uses."""
    keep = retention_limit() if keep is None else keep
    if keep < 1:
        raise ValueError(f"retention must keep at least one event; got {keep}")
    total = conn.fetchone("SELECT COUNT(*) AS n FROM status_events")["n"]
    if total <= keep:
        return 0
    conn.execute(
        "DELETE FROM status_events WHERE id IN ("
        "  SELECT id FROM status_events ORDER BY id ASC LIMIT ?"
        ")",
        (total - keep,),
    )
    return total - keep
