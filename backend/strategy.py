"""The Strategy Store holds prescriptive, versioned playbooks - what the
organization does, distinct from what it has learned (knowledge_records,
intelligence_artifacts). Addendum 20 §4's flow Data -> Knowledge -> Strategy
gets its third stage here, and it opens with a true statement: the seeded
strategy is the discovery playbook the organization already executes,
reverse-documented, not an aspiration. Every strategy names the knowledge it
rests on (knowledge_refs), and the one rule this module enforces is that an
ACTIVE strategy resting on knowledge that is no longer active is a finding -
a playbook whose premises expired is being executed on faith.

Fourth instance of the layering rule (after canonical, identifiers, risk):
fi_db.init_schema creates this module's table, so this module must not
import fi_db - would close an import cycle - and re-states the one
intelligence_artifacts query it needs, with this comment.

No 'proposed' status for strategies: intelligence artifacts got a proposal
lifecycle because a Trainer seat produces candidates; nothing produces
strategy candidates today, and a proposal state nobody can fill would be
machinery ahead of need (Manifesto §8).

Supersession is the adoption act: supersede_strategy records who adopted and
links the chain.
"""

from __future__ import annotations

import json

from backend.db import Database, now_iso

# This module's own schema version, like risk.py's - not a mirror of
# fi_db.SCHEMA_VERSION. Module-owned tables version independently; a
# constant that must be kept in sync with another module's by hand is a
# drift waiting to be found the hard way.
SCHEMA_VERSION = 1

STATUSES = ("active", "superseded", "retired")

SCHEMA = """
CREATE TABLE IF NOT EXISTS strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    name TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    -- Prescriptive: what we do and when - the counterpart of knowledge's
    -- "what we have learned" (addendum 20 §4).
    statement TEXT NOT NULL,
    rationale TEXT,
    -- JSON list of {"kind": ..., "name": ...} naming the intelligence
    -- artifacts this strategy rests on. A strategy must say what knowledge
    -- justifies it, or the health rule below has nothing to check.
    knowledge_refs TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','superseded','retired')),
    adopted_by TEXT,
    superseded_by INTEGER,
    retired_reason TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1,
    UNIQUE(name, version)
);
CREATE INDEX IF NOT EXISTS strategies_by_status ON strategies (status, name);
"""

# The seed strategy's name, exported so callers (agents/coo.py, tests) never
# have to spell the literal.
BASELINE_NAME = "baseline_discovery_playbook"


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)
    _seed_baseline(conn)


def _seed_baseline(conn: Database) -> None:
    """The Strategy Store's opening entry: the discovery pipeline the
    organization already executes, reverse-documented rather than aspired
    to.

    Inserted with a raw INSERT OR IGNORE, not create_strategy - deliberately.
    create_strategy validates that every knowledge_refs entry names an
    ACTIVE intelligence_artifacts row, but fi_db.init_schema calls this
    module's init_schema (which calls this) *before* _seed_static_metadata,
    the function that seeds the two lenses this strategy references. Going
    through create_strategy here would raise on every fresh database. INSERT
    OR IGNORE needs no such row to exist - it is keyed only on
    UNIQUE(name, version) - so seeding ahead of the lenses is safe; the
    validation create_strategy performs is for callers adding strategies
    *after* the store already has knowledge to check against, which is true
    of every caller except this one."""
    conn.execute(
        "INSERT OR IGNORE INTO strategies "
        "(created_at, name, version, statement, rationale, knowledge_refs, status, adopted_by, schema_version) "
        "VALUES (?, ?, 1, ?, ?, ?, 'active', 'seed', ?)",
        (
            now_iso(),
            BASELINE_NAME,
            "Scan every security in the observed universe each cycle through the active "
            "iv_ratio_threshold lens. When the lens fires, judge the detection before trusting "
            "it, and cross-check with the Speculator for independent social evidence - silence "
            "is not corroboration. File a discovery report only after judgment passes. Analysis "
            "reaches a conclusion, challenges it, and revises only when the challenge finds "
            "something material; 'not enough evidence' and 'not worthwhile' are valid "
            "conclusions. Every analyzed opportunity receives a risk assessment before it is "
            "complete.",
            "Reverse-documented from the pipeline the organization actually executes, so the "
            "Strategy Store opens with a true statement rather than an aspiration. The "
            "prescriptive counterpart of the knowledge the linked lenses hold.",
            json.dumps([
                {"kind": "detection_lens", "name": "iv_ratio_threshold"},
                {"kind": "detection_lens", "name": "speculator_confidence_threshold"},
            ]),
            SCHEMA_VERSION,
        ),
    )


def _validate_refs(conn: Database, knowledge_refs: list[dict]) -> None:
    if not knowledge_refs:
        raise ValueError("knowledge_refs must not be empty: a strategy must say what knowledge justifies it")
    for ref in knowledge_refs:
        if not isinstance(ref, dict) or set(ref) != {"kind", "name"}:
            raise ValueError(f"each knowledge ref must be shaped {{'kind', 'name'}}, got {ref!r}")
        # Re-stated against intelligence_artifacts directly rather than calling
        # fi_db.get_active_artifact: fi_db.init_schema creates this module's
        # table, so this module must not import fi_db - that would close a
        # cycle. See the module docstring's "fourth instance of the layering
        # rule".
        active = conn.fetchone(
            "SELECT 1 FROM intelligence_artifacts WHERE name = ? AND status = 'active'",
            (ref["name"],),
        )
        if active is None:
            raise ValueError(
                f"knowledge ref {ref['name']!r} names no ACTIVE intelligence artifact - a "
                "strategy cannot rest on knowledge that does not currently hold"
            )


