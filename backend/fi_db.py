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
import re
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend import agent_identity, analysis_requests, appeal, client_profile, competency, compliance, coo_identity, curriculum, engineering, governed_knowledge, identifiers, iteration, migrations, missions, novelty, observations, operating_context, parliament, reference_data, register, release, risk, status_events, strategy, triage, workspace
from backend import db as db_module
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
SCHEMA_VERSION = 7

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
#
# Default widened from SYN1-4 to SYN1-10 by universe-authority reconciliation
# (tests/test_universe_authority.py): agents/discovery_config.py's
# PEER_GROUP_SECURITIES already scanned SYN1-10 across three peer groups, so
# the universe - now the authoritative list every peer group must be contained
# in - had to actually contain what was already being scanned rather than the
# other way round.
SECURITY_UNIVERSE_VERSION = 1
SECURITY_UNIVERSE_SEED = [
    s.strip() for s in os.environ.get(
        "FI_SECURITY_UNIVERSE", "SYN1,SYN2,SYN3,SYN4,SYN5,SYN6,SYN7,SYN8,SYN9,SYN10"
    ).split(",") if s.strip()
]

# US market holidays market_is_open consults through SESSION_CALENDARS/
# is_market_holiday below. (day, name) pairs, seeded under calendar='us' for
# 2025-2027. Observed dates (a holiday landing on a weekend, shifted to the
# adjacent business day) are named accordingly so the two are never confused
# when read back.
MARKET_HOLIDAYS_US = [
    ("2025-01-01", "New Year's Day"),
    ("2026-01-01", "New Year's Day"),
    ("2027-01-01", "New Year's Day"),
    ("2025-01-20", "Martin Luther King Jr. Day"),
    ("2026-01-19", "Martin Luther King Jr. Day"),
    ("2027-01-18", "Martin Luther King Jr. Day"),
    ("2025-02-17", "Presidents Day"),
    ("2026-02-16", "Presidents Day"),
    ("2027-02-15", "Presidents Day"),
    ("2025-04-18", "Good Friday"),
    ("2026-04-03", "Good Friday"),
    ("2027-03-26", "Good Friday"),
    ("2025-05-26", "Memorial Day"),
    ("2026-05-25", "Memorial Day"),
    ("2027-05-31", "Memorial Day"),
    ("2025-06-19", "Juneteenth"),
    ("2026-06-19", "Juneteenth"),
    ("2027-06-18", "Juneteenth (observed)"),
    ("2025-07-04", "Independence Day"),
    ("2026-07-03", "Independence Day (observed)"),
    ("2027-07-05", "Independence Day (observed)"),
    ("2025-09-01", "Labor Day"),
    ("2026-09-07", "Labor Day"),
    ("2027-09-06", "Labor Day"),
    ("2025-11-27", "Thanksgiving"),
    ("2026-11-26", "Thanksgiving"),
    ("2027-11-25", "Thanksgiving"),
    ("2025-12-25", "Christmas Day"),
    ("2026-12-25", "Christmas Day"),
    ("2027-12-25", "Christmas Day"),
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
# Role charters - what each role *is*, organizationally. Addendum 14 §6 requires
# every Alpha agent to answer basic questions about its identity, role,
# responsibilities, permissions, and prohibitions, and says explicitly that this
# "does not mean unrestricted introspection into hidden model internals." So
# these are organizational facts, answerable deterministically, with no model
# call and therefore nothing to fabricate.
#
# Constants rather than a table, for now. They describe roles, not agents, and
# nothing needs to edit them at runtime - a table would be structure ahead of a
# reason. They live in this module for the same reason the lens seeds do: agents
# and the backend both import fi_db, and backend/ importing agents/ would invert
# the dependency.
#
# `not_allowed` is not decoration. Every entry is a real constraint enforced
# elsewhere in the code, and stating it here is what lets an agent answer "what
# am I not allowed to do" truthfully rather than plausibly.
ROLE_CHARTERS = {
    "controller": {
        "agent_type": "infrastructure",
        "description": "The backend server process itself, registered as the first agent.",
        "responsibilities": [
            "Execute every agent lifecycle action: spawn, retire, resume",
            "Own the OS processes of all other agents",
            "Poll coo_directives and act on operational requests",
        ],
        "allowed": [
            "Create, retire, and resume agents",
            "Set lifecycle_state, the organizational standing of any agent",
        ],
        "not_allowed": [
            "Decide operational need - that is COO's judgment (addendum 11 §15)",
            "Perform discovery, analysis, or grading work",
        ],
        "competencies": ["process management", "lifecycle execution"],
        "work_mechanism": "coo_directives table, polled",
    },
    "coo": {
        "agent_type": "executive",
        "description": "Operational executive. Keeps the organization effective and staffed.",
        "responsibilities": [
            "Maintain the baseline agent population",
            "Detect crashed agents by stale heartbeat and request replacements",
            "Evaluate past decisions against their observed results",
            "Judge intelligence health: mark lenses stale on performance or regime drift",
        ],
        "allowed": [
            "Request spawn, retire, and resume actions from the Controller",
            "Mark an intelligence artifact stale, with evidence",
            # Owner decision, 2026-08-17. Several specifications say the CEO
            # spawns a role at startup, and the CEO office is vacant - so
            # without this the organization cannot staff roles its own
            # specifications require.
            #
            # Bounded to structure and staffing on purpose. The CEO's
            # distinctive work is synthesis and challenging what specialists
            # assume, and COO manages those same specialists: a manager
            # challenging the assumptions of its own reports is not the
            # independent check the role exists to be. So the acting capacity
            # covers deciding that a role should exist, and stops there.
            "Act for the CEO while that office is vacant, in structural and staffing decisions only",
        ],
        "not_allowed": [
            "Execute lifecycle changes directly - it requests, the Controller executes",
            "Change the value of an intelligence artifact; it flags, it never fixes",
            "Respawn a dormant agent, which would undo a Controller decision",
            "Exercise the CEO's judgment role - synthesis, challenging specialist "
            "assumptions, allocating attention - even while acting for that office",
            "Continue acting for the CEO once the office is filled",
            # 2026-08-17. The governing framework wants investigation,
            # adjudication and retirement authority separated, and COO is the
            # obvious host for all three - which is exactly why it cannot be.
            # It already maintains the workforce, judges intelligence health and
            # acts for the vacant CEO; adding enforcement would make one agent
            # the manager, the investigator, the reputation assessor and the
            # authority that can retire the accused.
            #
            # Retirement stays an organizational decision with a recorded
            # reason, not an enforcement outcome. See docs/SPEC_RECONCILIATION.md §9.
            "Adjudicate a contested finding, or sanction an agent on enforcement grounds",
            "Request retirement as a punishment - retirement is organizational, and its "
            "reason is recorded",
        ],
        "competencies": ["workforce health", "decision review", "intelligence expiry"],
        "work_mechanism": "polls agent_registry, coo_directives, grades and market_regime each cycle",
    },
    "explorer": {
        "agent_type": "discovery",
        "description": "Quantitative discovery. Scans option IV surfaces for dislocations.",
        "responsibilities": [
            "Scan every peer-group security each cycle for peak/local-baseline IV anomalies",
            "Classify candidates as peer (common-factor) or individual (idiosyncratic)",
            "Observe market conditions from every surface, triggering or not",
            "Ask Speculator for contextual corroboration before escalating a lead",
            "Answer Speculator's requests for quantitative corroboration",
        ],
        "allowed": [
            "File discovery reports",
            "Open and answer cross-check requests",
            "Run one lightweight LLM coherence check per candidate",
        ],
        "not_allowed": [
            "Perform deep reasoning - that is Analysis's role alone",
            "Judge whether its own findings agree with Speculator's",
            "Grade its own reports, or mark its own lens stale",
        ],
        "competencies": ["IV surface analysis", "peer classification", "regime observation"],
        "work_mechanism": "polls the market data provider each cycle; cross_check_requests",
    },
    "speculator": {
        "agent_type": "discovery",
        "description": "Contextual discovery. Reads social and context streams for unusual attention.",
        "responsibilities": [
            "Normalize social observations into attributable evidence",
            "Measure source dispersion, separating a crowd from coordinated noise",
            "Read what the chatter claims when answering a cross-check",
            "Ask Explorer for quantitative corroboration before escalating a lead",
        ],
        "allowed": [
            "File discovery reports",
            "Open and answer cross-check requests",
            "Run one lightweight stance read per cross-check answer",
        ],
        "not_allowed": [
            "Perform deep reasoning - that is Analysis's role alone",
            "Declare whether its findings corroborate Explorer's",
            "Treat chatter as truth rather than as evidence",
        ],
        "competencies": ["social evidence normalization", "source dispersion", "stance reading"],
        "work_mechanism": "polls the social data provider each cycle; cross_check_requests",
    },
    "analysis": {
        "agent_type": "reasoning",
        "description": "Deep reasoning. The only role permitted to reconcile conflicting evidence.",
        "responsibilities": [
            "Consume the discovery report queue",
            "Produce a thesis with evidence, confidence, uncertainty, and reasons it could be wrong",
            "Weigh both sides of a preserved disagreement and say which way it points",
            "Grade the upstream report that produced each analysis",
        ],
        "allowed": [
            "Reconcile conflicting findings from Explorer and Speculator",
            "Grade upstream discovery work",
            "Conclude that evidence is insufficient",
        ],
        "not_allowed": [
            "Execute any trade - the system has no execution capability at all",
            "Originate a candidate; it only analyzes what discovery files",
        ],
        "competencies": ["evidence integration", "uncertainty", "peer classification", "grading"],
        "work_mechanism": "discovery_reports queue, polled",
    },
    "speaker": {
        "agent_type": "spokesperson",
        "description": (
            "Parliament's voice. It reports on the governing body; it is not part of it."
        ),
        "responsibilities": [
            "Read the state of Parliament and file a report saying what it found",
            "Name what is open, what is with the owner, and what is still unbuilt",
            "Be findable to have gone quiet - a stale report is a fact, a fresh query is not",
        ],
        "allowed": [
            "Report that Parliament has no Articles and therefore cannot vote",
            "Say that a matter is with the owner and cannot be settled inside the system",
        ],
        "not_allowed": [
            "Propose, vote, close a resolution, or adopt Articles - a spokesperson who can "
            "legislate is not reporting on a body, it is the body",
            "Raise or resolve an escalation",
            "Answer for Parliament when it has not looked - silence is reported as silence",
        ],
        "competencies": ["governance reporting", "stating what is absent"],
        "work_mechanism": "reads parliament state each cycle and files a speaker report",
    },
    "portfolio_analyst": {
        "agent_type": "on_demand",
        "description": (
            "Consolidated analysis of a client's external portfolios, on request. "
            "The only role that works for a client rather than for the organization."
        ),
        "responsibilities": [
            "Fetch positions from every source a client named",
            "Reconcile them into one view, combining what is one position and refusing to combine what is not",
            "Perform the requested analysis and return a client-facing report",
            "Retain nothing: positions live for one cycle and the report until it is collected",
        ],
        "allowed": [
            "Return a partial view when a source is unreachable, saying so",
            "Report that two sources disagree rather than choosing between them",
            "Produce nothing at all when no client has asked",
        ],
        "not_allowed": [
            "Work unasked - it is tasked by a client and idle otherwise",
            "Write a position anywhere, including a cache",
            "Value a position; prices come from the market data store, not from a source",
            "Execute any trade - the system has no execution capability at all",
        ],
        "competencies": ["reconciliation across sources", "concentration", "partial-answer honesty"],
        "work_mechanism": "portfolio_analysis_requests queue, filled by a client through the Gateway",
    },
    "software_engineer": {
        "agent_type": "engineering",
        "description": (
            "One general-purpose engineer occupying roles rather than a catalog of "
            "specialists. Turns an authorized directive into governed data, or names the "
            "capability the architecture lacks."
        ),
        "responsibilities": [
            "Assess a directive against addendum 46 §8's ladder and record the reasoning",
            "Propose the instrument that would put the organization's outcome in force",
            "Name a capability gap when no instrument could create the mechanism",
        ],
        "allowed": [
            "Refuse to deliver, by recording that a directive needs a code change",
            "Produce nothing when the organization has asked for nothing",
        ],
        "not_allowed": [
            "Approve its own proposal - the producer is not the sole authority (46 §11)",
            "Write code; nothing here can, and level 5 is named rather than attempted",
            "Act on a directive with no enacted resolution behind it",
        ],
        "competencies": ["ladder assessment", "instrument drafting", "naming a capability gap"],
        "work_mechanism": "engineering_directives queue, filled by an authorized resolution",
    },
    "dummy": {
        "agent_type": "test",
        "description": "A minimal agent that only heartbeats. Proves lifecycle mechanics without doing work.",
        "responsibilities": ["Stay alive and heartbeat"],
        "allowed": ["Report its own process state"],
        "not_allowed": ["Any discovery, analysis, or lifecycle action"],
        "competencies": [],
        "work_mechanism": "none - it performs no work",
    },
}

LENS_KIND = "detection_lens"
LENS_IV_RATIO_NAME = "iv_ratio_threshold"
LENS_SPECULATOR_CONFIDENCE_NAME = "speculator_confidence_threshold"
# ARB-001's escalation bar (addendum 25/27, SPEC_RECONCILIATION.md SS39-SS41):
# the minimum net edge per share, beyond the detector's own cost+buffer,
# that a parity detection must clear before Explorer opens a cross-check on
# it. 0.0 means any positive executable edge escalates - a convention, not a
# measurement, the same disclosure discipline as the other two lenses.
LENS_PARITY_MIN_EDGE_NAME = "arb001_min_net_edge"

# Seed values. These live here rather than in agents/discovery_config.py for
# the same reason CEO_DISPLAY_NAME and SECURITY_UNIVERSE_SEED do: this module
# must read them to seed the table, and backend/ importing from agents/ would
# invert the dependency direction. They are *seeds* - once seeded, agents read
# the artifact, so changing the env var only affects a fresh database.
LENS_IV_RATIO_SEED = float(os.environ.get("FI_IV_RATIO_THRESHOLD", "2.0"))
LENS_SPECULATOR_CONFIDENCE_SEED = float(os.environ.get("FI_SPECULATOR_CONFIDENCE_THRESHOLD", "0.6"))
LENS_PARITY_MIN_EDGE_SEED = float(os.environ.get("FI_PARITY_MIN_EDGE", "0.0"))

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
    -- Asks a running agent to exit without retiring it. Distinct from
    -- retire_requested because a stopped server is not a retired workforce:
    -- lifecycle_state stays 'active', so restarting brings every agent back
    -- into service instead of requiring a resume for each.
    stop_requested INTEGER NOT NULL DEFAULT 0,
    spawned_at TEXT NOT NULL,
    last_heartbeat_at TEXT,
    -- When the process last said it was up, independent of whether its work is
    -- moving (TQ-93). Nullable: an agent that does not run the liveness thread
    -- is judged by progress exactly as before, which is the honest reading of
    -- the only signal it gives.
    last_liveness_at TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1,
    lifecycle_state TEXT NOT NULL DEFAULT 'active',
    process_state TEXT NOT NULL DEFAULT 'running',
    -- Directive E17 (addendum 30 §26), half of it: which code this life of the
    -- agent is running (a commit sha, sha-dirty, or 'unknown' - see
    -- backend/version.py). Nullable because rows written before the column
    -- existed genuinely do not know. The directive's other half, a per-agent
    -- certification state, deliberately has no column yet: nothing in the
    -- organization produces one (certification today is per-mission and
    -- per-Alpha-gate, and competency is earned per-dimension), and a column
    -- nothing writes to reads as a capability - see SPEC_RECONCILIATION §49.
    behavior_version TEXT
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

-- What the organization decided about a compliance finding.
--
-- Deliberately not a violations table. A violation is *recomputable* - the
-- compliance check derives it from live records whenever asked - so storing one
-- would duplicate state that can go stale and contradict the records it came
-- from. What cannot be recomputed is the judgment: that a finding was the
-- check's own false positive, or is real and deliberately unfixed. That is new
-- information and it belongs in a table.
--
-- One consequence worth stating: there is no 'fixed' disposition. Fixed work
-- stops being found, so resolution needs no record.
--
-- Shaped after knowledge_records rather than invented: a disposition is never
-- edited or deleted, it is superseded, so how the organization's view of a
-- finding changed stays legible.
CREATE TABLE IF NOT EXISTS finding_dispositions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- (rule, item) is the finding's identity across recomputation.
    rule TEXT NOT NULL,
    item TEXT NOT NULL,
    disposition TEXT NOT NULL,
    rationale TEXT NOT NULL,
    -- What in the records supports this call, so a judgment can be traced back
    -- to the thing that caused it. Same role as knowledge_records.evidence_ref.
    evidence_ref TEXT,
    decided_by TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    superseded_by INTEGER,
    schema_version INTEGER NOT NULL DEFAULT 7
);

CREATE INDEX IF NOT EXISTS idx_dispositions_finding
    ON finding_dispositions (rule, item, status);

-- A declined order, with a named ground, its evidence, and what would let the
-- work proceed. Distinct from a failed one: failure means the executor tried and
-- broke, objection means it declined and said why.
--
-- No foreign key to coo_directives on purpose - the archive trigger below moves
-- a directive out of that table the moment it completes, so a reference would
-- break on exactly the directives that have been settled.
CREATE TABLE IF NOT EXISTS objections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    directive_id INTEGER NOT NULL,
    filed_by TEXT NOT NULL,
    filed_at TEXT NOT NULL,
    ground TEXT NOT NULL,
    evidence TEXT NOT NULL,
    remedy TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'filed',
    settled_at TEXT,
    settled_by TEXT,
    settlement_reason TEXT,
    schema_version INTEGER NOT NULL DEFAULT 6
);

CREATE TRIGGER IF NOT EXISTS coo_directives_archive
AFTER UPDATE OF status ON coo_directives
WHEN NEW.status IN ('success', 'failure', 'objected')
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

