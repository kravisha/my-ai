"""Making things fail on purpose, on a schedule, during a real run.

The lifecycle catalogue has carried an `injectable` flag since it was written -
"whether a scenario can cause this on demand in a live run" - and for
thirty-six events the answer was yes in the catalogue and no in fact. Nothing
could cause anything. The fault-tolerance work made that worse rather than
better: four executive-failure events were declared injectable, so the machinery
that notices a dead COO had no way to be exercised by the machinery that is
supposed to prove it works.

The Fault Tolerance Framework's §15 is explicit about why that matters: the
purpose of a fault simulation "is not merely to prove that processes restart. It
is to prove that the organization notices, assigns responsibility, recovers
coherently, and learns."

## Only what this code can actually cause

The same entry rule the catalogue keeps. §15 lists thirteen scenarios; three are
implemented here because three are real:

- **kill** - terminate a process abruptly, so it never runs its own cleanup. This
  is what a crash *is*: no clean exit, no `mark_process_stopped`, just a heartbeat
  that stops advancing.
- **stop** - request retirement through the ordinary path, so the agent winds down
  on its own terms. Its value is as the control case: a watcher must tell this
  apart from a crash, and a fault suite that only ever kills cannot show that it
  does.
- **lock_database** - hold an exclusive write lock for a while, which is §15's
  "database temporarily unavailable" and the one failure that touches every agent
  at once, since SQLite is the only coordination channel.

Deliberately absent, and named so nobody assumes otherwise: hanging a process
(alive, responsive to nothing) needs a suspend primitive Windows does not offer
without a debugger or a third dependency; network partition has no network to
partition, because coordination is a file; and simultaneous multi-failure is
composition, which a schedule already expresses.

## Targets are read from the registry, not tracked

A fault names an identity - `coo-1`, `explorer-1` - and the pid comes from
`agent_registry`. The harness never sees those processes: the Controller spawns
them, and they are grandchildren of the run. Reading the pid the organization
itself recorded is both simpler and more honest, because it fails in the
interesting way: if the registry's pid is wrong, a fault that cannot find its
target says so rather than killing something else.
"""

from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from backend import fi_db

# What a fault may be. Kept as a tuple so an unknown action is refused at parse
# time, when the scenario is being read, rather than at the moment it was meant
# to fire - a scenario that silently does nothing is the failure mode this whole
# module exists to remove.
ACTIONS = ("kill", "stop", "lock_database")

# How long a database lock is held if a scenario does not say.
DEFAULT_LOCK_SECONDS = 5.0


class FaultError(ValueError):
    """A fault that cannot be parsed or cannot be carried out."""


@dataclass
class Fault:
    """One thing that will go wrong, and when."""

    at_seconds: float
    action: str
    target: str | None = None
    seconds: float | None = None
    fired_at: str | None = None
    outcome: str | None = None

    def describe(self) -> str:
        target = f" {self.target}" if self.target else ""
        return f"{self.action}{target} at +{self.at_seconds:g}s"


@dataclass
class FaultSchedule:
    """The faults a scenario declares, in the order they fire."""

    faults: list[Fault] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.faults)

    def due(self, elapsed: float) -> list[Fault]:
        return [f for f in self.faults if f.fired_at is None and elapsed >= f.at_seconds]

    def record(self) -> list[dict]:
        """What actually happened, for the run manifest. A fault that never fired
        is reported as such rather than omitted: a run whose faults did not land
        proved nothing, and the manifest is where that has to be visible."""
        return [
            {
                "at_seconds": fault.at_seconds,
                "action": fault.action,
                "target": fault.target,
                "fired_at": fault.fired_at,
                "outcome": fault.outcome,
            }
            for fault in self.faults
        ]


