"""Financial Intelligence system's coordination substrate: a SQLite-backed
(WAL mode) database, accessed only through backend/db.py's Database
abstraction - see docs/addenda/addendum_6 §1-3 and the confirmed decision
in [[project_my_ai_financial_intelligence]] that no agent ever calls another
agent directly. Every coordination act (COO directives, agent registration,
health) is a row in one of these tables.

Data-access abstraction (Pre-Alpha requirement, 2026-08-15): this module is
the *only* place that knows the FI schema and writes SQL, but it no longer
touches sqlite3 directly - every read/write goes through backend/db.py's
Database class, which hides row-factory/lastrowid/PRAGMA details. Nothing
outside this module has ever needed to change as a result (confirmed:
agents/base.py and every real agent module only ever pass the connection
object through opaquely to this module's functions) - this rewrite is a
pure internal-implementation change, not a public API change.

Table design follows the queue-vs-log principle worked out this session:
a table gets the pending->completed split only if something needs to ask
"is there unprocessed work here?" (coo_directives). Pure facts with no
consumer that "completes" them are single append/update tables
(agent_registry, health_metrics).

The pending->completed move for directives is enforced by a SQL trigger,
not application code doing a manual delete+insert - the DB itself
guarantees the invariant, per the plan's explicit intent, rather than
depending on every call site remembering to do both steps correctly.
Deliberately left as a trigger even after the Pre-Alpha persistence
abstraction (2026-08-15): it's invisible to every caller outside this
module (nothing else issues a raw UPDATE against these tables), so it
doesn't violate "agents must not depend on SQLite-specific behavior" -
reimplementing it in application code is real work with a cost, better
scoped to whenever an actual PostgreSQL migration is undertaken.

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
import os
from datetime import datetime, timezone
from pathlib import Path

from backend.db import Database

# FI_DB_PATH is honoured here, not only in agents/base.py. backend/controller.py
# already *sets* this variable for every child process it spawns, so without
# this the Controller would read one database while claiming to have pointed its
# agents at another - an externally-set FI_DB_PATH was silently discarded by the
# one process that owns the registry.
DB_PATH = Path(os.environ.get("FI_DB_PATH") or (Path(__file__).resolve().parent.parent / "financial_intelligence.db"))

# Bump only when the *meaning* of newly-written rows changes in a way a
# future reader/grader needs to distinguish from older rows - not on every
# column addition (see the additive-only-columns rule above).
#
# v2 (2026-08-16): agent_registry split organizational lifecycle from process
# liveness (lifecycle_state + process_state). `status` still exists and is
# still written, but is now a *derived* legacy value rather than the primary
# fact - a grader reading old rows needs to know which model produced them.
# v3 (2026-08-16): detections and reports now reference the intelligence
# artifact (lens) that produced them. A v2 detector_event records only the
# threshold *value* used; a v3 one records *which lens* it came from, so its
# grades can be attributed back to that lens.
# v4 (2026-08-16): market conditions are characterized (market_regime), and a
# lens can be bound to the regime it was observed working under - so a lens
# can now expire because *conditions changed*, not only because its grades
# were poor.
SCHEMA_VERSION = 4

# --- Pre-Alpha static metadata (Consolidated spec §10/§21) ---
# These are organization-level constants, deliberately kept here rather than
# in agents/discovery_config.py: this module has to read them to seed the
# tables below, and backend/ importing from agents/ would invert the
# dependency direction (agents depend on backend, never the reverse).

# "The CEO display name is a configurable reserved-name setting whose
# initial/default value is Bob. Bob must not be hard-coded throughout
# application logic." This one setting, plus the reserved row it seeds, is
# the entirety of that requirement - the literal string appears nowhere else.
CEO_DISPLAY_NAME = os.environ.get("FI_CEO_DISPLAY_NAME", "Bob")

# "Create a diverse global Agent Name Repository." Deliberately spans many
# languages/regions rather than one culture's name list. Names are a display
# layer over the permanent role-slot identity (explorer-1, ...), which stays
# the immutable internal identifier everything else joins on - §10 asks for
# both ("every active agent *also* has an immutable internal identifier").
AGENT_NAME_POOL = (
    "Amara", "Aiko", "Anand", "Ana", "Bilal", "Chen", "Dmitri", "Elena",
    "Ewa", "Fatima", "Gabriel", "Hana", "Hugo", "Ibrahim", "Ines", "Jamal",
    "Jin", "Kavya", "Kwame", "Lars", "Leila", "Mateo", "Mei", "Nadia",
    "Niko", "Oluwaseun", "Omar", "Priya", "Qing", "Rafael", "Ravi", "Rosa",
    "Sanjay", "Sofia", "Tariq", "Thandiwe", "Yuki", "Yusuf", "Zara", "Zheng",
)

# "Create a configurable, expandable, versioned Security Universe of assets
# the organization may monitor." Inclusion means an asset MAY be monitored -
# it implies nothing about whether it is attractive or investable.
SECURITY_UNIVERSE_VERSION = 1
SECURITY_UNIVERSE_SEED = [
    s.strip() for s in os.environ.get("FI_SECURITY_UNIVERSE", "SYN1,SYN2,SYN3,SYN4").split(",") if s.strip()
]

# --- Intelligence artifacts (JARVIS Constitution §3, gap analysis §4.11) ---
# "Intelligence is about defining how to look at things, using pattern
# recognition as the key guiding principle to differentiate things"
# (owner, 2026-08-16). A detection threshold is therefore not configuration -
# it IS the system's intelligence, and it needs the properties intelligence
# has: provenance, a rationale, validity conditions, and the ability to go
# stale when the market conditions it was derived for change.
#
# These names are the lookup keys for the seeded lenses. The seed *values*
# live in agents/discovery_config.py, which is where they have always been;
# after seeding, agents read the artifact rather than the constant, so the
# config is the starting point rather than the runtime source of truth.
LENS_KIND = "detection_lens"
LENS_IV_RATIO_NAME = "iv_ratio_threshold"
LENS_SPECULATOR_CONFIDENCE_NAME = "speculator_confidence_threshold"

# Seed values. These live here rather than in agents/discovery_config.py for
# the same reason CEO_DISPLAY_NAME and SECURITY_UNIVERSE_SEED do: this module
# must read them to seed the table, and backend/ importing from agents/ would
# invert the dependency direction. They are *seeds* - once seeded, agents read
# the artifact, so changing the env var only affects a fresh database.
LENS_IV_RATIO_SEED = float(os.environ.get("FI_IV_RATIO_THRESHOLD", "2.0"))
LENS_SPECULATOR_CONFIDENCE_SEED = float(os.environ.get("FI_SPECULATOR_CONFIDENCE_THRESHOLD", "0.6"))

# Default validity conditions attached to a seeded lens - the performance half
# of "intelligence expires", evaluated by agents/coo.py's
# _evaluate_intelligence_health.
DEFAULT_LENS_VALIDITY_CONDITIONS = {
    "min_graded_reports": 10,
    "min_mean_overall_score": 0.35,
    "min_worth_the_compute_rate": 0.4,
}

# The conditions half, added only to lenses that look at the *market* - see
# MARKET_LENS_VALIDITY_CONDITIONS below for why that qualifier matters.
#
# observed_under is null until earned: a seeded lens came from the
# specification, so the regime it was *derived* under is genuinely unknown and
# claiming one would be a fabrication. Instead COO binds the lens to the regime
# it has been observed *performing acceptably* under, and divergence from that
# is what invalidates it. Drift tolerances are sized against the synthetic
# surface (base 0.25, noise +/-0.01, term structure spreading ~0.03) so ordinary
# jitter cannot trip them but a genuine level or noise shift does.
DEFAULT_MARKET_REGIME_CONDITIONS = {
    "observed_under": None,
    "bound_at": None,
    "max_mean_iv_drift": 0.08,
    "max_dispersion_drift": 0.02,
    "min_observations": 30,
}

MARKET_LENS_VALIDITY_CONDITIONS = {
    **DEFAULT_LENS_VALIDITY_CONDITIONS,
    "regime": DEFAULT_MARKET_REGIME_CONDITIONS,
}

# EWMA weight for each new regime observation. 0.05 means the estimate follows
# a sustained shift over a few dozen observations rather than jumping on one
# surface - regime is a persistent condition, not a tick.
REGIME_EWMA_ALPHA = float(os.environ.get("FI_REGIME_EWMA_ALPHA", "0.05"))

SCHEMA = """
-- lifecycle_state and process_state are deliberately two ORTHOGONAL axes
-- (owner decision, 2026-08-16). lifecycle_state is the agent's standing in
-- the organization; process_state is only whether an OS process is currently
-- alive for it. Conflating them (as the single legacy `status` column did)
-- made retirement indistinguishable from an ordinary exit, and made dormancy
-- impossible to express at all: a retired agent looked exactly like a dead
-- one, so COO would immediately respawn it.
--
--   lifecycle_state: 'active'  - in service, a process is expected to run
--                    'dormant' - retired/suspended. Non-destructive and
--                                reversible; the row, identity, name, and
--                                full history are preserved. No process is
--                                expected, and COO must not respawn it.
--   process_state:   'running' - a live process is heartbeating
--                    'stopped' - no process; it exited on its own terms
--                    'crashed' - no process; it died without a clean exit
--
-- `status` is retained (never removed - additive-only rule) but is now a
-- DERIVED legacy value, computed by _derive_status from the two axes above.
-- Never make a decision from it; read the two axes instead.
CREATE TABLE IF NOT EXISTS agent_registry (
    identity TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    pid INTEGER,
    status TEXT NOT NULL DEFAULT 'active',
    retire_requested INTEGER NOT NULL DEFAULT 0,
    spawned_at TEXT NOT NULL,
    last_heartbeat_at TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1,
    lifecycle_state TEXT NOT NULL DEFAULT 'active',
    process_state TEXT NOT NULL DEFAULT 'running'
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
    -- which intelligence artifact produced this detection. `threshold` above
    -- records the value that was used; this records which lens it came from,
    -- so grades on the resulting report can be attributed back to the lens.
    lens_artifact_id INTEGER,
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

-- Explorer<->Speculator cross-check contracts (addendum 12 §14, a Pre-Alpha
-- task in §21). One row per question asked and, once answered, the answer.
--
-- Polled like everything else - the requester files a question and carries on
-- with its own loop; the responder picks it up on its own cycle; the requester
-- collects the answer on a later cycle. Nobody blocks. A synchronous call
-- between two independent agent processes would be a new IPC channel, and
-- SQLite is deliberately the only one.
--
-- The requester's own finding is recorded in requester_finding *before* the
-- question is asked, because §14 says "investigate independently first, then
-- cross-check." If the request went out first the two views would no longer be
-- independent, and the pair would be one reference frame counted twice rather
-- than two (addendum 15 §4-5).
CREATE TABLE IF NOT EXISTS cross_check_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    requester_identity TEXT NOT NULL,
    requester_spawned_at TEXT NOT NULL,
    requester_role TEXT NOT NULL,
    responder_role TEXT NOT NULL,
    security TEXT NOT NULL,
    -- The specific question being answered (§14, literal requirement) rather
    -- than a bare "look at this" - so an answer can be read against what was
    -- actually asked.
    question TEXT NOT NULL,
    -- The requester's independent finding, as JSON, captured before asking.
    requester_finding TEXT NOT NULL,
    requester_confidence REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    -- 'answered' | 'no_evidence' | 'unanswered'. Deliberately NOT
    -- 'corroborated'/'contradicted': whether two findings agree is a reasoning
    -- judgment, and Explorer and Speculator are procedural. Analysis reads both
    -- findings and concludes. See agents/analysis.py.
    outcome TEXT,
    responder_identity TEXT,
    responder_spawned_at TEXT,
    responder_finding TEXT,
    responder_confidence REAL,
    answered_at TEXT,
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
    -- The lens that produced this report. Carried here, not only on
    -- detector_events, because Speculator reports have no detector event -
    -- putting it on the report makes attribution from grades a single join
    -- for both agents rather than two different paths.
    lens_artifact_id INTEGER,
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
    lens_artifact_id INTEGER,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE TRIGGER IF NOT EXISTS discovery_reports_archive
AFTER UPDATE OF status ON discovery_reports
WHEN NEW.status IN ('analyzed', 'failed')
BEGIN
    INSERT INTO discovery_reports_completed
        (id, created_at, producer_identity, producer_spawned_at, report_type, security, summary,
         detector_event_id, evidence_ids, judgment_confidence, handled_by_identity, handled_by_spawned_at,
         detail, completed_at, outcome, lens_artifact_id, schema_version)
    VALUES
        (NEW.id, NEW.created_at, NEW.producer_identity, NEW.producer_spawned_at, NEW.report_type, NEW.security, NEW.summary,
         NEW.detector_event_id, NEW.evidence_ids, NEW.judgment_confidence, NEW.handled_by_identity, NEW.handled_by_spawned_at,
         NEW.detail, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), NEW.status, NEW.lens_artifact_id, NEW.schema_version);
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

