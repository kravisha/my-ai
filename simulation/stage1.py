"""Stage 1 Monte Carlo training exercises (addendum 20 §11).

Stage 1 training generates synthetic worlds and measures detection against
planted ground truth. Monte Carlo samples the configuration space - which
securities are dislocated, how strongly, where, under what regime - and the
deterministic provider renders each drawn world, which is §30's decision made
literal: the fixture that makes the pipeline testable is the rendering layer,
not the thing replaced.

The answer key is precomputed with the organization's own detector run offline
over the same rendered surfaces, so scoring can distinguish what was planted
from what the current lens could possibly see - an organization should not be
blamed for missing what its lens cannot resolve, and should not be credited
for firing on noise.

The key is returned to the caller and written only to the exercise summary
after the run, never to the run database (simulation/personnel.py's rule: a
table holding the answer is a table something can accidentally read).
"""

from __future__ import annotations

import json
import random
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from agents.discovery_config import DEFAULT_PEER_GROUPS
from agents.explorer import scan_for_anomaly
from backend.fi_db import LENS_IV_RATIO_SEED
from providers.market_data import SyntheticMarketDataProvider
from simulation.scenario import MIN_DURATION_SECONDS, Scenario

UNIVERSE = tuple(s for members in DEFAULT_PEER_GROUPS.values() for s in members)

# Sampling ranges. Conventions, not measurements (the disclosure discipline of
# TIMING_CONSTANTS.md): base_level spans calm to stressed around the fixture's
# 0.25 default; noise up to 3x the default makes some worlds genuinely harder;
# plant heights run from below what any honest lens resolves (0.02 over noise
# 0.01-0.03) to unmissable (0.60 vs the default bump's 0.40), because agents
# training only on obvious opportunities learn rote pattern matching, not
# discernment (addendum 20 §10).
BASE_LEVEL_RANGE = (0.15, 0.40)
NOISE_RANGE = (0.005, 0.03)
MAX_PLANTS = 3          # 0..3 per world; zero-plant worlds are false-positive material
HEIGHT_RANGE = (0.02, 0.60)
# Width is capped where the current lens goes blind, and that cap is a
# measurement, not a convention (measured: True). A wide bump raises its own
# local baseline - the neighborhood mean includes the bump's shoulders - so the
# peak/baseline ratio collapses as width grows: across 300 offline worlds,
# plants at width 0.30-0.45 were detectable 39% of the time, 0.45-0.60 35%,
# 0.60-0.80 7%, and 0.80-1.00 never (0/133). The original (0.3, 1.0) range
# produced worlds that were nearly all beyond_lens - honest, but an exercise
# that can never score a hit measures restraint and nothing else. The blind
# spot itself is a real finding about the iv-ratio lens (a wide dislocation is
# invisible to a local-baseline detector by construction) and is recorded in
# SPEC_RECONCILIATION §37; the sampler keeps a 0.60-0.70 tail so every
# exercise still draws some plants from inside it.
WIDTH_RANGE = (0.3, 0.7)
DEFAULT_DURATION_SECONDS = 45.0

# The six outcomes a security can land in once a world's ground truth is
# compared against what the run's detector_events actually recorded. Named as
# a tuple (rather than inferred from dict keys scattered across this module)
# so every place that aggregates counts starts from the same fixed vocabulary
# and a typo in one code path shows up as a KeyError instead of a silently
# absent bucket.
OUTCOMES = ("hit", "miss", "beyond_lens", "artifact_detection", "false_positive", "clean")


@dataclass(frozen=True)
class Plant:
    security: str
    strike_idx: int
    expiry_idx: int
    height: float
    width: float


@dataclass(frozen=True)
class SecurityTruth:
    """detectable means the organization's own scan over the rendered surface
    (not a reimplementation of the detector) meets the seed threshold -
    LENS_IV_RATIO_SEED, the same default the run's own Explorer resolves to
    when the scenario leaves FI_IV_RATIO_THRESHOLD unset."""

    security: str
    plant: Plant | None
    offline_ratio: float
    detectable: bool


