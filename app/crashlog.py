"""What is left behind when the process dies, and what was true when it started.

Krish, 2026-09-23: *"I want extensive logs so that we should be able to find out
what went wrong from the logs if anything fails to work in the target PC."*

`app/eventlog.py` records what a running process says about itself. It cannot
record the two cases that matter most when something has failed on a machine
nobody can reach:

**A crash before logging is configured.** A missing dependency, a bad
environment variable, a syntax error in a module imported at startup - none of
these reach `lifespan`, so the handler is never installed and the event log is
empty. The log's silence looks identical to the service never having been asked
to start.

**A crash that is not an exception.** A segfault in a C extension, a hard
interpreter abort, a `MemoryError` that takes the process before anything can be
written. `faulthandler` is the only thing that catches those, and it has to be
armed in advance because by definition nothing is running afterwards.

## The breadcrumb is half the value

`breadcrumb()` writes one line at startup saying what the process is, which
commit it is, which Python, and where. That line is what makes **"it never
started"** distinguishable from **"it started and died"** - and on a remote
machine those two have completely different causes and completely different
fixes. Without it, an empty log is ambiguous and the ambiguity is unresolvable.

## It writes its own file, not just the event log

A crash record that could only be written through the logging system would share
the logging system's failure modes, which is the wrong bet at exactly the moment
it matters. So a crash goes to a plain file under `logs/crashes/` first, and to
the event log as well if that still works. Two chances, and the one that does
not depend on anything is tried first.
"""

from __future__ import annotations

import faulthandler
import logging
import os
import platform
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path

from app import model_calls

logger = logging.getLogger("app.crashlog")

CRASH_DIR_NAME = "crashes"
BREADCRUMB_FILE = "startup.jsonl"

# Deliberately NOT a `.log`. `crashes()` globs `*.log` for crash records, and the
# first version named this one `<service>-faulthandler.log` - so it was returned
# as though it were a crash, and because the list sorts by name descending it
# sorted *first*, hiding the newest real crash behind an empty file. A support
# bundle still wants it (it holds hard-abort tracebacks that no excepthook sees),
# which is what `fault_streams()` is for.
FAULTHANDLER_SUFFIX = ".faulthandler.txt"

ENABLED_ENV = "JARVIS_CRASH_LOG"

# How many crash files to keep. Enough to see a pattern - the same crash four
# times in a minute is a different problem from four different ones - and few
# enough that a crash loop cannot fill the disk.
KEEP_CRASHES = 50

_INSTALLED = {"service": None, "handle": None}


def enabled() -> bool:
    return (os.environ.get(ENABLED_ENV, "1") or "1").strip() not in ("0", "false", "no")


def crash_dir() -> Path:
    return model_calls.log_dir() / CRASH_DIR_NAME


def breadcrumb_path() -> Path:
    return model_calls.log_dir() / BREADCRUMB_FILE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _code_version() -> str | None:
    """The running commit, without importing the Gateway.

    `gateway/identity.py` answers this properly and shells out to git; this is
    the cheap half, because a breadcrumb must not be able to fail or hang. An
    unknown version is reported as unknown rather than guessed."""
    override = (os.environ.get("JARVIS_CODE_VERSION") or "").strip()
    if override:
        return override
    stamped = Path(__file__).resolve().parent.parent / "DEPLOYED-COMMIT.txt"
    try:
        text = stamped.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text.split()[0] if text else None


