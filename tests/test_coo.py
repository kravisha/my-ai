"""Unit tests for agents/coo.py's decision logic - pure DB logic, no real
process needed here (the real bootstrap->baseline flow is covered as an
integration test in test_controller.py alongside the rest of the genuine
subprocess tests)."""

import json
import time

import pytest

from agents.coo import (
    BASELINE_ROLES,
    _coo_work,
    _ensure_baseline_population,
    _evaluate_agent_health,
    _evaluate_intelligence_health,
    _evaluate_past_decisions,
    _spawns_in_flight,
)
from backend import fi_db


def test_ensure_baseline_population_enqueues_spawn_when_role_missing(conn):
    _ensure_baseline_population(conn)
    pending = fi_db.fetch_next_pending_directive(conn)
    assert pending["directive_type"] == "spawn"
    assert pending["target_role"] in BASELINE_ROLES
    assert pending["requested_by"] == "coo"
    # Gap 2 (project brief): COO's decision must carry a reason, and a first-
    # ever spawn should read differently from a respawn-after-death (see
    # test_ensure_baseline_population_respawns_role_after_it_goes_gone below).
    assert "never been spawned" in pending["reason"]


def test_ensure_baseline_population_does_not_duplicate_when_role_already_active(conn):
    for i, role in enumerate(BASELINE_ROLES):
        fi_db.register_agent(conn, f"{role}-1", role, 111 + i)
    _ensure_baseline_population(conn)
    assert fi_db.fetch_next_pending_directive(conn) is None


