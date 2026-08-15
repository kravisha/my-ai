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

-- Phase C (Discovery Slice, addendum_10 §5 / addendum_7): the first real
-- multi-agent handoff chain in the project (detector event -> report ->
-- analysis -> grade, addendum_5 §3), so provenance is a first-class concern
-- here in a way it wasn't for Phase A/B's single-producer coo_directives -
-- producer_identity/producer_spawned_at (and handled_by_*/grader_*) use the
-- same permanent (identity, spawned_at) session-key scheme already
-- established for agent_registry.

CREATE TABLE IF NOT EXISTS detector_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    producer_identity TEXT NOT NULL,
    producer_spawned_at TEXT NOT NULL,
    security TEXT NOT NULL,
    detector_type TEXT NOT NULL,
    peak_iv REAL NOT NULL,
    baseline_iv REAL NOT NULL,
    ratio REAL NOT NULL,
    threshold REAL NOT NULL,
    neighborhood_desc TEXT,
    surface_seed TEXT,
    scope TEXT NOT NULL DEFAULT 'individual',
    peer_group_name TEXT,
    peer_group_version INTEGER,
    peer_context TEXT,
    judgment_passed INTEGER,
    judgment_note TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS evidence_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    producer_identity TEXT NOT NULL,
    producer_spawned_at TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    security TEXT NOT NULL,
    source TEXT,
    observed_at TEXT,
    content TEXT,
    confidence REAL,
    raw_ref TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS discovery_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    producer_identity TEXT NOT NULL,
    producer_spawned_at TEXT NOT NULL,
    report_type TEXT NOT NULL,
    security TEXT NOT NULL,
    summary TEXT,
    detector_event_id INTEGER,
    evidence_ids TEXT,
    judgment_confidence REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    handled_by_identity TEXT,
    handled_by_spawned_at TEXT,
    detail TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS discovery_reports_completed (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    producer_identity TEXT NOT NULL,
    producer_spawned_at TEXT NOT NULL,
    report_type TEXT NOT NULL,
    security TEXT NOT NULL,
    summary TEXT,
    detector_event_id INTEGER,
    evidence_ids TEXT,
    judgment_confidence REAL,
    handled_by_identity TEXT,
    handled_by_spawned_at TEXT,
    detail TEXT,
    completed_at TEXT NOT NULL,
    outcome TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE TRIGGER IF NOT EXISTS discovery_reports_archive
AFTER UPDATE OF status ON discovery_reports
WHEN NEW.status IN ('analyzed', 'failed')
BEGIN
    INSERT INTO discovery_reports_completed
        (id, created_at, producer_identity, producer_spawned_at, report_type, security, summary,
         detector_event_id, evidence_ids, judgment_confidence, handled_by_identity, handled_by_spawned_at,
         detail, completed_at, outcome, schema_version)
    VALUES
        (NEW.id, NEW.created_at, NEW.producer_identity, NEW.producer_spawned_at, NEW.report_type, NEW.security, NEW.summary,
         NEW.detector_event_id, NEW.evidence_ids, NEW.judgment_confidence, NEW.handled_by_identity, NEW.handled_by_spawned_at,
         NEW.detail, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), NEW.status, NEW.schema_version);
    DELETE FROM discovery_reports WHERE id = NEW.id;
END;

CREATE TABLE IF NOT EXISTS analysis_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    producer_identity TEXT NOT NULL,
    producer_spawned_at TEXT NOT NULL,
    report_id INTEGER NOT NULL,
    security TEXT NOT NULL,
    thesis TEXT,
    evidence_summary TEXT,
    confidence REAL,
    uncertainty TEXT,
    peer_classification TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS grades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    grader_identity TEXT NOT NULL,
    grader_spawned_at TEXT NOT NULL,
    report_id INTEGER NOT NULL,
    analysis_result_id INTEGER NOT NULL,
    relevance_score REAL,
    novelty_score REAL,
    evidence_quality_score REAL,
    worth_the_compute INTEGER,
    overall_score REAL,
    rationale TEXT,
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


# --- Phase C: detector events, evidence, discovery report queue, analysis, grading ---