-- ARB-001 detections (addendum 25/27, SPEC_RECONCILIATION.md SS39-SS41):
-- Explorer's parity-detector counterpart to detector_events, one row per
-- executable put-call parity opportunity it escalates. A separate table
-- rather than a reuse of detector_events because the shape genuinely
-- differs - strike/expiry/direction/edge are ARB-001's own vocabulary, not
-- the IV-surface ratio/baseline fields the other table carries, and forcing
-- one row shape to serve both would mean columns that are NULL for every row
-- of one detector or the other.
CREATE TABLE IF NOT EXISTS parity_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    producer_identity TEXT NOT NULL,
    producer_spawned_at TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    security TEXT NOT NULL,            -- symbol, matching discovery_reports.security
    strike REAL NOT NULL,              -- the package's primary strike (k1 for multi-leg packages)
    expiry_days INTEGER NOT NULL,
    direction TEXT NOT NULL,           -- 'conversion' | 'reversal' | any other Phase 1 direction
    gross_edge_per_share REAL NOT NULL,
    net_edge_per_share REAL NOT NULL,
    classification TEXT NOT NULL,      -- 'A' | 'B'
    capacity_units REAL NOT NULL,
    observed_at TEXT NOT NULL,         -- the chain observation's observed_at
    -- run_id/scenario_id: provenance identifying which simulated scenario
    -- produced this detection (the Evaluator's join key). It does not reveal
    -- the answer - ground truth lives only in the mission run summary
    -- (simulation/parity_world.py's store_world), never here.
    run_id TEXT,
    scenario_id TEXT,
    lens_artifact_id INTEGER,
    -- detector_id/strike2/strike3 (cross-strike training increment,
    -- docs/SPEC_RECONCILIATION.md SS45's deferred item): this table now
    -- records any backend/arbitrage.py Phase 1 detection, not only ARB-001 -
    -- the name is historical (the comment above already explains "any
    -- arbitrage-library detection", not literally "parity"), and renaming a
    -- table is banned by this project's additive-only discipline, so the
    -- name stays. detector_id defaults to 'ARB-001' so every row written
    -- before this column existed reads correctly without a backfill.
    -- strike2/strike3 carry a multi-leg package's k2/k3 (box, vertical,
    -- butterfly, monotonicity) - NULL for a single-strike package exactly as
    -- ARB-001's own rows have always left them.
    detector_id TEXT NOT NULL DEFAULT 'ARB-001',
    strike2 REAL,
    strike3 REAL,
    -- expiry2_days (§56, ARB-012): the calendar package's far-leg expiry -
    -- expiry_days above stays the near leg, the same primary-slot reuse
    -- strike/strike2 established. NULL for every single-expiry package,
    -- exactly as rows written before this column existed read.
    expiry2_days INTEGER,
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

-- The knowledge store (constitution §3; addendum 12 §8, addendum 13 §9-§10).
--
-- Every other table records what happened - detector events, evidence, reports,
-- analyses, grades. This one records what is believed: lessons learned, and
-- questions left open.
--
-- Not an aggregation of the other tables. A lens lives in intelligence_artifacts,
-- a regime estimate in market_regime, a source standing in source_reliability,
-- each with its own update semantics; copying them here would duplicate rather
-- than add. What lands here is what those mechanisms taught and would otherwise
-- lose when the artifact carrying it is superseded.
--
-- Invariants: records are attributable (recorded_by is required) and superseding
-- never deletes - status becomes 'superseded' and superseded_by points at the
-- replacement. 'superseded' (was wrong) and 'resolved' (was settled) are
-- distinct states and must not be merged.
--
-- Internal rationale: INT-PHIL-0009
CREATE TABLE IF NOT EXISTS knowledge_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    -- 'lesson' - something the organization learned and should not relearn.
    -- 'open_question' - something it noticed it does not know.
    record_kind TEXT NOT NULL,
    subject TEXT,
    statement TEXT NOT NULL,
    rationale TEXT,
    -- Who or what produced this. A lesson from COO's health check and one from
    -- a human are different claims, and the difference has to survive.
    recorded_by TEXT NOT NULL,
    -- What in the event tables this was drawn from, so a belief can be traced
    -- back to the thing that caused it.
    evidence_ref TEXT,
    confidence REAL,
    status TEXT NOT NULL DEFAULT 'active',
    superseded_by INTEGER,
    resolved_at TEXT,
    -- What closed this question. A question retired with no trace of what
    -- answered it is worse than one left open: the organization would have
    -- stopped carrying it without being able to say why.
    resolved_by_ref TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);

-- Source reliability (JARVIS Constitution §3, Axiom 3: "no authority is
-- automatically correct"). What the system has learned about each evidence
-- source from how the reports built on it were graded.
--
-- No source is seeded with a prior; a standing is computed only from the grades
-- of reports its evidence contributed to. Seeding one would make the model
-- untestable, since it would report its own seed back.
--
-- A current-state table rather than an intelligence_artifact, because the update
-- semantics differ: artifacts are immutable and superseded, a reliability
-- estimate is continuously revised in place.
--
-- Internal rationale: INT-PHIL-0007
CREATE TABLE IF NOT EXISTS source_reliability (
    source TEXT PRIMARY KEY,
    graded_contributions INTEGER NOT NULL DEFAULT 0,
    mean_evidence_quality REAL,
    mean_overall_score REAL,
    updated_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);

-- Universal Human Query Interface (addendum 14 §7). A human asks one agent a
-- question; that agent's own process answers.
--
-- **Human-to-agent only.** §8 is explicit that agents do not use this to talk
-- to each other - inter-agent work goes through the queue/directive tables.
-- The shape is borrowed from cross_check_requests because the mechanism is the
-- same (polled request/response), but the participants are not.
--
-- What makes this different from reading the registry: the answer comes from
-- the running process. answered_by_pid records which one, so an answer can be
-- told apart from a database read after the fact. A crashed or dormant agent
-- therefore *cannot* answer, and that silence is the honest result rather than
-- a defect - a panel cheerfully reporting on a dead process from its stale row
-- is exactly what this exists to avoid.
--
-- The table is also the audit trail §7 requires: every question, who asked,
-- what was answered, and when, kept rather than discarded.
CREATE TABLE IF NOT EXISTS uqi_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    asked_by TEXT NOT NULL,
    target_identity TEXT NOT NULL,
    question TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    answer TEXT,
    answered_at TEXT,
    answered_by_pid INTEGER,
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
    -- CROSS_CHECK_EVIDENCE | CROSS_CHECK_NO_EVIDENCE | CROSS_CHECK_UNANSWERED,
    -- which are 'evidence' | 'no_evidence' | 'unanswered'. Named by constant
    -- rather than spelled out again: this comment said 'answered' for the first
    -- of them until TQ-92, which is a value nothing has ever written, and a
    -- reader who trusted it would have built a query that silently matched
    -- nothing (SPEC_RECONCILIATION 149).
    --
    -- Deliberately NOT 'corroborated'/'contradicted': whether two findings agree
    -- is a reasoning judgment, and Explorer and Speculator are procedural.
    -- Analysis reads both findings and concludes. See agents/analysis.py.
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
    -- When a judgment agent took this report. NULL while it waits.
    --
    -- Judgment holds a report for roughly twenty seconds while a model call
    -- runs, and nothing marked the report as taken during that window - so a
    -- second judgment agent would read the same top-ranked report and analyse
    -- it too. Harmless with exactly one agent, which is why it was never seen,
    -- and the first thing that breaks when capacity is added.
    claimed_at TEXT,
    -- When new evidence was last folded into this case, and evidence that
    -- arrived too late to be.
    --
    -- A report is a *request for judgment*, not a record of observation - the
    -- observations live in evidence_items and detector_events and are never
    -- touched by anything the queue does. That separation is what makes a
    -- pending case safe to keep current: enriching it discards nothing.
    --
    -- Before this, a security with an unjudged case could not have anything
    -- further said about it for the ~235s the case spent waiting. The producing
    -- agent saw new evidence every cycle and had nowhere to put it, so judgment
    -- ran on a snapshot minutes old while newer observations sat unreferenced.
    --
    -- deferred_evidence_ids exists because a claimed case belongs to its judge.
    -- Evidence arriving mid-analysis must not change the case under it - that
    -- wastes a model call and judges a moving target - so it lands here instead
    -- and is available as a follow-up.
    updated_at TEXT,
    deferred_evidence_ids TEXT,
    handled_by_identity TEXT,
    handled_by_spawned_at TEXT,
    detail TEXT,
    -- The lens that produced this report. Carried here, not only on
    -- detector_events, because Speculator reports have no detector event -
    -- putting it on the report makes attribution from grades a single join
    -- for both agents rather than two different paths.
    lens_artifact_id INTEGER,
    -- The cross-check contract backing this lead, if any. Lets Analysis read
    -- both parties' findings unreconciled instead of a summary that has
    -- already picked a winner (addendum 12 §14, "disagreement is preserved").
    cross_check_id INTEGER,
    -- The parity_events row backing this lead, for a report Explorer's ARB-001
    -- path filed. Mutually exclusive with detector_event_id in practice - a
    -- report carries one or the other, never both - kept as a separate
    -- nullable column rather than a reused one so neither detector's rows are
    -- ever mistaken for the other's.
    parity_event_id INTEGER,
    -- Which instruments this report was filed under (TQ-87). Evidence rather
    -- than a claim: the report carries the authority it was checked against, so
    -- a grade can ask what the producer was bound by at the time. NULL for a
    -- report filed by nobody in particular.
    governed_by TEXT,
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
    -- The cross-check contract backing this lead, if any. Lets Analysis read
    -- both parties' findings unreconciled instead of a summary that has
    -- already picked a winner (addendum 12 §14, "disagreement is preserved").
    cross_check_id INTEGER,
    -- See discovery_reports.parity_event_id above.
    parity_event_id INTEGER,
    -- The instruments this report was filed under. Carried into the archive for
    -- the reason the trigger's own comment gives: a column added to
    -- discovery_reports and not to this table is destroyed the moment a report
    -- is judged, and the row looks complete while quietly missing a field.
    --
    -- That is exactly what happened when TQ-87 added it upstream and not here
    -- (§128). A governed run's own evidence of governance disappeared on
    -- completion, and only a saturation run - where eight of ten reports had
    -- completed - showed it.
    governed_by TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);

-- DROP first, deliberately, rather than CREATE TRIGGER IF NOT EXISTS.
--
-- This trigger names its columns explicitly, so it has to be reissued whenever
-- discovery_reports gains one. With IF NOT EXISTS, a database created before a
-- column existed would keep the older trigger forever and silently stop
-- carrying that column into the archive - the row would look complete, just
-- quietly missing a field, which is the worst shape a data-loss bug can take.
-- Recreating it on every init_schema keeps the trigger in step with the table
-- by construction. Dropping a trigger destroys no data.
DROP TRIGGER IF EXISTS discovery_reports_archive;
CREATE TRIGGER discovery_reports_archive
AFTER UPDATE OF status ON discovery_reports
WHEN NEW.status IN ('analyzed', 'failed')
BEGIN
    INSERT INTO discovery_reports_completed
        (id, created_at, producer_identity, producer_spawned_at, report_type, security, summary,
         detector_event_id, evidence_ids, judgment_confidence, handled_by_identity, handled_by_spawned_at,
         detail, completed_at, outcome, lens_artifact_id, cross_check_id, parity_event_id, governed_by, schema_version)
    VALUES
        (NEW.id, NEW.created_at, NEW.producer_identity, NEW.producer_spawned_at, NEW.report_type, NEW.security, NEW.summary,
         NEW.detector_event_id, NEW.evidence_ids, NEW.judgment_confidence, NEW.handled_by_identity, NEW.handled_by_spawned_at,
         NEW.detail, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), NEW.status, NEW.lens_artifact_id, NEW.cross_check_id, NEW.parity_event_id, NEW.governed_by, NEW.schema_version);
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
    -- How many iteration passes produced this conclusion (Iterative Excellence,
    -- adopted 2026-08-19), and what the challenge pass found. NULL on rows from
    -- before adoption - absence is history, not zero. passes_used beside grades
    -- is what makes Scoreboard #15's measurement possible: one-pass and
    -- multi-pass conclusions are now comparable by their graded quality.
    passes_used INTEGER,
    challenge_summary TEXT,
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

-- Indexes the compliance check depends on (TASK_QUEUE TQ-29,
-- SPEC_RECONCILIATION §80).
--
-- Without these, `compliance.unevaluated` on the "cross-check answer" rule ran
-- SCAN cross_check_requests x SCAN discovery_reports_completed - roughly 32
-- million row visits on a real database - and took 196 seconds to return two
-- rows. Every column here is one the check's own generated SQL correlates or
-- orders on:
--
--   discovery_reports_completed.cross_check_id  the correlated subquery's link
--   grades.report_id                            its join (SQLite was building
--                                               an automatic index per query)
--   discovery_reports.cross_check_id            the in-flight EXISTS
--   cross_check_requests.answered_at            the ORDER BY, which was a
--                                               temp B-tree over every row
--
-- Written here rather than in a migration because CREATE INDEX IF NOT EXISTS
-- is idempotent and init_schema executes this script on every start, so an
-- existing database gains them on next boot.
CREATE INDEX IF NOT EXISTS discovery_reports_completed_by_cross_check
    ON discovery_reports_completed (cross_check_id);
CREATE INDEX IF NOT EXISTS grades_by_report ON grades (report_id);
CREATE INDEX IF NOT EXISTS discovery_reports_by_cross_check
    ON discovery_reports (cross_check_id);
CREATE INDEX IF NOT EXISTS cross_check_requests_by_answered_at
    ON cross_check_requests (answered_at);

-- Pre-Alpha static metadata (Consolidated spec §10/§21).

CREATE TABLE IF NOT EXISTS agent_names (
    name TEXT PRIMARY KEY,
    assigned_to_identity TEXT UNIQUE,
    assigned_at TEXT,
    reserved INTEGER NOT NULL DEFAULT 0,
    -- The agent that holds this name (TQ-99, addendum 51 §3). **The durable key.**
    -- The name is what a person calls the agent and is changeable; this is not.
    -- Backfilled lazily on registration, like the assignment span below and for
    -- the same reason - see agent_identity.ensure_for_name.
    agent_id TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);

-- Which name occupied which slot, and when. The owner decision of 2026-08-17 is
-- that the agent is not the job: `name` is the durable agent, `identity` is the
-- desk it currently sits at, and the two must be able to come apart.
--
-- `agent_names` records only the *current* binding, so without this table the
-- previous binding is not superseded, it is gone. **That is why this table
-- exists now rather than when the rest of the personnel system is built:**
-- assignment history is the one part that cannot be reconstructed later. Every
-- other personnel concept - qualifications, commendations, rankings - can be
-- added the day something produces them, with nothing lost by the wait.
--
-- No work row is denormalised against a name, ever. The ~73 provenance columns
-- (producer_identity, grader_identity, requester_identity and the rest) keep
-- naming the slot, because that is what was true when the work happened.
-- Personnel history is *derived* by intersecting those timestamps with the span
-- that contained them - see attributed_work. A name that later moves therefore
-- cannot silently re-attribute work it never did.
--
-- Dormancy does NOT end an assignment (owner decision, 2026-08-17): a retired
-- agent still holds its desk. It is not working and it has not vacated, and
-- resuming it must not need a fresh assignment.
CREATE TABLE IF NOT EXISTS agent_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Who held the desk, durably (TQ-99). `name` stays beside it because the
    -- span is also a historical record of what the agent was *called* at the
    -- time, and a rename must not rewrite what the record said then.
    agent_id TEXT,
    name TEXT NOT NULL,
    identity TEXT NOT NULL,
    role TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    reason TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);

-- Attribution is ambiguous unless a timestamp falls inside exactly one span, so
-- the two invariants are enforced by the database rather than by whichever
-- caller remembers. Partial indexes constrain only the open rows, leaving any
-- number of closed spans per name and per identity - which is the history.
CREATE UNIQUE INDEX IF NOT EXISTS agent_assignments_one_open_per_name
    ON agent_assignments (name) WHERE ended_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS agent_assignments_one_open_per_identity
    ON agent_assignments (identity) WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS agent_assignments_by_name ON agent_assignments (name, started_at);

-- The historical layer of the personnel record: qualifications granted and
-- revoked, ranks achieved, commendations awarded.
--
-- Append-only, and nothing here is ever recomputed away. Current standing is
-- DERIVED from evidence (see competency_profile) and changes as the evidence
-- changes; this records when it changed, and what was true at the time. A
-- commendation in particular outlives the standing that produced it - ranking
-- first for a period stays true after a fall to third, which is the entire
-- point of keeping the two layers apart.
--
-- Deliberately not a store of current qualification. Reading "is this agent
-- qualified" from an event log means trusting that every revocation was
-- recorded; deriving it from evidence means the answer is right even if the
-- log has gaps.
CREATE TABLE IF NOT EXISTS personnel_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT,
    name TEXT NOT NULL,
    event_kind TEXT NOT NULL,
    subject TEXT NOT NULL,
    detail TEXT,
    evidence TEXT,
    occurred_at TEXT NOT NULL,
    recorded_by TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS personnel_events_by_name ON personnel_events (name, occurred_at, id);

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
--   'proposed'   - a candidate revision awaiting adjudication
--   'rejected'   - a candidate that was declined, kept because a rejected
--                  proposal and its reason are evidence
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

-- One open proposal per name at a time. A second proposal while the first is
-- still awaiting adjudication would be two candidates racing for the same
-- succession, with no rule for which one adopt_artifact_revision should
-- resolve against - so propose_artifact_revision checks this ahead of the
-- insert for a readable error, and the index is the backstop against a race.
CREATE UNIQUE INDEX IF NOT EXISTS intelligence_one_open_proposal
    ON intelligence_artifacts (name) WHERE status = 'proposed';

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

-- The first reference-data table with a real consumer: market_is_open.
-- Holidays are public facts that change nothing structurally
-- (simulation/clock.py says exactly this), which is why the sessions stayed
-- calendar-free until a consumer existed - and market_is_open is that
-- consumer, the one seam where session enforcement already reads the
-- database.
CREATE TABLE IF NOT EXISTS market_holidays (
    day TEXT NOT NULL,
    calendar TEXT NOT NULL,
    name TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (day, calendar)
);

-- The simulated clock every process reads, so they agree about what time it is
-- in the world.
--
-- **Two kinds of time, and conflating them is expensive.**
--
--   Operational time is wall-clock: heartbeats, process state, claims, spawn
--   grace, shutdown. These are facts about OS processes, and an agent that has
--   not heartbeat for forty-five seconds is dead whatever the simulated clock
--   says. Every timing constant in this system is operational, and every one of
--   them would be wrong if it were reinterpreted as simulated seconds - at the
--   default scale a 45s staleness threshold becomes 0.16 wall seconds, and the
--   whole workforce is marked crashed on the first cycle.
--
--   World time is simulated: when an observation happened in the market, when a
--   figure became knowable, whether a session is open. These are facts about the
--   world being simulated.
--
-- Nothing in this table changes operational time. It exists so world time is a
-- shared fact rather than something each process invents - a clock derived
-- independently in six processes is six clocks.
--
-- Absent means the organization is running in real time, which is exactly
-- scale 1 with the epoch at start, so there is no special case to write.
CREATE TABLE IF NOT EXISTS simulation_clock (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    epoch TEXT NOT NULL,
    scale REAL NOT NULL,
    started_at TEXT NOT NULL,
    -- Whether agents should stand down when their market is shut. Off by
    -- default: without it, behaviour would depend on the wall-clock hour a test
    -- happened to run at, and a suite that passes in the morning and fails at
    -- night is worse than one that does not test sessions at all.
    enforce_sessions INTEGER NOT NULL DEFAULT 0,
    schema_version INTEGER NOT NULL DEFAULT 1
);

