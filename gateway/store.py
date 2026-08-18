"""The Gateway's own persistence, deliberately separate from
`financial_intelligence.db`.

Addendum 16 §23 requires the Gateway to stay usable when an internal component
is unavailable, and §22 requires it to run as a small independent service while
the rest of the system is under construction. A Scoreboard or a conversation
living in the Financial Intelligence database would inherit every dependency the
Gateway is supposed to be isolated from - the backend would have to be up for the
Super User to read a deferred question, which is the opposite of what those two
sections ask for.

So: a second database file, `gateway.db`, built on the same domain-agnostic
`backend/db.py` Database class that `backend/fi_db.py` uses. That module's own
docstring anticipated this ("reusable by any future persistence need"), and
reusing it means WAL mode, busy timeout and row handling are decided once.

`GATEWAY_DB_PATH` is honoured for the same reason `FI_DB_PATH` is: the test suite
has to be able to say what "the default database" means before any module reads
it, and a developer running two instances should be able to separate them.

Nothing here is created at import. `init_schema` is called from the FastAPI
lifespan (see gateway/main.py), because a module that builds a database when it
is imported writes to disk in every process that so much as names it - the defect
`tests/test_db_isolation.py` now exists to prevent.
"""

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.db import Database
from gateway import scoreboard

DB_PATH = Path(os.environ.get("GATEWAY_DB_PATH") or (Path(__file__).resolve().parent.parent / "gateway.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id);
"""


def get_connection(db_path: str | Path = DB_PATH) -> Database:
    return Database(db_path)


def init_schema(conn: Database) -> None:
    """Every table in gateway.db, from whichever module owns it.

    The Scoreboard keeps its own DDL next to the functions that read and write it
    (gateway/scoreboard.py), because that is where the reasoning about its fields
    belongs. This function stays the single place that creates the database, so a
    caller never has to know how many modules have tables in it."""
    conn.executescript(SCHEMA)
    scoreboard.init_schema(conn)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Sessions ---
#
# Tokens are stored as SHA-256 digests, never in the clear. The ordinary
# app/session.py keeps raw tokens in sessions.json, which is defensible for a
# localhost desktop client; this service is the one addendum 17 §14 calls a
# high-security boundary and intends to expose to a phone, so a stolen database
# file should not hand over a live session. Hashing costs one line and removes
# the whole class.


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(conn: Database, ttl_seconds: int) -> tuple[str, str]:
    """Issues a token and records only its digest. Returns (token, expires_at);
    the token itself is never persisted and cannot be recovered from this row."""
    token = secrets.token_urlsafe(32)
    now = _now()
    expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()
    conn.execute(
        "INSERT INTO sessions (token_hash, created_at, expires_at, last_seen_at) VALUES (?, ?, ?, ?)",
        (_hash(token), now.isoformat(), expires_at, now.isoformat()),
    )
    return token, expires_at


def session_is_valid(conn: Database, token: str) -> bool:
    """True only for a token that exists and has not expired.

    Expiry is enforced on read rather than by a background sweep: a sweep that
    stops running would silently extend every session, whereas a comparison that
    stops running fails closed the moment it is wrong."""
    row = conn.fetchone("SELECT expires_at FROM sessions WHERE token_hash = ?", (_hash(token),))
    if row is None:
        return False
    if datetime.fromisoformat(row["expires_at"]) <= _now():
        return False
    conn.execute(
        "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
        (_now().isoformat(), _hash(token)),
    )
    return True


def delete_session(conn: Database, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))


def purge_expired_sessions(conn: Database) -> int:
    """Housekeeping, not a security control - `session_is_valid` is what refuses
    an expired token. Returns how many rows went, so a caller can log it."""
    return conn.execute_returning_rowcount(
        "DELETE FROM sessions WHERE expires_at <= ?", (_now().isoformat(),)
    )


# --- Conversations ---
#
# Version 1 is explicitly single-user (addendum 17 §13), so there is no owner
# column: every row in this database belongs to the Super User. Conversations are
# still a table rather than an implicit singleton because §9's "conversation
# continuity" and the eventual ability to start a fresh thread are the same
# feature, and adding the identifier later would mean migrating the messages.


def current_conversation_id(conn: Database) -> int:
    """The conversation a reconnecting client resumes, created on first use.

    Newest wins. A client that disconnects and returns is continuing a
    conversation, not starting one - which is the behaviour §9 asks for and the
    reason the transcript is persisted at all."""
    row = conn.fetchone("SELECT id FROM conversations ORDER BY id DESC LIMIT 1")
    if row is not None:
        return row["id"]
    return conn.execute_returning_id(
        "INSERT INTO conversations (created_at) VALUES (?)", (_now().isoformat(),)
    )


def start_conversation(conn: Database) -> int:
    return conn.execute_returning_id(
        "INSERT INTO conversations (created_at) VALUES (?)", (_now().isoformat(),)
    )


def append_message(conn: Database, conversation_id: int, role: str, text: str) -> int:
    return conn.execute_returning_id(
        "INSERT INTO messages (conversation_id, role, text, created_at) VALUES (?, ?, ?, ?)",
        (conversation_id, role, text, _now().isoformat()),
    )


def history(conn: Database, conversation_id: int) -> list[dict]:
    """Every turn, oldest first - what the client renders on reconnect and what
    the model is given as context."""
    return conn.fetchall(
        "SELECT id, role, text, created_at FROM messages WHERE conversation_id = ? ORDER BY id",
        (conversation_id,),
    )
