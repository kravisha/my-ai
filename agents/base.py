"""The AgentProcess contract every spawned agent implements (addendum 10
Phase A). Every agent: registers itself in fi_db on startup, runs a
heartbeat + retire-poll loop, and exits itself cleanly when told to retire.

Nothing ever forcibly kills an agent process - retirement works by the
Controller setting a flag (fi_db.request_retirement) that the agent's own
loop notices and acts on. This is the concrete mechanism behind "graceful
retire": the agent retires itself, on its own terms, once it sees the
signal - matching the no-direct-IPC rule (the flag is a database row, not a
signal/call from one process to another) and letting a real agent finish
whatever it's mid-doing before exiting, rather than being cut off mid-work.
"""

import os
import sys
import time

from backend import fi_db

HEARTBEAT_INTERVAL_SECONDS = 1.0


def run_agent(identity: str, role: str, work_fn=None, db_path=None) -> None:
    """The shared run loop. `work_fn(conn)`, if given, is called once per
    cycle before the heartbeat/retire check - this is where a real agent's
    actual job (Explorer detection, Speculator search, ...) plugs in. The
    dummy agent passes nothing and just idles, which is the point of it.

    db_path defaults to the FI_DB_PATH environment variable if set, falling
    back to the real project database - lets the Controller (or a test)
    point a spawned subprocess at an isolated database without needing a
    CLI flag on every agent.

    An exception from work_fn is caught here, not left to propagate: before
    Phase C, no agent made a real network call, so this never mattered in
    practice. A transient failure (LLM API blip, malformed provider
    payload) should cost this agent one cycle, not kill the process and get
    mislabeled 'gone' (a clean exit) instead of 'crashed' - agents/coo.py's
    _evaluate_agent_health already exists specifically to catch a process
    that's actually dead; an uncaught work_fn exception must not bypass it
    by exiting cleanly enough to look intentional. Caught here once, in the
    contract every agent shares, rather than in each agent's own work_fn -
    so any future agent (including training-capable ones) gets this for
    free instead of needing to remember it."""
    if db_path is None:
        db_path = os.environ.get("FI_DB_PATH", str(fi_db.DB_PATH))
    conn = fi_db.get_connection(db_path)
    fi_db.init_schema(conn)
    fi_db.register_agent(conn, identity, role, os.getpid())

    try:
        while True:
            if work_fn is not None:
                try:
                    work_fn(conn)
                except Exception as exc:
                    print(f"[{role}:{identity}] work_fn error: {exc}", file=sys.stderr)
            fi_db.record_heartbeat(conn, identity)
            if fi_db.is_retirement_requested(conn, identity):
                break
            time.sleep(HEARTBEAT_INTERVAL_SECONDS)
    finally:
        fi_db.mark_agent_gone(conn, identity)
        conn.close()