def test_ensure_baseline_population_respawns_role_after_it_goes_gone(conn):
    """If the only dummy dies, COO should notice on its next cycle and ask
    for a replacement - a small real instance of maintaining ecosystem
    health, not just a one-time bootstrap check."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.mark_process_stopped(conn, "dummy-1")

    _ensure_baseline_population(conn)

    pending = fi_db.fetch_next_pending_directive(conn)
    assert pending is not None
    assert pending["target_role"] == "dummy"
    # A refill must read differently from a first-ever spawn and from capacity
    # being added deliberately - three situations that want different things
    # investigated, and which a bare shortfall count would flatten into one.
    assert "refilling it under the same identity" in pending["reason"]
    assert "never been spawned" not in pending["reason"]


def test_ensure_baseline_population_does_not_duplicate_when_spawn_in_flight(conn):
    """Regression test for a race caught during manual end-to-end
    verification: the Controller marks a spawn directive completed as
    soon as subprocess.Popen returns, before the child has actually called
    register_agent. COO must not enqueue a second spawn for the same role
    while that gap is still open."""
    # other baseline roles already established - isolates this test to just
    # dummy's in-flight check, not the unrelated "never been spawned" noise
    # from the other roles.
    for i, role in enumerate(r for r in BASELINE_ROLES if r != "dummy"):
        fi_db.register_agent(conn, f"{role}-1", role, 200 + i)

    directive_id = fi_db.enqueue_directive(conn, "spawn", requested_by="coo", target_role="dummy")
    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-not-yet-registered")

    assert _spawns_in_flight(conn, "dummy") == 1

    _ensure_baseline_population(conn)

    assert fi_db.fetch_next_pending_directive(conn) is None


def test_ensure_baseline_population_does_not_duplicate_while_directive_still_pending(conn):
    """Regression test for a bug found via manual verification of Gap 3: the
    old _spawns_in_flight only checked coo_directives_completed, which
    is blind to a directive the Controller hasn't picked up yet. COO's
    ~1s cycle and the Controller's ~1s poll are close enough in period
    that this was routine, not rare - simulated here by enqueuing a spawn
    and calling _ensure_baseline_population again before anything completes
    it, exactly as COO's next cycle would if the Controller hadn't caught
    up yet."""
    fi_db.enqueue_directive(conn, "spawn", requested_by="coo", target_role="dummy")

    assert _spawns_in_flight(conn, "dummy") == 1

    _ensure_baseline_population(conn)

    count = conn.fetchone("SELECT COUNT(*) AS n FROM coo_directives WHERE target_role = 'dummy'")["n"]
    assert count == 1


def test_spawns_in_flight_true_when_directive_reuses_identity_of_a_dead_prior_life(conn):
    """Core regression test for the permanent-identity redesign (addendum_5
    §4): identity is now a role-slot reused across every respawn, so a
    fresh spawn directive for 'dummy' names the *same* identity a previous,
    now-dead life already used. Before the new process registers again
    (bumping spawned_at), the registry row still shows the old life - this
    must read as "in flight", not "already resolved", or COO would treat a
    still-starting-up respawn as a silent success/failure."""
    old_directive_id = fi_db.enqueue_directive(conn, "spawn", requested_by="coo", target_role="dummy")
    fi_db.complete_directive(conn, old_directive_id, "success", detail="dummy-1")
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.mark_process_crashed(conn, "dummy-1")
    # completed_at is SQL-trigger-written at millisecond precision; a real
    # respawn always has tens of milliseconds of real subprocess startup
    # between "directive completed" and "agent registered" - this sleep
    # reflects that gap rather than an artificial same-instant collision.
    time.sleep(0.02)

    new_directive_id = fi_db.enqueue_directive(conn, "spawn", requested_by="coo", target_role="dummy")
    fi_db.complete_directive(conn, new_directive_id, "success", detail="dummy-1")  # same permanent identity

    assert _spawns_in_flight(conn, "dummy") == 1


def test_spawns_in_flight_false_once_reused_identity_reregisters(conn):
    """Continuation of the above: once the new process actually registers
    (register_agent bumps spawned_at past the new directive's completed_at),
    the same identity that was 'in flight' a moment ago should no longer
    read that way."""
    old_directive_id = fi_db.enqueue_directive(conn, "spawn", requested_by="coo", target_role="dummy")
    fi_db.complete_directive(conn, old_directive_id, "success", detail="dummy-1")
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.mark_process_crashed(conn, "dummy-1")

    new_directive_id = fi_db.enqueue_directive(conn, "spawn", requested_by="coo", target_role="dummy")
    fi_db.complete_directive(conn, new_directive_id, "success", detail="dummy-1")
    fi_db.register_agent(conn, "dummy-1", "dummy", 222)  # the new life actually registers

    assert _spawns_in_flight(conn, "dummy") == 0


def test_ensure_baseline_population_respawns_once_in_flight_agent_actually_dies(conn):
    """Once the previously in-flight agent shows up in the registry and
    then goes gone, it's no longer "in flight" - COO should treat this as
    a real death and ask for a replacement, same as the existing
    respawn-after-death behavior."""
    directive_id = fi_db.enqueue_directive(conn, "spawn", requested_by="coo", target_role="dummy")
    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-1")
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.mark_process_stopped(conn, "dummy-1")

    assert _spawns_in_flight(conn, "dummy") == 0

    _ensure_baseline_population(conn)

    pending = fi_db.fetch_next_pending_directive(conn)
    assert pending is not None
    assert pending["target_role"] == "dummy"


def test_evaluate_agent_health_marks_stale_agent_crashed(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.record_heartbeat(conn, "dummy-1")

    _evaluate_agent_health(conn, stale_seconds=0)

    agent = fi_db.get_agent(conn, "dummy-1")
    assert agent["process_state"] == fi_db.PROCESS_CRASHED
    # crash detection is a process observation - it must never retire the
    # agent, which is the Controller's decision alone
    assert agent["lifecycle_state"] == fi_db.LIFECYCLE_ACTIVE


def test_evaluate_agent_health_leaves_fresh_agent_running(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.record_heartbeat(conn, "dummy-1")

    _evaluate_agent_health(conn, stale_seconds=999)

    assert fi_db.get_agent(conn, "dummy-1")["process_state"] == fi_db.PROCESS_RUNNING


def test_evaluate_agent_health_does_not_touch_cleanly_stopped_agents(conn):
    """A clean exit already reported process_state='stopped' - health
    evaluation should leave that alone rather than overwriting it with
    'crashed'."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.mark_process_stopped(conn, "dummy-1")

    _evaluate_agent_health(conn, stale_seconds=0)

    assert fi_db.get_agent(conn, "dummy-1")["process_state"] == fi_db.PROCESS_STOPPED


def test_evaluate_agent_health_does_not_touch_dormant_agents(conn):
    """A retired agent is not a crashed one. Health evaluation must leave
    dormant agents entirely alone, however long they sit stopped."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.request_retirement(conn, "dummy-1")
    fi_db.mark_process_stopped(conn, "dummy-1")

    _evaluate_agent_health(conn, stale_seconds=0)

    agent = fi_db.get_agent(conn, "dummy-1")
    assert agent["lifecycle_state"] == fi_db.LIFECYCLE_DORMANT
    assert agent["process_state"] == fi_db.PROCESS_STOPPED


def test_coo_work_respawns_crashed_agent_within_same_cycle(conn):
    """Integration of Gap 3 with the existing baseline-population logic:
    a crashed agent (health evaluation runs before baseline population in
    _coo_work) should trigger a respawn in the very same cycle it was
    detected, not one cycle later."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.record_heartbeat(conn, "dummy-1")

    _evaluate_agent_health(conn, stale_seconds=0)
    _ensure_baseline_population(conn)

    assert fi_db.get_agent(conn, "dummy-1")["process_state"] == fi_db.PROCESS_CRASHED
    pending = fi_db.fetch_next_pending_directive(conn)
    assert pending is not None
    assert pending["target_role"] == "dummy"


# --- dormancy: retirement is non-destructive and reversible ---


def test_coo_does_not_respawn_a_dormant_agent(conn):
    """The whole point of separating lifecycle from process liveness.
    Retirement is a deliberate Controller decision; COO must not undo it by
    respawning. Before the split, a retired agent was indistinguishable from
    a dead one and got respawned within a cycle, so retirement silently did
    nothing."""
    for i, role in enumerate(BASELINE_ROLES):
        fi_db.register_agent(conn, f"{role}-1", role, 111 + i)
    fi_db.request_retirement(conn, "dummy-1")
    fi_db.mark_process_stopped(conn, "dummy-1")

    _ensure_baseline_population(conn)

    assert fi_db.fetch_next_pending_directive(conn) is None


def test_coo_respawns_once_a_dormant_agent_is_resumed(conn):
    """Resume restores organizational standing only; COO's next cycle then
    sees an in-service role with no process and requests the spawn."""
    for i, role in enumerate(BASELINE_ROLES):
        fi_db.register_agent(conn, f"{role}-1", role, 111 + i)
    fi_db.request_retirement(conn, "dummy-1")
    fi_db.mark_process_stopped(conn, "dummy-1")
    _ensure_baseline_population(conn)
    assert fi_db.fetch_next_pending_directive(conn) is None  # dormant, left alone

    fi_db.resume_agent(conn, "dummy-1")
    _ensure_baseline_population(conn)

    pending = fi_db.fetch_next_pending_directive(conn)
    assert pending is not None
    assert pending["target_role"] == "dummy"


def test_evaluate_past_decisions_marks_established_when_agent_active(conn):
    directive_id = fi_db.enqueue_directive(conn, "spawn", requested_by="coo", target_role="dummy")
    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-1")
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)

    _evaluate_past_decisions(conn, grace_seconds=0)

    completed = fi_db.list_completed_directives(conn)
    assert completed[0]["observed_result"] == "established"


