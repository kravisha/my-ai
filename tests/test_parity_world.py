"""Tests for simulation/parity_world.py - the Market Data Simulation
Engine's Version 1 mission (addendum 25; docs/SPEC_RECONCILIATION.md SS39/
SS41). Mirrors addendum 25 SS25's testing list: reference dependency,
canonical identifiers, parity-consistency, intentional violations,
reproducibility, chatter synchronization, ground-truth isolation and
strategy coverage.

Runs stay small (n_scenarios <= 8) so the suite stays fast, per the
increment's own instruction."""

import json
import random

import pytest

from backend import reference_data as rd
from backend.arbitrage import ChainSnapshot, CostConfig, Opportunity, StrikeQuotes, scan_chain
from simulation import parity_world as pw
from simulation import pricing

MISSION_KWARGS = dict(run_mode="simulation", strategy="put_call_parity_arbitrage")
CROSS_MISSION_KWARGS = dict(run_mode="simulation", strategy="options_arbitrage_phase1")


def _config(mission_id, seed, **overrides):
    kwargs = dict(MISSION_KWARGS)
    kwargs.update(mission_id=mission_id, seed=seed)
    kwargs.update(overrides)
    return pw.MissionConfig(**kwargs)


# --- reference gate (addendum 25 SS3) -------------------------------------------


def test_refuses_without_reference_ready(conn):
    config = _config("m-refuse", seed=1, n_scenarios=2)
    with pytest.raises(pw.ReferenceNotReady) as exc_info:
        pw.run_parity_exercise(conn, config)
    assert pw.WAITING_FOR_REFERENCE_DATA in str(exc_info.value)


# --- config validation -----------------------------------------------------------


def test_run_mode_other_than_simulation_is_rejected():
    with pytest.raises(ValueError):
        pw.MissionConfig(mission_id="m", run_mode="historical", strategy="put_call_parity_arbitrage", seed=1)


def test_unknown_strategy_is_rejected():
    with pytest.raises(ValueError):
        pw.MissionConfig(mission_id="m", run_mode="simulation", strategy="something_else", seed=1)


def test_from_dict_validates_too():
    with pytest.raises(ValueError):
        pw.MissionConfig.from_dict({
            "mission_id": "m", "run_mode": "live", "strategy": "put_call_parity_arbitrage", "seed": 1,
        })


# --- canonical identifiers (addendum 25 SS3/SS12) -------------------------------


def test_scenarios_use_canonical_focus_asset_identities(conn):
    rd.run_reference_engine(conn)
    focus_by_entity = {a["entity_id"]: a["primary_identifier"] for a in rd.list_focus_assets(conn)}

    config = _config("m-canon", seed=7, n_scenarios=6)
    report = pw.run_parity_exercise(conn, config)

    for entry in report["scenarios"]:
        gt = entry["ground_truth"]
        assert gt["entity_id"] in focus_by_entity
        assert gt["symbol"] == focus_by_entity[gt["entity_id"]]


# --- parity-consistency: no injection means no detection ------------------------


def test_no_injection_mix_produces_an_empty_answer_key(conn):
    """Every 'none' scenario grades PASS with zero detections, unconditionally.
    answer_key runs scan_chain, not per-row detect_arb001 (this increment's
    own switch, SS45), and the one skew shape that can genuinely create a
    cross-strike opportunity on its own ('localized_distortion' -
    tests/test_arbitrage_phase1.py) is excluded from a clean variant's draw
    by construction (`_build_scenario`'s redraw, same module) - a 'none'
    scenario's own ground truth promises no opportunity, and it is never
    allowed to draw the one shape that would make that promise a lie."""
    rd.run_reference_engine(conn)
    for seed in (1, 2, 3):
        config = _config(f"m-none-{seed}", seed=seed, n_scenarios=5, scenario_mix={"none": 1.0})
        report = pw.run_parity_exercise(conn, config)
        for entry in report["scenarios"]:
            assert entry["ground_truth"]["skew_shape"] != "localized_distortion"
            assert entry["detections"] == []
            assert entry["outcome"] == "PASS"


# --- genuine-only mix: every scenario detected -----------------------------------