def parse(raw) -> FaultSchedule:
    """Read a scenario's `faults:` block.

    Validated here, at load time, for the reason the action list gives: a fault
    that turns out to be unspellable at second 40 of a five-minute run has wasted
    the run."""
    if raw is None:
        return FaultSchedule()
    if not isinstance(raw, list):
        raise FaultError("faults must be a list")

    faults = []
    for index, entry in enumerate(raw):
        where = f"faults[{index}]"
        if not isinstance(entry, dict):
            raise FaultError(f"{where} must be a mapping")
        missing = {"at_seconds", "action"} - set(entry)
        if missing:
            raise FaultError(f"{where} is missing {sorted(missing)}")

        action = entry["action"]
        if action not in ACTIONS:
            raise FaultError(
                f"{where} has unknown action {action!r}; this code can cause {', '.join(ACTIONS)}"
            )

        target = entry.get("target")
        if action in ("kill", "stop") and not target:
            raise FaultError(f"{where} ({action}) needs a target identity")

        try:
            at_seconds = float(entry["at_seconds"])
        except (TypeError, ValueError):
            raise FaultError(f"{where} has a non-numeric at_seconds") from None
        if at_seconds < 0:
            raise FaultError(f"{where} fires before the run starts")

        faults.append(
            Fault(
                at_seconds=at_seconds,
                action=action,
                target=target,
                seconds=float(entry["seconds"]) if entry.get("seconds") is not None else None,
            )
        )

    return FaultSchedule(sorted(faults, key=lambda fault: fault.at_seconds))


def fire(fault: Fault, db_path: str | Path) -> str:
    """Carry out one fault. Returns what happened, in the words the manifest will
    carry.

    Never raises for an ordinary failure - a target that has already died is a
    perfectly normal thing to find, and a scenario should record it rather than
    end the run."""
    fault.fired_at = fi_db._now()
    try:
        if fault.action == "kill":
            fault.outcome = _kill(fault.target, db_path)
        elif fault.action == "stop":
            fault.outcome = _stop(fault.target, db_path)
        elif fault.action == "lock_database":
            fault.outcome = _lock_database(db_path, fault.seconds or DEFAULT_LOCK_SECONDS)
        else:  # pragma: no cover - parse() refuses these
            fault.outcome = f"unknown action {fault.action!r}"
    except Exception as failure:  # noqa: BLE001 - recorded, never fatal to the run
        fault.outcome = f"failed: {failure}"
    return fault.outcome


def _pid_of(identity: str, db_path: str | Path) -> int | None:
    conn = fi_db.get_connection(db_path)
    try:
        agent = fi_db.get_agent(conn, identity)
    finally:
        conn.close()
    return None if agent is None else agent["pid"]


def _kill(identity: str, db_path: str | Path) -> str:
    """Abrupt termination, with no chance to clean up.

    Deliberately not `terminate()` on Windows for the reason harness.py records
    about uvicorn: a signal the process can handle produces a *clean* exit, and a
    clean exit is the one thing this fault must not cause. taskkill /F is the
    local equivalent of SIGKILL."""
    pid = _pid_of(identity, db_path)
    if pid is None:
        return f"{identity} has no registry row; nothing to kill"

    if sys.platform == "win32":
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return f"{identity} (pid {pid}) could not be killed: {result.stderr.strip()}"
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return f"{identity} (pid {pid}) was already gone"

    return f"killed {identity} (pid {pid})"


def _stop(identity: str, db_path: str | Path) -> str:
    """The control case: a graceful retirement through the ordinary path.

    A fault suite that only ever kills cannot show that a watcher tells a
    deliberate stop apart from a crash, which is the distinction the two-axis
    lifecycle exists for."""
    conn = fi_db.get_connection(db_path)
    try:
        if fi_db.get_agent(conn, identity) is None:
            return f"{identity} has no registry row; nothing to stop"
        fi_db.request_retirement(conn, identity)
    finally:
        conn.close()
    return f"requested retirement of {identity}"


def _lock_database(db_path: str | Path, seconds: float) -> str:
    """Hold an exclusive write lock, so every agent meets a database that will
    not accept writes.

    §15's "database temporarily unavailable", and the only fault here that
    touches the whole organization at once - SQLite is the sole coordination
    channel, so this is the closest thing this architecture has to a network
    partition.

    Blocking on purpose: the harness fires faults from its own thread and a lock
    that returned immediately would not be a lock."""
    connection = sqlite3.connect(str(db_path), timeout=1.0, isolation_level=None)
    try:
        connection.execute("BEGIN EXCLUSIVE")
        time.sleep(seconds)
        connection.execute("ROLLBACK")
    except sqlite3.OperationalError as busy:
        return f"could not take an exclusive lock: {busy}"
    finally:
        connection.close()
    return f"held an exclusive database lock for {seconds:g}s"