def test_evaluate_past_decisions_marks_never_registered_when_agent_absent(conn):
    """Grace period elapsed and the identity never showed up in
    agent_registry at all - the spawn succeeded at the OS level but the
    child never got as far as registering itself."""
    directive_id = fi_db.enqueue_directive(conn, "spawn", requested_by="coo", target_role="dummy")
    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-1")

    _evaluate_past_decisions(conn, grace_seconds=0)

    completed = fi_db.list_completed_directives(conn)
    assert completed[0]["observed_result"] == "never_registered"


def test_evaluate_past_decisions_marks_died_before_establishing(conn):
    directive_id = fi_db.enqueue_directive(conn, "spawn", requested_by="coo", target_role="dummy")
    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-1")
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.mark_process_stopped(conn, "dummy-1")

    _evaluate_past_decisions(conn, grace_seconds=0)

    completed = fi_db.list_completed_directives(conn)
    assert completed[0]["observed_result"] == "died_before_establishing"


def test_evaluate_past_decisions_does_not_credit_a_newer_directive_with_an_older_lifes_status(conn):
    """Permanent-identity regression test: a directive's grading must
    reflect *its own* spawn attempt, not whatever agent_registry currently
    shows for that identity. Here the identity ('dummy-1') is still
    'active' from an earlier, unrelated life at the moment this newer
    directive's grace period expires - without the spawned_at comparison,
    this would wrongly grade the newer directive 'established' even though
    its own respawn attempt hasn't registered anything yet."""
    old_directive_id = fi_db.enqueue_directive(conn, "spawn", requested_by="coo", target_role="dummy")
    fi_db.complete_directive(conn, old_directive_id, "success", detail="dummy-1")
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)  # older life, still 'active'
    # completed_at is SQL-trigger-written at millisecond precision; a real
    # respawn always has tens of milliseconds of real subprocess startup in
    # between - this sleep reflects that gap rather than an artificial
    # same-instant collision with the registration above.
    time.sleep(0.02)

    new_directive_id = fi_db.enqueue_directive(conn, "spawn", requested_by="coo", target_role="dummy")
    fi_db.complete_directive(conn, new_directive_id, "success", detail="dummy-1")
    # the new life never actually registers in this test

    _evaluate_past_decisions(conn, grace_seconds=0)

    completed = {d["id"]: d for d in fi_db.list_completed_directives(conn)}
    assert completed[new_directive_id]["observed_result"] == "never_registered"