def test_genuine_only_mix_is_fully_detected(conn):
    rd.run_reference_engine(conn)
    config = _config("m-genuine", seed=11, n_scenarios=6, scenario_mix={"genuine": 1.0})
    report = pw.run_parity_exercise(conn, config)

    assert all(entry["outcome"] == "PASS" for entry in report["scenarios"])
    assert report["metrics"]["pass_rate"] == pytest.approx(1.0)
    assert report["metrics"]["strategy_exercised"] is True
    assert report["states"][-1] == pw.COMPLETED
    # A run whose reference gate never blocked must not claim it waited.
    assert pw.WAITING_FOR_REFERENCE_DATA not in report["states"]


def test_genuine_injection_survives_the_mid_clip_floor(conn):
    """A deviation larger than most put mids would, before the clip fallback,
    silently plant a weaker shift than the ground truth records - the tail
    risk the first implementation disclosed. With the fallback, an unclippable
    direction is used instead and every genuine scenario stays detectable."""
    rd.run_reference_engine(conn)
    config = _config(
        "m-clip", seed=13, n_scenarios=6,
        scenario_mix={"genuine": 1.0}, deviation_range=(5.0, 8.0),
    )
    report = pw.run_parity_exercise(conn, config)
    assert all(entry["outcome"] == "PASS" for entry in report["scenarios"])
    assert report["metrics"]["strategy_exercised"] is True


# --- each trap variant, in isolation, detects nothing ----------------------------


@pytest.mark.parametrize("variant", list(pw.TRAP_VARIANTS))
def test_trap_variant_in_isolation_yields_zero_detections(conn, variant):
    """Every trap variant is a clean-world variant too (`_build_scenario`'s
    redraw treats VARIANT_NONE and every TRAP_VARIANTS member alike), so
    this now asserts unconditional zero detections, no carve-out - a trap's
    own injector only erases the edge IT planted, and 'localized_distortion'
    (the one shape that could otherwise leak an unrelated cross-strike
    violation - tests/test_arbitrage_phase1.py) is excluded from the draw by
    construction. cross_strike_spread_artifact (SS45's deferred item) is
    included in TRAP_VARIANTS, so this parametrization also checks that its
    widened spread at k_mid erases every OTHER cross-strike package through
    k_mid, not only the two packages _inject_cross_spread_artifact
    explicitly floors against."""
    rd.run_reference_engine(conn)
    config = _config(f"m-trap-{variant}", seed=5, n_scenarios=4, scenario_mix={variant: 1.0})
    report = pw.run_parity_exercise(conn, config)

    for entry in report["scenarios"]:
        assert entry["ground_truth"]["variant"] == variant
        assert entry["ground_truth"]["skew_shape"] != "localized_distortion"
        assert entry["detections"] == []
        assert entry["outcome"] == "PASS"


def test_clean_variant_skew_redraw_pins_a_previously_distorting_seed(conn):
    """The constraint itself, pinned: seed=5's scenario index 0 drew
    'localized_distortion' for every clean (none/trap) single-variant mix
    before the redraw existed (verified directly against the pre-redraw
    code - and the exact seed test_trap_variant_in_isolation_yields_zero_
    detections above and tests/test_explorer.py's trap-only mission test
    both rely on staying clean). `_build_scenario`'s redraw now lands
    deterministically on 'inverted_term' instead for every clean variant at
    this (seed, index) - a different, reproducible shape, not merely "not
    localized_distortion" - and the resulting world scans clean end to end,
    the property the redraw exists to guarantee."""
    rd.run_reference_engine(conn)
    for variant in list(pw.TRAP_VARIANTS) + [pw.VARIANT_NONE]:
        config = _config(f"m-clean-redraw-{variant}", seed=5, n_scenarios=1, scenario_mix={variant: 1.0})
        report = pw.run_parity_exercise(conn, config)
        entry = report["scenarios"][0]
        assert entry["ground_truth"]["skew_shape"] == "inverted_term"
        assert entry["detections"] == []
        assert entry["outcome"] == "PASS"


# --- ground-truth isolation (addendum 25 SS15) -----------------------------------


def test_observation_payloads_carry_no_ground_truth(conn):
    rd.run_reference_engine(conn)
    config = _config("m-isolation", seed=13, n_scenarios=4, scenario_mix={"genuine": 0.5, "spread_artifact": 0.5})
    report = pw.run_parity_exercise(conn, config)

    focus_assets = rd.list_focus_assets(conn)
    scenarios = [pw._build_scenario(config, focus_assets, i) for i in range(config.n_scenarios)]
    forbidden = ("variant", "executable", "ground_truth", "expected")
    for scenario in scenarios:
        for observation in pw.observations(scenario, config):
            serialized = json.dumps(observation.as_record())
            for term in forbidden:
                assert term not in serialized

    # the run report itself is allowed to carry ground truth - only the
    # observation payloads must not.
    assert report["scenarios"]


