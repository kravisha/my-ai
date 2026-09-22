"""The DBA taking its own backups, because that is its job (§25).

    *"This should be done by the DBA who keeps everything backed up and safe."*
    — Krish, 2026-09-21

The first version of backup left scheduling to a cron entry somebody had to
install, and said so honestly. Honest and wrong: an agent whose responsibility
is that persistent information is safe, and which needs someone else to
remember to run it, is not keeping anything safe. It is a tool that describes
a backup system. So the running DBA does it itself.

## A thread, not an async task

`backup.take` is blocking - SQLite pages and file hashing - and an async task
doing that on the event loop would stall every request for the duration. A
daemon thread with an `Event` to stop it is the simple correct shape, and the
event is what makes shutdown immediate rather than "within fifteen minutes".

## It wakes often and acts rarely

The schedule has hour granularity, so waking every fifteen minutes is enough
to notice. What stops that being fifteen backups an hour is `backup.due`,
which is idempotent through the catalogue: a backup already taken today is not
taken twice. So a machine asleep at 02:00 gets its backup at 09:15 when it
wakes up, and a machine that runs all day gets exactly one - which is the
property `app/self_diagnosis.py` chose hour-based scheduling for.

## It cannot take the service down

Every iteration is wrapped. A backup that fails - a full disk, a corrupt
store, a permission - is recorded and the loop continues, because a DBA that
stopped serving requests because it could not back itself up would have turned
a backup problem into an outage. The failure is visible in `state()` and in
`/health`, which is where an operator looks.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone

# How often to wake and ask whether anything is due. Well under an hour so the
# configured hour is not missed, well over a second so this costs nothing.
CHECK_EVERY_SECONDS = 15 * 60

# Set to 0/false to stop the DBA scheduling its own backups. On by default,
# because "the DBA keeps everything backed up" is the requirement and a
# default of off would mean every fresh install is unprotected until somebody
# notices. The test suite sets it off: a background thread writing backups
# during a test run is nondeterminism nobody asked for.
ENABLED_ENV = "DBA_AUTOBACKUP"

_THREAD: threading.Thread | None = None
_STOP: threading.Event | None = None
_STATE: dict = {
    "running": False,
    "started_at": None,
    "last_checked_at": None,
    "last_result": None,
    "checks": 0,
    "failures": 0,
}
_LOCK = threading.Lock()


def enabled() -> bool:
    raw = (os.environ.get(ENABLED_ENV, "") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    return True


def state() -> dict:
    """What the scheduler has been doing, for §28's health response.

    A backup system nobody can see the scheduler of is a backup system nobody
    trusts, and rightly: "it should be running" is not a measurement."""
    with _LOCK:
        snapshot = dict(_STATE)
    snapshot["enabled"] = enabled()
    snapshot["check_every_seconds"] = CHECK_EVERY_SECONDS
    if not snapshot["enabled"]:
        snapshot["why_not_running"] = (
            f"{ENABLED_ENV} is set off. Nothing is scheduling backups; they "
            f"have to be taken by hand or by something else calling "
            f"`python -m dba.backup --if-due`, which covers every protected "
            f"store.")
    elif not snapshot["running"]:
        snapshot["why_not_running"] = (
            "the DBA service is not running, or its lifespan did not start "
            "the scheduler. Nothing is taking backups.")
    return snapshot


def failed_stores(result: dict | None) -> list[str]:
    """Which stores did not get backed up for a reason that is not "not due".

    THE REVIEW FOUND THE SCHEDULER BLIND TO EXACTLY THIS. `run_all_if_due`
    catches every per-store error and returns them inside its result, so the
    `except` around it never fired, `failures` stayed 0 for ever, and the
    health check added to catch failing backups passed while every one of them
    failed. Observability that cannot see the thing it was built for.

    A store that is simply not due is not a failure, and neither is one that
    has never existed on this machine - `refused` covers both, and the caller
    reading `last_result` can see which."""
    if not result:
        return []
    return sorted(name for name, outcome in result.items()
                  if isinstance(outcome, dict) and "failed" in outcome)


def _record(result: dict | None, failure: str | None) -> None:
    with _LOCK:
        _STATE["last_checked_at"] = datetime.now(timezone.utc).isoformat()
        _STATE["checks"] += 1
        if failure:
            _STATE["failures"] += 1
            _STATE["last_result"] = {"failed": failure}
            return
        _STATE["last_result"] = result
        broken = failed_stores(result)
        if broken:
            _STATE["failures"] += 1
            _STATE["failed_stores"] = broken
        else:
            _STATE.pop("failed_stores", None)


def check_once() -> dict:
    """One pass: back up whatever is due, across every protected store.

    Separate from the loop so it can be called directly - by a test, by the
    CLI, or by an operator who wants it to happen now rather than at the next
    wake."""
    from dba import backup

    try:
        result = backup.run_all_if_due()
        _record(result, None)
        return result
    except Exception as bad:  # noqa: BLE001 - see the module docstring
        _record(None, f"{type(bad).__name__}: {bad}")
        return {"failed": f"{type(bad).__name__}: {bad}"}


def _loop(stop: threading.Event) -> None:
    # One pass immediately on start, so a machine that was off at the
    # scheduled hour is protected the moment it comes back rather than
    # tomorrow.
    check_once()
    while not stop.wait(CHECK_EVERY_SECONDS):
        check_once()


def start() -> bool:
    """Start the scheduler. Returns whether it is now running."""
    global _THREAD, _STOP

    if not enabled():
        return False
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return True
        _STOP = threading.Event()
        _THREAD = threading.Thread(target=_loop, args=(_STOP,),
                                   name="dba-backup-scheduler", daemon=True)
        _STATE["running"] = True
        _STATE["started_at"] = datetime.now(timezone.utc).isoformat()
        thread = _THREAD
    thread.start()
    return True


def stop(timeout: float = 5.0) -> None:
    """Stop it and wait briefly, so a shutdown does not leave a backup
    half-written."""
    global _THREAD, _STOP

    with _LOCK:
        stopper, thread = _STOP, _THREAD
        _STATE["running"] = False
    if stopper is not None:
        stopper.set()
    if thread is not None and thread.is_alive():
        thread.join(timeout=timeout)
    with _LOCK:
        # ONLY IF IT ACTUALLY STOPPED. Clearing these while the thread was
        # still alive meant the next `start()` spawned a second scheduler
        # beside the first: duplicate backups, and one thread's `prune` able
        # to unlink a file the other was hashing.
        if thread is not None and thread.is_alive():
            _STATE["running"] = True
            _STATE["why_not_running"] = (
                f"stop() waited {timeout}s and the scheduler thread is still "
                f"finishing a backup. It has been told to stop and will; "
                f"nothing new was started.")
            return
        _THREAD = None
        _STOP = None
        _STATE.pop("why_not_running", None)


def reset_for_test() -> None:
    """Forget everything. The suite shares a process between tests."""
    stop(timeout=1.0)
    with _LOCK:
        _STATE.update({"running": False, "started_at": None,
                       "last_checked_at": None, "last_result": None,
                       "checks": 0, "failures": 0})
