"""The Project Scoreboard: unresolved items awaiting human or analysis attention
(addendum 16 §16, addendum 17 §10).

The point of it is addendum 16 §17 - not every question should interrupt
development. Something noticed mid-implementation gets recorded and the work
continues, and the Super User decides later, in one place, rather than being
interrupted per question or losing the question entirely.

**The fields are §16's list, minus the ones with no producer yet.** §16 says an
item "should eventually contain" thirteen things and that the detailed schema
belongs to a later specification. Two of those are deliberately absent here:

- *Related commits* - nothing in this system touches Git until G4. A nullable
  column nothing writes is an empty schema, which is the failure this project has
  refused repeatedly. The schema rule is additive, so it costs one line when
  commits exist to name.
- *Decision*, as distinct from *Resolution* - collapsed into one field, because
  nothing today can tell them apart. A decision recorded while the item stays
  open is a real distinction, and when something needs it, it separates.

**Importance is addendum 17 §10's three escalation levels**, and they are the
same vocabulary because they describe the same judgment: informational goes on
the board, important is surfaced prominently, urgent is escalated. What §10 calls
"the highest-priority notification mechanism available to the Gateway" does not
exist yet - §10 itself defers notification channels to a separate specification -
so an urgent item sorts first and is counted in the header, and nothing rings a
phone. That gap is stated rather than papered over: an item filed urgent today
will be seen when the Super User looks.

`blocking` is separate from importance on purpose (§16 lists both, §17 turns on
the difference). Importance is how much attention it deserves; blocking is
whether work stopped. An urgent non-blocking security question and a trivial
blocker are both real, and one field cannot say both.
"""

from datetime import datetime, timezone

from backend.db import Database

# Addendum 17 §10's escalation levels, most severe first. Order matters: it is
# the sort key, so a new level has to be inserted where it belongs rather than
# appended.
IMPORTANCE_LEVELS = ("urgent", "important", "informational")

# Two states, because two are what the system can currently tell apart. More
# would be vocabulary for distinctions nothing makes.
STATUSES = ("open", "resolved")

SCHEMA = """
CREATE TABLE IF NOT EXISTS scoreboard_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    question TEXT NOT NULL,
    importance TEXT NOT NULL CHECK (importance IN ('urgent', 'important', 'informational')),
    blocking INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
    related_spec TEXT,
    related_component TEXT,
    resolution TEXT,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS scoreboard_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    author TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (item_id) REFERENCES scoreboard_items(id)
);

CREATE INDEX IF NOT EXISTS idx_scoreboard_status ON scoreboard_items(status, id);
CREATE INDEX IF NOT EXISTS idx_scoreboard_notes_item ON scoreboard_notes(item_id, id);
"""

# The routing policy addendum 17 §6 asks the Gateway to own: the originating
# agent describes the issue, the Gateway decides how it is presented. Open before
# resolved, then most severe first, then oldest first - an urgent item that has
# sat for a week outranks one filed this morning, because the queue exists to
# stop things being forgotten rather than to show the newest.
_ORDER_BY = """
    ORDER BY
        CASE status WHEN 'open' THEN 0 ELSE 1 END,
        CASE importance WHEN 'urgent' THEN 0 WHEN 'important' THEN 1 ELSE 2 END,
        id
"""


