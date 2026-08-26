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
from gateway import client_agent, clients, roles
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
    conn.executescript(client_agent.SCHEMA)
    conn.executescript(clients.SCHEMA)
    _apply_additive_migrations(conn)
    # `portfolios` and `portfolio_holdings` are deliberately absent (TQ-69,
    # §110), and their absence is a tested property rather than an omission -
    # `test_the_gateway_holds_no_portfolio_table` asserts this function creates
    # neither.
    #
    # Owner direction, 2026-08-26 (§109): the Gateway authenticates; the backend
    # authorizes and holds business logic. Those two tables carry the ownership
    # guard that authorizes every read of them, so they are business logic, and
    # they now live in financial_intelligence.db where backend/fi_db.init_schema
    # creates them. The Gateway reaches them over HTTP through
    # gateway/portfolio_client.py.
    #
    # Creating them here again would be worse than useless: it would produce a
    # second, empty portfolios table that nothing writes to and any future reader
    # might. Two sources of truth for whose money this is, which is the failure
    # TQ-44 existed to prevent (spec Risk 2).
    #
    # The two pre-TQ-69 migrations that used to run here (TQ-44's move into owned
    # portfolios and TQ-45a's field rename) have not been deleted. They now run
    # from backend/portfolio_migration.py, against this database, immediately
    # before its rows are copied to the backend - a database still at the old
    # shape has to reach the current one before it can be moved, or the move
    # carries columns that mean something different.
    _archive_any_portfolio_tables(conn)


PORTFOLIO_ARCHIVES = ("portfolios", "portfolio_holdings")


def _archive_any_portfolio_tables(conn: Database) -> list[str]:
    """Rename away any portfolio table an older build left here (TQ-72, §111).

    TQ-69 moved these to the backend and this function refused to start without
    a migration. §111 then removed them from the backend too - the system stores
    no portfolio at all - so there is nowhere to migrate *to*, and refusing to
    start would strand a database with no fix available.

    Renamed rather than dropped, following `client_holdings_legacy` and
    `portfolio_holdings_pre45`, and for a sharper reason than habit: these rows
    are **client financial records**, and this build has just decided it should
    never have held them. Deleting them silently on startup would be this system
    destroying somebody's data to tidy up after its own architectural mistake.
    They are renamed, reported, and TQ-71 disposes of them deliberately."""
    archived = []
    for table in PORTFOLIO_ARCHIVES:
        if conn.fetchone(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ) is None:
            continue
        target = f"{table}_pre72"
        if conn.fetchone(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (target,)
        ) is not None:
            # An earlier pass already archived one. Leave both alone rather than
            # overwriting an archive - that is a person's decision, not a
            # startup step's.
            continue
        conn.execute(f"ALTER TABLE {table} RENAME TO {target}")
        archived.append(target)
    return archived


# Columns added after a database already existed. Additive only, matching the
# schema rule backend/fi_db.py works under: a column is added, never renamed or
# removed, so every historical row stays readable under the current layout.
#
# `CREATE TABLE IF NOT EXISTS` does nothing to a table that is already there, so
# without this an existing gateway.db would keep the old shape and every insert
# naming the new column would fail - on the developer's machine only, which is
# the worst place to find out.
_ADDITIVE_COLUMNS = {
    "scoreboard_items": {"signature": "TEXT"},
    # The role a session was issued under (TQ-34, §92). Deliberately with no
    # default: a session predating roles gets NULL, and NULL is refused rather
    # than resolved to anything. Defaulting it to the operator would silently
    # promote every session that existed before the boundary did, which is the
    # one upgrade outcome a security column must not have.
    "sessions": {"role": "TEXT", "subject": "TEXT"},
    # Who a conversation belongs to (TQ-39, §93). No default, and NULL is
    # refused rather than treated as anybody's: a conversation predating owners
    # is one whose owner is genuinely unknown, and handing it to whoever asks
    # next is precisely the leak this column exists to close.
    "conversations": {"owner": "TEXT"},
    # Demo data, flagged rather than named (TQ-41, §96). Clearing it before
    # going live is then exact instead of a careful guess at which rows a
    # naming convention covered.
    "client_agents": {"simulated": "INTEGER NOT NULL DEFAULT 0"},
}


