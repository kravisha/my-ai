"""The forward leg's training world (simulation/parity_world.py's forward
variants, SPEC_RECONCILIATION §61, TQ-14): the first world increment that
adds an *instrument* rather than a relation among existing ones.

The load-bearing properties: instrument existence is per-variant (a fair
forward beside the legacy traps would falsify their promises - the module
note above VARIANT_FORWARD_BUMP carries the finance), a fair forward over a
clean chain is silent through the organization's own scan (the clean-world
guarantee), a shifted forward is found by exactly the forward detectors in
exactly the direction the shift explains, and the trap erases through the
forward's own spread. Runs stay small (n_scenarios <= 8), per the world
suite's own instruction."""

import pytest

from backend import reference_data as rd
from backend.arbitrage import Opportunity
from providers.stored_data import forward_quotes
from simulation import parity_world as pw

FORWARD_KWARGS = dict(run_mode="simulation", strategy=pw.STRATEGY_FORWARD)


def _config(mission_id, seed, **overrides):
    kwargs = dict(FORWARD_KWARGS)
    kwargs.update(mission_id=mission_id, seed=seed)
    kwargs.update(overrides)
    return pw.MissionConfig(**kwargs)


def _scenarios(conn, config):
    focus = rd.list_focus_assets(conn)
    return [pw._build_scenario(config, focus, i) for i in range(config.n_scenarios)]


# --- strategy and mix plumbing ---------------------------------------------------


def test_forward_strategy_is_registered_with_a_valid_default_mix():
    assert pw.STRATEGY_FORWARD in pw.STRATEGIES  # mission control lists STRATEGIES verbatim
    config = _config("m-mix", seed=1)
    assert config.scenario_mix == pw.DEFAULT_SCENARIO_MIX_FORWARD
    assert sum(pw.DEFAULT_SCENARIO_MIX_FORWARD.values()) == pytest.approx(1.0)
    assert set(pw.DEFAULT_SCENARIO_MIX_FORWARD) <= set(pw.VARIANTS)


def test_forward_variants_are_known_and_classified():
    for variant in pw.FORWARD_VARIANTS:
        assert variant in pw.VARIANTS
    assert pw.VARIANT_FORWARD_SPREAD_ARTIFACT in pw.TRAP_VARIANTS
    assert pw.VARIANT_FORWARD_NONE in pw.CLEAN_VARIANTS
    assert pw.VARIANT_FORWARD_NONE not in pw.TRAP_VARIANTS


# --- instrument existence is per-variant -----------------------------------------


def test_only_forward_variants_list_a_forward(conn):
    """The world's own statement about instrument existence: forwards in
    every forward-variant scenario (one per listed expiry), none anywhere
    else - the finance in the module note (a fair forward beside a
    borrow_cost trap would arbitrage the trap's own blocked signal)."""
    rd.run_reference_engine(conn)
    for variant in pw.FORWARD_VARIANTS:
        config = _config(f"m-has-{variant}", seed=3, n_scenarios=2, scenario_mix={variant: 1.0})
        for scenario in _scenarios(conn, config):
            assert len(scenario.forwards) == len(pw.EXPIRY_DAYS)
            assert [f.expiry_days for f in scenario.forwards] == list(pw.EXPIRY_DAYS)
    for variant in (pw.VARIANT_GENUINE, pw.VARIANT_BORROW_COST, pw.VARIANT_NONE,
                    pw.VARIANT_CROSS_BUMP, pw.VARIANT_CALENDAR_BUMP):
        config = _config(f"m-not-{variant}", seed=3, n_scenarios=2, scenario_mix={variant: 1.0})
        for scenario in _scenarios(conn, config):
            assert scenario.forwards == ()


# --- the clean-world guarantee ---------------------------------------------------


def test_fair_forward_over_clean_chain_is_silent(conn):
    """forward_none: the instrument exists, nothing is wrong, and the
    organization's whole answer key - chain, calendar AND forward scans -
    finds nothing. The forward-specific false-positive control."""
    rd.run_reference_engine(conn)
    for seed in (1, 2, 3):
        config = _config(f"m-fnone-{seed}", seed=seed, n_scenarios=4,
                         scenario_mix={pw.VARIANT_FORWARD_NONE: 1.0})
        report = pw.run_parity_exercise(conn, config)
        for entry in report["scenarios"]:
            assert entry["detections"] == []
            assert entry["outcome"] == "PASS"