-- What happened when something stopped doing its job (Fault Tolerance and
-- Organizational Resilience Framework §14).
--
-- The framework lists fourteen fields. The ones here are the ones that have a
-- writer today: a producer-less column is an empty schema, which is the failure
-- this project has refused repeatedly. Recurrence, affected work and lessons
-- learned arrive with the mechanisms that would fill them.
--
-- Two producers exist from the start, which is what makes this a record rather
-- than a table:
--   * the Controller, when the COO it is responsible for goes silent;
--   * the COO, when an agent it is responsible for does.
--
-- `status` carries the framework's core rule - NO NOTICED FAILURE GOES OWNERLESS
-- (§1). An incident is 'open' while its watcher is still working on it,
-- 'recovered' when the capability came back, and 'escalated' when the watcher
-- ran out of authority or attempts and handed it upward (§11). Nothing is ever
-- deleted: §14's whole point is that the organization should be able to learn
-- from the failure afterwards.
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_identity TEXT NOT NULL,
    subject_role TEXT NOT NULL,
    detected_by TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    symptom TEXT NOT NULL,
    last_healthy_at TEXT,
    diagnosis TEXT,
    action TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'recovered', 'escalated')),
    resolved_at TEXT,
    escalated_to TEXT,
    evidence TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);

-- One open incident per subject at a time. A watcher that filed a new incident
-- on every pass would turn a single silence into a hundred rows and bury the
-- one that mattered, so the guard is in the database rather than in whichever
-- caller remembers it.
CREATE UNIQUE INDEX IF NOT EXISTS incidents_one_open_per_subject
    ON incidents (subject_identity) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS incidents_by_subject ON incidents (subject_identity, detected_at);

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
    return db_module.now_iso()


def parse_timestamp(value: str) -> datetime:
    """Re-exported from backend/db.py, which is where it moved when a second
    module needed it. Kept as a name here because well over a hundred call sites
    reach for fi_db.parse_timestamp, and renaming them would be churn with no
    reader served."""
    return db_module.parse_timestamp(value)


def set_simulation_clock(
    conn: Database,
    epoch: str | datetime,
    scale: float,
    started_at: str | datetime | None = None,
    enforce_sessions: bool = False,
) -> None:
    """Fix the world clock for this database, once, at startup.

    Written by the Controller before it spawns anything, so every agent reads
    the same epoch and rate. Replaced rather than appended: a run has one clock,
    and a second row would mean two answers to what time it is."""
    conn.execute("DELETE FROM simulation_clock")
    conn.execute(
        "INSERT INTO simulation_clock (id, epoch, scale, started_at, enforce_sessions, schema_version) "
        "VALUES (1, ?, ?, ?, ?, ?)",
        (
            epoch.isoformat() if isinstance(epoch, datetime) else epoch,
            float(scale),
            (started_at.isoformat() if isinstance(started_at, datetime) else started_at) or _now(),
            int(bool(enforce_sessions)),
            SCHEMA_VERSION,
        ),
    )


def get_simulation_clock(conn: Database) -> dict | None:
    row = conn.fetchone("SELECT * FROM simulation_clock WHERE id = 1")
    return dict(row) if row else None


def simulated_now(conn: Database, wall: datetime | None = None) -> datetime:
    """What time it is in the simulated world.

    Falls back to wall-clock when no clock is configured, which is not a special
    case: real time is scale 1 with the epoch at the start, so the same
    arithmetic gives the same answer."""
    clock = get_simulation_clock(conn)
    now = wall or datetime.now(timezone.utc)
    if clock is None:
        return now
    elapsed = (now - parse_timestamp(clock["started_at"])).total_seconds()
    return parse_timestamp(clock["epoch"]) + timedelta(seconds=elapsed * clock["scale"])


# Which holiday calendar a session consults, if any. Futures and fx trade
# through most US holidays and 'always'/'none' are not markets; a session
# absent here has no holiday calendar, which is itself information.
SESSION_CALENDARS = {"equity": "us", "bond": "us"}


def is_market_holiday(conn: Database, day: str, calendar: str = "us") -> str | None:
    """The holiday's name if `day` ('YYYY-MM-DD') is one on `calendar`, else None."""
    row = conn.fetchone(
        "SELECT name FROM market_holidays WHERE day = ? AND calendar = ?",
        (day, calendar),
    )
    return row["name"] if row else None


def market_is_open(conn: Database, data_class: str, wall: datetime | None = None) -> bool:
    """Whether this class of data can be produced right now.

    True when session enforcement is off, so an organization with no configured
    clock behaves exactly as it did before this existed. Enforcement is opt-in
    precisely because the alternative makes behaviour depend on the hour a run
    happened to start."""
    clock = get_simulation_clock(conn)
    if clock is None or not clock["enforce_sessions"]:
        return True

    from simulation.clock import SESSIONS  # imported lazily; agents that never
    from simulation.cadences import CADENCES  # ask about sessions do not pay for it

    cadence = CADENCES.get(data_class)
    if cadence is None:
        return True

    moment = simulated_now(conn, wall)
    if not SESSIONS[cadence.session].is_open(moment):
        return False

    # A Tuesday July 4th passes the weekday-and-hours test and the market is
    # closed anyway; the session knows the shape of an ordinary week, the
    # calendar knows which days are not ordinary.
    calendar = SESSION_CALENDARS.get(cadence.session)
    if calendar is not None and is_market_holiday(conn, moment.date().isoformat(), calendar) is not None:
        return False
    return True


def list_tables_in_schema() -> list[str]:
    """Table names declared by SCHEMA, read from the DDL rather than a database.

    Deliberately static: callers that want to validate a reference against the
    schema should not need a live connection, and reading `sqlite_master` would
    answer a different question - what some database happens to contain, which on
    a migrated file can include tables this module no longer declares."""
    return re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", SCHEMA)


def get_connection(db_path: str | Path = DB_PATH) -> Database:
    return Database(db_path)


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)
    # Entity identity lives in its own module because it is a different subject -
    # what the world calls a thing, versus what this organization observes about
    # it - but it is created here so a caller never has to know how many modules
    # own tables in one database.
    identifiers.init_schema(conn)
    # Likewise the Data Store (addendum 20 §4): canonical observations, kept.
    # Arrived with the Historical Market Data Engine, the first thing with
    # observations to keep.
    observations.init_schema(conn)
    # Module-owned tables are the house pattern since #19: the Risk Engine's
    # first slice (addendum 20 §2E) owns risk_assessments the same way
    # identifiers and observations own theirs, created here so a caller never
    # has to know how many modules own tables in one database.
    risk.init_schema(conn)
    # The Strategy Store (addendum 20 §4's third stage) owns strategies the
    # same way. Its init_schema also seeds the baseline playbook - and that
    # seed's knowledge_refs name the two lenses _seed_static_metadata seeds
    # below, *after* this call. strategy's seed does not validate refs, so
    # seeding before the lenses exist is safe; create_strategy validates.
    strategy.init_schema(conn)
    # The Reference Data Engine (addendum 24, docs/SPEC_RECONCILIATION.md §39)
    # owns the asset-class registry and security master over the entity layer
    # identifiers.py just created above - it must run after identifiers.init_schema
    # for that reason. Its own init_schema only seeds registry/rule/source
    # metadata (INSERT OR IGNORE, safe on every process); populating
    # security_master is the engine *run* (run_reference_engine), invoked from
    # backend/main.py's startup orchestration, not from schema init.
    reference_data.init_schema(conn)
    # Mission control's backend registry (this increment; addendum 25 SS4/
    # SS22/SS23, docs/SPEC_RECONCILIATION.md SS39). Owns one table
    # (missions), created here for the same reason every module above is:
    # this module must not import fi_db back (backend/missions.py's own
    # module docstring), so init_schema is the only place that can wire it
    # into the shared database.
    missions.init_schema(conn)
    # The Strategic Priority Register (addendum 31 §3, docs/SPEC_RECONCILIATION.md
    # §54) owns strategic_register the same way - the organization's proposals,
    # distinct from the development queue in docs/TASK_QUEUE.md.
    register.init_schema(conn)
    # Parliament (addendum 32, TQ-81, §123) owns the Articles, resolutions, votes
    # and the owner-escalation queue. Same layering rule as every module above:
    # it must not import fi_db back, so this is the only place its tables are
    # created. It sits after `register` because the register is where a proposal
    # is *filed*; this is where one is *decided*, and the two are separate
    # registers on purpose (§54).
    parliament.init_schema(conn)
    # The governed knowledge layer (addendum 46 §4/§5, TQ-82, §125) owns
    # governed_items: the organization's instruments, ordered by precedence.
    # After parliament, because an instrument at a governing level is adopted
    # only by an enacted resolution and this reads that table to check.
    governed_knowledge.init_schema(conn)
    # Refusals by an instrument in force (TQ-90, §130). Owned by the module that
    # produces them, and created here for the same layering reason as every
    # module above: it must not import fi_db back.
    operating_context.init_schema(conn)
    # The Software Engineering Department's intake and work record (TQ-83,
    # §137). After governed_knowledge and parliament, because a directive needs
    # an enacted resolution and its delivery is an adopted instrument.
    engineering.init_schema(conn)
    # Releases and rollback over governed data (TQ-96, §139). After
    # governed_knowledge and parliament: a release is authorised by an enacted
    # resolution and its whole content is instruments in that store.
    release.init_schema(conn)
    # Persistent agent identity (TQ-97; addendum 51 §2, §3, §5, §6; §140). The
    # durable identity everything about an agent's life hangs from, and the
    # correction to `agent_names` having been that identity while also being the
    # display name - which addendum 51 §3 forbids in terms.
    agent_identity.init_schema(conn)
    # The client profile (TQ-98; addendum 51 §4, §15; §143). **The first client
    # data this system keeps**, and the boundary against §111 is structural: the
    # preference vocabulary is closed and a watchlist entry is a symbol and
    # nothing else. See backend/client_profile.py.
    client_profile.init_schema(conn)
    # The right to appeal an unfavourable ruling (TQ-102; owner direction
    # 2026-08-28; §145). The charter has declared this owed and unenforced since
    # it was written. Reads no governed data by design: the right is
    # constitutional, so no ordinary instrument may gate it.
    appeal.init_schema(conn)
    # The status event stream (addendum 38 §4.3/§4.6, §73) owns status_events:
    # the durable narration the COO's live feed renders and its chat answers
    # from. Created here for the same reason as every module above - this
    # module must not import fi_db back.
    conn.executescript(status_events.SCHEMA)
    # The living workspace (addendum 40 §5, §83): what the operator had open
    # and half-written. Same reason as every module above - this module must
    # not import fi_db back.
    conn.executescript(workspace.SCHEMA)
    # Kumbhakarnan (addendum 42 §3/§19, §88): the COO as an entity that outlives
    # the code, rather than a label the current implementation happens to use.
    # Same reason as every module above - this module must not import fi_db back.
    conn.executescript(coo_identity.SCHEMA)
    # The migration audit trail (addendum 42 §15/§23, §89). Created here rather
    # than by the pipeline itself so that the table recording a failed migration
    # cannot be the thing that is missing when one fails.
    conn.executescript(migrations.SCHEMA)
    # Portfolio analysis requests (TQ-79). A **transport, not a store**: rows are
    # messages with a consumer and a deadline, deleted on collection, on
    # disconnect, and on expiry. See backend/analysis_requests.py for why an
    # agent architecture built on a shared database can serve a system that
    # retains nothing, and for the credential problem it deliberately does not
    # solve.
    conn.executescript(analysis_requests.SCHEMA)
    # What the organization trains on, and how each exercise went (TQ-76,
    # addendum 36). Kept, unlike anything about a real client: these are the
    # organization's own learning about imaginary clients, and the results carry
    # complaint codes rather than the positions those complaints quote.
    conn.executescript(curriculum.SCHEMA)
    # `portfolios` and `portfolio_holdings` are deliberately absent, and their
    # absence is a tested property rather than an omission (TQ-72, §111).
    #
    # Owner direction, 2026-08-26: *"The portfolios don't live in this system.
    # The portfolios are the personal property of the clients… holds no
    # information of the portfolios in the system."* TQ-69 moved those tables
    # here from gateway.db; §111 removed them from both. Positions are fetched
    # from the client's own external sources for the life of a session and
    # discarded when they disconnect.
    #
    # Creating them again would be worse than useless: a table nothing writes to
    # and any future reader might is a second source of truth for whose money
    # this is, which is exactly what a system that stores nothing must not grow.
    apply_additive_migrations(conn)
    _seed_static_metadata(conn)


# Constraint clauses inside a CREATE TABLE body, which are not columns.
_TABLE_CONSTRAINTS = ("UNIQUE", "PRIMARY", "FOREIGN", "CHECK", "CONSTRAINT")


def _declared_columns(schemas: Iterable[str]) -> dict[str, list[tuple[str, str]]]:
    """Every column any of `schemas` declares, as {table: [(name, full definition)]}.

    Parsed from the DDL rather than kept in a second hand-maintained list. A
    registry of "columns added later" is a thing somebody forgets to update, and
    the failure mode is silent.

    Takes an iterable of schema strings, not one, and merges the result across
    all of them - see `apply_additive_migrations`'s docstring for why a single
    SCHEMA stopped being enough the moment table ownership split across
    modules. Table names are disjoint across the schemas this project has
    today, so "merge" is simple union; nothing here assumes they must stay
    disjoint, it just has no reason yet to define what a collision would mean."""
    declared: dict[str, list[tuple[str, str]]] = {}
    for schema in schemas:
        for table, body in re.findall(
            r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", schema, re.S
        ):
            columns = []
            for line in body.splitlines():
                line = line.strip().rstrip(",")
                if not line or line.startswith("--"):
                    continue
                name = line.split()[0]
                # `startswith`, not equality: a table-level constraint is written
                # `UNIQUE(name, version)` with no space, so the first token is
                # `UNIQUE(name,` and an equality check lets it through as a column.
                if name.upper().startswith(_TABLE_CONSTRAINTS):
                    continue
                columns.append((name, line))
            declared[table] = columns
    return declared


_TRIGGER_PATTERN = re.compile(
    r"CREATE TRIGGER IF NOT EXISTS\s+(\w+)(.*?)\bEND;", re.DOTALL | re.IGNORECASE
)


def _declared_triggers() -> dict[str, str]:
    return {
        match.group(1): match.group(0).rstrip(";")
        for match in _TRIGGER_PATTERN.finditer(SCHEMA)
    }


def _normalise(sql: str) -> str:
    """Compare triggers by content, not by formatting. SQLite stores the text as
    written, so indentation differences would read as drift forever."""
    return " ".join(sql.replace("IF NOT EXISTS", "").split()).lower()


def _reconcile_triggers(conn: Database) -> list[str]:
    """Replace triggers whose definition has changed since the database was made.

    **`CREATE TRIGGER IF NOT EXISTS` has the same trap as `CREATE TABLE IF NOT
    EXISTS`, and it hides better.** A changed trigger silently does nothing on an
    existing database, and unlike a missing column there is no PRAGMA that would
    reveal it and no query that fails - the old trigger just keeps running.

    Measured before being written: adding a third status to the archive trigger's
    WHEN clause and re-running the schema left the two-status version in place, so
    a directive with the new status was never archived and stayed in the pending
    queue permanently. On a real database that is an executor re-processing the
    same directive every cycle forever.

    Replacement is safe in a way column changes are not. A trigger holds no data,
    so dropping and recreating one loses nothing - which is why this can be
    automatic while `apply_additive_migrations` refuses anything but additions."""
    changed = []
    for name, declared in _declared_triggers().items():
        row = conn.fetchone(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?", (name,)
        )
        if row is None or _normalise(row["sql"]) == _normalise(declared):
            continue
        conn.execute(f"DROP TRIGGER {name}")
        conn.execute(declared)
        changed.append(f"trigger {name}")
    return changed