def _apply_additive_migrations(conn: Database) -> None:
    for table, columns in _ADDITIVE_COLUMNS.items():
        present = {row["name"] for row in conn.fetchall(f"PRAGMA table_info({table})")}
        for column, declaration in columns.items():
            if column not in present:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


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


def create_session(conn: Database, ttl_seconds: int, role: str,
                   subject: str | None = None) -> tuple[str, str]:
    """Issues a token and records only its digest. Returns (token, expires_at);
    the token itself is never persisted and cannot be recovered from this row.

    The role is required rather than defaulted (TQ-34, §92). A caller that had
    verified a credential and then let this fill in a role would be guessing at
    precisely the moment the answer is known."""
    if role not in roles.ROLES:
        raise roles.UnknownRole(f"cannot issue a session for unknown role {role!r}")
    token = secrets.token_urlsafe(32)
    now = _now()
    expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()
    conn.execute(
        "INSERT INTO sessions (token_hash, created_at, expires_at, last_seen_at, role, subject) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (_hash(token), now.isoformat(), expires_at, now.isoformat(), role, subject or role),
    )
    return token, expires_at


def session_subject(conn: Database, token: str) -> str | None:
    """Which account a live session belongs to, or None.

    Separate from `session_role` because they answer different questions: the
    role decides what may be done, the subject decides whose memory it is. A
    Gateway that conflated them would give two clients one conversation."""
    row = conn.fetchone(
        "SELECT expires_at, role, subject FROM sessions WHERE token_hash = ?", (_hash(token),))
    if row is None or row["role"] is None or row["subject"] is None:
        return None
    if datetime.fromisoformat(row["expires_at"]) <= _now():
        return None
    return row["subject"]


def session_role(conn: Database, token: str) -> str | None:
    """The role a live session was issued under, or None if there is no usable
    session behind this token.

    None covers three cases on purpose - no such token, expired, or issued
    before sessions carried roles - because the caller does the same thing with
    all three: refuse, and say to log in again. Distinguishing them in the
    answer would tell an unauthenticated caller which of their guesses was
    closest."""
    row = conn.fetchone(
        "SELECT expires_at, role FROM sessions WHERE token_hash = ?", (_hash(token),))
    if row is None or row["role"] is None:
        return None
    if datetime.fromisoformat(row["expires_at"]) <= _now():
        return None
    if row["role"] not in roles.ROLES:
        return None
    conn.execute(
        "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
        (_now().isoformat(), _hash(token)),
    )
    return row["role"]


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


def current_conversation_id(conn: Database, owner: str) -> int:
    """The conversation *this owner* resumes, created on first use.

    `owner` is required, and the reason is a breach rather than a preference
    (TQ-39, §93). This used to be "newest wins" across the whole database, which
    was correct while the Gateway had exactly one credential and became a leak
    the moment TQ-34 added two more: a client connecting received the operator's
    entire transcript in the socket's opening frame. Reproduced before it was
    fixed, which is how it is known rather than suspected.

    Owner is the *subject* - the account that logged in - not the role.
    Relationship continuity (addendum 43 §16) belongs to a person, and two
    clients sharing a role must not share a memory."""
    if not (owner or "").strip():
        raise ValueError("a conversation must belong to somebody")
    row = conn.fetchone(
        "SELECT id FROM conversations WHERE owner = ? ORDER BY id DESC LIMIT 1", (owner,))
    if row is not None:
        return row["id"]
    return start_conversation(conn, owner)


def start_conversation(conn: Database, owner: str) -> int:
    if not (owner or "").strip():
        raise ValueError("a conversation must belong to somebody")
    return conn.execute_returning_id(
        "INSERT INTO conversations (created_at, owner) VALUES (?, ?)",
        (_now().isoformat(), owner),
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