# --- genuine variants ------------------------------------------------------------


def test_forward_bump_is_detected_by_the_forward_detectors_only(conn):
    rd.run_reference_engine(conn)
    config = _config("m-bump", seed=11, n_scenarios=6,
                     scenario_mix={pw.VARIANT_FORWARD_BUMP: 1.0})
    report = pw.run_parity_exercise(conn, config)

    assert all(entry["outcome"] == "PASS" for entry in report["scenarios"])
    assert report["metrics"]["strategy_exercised"] is True
    assert report["states"][-1] == pw.COMPLETED
    for entry in report["scenarios"]:
        gt = entry["ground_truth"]
        assert gt["expected_family"] == "forward"
        assert gt["affected_expiry_days"] == pw.FORWARD_TARGET_EXPIRY
        assert gt["injected_deviation"] > 0  # signed: the mid moved up
        detectors = {d["detector_id"] for d in entry["detections"]}
        assert detectors <= {"ARB-013", "ARB-014"} and detectors
        assert all(d["direction"] in ("sell_forward", "carry") for d in entry["detections"])
        assert all(d["expiry_days"] == pw.FORWARD_TARGET_EXPIRY for d in entry["detections"])


def test_forward_dip_is_detected_in_the_cheap_direction(conn):
    rd.run_reference_engine(conn)
    config = _config("m-dip", seed=13, n_scenarios=6,
                     scenario_mix={pw.VARIANT_FORWARD_DIP: 1.0})
    report = pw.run_parity_exercise(conn, config)

    assert all(entry["outcome"] == "PASS" for entry in report["scenarios"])
    for entry in report["scenarios"]:
        assert entry["ground_truth"]["injected_deviation"] < 0  # signed: down
        assert all(d["direction"] in ("buy_forward", "reverse_carry") for d in entry["detections"])
        # ARB-013's buy side needs no borrow, so at minimum it always fires.
        assert any(d["detector_id"] == "ARB-013" for d in entry["detections"])


# --- the trap --------------------------------------------------------------------


def test_forward_trap_erases_through_the_forwards_own_spread(conn):
    """The same off-fair shift, swallowed by the forward's executable band:
    zero detections of anything, graded PASS - and the mid really is off
    fair (the deviation is recorded), so a mid-price detector would have
    been fooled. addendum 27's non-negotiable rule, forward form."""
    rd.run_reference_engine(conn)
    for seed in (5, 6):
        config = _config(f"m-ftrap-{seed}", seed=seed, n_scenarios=4,
                         scenario_mix={pw.VARIANT_FORWARD_SPREAD_ARTIFACT: 1.0})
        report = pw.run_parity_exercise(conn, config)
        for entry in report["scenarios"]:
            assert entry["detections"] == []
            assert entry["outcome"] == "PASS"
            assert entry["ground_truth"]["injected_deviation"] != 0


# --- reproducibility -------------------------------------------------------------


def test_forward_worlds_are_reproducible_by_seed(conn):
    rd.run_reference_engine(conn)
    config_a = _config("m-repro", seed=21, n_scenarios=4)
    config_b = _config("m-repro", seed=21, n_scenarios=4)
    scenarios_a, scenarios_b = _scenarios(conn, config_a), _scenarios(conn, config_b)
    for a, b in zip(scenarios_a, scenarios_b):
        assert a.forwards == b.forwards
        assert a.ground_truth == b.ground_truth


# --- the observation payload and its read side -----------------------------------


def test_payload_roundtrips_forwards_through_the_stored_provider(conn):
    rd.run_reference_engine(conn)
    config = _config("m-payload", seed=31, n_scenarios=2,
                     scenario_mix={pw.VARIANT_FORWARD_BUMP: 1.0})
    scenario = _scenarios(conn, config)[0]
    observation = pw.build_option_chain_observation(scenario, config)
    assert "forwards" in observation.payload
    assert tuple(forward_quotes(observation)) == scenario.forwards


