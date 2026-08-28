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
import threading
import time

from agents import introspection
from app import model_budget
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


# How often the liveness thread says the process is up (TQ-93, §134).
#
# Chosen against COO's 45s staleness threshold rather than against anything a
# model does: nine ticks fit inside the threshold, so losing several in a row to
# scheduling still leaves the agent detected as live. **That is the whole point of
# the separation** - a progress signal is bounded by the slowest model call, which
# a vendor sets, and this one is bounded by an interval this system chooses.
#
# The cost is one UPDATE against a WAL database every five seconds per agent.
LIVENESS_INTERVAL_SECONDS = 5.0


class _Liveness:
    """A thread that says the process is up, on its own clock.

    **Its own connection, deliberately.** `Database` wraps a single sqlite3
    connection and sqlite3 objects are not safe to share across threads; handing
    this thread the agent's connection would introduce a race into every agent in
    the organization to fix a reporting bug.

    A daemon thread, so a process that is exiting is never held open by it, and
    an `Event` rather than a sleep so a stop is immediate rather than up to one
    interval late.

    **Failures are swallowed on purpose.** This thread exists to report health and
    must never become a way for an agent to die: a locked database or a closed
    connection during shutdown is a missed tick, and a missed tick is what the
    threshold's margin is for. It is the one place in this codebase where a bare
    except is the correct answer, which is why it says so."""

    def __init__(self, identity: str, db_path: str,
                 interval: float = LIVENESS_INTERVAL_SECONDS):
        self.identity = identity
        self.db_path = db_path
        self.interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"liveness:{identity}",
                                        daemon=True)

    def start(self) -> "_Liveness":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=self.interval)

    def _run(self) -> None:
        conn = None
        try:
            conn = fi_db.get_connection(self.db_path)
            while not self._stop.is_set():
                try:
                    fi_db.record_liveness(conn, self.identity)
                except Exception:  # noqa: BLE001 - see the class docstring
                    pass
                self._stop.wait(self.interval)
        except Exception:  # noqa: BLE001 - a thread that cannot start is a missed
            pass            # signal, never a dead agent
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass


def note_governed_refusal(role: str, identity: str, refusal: Exception) -> None:
    """An instrument in force was not satisfied, so the work was not done.

    Said in its own words rather than through the `work_fn error` path, because
    those are different events and anything reading agent output has to be able
    to tell them apart. **A rule being obeyed must not look like a fault**: an
    organization whose policies make its agents appear broken will have its
    policies removed by whoever is watching the error stream.

    Not a warning either. The agent did exactly what the organization decided.
    """
    print(f"[{role}:{identity}] not filed - an instrument in force was not satisfied: {refusal}")


def read_own_record(conn, identity: str) -> int:
    """What was found about this agent's own work, read by the agent itself.

    The charter owes an agent knowledge of findings concerning its work, and the
    organization model's declared gap 1 is that *a producing agent never learns
    how its own report was judged.* Both are about **every** agent, so this lives
    in the loop every agent shares rather than in the one role that happened to
    have rulings - putting it in `agents/analysis.py` would have discharged a
    protection about agents by serving one of them (§147).

    Reading alone changes nothing, which is §118's trap. So this also files an
    appeal where the **record alone** shows a ruling is contestable - the grader
    filed the report it graded, or the ruling carries no reasoning. Whether a
    grade is *wrong* is a judgement and stays out of it; an agent appealing every
    low score would be appealing rather than disagreeing.

    Both grounds are correctly aimed and neither currently fires (§147). That is
    the honest state of a right whose occasions do not presently arise, and it is
    why this is written to report what it found rather than to be seen filing."""
    from backend import appeal

    filed = 0
    for ruling in appeal.contestable_by(conn, identity):
        try:
            appeal.file_appeal(conn, ruling_kind=ruling["kind"], ruling_id=ruling["id"],
                               appellant=identity, grounds=ruling["grounds"])
        except appeal.AppealRefused as refusal:
            # Never fatal. A right whose exercise could stop the day's work is one
            # nobody would dare use.
            print(f"[{identity}] could not contest {ruling['kind']} {ruling['id']}: {refusal}")
            continue
        filed += 1
        print(f"[{identity}] contested {ruling['kind']} {ruling['id']}: {ruling['grounds'][:90]}")
    return filed


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
    # Every model call this process makes is this agent's spend (TQ-18,
    # SPEC_RECONCILIATION §66). Declared here, in the one run loop every
    # agent shares, so a future agent is attributed without remembering to
    # ask - the same reasoning the work_fn exception guard below is written
    # here rather than in each agent.
    model_budget.set_caller(identity)
    conn = fi_db.get_connection(db_path)
    fi_db.init_schema(conn)
    # Computed here, once per life, not per heartbeat: which code this process
    # is actually running (Directive E17; backend/version.py never guesses).
    fi_db.register_agent(conn, identity, role, os.getpid(), behavior_version=code_version())

    # Started after registration so the first tick has a row to write to, and
    # before any work so an agent whose very first cycle is slow is still visibly
    # alive - which is the case §133's incident actually caught.
    liveness = _Liveness(identity, db_path).start()

    try:
        while True:
            # Before the role's own work and outside its try, because an agent's
            # record is not something it reads only on the cycles its job succeeds.
            try:
                read_own_record(conn, identity)
            except Exception as record_failure:  # noqa: BLE001
                print(f"[{identity}] could not read its own record: {record_failure}")

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
        liveness.stop()
        # Reports only that this process is ending. Whether the agent is
        # still in service is not its call - if it was retired, the
        # Controller already set lifecycle_state='dormant', and this simply
        # completes that; if it wasn't, the agent stays organizationally
        # active with a stopped process, which COO will refill.
        fi_db.mark_process_stopped(conn, identity)
        conn.close()
