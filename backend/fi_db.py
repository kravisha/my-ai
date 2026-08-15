"""Financial Intelligence system's coordination substrate: SQLite (WAL mode)
as the *only* channel between processes - see docs/addenda/addendum_6 §1-3
and the confirmed decision in [[project_my_ai_financial_intelligence]] that
no agent ever calls another agent directly. Every coordination act (COO
directives, agent registration, health) is a row in one of these tables.

Table design follows the queue-vs-log principle worked out this session:
a table gets the pending->completed split only if something needs to ask
"is there unprocessed work here?" (coo_directives). Pure facts with no
consumer that "completes" them are single append/update tables
(agent_registry, health_metrics).

The pending->completed move for directives is enforced by a SQL trigger,
not application code doing a manual delete+insert - the DB itself
guarantees the invariant, per the plan's explicit intent, rather than
depending on every call site remembering to do both steps correctly.

Schema evolution rule (confirmed 2026-08-14, resolving Gap 1's proposed
schema_version removal by keeping both ideas rather than picking one):
columns are only ever ADDED, never renamed or removed - every historical
row stays fully readable under the current column layout, so there's
nothing a version tag needs to disambiguate about *shape*. SCHEMA_VERSION
below is a separate concern: a producer/semantic version, bumped when the
*meaning* of written data changes even though the columns look the same
(e.g. a detector algorithm change that shifts what a confidence score
represents) - satisfies addendum_10 Phase A's literal "every message
carries... schema version" requirement without contradicting it.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "financial_intelligence.db"

# Bump only when the *meaning* of newly-written rows changes in a way a
# future reader/grader needs to distinguish from older rows - not on every
# column addition (see the additive-only-columns rule above).
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_registry (
    identity TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    pid INTEGER,
    status TEXT NOT NULL DEFAULT 'active',
    retire_requested INTEGER NOT NULL DEFAULT 0,
    spawned_at TEXT NOT NULL,
    last_heartbeat_at TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS coo_directives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    directive_type TEXT NOT NULL,
    target_role TEXT,
    target_identity TEXT,
    params TEXT,
    requested_by TEXT NOT NULL,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    detail TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS coo_directives_completed (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    directive_type TEXT NOT NULL,
    target_role TEXT,
    target_identity TEXT,
    params TEXT,
    requested_by TEXT NOT NULL,
    reason TEXT,
    completed_at TEXT NOT NULL,
    outcome TEXT NOT NULL,
    detail TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1,
    observed_result TEXT,
    observed_at TEXT
);

CREATE TRIGGER IF NOT EXISTS coo_directives_archive
AFTER UPDATE OF status ON coo_directives
WHEN NEW.status IN ('success', 'failure')
BEGIN
    INSERT INTO coo_directives_completed
        (id, timestamp, directive_type, target_role, target_identity, params, requested_by, reason, completed_at, outcome, detail, schema_version)
    VALUES
        (NEW.id, NEW.timestamp, NEW.directive_type, NEW.target_role, NEW.target_identity, NEW.params, NEW.requested_by, NEW.reason,
         strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), NEW.status, NEW.detail, NEW.schema_version);
    DELETE FROM coo_directives WHERE id = NEW.id;
END;

CREATE TABLE IF NOT EXISTS health_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    identity TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    metric TEXT NOT NULL,
    value TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE VIEW IF NOT EXISTS performance_card AS
SELECT
    r.identity,
    r.role,
    r.status,
    r.spawned_at,
    r.last_heartbeat_at,
    (SELECT COUNT(*) FROM health_metrics h WHERE h.identity = r.identity) AS heartbeat_count
FROM agent_registry r;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value: str) -> datetime:
    """Normalizes the two timestamp shapes this module produces: Python's
    own _now() (e.g. '...+00:00') and the SQL archive trigger's strftime
    (e.g. '...Z'). Comparing them as raw strings is fragile - this is the
    one place that difference gets handled, instead of every call site
    reimplementing the same .replace("Z", "+00:00") fix."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


# --- Agent registry ---


def register_agent(conn: sqlite3.Connection, identity: str, role: str, pid: int) -> None:
    """identity is a permanent role-slot ID (addendum_5 §4: durable
    performance record independent of any one process instance - see
    backend/coordinator.py's _slot_identity), so this INSERT...ON CONFLICT
    path is the normal case for a respawn, not an edge case: the same
    identity comes back to life under a new pid. last_heartbeat_at is
    explicitly reset to NULL on that path - without it, a respawned agent
    would inherit its *previous* life's last heartbeat, which could already
    be well past agents/coo.py's staleness threshold and get the freshly-
    registered agent marked 'crashed' before it ever got a chance."""
    now = _now()
    conn.execute(
        "INSERT INTO agent_registry (identity, role, pid, status, retire_requested, spawned_at, last_heartbeat_at, schema_version) "
        "VALUES (?, ?, ?, 'active', 0, ?, NULL, ?) "
        "ON CONFLICT(identity) DO UPDATE SET pid=excluded.pid, status='active', retire_requested=0, spawned_at=excluded.spawned_at, last_heartbeat_at=NULL, schema_version=excluded.schema_version",
        (identity, role, pid, now, SCHEMA_VERSION),
    )
    conn.commit()