def test_evaluate_past_decisions_is_idempotent(conn):
    """Once a directive has an observed_result, later calls should not
    re-evaluate or overwrite it (e.g. an agent that was 'established' at
    observation time but later dies shouldn't retroactively rewrite the
    original decision's grade)."""
    directive_id = fi_db.enqueue_directive(conn, "spawn", requested_by="coo", target_role="dummy")
    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-1")
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)

    _evaluate_past_decisions(conn, grace_seconds=0)
    fi_db.mark_process_stopped(conn, "dummy-1")
    _evaluate_past_decisions(conn, grace_seconds=0)

    completed = fi_db.list_completed_directives(conn)
    assert completed[0]["observed_result"] == "established"


def test_coo_work_does_not_raise_and_prints_status(conn, capsys):
    _coo_work(conn)
    out = capsys.readouterr().out
    assert "[COO]" in out
    # also has the real side effect of ensuring baseline population
    assert fi_db.fetch_next_pending_directive(conn) is not None


# --- intelligence health: lenses go stale on evidence (gap analysis §4.11) ---


def _graded_report_for_lens(conn, lens_artifact_id, overall_score, worth_the_compute):
    report_id = fi_db.enqueue_report(
        conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "SYN1",
        lens_artifact_id=lens_artifact_id,
    )
    fi_db.complete_report(conn, report_id, "analyzed",
                          handled_by_identity="analysis-1", handled_by_spawned_at="2026-01-01T00:01:00+00:00")
    result_id = fi_db.record_analysis_result(
        conn, "analysis-1", "2026-01-01T00:01:00+00:00", report_id, "SYN1",
        thesis="t", evidence_summary="e", confidence=0.5, uncertainty="u",
    )
    fi_db.record_grade(
        conn, "analysis-1", "2026-01-01T00:01:00+00:00", report_id, result_id,
        relevance_score=overall_score, novelty_score=overall_score,
        evidence_quality_score=overall_score, worth_the_compute=worth_the_compute,
        overall_score=overall_score, rationale="r",
    )


def test_intelligence_health_refuses_to_judge_on_thin_evidence(conn):
    """Below min_graded_reports it does nothing at all, however bad the few
    grades look - the same guard that led to declining performance-ranked
    agent selection while there was nothing real to rank on."""
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    minimum = json.loads(lens["validity_conditions"])["min_graded_reports"]
    for _ in range(minimum - 1):
        _graded_report_for_lens(conn, lens["id"], 0.01, False)

    _evaluate_intelligence_health(conn)

    assert fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME) is not None


