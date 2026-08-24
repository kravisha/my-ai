"""The Strategic Priority Register, machine-readable (addendum 31 §3, §5;
addendum 32 §12, §15; TASK_QUEUE TQ-05).

What the organization is considering pursuing, as rows instead of prose. An
entry is a proposal with a classification the addenda define: NEED or WANT
(31 §2), a GREEN→CRITICAL urgency flag on Needs only (31 §2.2 — a flag is an
escalation property of necessity, so a Want carrying one is rejected rather
than stored), a Quick-Win mark (32 §15), and a status whose transitions carry
their reasons.

## What this register is, and what it is not

Implementation revealed a boundary the queue entry (TQ-05) had blurred: the
*development* work queue — increments executed against this repository,
recorded in `docs/TASK_QUEUE.md` — and the *organization's* register of
proposals are different registers with different authors and lifecycles. The
paper file stays authoritative for development work, where the record must
live in the repository next to the code it describes. This store is the
organization's own: the place a petition (31 §5) lands when an agent or the
owner files one, and the substrate the intake pipeline (31 §22) grows on.
Duplicating the development queue into these rows would have manufactured two
sources of truth — exactly what the Conflict Rule bans. Disposition in
`SPEC_RECONCILIATION.md` §54.

## The fields are 31 §3's list, minus those with no producer

Title, category, flag, rationale, origin, source reference, status with
reasons, and the record reference a completed entry points at. The specified
fields deliberately absent, and why: cost/impact profile (32 §14) is TQ-07,
deferred until something consumes it; priority *score* (31 §3) would be a
number wearing authority nothing earned — ordering below is by the doctrine's
own rules, not a scalar; champion, Board status, commission linkage need the
parliamentary machinery the queue defers. Absent fields are absent, not
defaulted.

## Fail-closed vocabulary, reasons required

Category and flag vocabularies are enforced at write time; a Want with a
flag, a blocked/deferred/declined transition without a reason, or a done
transition without a record reference (Governance G14/G19: passing is not
sufficient, implementation is verified — the reference *is* the
verification pointer) are refused, not normalized. An open entry with the
same title is a duplicate (31 §5.4 consolidation) and refused with the
existing entry named.

Sits below fi_db (fi_db.init_schema creates this table), so it must not
import fi_db — the same layering as risk.py and strategy.py.
"""

from __future__ import annotations

from backend.db import Database, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS strategic_register (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    need_flag TEXT,
    quick_win INTEGER NOT NULL DEFAULT 0,
    origin TEXT NOT NULL,
    rationale TEXT NOT NULL,
    source_reference TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    status_reason TEXT,
    record_reference TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS strategic_register_by_status ON strategic_register (status, id);
"""

SCHEMA_VERSION = 1

CATEGORIES = ("need", "want")

# 31 §2.2's escalation ladder, most urgent first. Order is meaning here: it
# drives queue_order, so the tuple is the one place the ladder lives.
FLAGS = ("critical", "red", "orange", "yellow", "green")

STATUSES = ("queued", "in_progress", "done", "blocked", "deferred", "declined")

# Transitions that close or park an entry must say why; done must point at
# the record that proves it. queued/in_progress carry no obligation.
_REASON_REQUIRED = ("blocked", "deferred", "declined")

OPEN_STATUSES = ("queued", "in_progress", "blocked")


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)


def file_entry(
    conn: Database,
    title: str,
    category: str,
    origin: str,
    rationale: str,
    need_flag: str | None = None,
    quick_win: bool = False,
    source_reference: str | None = None,
) -> int:
    """A petition or mandate enters the register. Validation refuses rather
    than repairs — an entry the vocabulary cannot express is a conversation
    to have, not a row to coerce."""
    title = (title or "").strip()
    rationale = (rationale or "").strip()
    origin = (origin or "").strip()
    if not title or not rationale or not origin:
        raise ValueError("a register entry requires a title, a rationale, and an origin")
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of {CATEGORIES}, not {category!r}")
    if need_flag is not None:
        if category != "need":
            raise ValueError(
                "a priority flag is an escalation property of necessity (addendum 31 §2.2); "
                "a want cannot carry one"
            )
        if need_flag not in FLAGS:
            raise ValueError(f"need_flag must be one of {FLAGS}, not {need_flag!r}")

    duplicate = conn.fetchone(
        f"SELECT id, status FROM strategic_register WHERE title = ? "
        f"AND status IN ({','.join('?' * len(OPEN_STATUSES))})",
        (title, *OPEN_STATUSES),
    )
    if duplicate:
        raise ValueError(
            f"an open entry with this title already exists (id {duplicate['id']}, "
            f"status {duplicate['status']}) - consolidate rather than duplicate (addendum 31 §5.4)"
        )

    now = now_iso()
    return conn.execute_returning_id(
        "INSERT INTO strategic_register "
        "(created_at, updated_at, title, category, need_flag, quick_win, origin, rationale, "
        " source_reference, status, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)",
        (now, now, title, category, need_flag, int(bool(quick_win)), origin, rationale,
         source_reference, SCHEMA_VERSION),
    )


def set_status(
    conn: Database,
    entry_id: int,
    status: str,
    reason: str | None = None,
    record_reference: str | None = None,
) -> None:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}, not {status!r}")
    if status in _REASON_REQUIRED and not (reason or "").strip():
        raise ValueError(f"a {status!r} transition requires a reason - parking without one is drift")
    if status == "done" and not (record_reference or "").strip():
        raise ValueError(
            "done requires a record_reference (where the completed work is recorded) - "
            "passing is not implementation (addendum 32, G14/G19)"
        )
    updated = conn.execute_returning_rowcount(
        "UPDATE strategic_register SET status = ?, status_reason = ?, record_reference = ?, "
        "updated_at = ? WHERE id = ?",
        (status, reason, record_reference, now_iso(), entry_id),
    )
    if updated == 0:
        raise ValueError(f"no register entry with id {entry_id}")


def get_entry(conn: Database, entry_id: int) -> dict | None:
    return conn.fetchone("SELECT * FROM strategic_register WHERE id = ?", (entry_id,))


def list_register(conn: Database, status: str | None = None) -> list[dict]:
    if status is not None:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}, not {status!r}")
        return conn.fetchall(
            "SELECT * FROM strategic_register WHERE status = ? ORDER BY id", (status,)
        )
    return conn.fetchall("SELECT * FROM strategic_register ORDER BY id")


def queue_order(conn: Database) -> list[dict]:
    """Open entries in working order, by the doctrine's own rules rather than
    a score: Needs before Wants (31 §2.1), Needs by flag severity (an
    unflagged Need sits below green — urgency someone stated outranks urgency
    nobody did), Quick-Win Wants before other Wants (32 §15's accelerated
    path), then filing order. Deterministic, so two readers of the register
    see one queue."""
    entries = [e for e in list_register(conn) if e["status"] in OPEN_STATUSES]

    def sort_key(entry: dict):
        if entry["category"] == "need":
            flag = entry["need_flag"]
            severity = FLAGS.index(flag) if flag in FLAGS else len(FLAGS)
            return (0, severity, 0, entry["id"])
        return (1, 0, 0 if entry["quick_win"] else 1, entry["id"])

    return sorted(entries, key=sort_key)
