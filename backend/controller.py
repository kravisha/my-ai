"""The Controller is the sole thing that ever spawns or retires an agent
process ("all agents will be spawned only by the controller... the COO...
is officer who will be directing the controller to spawn an agent on demand
and also... to retire an agent... in a controlled and smooth manner").
Mechanics only - it never invents policy, it only executes directives the
COO has placed in the coo_directives table.

**The Controller is the backend server's own agent identity** (owner
clarification, 2026-08-15): the server does not *contain* a Controller, it
comes up *as* one. So unlike every other agent it is not a spawned
subprocess - it lives inside backend/main.py's event loop - but it is
otherwise a first-class agent: it registers itself in agent_registry
(bootstrap_self), heartbeats, and marks itself gone on clean shutdown,
satisfying "every agent has a defined role, identity, state... health
state, and durable organizational record" (Org Addendum §2). It is the
first agent to exist, and it then creates COO - the startup order the specs
give literally (Consolidated §2, Org Addendum §13).

The authority split this implements (Org Addendum §15): the COO decides
operational need and *requests*; the Controller is the exclusive executor.
COO never touches a process directly - it only ever enqueues directives.

Critically, role "controller" must never appear in agents/coo.py's
BASELINE_ROLES: the Controller is the running server, so a COO that tried
to "respawn" it would be asking the Controller to Popen an agents/
controller.py that deliberately does not exist. tests/test_controller.py
guards this invariant explicitly.

Retirement is never a kill: it only ever sets a flag (fi_db.request_
retirement) that the target agent's own run loop notices and acts on
(agents/base.py) - "controlled and smooth" in the literal sense of the
agent finishing on its own terms.
"""

import os
import subprocess
import sys
from pathlib import Path

from backend import fi_db

# Environment every spawned agent gets on top of the Controller's own.
#
# PYTHONUNBUFFERED matters more than it looks. Agents inherit the backend's
# stdout, which in any real run is redirected to a log file - and Python
# block-buffers stdout when it is not a terminal. Without this, an agent's
# prints sit in a 4-8KB buffer and never reach the log, so the one place an
# agent explains its own reasoning ("[analysis] taking report #7: cross-check
# answered...") is invisible during exactly the manual verification runs that
# have found every timing defect in this project.
AGENT_ENV = {"PYTHONUNBUFFERED": "1"}

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CONTROLLER_ROLE = "controller"


def _slot_identity(role: str) -> str:
    """Permanent, role-slot agent identity (addendum_5 §4: "each role or
    agent identity maintains a durable performance record independent of
    any one process instance") - replaces the disposable {role}-{uuid4}
    scheme, under which every respawn started that role's performance
    history over from zero. Phase A/B's baseline population is exactly one
    instance per role (BASELINE_ROLES in agents/coo.py), so slot numbering
    is trivial for now - always slot 1. Real multi-instance-per-role
    scaling, and the slot-allocation policy that would need, is deferred to
    Phase C+ along with the rest of the agent lifecycle states (reserve/
    retraining/quarantine)."""
    return f"{role}-1"