def request_retirement(conn: sqlite3.Connection, identity: str) -> None:
    """The Coordinator calls this when processing a 'retire' directive - it
    only ever sets a flag. The target agent's own run loop (see
    agents/base.py) polls for this and exits itself; nothing forcibly kills
    the process. This *is* what "graceful retire" means concretely."""
    conn.execute("UPDATE agent_registry SET retire_requested = 1 WHERE identity = ?", (identity,))
    conn.commit()


def is_retirement_requested(conn: sqlite3.Connection, identity: str) -> bool:
    row = conn.execute("SELECT retire_requested FROM agent_registry WHERE identity = ?", (identity,)).fetchone()
    return bool(row and row["retire_requested"])


def record_heartbeat(conn: sqlite3.Connection, identity: str, metric: str = "heartbeat", value: str | None = None) -> None:
    now = _now()
    conn.execute("UPDATE agent_registry SET last_heartbeat_at = ? WHERE identity = ?", (now, identity))
    conn.execute(
        "INSERT INTO health_metrics (identity, timestamp, metric, value, schema_version) VALUES (?, ?, ?, ?, ?)",
        (identity, now, metric, value, SCHEMA_VERSION),
    )
    conn.commit()


def mark_agent_gone(conn: sqlite3.Connection, identity: str) -> None:
    conn.execute("UPDATE agent_registry SET status = 'gone' WHERE identity = ?", (identity,))
    conn.commit()


def mark_agent_crashed(conn: sqlite3.Connection, identity: str) -> None:
    """Distinct from mark_agent_gone: 'gone' means the agent's own run loop
    exited cleanly and marked itself on its way out (agents/base.py's
    finally block). 'crashed' means agents/coo.py's health evaluation
    detected a heartbeat that stopped moving without that clean exit ever
    happening - addendum_10 Phase B's restart-vs-crash distinction (Gap 3
    in the project brief)."""
    conn.execute("UPDATE agent_registry SET status = 'crashed' WHERE identity = ?", (identity,))
    conn.commit()


def list_stale_active_agents(conn: sqlite3.Connection, stale_seconds: float) -> list[dict]:
    """'active' agents whose most recent signal of life (last heartbeat, or
    spawn time if it never got as far as a first heartbeat) is older than
    stale_seconds - candidates for agents/coo.py's _evaluate_agent_health to
    mark as crashed. An agent that exits cleanly calls mark_agent_gone
    itself; one that's killed outright (SIGKILL, OOM, host crash) never
    reaches that code at all, so its row would stay 'active' forever with a
    heartbeat that's stopped advancing unless something else notices - this
    is that something else."""
    rows = conn.execute("SELECT * FROM agent_registry WHERE status = 'active'").fetchall()
    now = datetime.now(timezone.utc)
    stale = []
    for row in rows:
        reference = row["last_heartbeat_at"] or row["spawned_at"]
        if (now - parse_timestamp(reference)).total_seconds() >= stale_seconds:
            stale.append(dict(row))
    return stale


def get_agent(conn: sqlite3.Connection, identity: str) -> dict | None:
    row = conn.execute("SELECT * FROM agent_registry WHERE identity = ?", (identity,)).fetchone()
    return dict(row) if row else None


