"""The AgentProcess contract every spawned agent implements (addendum 10
Phase A). Every agent: registers itself in fi_db on startup, runs a
heartbeat + retire-poll loop, and exits itself cleanly when told to retire.

Stopping is cooperative, not forced. The Controller sets a flag
(fi_db.request_retirement or fi_db.request_process_stop) and the agent's own
loop notices it and exits, having finished the cycle it was in. The flag is a
database row rather than a signal or call between processes, which is what keeps
the no-direct-IPC rule intact.

Two distinct signals, and the difference matters for correctness: retirement
changes organizational standing (lifecycle_state becomes dormant), a stop does
not. A stopped agent stays in service and is restaffed on the next server start;
a retired one waits for an explicit resume.

Internal rationale: INT-PHIL-0013, INT-PHIL-0014
"""

import os
import sys
import time

from agents import introspection
from backend import fi_db
from backend.version import code_version

HEARTBEAT_INTERVAL_SECONDS = 1.0


def _answer_operator_question(conn, identity: str, role: str) -> None:
    """Answer one pending UQI question per cycle, if any (addendum 14 §7).

    Lives in the shared loop rather than in each agent, so every agent - present
    and future - is queryable by construction rather than by remembering to
    implement it. Answering is a property of *being* an agent here.

    One per cycle, not a drain loop: a burst of questions must not starve the
    agent's actual work, and the operator asking them is a human who will wait a
    second. Failures are swallowed for the same reason work_fn's are - a
    malformed question must cost a cycle, never the process.

    Recording the pid is what makes the answer meaningful. It proves a live
    process replied rather than the database being read on the agent's behalf,
    which is the whole distinction between this and GET /admin/agents/{id}."""
    try:
        request = fi_db.fetch_next_uqi_request(conn, identity)
        if request is None:
            return
        # A fresh heartbeat before the slow step, for the same reason Explorer
        # and Analysis do it: composing an answer can outlast the health
        # check's staleness threshold and get a healthy agent marked crashed.
        fi_db.record_heartbeat(conn, identity)
        answer = introspection.answer_question(conn, identity, request["question"])
        fi_db.answer_uqi_request(conn, request["id"], answer, os.getpid())
    except Exception as exc:
        print(f"[{role}:{identity}] uqi error: {exc}", file=sys.stderr)


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
    # Computed here, once per life, not per heartbeat: which code this process
    # is actually running (Directive E17; backend/version.py never guesses).
    fi_db.register_agent(conn, identity, role, os.getpid(), behavior_version=code_version())

    try:
        while True:
            if work_fn is not None:
                try:
                    work_fn(conn)
                except Exception as exc:
                    print(f"[{role}:{identity}] work_fn error: {exc}", file=sys.stderr)
            _answer_operator_question(conn, identity, role)
            fi_db.record_heartbeat(conn, identity)
            if fi_db.is_retirement_requested(conn, identity):
                break
            # A stop is not a retirement. The finally block below reports this
            # process as stopped, but organizational standing is untouched, so
            # COO's baseline check will ask for this role again the moment a
            # server comes back up.
            if fi_db.is_stop_requested(conn, identity):
                print(f"[{role}:{identity}] stop requested - exiting", file=sys.stderr)
                break
            time.sleep(HEARTBEAT_INTERVAL_SECONDS)
    finally:
        # Reports only that this process is ending. Whether the agent is
        # still in service is not its call - if it was retired, the
        # Controller already set lifecycle_state='dormant', and this simply
        # completes that; if it wasn't, the agent stays organizationally
        # active with a stopped process, which COO will refill.
        fi_db.mark_process_stopped(conn, identity)
        conn.close()