# --- chatter synchronization (addendum 25 SS12) ----------------------------------


def test_chatter_entity_ids_resolve_within_focus_assets_and_signal_matches_scenario(conn):
    rd.run_reference_engine(conn)
    focus_entity_ids = {a["entity_id"] for a in rd.list_focus_assets(conn)}
    config = _config("m-chatter", seed=17, n_scenarios=5, scenario_mix={"genuine": 1.0})
    focus_assets = rd.list_focus_assets(conn)
    scenarios = [pw._build_scenario(config, focus_assets, i) for i in range(config.n_scenarios)]

    for scenario in scenarios:
        for item in scenario.chatter:
            assert item["entity_id"] in focus_entity_ids
        signal_items = [item for item in scenario.chatter if item["symbol"] == scenario.symbol]
        for item in signal_items:
            assert item["entity_id"] == scenario.entity_id


# --- reproducibility (addendum 25 SS20) ------------------------------------------


def test_same_config_run_twice_is_identical(conn, tmp_path):
    rd.run_reference_engine(conn)
    config = _config("m-repro", seed=23, n_scenarios=5)

    report1 = pw.run_parity_exercise(conn, config, runs_dir=tmp_path / "run1")
    report2 = pw.run_parity_exercise(conn, config, runs_dir=tmp_path / "run2")

    assert report1["scenarios"] == report2["scenarios"]
    assert report1["metrics"] == report2["metrics"]
    assert report1["states"] == report2["states"]


# --- mixed default run: metrics consistent, summary written, COMPLETED ----------


