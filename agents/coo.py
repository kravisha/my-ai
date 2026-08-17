"""COO: the privileged client that decides what agents should exist and
directs the Controller to spawn/retire them - never does domain work
itself (addendum 6 §1; confirmed this session: COO "will not be doing the
usual stuff that the client does, like portfolio management or act on
trade ideas... but it will only be creating processes or agents as
necessary and sort of managing them like a real manager").

COO never spawns or retires anything directly - per the confirmed rule
that the Controller is the *sole* spawner, COO only ever enqueues
directives (fi_db.enqueue_directive) for the Controller to pick up and
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

COO's own observability interface (distinct from the Controller-produced
server dashboard, per addendum 6 §1) is deliberately minimal for this
increment too - a printed status line each cycle. A real dashboard for it
is future work, same as monitor/app.py was for the conversation transcript
system.

Run directly as: python -m agents.coo <identity>
Normally launched by backend/controller.py's bootstrap_coo(), not by hand.
"""

import json
import sys
from collections import Counter

from agents.base import run_agent
from backend import fi_db

ROLE = "coo"
# 'dummy' stays alongside the real Phase C roles: cheap, business-logic-free
# diagnostic isolation if a new agent fails to spawn - if dummy comes up but
# explorer/speculator/analysis don't, the problem is in the new agent code,
# not the control plane.
BASELINE_ROLES = ["dummy", "explorer", "speculator", "analysis"]

# How long to wait after a spawn directive completes before checking whether
# the target agent actually established itself (registered a heartbeat)
# versus never came up or died immediately. Comfortably longer than
# agents/base.py's HEARTBEAT_INTERVAL_SECONDS so a healthy agent has time to
# register and send at least one heartbeat.
OBSERVATION_GRACE_SECONDS = 5.0

# How long an 'active' agent's heartbeat can go stale before COO's health
# evaluation treats it as crashed rather than merely slow. Was 10.0 until
# manual verification of Phase C caught a real bug at that value: a
# heartbeat is only recorded after work_fn(conn) returns (agents/base.py),
# and Analysis's real LLM call (app/model_gateway.py's call_reasoning_model,
# max_tokens up to 4096) routinely took long enough to blow past 10s -
# every time it did, COO wrongly concluded the still-alive-but-busy agent
# had crashed and respawned a duplicate under the same permanent identity
# (Gap 1's identity redesign) without the original process ever actually
# dying. Observed three concurrent analysis-1 OS processes racing to
# consume the same report queue as a direct result. 45s gives real headroom
# over realistic LLM latency (including occasional slow responses) while
# still being a bounded, reasonable "detect a genuine crash within under a
# minute" guarantee for a background pipeline like this - not a real-time
# system where 45s of crash-detection lag would matter. See agents/
# explorer.py's and agents/analysis.py's own explicit heartbeat calls right
# before their LLM calls for the other half of this fix: keeping the
# heartbeat fresh going into a slow operation, not just tolerating a wider
# window after the fact.
HEALTH_STALE_THRESHOLD_SECONDS = 45.0


def _role_spawn_in_flight(conn, role: str) -> bool:
    """True if a spawn for this role is still in progress somewhere between
    "COO asked for it" and "the agent is registered and active": either the
    directive itself hasn't been picked up by the Controller yet (still
    pending), or the Controller has processed it but the target identity
    hasn't (re-)registered for *this* attempt yet.

    Agent identity is a permanent role-slot (addendum_5 §4 - see
    backend/controller.py's _slot_identity), so "does this identity exist
    in agent_registry" stopped being a usable signal for the second half:
    once a role has been spawned even once, its identity exists forever,
    reused across every later respawn. The real question is whether the
    registry row's spawned_at reflects *this* spawn attempt specifically -
    compared against the directive's own completed_at, not just presence.
    An older spawned_at means the row is still showing a previous life;
    this attempt's process hasn't registered yet (or never will).

    Both this half and the still-pending half were caught by manual end-to-
    end verification, not the unit suite - see the project memory for both
    incidents. The still-pending half: COO's ~1s cycle and the
    Controller's ~1s poll loop (backend/main.py) are close enough in
    period that it's routine for COO's next cycle to run before the
    previous cycle's directive has even been picked up."""
    if fi_db.has_pending_spawn_directive(conn, role):
        return True
    directive = fi_db.most_recent_completed_spawn(conn, role)
    if directive is None or directive["outcome"] != "success":
        return False
    agent = fi_db.get_agent(conn, directive["detail"])
    if agent is None:
        return True
    return fi_db.parse_timestamp(agent["spawned_at"]) < fi_db.parse_timestamp(directive["completed_at"])