class Controller:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(fi_db.DB_PATH)
        self.conn = fi_db.get_connection(self.db_path)
        fi_db.init_schema(self.conn)
        # Popen handles this Controller instance has itself spawned - only the
        # spawning process can hold/control these; not the same as everyone
        # in agent_registry, which also reflects agents from a prior run.
        self._processes: dict[str, subprocess.Popen] = {}
        self.identity = _slot_identity(CONTROLLER_ROLE)

    def bootstrap_self(self) -> str:
        """Registers the Controller as an agent in its own right - the first
        agent to exist, before it creates COO (Consolidated §2: "server
        starts; Controller Agent starts; Controller creates COO as the first
        executive agent").

        Reuses fi_db.register_agent unchanged: its ON CONFLICT path already
        handles a permanent identity coming back to life under a new pid,
        which here is exactly what a server restart is. No subprocess is
        spawned - the Controller *is* this process (os.getpid() is the
        server's own pid), which is what makes it different from every other
        agent and why it must never be in BASELINE_ROLES.

        Also records a first heartbeat immediately, so the row is never
        momentarily stale-looking to a COO health check that happens to run
        between registration and the first poll-loop tick."""
        fi_db.register_agent(self.conn, self.identity, CONTROLLER_ROLE, os.getpid())
        fi_db.record_heartbeat(self.conn, self.identity)
        return self.identity

    def record_self_heartbeat(self) -> None:
        """Called once per poll-loop tick by backend/main.py. The loop
        already runs every ~1s, far inside agents/coo.py's 45s
        HEALTH_STALE_THRESHOLD_SECONDS, so this needs no timer of its own.

        If the server dies while COO (a separate surviving subprocess) keeps
        running, this heartbeat stops advancing and COO's health evaluation
        correctly marks the Controller 'crashed' - a real signal that did
        not exist before, and one nothing will try to auto-respawn, which is
        right: a dead server cannot restart itself from the inside."""
        fi_db.record_heartbeat(self.conn, self.identity)

    def shutdown_self(self) -> None:
        """Clean server shutdown reads as a clean process stop, not a crash -
        the same distinction agents/base.py's finally block makes for
        subprocess agents.

        Note it reports process_state only: a stopped server is *not* a
        retired Controller. The Controller stays organizationally active, so
        restarting the server brings it straight back into service rather
        than requiring a resume."""
        fi_db.mark_process_stopped(self.conn, self.identity)

    def bootstrap_coo(self) -> str:
        """The one spawn that bypasses the directive queue entirely -
        there's no COO yet to have placed a directive, so the Controller
        spawns it directly as its first action on server startup (addendum
        6 §2 step 3: "the controller spawns the COO privileged client as
        the first managed process"). Every other agent, including the
        baseline population COO itself will ask for once running, goes
        through the normal directive queue in process_next_directive."""
        identity = _slot_identity("coo")
        env = {**os.environ, "FI_DB_PATH": self.db_path, **AGENT_ENV}
        process = subprocess.Popen(
            [sys.executable, "-m", "agents.coo", identity],
            cwd=PROJECT_ROOT,
            env=env,
        )
        self._processes[identity] = process
        return identity

    def process_next_directive(self) -> bool:
        """Processes one pending directive if any exist. Returns True if a
        directive was processed, False if the queue was empty - lets the
        caller (a polling loop) decide cadence rather than baking a sleep
        in here."""
        directive = fi_db.fetch_next_pending_directive(self.conn)
        if directive is None:
            return False

        if directive["directive_type"] == "spawn":
            self._handle_spawn(directive)
        elif directive["directive_type"] == "retire":
            self._handle_retire(directive)
        elif directive["directive_type"] == "resume":
            self._handle_resume(directive)
        else:
            fi_db.complete_directive(
                self.conn, directive["id"], "failure",
                detail=f"unknown directive_type: {directive['directive_type']}",
            )
        return True

    def _handle_spawn(self, directive: dict) -> None:
        role = directive["target_role"]
        identity = _slot_identity(role)
        env = {**os.environ, "FI_DB_PATH": self.db_path, **AGENT_ENV}
        try:
            process = subprocess.Popen(
                [sys.executable, "-m", f"agents.{role}", identity],
                cwd=PROJECT_ROOT,
                env=env,
            )
        except OSError as exc:
            fi_db.complete_directive(self.conn, directive["id"], "failure", detail=str(exc))
            return
        self._processes[identity] = process
        fi_db.complete_directive(self.conn, directive["id"], "success", detail=identity)

    def _handle_retire(self, directive: dict) -> None:
        """Retirement moves the agent to dormant and asks its process to wind
        down. It never deletes anything: the identity, name, and full history
        survive, and _handle_resume is the exact inverse (addendum 11 §9,
        "retirement is non-destructive and reversible")."""
        identity = directive["target_identity"]
        if fi_db.get_agent(self.conn, identity) is None:
            fi_db.complete_directive(self.conn, directive["id"], "failure", detail=f"unknown identity: {identity}")
            return
        fi_db.request_retirement(self.conn, identity)
        fi_db.complete_directive(self.conn, directive["id"], "success", detail=f"retirement requested for {identity}")

    def _handle_resume(self, directive: dict) -> None:
        """Brings a dormant agent back into service. Only restores its
        organizational standing - COO's normal baseline check then sees an
        in-service role with no process running and requests the spawn, so
        the agent returns under the same permanent identity with its name and
        history intact."""
        identity = directive["target_identity"]
        agent = fi_db.get_agent(self.conn, identity)
        if agent is None:
            fi_db.complete_directive(self.conn, directive["id"], "failure", detail=f"unknown identity: {identity}")
            return
        fi_db.resume_agent(self.conn, identity)
        fi_db.complete_directive(self.conn, directive["id"], "success", detail=f"resumed {identity}")

    def known_process_identities(self) -> list[str]:
        """Identities this Controller instance has itself spawned (has a
        live Popen handle for)."""
        return list(self._processes.keys())

    def close(self) -> None:
        self.conn.close()