-- Pre-Alpha static metadata (Consolidated spec §10/§21).

CREATE TABLE IF NOT EXISTS agent_names (
    name TEXT PRIMARY KEY,
    assigned_to_identity TEXT UNIQUE,
    assigned_at TEXT,
    reserved INTEGER NOT NULL DEFAULT 0,
    schema_version INTEGER NOT NULL DEFAULT 1
);

-- The seed of the knowledge store (JARVIS Constitution §3). Holds
-- *intelligence* - ways of seeing - rather than data or observations. The
-- distinction is load-bearing: an IV surface is data, a detected anomaly is
-- an observation, but the threshold and neighborhood that decide what counts
-- as an anomaly at all are the intelligence, and only intelligence has a
-- preservation claim.
--
-- artifact_kind is deliberately general so this table can grow into the
-- knowledge store: source reliability and validated lessons become other
-- kinds without a schema change. 'detection_lens' is the only kind built.
--
-- Lifecycle mirrors the agent one for the same reason - intelligence, like
-- an agent, is retired rather than destroyed:
--   'active'     - in use
--   'stale'      - evidence says it no longer holds; still readable, and its
--                  value is NOT changed automatically (see coo.py)
--   'superseded' - replaced by another artifact, linked via superseded_by
CREATE TABLE IF NOT EXISTS intelligence_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    name TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    value TEXT NOT NULL,
    rationale TEXT,
    validity_conditions TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    staleness_reason TEXT,
    stale_at TEXT,
    superseded_by INTEGER,
    producer_identity TEXT,
    producer_spawned_at TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1,
    UNIQUE(name, version)
);