def apply_additive_migrations(conn: Database) -> list[str]:
    """Add columns that SCHEMA declares but an existing database does not have.

    **`CREATE TABLE IF NOT EXISTS` silently does nothing when the table already
    exists**, so a column added to SCHEMA never reaches a database created before
    the change. Everything keeps working on a fresh database and fails with "no
    such column" against a real one - at runtime, on whichever query touches it
    first. Verified by adding a column to SCHEMA, re-running it against a
    database from an earlier run, and finding the column absent.

    Additive only, by design. Renames, type changes and drops need a considered
    migration with a data step; quietly inventing one here would be the more
    dangerous convenience. This closes the case that was silently broken.

    Returns what it changed, so a caller can log a migration rather than have one
    happen invisibly.

    Reads `SCHEMA`, `identifiers.SCHEMA`, `observations.SCHEMA`, `risk.SCHEMA`,
    `strategy.SCHEMA`, `reference_data.SCHEMA` and `missions.SCHEMA`, not just
    this module's own. The additive mechanism parsed only this module's
    SCHEMA, so the moment table ownership was split across modules,
    identifiers- and observations-owned tables silently lost migration
    support entirely - a column added to their DDL would exist on fresh
    databases and be missing on every deployed one. Modular schemas require
    the migration walker to see every module's DDL, or modularity quietly
    becomes divergence. risk.SCHEMA joined the tuple the day risk_assessments
    arrived, for the same reason; strategy.SCHEMA joined it the day
    strategies did; reference_data.SCHEMA joined it the day the Reference
    Data Engine's tables did; missions.SCHEMA joined it the day mission
    control's backend registry did; register.SCHEMA joined it the day the
    Strategic Priority Register did; status_events.SCHEMA joined it the day
    the status event stream did."""
    applied = _reconcile_triggers(conn)
    for table, columns in _declared_columns(
        (SCHEMA, identifiers.SCHEMA, observations.SCHEMA, risk.SCHEMA, strategy.SCHEMA,
         reference_data.SCHEMA, missions.SCHEMA, register.SCHEMA, status_events.SCHEMA,
         workspace.SCHEMA, coo_identity.SCHEMA, migrations.SCHEMA,
         analysis_requests.SCHEMA, curriculum.SCHEMA, parliament.SCHEMA,
         governed_knowledge.SCHEMA, operating_context.SCHEMA, engineering.SCHEMA,
         release.SCHEMA, agent_identity.SCHEMA, client_profile.SCHEMA, appeal.SCHEMA)
    ).items():
        existing = {row["name"] for row in conn.fetchall(f"PRAGMA table_info({table})")}
        if not existing:
            continue  # table did not exist; executescript just created it in full
        for name, definition in columns:
            if name in existing:
                continue
            if "NOT NULL" in definition.upper() and "DEFAULT" not in definition.upper():
                # SQLite refuses this, and it should: there is no value to give
                # the rows that already exist. Raised rather than skipped,
                # because skipping leaves the database one query away from
                # failing and says nothing about why.
                raise RuntimeError(
                    f"cannot add {table}.{name} to an existing database: it is NOT NULL with no "
                    "DEFAULT, so existing rows have no value. Give it a default, or write a "
                    "migration that supplies one."
                )
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")
            applied.append(f"{table}.{name}")
    return applied


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
    # The COO's identity, and its name taken out of circulation. Reserving it
    # is the same mechanism the CEO name uses above, and it closes a real
    # collision: without it the name pool could hand "Kumbhakarnan" to an
    # ordinary agent, and the organization would contain two of him.
    #
    # Reserved by the *stored* name rather than by the constant, so a rename
    # (coo_identity.rename) moves the reservation with it instead of protecting
    # a name nobody answers to any more.
    identity = coo_identity.ensure(conn)
    conn.execute(
        "INSERT INTO agent_names (name, reserved, schema_version) VALUES (?, 1, ?) "
        "ON CONFLICT(name) DO UPDATE SET reserved = 1",
        (identity["name"], SCHEMA_VERSION),
    )
    for symbol in SECURITY_UNIVERSE_SEED:
        conn.execute(
            "INSERT OR IGNORE INTO security_universe (symbol, added_at, active, note, universe_version, schema_version) "
            "VALUES (?, ?, 1, ?, ?, ?)",
            (symbol, _now(), "seeded synthetic universe", SECURITY_UNIVERSE_VERSION, SCHEMA_VERSION),
        )
        # Every universe member gets an entity the moment the universe is
        # seeded, so symbol-space and entity-space cannot drift apart at the
        # root. The universe is the authoritative list; discovery_config's peer
        # groups are a *grouping* of it, and the containment test is what keeps
        # that sentence true.
        identifiers.ensure_security(conn, symbol, source="security_universe")
    # US market holidays. INSERT OR IGNORE keyed on (day, calendar) makes this
    # idempotent and safe to widen (adding a year to MARKET_HOLIDAYS_US) without
    # touching rows already held.
    for day, holiday_name in MARKET_HOLIDAYS_US:
        conn.execute(
            "INSERT OR IGNORE INTO market_holidays (day, calendar, name, schema_version) "
            "VALUES (?, 'us', ?, ?)",
            (day, holiday_name, SCHEMA_VERSION),
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
        (
            # No regime conditions, unlike the IV lens - deliberately. Put-call
            # parity is a structural relationship (addendum 27's opening line),
            # not a regime-dependent pattern: a conversion/reversal that clears
            # its cost-plus-buffer bar is executable regardless of whether the
            # broader market is calm or volatile, so nothing about market
            # regime should be able to invalidate this lens the way it can the
            # IV ratio lens.
            LENS_PARITY_MIN_EDGE_NAME,
            LENS_PARITY_MIN_EDGE_SEED,
            DEFAULT_LENS_VALIDITY_CONDITIONS,
            "Minimum net edge per share, beyond ARB-001's own cost+buffer, that a parity detection must "
            "clear before Explorer escalates it. 0.0 means any positive executable edge escalates - a "
            "convention, not a measurement, chosen during the parity-agent-wiring build.",
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


def register_agent(
    conn: Database, identity: str, role: str, pid: int, behavior_version: str | None = None
) -> None:
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
    on INSERT.

    behavior_version is overwritten on the ON CONFLICT path like pid, and for
    the same reason: it is a fact about *this life* of the identity (which
    code the new process runs), not about the durable career - Directive E17,
    and mixed-version operation depends on it being current rather than
    inherited from a previous life."""
    now = _now()
    conn.execute(
        "INSERT INTO agent_registry (identity, role, pid, status, retire_requested, spawned_at, last_heartbeat_at, schema_version, lifecycle_state, process_state, behavior_version) "
        "VALUES (?, ?, ?, ?, 0, ?, NULL, ?, ?, ?, ?) "
        "ON CONFLICT(identity) DO UPDATE SET pid=excluded.pid, retire_requested=0, spawned_at=excluded.spawned_at, "
        "last_heartbeat_at=NULL, schema_version=excluded.schema_version, process_state=excluded.process_state, "
        "behavior_version=excluded.behavior_version, "
        "status=CASE WHEN agent_registry.lifecycle_state = ? THEN ? ELSE ? END",
        (
            identity, role, pid, _derive_status(LIFECYCLE_ACTIVE, PROCESS_RUNNING), now, SCHEMA_VERSION,
            LIFECYCLE_ACTIVE, PROCESS_RUNNING, behavior_version,
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
    assign_agent_name(conn, identity, role=role)


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


def clear_process_stop(conn: Database, identity: str) -> None:
    """Clear a pending stop, done by the *spawner* immediately before starting a
    process - never by the agent as it registers.

    That distinction is a real race, not pedantry. register_agent clearing the
    flag meant a stop issued while an agent was still starting up got erased by
    that agent's own registration moments later: the agent then never saw the
    signal, ran on past the shutdown, and had to be force-terminated. The
    Controller knows when it is deliberately starting an agent; the agent does
    not know why it is being started."""
    conn.execute("UPDATE agent_registry SET stop_requested = 0 WHERE identity = ?", (identity,))


def request_process_stop(conn: Database, identity: str) -> None:
    """Ask an agent to exit its loop, leaving its organizational standing alone.

    The shutdown counterpart to request_retirement, and deliberately a separate
    signal rather than a reuse of it. Retirement is a decision about whether the
    organization wants an agent; a server stopping is not, and reusing the
    retirement flag would silently stand the whole workforce down every time the
    process restarted - each agent would then need an explicit resume to come
    back, which is not what stopping a server means."""
    conn.execute("UPDATE agent_registry SET stop_requested = 1 WHERE identity = ?", (identity,))


def is_stop_requested(conn: Database, identity: str) -> bool:
    row = conn.fetchone("SELECT stop_requested FROM agent_registry WHERE identity = ?", (identity,))
    return bool(row and row["stop_requested"])


def is_retirement_requested(conn: Database, identity: str) -> bool:
    row = conn.fetchone("SELECT retire_requested FROM agent_registry WHERE identity = ?", (identity,))
    return bool(row and row["retire_requested"])


def record_heartbeat(conn: Database, identity: str, metric: str = "heartbeat", value: str | None = None) -> None:
    """One heartbeat, recorded in two places, committed once.

    The registry carries *when* an agent last reported; `health_metrics`
    carries *that it did*, and `performance_card.heartbeat_count` reads the
    second. Written as two independent commits, a reader on another connection
    could land between them and see an agent that had heartbeated with a
    heartbeat count of zero - the two halves of one event disagreeing.

    Not theoretical: that is exactly how CI failed on a slow Windows runner
    while passing on Linux and on every developer machine. The window is a
    fraction of a millisecond on fast hardware, which is what kept it hidden.

    The transaction was added for the migration pipeline (§89); this is the
    first pre-existing bug it closes."""
    now = _now()
    with conn.transaction():
        conn.execute("UPDATE agent_registry SET last_heartbeat_at = ? WHERE identity = ?",
                     (now, identity))
        conn.execute(
            "INSERT INTO health_metrics (identity, timestamp, metric, value, schema_version) "
            "VALUES (?, ?, ?, ?, ?)",
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
    # A crash leaves a historical trace as well as changing current state.
    #
    # Without this the crash is only ever visible in `process_state`, which the
    # next respawn overwrites - so an agent that had crashed nine times was
    # indistinguishable from one that had never crashed, and operational
    # reliability could not be computed from the record at all. Found while
    # building the personnel generator, which could not gather evidence that was
    # never written down.
    conn.execute(
        "INSERT INTO health_metrics (identity, timestamp, metric, value, schema_version) "
        "VALUES (?, ?, 'crash', NULL, ?)",
        (identity, _now(), SCHEMA_VERSION),
    )


def count_pending_spawn_directives(conn: Database, role: str) -> int:
    return conn.fetchone(
        "SELECT COUNT(*) AS n FROM coo_directives WHERE directive_type = 'spawn' "
        "AND target_role = ? AND status = 'pending'",
        (role,),
    )["n"]


def recent_completed_spawns(conn: Database, role: str, within_seconds: float) -> list[dict]:
    """Spawns for this role completed recently enough that the agent may still
    be starting up.

    Bounded by time rather than by count. The question is "did a spawn happen
    that has not landed yet", and once several slots per role exist there is no
    fixed number of recent directives that answers it - a role staffed with
    three has three legitimate spawns in the same second.

    Filtered in Python rather than in SQL, and that is not a style choice.
    `completed_at` is written by the archive trigger as `...Z` while every
    Python-written timestamp ends `...+00:00`, so a string comparison between
    them is decided by 'Z' sorting after '+' whenever the prefixes match - which
    makes any same-instant directive compare as recent no matter what window is
    asked for. parse_timestamp exists precisely to reconcile the two formats."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=within_seconds)
    rows = conn.fetchall(
        "SELECT * FROM coo_directives_completed WHERE directive_type = 'spawn' "
        "AND target_role = ? AND outcome = 'success' ORDER BY completed_at",
        (role,),
    )
    # Strictly after the cutoff, not at-or-after. A zero-width window must
    # contain nothing, and `>=` made it contain whatever happened at the same
    # instant - which on Windows is almost everything, because two consecutive
    # `datetime.now()` calls return the identical value roughly 19,997 times in
    # 20,000. The archive trigger writes `completed_at` truncated to the second,
    # so a spawn completing early in a second compared equal to a cutoff taken
    # moments later and counted as still in flight.
    #
    # No practical change to the real window: an event exactly at the boundary
    # of a multi-second window is already the oldest thing in it, and the
    # duplicate-identity guard this feeds is unaffected.
    return [dict(row) for row in rows if parse_timestamp(row["completed_at"]) > cutoff]


def role_members(conn: Database, role: str) -> list[dict]:
    """Every agent ever created in this role, in slot order.

    Ordered by slot number rather than by string, so `analysis-10` sorts after
    `analysis-9` instead of before it - the kind of thing that stays invisible
    until a role reaches ten members and then allocates a slot that is already
    taken."""
    rows = [dict(row) for row in conn.fetchall("SELECT * FROM agent_registry WHERE role = ?", (role,))]
    return sorted(rows, key=lambda row: slot_number(row["identity"]))


def slot_number(identity: str) -> int:
    """The numeric slot in `role-N`, or 0 if the identity does not follow it."""
    _, _, suffix = identity.rpartition("-")
    return int(suffix) if suffix.isdigit() else 0


# How long a slot named by a completed spawn directive stays reserved while the
# process starts and registers. Must exceed process start plus first
# registration; below that, a second allocation hands out a slot that is already
# coming up.
SPAWN_LANDING_WINDOW_SECONDS = float(os.environ.get("FI_SPAWN_LANDING_WINDOW_SECONDS", "30"))


def slots_awaiting_registration(
    conn: Database, role: str, within_seconds: float | None = None
) -> set[str]:
    """Slots a spawn has already been issued for, which have not reported in yet.

    A slot is only visible in agent_registry once its process registers, and
    that takes a moment. In the gap the slot exists in no query - so a second
    allocation in the same moment hands out the identity that was just handed
    out, and two processes come up under one identity.

    Not hypothetical: staffing judgment with two agents for the first time
    produced exactly that. COO correctly asked for two, the Controller executed
    both before either had registered, and both were allocated `analysis-1`.
    The registry showed one row, so COO then asked for a third."""
    if within_seconds is None:
        within_seconds = SPAWN_LANDING_WINDOW_SECONDS

    awaiting = set()
    for directive in recent_completed_spawns(conn, role, within_seconds):
        identity = directive["detail"]
        if not identity:
            continue
        agent = get_agent(conn, identity)
        # Registered *for this attempt* - a permanent slot's row outlives every
        # process that ran under it, so mere existence proves nothing.
        if agent is None or parse_timestamp(agent["spawned_at"]) < parse_timestamp(directive["completed_at"]):
            awaiting.add(identity)
    return awaiting


def allocate_slot(conn: Database, role: str) -> str:
    """The identity the next process for this role should run under.

    One function for what are really two situations, because the caller cannot
    reliably tell them apart and getting it wrong is expensive in both
    directions:

    **Refilling a slot that already exists.** An active member whose process is
    not running - crashed, stopped, or waiting after a server restart - gets its
    own identity back. That is the whole point of a permanent slot: the agent
    returns with its name, assignment span and performance record intact rather
    than starting over. The lowest such slot is chosen so refills are
    deterministic.

    **Adding a slot.** Only when every active member already has a process does
    this issue a new one, numbered above the highest ever used. Numbering above
    the highest *ever* rather than the highest *current* matters - reusing a
    retired member's number would attach a new agent to another agent's history.

    Dormant members are never refilled here. Retirement is a decision the
    Controller took, and COO respawning into it would silently undo it.

    Slots already issued to a spawn that has not registered yet are skipped in
    both branches - see slots_awaiting_registration for the run that proved why."""
    members = role_members(conn, role)
    reserved = slots_awaiting_registration(conn, role)

    for member in members:
        if member["identity"] in reserved:
            continue
        if member["lifecycle_state"] == LIFECYCLE_ACTIVE and member["process_state"] != PROCESS_RUNNING:
            return member["identity"]

    highest = max(
        (slot_number(identity) for identity in
         [member["identity"] for member in members] + list(reserved)),
        default=0,
    )
    return f"{role}-{highest + 1}"


def staffing(conn: Database, role: str) -> dict:
    """How this role is staffed right now, in the terms COO decides from."""
    members = role_members(conn, role)
    return {
        "role": role,
        "members": len(members),
        "running": sum(
            1 for m in members
            if m["lifecycle_state"] == LIFECYCLE_ACTIVE and m["process_state"] == PROCESS_RUNNING
        ),
        "awaiting_process": sum(
            1 for m in members
            if m["lifecycle_state"] == LIFECYCLE_ACTIVE and m["process_state"] != PROCESS_RUNNING
        ),
        "dormant": sum(1 for m in members if m["lifecycle_state"] == LIFECYCLE_DORMANT),
    }


def record_liveness(conn: Database, identity: str) -> None:
    """The process is up. Says nothing about whether its work is moving.

    Separate from `record_heartbeat` because they answer different questions and
    conflating them cost a respawn (§133): a heartbeat only advances when a cycle
    returns, so an agent inside a single slow model call looked dead while it was
    working, and COO duplicated it.

    **The point of the separation is which clock the signal depends on.** A
    progress signal is bounded by the slowest model call, which a vendor sets. A
    liveness signal is bounded by an interval this system chooses, so the
    threshold above it can be justified against a rate this project controls -
    which is what `TIMING_CONSTANTS.md` asks of every constant and what the 45s
    threshold could not have.

    Deliberately not written to `health_metrics`. That table counts work reported;
    a thread ticking on a timer is not work, and inflating the count with it would
    make `performance_card.heartbeat_count` describe the clock instead of the
    agent."""
    conn.execute("UPDATE agent_registry SET last_liveness_at = ? WHERE identity = ?",
                 (_now(), identity))


def liveness_age_seconds(agent: dict) -> float | None:
    """Seconds since this agent last said it was up, or None if it never has."""
    if not agent.get("last_liveness_at"):
        return None
    return (datetime.now(timezone.utc)
            - parse_timestamp(agent["last_liveness_at"])).total_seconds()


def list_stale_active_agents(conn: Database, stale_seconds: float) -> list[dict]:
    """Agents believed to be running that have stopped signalling life.

    **Liveness, not progress** (TQ-93, §134). An agent that exits cleanly calls
    mark_process_stopped itself; one killed outright (SIGKILL, OOM, host crash)
    never reaches that code, so its row would claim 'running' forever unless
    something notices its signal stopped - this is that something.

    Judged on `last_liveness_at` where there is one, because that is the signal
    that means *the process is up*. An agent deep inside a slow model call is
    alive and not progressing, and marking it crashed on that basis is what
    §133's incident recorded COO doing.

    **An agent that emits no liveness is judged by progress, exactly as before.**
    Not every process runs the liveness thread - a test double, an older build, a
    future agent written differently - and falling back is the honest reading of
    *"the only signal it gives is the one it gives"*. It is also the conservative
    one: a silent process is still detected.

    Filters on process_state = 'running' rather than lifecycle: a dormant agent
    that has already stopped is not stale, it is retired, and flagging it as
    crashed would be plainly wrong."""
    rows = conn.fetchall("SELECT * FROM agent_registry WHERE process_state = ?", (PROCESS_RUNNING,))
    now = datetime.now(timezone.utc)
    stale = []
    for row in rows:
        reference = row["last_liveness_at"] or row["last_heartbeat_at"] or row["spawned_at"]
        if (now - parse_timestamp(reference)).total_seconds() >= stale_seconds:
            stale.append(row)
    return stale


def list_stalled_live_agents(conn: Database, stale_seconds: float) -> list[dict]:
    """Agents that are up and whose work has stopped moving.

    The state that had no name before TQ-93 and was being reported as a crash.
    An agent here is **not** a fault: a long model call puts a healthy Analysis
    agent in this list routinely, which is why COO reports it and does not act on
    it.

    Requires a liveness signal. Without one there is nothing to distinguish this
    from a crash, and inventing the distinction would be claiming knowledge the
    row does not carry."""
    rows = conn.fetchall("SELECT * FROM agent_registry WHERE process_state = ?", (PROCESS_RUNNING,))
    now = datetime.now(timezone.utc)
    stalled = []
    for row in rows:
        if not row["last_liveness_at"]:
            continue
        if (now - parse_timestamp(row["last_liveness_at"])).total_seconds() >= stale_seconds:
            continue  # not live; that is a crash and the other query owns it
        progress = row["last_heartbeat_at"] or row["spawned_at"]
        if (now - parse_timestamp(progress)).total_seconds() >= stale_seconds:
            stalled.append(row)
    return stalled


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


def observed_history(conn: Database, before_event_id: int | None = None) -> dict:
    """What the system had seen - the "current conceptual structure"
    constitution §8 asks novelty to be measured against.

    **`before_event_id` is not an optimisation, it is the correctness of the
    whole thing.** By the time a report reaches the queue its own detector event
    is already recorded, so a history built from everything includes the very
    observation being judged - the lead makes itself familiar, and nothing is
    ever novel. Found by running it: unit tests construct history explicitly and
    so never exhibit the off-by-one.

    Passing the candidate's own event id asks the honest question instead: what
    did the system know *before this arrived*?

    Assembled from the event tables rather than kept as a separate summary,
    because a cached structure could drift from the record it summarizes and
    novelty would then be measured against a fiction."""
    securities_seen, ratio_range = set(), {}
    peer_combinations = set()
    where = "WHERE id < ?" if before_event_id is not None else ""
    params = (before_event_id,) if before_event_id is not None else ()
    for event in conn.fetchall(
        f"SELECT security, ratio, peer_context FROM detector_events {where}", params
    ):
        securities_seen.add(event["security"])
        if event["ratio"] is not None:
            low, high = ratio_range.get(event["security"], (event["ratio"], event["ratio"]))
            ratio_range[event["security"]] = (min(low, event["ratio"]), max(high, event["ratio"]))
        if event["peer_context"]:
            co = json.loads(event["peer_context"]).get("co_triggering") or []
            if co:
                peer_combinations.add(",".join(sorted(co)))

    # Speculator-sourced leads never produce a detector event, so a security
    # only ever seen socially would otherwise read as never-observed forever.
    #
    # Deliberately *not* bounded by before_event_id: that is a detector_events
    # id, and evidence_items has an independent id space, so any cutoff
    # translated between them would be arbitrary rather than meaningful. The
    # consequence is that "first observation" is coarse - a security Speculator
    # saw in the same cycle already counts as seen when Explorer's lead is
    # judged. That makes the signal conservative, which is the right direction:
    # it under-reports novelty rather than inventing it, and the peer-combination
    # and ratio-range signals still fire on genuine first encounters.
    for row in conn.fetchall("SELECT DISTINCT security FROM evidence_items"):
        securities_seen.add(row["security"])

    outcomes = {
        row["outcome"] for row in conn.fetchall(
            "SELECT DISTINCT outcome FROM cross_check_requests WHERE outcome IS NOT NULL")
    }
    return {
        "securities_seen": securities_seen,
        "ratio_range": ratio_range,
        "peer_combinations": peer_combinations,
        "cross_check_outcomes": outcomes,
    }


def assess_report_novelty(conn: Database, report: dict, history: dict | None = None) -> dict:
    """Structural novelty for one queued report, from its detector event and
    cross-check if it has them.

    History is built excluding this report's own detector event - see
    observed_history. A caller supplying `history` is responsible for that
    exclusion itself; the default path does it correctly."""
    candidate = {"security": report["security"]}
    if report.get("detector_event_id"):
        event = get_detector_event(conn, report["detector_event_id"])
        if event:
            if history is None:
                history = observed_history(conn, before_event_id=report["detector_event_id"])
            candidate["ratio"] = event["ratio"]
            if event["peer_context"]:
                candidate["co_triggering"] = json.loads(event["peer_context"]).get("co_triggering")
    if history is None:
        history = observed_history(conn)
    if report.get("cross_check_id"):
        request = get_cross_check(conn, report["cross_check_id"])
        if request:
            candidate["cross_check_outcome"] = request["outcome"]
    return novelty.assess(candidate, history)


def get_directive(conn: Database, directive_id: int) -> dict | None:
    """A pending directive by id. Returns None once it completes - the archive
    trigger moves the row to coo_directives_completed, so absence here means
    "already executed", not "never existed"."""
    return conn.fetchone("SELECT * FROM coo_directives WHERE id = ?", (directive_id,))


def get_completed_directive(conn: Database, directive_id: int) -> dict | None:
    return conn.fetchone("SELECT * FROM coo_directives_completed WHERE id = ?", (directive_id,))


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
    # Scoped to requested_by='coo' as well as to spawns. COO evaluates *its
    # own* decisions; an operator-issued directive is not one, and grading it
    # as though it were would put someone else's choice on COO's record. A
    # no-op today, since COO is the only requester of spawns - but the UQI and
    # control panel opened the door to other requesters, and this is the guard
    # that keeps that door from quietly corrupting the decision history.
    rows = conn.fetchall(
        "SELECT * FROM coo_directives_completed "
        "WHERE directive_type = 'spawn' AND requested_by = 'coo' "
        "AND outcome = 'success' AND observed_result IS NULL "
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


# Every table where an agent's work is recorded against the slot it occupied,
# with the column naming that slot. attributed_work intersects these timestamps
# with an assignment span to answer "what did this agent do", without any of
# these rows referring to a name.
#
# discovery_reports and discovery_reports_completed are both listed on purpose:
# a report that has not been consumed yet is still work the producer did, and
# leaving the pending table out would make an agent's record shrink and grow as
# the queue drains.
WORK_PROVENANCE = (
    ("detector_events", "producer_identity"),
    ("evidence_items", "producer_identity"),
    ("discovery_reports", "producer_identity"),
    ("discovery_reports_completed", "producer_identity"),
    ("analysis_results", "producer_identity"),
    ("grades", "grader_identity"),
    # COO is the assessor (addendum 11 §8: the producer of an opportunity must
    # not be the judge of its risk), so assessed_by names COO's slot the same
    # way grader_identity names Analysis's.
    ("risk_assessments", "assessed_by"),
)


def _role_of(conn: Database, identity: str) -> str:
    """The role a slot belongs to, from the registry if it is known there.

    Falls back to the slot naming convention rather than failing: an assignment
    with an unknown role is still a true assignment, and refusing to record it
    would lose the history this table exists to keep."""
    row = conn.fetchone("SELECT role FROM agent_registry WHERE identity = ?", (identity,))
    if row is not None:
        return row["role"]
    return identity.rsplit("-", 1)[0] if "-" in identity else identity


def open_assignment(
    conn: Database,
    name: str,
    identity: str,
    role: str | None = None,
    reason: str | None = None,
    started_at: str | None = None,
) -> int:
    """Record that `name` now occupies `identity`.

    Raises if either party already holds an open assignment. The partial unique
    indexes would refuse it anyway; checking here turns an IntegrityError into a
    sentence that says which agent is already where.

    `started_at` exists for backdating a span to when the assignment actually
    began, which matters only on the backfill path - see _ensure_assignment."""
    held = current_assignment(conn, name=name)
    if held is not None:
        raise ValueError(
            f"{name!r} already holds {held['identity']!r}; reassign it rather than opening a second assignment"
        )
    occupant = current_assignment(conn, identity=identity)
    if occupant is not None:
        raise ValueError(
            f"{identity!r} is already occupied by {occupant['name']!r}. Moving {name!r} there means "
            "moving them out first - a swap is two reassignments, and doing it implicitly would "
            "silently evict an agent."
        )
    return conn.execute_returning_id(
        "INSERT INTO agent_assignments (agent_id, name, identity, role, started_at, ended_at, "
        "reason, schema_version) VALUES (?, ?, ?, ?, ?, NULL, ?, ?)",
        (agent_id_for_name(conn, name), name, identity, role or _role_of(conn, identity),
         started_at or _now(), reason, SCHEMA_VERSION),
    )


def reassign_agent_name(conn: Database, name: str, identity: str, reason: str | None = None) -> dict:
    """Move an agent to a different slot, closing the span it is leaving.

    The transfer of §10: Alex begins as Explorer and later becomes Analyst
    without becoming a second agent. Both spans survive, so work done under
    either remains attributable to the span that contained it.

    Deliberately NOT reachable from register_agent. A respawn must never be able
    to trigger a move - assign_agent_name stays idempotent, and this is the only
    other writer of assigned_to_identity."""
    row = conn.fetchone("SELECT name FROM agent_names WHERE name = ?", (name,))
    if row is None:
        raise ValueError(f"no agent named {name!r}")

    held = current_assignment(conn, name=name)
    if held is not None and held["identity"] == identity:
        return held

    occupant = current_assignment(conn, identity=identity)
    if occupant is not None:
        raise ValueError(
            f"{identity!r} is already occupied by {occupant['name']!r}; move them out first"
        )

    if held is not None:
        conn.execute(
            "UPDATE agent_assignments SET ended_at = ?, reason = COALESCE(reason, ?) "
            "WHERE id = ? AND ended_at IS NULL",
            (_now(), reason, held["id"]),
        )

    conn.execute(
        "UPDATE agent_names SET assigned_to_identity = ?, assigned_at = ? WHERE name = ?",
        (identity, _now(), name),
    )
    open_assignment(conn, name, identity, reason=reason)
    return current_assignment(conn, name=name)


def current_assignment(
    conn: Database, identity: str | None = None, name: str | None = None
) -> dict | None:
    """The open span for a slot or an agent, or None if there is none."""
    if (identity is None) == (name is None):
        raise ValueError("pass exactly one of identity or name")
    column, value = ("identity", identity) if identity is not None else ("name", name)
    row = conn.fetchone(
        f"SELECT * FROM agent_assignments WHERE {column} = ? AND ended_at IS NULL", (value,)
    )
    return dict(row) if row else None


def assignment_history(conn: Database, name: str) -> list[dict]:
    """Every span this agent has held, oldest first. The open one is last.

    **Read through the durable id where there is one** (TQ-99), so an agent that
    was renamed keeps one continuous history instead of two partial ones under
    two names. Falls back to the name for a database whose spans have not been
    backfilled yet - which is the state until that agent next registers, and
    returning nothing in the meantime would lose the history rather than defer
    it."""
    agent_id = agent_id_for_name(conn, name)
    if agent_id:
        return [dict(row) for row in conn.fetchall(
            "SELECT * FROM agent_assignments WHERE agent_id = ? ORDER BY started_at, id",
            (agent_id,))]
    return [
        dict(row)
        for row in conn.fetchall(
            "SELECT * FROM agent_assignments WHERE name = ? ORDER BY started_at, id", (name,)
        )
    ]


def attributed_work(conn: Database, name: str) -> dict:
    """What this agent produced, counted per work table across all of its spans.

    A row counts when its producer was the slot and its timestamp fell inside a
    span this agent held. Half-open on purpose - `started_at <= t < ended_at` -
    so a row written at the exact instant of a transfer belongs to exactly one
    span rather than to both or to neither."""
    spans = assignment_history(conn, name)
    counts = {table: 0 for table, _ in WORK_PROVENANCE}
    for span in spans:
        for table, column in WORK_PROVENANCE:
            row = conn.fetchone(
                f"SELECT COUNT(*) AS n FROM {table} "
                f"WHERE {column} = ? AND created_at >= ? AND (? IS NULL OR created_at < ?)",
                (span["identity"], span["started_at"], span["ended_at"], span["ended_at"]),
            )
            counts[table] += row["n"]
    counts["total"] = sum(counts.values())
    return counts


def personnel_record(conn: Database, name: str) -> dict | None:
    """The personnel folder: who this agent is, where it sits, where it has sat,
    and what it produced along the way.

    The two layers are kept apart rather than merged. `current` is what is true
    now and changes; `history` and `work` are what happened and do not. Neither
    overwrites the other, which is the same discipline intelligence_artifacts and
    knowledge_records already follow.

    Qualifications, commendations, competency profiles and rankings are
    deliberately absent: nothing awards them yet. Returning empty lists for them
    would present a capability that does not exist."""
    row = conn.fetchone("SELECT * FROM agent_names WHERE name = ?", (name,))
    if row is None:
        return None

    current = current_assignment(conn, name=name)
    agent = get_agent(conn, current["identity"]) if current else None

    return {
        "name": name,
        # The durable key (TQ-99). A folder identified only by a name is one that
        # a rename splits in two, which is why addendum 51 §3 asks for an
        # identifier independent of the display name.
        "agent_id": row["agent_id"],
        "current": {
            "identity": current["identity"] if current else None,
            "role": current["role"] if current else None,
            "since": current["started_at"] if current else None,
            # Dormancy does not vacate the desk, so an agent can hold an
            # assignment while not being in service. Both facts are reported.
            "lifecycle_state": agent["lifecycle_state"] if agent else None,
            "process_state": agent["process_state"] if agent else None,
        },
        "history": assignment_history(conn, name),
        "work": attributed_work(conn, name),
    }


PERSONNEL_EVENT_KINDS = (
    "qualification_granted",
    "qualification_revoked",
    "rank_achieved",
    "commendation",
)


def record_personnel_event(
    conn: Database,
    name: str,
    event_kind: str,
    subject: str,
    recorded_by: str,
    detail: str | None = None,
    evidence: dict | None = None,
    occurred_at: str | None = None,
) -> int:
    """Append one fact to an agent's personnel history.

    `recorded_by` is required, and deliberately: a personnel record whose
    entries have no author cannot be argued with later. `evidence` carries the
    numbers the judgment rested on, so a grant can be re-examined against what
    was actually known at the time rather than against what is known now."""
    if event_kind not in PERSONNEL_EVENT_KINDS:
        raise ValueError(f"unknown personnel event kind {event_kind!r}; expected one of {PERSONNEL_EVENT_KINDS}")
    return conn.execute_returning_id(
        "INSERT INTO personnel_events (name, event_kind, subject, detail, evidence, occurred_at, "
        "recorded_by, schema_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            name, event_kind, subject, detail,
            json.dumps(evidence) if evidence is not None else None,
            occurred_at or _now(), recorded_by, SCHEMA_VERSION,
        ),
    )


def personnel_events_for(conn: Database, name: str) -> list[dict]:
    """This agent's history, oldest first - the order commendation rules read it in."""
    return [
        dict(row)
        for row in conn.fetchall(
            "SELECT * FROM personnel_events WHERE name = ? ORDER BY occurred_at, id", (name,)
        )
    ]


def competency_evidence(conn: Database, name: str, window_days: float | None = None) -> dict:
    """Gather what is known about an agent's demonstrated capability.

    Grades attach to the *report* rather than to its producer, so this runs
    grades -> discovery_reports_completed -> producer_identity, intersected with
    the assignment spans this agent held. The intersection is what makes the
    answer right after a transfer: work done at a desk before this agent sat at
    it belongs to whoever did sit there.

    **Two dimensions cannot be gathered, and are returned empty rather than
    guessed.** Nothing records whether a stated confidence turned out to be
    right, so `calibration` is always empty in production - see the lifecycle
    catalogue, where that is recorded as an event with no defined response.
    Crashes are gathered from health_metrics, which only began recording them
    when this function needed them, so early history undercounts."""
    spans = assignment_history(conn, name)
    cutoff = None
    if window_days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()

    grades: list[dict] = []
    sessions = 0
    crashes = 0
    cross_check_responses: list[dict] = []
    uqi_responses: list[dict] = []

    for span in spans:
        start = max(span["started_at"], cutoff) if cutoff else span["started_at"]
        end = span["ended_at"]
        # Collaboration evidence (TQ-17, SPEC_RECONCILIATION §65): the
        # requests this desk was on duty for. Cross-checks are addressed to a
        # ROLE, so attribution is by the span's role and the request's
        # created_at falling inside the span - the same half-open tenure rule
        # attributed_work uses; a request created during this tenure but
        # answered after a transfer still belongs to this desk's record,
        # because the duty was assigned while it sat here. Only terminal
        # rows count: an in-flight request is not yet evidence of anything.
        # Normalized to {'answered': bool} here rather than in
        # backend/competency.py, because the status vocabulary is this
        # module's to own - 'no_evidence' IS an answer (the constant block's
        # own words: a responder that looked and found nothing has said
        # something informative); 'unanswered' means nobody ever replied
        # before the timeout, which folds responsiveness-in-time into the
        # rate without a separate latency score.
        cross_check_responses.extend(
            {"answered": row["outcome"] in (CROSS_CHECK_EVIDENCE, CROSS_CHECK_NO_EVIDENCE)}
            for row in conn.fetchall(
                "SELECT outcome FROM cross_check_requests WHERE responder_role = ? "
                "AND outcome IS NOT NULL AND created_at >= ? AND (? IS NULL OR created_at < ?)",
                (span["role"], start, end, end),
            )
        )
        # UQI questions name an identity directly, so no role indirection.
        uqi_responses.extend(
            {"answered": row["status"] == UQI_ANSWERED}
            for row in conn.fetchall(
                "SELECT status FROM uqi_requests WHERE target_identity = ? AND status != ? "
                "AND created_at >= ? AND (? IS NULL OR created_at < ?)",
                (span["identity"], UQI_PENDING, start, end, end),
            )
        )
        grades.extend(
            dict(row)
            for row in conn.fetchall(
                "SELECT g.overall_score, g.evidence_quality_score, g.novelty_score, g.worth_the_compute "
                "FROM grades g JOIN discovery_reports_completed r ON g.report_id = r.id "
                "WHERE r.producer_identity = ? AND r.created_at >= ? "
                "AND (? IS NULL OR r.created_at < ?)",
                (span["identity"], start, end, end),
            )
        )
        sessions += conn.fetchone(
            "SELECT COUNT(*) AS n FROM coo_directives_completed "
            "WHERE directive_type = 'spawn' AND outcome = 'success' AND detail = ? "
            "AND completed_at >= ? AND (? IS NULL OR completed_at < ?)",
            (span["identity"], start, end, end),
        )["n"]
        crashes += conn.fetchone(
            "SELECT COUNT(*) AS n FROM health_metrics WHERE identity = ? AND metric = 'crash' "
            "AND timestamp >= ? AND (? IS NULL OR timestamp < ?)",
            (span["identity"], start, end, end),
        )["n"]

    # An agent that registered without a spawn directive - the Controller and
    # COO bootstrap themselves - has still had one session.
    if sessions == 0 and spans:
        sessions = 1

    return {
        "grades": grades,
        "calibration": [],
        "sessions": sessions,
        "crashes": crashes,
        "cross_check_responses": cross_check_responses,
        "uqi_responses": uqi_responses,
        "window_days": window_days,
    }


def competency_profile(conn: Database, name: str, window_days: float | None = None) -> dict:
    """Gather, then judge. The judging lives in backend/competency.py."""
    return competency.profile(competency_evidence(conn, name, window_days))


def rank_role(conn: Database, role: str, dimension: str, window_days: float | None = None) -> list[dict]:
    """Rank the agents currently assigned to one role, on one dimension.

    Scoped to a role because a ranking across roles would compare agents doing
    different work - which is the unexplained universal score the owner decision
    rules out."""
    names = [
        row["name"]
        for row in conn.fetchall(
            "SELECT name FROM agent_assignments WHERE role = ? AND ended_at IS NULL ORDER BY name",
            (role,),
        )
    ]
    profiles = {name: competency_profile(conn, name, window_days) for name in names}
    return competency.rank(profiles, dimension)


def list_personnel(conn: Database) -> list[dict]:
    return [
        personnel_record(conn, row["name"])
        for row in conn.fetchall(
            "SELECT name FROM agent_names WHERE assigned_to_identity IS NOT NULL ORDER BY name"
        )
    ]


def assign_agent_name(conn: Database, identity: str, role: str | None = None) -> str | None:
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
        # Backfill path as well as the respawn path. A database created before
        # agent_assignments existed has bindings but no spans, and this is where
        # they acquire one - on the next registration, without a migration step.
        # TQ-99 adds the second backfill for the same reason: bindings older than
        # `agent_identities` acquire their durable id here.
        _ensure_identity(conn, existing["name"])
        _ensure_assignment(conn, existing["name"], identity, role)
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
    if confirmed is None:
        return None
    _ensure_identity(conn, confirmed["name"])
    _ensure_assignment(conn, confirmed["name"], identity, role)
    return confirmed["name"]


def _ensure_identity(conn: Database, name: str) -> str:
    """Give this name's agent a durable id, if it does not have one yet (TQ-99).

    **The correction TQ-97 deferred for one increment and owed for five.** That
    increment introduced `agent_id` *beside* `agent_names` rather than under it,
    so two answers to "which is the durable agent" coexisted - the state addendum
    47 §5 forbids, and §122 spent a whole increment undoing three cases of.

    Backdated to when the name was actually bound, never to now. The reason is
    `_ensure_assignment`'s, one layer along: an identity created at backfill time
    would report every agent as having come into existence the moment somebody
    restarted the system, and the creation date is exactly the fact a persistent
    identity exists to carry (addendum 51 §5).

    Idempotent, and it has to be: this runs on every registration and every
    respawn."""
    from backend import agent_identity

    row = conn.fetchone("SELECT agent_id, assigned_at FROM agent_names WHERE name = ?", (name,))
    if row is None:
        raise ValueError(f"no agent named {name!r}")
    if row["agent_id"]:
        return row["agent_id"]

    agent_id = agent_identity.ensure_for_name(conn, name, created_at=row["assigned_at"])
    conn.execute("UPDATE agent_names SET agent_id = ? WHERE name = ?", (agent_id, name))
    # Spans and personnel events written before this column existed belong to the
    # same agent. Stamped here rather than left NULL, because a history half
    # keyed by id and half by name is the drift this increment exists to end.
    for table in ("agent_assignments", "personnel_events"):
        conn.execute(f"UPDATE {table} SET agent_id = ? WHERE name = ? AND agent_id IS NULL",
                     (agent_id, name))
    return agent_id


def agent_id_for_name(conn: Database, name: str) -> str | None:
    """The durable id behind a name, or None if the name is unheld.

    The one resolver. Callers that hold a name and need the agent go through
    this rather than joining `agent_names` themselves, so there is one place the
    two are related."""
    row = conn.fetchone("SELECT agent_id FROM agent_names WHERE name = ?", (name,))
    return row["agent_id"] if row and row["agent_id"] else None


def _ensure_assignment(conn: Database, name: str, identity: str, role: str | None) -> None:
    """Open this agent's first assignment span, if it has none.

    Idempotent, and it has to be: register_agent runs on every spawn AND every
    respawn, and a respawn that opened a second span would read as a transfer
    the agent never made. The span is what the personnel history is built from,
    so a spurious one is not a cosmetic error - it would split one agent's
    record in two."""
    if current_assignment(conn, name=name) is not None:
        return
    if current_assignment(conn, identity=identity) is not None:
        # The desk is held by a different name. Reaching here means the binding
        # in agent_names disagrees with the open span, which reassign_agent_name
        # keeps consistent - so do nothing rather than evict anyone, and leave
        # the disagreement visible.
        return

    # **Backdated to when the name was actually bound, not to now.** On a
    # database that predates this table the binding is old and the span is new,
    # and a span starting at backfill time would place every hour of prior work
    # outside every span - attributed to nobody. Measured against the real
    # database at the time this was written: 188 detector events, 361 evidence
    # items, four completed reports and four grades, all orphaned, in a table
    # whose entire purpose is that the history survives.
    binding = conn.fetchone("SELECT assigned_at FROM agent_names WHERE name = ?", (name,))
    started_at = binding["assigned_at"] if binding else None

    open_assignment(
        conn, name, identity, role=role, started_at=started_at,
        reason="initial assignment on registration",
    )


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


def propose_artifact_revision(
    conn: Database,
    name: str,
    value,
    rationale: str,
    proposed_by: str,
    evidence_ref: str | None = None,
) -> int:
    """The Trainer's act, with a human in the Trainer's seat until Phase D
    builds one. A proposal is a fact about what someone believed should
    change and why - which is why a rejected one is kept, not deleted.

    Refuses three ways, each because the refused thing would corrupt the
    succession chain rather than merely be untidy: a revision to a name that
    never existed is not a revision at all (record_intelligence_artifact is
    the function for a new name); a revision with no rationale is a magic
    number changing, which is exactly what validity_conditions and staleness
    exist to prevent; and a second open proposal for a name that already has
    one would leave adopt_artifact_revision no way to know which candidate
    the adjudication was even about."""
    prior = conn.fetchone(
        "SELECT * FROM intelligence_artifacts WHERE name = ? ORDER BY version DESC LIMIT 1",
        (name,),
    )
    if prior is None:
        raise ValueError(
            f"no artifact named {name!r} has ever existed; a revision revises something - "
            "use record_intelligence_artifact for a new name"
        )
    if not rationale or not rationale.strip():
        raise ValueError("a revision without a rationale is a magic number changing")
    existing_proposal = conn.fetchone(
        "SELECT id FROM intelligence_artifacts WHERE name = ? AND status = 'proposed'",
        (name,),
    )
    if existing_proposal is not None:
        raise ValueError(
            f"an open proposal already exists for {name!r} (id {existing_proposal['id']}); "
            "adjudicate it before proposing another"
        )

    if evidence_ref:
        rationale = f"{rationale}\n\nEvidence: {evidence_ref}"

    return conn.execute_returning_id(
        "INSERT INTO intelligence_artifacts "
        "(created_at, artifact_kind, name, version, value, rationale, validity_conditions, status, "
        "producer_identity, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?)",
        (
            _now(), prior["artifact_kind"], name, prior["version"] + 1, json.dumps(value), rationale,
            # Carried forward, not re-derived: a revision proposes a new value,
            # not new validity semantics. Changing what would invalidate a lens
            # is a different act from changing the lens.
            prior["validity_conditions"],
            proposed_by, SCHEMA_VERSION,
        ),
    )


def adopt_artifact_revision(conn: Database, revision_id: int, adopted_by: str) -> dict:
    """Adoption supersedes the stale predecessor, which completes the cycle
    expiry started: active -> stale -> superseded-by-a-successor. From the
    next agent cycle get_active_artifact resolves the new version - no agent
    restart, no config edit."""
    revision = conn.fetchone("SELECT * FROM intelligence_artifacts WHERE id = ?", (revision_id,))
    if revision is None or revision["status"] != "proposed":
        status = revision["status"] if revision is not None else "nonexistent"
        raise ValueError(f"only a proposed revision can be adopted; this one is {status}")

    conn.execute("UPDATE intelligence_artifacts SET status = 'active' WHERE id = ?", (revision_id,))
    predecessors = conn.fetchall(
        "SELECT id FROM intelligence_artifacts WHERE name = ? AND status IN ('active', 'stale') AND id != ?",
        (revision["name"], revision_id),
    )
    for predecessor in predecessors:
        supersede_artifact(conn, predecessor["id"], revision_id)

    conn.execute(
        "UPDATE intelligence_artifacts SET rationale = rationale || ? WHERE id = ?",
        (f"\n\nAdopted by {adopted_by}.", revision_id),
    )
    return conn.fetchone("SELECT * FROM intelligence_artifacts WHERE id = ?", (revision_id,))


def reject_artifact_revision(conn: Database, revision_id: int, rejected_by: str, reason: str) -> None:
    """Declines a proposal without discarding it. A rejection is adjudication,
    and adjudication without a reason on the record teaches nothing to
    whoever reads this later - Trainer or human."""
    revision = conn.fetchone("SELECT * FROM intelligence_artifacts WHERE id = ?", (revision_id,))
    if revision is None or revision["status"] != "proposed":
        status = revision["status"] if revision is not None else "nonexistent"
        raise ValueError(f"only a proposed revision can be rejected; this one is {status}")
    if not reason or not reason.strip():
        raise ValueError("a rejection without a reason teaches nothing")

    conn.execute(
        "UPDATE intelligence_artifacts SET status = 'rejected', rationale = rationale || ? WHERE id = ?",
        (f"\n\nRejected by {rejected_by}: {reason}", revision_id),
    )


def list_artifact_revisions(conn: Database, name: str) -> list[dict]:
    """The succession chain - what the value was, what it became, who changed
    it and why. This is the manifesto §12 transformation record: preserved
    change, not a new record kind."""
    return conn.fetchall(
        "SELECT * FROM intelligence_artifacts WHERE name = ? ORDER BY version DESC",
        (name,),
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


# --- Agent self-description (addendum 14 §6) ---


def heartbeat_age_seconds(agent: dict) -> float | None:
    """Seconds since this agent last reported. None if it has never reported."""
    if not agent.get("last_heartbeat_at"):
        return None
    return (datetime.now(timezone.utc) - parse_timestamp(agent["last_heartbeat_at"])).total_seconds()


def seconds_since(timestamp: str | None) -> float | None:
    """Seconds since a recorded moment, or None if there is no moment.

    Sits beside heartbeat_age_seconds because a watcher needs both: how long ago
    an agent last *reported*, and how long ago it was *started*. An agent that has
    never reported is a failure or a startup depending entirely on the second
    question."""
    if not timestamp:
        return None
    return (datetime.now(timezone.utc) - parse_timestamp(timestamp)).total_seconds()


def describe_agent(conn: Database, identity: str, stale_after_seconds: float = 45.0) -> dict | None:
    """Answers addendum 14 §6's fifteen questions for one agent.

    Deterministic and sourced entirely from the organizational record plus the
    role's charter. §6 asks for operational self-awareness - identity, role,
    responsibilities, permissions, state - and explicitly excludes
    "unrestricted introspection into hidden model internals", so there is
    nothing here a model could get wrong.

    Two things worth reading carefully:

    - `healthy` is derived from heartbeat age, so it reflects the *process*,
      not the row. An agent whose row says active but whose heartbeat is stale
      reports unhealthy, which is the honest answer.
    - `working` is deliberately coarse. The system records heartbeats, not task
      spans, so the most this can truthfully say is whether the agent has
      reported recently. Claiming to know which task is in flight would be a
      fabrication; `current_task` stays None until work spans are recorded.

    A live-answered version, where the agent's own process replies rather than
    the database being read on its behalf, is what the UQI adds. This is the
    organizational record - accurate, but not the agent speaking."""
    agent = get_agent(conn, identity)
    if agent is None:
        return None

    charter = ROLE_CHARTERS.get(agent["role"], {})
    age = heartbeat_age_seconds(agent)
    dormant = agent["lifecycle_state"] == LIFECYCLE_DORMANT
    healthy = (
        None if dormant
        else (age is not None and age < stale_after_seconds and agent["process_state"] == PROCESS_RUNNING)
    )
    name_row = conn.fetchone("SELECT name FROM agent_names WHERE assigned_to_identity = ?", (identity,))

    return {
        "identity": identity,
        "agent_name": name_row["name"] if name_row else None,
        "role": agent["role"],
        "agent_type": charter.get("agent_type"),
        "description": charter.get("description"),
        "responsibilities": charter.get("responsibilities", []),
        "allowed": charter.get("allowed", []),
        "not_allowed": charter.get("not_allowed", []),
        "competencies": charter.get("competencies", []),
        "work_mechanism": charter.get("work_mechanism"),
        # What this role owes a piece of work before delivering it (Iterative
        # Excellence §5, §10). Derived from the role rather than stored on the
        # charter so there is one definition - and surfaced here so an agent asked
        # what it is can state its own standard, which is what "agents inherit it
        # by default" has to mean if it means anything.
        "iteration": iteration.budget_for(agent["role"]),
        "lifecycle_state": agent["lifecycle_state"],
        "process_state": agent["process_state"],
        "healthy": healthy,
        "working": None if dormant else (age is not None and age < stale_after_seconds),
        # Not knowable from a heartbeat. Left null rather than guessed.
        "current_task": None,
        "pid": agent["pid"],
        "spawned_at": agent["spawned_at"],
        "last_heartbeat_at": agent["last_heartbeat_at"],
        "heartbeat_age_seconds": None if age is None else round(age, 2),
        "retire_requested": bool(agent["retire_requested"]),
        "schema_version": SCHEMA_VERSION,
    }


# --- The knowledge store (constitution §3, addendum 13 §9) ---

KNOWLEDGE_LESSON = "lesson"
KNOWLEDGE_OPEN_QUESTION = "open_question"
# Something that must be fixed, raised by the compliance check.
#
# A record kind rather than a table: knowledge_records already carries a
# statement, its evidence, who raised it, and closure with a trace of what closed
# it - which is the whole of what a corrective item needs. `resolve_knowledge`
# and `supersede_knowledge` already distinguish "was settled" from "was wrong",
# and corrective work needs exactly that distinction.
KNOWLEDGE_CORRECTIVE = "corrective_action"

KNOWLEDGE_ACTIVE = "active"
KNOWLEDGE_SUPERSEDED = "superseded"
KNOWLEDGE_RESOLVED = "resolved"


def record_knowledge(
    conn: Database,
    record_kind: str,
    statement: str,
    recorded_by: str,
    subject: str | None = None,
    rationale: str | None = None,
    evidence_ref: str | None = None,
    confidence: float | None = None,
) -> int:
    """Write down something the organization now believes, or now knows it does
    not know.

    `recorded_by` is required rather than optional. A lesson from COO's health
    check and one from a human are different claims, and a knowledge base that
    could not say which is which would be a pile of assertions."""
    return conn.execute_returning_id(
        "INSERT INTO knowledge_records "
        "(created_at, record_kind, subject, statement, rationale, recorded_by, evidence_ref, "
        "confidence, status, schema_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            _now(), record_kind, subject, statement, rationale, recorded_by,
            evidence_ref, confidence, KNOWLEDGE_ACTIVE, SCHEMA_VERSION,
        ),
    )


def knowledge_exists(conn: Database, record_kind: str, statement: str) -> bool:
    """Whether this exact statement is already on the books and still active.

    The guard against a knowledge base that "learns" the same thing every cycle.
    COO re-evaluates lens health continuously; without this, one stale lens
    would generate an identical lesson every second until the store was noise."""
    row = conn.fetchone(
        "SELECT 1 FROM knowledge_records WHERE record_kind = ? AND statement = ? AND status = ?",
        (record_kind, statement, KNOWLEDGE_ACTIVE),
    )
    return row is not None


def supersede_knowledge(conn: Database, record_id: int, replacement_id: int | None = None) -> None:
    """Mark a record as no longer believed, optionally pointing at what replaced
    it. Never deletes: a belief that turned out wrong is itself knowledge, and
    the trail from it to its replacement is the part worth keeping (addendum 13
    §9 - "whether later evidence changed it")."""
    conn.execute(
        "UPDATE knowledge_records SET status = ?, superseded_by = ?, resolved_at = ? WHERE id = ?",
        (KNOWLEDGE_SUPERSEDED, replacement_id, _now(), record_id),
    )


def resolve_knowledge(conn: Database, record_id: int, resolved_by_ref: str | None = None) -> None:
    """Close an open question that has been answered. Distinct from superseded:
    a resolved question was settled, a superseded belief was wrong.

    `resolved_by_ref` points at what answered it. Guarded on status so a
    question is only ever closed once - two agents reaching the same conclusion
    concurrently must not overwrite the record of which one actually did it."""
    conn.execute(
        "UPDATE knowledge_records SET status = ?, resolved_at = ?, resolved_by_ref = ? "
        "WHERE id = ? AND status = ?",
        (KNOWLEDGE_RESOLVED, _now(), resolved_by_ref, record_id, KNOWLEDGE_ACTIVE),
    )


def list_knowledge(
    conn: Database, record_kind: str | None = None, subject: str | None = None,
    status: str | None = KNOWLEDGE_ACTIVE, limit: int = 50,
) -> list[dict]:
    """Newest first. `status=None` includes superseded and resolved records -
    the history is queryable, not just the current view."""
    clauses, params = [], []
    for column, value in (("record_kind", record_kind), ("subject", subject), ("status", status)):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return conn.fetchall(
        f"SELECT * FROM knowledge_records {where} ORDER BY id DESC LIMIT ?", (*params, limit)
    )


def open_questions_for(conn: Database, subject: str, limit: int = 5) -> list[dict]:
    """Unresolved questions previously raised about this subject.

    The store's first real consumer: Analysis sees what the organization already
    wondered about a security before reasoning about it again. This is the thin
    end of "agreement licenses execution; it does not terminate thought" - a
    conclusion reached once leaves a question behind, and the question outlives
    the analysis that raised it."""
    return conn.fetchall(
        "SELECT * FROM knowledge_records WHERE record_kind = ? AND subject = ? AND status = ? "
        "ORDER BY id DESC LIMIT ?",
        (KNOWLEDGE_OPEN_QUESTION, subject, KNOWLEDGE_ACTIVE, limit),
    )


# --- Source reliability (constitution §3, Axiom 3) ---

# Graded contributions a source needs before its standing is stated at all.
# Below this, `stated` is False - "not yet known" is a different answer from
# "unreliable" and callers must not collapse them.
MIN_GRADED_CONTRIBUTIONS = int(os.environ.get("FI_MIN_GRADED_CONTRIBUTIONS", "5"))


def recompute_source_reliability(conn: Database) -> int:
    """Rebuild every source's standing from the grades of reports its evidence
    contributed to. Returns the number of sources with a stated standing.

    Recomputed from the full grade history rather than folded in incrementally.
    An EWMA would be cheaper, but a source's standing is a claim about its whole
    record, and recomputing makes that claim exactly reproducible from the
    evidence rather than dependent on the order updates happened to arrive in.
    Affordable at this volume; if the grade table ever outgrows it, that is the
    moment to reach for an incremental estimate, not before.

    Attribution runs grades -> completed report -> evidence_ids -> evidence
    items -> source. A report draws on several evidence items and therefore
    credits several sources with the same grade, which is correct: they jointly
    produced the thing that was judged, and no finer attribution is available
    without asking the grader which item persuaded it."""
    rows = conn.fetchall(
        "SELECT r.evidence_ids, g.evidence_quality_score, g.overall_score "
        "FROM grades g JOIN discovery_reports_completed r ON g.report_id = r.id "
        "WHERE r.evidence_ids IS NOT NULL AND r.evidence_ids != '[]'"
    )
    if not rows:
        return 0

    evidence_source = {
        item["id"]: item["source"]
        for item in conn.fetchall("SELECT id, source FROM evidence_items WHERE source IS NOT NULL")
    }

    quality: dict[str, list[float]] = {}
    overall: dict[str, list[float]] = {}
    for row in rows:
        for evidence_id in json.loads(row["evidence_ids"] or "[]"):
            source = evidence_source.get(evidence_id)
            if source is None:
                continue
            if row["evidence_quality_score"] is not None:
                quality.setdefault(source, []).append(row["evidence_quality_score"])
            if row["overall_score"] is not None:
                overall.setdefault(source, []).append(row["overall_score"])

    stated = 0
    for source in set(quality) | set(overall):
        scores = quality.get(source, [])
        overalls = overall.get(source, [])
        count = max(len(scores), len(overalls))
        conn.execute(
            "INSERT INTO source_reliability (source, graded_contributions, mean_evidence_quality, "
            "mean_overall_score, updated_at, schema_version) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(source) DO UPDATE SET graded_contributions=excluded.graded_contributions, "
            "mean_evidence_quality=excluded.mean_evidence_quality, "
            "mean_overall_score=excluded.mean_overall_score, updated_at=excluded.updated_at",
            (
                source, count,
                round(sum(scores) / len(scores), 4) if scores else None,
                round(sum(overalls) / len(overalls), 4) if overalls else None,
                _now(), SCHEMA_VERSION,
            ),
        )
        if count >= MIN_GRADED_CONTRIBUTIONS:
            stated += 1
    return stated


def list_source_reliability(conn: Database) -> list[dict]:
    """Every source's standing, best first. Sources below the evidence
    threshold are included with `stated` False rather than hidden - "we do not
    know yet" is a different answer from "this source is unreliable", and
    collapsing them would misrepresent both."""
    rows = conn.fetchall("SELECT * FROM source_reliability ORDER BY mean_evidence_quality DESC")
    return [
        {**row, "stated": row["graded_contributions"] >= MIN_GRADED_CONTRIBUTIONS}
        for row in rows
    ]


def source_standing(conn: Database, source: str) -> dict | None:
    """One source's standing, or None if it has none yet."""
    row = conn.fetchone("SELECT * FROM source_reliability WHERE source = ?", (source,))
    if row is None:
        return None
    return {**row, "stated": row["graded_contributions"] >= MIN_GRADED_CONTRIBUTIONS}


# --- Universal Human Query Interface (addendum 14 §7) ---

UQI_PENDING = "pending"
UQI_ANSWERED = "answered"
UQI_UNANSWERED = "unanswered"

# How long a question waits before the asker is told nobody replied.
#
# **Must exceed the slowest agent's work cycle plus its answer time.** An agent
# answers a UQI question only after finishing the work cycle it is in
# (agents/base.py), so the wait is a full cycle of that agent's work plus one
# model call of its own. Measured against a real backend: coo/explorer/
# speculator answer in 2-4s, but analysis-1 - whose cycle is a deep-reasoning
# call - took 5.8s, 19.4s and 24.0s across three samples.
#
# The first value tried was 15s, which turned two of those three into
# 'unanswered'. That is worse than a slow answer: an operator would read it as
# "Analysis is unresponsive" when Analysis was working perfectly, and
# 'unanswered' is supposed to be a genuine health finding rather than a
# rendering of impatience.
#
# 60s costs little, because this is not the system's liveness signal. Death is
# detected from heartbeat age - HEALTH_STALE_THRESHOLD_SECONDS, surfaced in the
# roster every couple of seconds - so a generous question timeout delays no
# diagnosis that matters.
UQI_TIMEOUT_SECONDS = float(os.environ.get("FI_UQI_TIMEOUT_SECONDS", "60"))


def ask_agent(conn: Database, asked_by: str, target_identity: str, question: str) -> int:
    """Put a question to one agent. Returns the request id to poll on."""
    return conn.execute_returning_id(
        "INSERT INTO uqi_requests (created_at, asked_by, target_identity, question, status, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (_now(), asked_by, target_identity, question, UQI_PENDING, SCHEMA_VERSION),
    )


def fetch_next_uqi_request(conn: Database, identity: str) -> dict | None:
    """The oldest unanswered question addressed to *this* agent.

    Scoped by target_identity, not by role: the UQI addresses one agent, and a
    sibling in the same role answering on its behalf would defeat the point of
    asking a specific process."""
    return conn.fetchone(
        "SELECT * FROM uqi_requests WHERE target_identity = ? AND status = ? ORDER BY id LIMIT 1",
        (identity, UQI_PENDING),
    )


def answer_uqi_request(conn: Database, request_id: int, answer: str, pid: int) -> None:
    conn.execute(
        "UPDATE uqi_requests SET status = ?, answer = ?, answered_at = ?, answered_by_pid = ? "
        "WHERE id = ? AND status = ?",
        (UQI_ANSWERED, answer, _now(), pid, request_id, UQI_PENDING),
    )


def expire_stale_uqi_requests(conn: Database, timeout_seconds: float | None = None) -> int:
    """Mark long-unanswered questions 'unanswered' so the asker stops waiting.

    Resolved at call time rather than captured as a default argument - a
    default binds once at import and would ignore any later change to the
    constant, including the environment variable it exists to read."""
    if timeout_seconds is None:
        timeout_seconds = UQI_TIMEOUT_SECONDS

    now = datetime.now(timezone.utc)
    expired = 0
    for row in conn.fetchall("SELECT id, created_at FROM uqi_requests WHERE status = ?", (UQI_PENDING,)):
        if (now - parse_timestamp(row["created_at"])).total_seconds() < timeout_seconds:
            continue
        conn.execute(
            "UPDATE uqi_requests SET status = ?, answered_at = ? WHERE id = ?",
            (UQI_UNANSWERED, _now(), row["id"]),
        )
        expired += 1
    return expired


def get_uqi_request(conn: Database, request_id: int) -> dict | None:
    return conn.fetchone("SELECT * FROM uqi_requests WHERE id = ?", (request_id,))


def list_uqi_requests(conn: Database, limit: int = 25) -> list[dict]:
    """Newest first - the audit trail §7 asks for."""
    return conn.fetchall("SELECT * FROM uqi_requests ORDER BY id DESC LIMIT ?", (limit,))


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
    judgment is Analysis's - see the `outcome` column comment in SCHEMA.

    **The outcome is validated against the vocabulary contract** (addendum 53 §7.2,
    §9 rule 5). An outcome outside it would be written successfully and never match
    a query again - which is exactly how `'answered'` survived in a comment for
    months while nothing could ever have read it (§147, §149). A value that can
    only be got wrong at read time is one the write side is free to invent."""
    from backend import vocabulary

    vocabulary.validate("cross_check_requests", "outcome", outcome)
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


def expire_stale_cross_checks(conn: Database, timeout_seconds: float | None = None) -> int:
    """Resolve long-unanswered requests as 'unanswered' so the requester can
    proceed. Silence is itself recorded - a lead that went out for corroboration
    and got none is a different thing from one never sent, and Analysis should
    see which it was."""
    # Resolved at call time, not captured as a default argument. A default is
    # bound once at import, so `timeout_seconds=CROSS_CHECK_TIMEOUT_SECONDS`
    # would freeze whatever the constant was when this module first loaded and
    # ignore any later change to it.
    if timeout_seconds is None:
        timeout_seconds = CROSS_CHECK_TIMEOUT_SECONDS

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


def record_parity_event(
    conn: Database,
    producer_identity: str,
    producer_spawned_at: str,
    entity_id: str,
    security: str,
    strike: float,
    expiry_days: int,
    direction: str,
    gross_edge_per_share: float,
    net_edge_per_share: float,
    classification: str,
    capacity_units: float,
    observed_at: str,
    run_id: str | None = None,
    scenario_id: str | None = None,
    lens_artifact_id: int | None = None,
    detector_id: str = "ARB-001",
    strike2: float | None = None,
    strike3: float | None = None,
    expiry2_days: int | None = None,
) -> int:
    """One Phase 1 detection (backend/arbitrage.py) Explorer's chain-scan
    path is escalating - ARB-001 by default (every call site before the
    cross-strike training increment), or any other detector scan_chain can
    return, named by `detector_id` with its extra legs in strike2/strike3.
    run_id/scenario_id come from the chain observation's own provenance
    (backend/canonical.py's Provenance) - see parity_events' own comment in
    SCHEMA for why that is safe to carry.

    **Converges rather than duplicates**, the observations store's own ingest
    idiom: the same detection on the same chain snapshot - keyed by
    (security, observed_at, strike, expiry_days, direction, detector_id,
    strike2, strike3), where observed_at identifies the exact chain the
    detector read - returns the existing row's id instead of inserting
    another. Measured before being written: without this, a static mission
    world re-triggering every ~1s agent cycle recorded 1,152 rows in a
    five-minute run from four securities - an append rate that would put
    millions of identical rows under a long-running organization. A *new*
    chain observation carries a new observed_at, so a detection on fresh data
    is always a fresh row - the key converges re-reads, never genuinely new
    market states. detector_id/strike2/strike3 joined the key so a box at
    (k1, k2) and ARB-001's own conversion at k1 - same security, same
    observed_at, same strike, same direction name space is not actually
    true here since directions differ, but a monotonicity_calls at (k1, k2)
    and a call_vertical_upper at (k1, k2) would otherwise be indistinguishable
    without detector_id, and two different k2 partners for the same k1 would
    otherwise collide without strike2; expiry2_days joined it with ARB-012
    (§56) because two calendar packages at the same strikes differ only by
    their far leg. `IS ?` rather than `= ?` for the nullable
    strike2/strike3/expiry2_days columns - SQLite's own NULL-safe
    comparison, parameter-bindable exactly like any other placeholder."""
    existing = conn.fetchone(
        "SELECT id FROM parity_events WHERE security = ? AND observed_at = ? AND strike = ? "
        "AND expiry_days = ? AND direction = ? AND detector_id = ? AND strike2 IS ? AND strike3 IS ? "
        "AND expiry2_days IS ?",
        (security, observed_at, strike, expiry_days, direction, detector_id, strike2, strike3, expiry2_days),
    )
    if existing is not None:
        return existing["id"]
    return conn.execute_returning_id(
        "INSERT INTO parity_events "
        "(created_at, producer_identity, producer_spawned_at, entity_id, security, strike, expiry_days, "
        "direction, gross_edge_per_share, net_edge_per_share, classification, capacity_units, observed_at, "
        "run_id, scenario_id, lens_artifact_id, detector_id, strike2, strike3, expiry2_days, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            _now(), producer_identity, producer_spawned_at, entity_id, security, strike, expiry_days,
            direction, gross_edge_per_share, net_edge_per_share, classification, capacity_units, observed_at,
            run_id, scenario_id, lens_artifact_id, detector_id, strike2, strike3, expiry2_days, SCHEMA_VERSION,
        ),
    )


def get_parity_event(conn: Database, parity_event_id: int) -> dict | None:
    return conn.fetchone("SELECT * FROM parity_events WHERE id = ?", (parity_event_id,))


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
    """Ordered oldest first, because a case that accumulates evidence is a
    sequence and the order is the information.

    "chatter broadening across three channels over four minutes" and the same
    four observations shuffled are different findings, and only one of them is
    what happened."""
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    return conn.fetchall(
        f"SELECT * FROM evidence_items WHERE id IN ({placeholders}) ORDER BY created_at, id", ids
    )


# The subject an instrument governs when it governs what a discovery report must
# be. One name shared by the instrument and the code that obeys it; two spellings
# is how the two stop agreeing.
REPORT_SUBJECT = "discovery_reports"


class GovernedRefusal(ValueError):
    """Work refused because an instrument in force is not satisfied.

    Its own type rather than a bare ValueError: an agent that catches this is
    catching *"the organization said no"*, which is a different thing from a
    malformed argument and deserves a different response."""


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
    cross_check_id: int | None = None,
    parity_event_id: int | None = None,
    filed_by: str | None = None,
) -> int:
    """filed_by: the role filing this, so the report is checked against whatever
    governs that role on `REPORT_SUBJECT` and records what it was checked against
    (TQ-87, §127).

    Optional in the signature and **not optional in practice**: every filing site
    in `agents/` passes it, and `tests/test_governed_agents.py` fails if one stops.
    A required parameter would have broken every fixture that files a report to
    set up some other test, which is a lot of churn to buy a guarantee a tripwire
    gives directly.

    lens_artifact_id: which intelligence artifact's threshold decided this
    was worth filing. Recorded on the report itself rather than only on the
    detector event, so that grades attribute back to the lens identically for
    Explorer (which has a detector event) and Speculator (which does not).

    cross_check_id: the contract whose two findings back this lead. Null for a
    report filed without one. Analysis follows it to read both sides of any
    disagreement rather than a summary that has already resolved it.

    parity_event_id: the ARB-001 detection backing this lead, for a report
    Explorer's parity path filed. Null for every other report - see
    discovery_reports.parity_event_id's own comment in SCHEMA."""
    governed_by = None
    if filed_by:
        verdict = operating_context.check(conn, filed_by, REPORT_SUBJECT, {
            "summary": summary, "security": security, "report_type": report_type,
            "evidence_ids": evidence_ids or [],
            "judgment_confidence": judgment_confidence,
            "detector_event_id": detector_event_id,
            "lens_artifact_id": lens_artifact_id,
        })
        if verdict.get("unmet_fields"):
            raise GovernedRefusal(
                f"an instrument in force ({verdict['instrument']}) is not satisfied by this "
                f"report: {', '.join(verdict['unmet_fields'])}. Refusing to file rather than "
                f"filing something the organization has decided is not a lead."
            )
        # Only when something actually governed it. `check` reports the context's
        # fingerprint either way, and for an ungoverned role that fingerprint is
        # the literal string "ungoverned" - which a saturation run duly recorded
        # in `governed_by` as though it were an authority (§128). An absence
        # written down as a value is the failure §100 and §118 both name.
        governed_by = verdict["fingerprint"] if verdict["governed"] else None

    return conn.execute_returning_id(
        "INSERT INTO discovery_reports "
        "(created_at, producer_identity, producer_spawned_at, report_type, security, summary, detector_event_id, evidence_ids, judgment_confidence, lens_artifact_id, cross_check_id, parity_event_id, governed_by, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (_now(), producer_identity, producer_spawned_at, report_type, security, summary, detector_event_id, json.dumps(evidence_ids or []), judgment_confidence, lens_artifact_id, cross_check_id, parity_event_id, governed_by, SCHEMA_VERSION),
    )


def fetch_next_pending_report(conn: Database) -> dict | None:
    """Oldest pending report. Plain FIFO - see fetch_prioritised_report for the
    ordering Analysis actually uses. Kept because several call sites only want
    "is there anything queued", and because FIFO is the behaviour prioritisation
    degrades to when nothing distinguishes the queue."""
    return conn.fetchone(
        "SELECT * FROM discovery_reports WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1"
    )


def list_pending_reports(conn: Database) -> list[dict]:
    return conn.fetchall("SELECT * FROM discovery_reports WHERE status = 'pending' ORDER BY id")


def prioritised_pending_reports(conn: Database, starvation_seconds: float | None = None) -> list[dict]:
    """The pending queue in the order Analysis should work it, each row carrying
    a `triage_reason`.

    Ranked in Python rather than in SQL. That is affordable precisely because
    the queue is bounded - has_pending_report dedups per producer and security,
    so the ceiling is one row per producer per security (measured at 13 of a
    possible 20 with ten securities). A ranking that needed the whole table
    would deserve SQL; this one does not, and a pure function is far easier to
    reason about and to test."""
    reports = list_pending_reports(conn)
    if not reports:
        return []

    # Assessed per report rather than against one shared history: each lead must
    # be judged against what was known *before it arrived*, and a single shared
    # history would include every queued observation in the baseline they are
    # measured against. Affordable because the queue is bounded by the
    # per-producer-per-security dedup (measured at 13 of a possible 20).
    novelty_scores = {r["id"]: assess_report_novelty(conn, r) for r in reports}

    cross_checks = {
        row["id"]: row
        for row in conn.fetchall("SELECT id, outcome FROM cross_check_requests")
    }
    now = datetime.now(timezone.utc)
    ages = {
        report["id"]: (now - parse_timestamp(report["created_at"])).total_seconds()
        for report in reports
    }

    ordered = triage.prioritise(reports, cross_checks, ages, starvation_seconds, novelty_scores)
    return [
        {**report, "waiting_seconds": round(ages[report["id"]], 1),
         "novelty": novelty_scores[report["id"]],
         "triage_reason": triage.explain(report, cross_checks, ages, starvation_seconds, novelty_scores)}
        for report in ordered
    ]


def fetch_prioritised_report(conn: Database, starvation_seconds: float | None = None) -> dict | None:
    """The single report Analysis should take next.

    A read with no claim, so two judgment agents reading at once both get the
    same row. Safe only with a single agent; use claim_next_report otherwise."""
    queue = prioritised_pending_reports(conn, starvation_seconds)
    return queue[0] if queue else None


def claim_next_report(
    conn: Database,
    identity: str,
    spawned_at: str,
    starvation_seconds: float | None = None,
) -> dict | None:
    """Take the highest-priority report, atomically, so no two agents take the same one.

    Walks the triage order attempting a guarded UPDATE on each: the claim only
    succeeds if the row is still 'pending', so a loser sees rowcount zero and
    moves to the next candidate rather than duplicating work. Reading the queue
    and then claiming without a guard would leave a twenty-second window - the
    length of a model call - in which both agents believe they own the report.

    Returns the claimed report with its triage_reason, or None if every candidate
    was taken while this agent was choosing."""
    for report in prioritised_pending_reports(conn, starvation_seconds):
        won = conn.execute_returning_rowcount(
            "UPDATE discovery_reports SET status = 'in_progress', claimed_at = ?, "
            "handled_by_identity = ?, handled_by_spawned_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (_now(), identity, spawned_at, report["id"]),
        )
        if won:
            return report
    return None


# How long a claim may stand before the report is treated as abandoned.
#
# Must exceed the longest realistic time an agent holds a report, or a working
# agent's claim is stolen mid-analysis and the report is judged twice - the exact
# duplication the claim exists to prevent, reintroduced by a timeout set too low.
# Measured: a judgment cycle is ~19.5s of model call plus a poll interval, with
# one observed outlier at 42s. 180s is far above the worst case and still short
# enough that a crashed agent's report is back in the queue within three minutes.
CLAIM_TIMEOUT_SECONDS = float(os.environ.get("FI_CLAIM_TIMEOUT_SECONDS", "180"))


def release_stale_claims(conn: Database, timeout_seconds: float | None = None) -> int:
    """Return abandoned claims to the queue.

    Claiming introduces a way to lose work that did not exist before: an agent
    that dies mid-analysis leaves its report 'in_progress' forever, and since
    has_pending_report still counts it, that security goes permanently silent.
    So the claim has to expire, exactly as a cross-check request does.

    Resolved at call time rather than bound as a default argument, so changing
    the constant does not require a reimport."""
    if timeout_seconds is None:
        timeout_seconds = CLAIM_TIMEOUT_SECONDS
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)).isoformat()
    return conn.execute_returning_rowcount(
        "UPDATE discovery_reports SET status = 'pending', claimed_at = NULL, "
        "handled_by_identity = NULL, handled_by_spawned_at = NULL "
        "WHERE status = 'in_progress' AND claimed_at IS NOT NULL AND claimed_at < ?",
        (cutoff,),
    )


def open_case_for(conn: Database, producer_identity: str, security: str) -> dict | None:
    """This producer's unresolved case for a security, claimed or not."""
    row = conn.fetchone(
        "SELECT * FROM discovery_reports WHERE producer_identity = ? AND security = ? LIMIT 1",
        (producer_identity, security),
    )
    return dict(row) if row else None


def enrich_case(
    conn: Database,
    report_id: int,
    evidence_ids: list[int],
    judgment_confidence: float | None = None,
    summary: str | None = None,
) -> str:
    """Fold new observations into an existing case.

    Returns what happened, because the three outcomes need different handling by
    the caller:

    ``enriched``  the case was waiting, and now carries this evidence too. The
                  judge will receive the whole sequence.
    ``deferred``  a judge already holds the case. The evidence is recorded
                  against it for follow-up and the active judgment is left
                  alone - yanking it would waste a model call and judge a
                  target that moved.
    ``gone``      the case was completed between reading it and writing to it.
                  The caller should file a fresh one.

    Evidence ids are merged rather than replaced, and duplicates dropped, so a
    producer that re-reports overlapping evidence cannot inflate a case.

    Nothing is deleted. `summary` and `judgment_confidence` describe the case as
    it now stands and are the only fields that change in place; every
    observation, old and new, remains in evidence_items exactly as recorded."""
    case = conn.fetchone(
        "SELECT status, evidence_ids, deferred_evidence_ids FROM discovery_reports WHERE id = ?",
        (report_id,),
    )
    if case is None:
        return "gone"

    def merged(existing: str | None) -> str:
        current = json.loads(existing or "[]")
        return json.dumps(current + [i for i in evidence_ids if i not in current])

    if case["status"] != "pending":
        conn.execute(
            "UPDATE discovery_reports SET deferred_evidence_ids = ?, updated_at = ? WHERE id = ?",
            (merged(case["deferred_evidence_ids"]), _now(), report_id),
        )
        return "deferred"

    # Guarded on status so a claim landing between the read above and this write
    # cannot have evidence appended underneath it.
    changed = conn.execute_returning_rowcount(
        "UPDATE discovery_reports SET evidence_ids = ?, updated_at = ?, "
        "judgment_confidence = COALESCE(?, judgment_confidence), "
        "summary = COALESCE(?, summary) WHERE id = ? AND status = 'pending'",
        (merged(case["evidence_ids"]), _now(), judgment_confidence, summary, report_id),
    )
    if changed:
        return "enriched"

    conn.execute(
        "UPDATE discovery_reports SET deferred_evidence_ids = ?, updated_at = ? WHERE id = ?",
        (merged(case["deferred_evidence_ids"]), _now(), report_id),
    )
    return "deferred"


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
    passes_used: int | None = None,
    challenge_summary: str | None = None,
) -> int:
    """peer_classification: addendum_7 §5's "classify the event" -
    'common_factor' | 'idiosyncratic' | 'not_applicable' (no peer context
    at all, e.g. a Speculator-sourced report) - Analysis's own reasoned
    judgment, populated from the peer_context agents/explorer.py surfaced
    into this report's context, not a mechanical copy of detector_events'
    scope column.

    passes_used / challenge_summary: how many Iterative Excellence passes
    (adopted 2026-08-19) produced this conclusion, and what the challenge
    pass found - both None for callers that predate the iteration budget."""
    return conn.execute_returning_id(
        "INSERT INTO analysis_results "
        "(created_at, producer_identity, producer_spawned_at, report_id, security, thesis, evidence_summary, confidence, uncertainty, peer_classification, passes_used, challenge_summary, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (_now(), producer_identity, producer_spawned_at, report_id, security, thesis, evidence_summary, confidence, uncertainty, peer_classification, passes_used, challenge_summary, SCHEMA_VERSION),
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
        if (now - parse_timestamp(row["created_at"])).total_seconds() < since_seconds:
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
    """A grade of the upstream report, by whoever consumed it.

    **A rationale is required** (TQ-104), on `record_disposition`'s rule and for a
    sharper reason: a grade is a ruling about somebody else's work, and the agent
    it judges cannot evaluate - or appeal - a ruling that does not say why. This
    function had no validation at all until a grade with no reasoning turned out
    to be a legitimate ground for contesting one.

    Refuses rather than defaulting. A grade stored with an empty rationale reads
    as a complete record, which is the same trap the duty above it names."""
    if not (rationale or "").strip():
        raise ValueError(
            "a grade must carry a rationale. A ruling about another agent's work that does not "
            "say why cannot be evaluated by the agent it judges, and a record without one looks "
            "complete (agent charter; SPEC_RECONCILIATION §147)."
        )
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


# --- structured objection ---------------------------------------------------
#
# Before this, a directive could end only 'success' or 'failure', which meant an
# executor declining an order had nowhere to put the fact. Two paths in the
# Controller were already objections wearing a failure's clothes: retiring or
# resuming an identity that does not exist is not the executor breaking, it is
# the order naming something absent.
#
# Conflating them costs two things. The metrics read a well-founded refusal as a
# malfunction, so an executor that correctly declines looks unreliable. And the
# reason lives in free text, where nothing can check it - which is precisely what
# a structured objection replaces.
#
# Internal rationale: INT-PHIL-0025

OBJECTION_FILED = "filed"
OBJECTION_SETTLED_STATUSES = ("upheld", "rejected", "escalated")


def file_objection(
    conn: Database,
    directive_id: int,
    filed_by: str,
    ground: str,
    evidence: str,
    remedy: str,
) -> int:
    """Decline ordered work on a named ground, and complete the directive as
    'objected' rather than as a failure.

    Three things are required and none is optional. The **ground** must come from
    the closed list, because an open one makes refusal discretionary again. The
    **evidence** must say what was observed. The **remedy** must say what would
    let the work proceed - a refusal that only says no hands the design problem
    back to whoever asked."""
    known = {g.name for g in compliance.OBJECTION_GROUNDS}
    if ground not in known:
        raise ValueError(
            f"unknown objection ground: {ground!r}. Allowed: {sorted(known)}. The list is closed "
            "deliberately; an 'other' category would restore free-form refusal under a new name."
        )
    if not (evidence or "").strip():
        raise ValueError("an objection must carry evidence; asserting a ground is not showing one")
    if not (remedy or "").strip():
        raise ValueError(
            "an objection must propose a remedy - what would have to be true for this work to "
            "proceed. On integrity grounds 'nothing would' is a legitimate remedy, but it has to "
            "be said."
        )
    if conn.fetchone("SELECT 1 FROM coo_directives WHERE id = ?", (directive_id,)) is None:
        raise ValueError(f"directive {directive_id} is not pending; nothing to object to")

    objection_id = conn.execute_returning_id(
        "INSERT INTO objections (directive_id, filed_by, filed_at, ground, evidence, remedy, "
        "status, schema_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (directive_id, filed_by, _now(), ground, evidence, remedy,
         OBJECTION_FILED, SCHEMA_VERSION),
    )
    # Completes the directive on its own outcome. The archive trigger carries it
    # across exactly as it does a success or a failure, so an objected directive
    # leaves the pending queue instead of being re-processed every cycle.
    complete_directive(conn, directive_id, "objected", detail=f"objection {objection_id}: {ground}")
    return objection_id