def test_payload_omits_the_key_when_no_forward_is_listed(conn):
    """Additive compatibility: worlds without the instrument - including
    every world stored before the increment - carry no 'forwards' key at
    all, and the read side answers with the empty no-op list."""
    rd.run_reference_engine(conn)
    config = _config("m-nokey", seed=31, n_scenarios=1, scenario_mix={pw.VARIANT_NONE: 1.0})
    scenario = _scenarios(conn, config)[0]
    observation = pw.build_option_chain_observation(scenario, config)
    assert "forwards" not in observation.payload
    assert forward_quotes(observation) == []


# --- the evaluator's forward family, branch by branch ----------------------------


def _fake(detector_id, direction, expiry_days, strike=100.0):
    inputs = {"expiry_days": expiry_days, "symbol": "TEST", "entity_id": "E1", "as_of": "t"}
    if detector_id != "ARB-014":
        inputs["strike"] = strike
    return Opportunity(detector_id=detector_id, direction=direction, gross_edge_per_share=1.0,
                       net_edge_per_share=0.9, capacity_units=10, classification="A", inputs=inputs)


def _bump_scenario(conn):
    config = _config("m-eval", seed=41, n_scenarios=1,
                     scenario_mix={pw.VARIANT_FORWARD_BUMP: 1.0})
    return _scenarios(conn, config)[0]


def test_evaluate_forward_family_branches(conn):
    rd.run_reference_engine(conn)
    scenario = _bump_scenario(conn)
    target = pw.FORWARD_TARGET_EXPIRY

    matching = _fake("ARB-013", "sell_forward", target)
    assert pw.evaluate(scenario, [matching])["outcome"] == "PASS"

    report = pw.evaluate(scenario, [])
    assert (report["outcome"], report["reasons"]) == ("FAIL", ["injection_missed"])

    # A parity hit on a chain the shift never touched: world drift, its own name.
    report = pw.evaluate(scenario, [matching, _fake("ARB-001", "conversion", target)])
    assert (report["outcome"], report["reasons"]) == ("FAIL", ["unexpected_parity_hit"])

    # Any other option-relation hit likewise - the family's new named failure.
    report = pw.evaluate(scenario, [matching, _fake("ARB-006", "box", target)])
    assert (report["outcome"], report["reasons"]) == ("FAIL", ["unexpected_chain_hit"])

    # A forward package through the wrong expiry, or against the shift's
    # sign, is a stray the injector should not have produced.
    report = pw.evaluate(scenario, [matching, _fake("ARB-013", "sell_forward", pw.EXPIRY_DAYS[0])])
    assert (report["outcome"], report["reasons"]) == ("FAIL", ["stray_detection"])
    report = pw.evaluate(scenario, [_fake("ARB-014", "reverse_carry", target)])
    assert (report["outcome"], report["reasons"]) == ("FAIL", ["stray_detection"])


def test_forward_none_detection_grades_as_false_positive_not_trap(conn):
    rd.run_reference_engine(conn)
    config = _config("m-fp", seed=43, n_scenarios=1, scenario_mix={pw.VARIANT_FORWARD_NONE: 1.0})
    scenario = _scenarios(conn, config)[0]
    report = pw.evaluate(scenario, [_fake("ARB-013", "sell_forward", pw.FORWARD_TARGET_EXPIRY)])
    assert (report["outcome"], report["reasons"]) == ("FAIL", ["false_positive"])


# --- the strategy's own default curriculum runs end to end -----------------------


def test_default_forward_mix_runs_to_completion(conn):
    rd.run_reference_engine(conn)
    config = _config("m-full", seed=51, n_scenarios=8)
    report = pw.run_parity_exercise(conn, config)
    assert report["states"][-1] in (pw.COMPLETED, pw.RETRY_REQUIRED)
    # Whatever the mix drew, no scenario may fail: every variant's promise
    # holds under every other variant's presence in the same run.
    assert all(entry["outcome"] in ("PASS", "PARTIAL") for entry in report["scenarios"])
