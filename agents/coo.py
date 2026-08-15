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
is one instance of each required role"), and COO's health watching covers
only what Phase A/B actually has data for - detecting a heartbeat that's
stopped moving (_evaluate_agent_health) and distinguishing that from a
clean exit (crashed vs. gone). Richer scaling policy (starvation/backlog-
driven scaling per addendum 6 §5) is deliberately still Phase C+ work:
there's no real task queue yet for anything to back up on, so "backlog"
has no meaning until a real Explorer/Speculator/Analysis pipeline exists
to actually scale against.

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

# How long to wait after a spawn directive completes before checking whether
# the target agent actually established itself (registered a heartbeat)
# versus never came up or died immediately. Comfortably longer than
# agents/base.py's HEARTBEAT_INTERVAL_SECONDS so a healthy agent has time to
# register and send at least one heartbeat.
OBSERVATION_GRACE_SECONDS = 5.0

# How long an 'active' agent's heartbeat can go stale before COO's health
# evaluation treats it as crashed rather than merely slow. Comfortably
# longer than agents/base.py's HEARTBEAT_INTERVAL_SECONDS (normal cycle-to-
# cycle jitter shouldn't false-positive as a crash).
HEALTH_STALE_THRESHOLD_SECONDS = 10.0


def _role_spawn_in_flight(conn, role: str) -> bool:
    """True if a spawn for this role is still in progress somewhere between
    "COO asked for it" and "the agent is registered and active": either the
    directive itself hasn't been picked up by the Coordinator yet (still
    pending), or the Coordinator has processed it but the target identity
    hasn't shown up in agent_registry yet.

    Both halves were caught by manual end-to-end verification, not the unit
    suite. The registered-but-not-yet-active half: the Coordinator marks a
    spawn directive completed as soon as subprocess.Popen returns, but the
    child doesn't call register_agent until it's actually running - a real
    gap, not instant. The still-pending half (added alongside Gap 3's crash
    detection): COO's ~1s cycle and the Coordinator's ~1s poll loop
    (backend/main.py) are close enough in period that it's routine for
    COO's next cycle to run before the previous cycle's directive has even
    been picked up - list_completed_directives alone is blind to that,
    since the directive isn't there yet."""
    if fi_db.has_pending_spawn_directive(conn, role):
        return True
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


def _evaluate_agent_health(conn, stale_seconds: float = HEALTH_STALE_THRESHOLD_SECONDS) -> None:
    """Health evaluation + restart-vs-crash distinction (Gap 3, project
    brief): an agent that exits cleanly marks itself 'gone' via agents/
    base.py's finally block, but a hard crash (SIGKILL, OOM, hung process)
    never reaches that code at all - the row stays 'active' forever unless
    something else notices the heartbeat stopped moving. This is that
    something else: any 'active' agent stale beyond stale_seconds is marked
    'crashed', which drops it out of _ensure_baseline_population's active-
    role count so a replacement gets spawned, the same as a clean 'gone'
    would trigger. Runs before _ensure_baseline_population in _coo_work so
    a crash detected this cycle is already reflected in this cycle's
    respawn check, not one cycle later.

    stale_seconds is overridable (default HEALTH_STALE_THRESHOLD_SECONDS)
    so tests can evaluate without waiting out the real threshold."""
    for agent in fi_db.list_stale_active_agents(conn, stale_seconds):
        fi_db.mark_agent_crashed(conn, agent["identity"])


def _evaluate_past_decisions(conn, grace_seconds: float = OBSERVATION_GRACE_SECONDS) -> None:
    """The "later observed result" half of Gap 2 (project brief): the
    Coordinator's 'success' outcome on a spawn directive only proves
    subprocess.Popen didn't raise (backend/coordinator.py's _handle_spawn) -
    not that the decision panned out. Once the grace period has passed,
    check the registry for what actually happened and record it, so COO's
    baseline-population decisions become gradeable against reality rather
    than just against their own immediate mechanical outcome.

    grace_seconds is overridable (default OBSERVATION_GRACE_SECONDS) so
    tests can evaluate immediately instead of waiting out the real grace
    period."""
    for directive in fi_db.list_directives_needing_observation(conn, grace_seconds):
        identity = directive["detail"]
        agent = fi_db.get_agent(conn, identity)
        if agent is None:
            result = "never_registered"
        elif agent["status"] == "active":
            result = "established"
        else:
            result = "died_before_establishing"
        fi_db.record_observed_result(conn, directive["id"], result)


def _coo_work(conn) -> None:
    _evaluate_agent_health(conn)
    _ensure_baseline_population(conn)
    _evaluate_past_decisions(conn)
    print(f"[COO] ecosystem: {fi_db.get_performance_card(conn)}")


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m agents.coo <identity>", file=sys.stderr)
        raise SystemExit(1)
    run_agent(identity=sys.argv[1], role=ROLE, work_fn=_coo_work)


if __name__ == "__main__":
    main()