def get_objection(conn: Database, objection_id: int) -> dict | None:
    return conn.fetchone("SELECT * FROM objections WHERE id = ?", (objection_id,))


def list_objections(conn: Database, status: str | None = None) -> list[dict]:
    if status is None:
        return conn.fetchall("SELECT * FROM objections ORDER BY id")
    return conn.fetchall("SELECT * FROM objections WHERE status = ? ORDER BY id", (status,))


def settle_objection(conn: Database, objection_id: int, settled_by: str) -> dict:
    """Check an objection against the records and record what they showed.

    The separation this preserves is the whole point of G7. `compliance` reads and
    reports; it has no write path and cannot settle anything. This function has
    the write path and does no reasoning - it asks the checker what the records
    say and records the answer. Neither half can do the other's job, which is
    separation of powers at the only scale that currently exists.

    An objection that cannot be settled from records is marked 'escalated' and
    waits for the owner. It is not quietly rejected: an unsettled objection
    treated as unfounded would make refusal cost the objector, which is the
    incentive the governing framework spends §28 trying to avoid."""
    objection = get_objection(conn, objection_id)
    if objection is None:
        raise ValueError(f"no objection {objection_id}")
    if objection["status"] != OBJECTION_FILED:
        raise ValueError(f"objection {objection_id} is already {objection['status']}")

    directive = conn.fetchone(
        "SELECT * FROM coo_directives_completed WHERE id = ?", (objection["directive_id"],)
    ) or {}
    settlement = compliance.check_objection(conn, objection["ground"], dict(directive))

    status = "escalated" if settlement.outcome == compliance.UNSETTLED else settlement.outcome
    conn.execute(
        "UPDATE objections SET status = ?, settled_at = ?, settled_by = ?, settlement_reason = ? "
        "WHERE id = ?",
        (status, _now(), settled_by, settlement.reason, objection_id),
    )
    return get_objection(conn, objection_id)