-- The system's *estimate* of current market conditions, inferred from the
-- surfaces Explorer observes. Deliberately a current-state table (one row per
-- security, revised in place) rather than a log: an observation per security
-- per cycle would be several rows a second of pure data, and "data retention
-- is not imperative" - only the extracted characterization is intelligence.
-- An EWMA gives that with no history and no growth.
--
-- Kept out of intelligence_artifacts despite being intelligence, because the
-- update semantics are the opposite: artifacts are immutable and superseded,
-- a live estimate is continuously revised.
CREATE TABLE IF NOT EXISTS market_regime (
    security TEXT PRIMARY KEY,
    mean_iv REAL NOT NULL,
    iv_dispersion REAL NOT NULL,
    observation_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS security_universe (
    symbol TEXT PRIMARY KEY,
    added_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    note TEXT,
    universe_version INTEGER NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE VIEW IF NOT EXISTS performance_card AS
SELECT
    r.identity,
    r.role,
    r.status,
    r.lifecycle_state,
    r.process_state,
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


def get_connection(db_path: str | Path = DB_PATH) -> Database:
    return Database(db_path)


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)
    _seed_static_metadata(conn)


def _seed_static_metadata(conn: Database) -> None:
    """Idempotent seeding of the Pre-Alpha static metadata tables - safe to
    re-run on every startup (init_schema is called by every agent process,
    not just the server). Uses INSERT OR IGNORE so existing rows, including
    already-assigned names and any securities added at runtime, are never
    disturbed."""
    for name in AGENT_NAME_POOL:
        conn.execute(
            "INSERT OR IGNORE INTO agent_names (name, reserved, schema_version) VALUES (?, 0, ?)",
            (name, SCHEMA_VERSION),
        )
    # The CEO name is seeded reserved, and re-asserted as reserved on every
    # startup in case FI_CEO_DISPLAY_NAME changed to a name already in the
    # ordinary pool - reserving it late is still correct, it just means the
    # name stops being handed out from that point on.
    conn.execute(
        "INSERT INTO agent_names (name, reserved, schema_version) VALUES (?, 1, ?) "
        "ON CONFLICT(name) DO UPDATE SET reserved = 1",
        (CEO_DISPLAY_NAME, SCHEMA_VERSION),
    )
    for symbol in SECURITY_UNIVERSE_SEED:
        conn.execute(
            "INSERT OR IGNORE INTO security_universe (symbol, added_at, active, note, universe_version, schema_version) "
            "VALUES (?, ?, 1, ?, ?, ?)",
            (symbol, _now(), "seeded synthetic universe", SECURITY_UNIVERSE_VERSION, SCHEMA_VERSION),
        )
    # The starting lenses. INSERT OR IGNORE on UNIQUE(name, version) makes this
    # idempotent *and* non-destructive: once a lens exists - including one that
    # has since been marked stale or had its value revised - re-seeding can
    # never overwrite it or resurrect a superseded value.
    #
    # Only the IV lens carries regime conditions. The speculator's bar looks at
    # *social* confidence, and nothing in the system characterizes a social
    # regime - attaching market conditions to it would make market volatility
    # invalidate a social lens, which is not a claim the evidence supports.
    # Characterizing a social regime is future work; until then this lens
    # legitimately expires on performance alone.
    for name, seed_value, conditions, rationale in (
        (
            LENS_IV_RATIO_NAME,
            LENS_IV_RATIO_SEED,
            MARKET_LENS_VALIDITY_CONDITIONS,
            "Initial peak-IV / local-baseline-IV ratio from addendum_7 §4, which specifies >= 2.0 as "
            "the initial strong trigger and states the threshold is configurable. Asserted by the "
            "specification, not yet derived from or validated against evidence.",
        ),
        (
            LENS_SPECULATOR_CONFIDENCE_NAME,
            LENS_SPECULATOR_CONFIDENCE_SEED,
            DEFAULT_LENS_VALIDITY_CONDITIONS,
            "Initial aggregate-confidence bar for filing social evidence. Chosen as a starting point "
            "during the Phase C build; not derived from evidence.",
        ),
    ):
        conn.execute(
            "INSERT OR IGNORE INTO intelligence_artifacts "
            "(created_at, artifact_kind, name, version, value, rationale, validity_conditions, status, schema_version) "
            "VALUES (?, ?, ?, 1, ?, ?, ?, 'active', ?)",
            (
                _now(), LENS_KIND, name, json.dumps(seed_value), rationale,
                json.dumps(conditions), SCHEMA_VERSION,
            ),
        )


# --- Agent registry ---

LIFECYCLE_ACTIVE = "active"
LIFECYCLE_DORMANT = "dormant"

PROCESS_RUNNING = "running"
PROCESS_STOPPED = "stopped"
PROCESS_CRASHED = "crashed"


def _derive_status(lifecycle_state: str, process_state: str) -> str:
    """The legacy single-axis `status` value, derived from the two real axes.

    Kept only so historical rows and the pre-2026-08-16 vocabulary stay
    coherent (the additive-only-columns rule means the column can never be
    removed). Nothing should make a decision from it - read lifecycle_state
    and process_state instead. Computed in exactly one place so the derived
    column can never drift out of sync with the facts it's derived from."""
    if lifecycle_state == LIFECYCLE_DORMANT:
        return "dormant"
    if process_state == PROCESS_RUNNING:
        return "active"
    if process_state == PROCESS_CRASHED:
        return "crashed"
    return "gone"


def register_agent(conn: Database, identity: str, role: str, pid: int) -> None:
    """identity is a permanent role-slot ID (addendum_5 §4: durable
    performance record independent of any one process instance - see
    backend/controller.py's _slot_identity), so this INSERT...ON CONFLICT
    path is the normal case for a respawn, not an edge case: the same
    identity comes back to life under a new pid. last_heartbeat_at is
    explicitly reset to NULL on that path - without it, a respawned agent
    would inherit its *previous* life's last heartbeat, which could already
    be well past agents/coo.py's staleness threshold and get the freshly-
    registered agent marked 'crashed' before it ever got a chance.

    Deliberately does NOT touch lifecycle_state on the ON CONFLICT path.
    Registration is a statement about *process* liveness ("a process for this
    identity is now running"), not about organizational standing. Only the
    Controller changes lifecycle_state (retire_agent/resume_agent), so a
    dormant agent whose process somehow starts can never silently
    un-retire itself. A brand-new agent gets 'active' from the column default
    on INSERT."""
    now = _now()
    conn.execute(
        "INSERT INTO agent_registry (identity, role, pid, status, retire_requested, spawned_at, last_heartbeat_at, schema_version, lifecycle_state, process_state) "
        "VALUES (?, ?, ?, ?, 0, ?, NULL, ?, ?, ?) "
        "ON CONFLICT(identity) DO UPDATE SET pid=excluded.pid, retire_requested=0, spawned_at=excluded.spawned_at, "
        "last_heartbeat_at=NULL, schema_version=excluded.schema_version, process_state=excluded.process_state, "
        "status=CASE WHEN agent_registry.lifecycle_state = ? THEN ? ELSE ? END",
        (
            identity, role, pid, _derive_status(LIFECYCLE_ACTIVE, PROCESS_RUNNING), now, SCHEMA_VERSION,
            LIFECYCLE_ACTIVE, PROCESS_RUNNING,
            LIFECYCLE_DORMANT,
            _derive_status(LIFECYCLE_DORMANT, PROCESS_RUNNING),
            _derive_status(LIFECYCLE_ACTIVE, PROCESS_RUNNING),
        ),
    )
    # Every agent gets a name from the repository on first registration and
    # keeps it for life - assign_agent_name is idempotent, so a respawn under
    # the same permanent identity returns the existing name rather than
    # burning a second one. Deliberately best-effort: a name is a display
    # concern, and an exhausted pool must never be able to stop an agent from
    # registering (see assign_agent_name).
    assign_agent_name(conn, identity)


def request_retirement(conn: Database, identity: str) -> None:
    """Retire an agent: move it to dormant and ask its process to wind down.

    Retirement is **non-destructive and reversible** (addendum 11 §9,
    addendum 12 §4). The row is never deleted - identity, name, performance
    history, grades, and every record the agent produced are preserved
    exactly as they were. Only two things change: lifecycle_state becomes
    'dormant', and retire_requested asks the running process to stop.

    Both are set here, by the Controller, because organizational standing is
    the Controller's call alone (addendum 11 §15). The agent itself only ever
    reports its own process_state; it never decides whether it is in service.

    The trigger stays a flag the agent polls: agents/base.py checks it *after*
    finishing the current work cycle, so the agent always completes what it
    was doing and exits on its own terms. Nothing forcibly kills it.

    resume_agent is the exact inverse."""
    conn.execute(
        "UPDATE agent_registry SET retire_requested = 1, lifecycle_state = ?, status = ? WHERE identity = ?",
        (LIFECYCLE_DORMANT, _derive_status(LIFECYCLE_DORMANT, PROCESS_STOPPED), identity),
    )


def resume_agent(conn: Database, identity: str) -> None:
    """Bring a dormant agent back into service - the 'resume' half of
    addendum 11 §9's "retirement is always reversible."

    Restores organizational standing only. It does not start a process:
    once lifecycle_state is 'active' again with no process running, COO's
    normal baseline check sees an understaffed role and requests a spawn
    through the Controller, exactly as it would for any other missing agent.
    The agent comes back under the *same* permanent identity, with the same
    name and its entire history intact - which is what makes dormancy
    genuinely non-destructive rather than a deletion with extra steps."""
    conn.execute(
        "UPDATE agent_registry SET retire_requested = 0, lifecycle_state = ?, status = ? WHERE identity = ?",
        (LIFECYCLE_ACTIVE, _derive_status(LIFECYCLE_ACTIVE, PROCESS_STOPPED), identity),
    )


def is_retirement_requested(conn: Database, identity: str) -> bool:
    row = conn.fetchone("SELECT retire_requested FROM agent_registry WHERE identity = ?", (identity,))
    return bool(row and row["retire_requested"])


def record_heartbeat(conn: Database, identity: str, metric: str = "heartbeat", value: str | None = None) -> None:
    now = _now()
    conn.execute("UPDATE agent_registry SET last_heartbeat_at = ? WHERE identity = ?", (now, identity))
    conn.execute(
        "INSERT INTO health_metrics (identity, timestamp, metric, value, schema_version) VALUES (?, ?, ?, ?, ?)",
        (identity, now, metric, value, SCHEMA_VERSION),
    )


def mark_process_stopped(conn: Database, identity: str) -> None:
    """The agent's own run loop calls this on its way out (agents/base.py's
    finally block) - it reports only that this identity's process is no
    longer running.

    Deliberately leaves lifecycle_state untouched. A process stopping says
    nothing about whether the agent is still in service: an 'active' agent
    whose process stopped is an understaffed role COO should refill, while a
    'dormant' agent whose process stopped is simply retirement completing.
    Same event, opposite correct responses - which is exactly why the two
    axes are separate."""
    conn.execute(
        "UPDATE agent_registry SET process_state = ?, "
        "status = CASE WHEN lifecycle_state = ? THEN ? ELSE ? END WHERE identity = ?",
        (
            PROCESS_STOPPED,
            LIFECYCLE_DORMANT,
            _derive_status(LIFECYCLE_DORMANT, PROCESS_STOPPED),
            _derive_status(LIFECYCLE_ACTIVE, PROCESS_STOPPED),
            identity,
        ),
    )


def mark_process_crashed(conn: Database, identity: str) -> None:
    """Distinct from mark_process_stopped: 'stopped' means the agent's own
    run loop exited cleanly and reported it (agents/base.py's finally block).
    'crashed' means agents/coo.py's health evaluation observed a heartbeat
    that stopped moving without that clean exit ever happening - addendum_10
    Phase B's restart-vs-crash distinction (Gap 3 in the project brief).

    Like mark_process_stopped, this records an observation about process
    liveness only. COO observing a dead process does not retire the agent -
    that would be COO taking a lifecycle decision, which belongs to the
    Controller."""
    conn.execute(
        "UPDATE agent_registry SET process_state = ?, "
        "status = CASE WHEN lifecycle_state = ? THEN ? ELSE ? END WHERE identity = ?",
        (
            PROCESS_CRASHED,
            LIFECYCLE_DORMANT,
            _derive_status(LIFECYCLE_DORMANT, PROCESS_CRASHED),
            _derive_status(LIFECYCLE_ACTIVE, PROCESS_CRASHED),
            identity,
        ),
    )


def list_stale_active_agents(conn: Database, stale_seconds: float) -> list[dict]:
    """Agents believed to be running whose most recent signal of life (last
    heartbeat, or spawn time if they never got as far as a first heartbeat)
    is older than stale_seconds - candidates for agents/coo.py's
    _evaluate_agent_health to mark as crashed. An agent that exits cleanly
    calls mark_process_stopped itself; one that's killed outright (SIGKILL,
    OOM, host crash) never reaches that code at all, so its row would claim
    'running' forever with a heartbeat that's stopped advancing unless
    something else notices - this is that something else.

    Filters on process_state = 'running' rather than lifecycle: a dormant
    agent that has already stopped is not stale, it is retired, and flagging
    it as crashed would be plainly wrong."""
    rows = conn.fetchall("SELECT * FROM agent_registry WHERE process_state = ?", (PROCESS_RUNNING,))
    now = datetime.now(timezone.utc)
    stale = []
    for row in rows:
        reference = row["last_heartbeat_at"] or row["spawned_at"]
        if (now - parse_timestamp(reference)).total_seconds() >= stale_seconds:
            stale.append(row)
    return stale


def get_agent(conn: Database, identity: str) -> dict | None:
    return conn.fetchone("SELECT * FROM agent_registry WHERE identity = ?", (identity,))


def list_agents(conn: Database) -> list[dict]:
    return conn.fetchall("SELECT * FROM agent_registry ORDER BY spawned_at")


# --- COO -> Controller directive queue ---


def enqueue_directive(
    conn: Database,
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
    return conn.execute_returning_id(
        "INSERT INTO coo_directives (timestamp, directive_type, target_role, target_identity, params, requested_by, reason, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (_now(), directive_type, target_role, target_identity, json.dumps(params or {}), requested_by, reason, SCHEMA_VERSION),
    )


def fetch_next_pending_directive(conn: Database) -> dict | None:
    return conn.fetchone(
        "SELECT * FROM coo_directives WHERE status = 'pending' ORDER BY timestamp ASC LIMIT 1"
    )


def has_pending_spawn_directive(conn: Database, role: str) -> bool:
    """True if a spawn directive for this role is sitting in the pending
    queue, not yet picked up by the Controller. Found via manual
    verification of Gap 3 (project brief): agents/coo.py's
    _role_spawn_in_flight only ever checked coo_directives_completed, which
    is blind to a directive that's still pending - COO's ~1s cycle and the
    Controller's ~1s poll (backend/main.py) are the same order of
    magnitude, so it's routine, not rare, for COO's next cycle to run
    before the previous cycle's spawn directive has even been picked up,
    let alone completed. Without this check, that cycle sees no completed
    directive to call "in flight" and enqueues a second, genuinely
    duplicate spawn for the same role."""
    row = conn.fetchone(
        "SELECT 1 FROM coo_directives WHERE directive_type = 'spawn' AND target_role = ? AND status = 'pending' LIMIT 1",
        (role,),
    )
    return row is not None


def complete_directive(conn: Database, directive_id: int, outcome: str, detail: str | None = None) -> None:
    conn.execute(
        "UPDATE coo_directives SET status = ?, detail = ? WHERE id = ?",
        (outcome, detail, directive_id),
    )


def list_completed_directives(conn: Database) -> list[dict]:
    return conn.fetchall("SELECT * FROM coo_directives_completed ORDER BY completed_at")


def most_recent_completed_spawn(conn: Database, role: str) -> dict | None:
    """The latest completed spawn directive for a role, or None if it's
    never had one. Agent identity is now a permanent role-slot (addendum_5
    §4 - see backend/controller.py's _slot_identity), so every spawn
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
    Controller's own ~1s poll loop, but a real one in tests exercising this
    logic without a real subprocess in between."""
    return conn.fetchone(
        "SELECT * FROM coo_directives_completed WHERE directive_type = 'spawn' AND target_role = ? "
        "ORDER BY id DESC LIMIT 1",
        (role,),
    )


def list_directives_needing_observation(conn: Database, grace_seconds: float = 5.0) -> list[dict]:
    """Completed spawn directives whose outcome only proves the Controller's
    subprocess.Popen call didn't raise (see controller.py's _handle_spawn) -
    not that the decision panned out. Once grace_seconds has elapsed since
    completion (long enough for a real agent to have registered and sent at
    least one heartbeat), these are ready for agents/coo.py's
    _evaluate_past_decisions to check against the actual registry state.
    Filtering by elapsed time happens here in Python rather than in the SQL
    WHERE clause because completed_at is written by the archive trigger
    using SQLite's own strftime (a differently-formatted timestamp than this
    module's _now()) - see parse_timestamp."""
    rows = conn.fetchall(
        "SELECT * FROM coo_directives_completed "
        "WHERE directive_type = 'spawn' AND outcome = 'success' AND observed_result IS NULL "
        "ORDER BY completed_at"
    )
    now = datetime.now(timezone.utc)
    ready = []
    for row in rows:
        if (now - parse_timestamp(row["completed_at"])).total_seconds() >= grace_seconds:
            ready.append(row)
    return ready


def record_observed_result(conn: Database, directive_id: int, observed_result: str) -> None:
    """The "later observed result" half of addendum_10 Phase B's decision-
    grading requirement (Gap 2's other half - reason-capture already shipped
    in enqueue_directive). Written once, after the fact, by agents/coo.py's
    _evaluate_past_decisions."""
    conn.execute(
        "UPDATE coo_directives_completed SET observed_result = ?, observed_at = ? WHERE id = ?",
        (observed_result, _now(), directive_id),
    )


# --- Performance card (objective fields only - see plan for the deferred recognition/commendation split) ---


def get_performance_card(conn: Database) -> list[dict]:
    return conn.fetchall("SELECT * FROM performance_card ORDER BY identity")


# --- Pre-Alpha static metadata: Agent Name Repository + Security Universe ---


def assign_agent_name(conn: Database, identity: str) -> str | None:
    """Claims the next available non-reserved name for this identity, or
    returns the name it already holds. Idempotent by design: identity is a
    permanent role-slot (see backend/controller.py's _slot_identity), so an
    agent respawning under the same identity must get the same name back
    rather than consuming another one - that continuity is the whole point
    of a name as a durable organizational record.

    Returns None if the pool is exhausted, and never raises: a name is a
    display concern, and running out of them must not be able to stop an
    agent from registering and doing real work."""
    existing = conn.fetchone("SELECT name FROM agent_names WHERE assigned_to_identity = ?", (identity,))
    if existing is not None:
        return existing["name"]

    available = conn.fetchone(
        "SELECT name FROM agent_names WHERE assigned_to_identity IS NULL AND reserved = 0 ORDER BY name LIMIT 1"
    )
    if available is None:
        return None

    conn.execute(
        "UPDATE agent_names SET assigned_to_identity = ?, assigned_at = ? WHERE name = ? AND assigned_to_identity IS NULL",
        (identity, _now(), available["name"]),
    )
    # Re-read rather than trusting the UPDATE: two processes registering at
    # once could race for the same row, and the WHERE ... IS NULL guard means
    # the loser silently updated nothing. Reading back returns whichever name
    # this identity actually ended up with (None if it lost and the pool has
    # since emptied).
    confirmed = conn.fetchone("SELECT name FROM agent_names WHERE assigned_to_identity = ?", (identity,))
    return confirmed["name"] if confirmed else None


def get_agent_name(conn: Database, identity: str) -> str | None:
    row = conn.fetchone("SELECT name FROM agent_names WHERE assigned_to_identity = ?", (identity,))
    return row["name"] if row else None


def list_agent_names(conn: Database, assigned_only: bool = False) -> list[dict]:
    if assigned_only:
        return conn.fetchall("SELECT * FROM agent_names WHERE assigned_to_identity IS NOT NULL ORDER BY name")
    return conn.fetchall("SELECT * FROM agent_names ORDER BY name")


def record_intelligence_artifact(
    conn: Database,
    artifact_kind: str,
    name: str,
    value,
    rationale: str | None = None,
    validity_conditions: dict | None = None,
    version: int = 1,
    producer_identity: str | None = None,
    producer_spawned_at: str | None = None,
) -> int:
    """Creates an intelligence artifact - a way of seeing, not an observation.

    value is JSON-encoded so a lens may be a scalar threshold now and a
    structured rule later without a schema change. validity_conditions states
    what would invalidate it (JARVIS Constitution §7: "a decision should state
    the assumptions and information changes that are sufficient to reopen
    it"), applied here to intelligence rather than to decisions."""
    return conn.execute_returning_id(
        "INSERT INTO intelligence_artifacts "
        "(created_at, artifact_kind, name, version, value, rationale, validity_conditions, status, "
        "producer_identity, producer_spawned_at, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)",
        (
            _now(), artifact_kind, name, version, json.dumps(value), rationale,
            json.dumps(validity_conditions) if validity_conditions is not None else None,
            producer_identity, producer_spawned_at, SCHEMA_VERSION,
        ),
    )


def get_active_artifact(conn: Database, name: str) -> dict | None:
    """The currently-in-force artifact for this name, or None if it has never
    existed or its only versions are stale/superseded.

    Returning None for a stale lens is deliberate: a lens that evidence says
    no longer holds should not silently keep being applied as though nothing
    happened. Callers decide what to do about that - agents/explorer.py falls
    back to the seed value and keeps working, because a stale lens is a
    signal for review, not a reason to stop detecting."""
    return conn.fetchone(
        "SELECT * FROM intelligence_artifacts WHERE name = ? AND status = 'active' "
        "ORDER BY version DESC LIMIT 1",
        (name,),
    )


def get_active_artifact_value(conn: Database, name: str, default=None):
    """Convenience for the common case: the decoded value of the active
    artifact, or `default` when there is no active one."""
    artifact = get_active_artifact(conn, name)
    if artifact is None:
        return default
    return json.loads(artifact["value"])


def list_intelligence_artifacts(conn: Database, artifact_kind: str | None = None, status: str | None = None) -> list[dict]:
    clauses, params = [], []
    if artifact_kind is not None:
        clauses.append("artifact_kind = ?")
        params.append(artifact_kind)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return conn.fetchall(f"SELECT * FROM intelligence_artifacts {where} ORDER BY name, version", tuple(params))


def mark_artifact_stale(conn: Database, artifact_id: int, reason: str) -> None:
    """Records that evidence says this intelligence no longer holds.

    Deliberately does **not** change the artifact's value. Addendum 13 §14:
    "production behavior changes remain gated by validation. Continuous
    learning does not mean uncontrolled self-modification." Flagging is
    evidence-gathering; replacing a lens is an explicit act via
    supersede_artifact. Nothing is deleted - the stale artifact remains
    readable with the reason it was retired."""
    conn.execute(
        "UPDATE intelligence_artifacts SET status = 'stale', staleness_reason = ?, stale_at = ? WHERE id = ?",
        (reason, _now(), artifact_id),
    )


def supersede_artifact(conn: Database, old_artifact_id: int, new_artifact_id: int) -> None:
    """Links an artifact forward to its replacement. The old row is never
    deleted - "track intellectual evolution" (Constitution §8) requires
    preserving what changed and why, which is impossible if superseded
    intelligence is thrown away."""
    conn.execute(
        "UPDATE intelligence_artifacts SET status = 'superseded', superseded_by = ? WHERE id = ?",
        (new_artifact_id, old_artifact_id),
    )


def lens_performance(conn: Database, artifact_id: int) -> dict:
    """How the reports produced by this lens have actually been graded.

    This is the join that closes a loop which was previously severed: grades
    already measured whether a report was relevant, novel, well-evidenced and
    worth the compute, and that evidence reached nothing. Attribution runs
    grades -> discovery_reports_completed -> lens_artifact_id, which works
    uniformly for Explorer and Speculator because the lens reference lives on
    the report itself (Speculator reports have no detector event).

    Returns zero counts rather than None when a lens has produced nothing
    gradeable yet - callers must distinguish "no evidence" from "bad
    evidence", and agents/coo.py refuses to judge a lens below its
    min_graded_reports threshold precisely for that reason."""
    row = conn.fetchone(
        "SELECT COUNT(*) AS graded_reports, "
        "       AVG(g.overall_score) AS mean_overall_score, "
        "       AVG(CAST(g.worth_the_compute AS REAL)) AS worth_the_compute_rate "
        "FROM grades g "
        "JOIN discovery_reports_completed r ON g.report_id = r.id "
        "WHERE r.lens_artifact_id = ?",
        (artifact_id,),
    )
    return {
        "graded_reports": row["graded_reports"] if row else 0,
        "mean_overall_score": row["mean_overall_score"] if row else None,
        "worth_the_compute_rate": row["worth_the_compute_rate"] if row else None,
    }


def update_market_regime(
    conn: Database,
    security: str,
    mean_iv: float,
    iv_dispersion: float,
    alpha: float = REGIME_EWMA_ALPHA,
) -> None:
    """Folds one observation into this security's running characterization.

    The first observation *seeds* the average rather than blending against a
    zero that was never observed - otherwise the estimate would start wrong
    and take dozens of cycles to recover, and any early divergence check would
    be measuring the seeding artifact rather than the market."""
    existing = conn.fetchone("SELECT * FROM market_regime WHERE security = ?", (security,))
    if existing is None:
        conn.execute(
            "INSERT INTO market_regime (security, mean_iv, iv_dispersion, observation_count, updated_at, schema_version) "
            "VALUES (?, ?, ?, 1, ?, ?)",
            (security, mean_iv, iv_dispersion, _now(), SCHEMA_VERSION),
        )
        return

    blended_mean = (alpha * mean_iv) + ((1 - alpha) * existing["mean_iv"])
    blended_dispersion = (alpha * iv_dispersion) + ((1 - alpha) * existing["iv_dispersion"])
    conn.execute(
        "UPDATE market_regime SET mean_iv = ?, iv_dispersion = ?, "
        "observation_count = observation_count + 1, updated_at = ? WHERE security = ?",
        (blended_mean, blended_dispersion, _now(), security),
    )


def get_market_regime(conn: Database, security: str) -> dict | None:
    return conn.fetchone("SELECT * FROM market_regime WHERE security = ?", (security,))


def list_market_regime(conn: Database) -> list[dict]:
    return conn.fetchall("SELECT * FROM market_regime ORDER BY security")


def current_market_characterization(conn: Database, securities: list[str] | None = None) -> dict:
    """The market-wide view a lens is judged against.

    Per-security rows aggregate up to this because the lens is market-wide -
    one threshold applies to every security, so it has to be evaluated against
    overall conditions rather than any single name's. observation_count is
    summed, so the thin-data guard reflects total evidence gathered."""
    rows = list_market_regime(conn)
    if securities is not None:
        rows = [r for r in rows if r["security"] in securities]
    if not rows:
        return {"mean_iv": None, "iv_dispersion": None, "observation_count": 0, "securities": 0}
    return {
        "mean_iv": sum(r["mean_iv"] for r in rows) / len(rows),
        "iv_dispersion": sum(r["iv_dispersion"] for r in rows) / len(rows),
        "observation_count": sum(r["observation_count"] for r in rows),
        "securities": len(rows),
    }


def bind_lens_to_regime(conn: Database, artifact_id: int, characterization: dict) -> None:
    """Records the conditions a lens has been observed performing acceptably
    under, so later divergence from them is meaningful.

    This is deliberately *not* "the regime it was derived under" - the seeded
    lenses came from the specification and that is genuinely unknown. What the
    system can honestly say is "it worked while conditions looked like this",
    which is the useful claim anyway: it learns the conditions its intelligence
    holds in, then notices when the market leaves them."""
    artifact = conn.fetchone("SELECT validity_conditions FROM intelligence_artifacts WHERE id = ?", (artifact_id,))
    if artifact is None:
        return
    conditions = json.loads(artifact["validity_conditions"] or "{}")
    regime = dict(conditions.get("regime") or {})
    regime["observed_under"] = {
        "mean_iv": characterization["mean_iv"],
        "iv_dispersion": characterization["iv_dispersion"],
    }
    regime["bound_at"] = _now()
    conditions["regime"] = regime
    conn.execute(
        "UPDATE intelligence_artifacts SET validity_conditions = ? WHERE id = ?",
        (json.dumps(conditions), artifact_id),
    )


# --- Explorer<->Speculator cross-checks (addendum 12 §14) ---

CROSS_CHECK_PENDING = "pending"
CROSS_CHECK_RESOLVED = "resolved"
CROSS_CHECK_CONSUMED = "consumed"

# Outcomes. 'evidence' and 'no_evidence' are both genuine answers - a responder
# that looked and found nothing has said something informative, and that is a
# different finding from disagreement. 'unanswered' means nobody ever replied.
CROSS_CHECK_EVIDENCE = "evidence"
CROSS_CHECK_NO_EVIDENCE = "no_evidence"
CROSS_CHECK_UNANSWERED = "unanswered"

# How long a request may sit unanswered before the requester stops waiting.
# Without this a dormant or crashed responder would silently stall the other
# agent's pipeline forever - the same class of defect as the pre-2026-08-16
# retirement that quietly did nothing. Generous relative to an agent cycle so
# a merely-busy responder is not written off.
CROSS_CHECK_TIMEOUT_SECONDS = float(os.environ.get("FI_CROSS_CHECK_TIMEOUT_SECONDS", "30"))


def open_cross_check(
    conn: Database,
    requester_identity: str,
    requester_spawned_at: str,
    requester_role: str,
    responder_role: str,
    security: str,
    question: str,
    requester_finding: dict,
    requester_confidence: float | None = None,
) -> int:
    """File a question for the other discovery agent.

    requester_finding is the requester's *own* conclusion, captured here rather
    than after the answer arrives. Addendum 12 §14 requires agents to
    "investigate independently first, then cross-check" - if the finding were
    recorded after seeing the response it would no longer be independent, and
    the pair would stop being two reference frames."""
    return conn.execute_returning_id(
        "INSERT INTO cross_check_requests "
        "(created_at, requester_identity, requester_spawned_at, requester_role, responder_role, "
        "security, question, requester_finding, requester_confidence, status, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            _now(), requester_identity, requester_spawned_at, requester_role, responder_role,
            security, question, json.dumps(requester_finding), requester_confidence,
            CROSS_CHECK_PENDING, SCHEMA_VERSION,
        ),
    )


def has_open_cross_check(conn: Database, requester_identity: str, security: str) -> bool:
    """True while this requester already has an unconsumed question out on this
    security - the dedup guard that stops an agent re-asking every cycle."""
    row = conn.fetchone(
        "SELECT 1 FROM cross_check_requests WHERE requester_identity = ? AND security = ? "
        "AND status != ?",
        (requester_identity, security, CROSS_CHECK_CONSUMED),
    )
    return row is not None


def fetch_next_pending_cross_check(conn: Database, responder_role: str) -> dict | None:
    """Oldest unanswered question addressed to this role. Ordered by id rather
    than created_at: timestamps can tie at millisecond resolution, which caused
    a real bug in the spawn-directive path."""
    return conn.fetchone(
        "SELECT * FROM cross_check_requests WHERE responder_role = ? AND status = ? ORDER BY id LIMIT 1",
        (responder_role, CROSS_CHECK_PENDING),
    )


def answer_cross_check(
    conn: Database,
    request_id: int,
    responder_identity: str,
    responder_spawned_at: str,
    outcome: str,
    responder_finding: dict,
    responder_confidence: float | None = None,
) -> None:
    """Record the responder's independent finding. The responder states what it
    observed; it does not declare whether that agrees with the requester. That
    judgment is Analysis's - see the `outcome` column comment in SCHEMA."""
    conn.execute(
        "UPDATE cross_check_requests SET status = ?, outcome = ?, responder_identity = ?, "
        "responder_spawned_at = ?, responder_finding = ?, responder_confidence = ?, answered_at = ? "
        "WHERE id = ? AND status = ?",
        (
            CROSS_CHECK_RESOLVED, outcome, responder_identity, responder_spawned_at,
            json.dumps(responder_finding), responder_confidence, _now(),
            request_id, CROSS_CHECK_PENDING,
        ),
    )


def expire_stale_cross_checks(conn: Database, timeout_seconds: float = CROSS_CHECK_TIMEOUT_SECONDS) -> int:
    """Resolve long-unanswered requests as 'unanswered' so the requester can
    proceed. Silence is itself recorded - a lead that went out for corroboration
    and got none is a different thing from one never sent, and Analysis should
    see which it was."""
    now = datetime.now(timezone.utc)
    expired = 0
    for row in conn.fetchall(
        "SELECT id, created_at FROM cross_check_requests WHERE status = ?", (CROSS_CHECK_PENDING,)
    ):
        # Compared in Python via parse_timestamp rather than as a SQL string
        # comparison: this module writes two timestamp shapes (see that
        # function's docstring), and lexical ordering is only correct for one.
        if (now - parse_timestamp(row["created_at"])).total_seconds() < timeout_seconds:
            continue
        conn.execute(
            "UPDATE cross_check_requests SET status = ?, outcome = ?, answered_at = ? WHERE id = ?",
            (CROSS_CHECK_RESOLVED, CROSS_CHECK_UNANSWERED, _now(), row["id"]),
        )
        expired += 1
    return expired


def fetch_resolved_cross_checks(conn: Database, requester_identity: str) -> list[dict]:
    """Answers this requester has not yet acted on."""
    return conn.fetchall(
        "SELECT * FROM cross_check_requests WHERE requester_identity = ? AND status = ? ORDER BY id",
        (requester_identity, CROSS_CHECK_RESOLVED),
    )


def consume_cross_check(conn: Database, request_id: int) -> None:
    """Mark an answer as acted upon, so it is not processed twice and the
    security becomes askable again."""
    conn.execute(
        "UPDATE cross_check_requests SET status = ? WHERE id = ?",
        (CROSS_CHECK_CONSUMED, request_id),
    )


def get_cross_check(conn: Database, request_id: int) -> dict | None:
    return conn.fetchone("SELECT * FROM cross_check_requests WHERE id = ?", (request_id,))


def add_security(conn: Database, symbol: str, note: str | None = None) -> None:
    """Expands the Security Universe (Consolidated §10: "configurable,
    expandable, versioned"). Inclusion means the asset MAY be monitored - it
    implies nothing about whether it is attractive or investable. Re-adding
    an existing symbol reactivates it rather than duplicating or erroring."""
    conn.execute(
        "INSERT INTO security_universe (symbol, added_at, active, note, universe_version, schema_version) "
        "VALUES (?, ?, 1, ?, ?, ?) "
        "ON CONFLICT(symbol) DO UPDATE SET active = 1, note = excluded.note",
        (symbol, _now(), note, SECURITY_UNIVERSE_VERSION, SCHEMA_VERSION),
    )


def deactivate_security(conn: Database, symbol: str) -> None:
    """Removes a symbol from active monitoring without deleting its row -
    matches this project's additive-only, non-destructive conventions (and
    the new docs' "retirement is dormancy, not destruction" principle)."""
    conn.execute("UPDATE security_universe SET active = 0 WHERE symbol = ?", (symbol,))


def list_security_universe(conn: Database, active_only: bool = True) -> list[dict]:
    if active_only:
        return conn.fetchall("SELECT * FROM security_universe WHERE active = 1 ORDER BY symbol")
    return conn.fetchall("SELECT * FROM security_universe ORDER BY symbol")


# --- Phase C: detector events, evidence, discovery report queue, analysis, grading ---


def record_detector_event(
    conn: Database,
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
    lens_artifact_id: int | None = None,
) -> int:
    """Only meaningful to call when ratio >= threshold (a real candidate,
    addendum_7 §4) - agents/explorer.py doesn't call this for a
    non-triggering scan; that isn't a gradeable unit of work.

    peer_group_name/peer_group_version/peer_context are the addendum_7 §5
    peer-analysis fields: which explicit, versioned peer group this scan
    ran against, and (as JSON) which other securities in that group also
    triggered this same cycle - the evidence behind scope='peer' vs
    'individual'. All None for a scan that had no peer group in play."""
    return conn.execute_returning_id(
        "INSERT INTO detector_events "
        "(created_at, producer_identity, producer_spawned_at, security, detector_type, peak_iv, baseline_iv, ratio, threshold, neighborhood_desc, surface_seed, scope, peer_group_name, peer_group_version, peer_context, lens_artifact_id, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (_now(), producer_identity, producer_spawned_at, security, detector_type, peak_iv, baseline_iv, ratio, threshold, neighborhood_desc, surface_seed, scope, peer_group_name, peer_group_version, peer_context, lens_artifact_id, SCHEMA_VERSION),
    )


def record_detector_judgment(conn: Database, detector_event_id: int, judgment_passed: bool, judgment_note: str | None = None) -> None:
    """The lightweight LLM judgment gate's verdict (addendum_7 §2 last
    bullet), recorded onto the detector_events row it evaluated - a 1:1
    relationship, no separate table needed."""
    conn.execute(
        "UPDATE detector_events SET judgment_passed = ?, judgment_note = ? WHERE id = ?",
        (int(judgment_passed), judgment_note, detector_event_id),
    )


def get_detector_event(conn: Database, detector_event_id: int) -> dict | None:
    return conn.fetchone("SELECT * FROM detector_events WHERE id = ?", (detector_event_id,))


def record_evidence_item(
    conn: Database,
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
    return conn.execute_returning_id(
        "INSERT INTO evidence_items "
        "(created_at, producer_identity, producer_spawned_at, evidence_type, security, source, observed_at, content, confidence, raw_ref, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (_now(), producer_identity, producer_spawned_at, evidence_type, security, source, observed_at, content, confidence, raw_ref, SCHEMA_VERSION),
    )


def list_evidence_items(conn: Database, ids: list[int]) -> list[dict]:
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    return conn.fetchall(f"SELECT * FROM evidence_items WHERE id IN ({placeholders})", ids)


def enqueue_report(
    conn: Database,
    producer_identity: str,
    producer_spawned_at: str,
    report_type: str,
    security: str,
    summary: str | None = None,
    detector_event_id: int | None = None,
    evidence_ids: list[int] | None = None,
    judgment_confidence: float | None = None,
    lens_artifact_id: int | None = None,
) -> int:
    """lens_artifact_id: which intelligence artifact's threshold decided this
    was worth filing. Recorded on the report itself rather than only on the
    detector event, so that grades attribute back to the lens identically for
    Explorer (which has a detector event) and Speculator (which does not)."""
    return conn.execute_returning_id(
        "INSERT INTO discovery_reports "
        "(created_at, producer_identity, producer_spawned_at, report_type, security, summary, detector_event_id, evidence_ids, judgment_confidence, lens_artifact_id, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (_now(), producer_identity, producer_spawned_at, report_type, security, summary, detector_event_id, json.dumps(evidence_ids or []), judgment_confidence, lens_artifact_id, SCHEMA_VERSION),
    )


def fetch_next_pending_report(conn: Database) -> dict | None:
    return conn.fetchone(
        "SELECT * FROM discovery_reports WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1"
    )


def has_pending_report(conn: Database, producer_identity: str, security: str) -> bool:
    """True if a report from this producer for this security is still
    sitting in the pending queue, unconsumed by Analysis. Explorer/
    Speculator check this before filing - without it, a static synthetic
    surface/stream would get re-filed as a "new" report every ~1s cycle
    even though Analysis hasn't had a chance to look at the last one yet
    (same idempotency shape as has_pending_spawn_directive)."""
    row = conn.fetchone(
        "SELECT 1 FROM discovery_reports WHERE producer_identity = ? AND security = ? LIMIT 1",
        (producer_identity, security),
    )
    return row is not None


def complete_report(
    conn: Database,
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


def list_completed_reports(conn: Database) -> list[dict]:
    return conn.fetchall("SELECT * FROM discovery_reports_completed ORDER BY completed_at")


def record_analysis_result(
    conn: Database,
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
    return conn.execute_returning_id(
        "INSERT INTO analysis_results "
        "(created_at, producer_identity, producer_spawned_at, report_id, security, thesis, evidence_summary, confidence, uncertainty, peer_classification, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (_now(), producer_identity, producer_spawned_at, report_id, security, thesis, evidence_summary, confidence, uncertainty, peer_classification, SCHEMA_VERSION),
    )


def list_recent_analysis_results(conn: Database, security: str, since_seconds: float) -> list[dict]:
    """Analysis's own recent results for this security - a recency/
    duplicate check against this security's own history, not peer analysis
    (which is cross-security and explicitly out of scope for this
    increment)."""
    rows = conn.fetchall(
        "SELECT * FROM analysis_results WHERE security = ? ORDER BY created_at DESC", (security,)
    )
    now = datetime.now(timezone.utc)
    recent = []
    for row in rows:
        if (now - parse_timestamp(row["created_at"])).total_seconds() <= since_seconds:
            recent.append(row)
    return recent


def record_grade(
    conn: Database,
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
    return conn.execute_returning_id(
        "INSERT INTO grades "
        "(created_at, grader_identity, grader_spawned_at, report_id, analysis_result_id, relevance_score, novelty_score, evidence_quality_score, worth_the_compute, overall_score, rationale, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (_now(), grader_identity, grader_spawned_at, report_id, analysis_result_id, relevance_score, novelty_score, evidence_quality_score, int(worth_the_compute), overall_score, rationale, SCHEMA_VERSION),
    )


def list_grades_for_identity(conn: Database, identity: str) -> list[dict]:
    """Grades attributable back to whichever agent produced the report
    being graded (Explorer/Speculator), not the grader (Analysis) - the
    queryable half of addendum_10 §10's grading feedback loop: "how has
    this identity's own reported work been graded over time." Joins
    through discovery_reports_completed since grades itself only carries
    report_id, not the original producer. Nothing in this increment reads
    this back to change Explorer/Speculator behavior - that consumption
    loop is Phase D (Trainer) territory; this just makes the feedback
    correctly persisted and attributable."""
    return conn.fetchall(
        "SELECT g.* FROM grades g "
        "JOIN discovery_reports_completed r ON g.report_id = r.id "
        "WHERE r.producer_identity = ? "
        "ORDER BY g.created_at",
        (identity,),
    )