def create_strategy(
    conn: Database,
    name: str,
    statement: str,
    rationale: str,
    knowledge_refs: list[dict],
    adopted_by: str,
) -> int:
    """A new playbook, versioned from any prior history under the same name.

    Refuses a blank statement, empty or malformed knowledge_refs, a ref
    naming knowledge that is not currently active, and a second active
    strategy under a name that already has one - a name identifies one
    playbook, and two active versions of it would leave no answer to "what
    do we currently do here"."""
    if not statement or not statement.strip():
        raise ValueError("statement must not be blank")
    _validate_refs(conn, knowledge_refs)

    existing_active = conn.fetchone(
        "SELECT 1 FROM strategies WHERE name = ? AND status = 'active'", (name,)
    )
    if existing_active is not None:
        raise ValueError(f"strategy {name!r} already has an active version")

    row = conn.fetchone("SELECT COALESCE(MAX(version), 0) AS max_version FROM strategies WHERE name = ?", (name,))
    version = row["max_version"] + 1

    return conn.execute_returning_id(
        "INSERT INTO strategies "
        "(created_at, name, version, statement, rationale, knowledge_refs, status, adopted_by, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)",
        (now_iso(), name, version, statement, rationale, json.dumps(knowledge_refs), adopted_by, SCHEMA_VERSION),
    )


def supersede_strategy(
    conn: Database,
    old_id: int,
    statement: str,
    rationale: str,
    knowledge_refs: list[dict],
    adopted_by: str,
) -> int:
    """Supersession is the adoption act: the record shows who adopted what
    over what, and the old text survives rather than being overwritten. The
    old row's statement and rationale stay exactly as they were decided at
    the time - a superseded playbook is history, not a draft to erase."""
    old = conn.fetchone("SELECT * FROM strategies WHERE id = ?", (old_id,))
    if old is None:
        raise ValueError(f"no strategy with id {old_id}")
    if old["status"] != "active":
        raise ValueError(f"strategy {old_id} is {old['status']!r}, not active - only an active strategy can be superseded")

    if not statement or not statement.strip():
        raise ValueError("statement must not be blank")
    _validate_refs(conn, knowledge_refs)

    new_id = conn.execute_returning_id(
        "INSERT INTO strategies "
        "(created_at, name, version, statement, rationale, knowledge_refs, status, adopted_by, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)",
        (
            now_iso(), old["name"], old["version"] + 1, statement, rationale,
            json.dumps(knowledge_refs), adopted_by, SCHEMA_VERSION,
        ),
    )
    conn.execute(
        "UPDATE strategies SET status = 'superseded', superseded_by = ? WHERE id = ?",
        (new_id, old_id),
    )
    return new_id


def retire_strategy(conn: Database, strategy_id: int, reason: str) -> None:
    """A retired strategy has no successor - the organization stopped doing
    the thing, which is different from doing it differently (that is
    supersede_strategy). Only an active strategy can be retired; a
    superseded or already-retired one is not the thing currently governing
    anything."""
    row = conn.fetchone("SELECT * FROM strategies WHERE id = ?", (strategy_id,))
    if row is None:
        raise ValueError(f"no strategy with id {strategy_id}")
    if row["status"] != "active":
        raise ValueError(f"strategy {strategy_id} is {row['status']!r}, not active - only an active strategy can be retired")

    conn.execute(
        "UPDATE strategies SET status = 'retired', retired_reason = ? WHERE id = ?",
        (reason, strategy_id),
    )


def _row_to_dict(row: dict) -> dict:
    result = dict(row)
    result["knowledge_refs"] = json.loads(result["knowledge_refs"])
    return result


def get_active(conn: Database, name: str) -> dict | None:
    row = conn.fetchone(
        "SELECT * FROM strategies WHERE name = ? AND status = 'active' ORDER BY version DESC LIMIT 1",
        (name,),
    )
    return _row_to_dict(row) if row is not None else None


def list_strategies(conn: Database, status: str | None = None) -> list[dict]:
    if status is not None:
        rows = conn.fetchall(
            "SELECT * FROM strategies WHERE status = ? ORDER BY name, version", (status,)
        )
    else:
        rows = conn.fetchall("SELECT * FROM strategies ORDER BY name, version")
    return [_row_to_dict(row) for row in rows]


def unhealthy(conn: Database) -> list[dict]:
    """Every active strategy whose knowledge_refs no longer all resolve to an
    active intelligence artifact.

    An active strategy resting on stale knowledge is being executed on
    faith. One finding per strategy (per cause = per strategy, matching
    remediation's per-rule grouping philosophy), naming every broken premise
    at once - so the adjudication (re-link, supersede, or retire) is one
    decision, not a drip of separate findings as each ref is noticed."""
    findings = []
    for strategy_row in conn.fetchall("SELECT * FROM strategies WHERE status = 'active'"):
        refs = json.loads(strategy_row["knowledge_refs"])
        broken = []
        for ref in refs:
            active = conn.fetchone(
                "SELECT 1 FROM intelligence_artifacts WHERE name = ? AND status = 'active'",
                (ref["name"],),
            )
            if active is not None:
                continue
            # Not just "missing" - the most recent row's status, so the
            # finding says *why* it is not current (stale, superseded,
            # rejected) rather than only that it fails the check.
            latest = conn.fetchone(
                "SELECT status FROM intelligence_artifacts WHERE name = ? ORDER BY version DESC LIMIT 1",
                (ref["name"],),
            )
            broken.append({"name": ref["name"], "status": latest["status"] if latest else "missing"})
        if broken:
            findings.append({
                "strategy_id": strategy_row["id"],
                "name": strategy_row["name"],
                "version": strategy_row["version"],
                "broken_refs": broken,
            })
    return findings
