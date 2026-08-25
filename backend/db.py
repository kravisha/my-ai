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
from contextlib import contextmanager
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
        self._in_transaction = False

    @contextmanager
    def transaction(self):
        """Group several writes so they land together or not at all.

        Every other write method here commits on its own, which is the right
        default for this system: agents make small independent writes, and one
        failing must not silently discard the last unrelated one.

        Migrations are the case that default cannot serve (addendum 42 §23,
        §89). "Only then mark the new state active" is not implementable when
        each step commits as it goes - a run that fails at step three leaves the
        first two applied and the version claiming they were not, which is the
        half-migrated state §23 exists to prevent.

        Deliberately not reentrant. A nested transaction that silently joined
        the outer one would let an inner block believe it had committed when an
        outer failure was still able to undo it, and that belief is exactly what
        a caller reaches for a transaction to avoid."""
        if self._in_transaction:
            raise RuntimeError(
                "nested transactions are not supported; the inner block would believe it had "
                "committed while an outer rollback could still undo it"
            )
        self._in_transaction = True
        try:
            yield self
        except BaseException:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()
        finally:
            self._in_transaction = False

    def _commit(self) -> None:
        """A no-op inside a transaction, so the block controls the boundary."""
        if not self._in_transaction:
            self._conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> None:
        """For INSERT/UPDATE/DELETE where the caller doesn't need the new
        row's id back - see execute_returning_id for INSERTs that do."""
        self._conn.execute(sql, params)
        self._commit()

    def execute_returning_id(self, sql: str, params: tuple = ()) -> int:
        """For INSERTs where the caller needs the new row's id - hides
        cursor.lastrowid, SQLite's mechanism for this (a future Postgres
        backend would use INSERT ... RETURNING id instead; that difference
        stays contained to this one method)."""
        cursor = self._conn.execute(sql, params)
        self._commit()
        return cursor.lastrowid

    def execute_returning_rowcount(self, sql: str, params: tuple = ()) -> int:
        """For conditional UPDATEs where the caller needs to know whether it won.

        The claim pattern: an UPDATE guarded by the state it expects to find,
        where a rowcount of zero means another process got there first. Without
        this the caller cannot distinguish "I claimed it" from "somebody else
        did", which is the whole point of an atomic claim."""
        cursor = self._conn.execute(sql, params)
        self._commit()
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
        future backend would need to reproduce exactly, just equivalently.

        Refused inside a transaction, because sqlite3's executescript issues a
        COMMIT before it runs. Allowing it would silently end the transaction
        and leave everything before it permanently applied, while the block
        still looked atomic - a trap that only shows up when a rollback is
        needed and turns out not to have happened."""
        if self._in_transaction:
            raise RuntimeError(
                "executescript cannot run inside a transaction: sqlite3 commits before running "
                "it, which would end the transaction and make an earlier rollback impossible. "
                "Run DDL outside the block, or issue the statements individually via execute()."
            )
        self._conn.executescript(script)
        self._commit()

    def close(self) -> None:
        self._conn.close()
