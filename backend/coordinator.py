"""The Coordinator is the sole thing that ever spawns or retires an agent
process (addendum 6 §3, confirmed this session: "all agents will be spawned
only by the coordinator... the COO... is officer who will be directing the
coordinator to spawn an agent on demand and also... to retire an agent...
in a controlled and smooth manner"). Mechanics only - it never invents
policy, it only executes directives the COO has placed in the
coo_directives table. It *is* the backend engine's own process-management
role, per the confirmed process model - not a separate process itself,
lives inside backend/main.py.

Retirement is never a kill: it only ever sets a flag (fi_db.request_
retirement) that the target agent's own run loop notices and acts on
(agents/base.py) - "controlled and smooth" in the literal sense of the
agent finishing on its own terms.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

from backend import fi_db

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Coordinator:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(fi_db.DB_PATH)
        self.conn = fi_db.get_connection(self.db_path)
        fi_db.init_schema(self.conn)
        # Popen handles this Coordinator instance has itself spawned - only the
        # spawning process can hold/control these; not the same as everyone
        # in agent_registry, which also reflects agents from a prior run.
        self._processes: dict[str, subprocess.Popen] = {}

    def bootstrap_coo(self) -> str:
        """The one spawn that bypasses the directive queue entirely -
        there's no COO yet to have placed a directive, so the Coordinator
        spawns it directly as its first action on server startup (addendum
        6 §2 step 3: "the coordinator spawns the COO privileged client as
        the first managed process"). Every other agent, including the
        baseline population COO itself will ask for once running, goes
        through the normal directive queue in process_next_directive."""
        identity = f"coo-{uuid.uuid4().hex[:8]}"
        env = {**os.environ, "FI_DB_PATH": self.db_path}
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
        else:
            fi_db.complete_directive(
                self.conn, directive["id"], "failure",
                detail=f"unknown directive_type: {directive['directive_type']}",
            )
        return True

    def _handle_spawn(self, directive: dict) -> None:
        role = directive["target_role"]
        identity = f"{role}-{uuid.uuid4().hex[:8]}"
        env = {**os.environ, "FI_DB_PATH": self.db_path}
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
        identity = directive["target_identity"]
        if fi_db.get_agent(self.conn, identity) is None:
            fi_db.complete_directive(self.conn, directive["id"], "failure", detail=f"unknown identity: {identity}")
            return
        fi_db.request_retirement(self.conn, identity)
        fi_db.complete_directive(self.conn, directive["id"], "success", detail=f"retirement requested for {identity}")

    def known_process_identities(self) -> list[str]:
        """Identities this Coordinator instance has itself spawned (has a
        live Popen handle for)."""
        return list(self._processes.keys())

    def close(self) -> None:
        self.conn.close()