def _ensure_baseline_population(conn) -> None:
    """Idempotent: only enqueues a spawn directive for a role if that role
    has no agent both in service and running, and no spawn for that role is
    already in flight (see _role_spawn_in_flight). Runs every cycle rather
    than once at startup - cheap, and it means COO notices and re-spawns a
    baseline agent that unexpectedly died, a small real instance of
    "maintain ecosystem health" rather than just a one-time bootstrap
    step.

    **Dormant agents are deliberately left alone.** Retirement is an
    explicit organizational decision taken by the Controller; COO must not
    immediately undo it by respawning. That means retiring the only agent of
    a baseline role genuinely leaves that role unstaffed until someone
    resumes it (fi_db.resume_agent) - which is what retirement *means*.
    Before lifecycle and process state were separated, this was impossible
    to express: a retired agent was indistinguishable from a dead one, so
    COO respawned it within a cycle and retirement silently did nothing."""
    agents = fi_db.list_agents(conn)
    staffed_roles = {
        a["role"] for a in agents
        if a["lifecycle_state"] == fi_db.LIFECYCLE_ACTIVE and a["process_state"] == fi_db.PROCESS_RUNNING
    }
    dormant_roles = {a["role"] for a in agents if a["lifecycle_state"] == fi_db.LIFECYCLE_DORMANT}
    known_roles = {a["role"] for a in agents}
    for role in BASELINE_ROLES:
        if role in staffed_roles or role in dormant_roles:
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
    brief): an agent that exits cleanly reports process_state='stopped' via
    agents/base.py's finally block, but a hard crash (SIGKILL, OOM, hung
    process) never reaches that code at all - the row would claim 'running'
    forever unless something else notices the heartbeat stopped moving. This
    is that something else: any agent still claiming to run, stale beyond
    stale_seconds, is marked process_state='crashed', which drops it out of
    _ensure_baseline_population's staffed-role set so a replacement gets
    spawned, the same as a clean stop would. Runs before
    _ensure_baseline_population in _coo_work so a crash detected this cycle
    is already reflected in this cycle's respawn check, not one cycle later.

    Records a *process* observation only - it never changes lifecycle_state.
    COO noticing a dead process is not COO retiring an agent; organizational
    standing is the Controller's call alone (addendum 11 §15).

    stale_seconds is overridable (default HEALTH_STALE_THRESHOLD_SECONDS)
    so tests can evaluate without waiting out the real threshold."""
    for agent in fi_db.list_stale_active_agents(conn, stale_seconds):
        fi_db.mark_process_crashed(conn, agent["identity"])


def _evaluate_past_decisions(conn, grace_seconds: float = OBSERVATION_GRACE_SECONDS) -> None:
    """The "later observed result" half of Gap 2 (project brief): the
    Controller's 'success' outcome on a spawn directive only proves
    subprocess.Popen didn't raise (backend/controller.py's _handle_spawn) -
    not that the decision panned out. Once the grace period has passed,
    check the registry for what actually happened and record it, so COO's
    baseline-population decisions become gradeable against reality rather
    than just against their own immediate mechanical outcome.

    grace_seconds is overridable (default OBSERVATION_GRACE_SECONDS) so
    tests can evaluate immediately instead of waiting out the real grace
    period.

    Identity is a permanent role-slot (addendum_5 §4), so agent_registry's
    row for directive["detail"] may reflect a *later* life than the one
    this directive spawned (e.g. it registered, crashed, and got respawned
    again before this directive got observed). Comparing spawned_at against
    the directive's own completed_at (same check _role_spawn_in_flight
    uses) keeps a directive from being graded off a different spawn
    attempt's outcome - if the row still predates this attempt, this
    attempt itself never registered, regardless of what a later life's
    state is."""
    for directive in fi_db.list_directives_needing_observation(conn, grace_seconds):
        agent = fi_db.get_agent(conn, directive["detail"])
        if agent is None or fi_db.parse_timestamp(agent["spawned_at"]) < fi_db.parse_timestamp(directive["completed_at"]):
            result = "never_registered"
        elif agent["process_state"] == fi_db.PROCESS_RUNNING:
            result = "established"
        else:
            result = "died_before_establishing"
        fi_db.record_observed_result(conn, directive["id"], result)


def _evaluate_intelligence_health(conn) -> None:
    """Checks each active detection lens against the evidence its own reports
    generated, and marks it stale when its stated validity conditions fail.

    This closes a loop that was previously severed. `grades` already recorded
    whether each report was relevant, novel, well-evidenced and worth the
    compute - and that evidence reached nothing, so the system could
    accumulate overwhelming proof that a lens was wrong and remain
    structurally incapable of noticing. Attribution now runs
    grades -> discovery_reports_completed -> lens_artifact_id
    (fi_db.lens_performance).

    Three deliberate constraints:

    1. **Deterministic, no LLM.** This is statistics over grades that already
       exist. Using a model to judge a gate another model passed would add
       cost and opacity for nothing.
    2. **Flags, never fixes.** It records staleness with the evidence; it does
       not touch the lens value. Addendum 13 §14: "production behavior changes
       remain gated by validation. Continuous learning does not mean
       uncontrolled self-modification."
    3. **Refuses to judge on thin evidence.** Below min_graded_reports it does
       nothing at all, however bad the few grades look - the same guard that
       led to declining performance-ranked agent selection while there was
       nothing real to rank on.

    Lives in COO because COO already owns the health cycle and, critically,
    is *not* the producer - Explorer judging the lens it detects with would be
    exactly the self-certification addendum 11 §8 forbids. This belongs to HR
    once HR exists (addendum 11 §5: capability, quality, drift); move it then."""
    for artifact in fi_db.list_intelligence_artifacts(conn, artifact_kind=fi_db.LENS_KIND, status="active"):
        conditions = json.loads(artifact["validity_conditions"] or "{}")
        performance = fi_db.lens_performance(conn, artifact["id"])

        minimum = conditions.get("min_graded_reports")
        judged_on_performance = minimum is not None and performance["graded_reports"] >= minimum

        failures = []
        if judged_on_performance:
            floor = conditions.get("min_mean_overall_score")
            mean_score = performance["mean_overall_score"]
            if floor is not None and mean_score is not None and mean_score < floor:
                failures.append(f"mean overall score {mean_score:.3f} < {floor}")

            worth_floor = conditions.get("min_worth_the_compute_rate")
            worth_rate = performance["worth_the_compute_rate"]
            if worth_floor is not None and worth_rate is not None and worth_rate < worth_floor:
                failures.append(f"worth-the-compute rate {worth_rate:.3f} < {worth_floor}")

        if failures:
            fi_db.mark_artifact_stale(
                conn, artifact["id"],
                f"validity conditions failed over {performance['graded_reports']} graded reports: "
                + "; ".join(failures),
            )
            continue

        # Performance is only half of expiry. A lens can be scoring perfectly
        # well and still be about to stop working, because the conditions it
        # works under are leaving.
        _evaluate_lens_regime(conn, artifact, conditions, performing_acceptably=judged_on_performance)


def _evaluate_lens_regime(conn, artifact: dict, conditions: dict, performing_acceptably: bool) -> None:
    """The conditions half of expiry: "intelligence depends on market
    conditions. Market conditions change, and when they change, intelligence
    changes" (owner, 2026-08-16).

    Two states, in order:

    - **Unbound** - the lens has no recorded baseline conditions. Seeded
      lenses arrive this way and always will: they came from the
      specification, so what regime they were *derived* under is genuinely
      unknown and claiming otherwise would be a fabrication. Instead a lens
      earns its baseline by being observed working: once enough market has
      been observed *and* its performance conditions currently pass, bind it
      to the conditions it demonstrably worked under.
    - **Bound** - compare current conditions to that baseline and mark stale
      on drift beyond either tolerance, with the actual numbers as evidence.

    Below min_observations, neither happens. An estimate built from a handful
    of surfaces would flag drift that is really just the estimate still
    converging - the same thin-evidence refusal as the performance arm.

    Like that arm, this flags and never fixes: proposing a corrected threshold
    for the new regime is a Trainer's job behind validation (addendum 13 §14),
    not a health check's."""
    regime = conditions.get("regime") or {}
    minimum_observations = regime.get("min_observations")
    if minimum_observations is None:
        return

    characterization = fi_db.current_market_characterization(conn)
    if characterization["observation_count"] < minimum_observations:
        return

    observed_under = regime.get("observed_under")
    if observed_under is None:
        if performing_acceptably:
            fi_db.bind_lens_to_regime(conn, artifact["id"], characterization)
            print(
                f"[COO] bound lens '{artifact['name']}' to observed regime "
                f"mean_iv={characterization['mean_iv']:.4f} "
                f"dispersion={characterization['iv_dispersion']:.4f}"
            )
        return

    drifts = []
    mean_tolerance = regime.get("max_mean_iv_drift")
    mean_drift = abs(characterization["mean_iv"] - observed_under["mean_iv"])
    if mean_tolerance is not None and mean_drift > mean_tolerance:
        drifts.append(
            f"mean IV moved {mean_drift:.4f} (from {observed_under['mean_iv']:.4f} "
            f"to {characterization['mean_iv']:.4f}, tolerance {mean_tolerance})"
        )

    dispersion_tolerance = regime.get("max_dispersion_drift")
    dispersion_drift = abs(characterization["iv_dispersion"] - observed_under["iv_dispersion"])
    if dispersion_tolerance is not None and dispersion_drift > dispersion_tolerance:
        drifts.append(
            f"IV dispersion moved {dispersion_drift:.4f} (from {observed_under['iv_dispersion']:.4f} "
            f"to {characterization['iv_dispersion']:.4f}, tolerance {dispersion_tolerance})"
        )

    if drifts:
        fi_db.mark_artifact_stale(
            conn, artifact["id"],
            f"market regime diverged from the conditions this lens was observed working under "
            f"({characterization['observation_count']} observations across "
            f"{characterization['securities']} securities): " + "; ".join(drifts),
        )


def _coo_work(conn) -> None:
    _evaluate_agent_health(conn)
    _ensure_baseline_population(conn)
    _evaluate_past_decisions(conn)
    _evaluate_intelligence_health(conn)
    # One line, not the whole performance card. This ran every cycle dumping a
    # dict repr of every agent - invisible while agent stdout was block-buffered
    # into the log redirect, and ~1.5KB/s of noise the moment that was fixed.
    # The roster is what the control panel is for; what belongs in a log is the
    # shape of the population and anything abnormal about it.
    card = fi_db.get_performance_card(conn)
    counts = Counter(a["lifecycle_state"] for a in card)
    unhealthy = [a["identity"] for a in card if a["process_state"] != fi_db.PROCESS_RUNNING]
    summary = ", ".join(f"{n} {state}" for state, n in sorted(counts.items()))
    print(f"[COO] {len(card)} agents ({summary})" + (f" | not running: {', '.join(unhealthy)}" if unhealthy else ""))


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m agents.coo <identity>", file=sys.stderr)
        raise SystemExit(1)
    run_agent(identity=sys.argv[1], role=ROLE, work_fn=_coo_work)


if __name__ == "__main__":
    main()
