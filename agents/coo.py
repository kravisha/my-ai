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
import os
import sys
from collections import Counter

from agents.base import run_agent
from backend import fi_db, remediation, risk

ROLE = "coo"

# Who this agent is when it files an incident. COO is a singleton by
# construction - the Controller spawns it directly as slot 1 and nothing
# allocates a second (backend/controller.py's _slot_identity says why) - so the
# identity is derivable rather than something work_fn has to be handed. The
# alternative was widening `work_fn(conn)`, the contract every agent shares, to
# carry an argument only this one needs. tests/test_coo.py pins the two together.
IDENTITY = f"{ROLE}-1"
# 'dummy' stays alongside the real Phase C roles: cheap, business-logic-free
# diagnostic isolation if a new agent fails to spawn - if dummy comes up but
# explorer/speculator/analysis don't, the problem is in the new agent code,
# not the control plane.
# How many agents each baseline role should have in service.
#
# A count rather than a list, because judgment latency is the time to cycle the
# whole security universe divided by the number of judgment agents - measured at
# ~235s with one agent over ten securities. Coverage cannot grow without this
# growing with it, and until now the organization had no way to express that.
#
# Overridable per role as FI_BASELINE_<ROLE>, so a scenario can staff a role
# differently without a code change - which is what makes one-versus-two
# judgment agents an experiment rather than an edit.
def _baseline_target(role: str, default: int) -> int:
    return max(0, int(os.environ.get(f"FI_BASELINE_{role.upper()}", str(default))))


BASELINE_POPULATION = {
    "dummy": _baseline_target("dummy", 1),
    "explorer": _baseline_target("explorer", 1),
    "speculator": _baseline_target("speculator", 1),
    "analysis": _baseline_target("analysis", 1),
}

# The role names alone. Kept because plenty of callers only ever wanted the
# names, and widening all of them to carry counts they ignore would be churn.
BASELINE_ROLES = list(BASELINE_POPULATION)

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


# How long after a spawn directive completes the agent is still considered to be
# starting up. Must comfortably exceed process start plus first registration, or
# COO enqueues a second spawn for a slot that is already coming up - and because
# allocate_slot is deterministic, both would target the same identity, which is
# how duplicate processes under one identity happened before.
SPAWN_IN_FLIGHT_WINDOW_SECONDS = 30.0