@dataclass(frozen=True)
class World:
    index: int
    provider_seed: int
    base_level: float
    noise_amplitude: float
    plants: tuple[Plant, ...]
    truths: tuple[SecurityTruth, ...]

    def anomaly_spec(self) -> dict:
        """{security: {strike_idx, expiry_idx, height, width}} for this
        world's plants - the payload FI_ANOMALY_SPEC expects."""
        return {
            plant.security: {
                "strike_idx": plant.strike_idx,
                "expiry_idx": plant.expiry_idx,
                "height": plant.height,
                "width": plant.width,
            }
            for plant in self.plants
        }

    def scenario(self, duration_seconds: float = DEFAULT_DURATION_SECONDS) -> Scenario:
        """This world, as something the harness can actually run.

        No expected_properties: a sampled world's assertions are the scoring
        (score_run below), not scenario properties - a fixed property list
        cannot know in advance which securities a given draw planted."""
        if self.plants:
            plant_desc = ", ".join(
                f"{plant.security}@(strike={plant.strike_idx},expiry={plant.expiry_idx},"
                f"height={plant.height:.3f})"
                for plant in self.plants
            )
            description = (
                f"Stage 1 sampled world {self.index}: {len(self.plants)} planted "
                f"dislocation(s) - {plant_desc} - under base_level="
                f"{self.base_level:.3f}, noise_amplitude={self.noise_amplitude:.4f}."
            )
        else:
            description = (
                f"Stage 1 sampled world {self.index}: no planted dislocations - false-positive "
                f"material - under base_level={self.base_level:.3f}, "
                f"noise_amplitude={self.noise_amplitude:.4f}."
            )
        return Scenario(
            id=f"stage1-w{self.index}",
            version=1,
            description=description,
            duration_seconds=max(duration_seconds, MIN_DURATION_SECONDS),
            lifecycle="active",
            config={
                "FI_MARKET_PROVIDER_SEED": str(self.provider_seed),
                "FI_MARKET_BASE_LEVEL": str(self.base_level),
                "FI_MARKET_NOISE_AMPLITUDE": str(self.noise_amplitude),
                "FI_ANOMALY_SPEC": json.dumps(self.anomaly_spec()),
            },
            requires_model=True,
        )


@dataclass(frozen=True)
class WorldScore:
    world_index: int
    outcomes: dict[str, str]
    counts: dict[str, int]
    detection_rate: float | None


def _answer_key(
    provider_seed: int, base_level: float, noise_amplitude: float, plants: tuple[Plant, ...]
) -> tuple[SecurityTruth, ...]:
    """The benchmark is the organization's own scan over the same rendered
    surface, not a reimplementation that could drift.

    Built with the real SyntheticMarketDataProvider and the real
    scan_for_anomaly - the identical functions the run itself will use - so
    the answer key can only ever disagree with a run because the run's
    process, threshold, or timing differed, never because this module drifted
    from what Explorer actually does."""
    anomalies = {
        plant.security: {
            "strike_idx": plant.strike_idx,
            "expiry_idx": plant.expiry_idx,
            "height": plant.height,
            "width": plant.width,
        }
        for plant in plants
    }
    regime = {"base_level": base_level, "noise_amplitude": noise_amplitude}
    provider = SyntheticMarketDataProvider(seed=provider_seed, anomalies=anomalies, regime=regime)
    plant_by_security = {plant.security: plant for plant in plants}

    truths = []
    for security in UNIVERSE:
        surface = provider.get_option_surface(security)
        best = scan_for_anomaly(surface)
        # An unplanted security CAN come out detectable when sampled noise
        # happens to form a ratio spike; that is a deceptive surface, recorded
        # as such, and a detector firing there is the lens working as
        # specified, not an organizational defect (see score_run's
        # "artifact_detection" outcome).
        offline_ratio = best[0] if best is not None else 0.0
        detectable = best is not None and best[0] >= LENS_IV_RATIO_SEED
        truths.append(SecurityTruth(
            security=security,
            plant=plant_by_security.get(security),
            offline_ratio=offline_ratio,
            detectable=detectable,
        ))
    return tuple(truths)