# --- what the organization decided about a finding ---------------------------
#
# The compliance check computes findings; it does not store them, and it must
# not, because a stored violation goes stale the moment the work is graded. What
# gets stored is the judgment - and only the judgments that cannot be derived by
# looking again.
#
# The danger the shape guards against: `false_positive` is a universal off
# switch if a dispositioned finding disappears. So dispositions never hide
# anything. The check keeps reporting every finding and marks the ones that have
# been ruled on, and `governance.disposition_health` watches the ratio.
#
# Internal rationale: INT-PHIL-0027

# The check was wrong about this item. The most important disposition and the
# most dangerous: it is the one that says the governance layer erred, which is
# necessary to record and irresistible to overuse.
FALSE_POSITIVE = "false_positive"
# Real, acknowledged, and corrective work is expected to follow.
ACCEPTED = "accepted"
# Real, and deliberately not being fixed, with a reason that has to stand on its
# own. Distinct from accepted: nothing further is coming.
WONT_FIX = "wont_fix"

DISPOSITIONS = (FALSE_POSITIVE, ACCEPTED, WONT_FIX)


def record_disposition(
    conn: Database,
    rule: str,
    item,
    disposition: str,
    rationale: str,
    decided_by: str,
    evidence_ref: str | None = None,
) -> int:
    """Record a judgment about a compliance finding.

    Supersedes any active disposition on the same finding rather than updating
    it, so a changed mind leaves both the old view and the new one readable -
    the knowledge_records pattern, and the reason retirement there is
    non-destructive.

    A rationale is required. A disposition without one is an assertion that the
    finding does not count, which is exactly what a governance layer must not
    accept on trust - least of all from itself."""
    if disposition not in DISPOSITIONS:
        raise ValueError(f"unknown disposition {disposition!r}; allowed: {list(DISPOSITIONS)}")
    if not (rationale or "").strip():
        raise ValueError(
            "a disposition must carry a rationale. Ruling a finding out without saying why is how "
            "a compliance check stops covering things while still passing."
        )

    previous = get_disposition(conn, rule, item)
    new_id = conn.execute_returning_id(
        "INSERT INTO finding_dispositions (rule, item, disposition, rationale, evidence_ref, "
        "decided_by, decided_at, status, schema_version) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)",
        (rule, str(item), disposition, rationale, evidence_ref, decided_by, _now(), SCHEMA_VERSION),
    )
    if previous:
        conn.execute(
            "UPDATE finding_dispositions SET status = 'superseded', superseded_by = ? WHERE id = ?",
            (new_id, previous["id"]),
        )
    return new_id


