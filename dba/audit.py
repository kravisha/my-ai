"""The audit trail (§13).

    *"Audit history should be append-oriented. Agents must not rewrite audit
    history as ordinary application data."*

Enforced by there being nothing here that rewrites one. This module has a
single writer and no updater and no deleter, and `tests/test_dba.py` greps the
package for an `UPDATE audit_events` or a `DELETE FROM audit_events` and fails
if one ever appears. That is a cheap test and it is the only kind that actually
holds an append-only rule - a convention in a docstring is not a constraint.

## Refusals are audited, not only changes

§14's last line: *"Unauthorized operations must be rejected and audited."* So
`record` is called on the refusal path too, with `succeeded = False`. An audit
trail that holds only the writes that worked cannot answer the question it is
usually asked, which is who tried.

## Why summaries rather than full before/after values

§13 says *"previous value or change summary"* and allows either. Summaries,
because §15 says sensitive information should not be placed unnecessarily into
logs, and a full row copy of a `confidential` person into an append-only table
is a second copy of the data with none of the classification's protections
around it. The summary names the fields that changed and their old and new
values *for the fields in the request*, which is what an investigation needs.
"""

from __future__ import annotations

import json
from typing import Any

from backend.db import Database, now_iso
from dba import ids

# The result vocabulary. Closed, because reports group on it.
COMMITTED = "committed"
REFUSED = "refused"
CLARIFICATION_REQUESTED = "clarification_requested"
FAILED = "failed"
REPLAYED = "replayed"
NO_CHANGE = "no_change"
RESULTS = (COMMITTED, REFUSED, CLARIFICATION_REQUESTED, FAILED, REPLAYED,
           NO_CHANGE)

SOURCE_AGENT_REQUEST = "agent_request"
SOURCE_MAINTENANCE = "maintenance"
SOURCES = (SOURCE_AGENT_REQUEST, SOURCE_MAINTENANCE)


def record(conn: Database, *, requesting_agent: str, action: str, result: str,
           succeeded: bool, actor: str | None = None,
           entity_type: str | None = None, entity_id: str | None = None,
           previous: dict | None = None, new: dict | None = None,
           request_id: str | None = None, reason: str | None = None,
           source: str = SOURCE_AGENT_REQUEST) -> str:
    """Append one audit event and return its id.

    Takes the connection rather than opening one, so that an event written
    inside a transaction rolls back with the write it describes. An audit row
    claiming a change that was rolled back is §44's failure in the one table
    that exists to be trusted."""
    if result not in RESULTS:
        raise ValueError(f"audit result={result!r} is not one of {RESULTS}")
    if source not in SOURCES:
        raise ValueError(f"audit source={source!r} is not one of {SOURCES}")

    audit_id = ids.new_id("audit")
    conn.execute(
        "INSERT INTO audit_events (audit_id, at, actor, requesting_agent, action, "
        "entity_type, entity_id, previous_summary, new_summary, request_id, "
        "reason, result, succeeded, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (audit_id, now_iso(), actor, requesting_agent, action, entity_type,
         entity_id, _summarise(previous), _summarise(new), request_id, reason,
         result, int(bool(succeeded)), source))
    return audit_id


def _summarise(values: dict | None) -> str | None:
    """A compact, stable rendering of the fields at issue.

    Sorted keys so two events on the same change compare equal as text, which
    is what makes a diff of the audit trail readable."""
    if not values:
        return None
    return json.dumps({key: values[key] for key in sorted(values)},
                      ensure_ascii=False, default=str)


def for_entity(conn: Database, entity_id: str, *, limit: int = 50) -> list[dict]:
    """§8's `history`, oldest first - the order a change is read in."""
    rows = conn.fetchall(
        "SELECT * FROM audit_events WHERE entity_id = ? ORDER BY at ASC, rowid ASC "
        "LIMIT ?", (entity_id, limit))
    return [_row(row) for row in rows]


def for_request(conn: Database, request_id: str) -> list[dict]:
    rows = conn.fetchall(
        "SELECT * FROM audit_events WHERE request_id = ? ORDER BY rowid ASC",
        (request_id,))
    return [_row(row) for row in rows]


def recent(conn: Database, *, limit: int = 50) -> list[dict]:
    rows = conn.fetchall(
        "SELECT * FROM audit_events ORDER BY rowid DESC LIMIT ?", (limit,))
    return [_row(row) for row in rows]


def counts(conn: Database) -> dict[str, int]:
    """How many events of each result, for §28's health response."""
    rows = conn.fetchall(
        "SELECT result, COUNT(*) AS n FROM audit_events GROUP BY result")
    return {row["result"]: int(row["n"]) for row in rows}


def _row(row: dict) -> dict[str, Any]:
    out = dict(row)
    out["succeeded"] = bool(out.get("succeeded"))
    for key in ("previous_summary", "new_summary"):
        if out.get(key):
            try:
                out[key] = json.loads(out[key])
            except (TypeError, ValueError):
                pass
    return out