def record_detector_event(
    conn: sqlite3.Connection,
    producer_identity: str,
    producer_spawned_at: str,
    security: str,
    detector_type: str,
    peak_iv: float,
    baseline_iv: float,
    ratio: float,
    threshold: float,
    neighborhood_desc: str | None = None,
    surface_seed: str | None = None,
    scope: str = "individual",
    peer_group_name: str | None = None,
    peer_group_version: int | None = None,
    peer_context: str | None = None,
) -> int:
    """Only meaningful to call when ratio >= threshold (a real candidate,
    addendum_7 §4) - agents/explorer.py doesn't call this for a
    non-triggering scan; that isn't a gradeable unit of work.

    peer_group_name/peer_group_version/peer_context are the addendum_7 §5
    peer-analysis fields: which explicit, versioned peer group this scan
    ran against, and (as JSON) which other securities in that group also
    triggered this same cycle - the evidence behind scope='peer' vs
    'individual'. All None for a scan that had no peer group in play."""
    cursor = conn.execute(
        "INSERT INTO detector_events "
        "(created_at, producer_identity, producer_spawned_at, security, detector_type, peak_iv, baseline_iv, ratio, threshold, neighborhood_desc, surface_seed, scope, peer_group_name, peer_group_version, peer_context, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (_now(), producer_identity, producer_spawned_at, security, detector_type, peak_iv, baseline_iv, ratio, threshold, neighborhood_desc, surface_seed, scope, peer_group_name, peer_group_version, peer_context, SCHEMA_VERSION),
    )
    conn.commit()
    return cursor.lastrowid


def record_detector_judgment(conn: sqlite3.Connection, detector_event_id: int, judgment_passed: bool, judgment_note: str | None = None) -> None:
    """The lightweight LLM judgment gate's verdict (addendum_7 §2 last
    bullet), recorded onto the detector_events row it evaluated - a 1:1
    relationship, no separate table needed."""
    conn.execute(
        "UPDATE detector_events SET judgment_passed = ?, judgment_note = ? WHERE id = ?",
        (int(judgment_passed), judgment_note, detector_event_id),
    )
    conn.commit()


