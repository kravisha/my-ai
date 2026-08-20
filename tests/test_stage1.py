"""Unit tests for simulation/stage1.py - the Monte Carlo world sampler and
scorer.

All fast: no subprocess, no LLM call, no simulation.harness.execute. The
scoring tests stand in a hand-built sqlite database for a finished run's
database, since score_run only ever reads detector_events' security column
(see that function's docstring) - a real harness run is exercised instead by
tests/test_simulation.py's `simulation`-marked tests."""

import dataclasses
import importlib
import json
import re
import sqlite3

import pytest

from agents import discovery_config
from agents.explorer import scan_for_anomaly
from backend.fi_db import LENS_IV_RATIO_SEED
from providers.market_data import SyntheticMarketDataProvider
from simulation import scenario as scenario_module
from simulation import stage1
from simulation.scenario import MIN_DURATION_SECONDS


def _make_detector_events_db(path, detected_securities):
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE detector_events (security TEXT)")
        conn.executemany(
            "INSERT INTO detector_events (security) VALUES (?)",
            [(security,) for security in detected_securities],
        )
        conn.commit()
    finally:
        conn.close()


# --- sampling ----------------------------------------------------------


def test_the_same_master_seed_draws_the_same_worlds():
    first = stage1.sample_worlds(7, 4)
    second = stage1.sample_worlds(7, 4)
    assert [dataclasses.asdict(w) for w in first] == [dataclasses.asdict(w) for w in second]


def test_worlds_vary_and_include_empty_ones():
    worlds = stage1.sample_worlds(7, 200)

    plant_counts = [len(world.plants) for world in worlds]
    assert 0 in plant_counts, "no zero-plant world drawn - false-positive material is missing"
    assert stage1.MAX_PLANTS in plant_counts

    heights = [plant.height for world in worlds for plant in world.plants]
    assert any(h < 0.1 for h in heights), "no plant below what an honest lens resolves"
    assert any(h > 0.4 for h in heights), "no plant above the default bump's own height"

    for world in worlds:
        assert stage1.BASE_LEVEL_RANGE[0] <= world.base_level <= stage1.BASE_LEVEL_RANGE[1]
        assert stage1.NOISE_RANGE[0] <= world.noise_amplitude <= stage1.NOISE_RANGE[1]


# --- the answer key ------------------------------------------------------


def test_the_answer_key_is_computed_with_the_real_detector():
    """The benchmark is the organization's own scan over the same rendered
    surface, not a reimplementation that could drift."""
    obvious = stage1.Plant(security="SYN1", strike_idx=4, expiry_idx=2, height=0.5, width=0.5)
    truths = stage1._answer_key(
        provider_seed=42, base_level=0.25, noise_amplitude=0.005, plants=(obvious,)
    )
    truth = next(t for t in truths if t.security == "SYN1")
    assert truth.plant == obvious
    assert truth.detectable
    assert truth.offline_ratio >= LENS_IV_RATIO_SEED

    faint = stage1.Plant(security="SYN2", strike_idx=4, expiry_idx=2, height=0.02, width=0.5)
    truths2 = stage1._answer_key(
        provider_seed=42, base_level=0.25, noise_amplitude=0.03, plants=(faint,)
    )
    truth2 = next(t for t in truths2 if t.security == "SYN2")
    assert not truth2.detectable


# --- scoring ---------------------------------------------------------------