def test_intelligence_health_marks_lens_stale_once_evidence_is_sufficient(conn):
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    minimum = json.loads(lens["validity_conditions"])["min_graded_reports"]
    for _ in range(minimum):
        _graded_report_for_lens(conn, lens["id"], 0.01, False)

    _evaluate_intelligence_health(conn)

    row = conn.fetchone("SELECT * FROM intelligence_artifacts WHERE id = ?", (lens["id"],))
    assert row["status"] == "stale"
    # the evidence is recorded, not just the verdict
    assert str(minimum) in row["staleness_reason"]
    assert "mean overall score" in row["staleness_reason"]


def test_intelligence_health_flags_but_never_changes_the_lens_value(conn):
    """The constitutional constraint: continuous learning does not mean
    uncontrolled self-modification (addendum 13 §14)."""
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    original_value = lens["value"]
    minimum = json.loads(lens["validity_conditions"])["min_graded_reports"]
    for _ in range(minimum):
        _graded_report_for_lens(conn, lens["id"], 0.01, False)

    _evaluate_intelligence_health(conn)

    assert conn.fetchone("SELECT value FROM intelligence_artifacts WHERE id = ?", (lens["id"],))["value"] == original_value


def test_intelligence_health_leaves_a_well_performing_lens_active(conn):
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    minimum = json.loads(lens["validity_conditions"])["min_graded_reports"]
    for _ in range(minimum + 3):
        _graded_report_for_lens(conn, lens["id"], 0.9, True)

    _evaluate_intelligence_health(conn)

    assert fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME) is not None


def test_intelligence_health_is_a_noop_with_no_reports_at_all(conn):
    """Startup state: seeded lenses, nothing graded yet."""
    _evaluate_intelligence_health(conn)
    # Three seeded lenses now, not two - ARB-001's escalation lens
    # (fi_db.LENS_PARITY_MIN_EDGE_NAME) joined the IV and speculator-
    # confidence lenses when Explorer/Speculator were wired to the parity
    # mission (SPEC_RECONCILIATION.md SS39-SS41).
    assert len(fi_db.list_intelligence_artifacts(conn, artifact_kind=fi_db.LENS_KIND, status="active")) == 3


# --- intelligence health: the conditions half (regime) ---


def _observe_regime(conn, mean_iv, dispersion, cycles):
    for _ in range(cycles):
        fi_db.update_market_regime(conn, "SYN1", mean_iv, dispersion)


def _regime_of(conn):
    lens = conn.fetchone(
        "SELECT * FROM intelligence_artifacts WHERE name = ?", (fi_db.LENS_IV_RATIO_NAME,)
    )
    return json.loads(lens["validity_conditions"])["regime"]


def _make_lens_perform_well(conn):
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    minimum = json.loads(lens["validity_conditions"])["min_graded_reports"]
    for _ in range(minimum):
        _graded_report_for_lens(conn, lens["id"], 0.9, True)


def test_regime_does_not_bind_below_min_observations(conn):
    """An estimate built from a handful of surfaces would flag drift that is
    really just the estimate still converging."""
    _make_lens_perform_well(conn)
    minimum = fi_db.DEFAULT_MARKET_REGIME_CONDITIONS["min_observations"]
    _observe_regime(conn, 0.2855, 0.0116, minimum - 1)

    _evaluate_intelligence_health(conn)

    assert _regime_of(conn)["observed_under"] is None


def test_regime_does_not_bind_while_performance_is_unproven(conn):
    """A lens earns its baseline by being observed *working*. Binding one that
    has never been graded would record 'these are the conditions it works
    under' on no evidence that it works at all."""
    _observe_regime(conn, 0.2855, 0.0116, 40)

    _evaluate_intelligence_health(conn)

    assert _regime_of(conn)["observed_under"] is None


def test_regime_binds_once_observations_and_performance_both_hold(conn):
    _make_lens_perform_well(conn)
    _observe_regime(conn, 0.2855, 0.0116, 40)

    _evaluate_intelligence_health(conn)

    regime = _regime_of(conn)
    assert regime["observed_under"]["mean_iv"] == pytest.approx(0.2855)
    assert regime["bound_at"] is not None
    assert fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME) is not None


