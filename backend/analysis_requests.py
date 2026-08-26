"""Tasking the Portfolio Analyst, and getting the report back — a transport, not
a store (TASK_QUEUE TQ-79; §111, §115, addendum 9 §2).

## The tension this module exists to resolve

Two rules in this system point in opposite directions, and the Portfolio Analyst
is where they meet.

**Agents talk through the database.** `backend/fi_db.py` states it: *"agents do
not use this to talk to each other — inter-agent work goes through the
queue/directive tables."* There is no direct IPC here, deliberately, and every
agent that has ever been built claims work from a table.

**Nothing about a client's portfolio is retained.** §111: *"holds no information
of the portfolios in the system"*, and §115 puts a time on it — everything is
discarded when the client disconnects.

An analyst that receives its task from a table and writes its report to one is,
on the face of it, a system that stores client data.

## The resolution: the row is a message, and messages are consumed

The database is the **transport**, not the store. What makes that a real
distinction rather than a comforting phrase is that it is enforced three ways,
and each one is a rule this project already applies elsewhere:

1. **A result is deleted when it is collected.** `collect()` returns the report
   and removes the row in one transaction. There is no second read, because it is
   not a store — a client who asks twice gets nothing the second time, which is
   the honest behaviour for a message.
2. **A session's rows go when the session does.** `discard_session()` is what a
   disconnect calls, and it removes everything for that session whether it was
   collected or not.
3. **Expiry is enforced on read, not only by the sweeper.** Exactly the reasoning
   `gateway/store.session_is_valid` gives: *"a sweep that stops running would
   silently extend every session, whereas a comparison that stops running fails
   closed the moment it is wrong."* A sweeper that dies must not become
   indefinite retention of somebody's portfolio.

The sweeper is still needed, because a client who never comes back leaves a row
nothing will read — and an unread row is exactly the case where "enforced on
read" enforces nothing.

## What a request may carry, and what it may never

**Source descriptors: yes.** Which sources to fetch, what they are called, what
they point at. That is the task, and it is deleted with the row.

**Positions: never.** They are fetched by the analyst, consolidated in memory,
turned into a report, and the report is what travels back. No row in this table
has ever held a position and none may.

**Credentials: never, and this one is a live problem.** The simulated and manual
providers need none, so nothing here needs them yet. But TQ-73's credentialed
fetch will, and **an agent that is a separate OS process cannot be handed a
secret through a table without that secret being written to disk** — which is the
one thing §115's design exists to prevent.

That is recorded here rather than solved, because it is a real architectural
question and this is not the increment that answers it. The options are visible
already: the analyst runs in-process for the session rather than as a subprocess;
or the secret passes by a pipe at spawn and never lands; or the fetch happens in
the process that received the request and only the consolidated result goes to
the analyst. Each has a cost. **What must not happen is a credential column
appearing here because it was the obvious place to put one.**

## Failure travels as a report, not as an error

A source that could not be reached produces a *partial* consolidation with notes
saying so (TQ-78), and that is a legitimate answer the client is entitled to. It
is delivered as a result rather than raised as a failure — the request only fails
when nothing could be produced at all.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone

from backend import portfolios
from backend.db import Database

SCHEMA_VERSION = 1

# How long a request or its result may sit before it is discarded regardless.
#
# A ceiling on retention rather than a convenience: it is the longest a client's
# report may exist on disk if they never come back for it. Shorter than a session
# would be wrong (a client is entitled to the answer they asked for), and much
# longer would make this a store with a slow delete.
DEFAULT_TTL_SECONDS = 30 * 60

STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
STATUSES = (STATUS_PENDING, STATUS_IN_PROGRESS, STATUS_READY, STATUS_FAILED)

SCHEMA = """
-- Portfolio analysis requests and their results (TQ-79).
--
-- **A transport, not a store.** Every row here is a message with a consumer and
-- a deadline: `collect` deletes on read, `discard_session` removes everything a
-- session left, and `expires_at` is enforced on read as well as by the sweeper.
--
-- `sources` is JSON describing *where to fetch from* - names and references,
-- never positions and never secrets. The positions a fetch returns are
-- consolidated in the analyst's memory and leave as a report; they are never
-- written here. See the module docstring on why a credential column must not
-- appear in this table however convenient it would be.
--
-- `result` is the report, and it is the only client-derived data that touches
-- disk at all. It exists between the analyst finishing and the client
-- collecting, and `collect` removes it in the same transaction that returns it.
CREATE TABLE IF NOT EXISTS portfolio_analysis_requests (
    request_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    owner_type TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    sources TEXT NOT NULL,
    requested TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT,
    result TEXT,
    claimed_by TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS analysis_requests_by_session
    ON portfolio_analysis_requests (session_id);
CREATE INDEX IF NOT EXISTS analysis_requests_pending
    ON portfolio_analysis_requests (status, created_at);
"""

_FIELDS = ("request_id", "session_id", "owner_type", "owner_id", "sources", "requested",
           "status", "detail", "result", "claimed_by", "created_at", "expires_at")


class RequestRefused(ValueError):
    """A request this module will not accept, with the reason."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _interpret(row) -> dict:
    request = dict(row)
    request["sources"] = json.loads(request["sources"])
    request["result"] = json.loads(request["result"]) if request["result"] else None
    return request


def submit(conn: Database, *, session_id: str, owner, sources, requested: str,
           ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str:
    """Ask for an analysis. Returns the request id.

    `owner` is an `OwnerContext`, refused as a bare string for the reason it has
    always been refused: a raw id is a claim, and this is the position that
    decides whose money gets fetched.

    `sources` is a sequence of mappings describing where to fetch from. They are
    checked for anything that looks like a secret before they are written,
    because the check is cheap and the failure is permanent — a credential
    written to disk stays written."""
    owner = portfolios.require_owner(owner)
    if not (session_id or "").strip():
        raise RequestRefused(
            "an analysis request belongs to a session, so that it can be discarded when "
            "that session ends")
    described = [dict(source) for source in sources]
    if not described:
        raise RequestRefused(
            "an analysis needs at least one source. There is nothing to consolidate and "
            "nothing to analyse without one.")
    for source in described:
        _refuse_secrets(source)

    request_id = f"par-{secrets.token_hex(12)}"
    now = _now()
    conn.execute(
        "INSERT INTO portfolio_analysis_requests (request_id, session_id, owner_type, "
        "owner_id, sources, requested, status, created_at, expires_at, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (request_id, session_id, owner.owner_type, owner.owner_id,
         json.dumps(described), requested, STATUS_PENDING, now.isoformat(),
         (now + timedelta(seconds=ttl_seconds)).isoformat(), SCHEMA_VERSION))
    return request_id


# Keys a source descriptor must never carry. Checked by name rather than by
# value, because a secret is identified by what it is for rather than by what it
# looks like - and a check that tried to recognise a token by shape would miss
# the first one that did not match.
_SECRET_KEYS = ("credential", "credentials", "password", "secret", "token",
                "api_key", "apikey", "access_token", "refresh_token", "private_key")


def _refuse_secrets(source: dict) -> None:
    offending = sorted(key for key in source
                       if any(secret in str(key).lower() for secret in _SECRET_KEYS))
    if offending:
        raise RequestRefused(
            f"a source descriptor carries {offending}, which would write a credential to "
            "disk. Credentials reach a fetch some other way (TQ-73) and never through "
            "this table - a secret written down stays written.")


def claim_next(conn: Database, identity: str) -> dict | None:
    """Take the oldest pending request, atomically.

    Guarded UPDATE rather than read-then-write, for the reason
    `fi_db.claim_next_report` gives: reading the queue and claiming without a
    guard leaves a window in which two analysts believe they own the same
    request, and here that would mean fetching one client's portfolio twice."""
    purge_expired(conn)
    rows = conn.fetchall(
        f"SELECT {', '.join(_FIELDS)} FROM portfolio_analysis_requests "
        "WHERE status = ? ORDER BY created_at, request_id", (STATUS_PENDING,))
    for row in rows:
        won = conn.execute_returning_rowcount(
            "UPDATE portfolio_analysis_requests SET status = ?, claimed_by = ? "
            "WHERE request_id = ? AND status = ?",
            (STATUS_IN_PROGRESS, identity, row["request_id"], STATUS_PENDING))
        if won:
            return _interpret(row)
    return None


def deliver(conn: Database, request_id: str, report: dict) -> None:
    """Hand back a finished report, for the client to collect.

    A *partial* report is still a report (TQ-78): a source that could not be
    reached produces a consolidation with notes saying so, and the client is
    entitled to it. `fail` is for a request that produced nothing at all."""
    conn.execute(
        "UPDATE portfolio_analysis_requests SET status = ?, result = ? "
        "WHERE request_id = ?",
        (STATUS_READY, json.dumps(report), request_id))


def fail(conn: Database, request_id: str, detail: str) -> None:
    conn.execute(
        "UPDATE portfolio_analysis_requests SET status = ?, detail = ? "
        "WHERE request_id = ?", (STATUS_FAILED, str(detail), request_id))


def collect(conn: Database, *, session_id: str, request_id: str) -> dict | None:
    """The report, once — and the row goes with it.

    **Delete-on-read is what makes this a transport rather than a store**, and
    it is why a second collect returns nothing. That is not a limitation to work
    around: a client who needs the report twice should be given it twice by
    whatever held it, not by this system keeping a copy of their portfolio.

    Scoped by session as well as by id, so a request id on its own is not enough
    to reach somebody's report - the same reasoning that makes an owner context
    required rather than an id."""
    purge_expired(conn)
    row = conn.fetchone(
        f"SELECT {', '.join(_FIELDS)} FROM portfolio_analysis_requests "
        "WHERE request_id = ? AND session_id = ?", (request_id, session_id))
    if row is None:
        return None
    request = _interpret(row)
    if request["status"] not in (STATUS_READY, STATUS_FAILED):
        # Still working. Left in place, and nothing is invented for the caller.
        return {"request_id": request_id, "status": request["status"], "result": None}
    conn.execute("DELETE FROM portfolio_analysis_requests WHERE request_id = ?",
                 (request_id,))
    return {"request_id": request_id, "status": request["status"],
            "result": request["result"], "detail": request["detail"]}


def discard_session(conn: Database, session_id: str) -> int:
    """Everything this session left, gone. What a disconnect calls (§115).

    Removes rows whatever their status - a request still being worked on is
    still this client's data, and an analyst that delivers into a deleted row
    simply finds nothing to update."""
    return conn.execute_returning_rowcount(
        "DELETE FROM portfolio_analysis_requests WHERE session_id = ?", (session_id,))


def purge_expired(conn: Database) -> int:
    """Discard anything past its deadline.

    Called from `claim_next` and `collect` as well as by a sweeper, so that
    expiry holds even if nothing is sweeping - `gateway/store.session_is_valid`'s
    rule, and the stakes are higher here: a sweeper that stopped would leave a
    client's report on disk indefinitely, which is the one thing §111 forbids
    outright."""
    return conn.execute_returning_rowcount(
        "DELETE FROM portfolio_analysis_requests WHERE expires_at <= ?",
        (_now().isoformat(),))


def outstanding(conn: Database) -> dict:
    """What is still held, for an operator or a pre-launch check.

    Reports counts and ages, **never contents**. A hygiene check that printed a
    client's report to prove it was there would be the problem it exists to
    detect."""
    purge_expired(conn)
    rows = conn.fetchall(
        "SELECT status, COUNT(*) AS n, MIN(created_at) AS oldest "
        "FROM portfolio_analysis_requests GROUP BY status")
    by_status = {row["status"]: {"count": row["n"], "oldest": row["oldest"]}
                 for row in rows}
    total = sum(entry["count"] for entry in by_status.values())
    return {
        "clean": total == 0,
        "held": total,
        "by_status": by_status,
        "note": ("No client analysis data is held." if not total else
                 f"{total} analysis request(s) still held. They are messages awaiting "
                 "collection or expiry, not stored portfolios - but nothing should be "
                 "here at rest."),
    }
