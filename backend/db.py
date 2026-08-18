"""Generic data-access abstraction (Pre-Alpha requirement - see the new
architecture documents assimilated 2026-08-15): agent code and tests must
never depend on SQLite-specific behavior directly, and a future PostgreSQL
migration should require minimal changes to agent logic. This module hides
every SQLite-specific detail (row factory, cursor.lastrowid, PRAGMA
settings) behind a small, domain-agnostic interface.

backend/fi_db.py builds the actual Financial Intelligence schema/functions
on top of this; this module knows nothing about that domain - it's pure
connection/execution mechanics, reusable by any future persistence need
(Agent Name Repository, Security Universe, ...) without becoming a dumping
ground for unrelated concerns.

SQLite remains the actual database engine for now - Pre-Alpha explicitly
defers "final PostgreSQL/pgvector migration timing." The point of this
abstraction is that a later Postgres backend would mean writing a new class
implementing this same small interface, not touching every call site across
the codebase - confirmed that sqlite3 is imported nowhere else in this repo
except backend/fi_db.py, and every agent module only ever calls fi_db.*
functions, passing the connection object through opaquely.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    """The one clock. Here rather than in backend/fi_db.py because two modules
    needed it and the second one importing the first created a cycle - identity
    is a lower layer than the financial-intelligence schema, and a timestamp is
    lower than both."""
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value: str) -> datetime:
    """Normalizes the two timestamp shapes this system produces: Python's own
    now_iso() (e.g. '...+00:00') and SQL's strftime (e.g. '...Z'). Comparing
    them as raw strings is fragile - this is the one place that difference gets
    handled, instead of every call site reimplementing the same fix."""
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


class Database:
    def __init__(self, path: str | Path):
        self._conn = sqlite3.connect(path, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA busy_timeout=5000;")

    def execute(self, sql: str, params: tuple = ()) -> None:
        """For INSERT/UPDATE/DELETE where the caller doesn't need the new
        row's id back - see execute_returning_id for INSERTs that do."""
        self._conn.execute(sql, params)
        self._conn.commit()

    def execute_returning_id(self, sql: str, params: tuple = ()) -> int:
        """For INSERTs where the caller needs the new row's id - hides
        cursor.lastrowid, SQLite's mechanism for this (a future Postgres
        backend would use INSERT ... RETURNING id instead; that difference
        stays contained to this one method)."""
        cursor = self._conn.execute(sql, params)
        self._conn.commit()
        return cursor.lastrowid

    def execute_returning_rowcount(self, sql: str, params: tuple = ()) -> int:
        """For conditional UPDATEs where the caller needs to know whether it won.

        The claim pattern: an UPDATE guarded by the state it expects to find,
        where a rowcount of zero means another process got there first. Without
        this the caller cannot distinguish "I claimed it" from "somebody else
        did", which is the whole point of an atomic claim."""
        cursor = self._conn.execute(sql, params)
        self._conn.commit()
        return cursor.rowcount

    def fetchone(self, sql: str, params: tuple = ()) -> dict | None:
        row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def executescript(self, script: str) -> None:
        """For multi-statement DDL (CREATE TABLE/TRIGGER/VIEW) - SQLite's
        own executescript method, not part of the standard DB-API surface a
        future backend would need to reproduce exactly, just equivalently."""
        self._conn.executescript(script)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