def sample_worlds(master_seed: int, count: int) -> list[World]:
    """Draw `count` worlds from `master_seed`, deterministically.

    Each world gets its own child RNG keyed off the world index, the same
    per-branch seeding idiom providers/market_data.py uses per security -
    so drawing 200 worlds and drawing 4 produce identical worlds 0-3, which
    is what makes an exercise reproducible independent of how many worlds
    were asked for."""
    worlds = []
    for index in range(count):
        rng = random.Random(f"{master_seed}:world:{index}")
        provider_seed = rng.randrange(1, 2 ** 31)
        base_level = rng.uniform(*BASE_LEVEL_RANGE)
        noise_amplitude = rng.uniform(*NOISE_RANGE)

        n_plants = rng.randint(0, MAX_PLANTS)
        securities = rng.sample(list(UNIVERSE), n_plants)
        plants = tuple(
            Plant(
                security=security,
                strike_idx=rng.randrange(0, 9),
                expiry_idx=rng.randrange(0, 5),
                height=rng.uniform(*HEIGHT_RANGE),
                width=rng.uniform(*WIDTH_RANGE),
            )
            for security in securities
        )

        truths = _answer_key(provider_seed, base_level, noise_amplitude, plants)
        worlds.append(World(
            index=index,
            provider_seed=provider_seed,
            base_level=base_level,
            noise_amplitude=noise_amplitude,
            plants=plants,
            truths=truths,
        ))
    return worlds


def score_run(db_path: str | Path, world: World) -> WorldScore:
    """Compare a run's detector_events against a world's ground truth.

    Reads only the `security` column of detector_events - deliberately the
    smallest surface this could depend on, so a schema change elsewhere in
    fi_db.py cannot break scoring by accident. Plain sqlite3, not
    backend.fi_db.get_connection: this is a read of one column from a run
    that has already finished, not a participant in the organization's own
    transactions."""
    conn = sqlite3.connect(str(db_path))
    try:
        detected = {row[0] for row in conn.execute("SELECT DISTINCT security FROM detector_events")}
    finally:
        conn.close()

    truths_by_security = {truth.security: truth for truth in world.truths}
    outcomes: dict[str, str] = {}
    counts = {outcome: 0 for outcome in OUTCOMES}

    for security in UNIVERSE:
        truth = truths_by_security[security]
        planted = truth.plant is not None
        was_detected = security in detected

        if planted and was_detected:
            # Covers both "planted, detectable, detected" and "planted, not
            # detectable, detected" - the latter found a real plant however
            # it managed, which still counts as a hit.
            outcome = "hit"
        elif planted and truth.detectable:
            # planted, detectable, not detected
            outcome = "miss"
        elif planted:
            # planted, not detectable, not detected - correct restraint
            outcome = "beyond_lens"
        elif truth.detectable and was_detected:
            # not planted, detectable, detected - the lens fired as specified
            outcome = "artifact_detection"
        elif was_detected:
            # not planted, not detectable, detected - a genuine defect
            outcome = "false_positive"
        else:
            outcome = "clean"

        outcomes[security] = outcome
        counts[outcome] += 1

    hits, misses = counts["hit"], counts["miss"]
    detection_rate = hits / (hits + misses) if (hits + misses) > 0 else None

    return WorldScore(
        world_index=world.index,
        outcomes=outcomes,
        counts=counts,
        detection_rate=detection_rate,
    )


def run_exercise(
    master_seed: int, count: int, duration_seconds: float = DEFAULT_DURATION_SECONDS,
    runs_dir: Path | None = None,
) -> dict:
    """Sample, run, score, and record one Stage 1 exercise.

    The summary file is written only after every world has run and been
    scored - the answer key reaches disk exactly once, at the end, and never
    touches a run database along the way (module docstring)."""
    from simulation import harness

    worlds = sample_worlds(master_seed, count)
    per_world = []
    aggregate_counts = {outcome: 0 for outcome in OUTCOMES}

    for world in worlds:
        result = harness.execute(world.scenario(duration_seconds), runs_dir=runs_dir)
        score = score_run(result.db_path, world)
        for outcome, n in score.counts.items():
            aggregate_counts[outcome] += n
        per_world.append({
            "world": asdict(world),
            "run_id": result.run_id,
            "graceful": result.graceful,
            "score": asdict(score),
        })

    total_hits, total_misses = aggregate_counts["hit"], aggregate_counts["miss"]
    overall_detection_rate = (
        total_hits / (total_hits + total_misses) if (total_hits + total_misses) > 0 else None
    )

    summary = {
        "master_seed": master_seed,
        "count": count,
        "worlds": per_world,
        "aggregate_counts": aggregate_counts,
        "overall_detection_rate": overall_detection_rate,
    }

    out_dir = Path(runs_dir) if runs_dir is not None else harness.RUNS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc)
    out_path = out_dir / f"stage1-{master_seed}-{timestamp:%Y%m%dT%H%M%S}.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Added to the returned dict, not to the file it names - the file does not
    # need to reference its own path.
    summary["summary_path"] = str(out_path)
    return summary