def test_scoring_classifies_all_six_outcomes(tmp_path):
    plant_kwargs = dict(strike_idx=4, expiry_idx=2, height=0.4, width=0.5)
    plants = {
        "SYN1": stage1.Plant(security="SYN1", **plant_kwargs),
        "SYN2": stage1.Plant(security="SYN2", **plant_kwargs),
        "SYN3": stage1.Plant(security="SYN3", **plant_kwargs),
    }
    # security -> (plant, offline_ratio, detectable)
    truth_specs = {
        "SYN1": (plants["SYN1"], 3.0, True),    # planted, detected -> hit
        "SYN2": (plants["SYN2"], 2.5, True),    # planted, detectable, not detected -> miss
        "SYN3": (plants["SYN3"], 1.1, False),   # planted, not detectable, not detected -> beyond_lens
        "SYN4": (None, 2.2, True),              # not planted, detectable, detected -> artifact_detection
        "SYN5": (None, 1.05, False),            # not planted, not detectable, detected -> false_positive
    }
    default_spec = (None, 1.0, False)  # everything else: not planted, not detectable, not detected -> clean

    truths = tuple(
        stage1.SecurityTruth(
            security=security,
            plant=truth_specs.get(security, default_spec)[0],
            offline_ratio=truth_specs.get(security, default_spec)[1],
            detectable=truth_specs.get(security, default_spec)[2],
        )
        for security in stage1.UNIVERSE
    )
    world = stage1.World(
        index=0, provider_seed=1, base_level=0.25, noise_amplitude=0.01,
        plants=tuple(plants.values()), truths=truths,
    )

    db_path = tmp_path / "run.db"
    _make_detector_events_db(db_path, detected_securities=["SYN1", "SYN4", "SYN5"])

    score = stage1.score_run(db_path, world)

    assert score.outcomes["SYN1"] == "hit"
    assert score.outcomes["SYN2"] == "miss"
    assert score.outcomes["SYN3"] == "beyond_lens"
    assert score.outcomes["SYN4"] == "artifact_detection"
    assert score.outcomes["SYN5"] == "false_positive"
    for security in stage1.UNIVERSE:
        if security not in truth_specs:
            assert score.outcomes[security] == "clean"

    assert score.counts == {
        "hit": 1, "miss": 1, "beyond_lens": 1,
        "artifact_detection": 1, "false_positive": 1,
        "clean": len(stage1.UNIVERSE) - 5,
    }
    assert score.detection_rate == pytest.approx(0.5)  # 1 hit / (1 hit + 1 miss)

    # A second world with a planted-but-undetectable case and no detections at
    # all: detection_rate must be None, not 0/0 or a divide-by-zero.
    quiet_truths = tuple(
        stage1.SecurityTruth(
            security=security,
            plant=plants["SYN3"] if security == "SYN3" else None,
            offline_ratio=1.1,
            detectable=False,
        )
        for security in stage1.UNIVERSE
    )
    quiet_world = stage1.World(
        index=1, provider_seed=2, base_level=0.25, noise_amplitude=0.01,
        plants=(plants["SYN3"],), truths=quiet_truths,
    )
    quiet_db = tmp_path / "quiet.db"
    _make_detector_events_db(quiet_db, detected_securities=[])
    quiet_score = stage1.score_run(quiet_db, quiet_world)
    assert quiet_score.outcomes["SYN3"] == "beyond_lens"
    assert quiet_score.detection_rate is None


# --- scenario construction --------------------------------------------------


def test_a_sampled_world_becomes_a_valid_scenario():
    worlds = stage1.sample_worlds(11, 5)
    config_key = re.compile(r"^FI_[A-Z0-9_]+$")

    for world in worlds:
        scenario = world.scenario()
        for key in scenario.config:
            assert config_key.match(key)
        assert "FI_DB_PATH" not in scenario.config
        assert scenario.requires_model is True
        assert scenario.duration_seconds >= MIN_DURATION_SECONDS

        spec = json.loads(scenario.config["FI_ANOMALY_SPEC"])
        assert set(spec) == {plant.security for plant in world.plants}
        for plant in world.plants:
            assert spec[plant.security] == {
                "strike_idx": plant.strike_idx,
                "expiry_idx": plant.expiry_idx,
                "height": plant.height,
                "width": plant.width,
            }

    short = worlds[0].scenario(duration_seconds=1.0)
    assert short.duration_seconds == MIN_DURATION_SECONDS


# --- env parsing -------------------------------------------------------------


def test_anomaly_spec_env_parsing(monkeypatch):
    monkeypatch.setenv("FI_ANOMALY_SPEC", '{"SYN1": {"height": 0.33}}')
    importlib.reload(discovery_config)
    try:
        assert discovery_config.ANOMALY_SPEC == {"SYN1": {"height": 0.33}}
    finally:
        monkeypatch.delenv("FI_ANOMALY_SPEC", raising=False)
        importlib.reload(discovery_config)
    assert discovery_config.ANOMALY_SPEC == {}


# --- rendering ---------------------------------------------------------------


def test_provider_renders_sampled_plants():
    """An obvious, isolated plant's peak lands exactly where it was sampled to
    be - proof the rendering layer (providers/market_data.py), not just the
    sampler's own bookkeeping, agrees with what a world claims it planted."""
    worlds = stage1.sample_worlds(2024, 200)
    obvious = next(
        w for w in worlds if len(w.plants) == 1 and w.plants[0].height >= 0.3
    )
    plant = obvious.plants[0]
    provider = SyntheticMarketDataProvider(
        seed=obvious.provider_seed,
        anomalies=obvious.anomaly_spec(),
        regime={"base_level": obvious.base_level, "noise_amplitude": obvious.noise_amplitude},
    )
    surface = provider.get_option_surface(plant.security)
    ratio, si, ei, peak_iv, baseline_iv = scan_for_anomaly(surface)
    assert (si, ei) == (plant.strike_idx, plant.expiry_idx)


# --- the shipped scenario ----------------------------------------------------


def test_anomaly_burst_scenario_loads():
    scenarios = scenario_module.load_all()
    assert "anomaly_burst" in scenarios
    scenario = scenarios["anomaly_burst"]
    assert scenario.is_runnable

    spec = json.loads(scenario.config["FI_ANOMALY_SPEC"])
    assert "SYN3" in spec
    assert "SYN9" in spec
