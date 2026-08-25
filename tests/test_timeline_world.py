"""The event-stepped timeline (simulation/parity_world.py, addendum 34 §6,
SPEC_RECONCILIATION §63, TQ-14's remaining scope): State(t) + Event(t) ->
State(t+1).

The load-bearing properties: the market genuinely moves while the listed
ladder stays fixed; the scheduled opportunity is live exactly in
[onset, resolution) and the organization's own answer key finds it there
and ONLY there; quiet steps - including whole quiet timelines - are silent;
every step is graded by the same evaluate() the static world uses; and the
whole sequence is reproducible by seed. Runs stay small, per the world
suite's own instruction."""

import pytest

from backend import observations as observation_store
from backend import reference_data as rd
from providers.stored_data import StoredChainProvider
from simulation import parity_world as pw


def _config(mission_id, seed, **overrides):
    kwargs = dict(run_mode="simulation", strategy=pw.STRATEGY_TIMELINE,
                  mission_id=mission_id, seed=seed)
    kwargs.update(overrides)
    return pw.MissionConfig(**kwargs)


def _timelines(conn, config):
    focus = rd.list_focus_assets(conn)
    return [pw._build_timeline(config, focus, i) for i in range(config.n_scenarios)]


# --- config and registration ------------------------------------------------------


def test_timeline_strategy_is_registered_with_a_valid_default_mix():
    assert pw.STRATEGY_TIMELINE in pw.STRATEGIES  # mission control lists STRATEGIES verbatim
    config = _config("m-mix", seed=1)
    assert config.scenario_mix == pw.DEFAULT_SCENARIO_MIX_TIMELINE
    assert sum(pw.DEFAULT_SCENARIO_MIX_TIMELINE.values()) == pytest.approx(1.0)
    assert set(pw.DEFAULT_SCENARIO_MIX_TIMELINE) <= set(pw.TIMELINE_VARIANTS)


def test_step_shape_is_validated():
    with pytest.raises(ValueError, match="n_steps"):
        _config("m", seed=1, n_steps=1)
    with pytest.raises(ValueError, match="step_seconds"):
        _config("m", seed=1, step_seconds=0)
    with pytest.raises(ValueError, match="step_seconds"):
        _config("m", seed=1, step_seconds=86400)


def test_unschedulable_variant_in_the_mix_is_rejected(conn):
    """A trap's teaching value is in its look, not its timing - the timeline
    refuses to schedule one rather than silently degrading it."""
    rd.run_reference_engine(conn)
    config = _config("m-trap", seed=1, n_scenarios=1,
                     scenario_mix={pw.VARIANT_SPREAD_ARTIFACT: 1.0})
    with pytest.raises(ValueError, match="not timeline-schedulable"):
        pw.run_timeline_exercise(conn, config)


# --- the schedule -----------------------------------------------------------------


def test_live_window_shape_and_events(conn):
    rd.run_reference_engine(conn)
    config = _config("m-window", seed=5, n_scenarios=3,
                     scenario_mix={pw.VARIANT_GENUINE: 1.0})
    for timeline in _timelines(conn, config):
        onset, resolution = timeline.onset_step, timeline.resolution_step
        assert 1 <= onset < resolution <= config.n_steps
        for step in timeline.steps:
            assert step.live == (onset <= step.step < resolution)
            assert (pw.EVENT_MARKET_DRIFT in step.events) == (step.step > 0)
            assert (pw.EVENT_OPPORTUNITY_ONSET in step.events) == (step.step == onset)
            assert (pw.EVENT_OPPORTUNITY_RESOLUTION in step.events) == (step.step == resolution)


def test_none_schedule_is_a_whole_quiet_timeline(conn):
    """34 §7's 'ordinary periods where nothing interesting happens': the
    market moves for the entire window and there is nothing to find."""
    rd.run_reference_engine(conn)
    config = _config("m-quiet", seed=7, n_scenarios=2, scenario_mix={pw.VARIANT_NONE: 1.0})
    for timeline in _timelines(conn, config):
        assert timeline.onset_step is None and timeline.resolution_step is None
        assert all(not step.live for step in timeline.steps)
    report = pw.run_timeline_exercise(conn, config)
    for entry in report["timelines"]:
        assert entry["outcome"] == "PASS"
        assert all(s["detections"] == [] for s in entry["steps"])
    # A run that never exercised its strategy's own material says so.
    assert report["metrics"]["strategy_exercised"] is False
    assert report["states"][-1] == pw.RETRY_REQUIRED


# --- the market moves; the ladder does not ----------------------------------------


