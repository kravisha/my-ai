"""Requests that could not be served, kept so they can be served later
(Task 01 §4.2.3).

> *"If the local answer is genuinely inadequate, say so in the agent's own
> terms ... and queue the request for retry."*

The queue is the half of that sentence that makes the other half honest. "I'll
retry shortly" said by a system with nowhere to write the request down is a
promise nobody kept, and Krish would discover that by it never happening.

## Append-only JSONL, like the call log beside it

One file, one line per state change, the latest line per `request_id` winning.
Not SQLite, although this project uses SQLite for everything that is really a
database, and the difference is worth stating: a queue entry is written from an
exception handler in whichever of several processes happened to be serving the
request, and read by one nightly job. Append-only is the shape that survives two
processes writing at the same instant without either of them holding a lock
during a user's failed turn.

A superseded line is left where it is rather than rewritten. The history of a
retried request - queued, attempted, failed, attempted again - is the thing the
self-diagnosis reports on, and a queue that only holds current state would
answer "how often does this happen" with "never, right now".

## What is never stored

The user's full request. `summary` is the same 200 characters the call log
holds, for the same reason. A retry therefore re-runs a request by its id
against whatever conversation state still exists; it does not replay a stored
prompt, and this module deliberately does not have the material to.

## What this does NOT do, stated here rather than discovered

**Nothing automatically re-executes a queued request.** §4.2.3 asks for the
request to be queued, and it is - written down, counted, reported in the
nightly self-diagnosis and in the morning brief, and closed out by
`abandon_exhausted` once its attempts are spent.

Re-executing it is a larger change than this task, and doing it badly would be
worse than not doing it. A Gateway turn is a tool loop over a conversation held
in a database owned by the thread that opened it; replaying one means deciding
what the user sees when an answer arrives twenty minutes after they asked, in a
conversation they have since continued. That is a product decision about
Jarvis's behaviour, and §8 rules it out of scope here. The queue is the part
that has to exist first either way - without it the decision would have nothing
to act on, and "I'll retry shortly" would be a sentence with nothing behind it.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import model_calls, router_config

SCHEMA_VERSION = 1

QUEUE_FILE_NAME = "retry_queue.jsonl"

STATUS_QUEUED = "queued"
STATUS_RETRIED = "retried"
STATUS_ABANDONED = "abandoned"
STATUSES = (STATUS_QUEUED, STATUS_RETRIED, STATUS_ABANDONED)


def queue_path() -> Path:
    return model_calls.log_dir() / QUEUE_FILE_NAME


def _append(entry: dict) -> dict:
    try:
        directory = queue_path().parent
        directory.mkdir(parents=True, exist_ok=True)
        with queue_path().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, default=str) + "\n")
    except OSError:  # pragma: no cover - a full or read-only disk
        # Same trade as the call log: this is bookkeeping wrapped around a turn
        # that has already failed, and it must not turn one failure into two.
        pass
    return entry


def _now() -> datetime:
    return datetime.now(timezone.utc)


def enqueue(*, request_id: str | None = None, summary: str | None = None,
            reason: str = "capacity", attempts: int = 0) -> dict:
    """Record that this request still wants answering.

    `attempts` is how many have already been made, so a caller retrying an
    entry passes the count forward and `max_retries` means what it says."""
    delay = router_config.retry_after_seconds()
    now = _now()
    return _append({
        "schema_version": SCHEMA_VERSION,
        "timestamp": now.isoformat(),
        "request_id": request_id or model_calls.current_request_id() or "unknown",
        "request_summary": summary,
        "reason": reason,
        "attempts": attempts,
        "next_attempt_at": (now + timedelta(seconds=delay)).isoformat(),
        "status": STATUS_QUEUED,
    })


def mark(request_id: str, status: str, detail: str | None = None) -> dict:
    if status not in STATUSES:
        raise ValueError(f"status={status!r} is not one of {STATUSES}")
    return _append({
        "schema_version": SCHEMA_VERSION,
        "timestamp": _now().isoformat(),
        "request_id": request_id,
        "status": status,
        "detail": detail,
    })


def entries() -> list[dict]:
    """Every line, oldest first. The history, not the current state."""
    path = queue_path()
    if not path.exists():
        return []
    found = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:  # pragma: no cover
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("request_id"):
            found.append(entry)
    return found


def current() -> dict[str, dict]:
    """The latest state of each request, by id."""
    state: dict[str, dict] = {}
    for entry in entries():
        existing = state.get(entry["request_id"], {})
        state[entry["request_id"]] = {**existing, **entry}
    return state


def due(now: datetime | None = None) -> list[dict]:
    """Queued requests whose wait has elapsed and whose attempts remain.

    An entry over `max_retries` is not returned and is not silently dropped:
    `abandon_exhausted` is what closes it, so that "we gave up on this" is a
    written fact rather than an absence."""
    moment = now or _now()
    limit = router_config.max_retries()
    ready = []
    for entry in current().values():
        if entry.get("status") != STATUS_QUEUED:
            continue
        if int(entry.get("attempts") or 0) >= limit:
            continue
        stamp = entry.get("next_attempt_at")
        if stamp and _parse(stamp) and _parse(stamp) > moment:
            continue
        ready.append(entry)
    return sorted(ready, key=lambda item: item.get("timestamp", ""))


def abandon_exhausted() -> list[dict]:
    limit = router_config.max_retries()
    closed = []
    for entry in current().values():
        if entry.get("status") != STATUS_QUEUED:
            continue
        if int(entry.get("attempts") or 0) < limit:
            continue
        closed.append(mark(entry["request_id"], STATUS_ABANDONED,
                           f"{limit} attempts made without success"))
    return closed


def _parse(stamp: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def summary(since: datetime | None = None) -> dict:
    """What the brief and the nightly report say about the queue."""
    rows = entries()
    if since is not None:
        rows = [row for row in rows
                if (_parse(row.get("timestamp", "")) or _now()) >= since]
    queued = [row for row in rows if row.get("status") == STATUS_QUEUED]
    return {
        "queued": len(queued),
        "retried": len([r for r in rows if r.get("status") == STATUS_RETRIED]),
        "abandoned": len([r for r in rows if r.get("status") == STATUS_ABANDONED]),
        "reasons": sorted({row.get("reason") for row in queued if row.get("reason")}),
        "path": str(queue_path()),
    }
