"""Jarvis's own log: everything he says about himself, written down.

Krish, 2026-09-23: *"Have Jarvis have an extensive verbose logging system and
the habit of frequently scanning them and seeking faults and behavior patterns
... His beauty lies in the beauty of these log files with no error messages or
unnecessary warnings."*

Before this, there was nothing to scan. Nothing in the codebase configured a
logging handler - no `basicConfig`, no `FileHandler`, no `dictConfig` - so all
nineteen `logger.warning`/`error`/`exception` call sites wrote to stderr and
vanished with the process. The only durable log was `logs/model_calls.jsonl`,
which is about model routing and nothing else.

## One handler, no call-site changes

That absence turned out to be the opportunity. Installing a single structured
handler on the root logger makes **every** existing call site durable and
machine-readable at once, and every future one for free. Nobody has to remember
to log to the right place, because there is only one place and `logging` already
routes to it.

So this module adds no `log_this()` function for callers to adopt. The API is
`logging.getLogger(__name__).warning(...)`, which every module already uses.

## Structured, because it is read by a program before it is read by a person

A line of prose is greppable; a JSON object is groupable. `gateway/logscan.py`
ranks faults by how often the same one recurs, and that is only possible if
"the same one" is decidable - which means the logger name, the module, the line
and the exception type have to survive as fields rather than be embedded in a
sentence. The human-readable rendering is still there as `message`.

## What must never end up in here

**No user content.** The conversation lives in `gateway.db` behind the privacy
boundary; a log that quoted it would be a second copy outside that boundary,
and a log Jarvis scans is a log the model reads. Messages are capped at
`MAX_MESSAGE` and passed through `redact` on the way in, which removes the
shapes a secret takes - a bearer token, an assignment to something named like
a key, a long hex string.

Redaction is a safety net and not a licence: the rule is still that call sites
do not log what was said. The net exists because the cost of being wrong once
is a credential in a file a model reads.

## Failing to log is never allowed to break anything

`emit` cannot raise. It is wrapped around whatever the process was actually
doing, and a full disk must not become a failed request. A write that fails is
counted, and `state()` reports the count - so a log that has silently stopped
recording is itself visible, which is the one failure a logging system cannot
afford to hide.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from app import jsonlog, model_calls

ENABLED_ENV = "JARVIS_EVENT_LOG"
LEVEL_ENV = "JARVIS_EVENT_LOG_LEVEL"

LOG_FILE_NAME = "events.jsonl"

# Long enough for a real message with a path and a reason in it, short enough
# that a stray payload cannot be smuggled through one.
MAX_MESSAGE = 2000

# The handler's own name, so `install` is idempotent: a second call finds the
# handler already attached rather than adding a second one and writing every
# line twice.
HANDLER_NAME = "jarvis-eventlog"

DEFAULT_LEVEL = logging.INFO

# The shapes a secret takes. Deliberately a short list of high-confidence
# patterns rather than a clever general rule: a redactor that mangles ordinary
# messages makes the log harder to read, and a log nobody can read is the thing
# this module exists to prevent.
_SECRETS = (
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)\b([a-z_]*(?:token|secret|password|api[_-]?key))"
               r"\s*[=:]\s*\S+"),
    re.compile(r"\b[0-9a-f]{32,}\b"),
)

_LOCK = threading.Lock()
_STATE = {"installed": False, "service": None, "written": 0, "failed": 0}


def log_path() -> Path:
    """Beside the model call log, and redirected by the same environment
    variable - so a test that redirects one redirects both, and neither can
    write into the developer's checkout by accident."""
    return model_calls.log_dir() / LOG_FILE_NAME


def enabled() -> bool:
    return (os.environ.get(ENABLED_ENV, "1") or "1").strip() not in ("0", "false", "no")


def level() -> int:
    named = (os.environ.get(LEVEL_ENV) or "").strip().upper()
    if named:
        resolved = logging.getLevelName(named)
        if isinstance(resolved, int):
            return resolved
    return DEFAULT_LEVEL


def redact(text: str) -> str:
    """Remove the shapes a secret takes, and say that something was removed.

    Replacing rather than dropping the line: a message with a redaction marker
    in it still tells the reader what happened, and a silently truncated one
    does not."""
    out = str(text)
    for pattern in _SECRETS:
        out = pattern.sub(lambda match: f"{match.group(1)} [redacted]"
                          if match.lastindex else "[redacted]", out)
    return out


def _clean(text: str) -> str:
    return redact(str(text))[:MAX_MESSAGE]


class JsonlHandler(logging.Handler):
    """Writes one JSON object per record, and never raises."""

    def __init__(self, service: str) -> None:
        super().__init__(level=level())
        self.name = HANDLER_NAME
        self.service = service

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        try:
            entry = build(record, self.service)
        except Exception:  # noqa: BLE001 - formatting must not break the caller
            _STATE["failed"] += 1
            return
        if jsonlog.append(log_path(), entry,
                          retention_days=model_calls.retention_days()):
            _STATE["written"] += 1
        else:
            _STATE["failed"] += 1


def build(record: logging.LogRecord, service: str) -> dict:
    """One log record as the object a scanner groups on.

    `request_id` ties a line to the turn it happened in, read from the same
    context variable `app/model_calls.py` sets - so a fault found here can be
    followed into the model calls that were made around it without either side
    having been designed for the other."""
    entry = {
        "at": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
        "level": record.levelname,
        "service": service,
        "logger": record.name,
        "module": record.module,
        "function": record.funcName,
        "line": record.lineno,
        "message": _clean(record.getMessage()),
        "request_id": model_calls.current_request_id(),
    }
    if record.exc_info and record.exc_info[0] is not None:
        kind, value, _ = record.exc_info
        entry["exception"] = getattr(kind, "__name__", str(kind))
        entry["exception_message"] = _clean(value)
    return entry


def install(service: str, *, force: bool = False) -> bool:
    """Attach the handler to the root logger. Idempotent.

    Called once per process from its entry point. `force` re-attaches after a
    test has torn the logging configuration down."""
    if not enabled():
        return False
    with _LOCK:
        root = logging.getLogger()
        existing = [handler for handler in root.handlers
                    if getattr(handler, "name", None) == HANDLER_NAME]
        if existing and not force:
            return False
        for handler in existing:
            root.removeHandler(handler)
        handler = JsonlHandler(service)
        root.addHandler(handler)
        # The root logger's own level gates what reaches any handler, so a
        # root left at WARNING would silently discard every INFO this module
        # was installed to capture.
        if root.level > handler.level or root.level == logging.NOTSET:
            root.setLevel(handler.level)
        _STATE.update({"installed": True, "service": service})
        return True


def uninstall() -> None:
    with _LOCK:
        root = logging.getLogger()
        for handler in list(root.handlers):
            if getattr(handler, "name", None) == HANDLER_NAME:
                root.removeHandler(handler)
        _STATE.update({"installed": False, "service": None})


def records(*, since: datetime | None = None, until: datetime | None = None,
            limit: int = jsonlog.MAX_RECORDS) -> list[dict]:
    """Everything logged in the window, oldest first."""
    return list(jsonlog.read(log_path(), since=since, until=until, limit=limit))


def state() -> dict:
    """What the logger itself has been doing.

    `failed` is the field that matters: a log that has quietly stopped
    recording is the one failure a logging system cannot afford to hide."""
    return {**_STATE, "path": str(log_path()), "enabled": enabled(),
            "level": logging.getLevelName(level())}


def reset_for_test() -> None:
    uninstall()
    _STATE.update({"written": 0, "failed": 0})
