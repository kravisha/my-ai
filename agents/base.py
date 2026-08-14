"""The AgentProcess contract every spawned agent implements (addendum 10
Phase A). Every agent: registers itself in fi_db on startup, runs a
heartbeat + retire-poll loop, and exits itself cleanly when told to retire.

Nothing ever forcibly kills an agent process - retirement works by the
Coordinator setting a flag (fi_db.request_retirement) that the agent's own
loop notices and acts on. This is the concrete mechanism behind "graceful
retire": the agent retires itself, on its own terms, once it sees the
signal - matching the no-direct-IPC rule (the flag is a database row, not a
signal/call from one process to another) and letting a real agent finish
whatever it's mid-doing before exiting, rather than being cut off mid-work.
"""

import os
import time

from backend import fi_db

HEARTBEAT_INTERVAL_SECONDS = 1.0


def run_agent(identity: str, role: str, work_fn=None, db_path=None) -> None:
    """The shared run loop. `work_fn(conn)`, if given, is called once per
    cycle before the heartbeat/retire check - this is where a real agent's
    actual job (Explorer detection, Speculator search, ...) plugs in. The
    dummy agent passes nothing and just idles, which is the point of it.

    db_path defaults to the FI_DB_PATH environment variable if set, falling
    back to the real project database - lets the Coordinator (or a test)
    point a spawned subprocess at an isolated database without needing a
    CLI flag on every agent."""
    if db_path is None:
        db_path = os.environ.get("FI_DB_PATH", str(fi_db.DB_PATH))
    conn = fi_db.get_connection(db_path)
    fi_db.init_schema(conn)
    fi_db.register_agent(conn, identity, role, os.getpid())

    try:
        while True:
            if work_fn is not None:
                work_fn(conn)
            fi_db.record_heartbeat(conn, identity)
            if fi_db.is_retirement_requested(conn, identity):
                break
            time.sleep(HEARTBEAT_INTERVAL_SECONDS)
    finally:
        fi_db.mark_agent_gone(conn, identity)
        conn.close()
