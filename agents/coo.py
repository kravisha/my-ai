"""COO: the privileged client that decides what agents should exist and
directs the Coordinator to spawn/retire them - never does domain work
itself (addendum 6 §1; confirmed this session: COO "will not be doing the
usual stuff that the client does, like portfolio management or act on
trade ideas... but it will only be creating processes or agents as
necessary and sort of managing them like a real manager").

COO never spawns or retires anything directly - per the confirmed rule
that the Coordinator is the *sole* spawner, COO only ever enqueues
directives (fi_db.enqueue_directive) for the Coordinator to pick up and
execute. This module implements the AgentProcess contract exactly like any
other agent (agents/base.py) - COO is architecturally just a privileged
client, not a special kind of process.

This first increment's policy is deliberately minimal: the baseline
population is "one dummy agent" (addendum 6 §2 step 6 - "Initial baseline
is one instance of each required role") and COO otherwise just watches
health. Richer scaling policy (starvation/backlog-driven scaling per
addendum 6 §5) is Phase C+ work, once there's a real Explorer/Speculator/
Analysis pipeline to actually scale.

COO's own observability interface (distinct from the Coordinator-produced
server dashboard, per addendum 6 §1) is deliberately minimal for this
increment too - a printed status line each cycle. A real dashboard for it
is future work, same as monitor/app.py was for the conversation transcript
system.

Run directly as: python -m agents.coo <identity>
Normally launched by backend/coordinator.py's bootstrap_coo(), not by hand.
"""

import sys

from agents.base import run_agent
from backend import fi_db

ROLE = "coo"
BASELINE_ROLES = ["dummy"]


def _role_spawn_in_flight(conn, role: str) -> bool:
    """True if the most recent successful spawn directive for this role
    named a target identity that hasn't shown up in agent_registry yet.

    Caught by manual end-to-end verification: the Coordinator marks a spawn
    directive completed as soon as subprocess.Popen returns, but the child
    doesn't call register_agent until it's actually running - a real gap,
    not instant. Without this check, _ensure_baseline_population's next
    ~1s cycle (running before that registration write lands) sees no
    active agent yet and enqueues a duplicate spawn."""
    for directive in reversed(fi_db.list_completed_directives(conn)):
        if directive["directive_type"] != "spawn" or directive["target_role"] != role:
            continue
        if directive["outcome"] != "success":
            continue
        return fi_db.get_agent(conn, directive["detail"]) is None
    return False


def _ensure_baseline_population(conn) -> None:
    """Idempotent: only enqueues a spawn directive for a role if no active
    agent of that role currently exists, and no spawn for that role is
    already in flight (see _role_spawn_in_flight). Runs every cycle rather
    than once at startup - cheap, and it means COO notices and re-spawns a
    baseline agent that unexpectedly died, a small real instance of
    "maintain ecosystem health" rather than just a one-time bootstrap
    step."""
    agents = fi_db.list_agents(conn)
    active_roles = {a["role"] for a in agents if a["status"] == "active"}
    known_roles = {a["role"] for a in agents}
    for role in BASELINE_ROLES:
        if role in active_roles:
            continue
        if _role_spawn_in_flight(conn, role):
            continue
        reason = (
            f"baseline role '{role}' has never been spawned - establishing initial population"
            if role not in known_roles
            else f"baseline role '{role}' has zero active agents - respawning to maintain baseline"
        )
        fi_db.enqueue_directive(conn, "spawn", requested_by="coo", target_role=role, reason=reason)


def _coo_work(conn) -> None:
    _ensure_baseline_population(conn)
    print(f"[COO] ecosystem: {fi_db.get_performance_card(conn)}")


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m agents.coo <identity>", file=sys.stderr)
        raise SystemExit(1)
    run_agent(identity=sys.argv[1], role=ROLE, work_fn=_coo_work)


if __name__ == "__main__":
    main()