def list_agents(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM agent_registry ORDER BY spawned_at").fetchall()
    return [dict(r) for r in rows]


# --- COO -> Coordinator directive queue ---


def enqueue_directive(
    conn: sqlite3.Connection,
    directive_type: str,
    requested_by: str,
    target_role: str | None = None,
    target_identity: str | None = None,
    params: dict | None = None,
    reason: str | None = None,
) -> int:
    """reason: why this directive was raised (e.g. "baseline role has zero
    active agents"), addressing addendum_10 Phase B's "record every COO
    decision with reason... so operational decisions can also be graded" -
    see Gap 2 in the project brief. The other half of that requirement (the
    "later observed result") is recorded after the fact via
    record_observed_result, once list_directives_needing_observation says
    enough time has passed to check what actually happened."""
    cursor = conn.execute(
        "INSERT INTO coo_directives (timestamp, directive_type, target_role, target_identity, params, requested_by, reason, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (_now(), directive_type, target_role, target_identity, json.dumps(params or {}), requested_by, reason, SCHEMA_VERSION),
    )
    conn.commit()
    return cursor.lastrowid


def fetch_next_pending_directive(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT * FROM coo_directives WHERE status = 'pending' ORDER BY timestamp ASC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def has_pending_spawn_directive(conn: sqlite3.Connection, role: str) -> bool:
    """True if a spawn directive for this role is sitting in the pending
    queue, not yet picked up by the Coordinator. Found via manual
    verification of Gap 3 (project brief): agents/coo.py's
    _role_spawn_in_flight only ever checked coo_directives_completed, which
    is blind to a directive that's still pending - COO's ~1s cycle and the
    Coordinator's ~1s poll (backend/main.py) are the same order of
    magnitude, so it's routine, not rare, for COO's next cycle to run
    before the previous cycle's spawn directive has even been picked up,
    let alone completed. Without this check, that cycle sees no completed
    directive to call "in flight" and enqueues a second, genuinely
    duplicate spawn for the same role."""
    row = conn.execute(
        "SELECT 1 FROM coo_directives WHERE directive_type = 'spawn' AND target_role = ? AND status = 'pending' LIMIT 1",
        (role,),
    ).fetchone()
    return row is not None


def complete_directive(conn: sqlite3.Connection, directive_id: int, outcome: str, detail: str | None = None) -> None:
    conn.execute(
        "UPDATE coo_directives SET status = ?, detail = ? WHERE id = ?",
        (outcome, detail, directive_id),
    )
    conn.commit()


def list_completed_directives(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM coo_directives_completed ORDER BY completed_at").fetchall()
    return [dict(r) for r in rows]


def most_recent_completed_spawn(conn: sqlite3.Connection, role: str) -> dict | None:
    """The latest completed spawn directive for a role, or None if it's
    never had one. Agent identity is now a permanent role-slot (addendum_5
    §4 - see backend/coordinator.py's _slot_identity), so every spawn
    directive for a role names the *same* target identity across the
    role's whole history - this is what lets agents/coo.py's
    _role_spawn_in_flight ask "did the most recent spawn attempt
    specifically register yet", not just "does this identity exist".

    Orders by id, not completed_at: id is the original coo_directives
    AUTOINCREMENT id, carried through by the archive trigger, so it's a
    precision-independent, strictly-increasing "most recent" signal.
    completed_at is SQL-trigger-written at millisecond precision (SQLite's
    strftime has no finer fractional-second format) and can tie between two
    directives that complete faster than that - not a real risk against the
    Coordinator's own ~1s poll loop, but a real one in tests exercising this
    logic without a real subprocess in between."""
    row = conn.execute(
        "SELECT * FROM coo_directives_completed WHERE directive_type = 'spawn' AND target_role = ? "
        "ORDER BY id DESC LIMIT 1",
        (role,),
    ).fetchone()
    return dict(row) if row else None


def list_directives_needing_observation(conn: sqlite3.Connection, grace_seconds: float = 5.0) -> list[dict]:
    """Completed spawn directives whose outcome only proves the Coordinator's
    subprocess.Popen call didn't raise (see coordinator.py's _handle_spawn) -
    not that the decision panned out. Once grace_seconds has elapsed since
    completion (long enough for a real agent to have registered and sent at
    least one heartbeat), these are ready for agents/coo.py's
    _evaluate_past_decisions to check against the actual registry state.
    Filtering by elapsed time happens here in Python rather than in the SQL
    WHERE clause because completed_at is written by the archive trigger
    using SQLite's own strftime (a differently-formatted timestamp than this
    module's _now()) - see parse_timestamp."""
    rows = conn.execute(
        "SELECT * FROM coo_directives_completed "
        "WHERE directive_type = 'spawn' AND outcome = 'success' AND observed_result IS NULL "
        "ORDER BY completed_at"
    ).fetchall()
    now = datetime.now(timezone.utc)
    ready = []
    for row in rows:
        if (now - parse_timestamp(row["completed_at"])).total_seconds() >= grace_seconds:
            ready.append(dict(row))
    return ready


def record_observed_result(conn: sqlite3.Connection, directive_id: int, observed_result: str) -> None:
    """The "later observed result" half of addendum_10 Phase B's decision-
    grading requirement (Gap 2's other half - reason-capture already shipped
    in enqueue_directive). Written once, after the fact, by agents/coo.py's
    _evaluate_past_decisions."""
    conn.execute(
        "UPDATE coo_directives_completed SET observed_result = ?, observed_at = ? WHERE id = ?",
        (observed_result, _now(), directive_id),
    )
    conn.commit()


# --- Performance card (objective fields only - see plan for the deferred recognition/commendation split) ---


def get_performance_card(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM performance_card ORDER BY identity").fetchall()
    return [dict(r) for r in rows]