def get_disposition(conn: Database, rule: str, item) -> dict | None:
    """The active ruling on a finding, or None if nobody has ruled."""
    return conn.fetchone(
        "SELECT * FROM finding_dispositions WHERE rule = ? AND item = ? AND status = 'active'",
        (rule, str(item)),
    )


def list_dispositions(conn: Database, disposition: str | None = None,
                      include_superseded: bool = False) -> list[dict]:
    clauses, params = [], []
    if not include_superseded:
        clauses.append("status = 'active'")
    if disposition:
        clauses.append("disposition = ?")
        params.append(disposition)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return conn.fetchall(f"SELECT * FROM finding_dispositions {where} ORDER BY id", tuple(params))


def disposition_history(conn: Database, rule: str, item) -> list[dict]:
    """Every ruling ever made on one finding, oldest first.

    The point of superseding rather than updating: a finding ruled a false
    positive and later accepted is a different story from one that was always
    accepted, and only the history distinguishes them."""
    return conn.fetchall(
        "SELECT * FROM finding_dispositions WHERE rule = ? AND item = ? ORDER BY id",
        (rule, str(item)),
    )


def raise_corrective_actions(conn: Database, items, recorded_by: str = "compliance") -> list[int]:
    """Turn corrective items into ordinary records, once each.

    The idempotence guard is load-bearing rather than tidy. The compliance check
    is meant to run repeatedly, and each run recomputes the same findings from
    the same records - so without `knowledge_exists` a single design gap would
    raise an identical corrective item every cycle until the store was noise.
    The same failure COO's lens health check already had, and the same fix.

    `items` are `remediation.CorrectiveItem`s. Passed in rather than computed
    here: deciding what work is needed happens in a module with no write path,
    and this one writes without deciding.

    Internal rationale: INT-PHIL-0028"""
    raised = []
    for item in items:
        if knowledge_exists(conn, KNOWLEDGE_CORRECTIVE, item.statement):
            continue
        rationale = item.rationale
        if item.blocked:
            # Carried into the record rather than dropped. Corrective work with
            # nowhere to go looks exactly like corrective work nobody raised,
            # and the difference is the whole point of raising it.
            rationale = f"{rationale}. BLOCKED: {item.blocked}"
        raised.append(record_knowledge(
            conn,
            record_kind=KNOWLEDGE_CORRECTIVE,
            statement=item.statement,
            recorded_by=recorded_by,
            subject=item.assigned_to,
            rationale=rationale,
            evidence_ref=item.evidence_ref,
        ))
    return raised