def test_mixed_default_run_metrics_are_consistent_and_summary_written(conn, tmp_path):
    rd.run_reference_engine(conn)
    # A seed chosen so the default equal-weight mix draws at least one
    # genuine scenario within a small n_scenarios - verified empirically for
    # this seed/count, per the increment's instruction to ensure at least one
    # genuine scenario by construction of the test's chosen seed.
    config = _config("m-mixed", seed=1, n_scenarios=8)
    report = pw.run_parity_exercise(conn, config, runs_dir=tmp_path)

    variants_seen = {entry["ground_truth"]["variant"] for entry in report["scenarios"]}
    assert "genuine" in variants_seen, "test seed must draw at least one genuine scenario"

    m = report["metrics"]
    assert m["detected"] + m["missed"] == sum(
        1 for e in report["scenarios"] if e["ground_truth"]["variant"] == "genuine"
    )
    assert m["contracts_generated"] == sum(len(s["detections"]) >= 0 for s in report["scenarios"]) * 27
    assert m["chatter_items"] == config.n_scenarios * config.chatter_per_scenario
    assert 0 <= m["pass_rate"] <= 1

    summary_path = report["summary_path"]
    with open(summary_path, encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["mission_id"] == config.mission_id
    assert report["states"][-1] in (pw.COMPLETED, pw.RETRY_REQUIRED)
    if report["states"][-1] == pw.RETRY_REQUIRED:
        assert m["strategy_exercised"] is False


# --- store_world: the mission runner's other entry point -------------------------


def test_store_world_refuses_without_reference_ready(conn):
    config = _config("m-store-refuse", seed=1, n_scenarios=2)
    with pytest.raises(pw.ReferenceNotReady) as exc_info:
        pw.store_world(conn, config)
    assert pw.WAITING_FOR_REFERENCE_DATA in str(exc_info.value)


def test_store_world_stores_one_observation_per_chain_and_chatter_item(conn, tmp_path):
    from backend import observations as observation_store

    rd.run_reference_engine(conn)
    config = _config("m-store-count", seed=3, n_scenarios=5)
    result = pw.store_world(conn, config, runs_dir=tmp_path)

    expected = config.n_scenarios * (1 + config.chatter_per_scenario)
    assert result["stored"]["kept"] + result["stored"]["already_held"] == expected
    assert result["scenarios"] == config.n_scenarios

    # Every scenario's chain must actually land. store_world assigns one
    # distinct focus asset per scenario precisely so the Data Store's
    # idempotency key (entity, class, observed_at, origin, source - all
    # shared within a mission) cannot collapse two scenarios' chains into
    # one and leave the Evaluator blaming agents for a miss the store caused.
    with open(result["summary_path"], encoding="utf-8") as f:
        summary = json.load(f)
    assert len(summary["scenarios"]) == config.n_scenarios
    entities = [s["ground_truth"]["entity_id"] for s in summary["scenarios"]]
    assert len(set(entities)) == config.n_scenarios  # distinct securities
    for entry in summary["scenarios"]:
        chains = observation_store.replay(conn, entry["ground_truth"]["entity_id"], "option_chain")
        assert entry["scenario_id"] in {row.provenance.scenario_id for row in chains}


def test_store_world_refuses_more_scenarios_than_focus_assets(conn, tmp_path):
    rd.run_reference_engine(conn)
    config = _config("m-store-too-many", seed=3, n_scenarios=len(rd.list_focus_assets(conn)) + 1)
    with pytest.raises(ValueError, match="distinct focus asset"):
        pw.store_world(conn, config, runs_dir=tmp_path)


def test_store_world_writes_a_summary_with_per_scenario_ground_truth_and_config(conn, tmp_path):
    rd.run_reference_engine(conn)
    config = _config("m-store-summary", seed=9, n_scenarios=4)
    result = pw.store_world(conn, config, runs_dir=tmp_path)

    with open(result["summary_path"], encoding="utf-8") as f:
        summary = json.load(f)

    assert summary["mission_id"] == config.mission_id
    assert summary["config"]["seed"] == config.seed
    assert len(summary["scenarios"]) == config.n_scenarios
    for entry in summary["scenarios"]:
        assert "scenario_id" in entry
        assert "ground_truth" in entry
        assert "variant" in entry["ground_truth"]
        assert "expected_executable" in entry["ground_truth"]
    # store_world does not run the answer key - there is nothing to evaluate
    # against, unlike run_parity_exercise's own summary.
    for entry in summary["scenarios"]:
        assert "detections" not in entry
        assert "outcome" not in entry


def test_store_world_stored_payloads_still_carry_no_ground_truth(conn, tmp_path):
    """The same isolation property test_observation_payloads_carry_no_ground_truth
    checks for the in-memory Observations, checked again against what actually
    landed in the Data Store - storage must not be a second place ground truth
    could leak through."""
    import json as _json

    from backend import observations as observation_store

    rd.run_reference_engine(conn)
    config = _config("m-store-isolation", seed=13, n_scenarios=4, scenario_mix={"genuine": 0.5, "spread_artifact": 0.5})
    pw.store_world(conn, config, runs_dir=tmp_path)

    forbidden = ("variant", "executable", "ground_truth", "expected")
    for asset in rd.list_focus_assets(conn):
        for data_class in ("option_chain", "social_post"):
            for row in observation_store.replay(conn, asset["entity_id"], data_class):
                serialized = _json.dumps(row.as_record())
                for term in forbidden:
                    assert term not in serialized


def test_store_world_chain_payload_round_trips_everything_a_parity_snapshot_needs(conn, tmp_path):
    """The fields providers/stored_data.py's StoredChainProvider needs to
    reconstruct a backend/arbitrage.py ParitySnapshot: per-leg bid/ask/sizes/
    quoted_at, the underlying quote, r, pv_div per expiry, borrow_fee, style,
    and as_of."""
    rd.run_reference_engine(conn)
    config = _config("m-store-fields", seed=21, n_scenarios=2)
    focus_assets = rd.list_focus_assets(conn)
    scenario = pw._build_scenario(config, focus_assets, 0)
    observation = pw.build_option_chain_observation(scenario, config)
    payload = observation.payload

    assert payload["style"] == "european"
    assert payload["as_of"] == config.base_time
    assert set(payload["underlying"]) >= {"bid", "ask", "bid_size", "ask_size", "quoted_at"}
    assert payload["carry"]["r"] == scenario.r
    assert payload["carry"]["borrow_fee_annual"] == scenario.borrow_fee_annual
    assert {row["expiry_days"] for row in payload["carry"]["pv_div_by_expiry"]} == set(pw.EXPIRY_DAYS)
    for row in payload["chain"]:
        for leg in ("call", "put"):
            assert set(row[leg]) >= {"bid", "ask", "bid_size", "ask_size", "quoted_at"}


# --- cross-strike training injectors (docs/SPEC_RECONCILIATION.md SS45's ---
# --- deferred item) ---------------------------------------------------------


def _cross_config(mission_id, seed, **overrides):
    kwargs = dict(CROSS_MISSION_KWARGS)
    kwargs.update(mission_id=mission_id, seed=seed)
    kwargs.update(overrides)
    return pw.MissionConfig(**kwargs)


def _executable_parity_edges(call, put):
    """(Cbid-Pask, Pbid-Cask) - the two executable parity edges detect_arb001
    actually prices (backend/arbitrage.py's _conversion/_reversal_gross_edge
    both route through these differences)."""
    return round(call.bid - put.ask, 6), round(put.bid - call.ask, 6)


def test_cross_bump_preserves_executable_parity_at_k_mid():
    """A same-strike parallel shift up leaves Cbid-Pask and Pbid-Cask exactly
    unchanged at k_mid (module note above _inject_cross_bump): both legs
    move by the same d, half-spreads unchanged, so both differences cancel
    the shift out algebraically."""
    rng = random.Random("cross-bump-parity-check")
    spot, r, q = 120.0, 0.03, 0.01
    skew = pw.Skew(shape="flat", params={"base_iv": 0.22})
    rows = pw._build_rows(rng, spot, r, q, skew, pw.SPREAD_PCT_DEFAULT, pw.BASE_TIME_DEFAULT)
    idx_prev, idx_mid = pw._cross_strike_indices(rows)
    before = _executable_parity_edges(rows[idx_mid].call, rows[idx_mid].put)

    config = _cross_config("m-bump-parity", seed=1)
    new_rows, deviation = pw._inject_cross_bump(rng, rows, idx_prev, idx_mid, config)
    after = _executable_parity_edges(new_rows[idx_mid].call, new_rows[idx_mid].put)

    assert deviation > 0
    assert before == after


def test_cross_dip_preserves_executable_parity_at_k_mid():
    """Same invariance as the bump, mirrored for the dip direction (both legs
    lowered by the same d)."""
    rng = random.Random("cross-dip-parity-check")
    spot, r, q = 120.0, 0.03, 0.01
    skew = pw.Skew(shape="flat", params={"base_iv": 0.22})
    rows = pw._build_rows(rng, spot, r, q, skew, pw.SPREAD_PCT_DEFAULT, pw.BASE_TIME_DEFAULT)
    idx_prev, idx_mid = pw._cross_strike_indices(rows)
    before = _executable_parity_edges(rows[idx_mid].call, rows[idx_mid].put)

    config = _cross_config("m-dip-parity", seed=1)
    new_rows, deviation, actual_variant = pw._inject_cross_dip(rng, rows, idx_prev, idx_mid, config)
    after = _executable_parity_edges(new_rows[idx_mid].call, new_rows[idx_mid].put)

    assert deviation > 0
    assert actual_variant in (pw.VARIANT_CROSS_DIP, pw.VARIANT_CROSS_BUMP)
    assert before == after


def _thirty_day_chain(scenario, config):
    rows_30 = sorted((row for row in scenario.rows if row.expiry_days == 30), key=lambda row: row.strike)
    strikes = tuple(StrikeQuotes(strike=row.strike, call=row.call, put=row.put) for row in rows_30)
    return ChainSnapshot(
        entity_id=scenario.entity_id, symbol=scenario.symbol, expiry_days=30, style="european",
        as_of=config.base_time, underlying=scenario.underlying, r=scenario.r,
        pv_div=pricing.pv_div(scenario.spot, scenario.q, 30 / 365),
        borrow_fee_annual=scenario.borrow_fee_annual, strikes=strikes,
    )


def test_cross_bump_floor_clears_monotonicity_calls_at_the_affected_pair(conn):
    """The primary package the bump is floored against - ARB-011
    monotonicity_calls at (k_prev, k_mid) - must actually clear in an
    offline scan, across several seeds/scenarios, skipping any scenario
    whose independently-drawn skew is 'localized_distortion' (unrelated
    noise the injector's own floor cannot and need not account for - see
    the trap-variant tests above)."""
    rd.run_reference_engine(conn)
    found = 0
    for seed in (1, 2, 3):
        config = _cross_config(f"m-bump-floor-{seed}", seed=seed, n_scenarios=5, scenario_mix={"cross_strike_bump": 1.0})
        focus_assets = rd.list_focus_assets(conn)
        for i in range(config.n_scenarios):
            scenario = pw._build_scenario(config, focus_assets, i)
            if scenario.ground_truth.skew_shape == "localized_distortion":
                continue
            chain = _thirty_day_chain(scenario, config)
            opps = scan_chain(chain, CostConfig())
            k_prev, k_mid = scenario.ground_truth.affected_strikes
            hit = next(
                (o for o in opps if o.detector_id == "ARB-011" and o.direction == "monotonicity_calls"
                 and o.inputs.get("k1") == k_prev and o.inputs.get("k2") == k_mid),
                None,
            )
            assert hit is not None, f"seed={seed} scenario={i}: monotonicity_calls not found at ({k_prev}, {k_mid})"
            assert hit.net_edge_per_share > 0
            found += 1
    assert found > 0


def test_cross_dip_floor_clears_monotonicity_puts_at_the_affected_pair(conn):
    """Same check as the bump's, for monotonicity_puts - only over scenarios
    whose actual applied variant stayed 'cross_strike_dip' (a clip-fallback
    would have planted the bump's own package instead, which the bump's own
    test above already checks)."""
    rd.run_reference_engine(conn)
    found = 0
    for seed in (1, 2, 3):
        config = _cross_config(f"m-dip-floor-{seed}", seed=seed, n_scenarios=5, scenario_mix={"cross_strike_dip": 1.0})
        focus_assets = rd.list_focus_assets(conn)
        for i in range(config.n_scenarios):
            scenario = pw._build_scenario(config, focus_assets, i)
            gt = scenario.ground_truth
            if gt.skew_shape == "localized_distortion" or gt.variant != pw.VARIANT_CROSS_DIP:
                continue
            chain = _thirty_day_chain(scenario, config)
            opps = scan_chain(chain, CostConfig())
            k_prev, k_mid = gt.affected_strikes
            hit = next(
                (o for o in opps if o.detector_id == "ARB-011" and o.direction == "monotonicity_puts"
                 and o.inputs.get("k1") == k_prev and o.inputs.get("k2") == k_mid),
                None,
            )
            assert hit is not None, f"seed={seed} scenario={i}: monotonicity_puts not found at ({k_prev}, {k_mid})"
            assert hit.net_edge_per_share > 0
            found += 1
    assert found > 0, "no non-distorted, non-fallback dip scenario drawn across these seeds"


def test_cross_dip_clip_fallback_records_the_actual_variant(conn):
    """A deviation_range large enough to clip the dip below the 0.02 mid
    floor (mirroring test_genuine_injection_survives_the_mid_clip_floor's
    own technique) forces the fallback to fire for at least one scenario at
    this seed - ground truth's own `variant` field then reads
    'cross_strike_bump', not the drawn 'cross_strike_dip', and the affected
    strike's mids both still clear the floor."""
    rd.run_reference_engine(conn)
    config = _cross_config(
        "m-dip-clip", seed=13, n_scenarios=6,
        scenario_mix={"cross_strike_dip": 1.0}, deviation_range=(5.0, 8.0),
    )
    focus_assets = rd.list_focus_assets(conn)
    scenarios = [pw._build_scenario(config, focus_assets, i) for i in range(config.n_scenarios)]

    variants = {s.ground_truth.variant for s in scenarios}
    assert variants <= {pw.VARIANT_CROSS_DIP, pw.VARIANT_CROSS_BUMP}
    assert pw.VARIANT_CROSS_BUMP in variants, "expected at least one clip-fallback to fire at this seed"

    for s in scenarios:
        gt = s.ground_truth
        row = next(row for row in s.rows if row.strike == gt.affected_strike and row.expiry_days == 30)
        assert row.call.bid >= 0.01
        assert row.put.bid >= 0.01


# --- cross trap: zero opportunities (SS45's deferred item) ------------------


def test_cross_trap_yields_zero_opportunities_in_the_offline_scan(conn):
    """cross_strike_spread_artifact is a TRAP_VARIANTS member, so it is a
    clean-world variant too - unconditional, no 'localized_distortion'
    carve-out (see test_trap_variant_in_isolation_yields_zero_detections
    above for why)."""
    rd.run_reference_engine(conn)
    for seed in (1, 2, 3):
        config = _cross_config(
            f"m-cross-trap-{seed}", seed=seed, n_scenarios=4, scenario_mix={"cross_strike_spread_artifact": 1.0},
        )
        report = pw.run_parity_exercise(conn, config)
        for entry in report["scenarios"]:
            assert entry["ground_truth"]["variant"] == pw.VARIANT_CROSS_SPREAD_ARTIFACT
            assert entry["ground_truth"]["skew_shape"] != "localized_distortion"
            assert entry["detections"] == []
            assert entry["outcome"] == "PASS"


# --- strategy default mixes --------------------------------------------------


def test_default_scenario_mix_for_parity_strategy_is_pinned_and_unchanged():
    """The parity strategy's default curriculum is byte-for-byte the same
    dict it always was - the six original variants, equal weight - even
    though VARIANTS now includes the three cross-strike additions too."""
    assert pw.DEFAULT_SCENARIO_MIX == {
        "genuine": 1.0, "spread_artifact": 1.0, "carry_effect": 1.0,
        "borrow_cost": 1.0, "stale_quote": 1.0, "none": 1.0,
    }
    config = pw.MissionConfig(mission_id="m", run_mode="simulation", strategy="put_call_parity_arbitrage", seed=1)
    assert config.scenario_mix == pw.DEFAULT_SCENARIO_MIX


def test_default_scenario_mix_for_cross_strike_strategy_includes_cross_variants():
    config = _cross_config("m", seed=1)
    assert set(config.scenario_mix) >= {
        pw.VARIANT_CROSS_BUMP, pw.VARIANT_CROSS_DIP, pw.VARIANT_CROSS_SPREAD_ARTIFACT,
    }
    assert sum(config.scenario_mix.values()) == pytest.approx(1.0)


def test_explicit_cross_mix_allowed_under_the_parity_strategy():
    """A mix is explicit operator intent (item 1's own instruction): cross
    variants are permitted in a scenario_mix under either strategy, only the
    *default* differs by strategy."""
    config = pw.MissionConfig(
        mission_id="m", run_mode="simulation", strategy="put_call_parity_arbitrage", seed=1,
        scenario_mix={pw.VARIANT_CROSS_BUMP: 1.0},
    )
    assert config.scenario_mix == {pw.VARIANT_CROSS_BUMP: 1.0}


# --- offline evaluate: cross-strike grading ----------------------------------


def test_offline_evaluate_grades_cross_genuine_pass(conn):
    rd.run_reference_engine(conn)
    for variant in (pw.VARIANT_CROSS_BUMP, pw.VARIANT_CROSS_DIP):
        config = _cross_config(f"m-eval-{variant}", seed=1, n_scenarios=5, scenario_mix={variant: 1.0})
        report = pw.run_parity_exercise(conn, config)
        for entry in report["scenarios"]:
            if entry["ground_truth"]["skew_shape"] == "localized_distortion":
                continue
            assert entry["outcome"] == "PASS", entry
            assert entry["reasons"] == []


def test_offline_evaluate_grades_planted_arb001_on_cross_as_unexpected_parity_hit(conn):
    """A hand-planted ARB-001 Opportunity added to a genuine cross-strike
    scenario's real scan output must flip the grade to
    FAIL('unexpected_parity_hit') regardless of the real cross-strike hits
    also present - the world-integrity alarm (module note in
    simulation/parity_world.py above the cross-strike injectors) overrides
    everything else."""
    rd.run_reference_engine(conn)
    config = _cross_config("m-eval-unexpected", seed=1, n_scenarios=5, scenario_mix={"cross_strike_bump": 1.0})
    focus_assets = rd.list_focus_assets(conn)
    scenario = next(
        s for s in (pw._build_scenario(config, focus_assets, i) for i in range(config.n_scenarios))
        if s.ground_truth.skew_shape != "localized_distortion"
    )
    opportunities = pw.answer_key(scenario, config)
    assert all(o.detector_id != "ARB-001" for o in opportunities)

    fake_arb001 = Opportunity(
        detector_id="ARB-001", direction="conversion", gross_edge_per_share=0.10, net_edge_per_share=0.05,
        capacity_units=10.0, classification="A",
        inputs={"strike": scenario.ground_truth.affected_strike, "expiry_days": 30},
    )
    result = pw.evaluate(scenario, opportunities + [fake_arb001])
    assert result["outcome"] == "FAIL"
    assert result["reasons"] == ["unexpected_parity_hit"]


# --- calendar variants (ARB-012's training world, §56) ------------------------


def test_calendar_bump_only_mix_is_fully_detected_with_zero_cofire(conn):
    """The whole-ladder lift's three promises, checked through the answer
    key rather than trusted to the algebra: every detection is ARB-012 with
    its near leg at the lifted expiry (zero ARB-001, zero same-expiry
    cross-strike co-fire, by the parallel-shift invariance one level up
    from §46's), and every scenario grades PASS under the 'calendar'
    family."""
    rd.run_reference_engine(conn)
    config = _config(
        "m-calendar", seed=7, n_scenarios=5,
        strategy=pw.STRATEGY_CALENDAR, scenario_mix={pw.VARIANT_CALENDAR_BUMP: 1.0},
    )
    report = pw.run_parity_exercise(conn, config)

    for entry in report["scenarios"]:
        gt = entry["ground_truth"]
        assert gt["variant"] == pw.VARIANT_CALENDAR_BUMP
        assert gt["expected_family"] == "calendar"
        assert gt["affected_expiry_days"] == pw.EXPIRY_DAYS[0]
        assert gt["affected_strike"] is None
        assert entry["detections"], "the lift must be visible to the answer key"
        for detection in entry["detections"]:
            assert detection["detector_id"] == "ARB-012"
            assert detection["expiry_days"] == pw.EXPIRY_DAYS[0]
            assert detection["expiry2_days"] in pw.EXPIRY_DAYS[1:]
        assert entry["outcome"] == "PASS", entry
    assert report["metrics"]["pass_rate"] == pytest.approx(1.0)
    assert report["metrics"]["strategy_exercised"] is True


def test_calendar_strategy_default_mix_is_registered_and_sums_to_one():
    config = pw.MissionConfig(
        mission_id="m", run_mode="simulation", strategy=pw.STRATEGY_CALENDAR, seed=1,
    )
    assert set(config.scenario_mix) >= {pw.VARIANT_CALENDAR_BUMP, pw.VARIANT_CALENDAR_SPREAD_ARTIFACT}
    assert set(config.scenario_mix) <= set(pw.VARIANTS)
    assert sum(config.scenario_mix.values()) == pytest.approx(1.0)
    assert pw.STRATEGY_CALENDAR in pw.STRATEGIES


def test_offline_evaluate_grades_same_expiry_cofire_on_calendar_as_its_own_failure(conn):
    """A hand-planted cross-strike hit on a calendar scenario is the world
    drifting from the whole-ladder invariance - named
    'unexpected_same_expiry_hit', distinct from a stray ARB-012 through the
    wrong expiry pair, so a world defect and an injector defect stay
    distinguishable in the grade."""
    rd.run_reference_engine(conn)
    config = _config(
        "m-cal-cofire", seed=7, n_scenarios=3,
        strategy=pw.STRATEGY_CALENDAR, scenario_mix={pw.VARIANT_CALENDAR_BUMP: 1.0},
    )
    focus_assets = rd.list_focus_assets(conn)
    scenario = pw._build_scenario(config, focus_assets, 0)
    opportunities = pw.answer_key(scenario, config)

    fake_vertical = Opportunity(
        detector_id="ARB-007", direction="call_vertical_upper", gross_edge_per_share=0.10,
        net_edge_per_share=0.05, capacity_units=10.0, classification="A",
        inputs={"k1": 90.0, "k2": 100.0, "expiry_days": 30},
    )
    result = pw.evaluate(scenario, opportunities + [fake_vertical])
    assert result["outcome"] == "FAIL"
    assert result["reasons"] == ["unexpected_same_expiry_hit"]

    fake_stray_calendar = Opportunity(
        detector_id="ARB-012", direction="put_calendar", gross_edge_per_share=0.10,
        net_edge_per_share=0.05, capacity_units=10.0, classification="C",
        inputs={"k1": 100.0, "k2": 100.0, "expiry_days": 30, "expiry2_days": 60},
    )
    result = pw.evaluate(scenario, opportunities + [fake_stray_calendar])
    assert result["outcome"] == "FAIL"
    assert result["reasons"] == ["stray_detection"]


def test_calendar_runs_are_deterministic(conn):
    rd.run_reference_engine(conn)
    reports = []
    for _ in range(2):
        config = _config(
            "m-cal-det", seed=21, n_scenarios=4,
            strategy=pw.STRATEGY_CALENDAR,
        )
        reports.append(pw.run_parity_exercise(conn, config))
    assert [e["ground_truth"] for e in reports[0]["scenarios"]] == \
        [e["ground_truth"] for e in reports[1]["scenarios"]]
    assert [e["detections"] for e in reports[0]["scenarios"]] == \
        [e["detections"] for e in reports[1]["scenarios"]]

