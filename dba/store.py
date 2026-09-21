"""The DBA's own database, and the only place SQL is written (§9).

## A third database file, on purpose

`financial_intelligence.db` belongs to the backend and `gateway.db` to the
Gateway, each for reasons its own module docstring gives. `dba.db` is a third,
for the reason §2.1 gives: the DBA is its own agent, and an agent whose store
lives inside another service's database is not independent of that service.

It is built on `backend/db.py`'s `Database`, which is §5.2's abstraction and
already carries WAL mode, busy-timeout handling and `transaction()`. Writing a
second connection layer beside it would duplicate the decisions that module
made once.

## Why the schema is small and the types are not in it

Five tables, and none of them is per entity type. §6.3 wants important fields
explicit and everything else in metadata; `dba/entities.py` declares which is
which. So a new kind of record is a declaration rather than a migration, and
the shape of the database stops moving.

## What is deliberately not here yet

§7's agent mailbox, §41's event history and §18's vectors have no table. Each
belongs to a later phase in §46, and this repository's standing rule - stated
in `backend/migrations.py` - is that machinery with no user does not get built.
The provenance and confidence columns on `entities` are the one reasoned
exception: §12's conflict resolution has to ask *"which source has higher
authority"*, and columns are cheaper to add now than to migrate onto live rows
later. They are columns, not machinery; nothing reads them yet and `status()`
says so.

`DBA_DB_PATH` is honoured for the same reason `FI_DB_PATH` and
`GATEWAY_DB_PATH` are: the test suite has to be able to say what "the default
database" means before any module reads it.

Nothing is created at import. `init_schema` is called by whoever opens the
agent - the lesson `tests/test_db_isolation.py` exists to keep.
"""

from __future__ import annotations

import os
from pathlib import Path

from backend.db import Database, now_iso

PATH_ENV = "DBA_DB_PATH"

SCHEMA_VERSION = 1

# --- the tables ---------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    -- §6.3's explicit searchable fields. Every one of these is used by search
    -- or by a duplicate rule; a field that is neither lives in data_json.
    name TEXT,
    email TEXT,
    phone TEXT,
    external_id TEXT,
    status TEXT,
    data_json TEXT NOT NULL DEFAULT '{}',
    classification TEXT NOT NULL DEFAULT 'internal',
    -- §20/§21. Written on create, not yet read - see the module docstring.
    source_type TEXT,
    source_agent TEXT,
    confidence REAL,
    verified INTEGER NOT NULL DEFAULT 0,
    -- §5.5
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT,
    deleted_at TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(entity_type, name);
CREATE INDEX IF NOT EXISTS idx_entities_email ON entities(email);
CREATE INDEX IF NOT EXISTS idx_entities_phone ON entities(phone);
CREATE INDEX IF NOT EXISTS idx_entities_external ON entities(entity_type, external_id);
CREATE INDEX IF NOT EXISTS idx_entities_live ON entities(entity_type, archived_at, deleted_at);

CREATE TABLE IF NOT EXISTS relationships (
    id TEXT PRIMARY KEY,
    from_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    to_id TEXT NOT NULL,
    data_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    archived_at TEXT
);

-- One live edge per (from, relation, to). A partial index rather than a table
-- constraint because an archived edge must be allowed to sit beside the live
-- one that replaced it - §5.6 prefers archival to deletion, and a plain UNIQUE
-- would make re-linking after an unlink fail.
CREATE UNIQUE INDEX IF NOT EXISTS idx_relationships_live
    ON relationships(from_id, relation, to_id) WHERE archived_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_relationships_from ON relationships(from_id, relation);
CREATE INDEX IF NOT EXISTS idx_relationships_to ON relationships(to_id, relation);

-- §13. Append-oriented: there is no update or delete statement for this table
-- anywhere in this package, and a test asserts that.
CREATE TABLE IF NOT EXISTS audit_events (
    audit_id TEXT PRIMARY KEY,
    at TEXT NOT NULL,
    actor TEXT,
    requesting_agent TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    previous_summary TEXT,
    new_summary TEXT,
    request_id TEXT,
    reason TEXT,
    result TEXT NOT NULL,
    succeeded INTEGER NOT NULL,
    source TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_events(entity_id, at);
CREATE INDEX IF NOT EXISTS idx_audit_request ON audit_events(request_id);
CREATE INDEX IF NOT EXISTS idx_audit_at ON audit_events(at);

-- §22. The response is stored, not just the fact of the request, because
-- "replaying the same request should return the prior result".
CREATE TABLE IF NOT EXISTS handled_requests (
    request_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    response_json TEXT NOT NULL,
    at TEXT NOT NULL
);

-- §4.1's "preserve the pending request until clarification is received".
CREATE TABLE IF NOT EXISTS pending_clarifications (
    clarification_id TEXT PRIMARY KEY,
    request_json TEXT NOT NULL,
    reason TEXT NOT NULL,
    question TEXT NOT NULL,
    options_json TEXT NOT NULL DEFAULT '[]',
    pending_action TEXT,
    asked_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution TEXT
);

CREATE INDEX IF NOT EXISTS idx_pending_open ON pending_clarifications(resolved_at);

CREATE TABLE IF NOT EXISTS dba_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def database_path() -> Path:
    configured = (os.environ.get(PATH_ENV, "") or "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent.parent / "dba.db"


def connect() -> Database:
    """A connection to the DBA's store.

    Not cached in a module global: `Database` holds a sqlite3 connection, and a
    process-wide one shared across threads is the defect `gateway/main.py`
    already documents avoiding by opening one per request."""
    return Database(database_path())


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)
    if conn.fetchone("SELECT value FROM dba_meta WHERE key = 'schema_version'") is None:
        conn.execute(
            "INSERT INTO dba_meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),))


def schema_version(conn: Database) -> int:
    """The version the stored data is at (§5.7's "the system must know which
    schema version is currently active")."""
    row = conn.fetchone("SELECT value FROM dba_meta WHERE key = 'schema_version'")
    return int(row["value"]) if row else 0


__all__ = ["PATH_ENV", "SCHEMA", "SCHEMA_VERSION", "database_path", "connect",
           "init_schema", "schema_version", "now_iso", "Database"]