def test_spot_drifts_but_listed_strikes_hold(conn):
    rd.run_reference_engine(conn)
    config = _config("m-drift", seed=9, n_scenarios=2, scenario_mix={pw.VARIANT_NONE: 1.0})
    for timeline in _timelines(conn, config):
        spots = [step.world.spot for step in timeline.steps]
        assert len(set(spots)) > 1  # the market genuinely moved
        ladders = {tuple(row.strike for row in step.world.rows) for step in timeline.steps}
        assert len(ladders) == 1  # the listed contracts did not re-strike
        times = [step.observed_at for step in timeline.steps]
        assert times == sorted(times) and len(set(times)) == len(times)


# --- every schedulable variant, found while live and only while live --------------


@pytest.mark.parametrize("variant", [
    pw.VARIANT_GENUINE, pw.VARIANT_CROSS_BUMP, pw.VARIANT_CALENDAR_BUMP,
    pw.VARIANT_FORWARD_BUMP, pw.VARIANT_FORWARD_DIP,
])
def test_variant_is_detected_exactly_in_its_window(conn, variant):
    rd.run_reference_engine(conn)
    config = _config(f"m-{variant}", seed=13, n_scenarios=2, scenario_mix={variant: 1.0})
    report = pw.run_timeline_exercise(conn, config)
    assert report["states"][-1] == pw.COMPLETED
    for entry in report["timelines"]:
        assert entry["outcome"] == "PASS"
        for step in entry["steps"]:
            if step["live"]:
                assert step["detections"]
            else:
                assert step["detections"] == []


def test_forward_schedule_lists_a_fair_forward_at_every_step(conn):
    """Instrument presence must never correlate with opportunity: the
    forward exists for the whole timeline, fair when quiet (the step ground
    truth is §61's forward_none clean control), shifted when live."""
    rd.run_reference_engine(conn)
    config = _config("m-fwd", seed=17, n_scenarios=2,
                     scenario_mix={pw.VARIANT_FORWARD_BUMP: 1.0})
    for timeline in _timelines(conn, config):
        for step in timeline.steps:
            assert len(step.world.forwards) == len(pw.EXPIRY_DAYS)
            expected = pw.VARIANT_FORWARD_BUMP if step.live else pw.VARIANT_FORWARD_NONE
            assert step.world.ground_truth.variant == expected


def test_live_step_ground_truth_matches_the_static_worlds_shape(conn):
    rd.run_reference_engine(conn)
    config = _config("m-gt", seed=19, n_scenarios=2, scenario_mix={pw.VARIANT_GENUINE: 1.0})
    for timeline in _timelines(conn, config):
        live_gts = [s.world.ground_truth for s in timeline.steps if s.live]
        assert live_gts
        # One persistent opportunity: the same target across the window.
        assert len({(gt.affected_strike, gt.affected_expiry_days) for gt in live_gts}) == 1
        assert all(gt.expected_direction == "conversion" for gt in live_gts)
        quiet_gts = [s.world.ground_truth for s in timeline.steps if not s.live]
        assert all(gt.variant == pw.VARIANT_NONE and not gt.expected_executable for gt in quiet_gts)


# --- reproducibility --------------------------------------------------------------


def test_timelines_are_reproducible_by_seed(conn):
    rd.run_reference_engine(conn)
    config_a = _config("m-repro", seed=23, n_scenarios=3)
    config_b = _config("m-repro", seed=23, n_scenarios=3)
    for a, b in zip(_timelines(conn, config_a), _timelines(conn, config_b)):
        assert (a.variant, a.onset_step, a.resolution_step) == (b.variant, b.onset_step, b.resolution_step)
        for sa, sb in zip(a.steps, b.steps):
            assert sa.world == sb.world
            assert sa.events == sb.events


# --- the stored sequence ----------------------------------------------------------


def test_store_timeline_gives_explorer_an_advancing_market(conn):
    rd.run_reference_engine(conn)
    config = _config("m-store", seed=29, n_scenarios=2, scenario_mix={pw.VARIANT_GENUINE: 1.0})
    result = pw.store_timeline(conn, config)
    assert result["timelines"] == 2
    assert result["stored"]["kept"] == 2 * config.n_steps

    # Explorer's read side sees the LAST step per entity - the newest state
    # of a market that moved - and replay preserves the whole sequence.
    focus = rd.list_focus_assets(conn)
    provider = StoredChainProvider(conn)
    seen = 0
    for asset in focus:
        latest = provider.latest_chain(asset["entity_id"])
        if latest is None:
            continue
        seen += 1
        rows = observation_store.replay(conn, asset["entity_id"], "option_chain")
        assert len(rows) == config.n_steps
        assert latest.observed_at == max(r.observed_at for r in rows)
    assert seen == 2


def test_store_timeline_requires_distinct_assets(conn):
    rd.run_reference_engine(conn)
    many = len(rd.list_focus_assets(conn)) + 1
    config = _config("m-toomany", seed=31, n_scenarios=many)
    with pytest.raises(ValueError, match="distinct focus asset"):
        pw.store_timeline(conn, config)
