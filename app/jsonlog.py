"""Appending to a rotated JSONL log, and reading one back.

Extracted from `app/model_calls.py`, which has been doing this correctly since
the call log existed and was about to acquire a second copy of itself when the
event log arrived. Two implementations of "rotate at write time and tolerate
another process racing you" is one more than anybody can keep right.

## Why rotation happens at write time and not in a handler

`TimedRotatingFileHandler` assumes it owns the file. This system is a
population of separate processes - the backend, the Controller, every agent,
the Gateway, the DBA - all appending to one path, and each one believing it
owns the file is how a log loses lines.

Renaming here can race between two processes on the same second. The loser
finds the target already there and keeps appending to the live file, which
costs at worst one day's lines sharing a neighbour's file and never costs a
line. **Losing a line to win tidiness is the wrong trade for a log whose whole
purpose is to be complete** - and it is more wrong now than when that sentence
was first written, because the log is about to become the thing Jarvis reads to
understand himself. A gap in it is a gap in what he can know about his own
behaviour.

## Reading is part of this module, not the caller's problem

A day's log is not one file. `read` walks the live file and the rotated ones in
date order, skips lines that will not parse rather than stopping at them, and
bounds how much it returns. A scanner that fell over on one corrupt line would
be a scanner that stops working on exactly the day something went wrong.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

LOG = logging.getLogger("app.jsonlog")

# A hard ceiling on a single read, so a caller cannot accidentally pull a
# month of lines into memory. Callers that want more ask again with a window.
MAX_RECORDS = 50_000


def append(path: Path, entry: dict, *, retention_days: int,
           today: str | None = None) -> bool:
    """Append one record, rotating first. Returns whether it was written.

    Never raises. Every caller is telemetry wrapped around something a user is
    waiting for, and a full disk must not become a failed answer."""
    stamp = today or (str(entry.get("at") or entry.get("timestamp") or "")[:10]
                      or datetime.now(timezone.utc).date().isoformat())
    try:
        line = json.dumps(entry, default=str)
    except (TypeError, ValueError) as bad:  # pragma: no cover - default=str is broad
        LOG.debug("could not serialise a log entry: %s", bad)
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        rotate(path, stamp, retention_days=retention_days)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return True
    except OSError as bad:  # pragma: no cover - a full or read-only disk
        LOG.debug("could not append to %s: %s", path, bad)
        return False


def rotate(path: Path, today: str, *, retention_days: int) -> None:
    """Daily rotation, done at write time. See the module docstring."""
    if not path.exists():
        return
    try:
        stamped = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return
    day = stamped.date().isoformat()
    if day >= today:
        return
    target = path.with_name(f"{path.stem}-{day}{path.suffix}")
    try:
        if not target.exists():
            path.rename(target)
    except OSError:
        return
    prune(path.parent, path.stem, path.suffix, today,
          retention_days=retention_days)


def prune(directory: Path, stem: str, suffix: str, today: str, *,
          retention_days: int) -> None:
    cutoff = (datetime.fromisoformat(today).date()
              - timedelta(days=retention_days))
    for candidate in directory.glob(f"{stem}-*{suffix}"):
        try:
            day = datetime.fromisoformat(candidate.stem[len(stem) + 1:]).date()
        except ValueError:
            continue
        if day < cutoff:
            try:
                candidate.unlink()
            except OSError:
                continue


def files(path: Path) -> list[Path]:
    """The live log and its rotated siblings, oldest first.

    The live file sorts last because its lines are the newest; the rotated ones
    carry their date in the name and sort by it."""
    rotated = []
    for candidate in path.parent.glob(f"{path.stem}-*{path.suffix}"):
        try:
            day = date.fromisoformat(candidate.stem[len(path.stem) + 1:])
        except ValueError:
            continue
        rotated.append((day, candidate))
    ordered = [candidate for _, candidate in sorted(rotated)]
    if path.exists():
        ordered.append(path)
    return ordered


def read(path: Path, *, since: datetime | None = None,
         until: datetime | None = None, limit: int = MAX_RECORDS,
         time_field: str = "at") -> Iterator[dict]:
    """Every record in the window, oldest first.

    A line that will not parse is skipped rather than raised on. A scanner that
    stopped at the first corrupt line would stop working on exactly the day
    something went wrong, which is the day it is for."""
    seen = 0
    for candidate in files(path):
        try:
            handle = candidate.open("r", encoding="utf-8")
        except OSError:
            continue
        with handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(entry, dict):
                    continue
                when = parse_time(entry.get(time_field))
                if since is not None and (when is None or when < since):
                    continue
                if until is not None and (when is None or when > until):
                    continue
                yield entry
                seen += 1
                if seen >= limit:
                    return


def parse_time(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