def _spawns_in_flight(conn, role: str) -> int:
    """How many spawns for this role are between "asked for" and "landed".

    Two halves, both found by end-to-end verification rather than by the unit
    suite. A directive the Controller has not picked up yet is in flight - COO's
    cycle and the Controller's poll loop have close enough periods that COO
    routinely runs again before its last directive was read. And a directive the
    Controller *has* executed is still in flight until the target identity
    registers for that attempt specifically.

    Registration cannot be judged by existence, because a slot identity is
    permanent and outlives every process that ever ran under it. The signal is
    whether the registry row's spawned_at is newer than the directive's
    completed_at; an older one means the row is still showing a previous life.

    A count rather than a boolean now that a role can hold several agents: three
    legitimate spawns in the same second are normal, and a boolean would suppress
    two of them."""
    pending = fi_db.count_pending_spawn_directives(conn, role)
    # The same predicate the Controller allocates against, deliberately shared:
    # if COO's idea of "still coming up" and the Controller's idea of "already
    # issued" could drift apart, one would ask for an agent the other was in the
    # middle of starting.
    landing = len(fi_db.slots_awaiting_registration(conn, role, SPAWN_IN_FLIGHT_WINDOW_SECONDS))
    return pending + landing


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
    for role, target in BASELINE_POPULATION.items():
        staffing = fi_db.staffing(conn, role)

        # Retirement genuinely leaves a role short. A dormant member still holds
        # its slot, so it lowers what COO is trying to staff rather than being
        # replaced - otherwise COO would quietly spawn a substitute and undo a
        # decision the Controller took.
        effective_target = max(0, target - staffing["dormant"])

        in_flight = _spawns_in_flight(conn, role)
        have = staffing["running"] + in_flight
        shortfall = effective_target - have
        if shortfall <= 0:
            continue

        # Three situations that a bare shortfall would flatten into one. They
        # want different things looked at when someone reads the directive log:
        # a role that never came up is a startup or deployment problem, a slot
        # being refilled is a crash to investigate, and a new slot is capacity
        # being added on purpose.
        for index in range(shortfall):
            if staffing["members"] == 0:
                what = "has never been spawned - establishing initial population"
            elif staffing["awaiting_process"] > index:
                what = "has a slot with no process - refilling it under the same identity"
            else:
                what = "needs more agents than it has slots - adding capacity"
            reason = (
                f"baseline role '{role}' {what} "
                f"({staffing['running']}/{effective_target} in service"
                + (f", {staffing['dormant']} dormant" if staffing["dormant"] else "")
                + (f", {in_flight} spawning" if in_flight else "")
                + ")"
            )
            fi_db.enqueue_directive(conn, "spawn", requested_by="coo", target_role=role, reason=reason)
            in_flight += 1


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
    so tests can evaluate without waiting out the real threshold.

    Every detection also opens an incident (Fault Tolerance Framework §14), and
    every agent that comes back closes the one it left open. Marking a registry
    row 'crashed' says what is true *now*; the incident says what happened, who
    noticed, and whether the capability returned - which is the difference
    between a state and a record the organization can learn from. The two halves
    live together here because a watcher that only ever files leaves a board of
    failures that all look permanent."""
    for agent in fi_db.list_stale_active_agents(conn, stale_seconds):
        fi_db.mark_process_crashed(conn, agent["identity"])
        fi_db.open_incident(
            conn,
            subject_identity=agent["identity"],
            subject_role=agent["role"],
            detected_by=IDENTITY,
            symptom=f"heartbeat stopped advancing past the {stale_seconds}s threshold",
            last_healthy_at=agent["last_heartbeat_at"],
            evidence={"pid": agent["pid"]},
        )

    for incident in fi_db.list_incidents(conn, status="open"):
        if incident["detected_by"] != IDENTITY:
            # Somebody else's incident. §16: monitoring follows assigned
            # responsibility, and closing another watcher's record would be
            # claiming an observation this agent did not make.
            continue
        agent = fi_db.get_agent(conn, incident["subject_identity"])
        if agent is None:
            continue
        age = fi_db.heartbeat_age_seconds(agent)
        if age is not None and age < stale_seconds:
            fi_db.record_recovery(
                conn, incident["id"], f"heartbeat resumed ({round(age, 1)}s old)"
            )


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
            reason = (
                f"validity conditions failed over {performance['graded_reports']} graded reports: "
                + "; ".join(failures)
            )
            fi_db.mark_artifact_stale(conn, artifact["id"], reason)
            _record_lens_lesson(conn, artifact, reason)
            continue

        # Performance is only half of expiry. A lens can be scoring perfectly
        # well and still be about to stop working, because the conditions it
        # works under are leaving.
        _evaluate_lens_regime(conn, artifact, conditions, performing_acceptably=judged_on_performance)


def _record_lens_lesson(conn, artifact: dict, reason: str) -> None:
    """Write what a lens failure taught into the knowledge store.

    `staleness_reason` lives on the artifact row, so it is lost when that
    artifact is superseded - this preserves it independently.

    Guarded on exact-statement duplication: health is re-evaluated every cycle,
    and without the guard one stale lens would record an identical lesson every
    second.

    Internal rationale: INT-PHIL-0009"""
    statement = f"Detection lens '{artifact['name']}' (value {artifact['value']}) stopped being reliable."
    if fi_db.knowledge_exists(conn, fi_db.KNOWLEDGE_LESSON, statement):
        return
    fi_db.record_knowledge(
        conn, fi_db.KNOWLEDGE_LESSON, statement, recorded_by=ROLE,
        subject=artifact["name"], rationale=reason,
        evidence_ref=f"intelligence_artifacts:{artifact['id']}",
    )


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
    # Risk is assessed here rather than by Analysis, for the same reason source
    # standings are COO's: the producer of an opportunity must not be the judge
    # of its risk (addendum 11 §8). Placed before the compliance sweep below so
    # a result is never counted unassessed merely because judgment ran first in
    # the same cycle - the order is the grace period.
    risk.assess_unassessed(conn, IDENTITY)
    # The remediation findings were computed on every panel request and
    # persisted never - raise_corrective_actions had no production caller, so
    # "corrective work becomes ordinary tasks" was true only in tests.
    # knowledge_exists makes this idempotent per cause, so running it every
    # cycle files each judgment once.
    fi_db.raise_corrective_actions(conn, remediation.corrective_items(conn))
    # Source standings are recomputed here rather than by Speculator, for the
    # same reason lens health is COO's: the producer of evidence must not be
    # the judge of its own sources (addendum 11 §8).
    fi_db.recompute_source_reliability(conn)
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