def breadcrumb(service: str, *, extra: dict | None = None) -> dict:
    """Record that this process reached the point of being able to say so.

    Written before anything else, so that an empty log after it means the
    process died, and no line at all means it was never started. Those are
    different problems and the difference is not otherwise recoverable."""
    from app import jsonlog

    entry = {
        "at": _now(),
        "event": "startup",
        "service": service,
        "pid": os.getpid(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "executable": sys.executable,
        "cwd": os.getcwd(),
        "code_version": _code_version(),
        **(extra or {}),
    }
    jsonlog.append(breadcrumb_path(), entry,
                   retention_days=model_calls.retention_days())
    return entry


def record(service: str, kind: str, detail: str, *,
           trace: str | None = None) -> Path | None:
    """Write one crash record. Returns the file, or None if it could not.

    The file first, the event log second. A crash record that could only be
    written through the logging system would share its failure modes at exactly
    the moment that matters."""
    written: Path | None = None
    try:
        directory = crash_dir()
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        written = directory / f"{service}-{stamp}.log"
        written.write_text(
            f"service: {service}\n"
            f"at:      {_now()}\n"
            f"kind:    {kind}\n"
            f"pid:     {os.getpid()}\n"
            f"python:  {sys.version.split()[0]}\n"
            f"version: {_code_version()}\n"
            f"platform:{platform.platform()}\n"
            f"\n{detail}\n\n{trace or ''}\n",
            encoding="utf-8")
        _prune(directory)
    except OSError:  # pragma: no cover - a full or read-only disk
        written = None

    try:
        logger.critical("%s in %s: %s", kind, service, detail)
    except Exception:  # noqa: BLE001 - logging may be exactly what is broken
        pass
    return written


def _prune(directory: Path) -> None:
    """Keep the newest few. A crash loop must not fill the disk, and the
    newest are the ones being diagnosed."""
    try:
        files = sorted(directory.glob("*.log"), key=lambda path: path.name)
    except OSError:
        return
    for stale in files[:-KEEP_CRASHES]:
        try:
            stale.unlink()
        except OSError:
            continue


def _excepthook(kind, value, tb) -> None:
    record("unknown" if not _INSTALLED["service"] else str(_INSTALLED["service"]),
           "unhandled exception",
           f"{getattr(kind, '__name__', kind)}: {value}",
           trace="".join(traceback.format_exception(kind, value, tb)))
    sys.__excepthook__(kind, value, tb)


def _thread_excepthook(args) -> None:
    """A daemon thread dying silently is the failure this catches.

    The upkeep loop, the DBA's backup scheduler and the technology review all
    run on threads or tasks that outlive no request. Without this, one of them
    raising takes the thread and nothing else - the feature simply stops
    existing and nobody is told."""
    record(str(_INSTALLED["service"] or "unknown"),
           f"unhandled exception in thread {args.thread.name if args.thread else '?'}",
           f"{getattr(args.exc_type, '__name__', args.exc_type)}: {args.exc_value}",
           trace="".join(traceback.format_exception(
               args.exc_type, args.exc_value, args.exc_traceback)))


def install(service: str) -> bool:
    """Arm the crash handlers for this process. Idempotent.

    Called as early as possible - before the application is imported where that
    can be arranged - because everything it catches happens at times when it is
    too late to start."""
    if not enabled():
        return False
    _INSTALLED["service"] = service

    try:
        directory = crash_dir()
        directory.mkdir(parents=True, exist_ok=True)
        handle = (directory / f"{service}{FAULTHANDLER_SUFFIX}").open(
            "a", encoding="utf-8")
        faulthandler.enable(file=handle, all_threads=True)
        _INSTALLED["handle"] = handle
    except (OSError, RuntimeError, ValueError):
        # A hard abort will go unrecorded; the excepthooks below still work,
        # and an interpreter that cannot open a file has larger problems.
        faulthandler.enable(all_threads=True)

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    return True


def uninstall() -> None:
    sys.excepthook = sys.__excepthook__
    threading.excepthook = threading.__excepthook__
    faulthandler.disable()
    handle = _INSTALLED.get("handle")
    if handle is not None:
        try:
            handle.close()
        except OSError:
            pass
    _INSTALLED.update({"service": None, "handle": None})


def crashes(limit: int = KEEP_CRASHES) -> list[Path]:
    """The crash records, newest first. One file per unhandled exception."""
    try:
        return sorted(crash_dir().glob("*.log"),
                      key=lambda path: path.name, reverse=True)[:limit]
    except OSError:
        return []


def fault_streams() -> list[Path]:
    """The faulthandler files - hard aborts, which no excepthook ever sees.

    Separate from `crashes()` because they are append-only streams rather than
    one-file-per-event, and mixing them made the newest real crash unreachable.
    A support bundle collects both."""
    try:
        return sorted(crash_dir().glob(f"*{FAULTHANDLER_SUFFIX}"))
    except OSError:
        return []


def state() -> dict:
    return {"installed": _INSTALLED["service"] is not None,
            "fault_streams": len(fault_streams()),
            "service": _INSTALLED["service"],
            "enabled": enabled(),
            "crash_dir": str(crash_dir()),
            "breadcrumbs": str(breadcrumb_path()),
            "recorded": len(crashes())}