def test_regime_within_tolerance_leaves_the_lens_active(conn):
    _make_lens_perform_well(conn)
    _observe_regime(conn, 0.2855, 0.0116, 40)
    _evaluate_intelligence_health(conn)  # binds

    _observe_regime(conn, 0.2900, 0.0120, 40)  # ordinary jitter
    _evaluate_intelligence_health(conn)

    assert fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME) is not None


def test_regime_level_shift_marks_the_lens_stale_with_the_numbers(conn):
    """A lens invalidated by conditions changing, not by bad grades - the
    grades here are excellent throughout."""
    _make_lens_perform_well(conn)
    _observe_regime(conn, 0.2855, 0.0116, 40)
    _evaluate_intelligence_health(conn)

    _observe_regime(conn, 0.4850, 0.0116, 200)  # sustained level shift
    _evaluate_intelligence_health(conn)

    row = conn.fetchone("SELECT * FROM intelligence_artifacts WHERE name = ?", (fi_db.LENS_IV_RATIO_NAME,))
    assert row["status"] == "stale"
    assert "mean IV moved" in row["staleness_reason"]
    assert "0.2855" in row["staleness_reason"]  # the before, not just the verdict


def test_regime_dispersion_shift_alone_marks_the_lens_stale(conn):
    """Dispersion is why *this* lens is regime-dependent: when the surface
    gets noisier, peak/baseline ratios rise generally and a fixed threshold
    starts firing on noise - even with the level unchanged."""
    _make_lens_perform_well(conn)
    _observe_regime(conn, 0.2855, 0.0116, 40)
    _evaluate_intelligence_health(conn)

    _observe_regime(conn, 0.2855, 0.0800, 200)
    _evaluate_intelligence_health(conn)

    row = conn.fetchone("SELECT * FROM intelligence_artifacts WHERE name = ?", (fi_db.LENS_IV_RATIO_NAME,))
    assert row["status"] == "stale"
    assert "IV dispersion moved" in row["staleness_reason"]


def test_regime_staleness_never_changes_the_lens_value(conn):
    """Flags, never fixes - proposing a corrected threshold for the new regime
    is a Trainer's job behind validation (addendum 13 §14)."""
    _make_lens_perform_well(conn)
    original_value = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)["value"]
    _observe_regime(conn, 0.2855, 0.0116, 40)
    _evaluate_intelligence_health(conn)
    _observe_regime(conn, 0.4850, 0.0116, 200)
    _evaluate_intelligence_health(conn)

    row = conn.fetchone("SELECT * FROM intelligence_artifacts WHERE name = ?", (fi_db.LENS_IV_RATIO_NAME,))
    assert row["status"] == "stale"
    assert row["value"] == original_value


def test_an_unbound_lens_is_never_marked_stale_for_regime_reasons(conn):
    """With no baseline there is nothing to diverge *from*. Wild conditions
    plus an unbound lens must be a no-op, not a staleness verdict."""
    _observe_regime(conn, 0.9000, 0.2000, 300)

    _evaluate_intelligence_health(conn)

    assert fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME) is not None


def test_a_lens_without_regime_conditions_is_untouched_by_market_drift(conn):
    """The speculator's social lens must not expire because the option
    surface moved."""
    _observe_regime(conn, 0.9000, 0.2000, 300)

    _evaluate_intelligence_health(conn)

    social = fi_db.get_active_artifact(conn, fi_db.LENS_SPECULATOR_CONFIDENCE_NAME)
    assert social is not None
    assert "regime" not in json.loads(social["validity_conditions"])


def test_the_observation_grace_exceeds_measured_spawn_latency():
    """COO waits this long after a spawn before judging whether the agent
    established itself. Too short and a healthy-but-slow-starting agent is
    recorded as having died.

    Measured against a real backend (docs/TIMING_CONSTANTS.md): directive
    completion to registry entry ran 0.09-1.62s across four agents."""
    from agents.coo import OBSERVATION_GRACE_SECONDS

    worst_observed_spawn_seconds = 1.62
    assert OBSERVATION_GRACE_SECONDS > worst_observed_spawn_seconds * 2
