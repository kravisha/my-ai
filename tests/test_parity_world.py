"""Tests for simulation/parity_world.py - the Market Data Simulation
Engine's Version 1 mission (addendum 25; docs/SPEC_RECONCILIATION.md SS39/
SS41). Mirrors addendum 25 SS25's testing list: reference dependency,
canonical identifiers, parity-consistency, intentional violations,
reproducibility, chatter synchronization, ground-truth isolation and
strategy coverage.

Runs stay small (n_scenarios <= 8) so the suite stays fast, per the
increment's own instruction."""

import json

import pytest

from backend import reference_data as rd
from simulation import parity_world as pw

MISSION_KWARGS = dict(run_mode="simulation", strategy="put_call_parity_arbitrage")


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
    rd.run_reference_engine(conn)
    for seed in (1, 2, 3):
        config = _config(f"m-none-{seed}", seed=seed, n_scenarios=5, scenario_mix={"none": 1.0})
        report = pw.run_parity_exercise(conn, config)
        for entry in report["scenarios"]:
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
    rd.run_reference_engine(conn)
    config = _config(f"m-trap-{variant}", seed=5, n_scenarios=4, scenario_mix={variant: 1.0})
    report = pw.run_parity_exercise(conn, config)

    for entry in report["scenarios"]:
        assert entry["ground_truth"]["variant"] == variant
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