def get_detector_event(conn: sqlite3.Connection, detector_event_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM detector_events WHERE id = ?", (detector_event_id,)).fetchone()
    return dict(row) if row else None


def record_evidence_item(
    conn: sqlite3.Connection,
    producer_identity: str,
    producer_spawned_at: str,
    evidence_type: str,
    security: str,
    source: str | None = None,
    observed_at: str | None = None,
    content: str | None = None,
    confidence: float | None = None,
    raw_ref: str | None = None,
) -> int:
    cursor = conn.execute(
        "INSERT INTO evidence_items "
        "(created_at, producer_identity, producer_spawned_at, evidence_type, security, source, observed_at, content, confidence, raw_ref, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (_now(), producer_identity, producer_spawned_at, evidence_type, security, source, observed_at, content, confidence, raw_ref, SCHEMA_VERSION),
    )
    conn.commit()
    return cursor.lastrowid


def list_evidence_items(conn: sqlite3.Connection, ids: list[int]) -> list[dict]:
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(f"SELECT * FROM evidence_items WHERE id IN ({placeholders})", ids).fetchall()
    return [dict(r) for r in rows]


def enqueue_report(
    conn: sqlite3.Connection,
    producer_identity: str,
    producer_spawned_at: str,
    report_type: str,
    security: str,
    summary: str | None = None,
    detector_event_id: int | None = None,
    evidence_ids: list[int] | None = None,
    judgment_confidence: float | None = None,
) -> int:
    cursor = conn.execute(
        "INSERT INTO discovery_reports "
        "(created_at, producer_identity, producer_spawned_at, report_type, security, summary, detector_event_id, evidence_ids, judgment_confidence, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (_now(), producer_identity, producer_spawned_at, report_type, security, summary, detector_event_id, json.dumps(evidence_ids or []), judgment_confidence, SCHEMA_VERSION),
    )
    conn.commit()
    return cursor.lastrowid


def fetch_next_pending_report(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT * FROM discovery_reports WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def has_pending_report(conn: sqlite3.Connection, producer_identity: str, security: str) -> bool:
    """True if a report from this producer for this security is still
    sitting in the pending queue, unconsumed by Analysis. Explorer/
    Speculator check this before filing - without it, a static synthetic
    surface/stream would get re-filed as a "new" report every ~1s cycle
    even though Analysis hasn't had a chance to look at the last one yet
    (same idempotency shape as has_pending_spawn_directive)."""
    row = conn.execute(
        "SELECT 1 FROM discovery_reports WHERE producer_identity = ? AND security = ? LIMIT 1",
        (producer_identity, security),
    ).fetchone()
    return row is not None


def complete_report(
    conn: sqlite3.Connection,
    report_id: int,
    outcome: str,
    handled_by_identity: str | None = None,
    handled_by_spawned_at: str | None = None,
    detail: str | None = None,
) -> None:
    conn.execute(
        "UPDATE discovery_reports SET status = ?, handled_by_identity = ?, handled_by_spawned_at = ?, detail = ? WHERE id = ?",
        (outcome, handled_by_identity, handled_by_spawned_at, detail, report_id),
    )
    conn.commit()


def list_completed_reports(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM discovery_reports_completed ORDER BY completed_at").fetchall()
    return [dict(r) for r in rows]


def record_analysis_result(
    conn: sqlite3.Connection,
    producer_identity: str,
    producer_spawned_at: str,
    report_id: int,
    security: str,
    thesis: str,
    evidence_summary: str,
    confidence: float,
    uncertainty: str,
    peer_classification: str | None = None,
) -> int:
    """peer_classification: addendum_7 §5's "classify the event" -
    'common_factor' | 'idiosyncratic' | 'not_applicable' (no peer context
    at all, e.g. a Speculator-sourced report) - Analysis's own reasoned
    judgment, populated from the peer_context agents/explorer.py surfaced
    into this report's context, not a mechanical copy of detector_events'
    scope column."""
    cursor = conn.execute(
        "INSERT INTO analysis_results "
        "(created_at, producer_identity, producer_spawned_at, report_id, security, thesis, evidence_summary, confidence, uncertainty, peer_classification, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (_now(), producer_identity, producer_spawned_at, report_id, security, thesis, evidence_summary, confidence, uncertainty, peer_classification, SCHEMA_VERSION),
    )
    conn.commit()
    return cursor.lastrowid


def list_recent_analysis_results(conn: sqlite3.Connection, security: str, since_seconds: float) -> list[dict]:
    """Analysis's own recent results for this security - a recency/
    duplicate check against this security's own history, not peer analysis
    (which is cross-security and explicitly out of scope for this
    increment)."""
    rows = conn.execute(
        "SELECT * FROM analysis_results WHERE security = ? ORDER BY created_at DESC", (security,)
    ).fetchall()
    now = datetime.now(timezone.utc)
    recent = []
    for row in rows:
        if (now - parse_timestamp(row["created_at"])).total_seconds() <= since_seconds:
            recent.append(dict(row))
    return recent


def record_grade(
    conn: sqlite3.Connection,
    grader_identity: str,
    grader_spawned_at: str,
    report_id: int,
    analysis_result_id: int,
    relevance_score: float,
    novelty_score: float,
    evidence_quality_score: float,
    worth_the_compute: bool,
    overall_score: float,
    rationale: str,
) -> int:
    cursor = conn.execute(
        "INSERT INTO grades "
        "(created_at, grader_identity, grader_spawned_at, report_id, analysis_result_id, relevance_score, novelty_score, evidence_quality_score, worth_the_compute, overall_score, rationale, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (_now(), grader_identity, grader_spawned_at, report_id, analysis_result_id, relevance_score, novelty_score, evidence_quality_score, int(worth_the_compute), overall_score, rationale, SCHEMA_VERSION),
    )
    conn.commit()
    return cursor.lastrowid


def list_grades_for_identity(conn: sqlite3.Connection, identity: str) -> list[dict]:
    """Grades attributable back to whichever agent produced the report
    being graded (Explorer/Speculator), not the grader (Analysis) - the
    queryable half of addendum_10 §10's grading feedback loop: "how has
    this identity's own reported work been graded over time." Joins
    through discovery_reports_completed since grades itself only carries
    report_id, not the original producer. Nothing in this increment reads
    this back to change Explorer/Speculator behavior - that consumption
    loop is Phase D (Trainer) territory; this just makes the feedback
    correctly persisted and attributable."""
    rows = conn.execute(
        "SELECT g.* FROM grades g "
        "JOIN discovery_reports_completed r ON g.report_id = r.id "
        "WHERE r.producer_identity = ? "
        "ORDER BY g.created_at",
        (identity,),
    ).fetchall()
    return [dict(r) for r in rows]
