"""Waking the organization, not starting an application (addendum 40 §4;
TASK_QUEUE TQ-30, docs/SPEC_RECONCILIATION.md §82).

Addendum 40 §4.1's flow, in order: initialize the minimum platform services,
locate the persisted identity, restore or create the root, reconnect it to the
services this machine provides, rehydrate the workspace, resume recoverable
work, and hand all ongoing control to the COO runtime.

## What "restore, do not create" means here concretely

This organization already persists the things §5.2 asks about identity: agent
names are durable (`agent_names` — a name is the agent, an identity is the
desk it sits at), the registry survives restart, and `Controller.
reconcile_on_start` refuses to start a second COO under one identity. So the
bootstrap's job is not to invent restoration; it is to *not interfere* with
the restoration that already happens, and to notice whether this machine has
ever run before.

A first run and a resumed run are genuinely different events and the operator
should be told which one they are looking at — §4.2 wants a restart to "feel
like waking the same entity, not starting a new session", and that promise is
only checkable if the system knows which it did.

## Why it starts the runtime rather than requiring one

§7.2 puts a "local COO runtime: long-lived process or service responsible for
restoring the COO root" behind the shell. A desktop application that told its
operator to open a terminal first would not be a desktop application. So this
starts the backend if nothing is listening, and leaves an already-running one
alone — a second server on the same database is precisely the duplicate the
specification forbids (§13.1's rule for the Gateway, applied to ourselves).

## The loopback requirement is not cosmetic

The shell loads the console over `http://127.0.0.1`, never from an inline HTML
string, and that is load-bearing: Chromium treats loopback as a **secure
context**, and a page without an origin loses `getUserMedia`, `localStorage`
and with them the microphone that addendum 40 §11 makes the default input
path. Measured on this machine (§82): from an inline string,
`mediaDevices: false`; from `http://127.0.0.1`, `true`.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

HOST = "127.0.0.1"
DEFAULT_PORT = 8000
PORT_ENV = "MY_AI_DESKTOP_PORT"

# How long to wait for a runtime we started to begin answering. Generous
# because first-boot does schema work; a disclosed convention, not a measured
# requirement.
RUNTIME_START_TIMEOUT_SECONDS = 90.0
RUNTIME_POLL_SECONDS = 0.5

# How long to let the runtime shut itself down before killing the tree.
# Generous: the lifespan teardown stops every agent (which can be mid-call)
# and takes the continuity shutdown backup on the way out.
SHUTDOWN_TIMEOUT_SECONDS = 60.0


def port() -> int:
    raw = os.environ.get(PORT_ENV)
    return int(raw) if raw else DEFAULT_PORT


def console_url() -> str:
    return f"http://{HOST}:{port()}/console"


def runtime_is_listening(timeout: float = 0.4) -> bool:
    """Whether something already answers on the runtime's port.

    A plain socket probe rather than an HTTP request: this runs before the
    shell exists and must not depend on the app being ready, only on the port
    being held."""
    try:
        with socket.create_connection((HOST, port()), timeout=timeout):
            return True
    except OSError:
        return False


def has_run_before() -> bool:
    """Whether this machine has an organization to wake, or is installing one.

    Read from the database file's existence rather than a marker of our own:
    a separate 'installed' flag could disagree with reality, and the database
    is the thing that actually carries the identity."""
    from backend import fi_db

    return Path(fi_db.DB_PATH).exists()


def start_runtime() -> subprocess.Popen | None:
    """Start the local COO runtime (§7.2), or return None if one is already up.

    Never starts a second one against the same database: two servers sharing
    one organization is the duplicate-brain error §13.1 forbids."""
    if runtime_is_listening():
        return None
    # CREATE_NEW_PROCESS_GROUP on Windows so the runtime can be sent
    # CTRL_BREAK_EVENT later - see `sleep_runtime` for why terminate() is not
    # good enough. simulation/harness.py learned this the same way.
    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app",
         "--host", HOST, "--port", str(port()), "--log-level", "warning"],
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        creationflags=creation_flags,
        start_new_session=(sys.platform != "win32"),
    )


def wait_for_runtime(deadline_seconds: float = RUNTIME_START_TIMEOUT_SECONDS) -> bool:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        if runtime_is_listening():
            return True
        time.sleep(RUNTIME_POLL_SECONDS)
    return False


def main(argv: list[str] | None = None) -> int:
    """§4.1's sequence, then hand control away.

    Deliberately linear and short. Anything that grows here belongs in the
    runtime or a manager behind it - see this module's own docstring and
    `desktop/__main__.py` for the invariant."""
    waking = has_run_before()
    print(f"[desktop] {'waking the existing organization' if waking else 'first run - creating one'}")

    started = start_runtime()
    if started is None:
        print(f"[desktop] runtime already listening on {HOST}:{port()}")
    elif not wait_for_runtime():
        print(f"[desktop] runtime did not answer within {RUNTIME_START_TIMEOUT_SECONDS:.0f}s", file=sys.stderr)
        started.terminate()
        return 1

    # Hand all ongoing control to the shell (§4.1's final step). The shell
    # owns the window and blocks until it closes; this function's remaining
    # job is only to put the runtime back to sleep if we were the one who
    # woke it.
    from desktop import shell

    try:
        shell.run(console_url(), waking=waking)
    finally:
        if started is not None:
            sleep_runtime(started)
    return 0


def sleep_runtime(process: subprocess.Popen, timeout: float = SHUTDOWN_TIMEOUT_SECONDS) -> bool:
    """Put the organization to sleep properly (addendum 40 §4.2).

    **`terminate()` is not good enough, and the failure is silent.** On
    Windows it bypasses uvicorn's signal handling entirely, so the FastAPI
    lifespan teardown never runs - which means `Controller.shutdown_agents`
    never runs, and every agent subprocess is orphaned and keeps writing to
    the database after the window has closed. The continuity shutdown backup
    (§59) is skipped for the same reason. Measured here first-hand: closing
    the window left twelve agent processes alive.

    `simulation/harness.py` documents the identical trap and the identical
    remedy, so this follows it: CTRL_BREAK_EVENT on Windows (which uvicorn
    *does* handle) or SIGINT elsewhere, wait for the teardown, and only fall
    back to a whole-tree kill if it will not go. `taskkill /T` because the
    agents are children of that process, and killing only the parent is how
    orphans are made.

    Returns True when the runtime shut itself down, False when it had to be
    killed - a distinction worth surfacing, because a killed runtime means
    the workspace and continuity work it owed did not happen."""
    if process.poll() is not None:
        return True

    print("[desktop] putting the organization to sleep")
    try:
        if sys.platform == "win32":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGINT)
    except Exception:  # noqa: BLE001 - a process that has already gone is fine
        pass

    try:
        process.wait(timeout=timeout)
        print("[desktop] the organization is asleep")
        return True
    except subprocess.TimeoutExpired:
        print(f"[desktop] the runtime did not stop within {timeout:.0f}s - killing the tree "
              "(agents may not have checkpointed)", file=sys.stderr)
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
        else:
            process.kill()
        return False