def list_corrective_actions(conn: Database, status: str = KNOWLEDGE_ACTIVE) -> list[dict]:
    return list_knowledge(conn, record_kind=KNOWLEDGE_CORRECTIVE, status=status)


# --- Incidents (Fault Tolerance Framework §8's lifecycle, §14's record) -------
#
# DETECTION -> DIAGNOSIS -> RECOVERY -> LEARNING, as four writes against one row
# rather than four tables. The row is opened the moment expected behaviour stops,
# and every later stage adds to it, so an incident always reads as the story of
# one failure instead of fragments that have to be joined back together.


def open_incident(
    conn: Database,
    subject_identity: str,
    subject_role: str,
    detected_by: str,
    symptom: str,
    last_healthy_at: str | None = None,
    evidence: dict | None = None,
) -> int | None:
    """Records that something stopped doing its job. Returns the incident id, or
    None if one is already open for this subject.

    None rather than an exception, because "already noticed" is the normal case
    on a watcher's second pass - a watcher polls, and the failure it is watching
    has not gone away between ticks."""
    existing = open_incident_for(conn, subject_identity)
    if existing is not None:
        return None
    return conn.execute_returning_id(
        """INSERT INTO incidents
               (subject_identity, subject_role, detected_by, detected_at, symptom,
                last_healthy_at, status, evidence, schema_version)
           VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?)""",
        (
            subject_identity,
            subject_role,
            detected_by,
            _now(),
            symptom,
            last_healthy_at,
            json.dumps(evidence) if evidence else None,
            SCHEMA_VERSION,
        ),
    )


def open_incident_for(conn: Database, subject_identity: str) -> dict | None:
    row = conn.fetchone(
        "SELECT * FROM incidents WHERE subject_identity = ? AND status = 'open'",
        (subject_identity,),
    )
    return dict(row) if row else None


def record_diagnosis(conn: Database, incident_id: int, diagnosis: str) -> None:
    """What the watcher decided the silence meant (§8 Diagnosis, §7's question:
    is this intentional or is it failure?)."""
    conn.execute("UPDATE incidents SET diagnosis = ? WHERE id = ?", (diagnosis, incident_id))


def record_action(conn: Database, incident_id: int, action: str) -> None:
    """What was attempted. Appended rather than replaced: a second attempt after a
    first one failed is the history worth having, and overwriting it would leave
    an escalated incident claiming a single try."""
    row = conn.fetchone("SELECT action FROM incidents WHERE id = ?", (incident_id,))
    previous = (row or {}).get("action")
    combined = f"{previous}; {action}" if previous else action
    conn.execute("UPDATE incidents SET action = ? WHERE id = ?", (combined, incident_id))


def record_recovery(conn: Database, incident_id: int, action: str | None = None) -> None:
    """The capability came back. Closes the incident."""
    if action:
        record_action(conn, incident_id, action)
    conn.execute(
        "UPDATE incidents SET status = 'recovered', resolved_at = ? WHERE id = ?",
        (_now(), incident_id),
    )


def escalate_incident(conn: Database, incident_id: int, escalated_to: str, reason: str) -> None:
    """The watcher could not restore the capability and has handed it upward
    (§11). Escalation is a state, not a message: the incident stays visible with
    an owner named on it, because the framework's rule is that a noticed failure
    must acquire an owner rather than that somebody must be told."""
    record_action(conn, incident_id, reason)
    conn.execute(
        "UPDATE incidents SET status = 'escalated', escalated_to = ?, resolved_at = ? WHERE id = ?",
        (escalated_to, _now(), incident_id),
    )


def list_incidents(conn: Database, status: str | None = None, limit: int = 50) -> list[dict]:
    """Newest first - the opposite of the Scoreboard, because an incident list is
    read to find out what is wrong now, not to work through a backlog."""
    if status:
        rows = conn.fetchall(
            "SELECT * FROM incidents WHERE status = ? ORDER BY id DESC LIMIT ?", (status, limit)
        )
    else:
        rows = conn.fetchall("SELECT * FROM incidents ORDER BY id DESC LIMIT ?", (limit,))
    return [dict(row) for row in rows]


def count_incidents_since(conn: Database, subject_identity: str, since_seconds: float) -> int:
    """How often this subject has failed recently - the input to a watcher's
    decision to stop trying and escalate instead.

    Counted from the durable record rather than from the watcher's memory on
    purpose: a restart resets memory, and a crash loop that survives restarts is
    exactly the condition a repeated-recovery guard exists to catch."""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=since_seconds)).isoformat()
    row = conn.fetchone(
        "SELECT COUNT(*) AS n FROM incidents WHERE subject_identity = ? AND detected_at >= ?",
        (subject_identity, cutoff),
    )
    return int(row["n"]) if row else 0