class ScoreboardError(ValueError):
    """A rejected write, with a message meant for whoever asked - including the
    model, which will read it as a tool result and should be able to correct
    itself from it."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)


def file_item(
    conn: Database,
    source: str,
    question: str,
    importance: str = "informational",
    blocking: bool = False,
    related_spec: str | None = None,
    related_component: str | None = None,
) -> int:
    """Records a question or concern. Returns its id.

    Validated here rather than only at the route, because the assistant's tool
    call reaches this function without passing through a Pydantic model, and a
    CHECK constraint failure would surface to the model as a database error
    instead of something it can act on."""
    question = (question or "").strip()
    if not question:
        raise ScoreboardError("An item needs a question or concern; empty text is not an item.")
    if importance not in IMPORTANCE_LEVELS:
        raise ScoreboardError(
            f"importance must be one of {', '.join(IMPORTANCE_LEVELS)}; got {importance!r}"
        )
    source = (source or "").strip()
    if not source:
        raise ScoreboardError("An item needs a source; provenance is not optional.")

    return conn.execute_returning_id(
        """INSERT INTO scoreboard_items
               (created_at, source, question, importance, blocking, status,
                related_spec, related_component)
           VALUES (?, ?, ?, ?, ?, 'open', ?, ?)""",
        (
            _now(),
            source,
            question,
            importance,
            1 if blocking else 0,
            (related_spec or "").strip() or None,
            (related_component or "").strip() or None,
        ),
    )


def get_item(conn: Database, item_id: int) -> dict | None:
    """One item with its discussion attached, or None.

    The notes come with it rather than through a second call because an item
    without its discussion is misleading - the current state of a deferred
    question is mostly what has been said about it since."""
    item = conn.fetchone("SELECT * FROM scoreboard_items WHERE id = ?", (item_id,))
    if item is None:
        return None
    item["blocking"] = bool(item["blocking"])
    item["notes"] = conn.fetchall(
        "SELECT id, author, note, created_at FROM scoreboard_notes WHERE item_id = ? ORDER BY id",
        (item_id,),
    )
    return item


def list_items(
    conn: Database, status: str | None = None, importance: str | None = None, limit: int = 50
) -> list[dict]:
    """The board, in presentation order. Notes are not included - a list of
    twenty items each carrying its full discussion is not a list anybody reads."""
    if status is not None and status not in STATUSES:
        raise ScoreboardError(f"status must be one of {', '.join(STATUSES)}; got {status!r}")
    if importance is not None and importance not in IMPORTANCE_LEVELS:
        raise ScoreboardError(
            f"importance must be one of {', '.join(IMPORTANCE_LEVELS)}; got {importance!r}"
        )

    clauses = []
    params: list = []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if importance is not None:
        clauses.append("importance = ?")
        params.append(importance)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    items = conn.fetchall(
        f"SELECT * FROM scoreboard_items {where} {_ORDER_BY} LIMIT ?", (*params, limit)
    )
    for item in items:
        item["blocking"] = bool(item["blocking"])
    return items


def add_note(conn: Database, item_id: int, author: str, note: str) -> int:
    """Appends to an item's discussion. Notes are never edited or deleted: the
    record of how a decision was reached is the reason to keep a board at all."""
    note = (note or "").strip()
    if not note:
        raise ScoreboardError("An empty note says nothing; nothing recorded.")
    if conn.fetchone("SELECT 1 FROM scoreboard_items WHERE id = ?", (item_id,)) is None:
        raise ScoreboardError(f"No Scoreboard item {item_id}.")

    return conn.execute_returning_id(
        "INSERT INTO scoreboard_notes (item_id, author, note, created_at) VALUES (?, ?, ?, ?)",
        (item_id, author, note, _now()),
    )


def resolve_item(conn: Database, item_id: int, resolution: str) -> dict:
    """Closes an item with a stated outcome, and returns it.

    A resolution is required. "Resolved" with no text is the state this whole
    mechanism exists to prevent: a question that stopped being visible without
    anybody being able to say what happened to it.

    Resolving an already-resolved item is refused rather than silently
    overwriting the first resolution - the second attempt usually means somebody
    is looking at a stale list."""
    resolution = (resolution or "").strip()
    if not resolution:
        raise ScoreboardError("A resolution has to say what was decided; empty text is not one.")

    item = conn.fetchone("SELECT status FROM scoreboard_items WHERE id = ?", (item_id,))
    if item is None:
        raise ScoreboardError(f"No Scoreboard item {item_id}.")
    if item["status"] == "resolved":
        raise ScoreboardError(f"Scoreboard item {item_id} is already resolved.")

    conn.execute(
        "UPDATE scoreboard_items SET status = 'resolved', resolution = ?, resolved_at = ? WHERE id = ?",
        (resolution, _now(), item_id),
    )
    return get_item(conn, item_id)


def open_counts(conn: Database) -> dict[str, int]:
    """How many open items at each level, for the header. Every level is present
    even at zero, so a client can render a stable row rather than one that
    changes shape as things are resolved."""
    counts = {level: 0 for level in IMPORTANCE_LEVELS}
    for row in conn.fetchall(
        "SELECT importance, COUNT(*) AS n FROM scoreboard_items WHERE status = 'open' GROUP BY importance"
    ):
        counts[row["importance"]] = row["n"]
    return counts
