"""The Market Data Simulation Engine, Version 1 mission: put-call parity
arbitrage training worlds (addendum 25; docs/SPEC_RECONCILIATION.md SS39/SS41).

**An engine, not an agent** - same precedent as backend/reference_data.py
(addendum 24 SS1, SPEC_RECONCILIATION SS40): pure functions over a database
connection, invoked from orchestration, no charter, no watcher.

## What this mission actually generates

For each scenario: draw one canonical security from the Reference Data
Engine's focus universe (never invented - addendum 25 SS3), price a full
listed option chain on it with simulation/pricing.py's Black-Scholes kernel
so European put-call parity holds by construction, then - for eight of nine
scenario variants - deliberately perturb either one (strike, expiry) pair
(the original six ARB-001/parity variants) or one strike across both legs
at the middle listed expiry (the three cross-strike variants,
docs/SPEC_RECONCILIATION.md SS45's deferred item) into either a genuine
executable arbitrage or a trap that *looks* like one at mid prices but is
not (addendum 27's non-negotiable rule, lived out as training data rather
than only stated as a rule). The ninth variant, 'none', injects nothing -
false-positive material, the same role Stage 1's zero-plant worlds play
(simulation/stage1.py).

The three families train different detectors: the six original variants
train ARB-001 (put-call parity, one strike, one expiry); the three
cross-strike variants (`cross_strike_bump`/`cross_strike_dip`/
`cross_strike_spread_artifact`) train backend/arbitrage.py's Phase 1
cross-strike detectors (ARB-006 through ARB-011) via a same-strike parallel
shift that leaves parity at the shifted strike exactly invariant while
breaking monotonicity/vertical/box/butterfly bounds against the neighboring
strike - see the module note above `_inject_cross_bump` for the algebra;
and the two calendar variants (`calendar_bump`/`calendar_spread_artifact`,
SPEC_RECONCILIATION §56) train ARB-012 via a whole-ladder parallel lift of
the near expiry that extends the same algebra one level up - parity and
every same-expiry relation exactly invariant, only the cross-expiry
relations move. `STRATEGIES` offers a `put_call_parity_arbitrage` mission
(the original six variants, unchanged default mix), an
`options_arbitrage_phase1` mission (a default mix spanning the first two
families), and an `options_arbitrage_calendar` mission (a default mix led
by the calendar variants) - a mix is explicit operator intent in every
case, so any variant is allowed under any strategy; only the per-strategy
*default* differs.

The simulator's own answer key is backend/arbitrage.py's `scan_chain` run
over every expiry's strike ladder - the organization's own chain-level
entry point, which runs ARB-001 per strike alongside every cross-strike
detector, not a reimplementation that could quietly drift from either (the
same reasoning stage1._answer_key gives for reusing scan_for_anomaly rather
than reinventing it).

## Reference gate (addendum 25 SS3, fail closed)

`run_parity_exercise` refuses outright - raises ReferenceNotReady - unless
reference_data.is_ready(conn) AND reference_data.list_focus_assets(conn) is
non-empty. There is no degraded mode: a simulation that invented its own
security identities would be exactly what SS3 forbids.

## Determinism (addendum 25 SS20)

Every timestamp in a run derives from `config.base_time`, never wall clock.
Every random draw is a random.Random seeded from `config.seed` plus a stable
per-branch key (mirroring simulation/stage1.py's own per-world seeding
idiom), so drawing the same config twice reproduces identical scenarios,
ground truth and detections - the property tests/test_parity_world.py checks
directly. Only the summary file's on-disk write time is wall-clock, and it
never enters the returned/written scenario content.

## Ground truth isolation (addendum 25 SS15)

`build_option_chain_observation` and `build_chatter_observations` emit
canonical Observations (backend/canonical.py) whose payloads carry only what
a market/chatter feed would actually carry - bid/ask, sizes, timestamps,
text. The variant, the injected deviation, and whether an opportunity is
"genuine" never appear in a payload; they live only in GroundTruth and the
run summary, which nothing an agent reads consumes (the same separation
simulation/stage1.py keeps between planted answer key and rendered world).

## Chatter's data class: reused, not invented

Addendum 25 SS11 wants synthetic Reddit-style chatter for the Speculator.
simulation/cadences.py already carries `social_post` (IRREGULAR, "always")
for exactly this shape of data, so chatter is emitted as Observations under
that existing class rather than adding a redundant 'social_chatter' entry -
the increment's own instruction to check first and reuse what already fits.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend import reference_data
from backend.arbitrage import ChainSnapshot, CostConfig, Opportunity, Quote, StrikeQuotes, scan_calendar, scan_chain
from backend.canonical import Observation, Provenance
from backend.db import parse_timestamp
# Aliased, not `from backend import observations`: this module defines its
# own `observations()` function below (Explorer's and Speculator's combined
# feed), and that def would shadow a same-named module import by the time
# store_world (which needs backend.observations.store_many) is called.
from backend import observations as observation_store
from simulation import pricing

# --- mission-level constants -------------------------------------------------

# Extensible by design (addendum 25 SS4: "the interface must be designed so
# additional strategies can be added without redesigning the mission
# system"). `options_arbitrage_phase1` (docs/SPEC_RECONCILIATION.md SS45's
# deferred item) is the cross-strike detectors' own training strategy - a
# tuple entry, per SS44's own extensibility claim, not a redesign.
STRATEGY_PARITY = "put_call_parity_arbitrage"
STRATEGY_CROSS_STRIKE = "options_arbitrage_phase1"
STRATEGY_CALENDAR = "options_arbitrage_calendar"
STRATEGIES = (STRATEGY_PARITY, STRATEGY_CROSS_STRIKE, STRATEGY_CALENDAR)

# A convention, not a measurement: an arbitrary fixed Monday afternoon inside
# a nominal equity session. Every timestamp a run produces derives from this
# (config.base_time), never from datetime.now() - the addendum 25 SS20
# reproducibility rule made literal. Callers needing a different clock supply
# their own base_time; this is only the shipped default.
BASE_TIME_DEFAULT = "2026-01-05T14:30:00+00:00"

# The six original scenario variants addendum 25 SS9/SS21 asks for: one
# genuine executable opportunity, four traps that look like one at mid
# prices but are not, and a clean no-injection control - all of them ARB-001
# (same-strike parity) material.
VARIANT_GENUINE = "genuine"
VARIANT_SPREAD_ARTIFACT = "spread_artifact"
VARIANT_CARRY_EFFECT = "carry_effect"
VARIANT_BORROW_COST = "borrow_cost"
VARIANT_STALE_QUOTE = "stale_quote"
VARIANT_NONE = "none"
PARITY_VARIANTS = (
    VARIANT_GENUINE, VARIANT_SPREAD_ARTIFACT, VARIANT_CARRY_EFFECT,
    VARIANT_BORROW_COST, VARIANT_STALE_QUOTE, VARIANT_NONE,
)

# The three cross-strike variants (docs/SPEC_RECONCILIATION.md SS45's
# deferred item): a same-strike parallel shift - call AND put mids at one
# strike moved by the same amount, unchanged half-spreads - leaves every
# executable parity edge at that strike invariant (Cbid-Pask and -Cask+Pbid
# both untouched by a shift applied equally to both legs) while violating
# monotonicity/verticals/butterflies against the neighboring strike. That
# makes 'cross_strike_bump'/'cross_strike_dip' genuine cross-strike
# opportunities with, by construction, zero ARB-001 co-fire - an ARB-001 hit
# on one of these scenarios is a world-integrity alarm, not a second correct
# answer (see _inject_cross_bump/_inject_cross_dip below).
# 'cross_strike_spread_artifact' is the trap: the same shift, erased by a
# widened spread at the bumped strike rather than by the shift never having
# happened.
VARIANT_CROSS_BUMP = "cross_strike_bump"
VARIANT_CROSS_DIP = "cross_strike_dip"
VARIANT_CROSS_SPREAD_ARTIFACT = "cross_strike_spread_artifact"
CROSS_GENUINE_VARIANTS = (VARIANT_CROSS_BUMP, VARIANT_CROSS_DIP)

# The two calendar variants (ARB-012's training world, SPEC_RECONCILIATION
# §56): a whole-ladder parallel lift - every near-expiry cell's call AND put
# mid raised by one constant, half-spreads unchanged. The algebra extends
# §45/§46's same-strike shift one level up: a per-strike parallel shift
# preserves parity at that strike; applying the *same* shift to every strike
# of one expiry additionally preserves every same-expiry cross-strike
# relation (verticals, monotonicity, butterflies, boxes are differences of
# same-expiry prices, all shift-invariant), so the only executable
# relations that move are the cross-expiry ones - ARB-012's, exactly.
# 'calendar_bump' is the genuine variant; 'calendar_spread_artifact' is the
# trap: the same lift, erased by widening every near-expiry cell's spread
# until the organization's own scan_calendar finds nothing.
VARIANT_CALENDAR_BUMP = "calendar_bump"
VARIANT_CALENDAR_SPREAD_ARTIFACT = "calendar_spread_artifact"

VARIANTS = (
    PARITY_VARIANTS + CROSS_GENUINE_VARIANTS
    + (VARIANT_CROSS_SPREAD_ARTIFACT, VARIANT_CALENDAR_BUMP, VARIANT_CALENDAR_SPREAD_ARTIFACT)
)
TRAP_VARIANTS = (
    VARIANT_SPREAD_ARTIFACT, VARIANT_CARRY_EFFECT, VARIANT_BORROW_COST, VARIANT_STALE_QUOTE,
    VARIANT_CROSS_SPREAD_ARTIFACT, VARIANT_CALENDAR_SPREAD_ARTIFACT,
)

# Equal weight per variant - a convention (scenario diversity, addendum 25
# SS21), not a measured training-curriculum split. A caller wanting a
# genuine-only or trap-only run overrides scenario_mix directly (the property
# tests below do exactly that). Unchanged in shape and value from before the
# cross-strike variants existed - the parity strategy's default training
# curriculum is exactly what it always was; only the new strategy's default
# spans the wider variant set (DEFAULT_SCENARIO_MIX_CROSS below).
DEFAULT_SCENARIO_MIX = {variant: 1.0 for variant in PARITY_VARIANTS}

# The cross-strike strategy's default curriculum: a convention, disclosed
# rather than measured (same discipline as DEFAULT_SCENARIO_MIX above).
# Genuine cross material (bump/dip) gets the largest single share since it is
# the strategy's own point; the parity variants stay present at a reduced
# combined weight so a cross-strike-trained run still sees ARB-001 material
# too (options_arbitrage_phase1 covers the whole Phase 1 library, ARB-001
# included). Weights sum to 1.0.
DEFAULT_SCENARIO_MIX_CROSS = {
    VARIANT_GENUINE: 0.20,
    VARIANT_CROSS_BUMP: 0.15,
    VARIANT_CROSS_DIP: 0.15,
    VARIANT_CROSS_SPREAD_ARTIFACT: 0.10,
    VARIANT_SPREAD_ARTIFACT: 0.075,
    VARIANT_CARRY_EFFECT: 0.075,
    VARIANT_BORROW_COST: 0.075,
    VARIANT_STALE_QUOTE: 0.075,
    VARIANT_NONE: 0.10,
}

# The calendar strategy's default curriculum, same disclosure discipline as
# the two above: the calendar variants carry the largest share (they are the
# strategy's point), with parity and cross-strike material kept present so a
# calendar-trained run still exercises the rest of the library, and 'none'
# for false-positive material. Weights sum to 1.0.
DEFAULT_SCENARIO_MIX_CALENDAR = {
    VARIANT_CALENDAR_BUMP: 0.30,
    VARIANT_CALENDAR_SPREAD_ARTIFACT: 0.15,
    VARIANT_GENUINE: 0.125,
    VARIANT_CROSS_BUMP: 0.10,
    VARIANT_SPREAD_ARTIFACT: 0.075,
    VARIANT_BORROW_COST: 0.075,
    VARIANT_STALE_QUOTE: 0.075,
    VARIANT_NONE: 0.10,
}

DEFAULT_SCENARIO_MIX_BY_STRATEGY = {
    STRATEGY_PARITY: DEFAULT_SCENARIO_MIX,
    STRATEGY_CROSS_STRIKE: DEFAULT_SCENARIO_MIX_CROSS,
    STRATEGY_CALENDAR: DEFAULT_SCENARIO_MIX_CALENDAR,
}

# Strike grid as moneyness (K/S - 1) and listed expiries in days - both
# conventions describing a plausible small chain, not a real exchange's
# actual strike/expiry calendar.
MONEYNESS_GRID = (-0.20, -0.15, -0.10, -0.05, 0.00, 0.05, 0.10, 0.15, 0.20)
EXPIRY_DAYS = (7, 30, 60)

# Sampling ranges. Conventions throughout (TIMING_CONSTANTS.md's disclosure
# discipline), not measurements of any real market.
SPOT_RANGE = (40.0, 400.0)                    # $/share
BASE_IV_RANGE = (0.15, 0.35)                  # at-the-money IV band
DEVIATION_RANGE_DEFAULT = (0.30, 1.50)        # $/share parity-violation size
SPREAD_PCT_DEFAULT = 0.01                     # relative half-spread basis
R_RANGE_DEFAULT = (0.01, 0.06)
Q_RANGE_DEFAULT = (0.0, 0.04)
BORROW_FEE_RANGE_DEFAULT = (0.0, 0.02)
STALE_TOLERANCE_DEFAULT = 10.0                # seconds
CHATTER_PER_SCENARIO_DEFAULT = 3
CHATTER_SIGNAL_RATIO_DEFAULT = 0.5
# A small seeded handle pool chatter authors are drawn from - mission-only
# data (module docstring's ground-truth isolation section), not a real
# identity source. Small on purpose: providers/stored_data.py's
# StoredSocialProvider needs an author per post to satisfy Speculator's
# _source_dispersion, and a pool of this size still lets several posts in one
# scenario legitimately share an author without meaning anything by it.
CHATTER_HANDLE_POOL = tuple(f"user{n}" for n in range(1000, 1030))
OPTION_SIZE_RANGE = (10, 200)                 # contracts, per quote side
UNDERLYING_SIZE_RANGE = (100, 2000)           # shares, per quote side

IV_FLOOR, IV_CEILING = 0.05, 1.5

# --- engine states (addendum 25 SS22) ----------------------------------------

NOT_STARTED = "NOT_STARTED"
WAITING_FOR_REFERENCE_DATA = "WAITING_FOR_REFERENCE_DATA"
CONFIGURING = "CONFIGURING"
GENERATING_MARKET = "GENERATING_MARKET"
GENERATING_OPTIONS = "GENERATING_OPTIONS"
GENERATING_SKEW = "GENERATING_SKEW"
INJECTING_OPPORTUNITIES = "INJECTING_OPPORTUNITIES"
GENERATING_INFORMATION_NOISE = "GENERATING_INFORMATION_NOISE"
READY = "READY"
EVALUATING = "EVALUATING"
# Not in addendum 25 SS22's own list literally, but required by SS18's
# strategy-coverage rule: a run that never exercised the selected strategy
# cannot certify COMPLETED. addendum 25's own dashboard section (SS22) lists
# RETRY_REQUIRED among its suggested states, so this is that state, not an
# invention.
RETRY_REQUIRED = "RETRY_REQUIRED"
COMPLETED = "COMPLETED"
FAILED = "FAILED"

STATES = (
    NOT_STARTED, WAITING_FOR_REFERENCE_DATA, CONFIGURING, GENERATING_MARKET,
    GENERATING_OPTIONS, GENERATING_SKEW, INJECTING_OPPORTUNITIES,
    GENERATING_INFORMATION_NOISE, READY, EVALUATING, RETRY_REQUIRED, COMPLETED, FAILED,
)


class ReferenceNotReady(Exception):
    """Refusal to start (addendum 25 SS3, fail closed). Raised rather than
    returned as a status, the same choice backend/reference_data.py's own
    fail-closed checks make for a hard boundary condition - a caller that
    forgets to check a return value cannot accidentally proceed."""


# --- mission configuration ----------------------------------------------------


@dataclass
class MissionConfig:
    """A simulation mission (addendum 25 SS6). Not frozen: from_dict and
    direct construction both funnel through __post_init__'s validation, so
    there is exactly one place a bad config can be rejected, but nothing
    here needs immutability the way a Quote or an Opportunity does."""

    mission_id: str
    run_mode: str
    strategy: str
    seed: int
    asset_classes: tuple[str, ...] = field(default_factory=lambda: ("stock", "stock_option"))
    n_scenarios: int = 12
    base_time: str = BASE_TIME_DEFAULT
    # None means "use this strategy's own default" (__post_init__ below) -
    # a sentinel rather than a fixed default_factory, because the default
    # curriculum is strategy-dependent (DEFAULT_SCENARIO_MIX_BY_STRATEGY)
    # and a dataclass field default cannot see another field's value. An
    # explicitly-passed mix is honored verbatim regardless of strategy - a
    # mix is explicit operator intent, and cross variants are allowed under
    # either strategy; only the *default* differs by strategy.
    scenario_mix: dict | None = None
    deviation_range: tuple[float, float] = DEVIATION_RANGE_DEFAULT
    spread_pct: float = SPREAD_PCT_DEFAULT
    r_range: tuple[float, float] = R_RANGE_DEFAULT
    q_range: tuple[float, float] = Q_RANGE_DEFAULT
    borrow_fee_range: tuple[float, float] = BORROW_FEE_RANGE_DEFAULT
    stale_tolerance_seconds: float = STALE_TOLERANCE_DEFAULT
    chatter_per_scenario: int = CHATTER_PER_SCENARIO_DEFAULT
    chatter_signal_ratio: float = CHATTER_SIGNAL_RATIO_DEFAULT

    def __post_init__(self) -> None:
        self.asset_classes = tuple(self.asset_classes)
        if self.scenario_mix is None:
            # Unknown strategy falls back to the parity default here rather
            # than raising early - _validate() below is what actually rejects
            # an unknown strategy, with a clear message naming it; picking
            # some placeholder mix first just gives it something to reject.
            self.scenario_mix = dict(DEFAULT_SCENARIO_MIX_BY_STRATEGY.get(self.strategy, DEFAULT_SCENARIO_MIX))
        else:
            self.scenario_mix = dict(self.scenario_mix)
        self.deviation_range = tuple(self.deviation_range)
        self.r_range = tuple(self.r_range)
        self.q_range = tuple(self.q_range)
        self.borrow_fee_range = tuple(self.borrow_fee_range)
        self._validate()

    def _validate(self) -> None:
        # addendum 25 SS2's activation rule, enforced at the engine boundary
        # rather than a not-yet-built mission-control UI
        # (docs/SPEC_RECONCILIATION.md SS39).
        if self.run_mode != "simulation":
            raise ValueError(
                f"run_mode must be 'simulation' (addendum 25 SS2's activation rule); got {self.run_mode!r}"
            )
        if self.strategy not in STRATEGIES:
            raise ValueError(f"unknown strategy {self.strategy!r}; supported: {STRATEGIES}")
        if not self.asset_classes or not set(self.asset_classes) <= {"stock", "stock_option"}:
            raise ValueError(
                f"asset_classes must be a non-empty subset of {{'stock', 'stock_option'}}; got {self.asset_classes!r}"
            )
        if not isinstance(self.seed, int):
            raise ValueError(f"seed must be an int; got {self.seed!r}")
        if self.n_scenarios <= 0:
            raise ValueError(f"n_scenarios must be positive; got {self.n_scenarios!r}")
        if not self.scenario_mix:
            raise ValueError("scenario_mix must not be empty")
        unknown = set(self.scenario_mix) - set(VARIANTS)
        if unknown:
            raise ValueError(f"scenario_mix names unknown variant(s) {sorted(unknown)}; known: {VARIANTS}")
        if any(w < 0 for w in self.scenario_mix.values()) or sum(self.scenario_mix.values()) <= 0:
            raise ValueError(f"scenario_mix weights must be non-negative and sum > 0; got {self.scenario_mix!r}")
        for name, rng in (
            ("deviation_range", self.deviation_range), ("r_range", self.r_range),
            ("q_range", self.q_range), ("borrow_fee_range", self.borrow_fee_range),
        ):
            if len(rng) != 2 or rng[0] > rng[1]:
                raise ValueError(f"{name} must be a (low, high) pair with low <= high; got {rng!r}")
        if self.q_range[0] < 0 or self.borrow_fee_range[0] < 0:
            raise ValueError("q_range and borrow_fee_range must be non-negative")
        if not (0 < self.spread_pct < 1):
            raise ValueError(f"spread_pct must be in (0, 1); got {self.spread_pct!r}")
        if self.stale_tolerance_seconds <= 0:
            raise ValueError(f"stale_tolerance_seconds must be positive; got {self.stale_tolerance_seconds!r}")
        if self.chatter_per_scenario < 0:
            raise ValueError("chatter_per_scenario must be non-negative")
        if not (0 <= self.chatter_signal_ratio <= 1):
            raise ValueError(f"chatter_signal_ratio must be in [0, 1]; got {self.chatter_signal_ratio!r}")
        try:
            parse_timestamp(self.base_time)
        except ValueError as exc:
            raise ValueError(f"base_time must be a parseable ISO timestamp; got {self.base_time!r}") from exc

    @classmethod
    def from_dict(cls, data: dict) -> "MissionConfig":
        return cls(**data)


# --- skew generator (addendum 25 SS8) -----------------------------------------

SKEW_SHAPES = (
    "flat", "put_skew", "call_heavy", "steep_put_skew", "shallow_put_skew",
    "smile", "inverted_term", "localized_distortion",
)
_PUT_SKEW_SLOPE_RANGE = (0.3, 0.6)
_CALL_HEAVY_SLOPE_RANGE = (0.3, 0.6)
_STEEP_PUT_SLOPE_RANGE = (0.8, 1.3)
_SHALLOW_PUT_SLOPE_RANGE = (0.1, 0.3)
_SMILE_CURVATURE_RANGE = (1.0, 2.5)
_TERM_BUMP_RANGE = (0.10, 0.30)
_LOCALIZED_BUMP_RANGE = (0.30, 0.60)


@dataclass(frozen=True)
class Skew:
    """One drawn volatility shape. `shape` and `params` are what ground
    truth records (addendum 25 SS15: "what scenario was generated")."""

    shape: str
    params: dict

    def iv(self, moneyness: float, expiry_days: int) -> float:
        base = self.params["base_iv"]
        if self.shape == "flat":
            raw = base
        elif self.shape in ("put_skew", "steep_put_skew", "shallow_put_skew"):
            raw = base + self.params["slope"] * max(0.0, -moneyness)
        elif self.shape == "call_heavy":
            raw = base + self.params["slope"] * max(0.0, moneyness)
        elif self.shape == "smile":
            raw = base + self.params["curvature"] * moneyness ** 2
        elif self.shape == "inverted_term":
            raw = base + self.params["term_bump"] * max(0.0, 1.0 - expiry_days / 60.0)
        elif self.shape == "localized_distortion":
            raw = base
            if abs(moneyness - self.params["target_moneyness"]) < 1e-9 and expiry_days == self.params["target_expiry_days"]:
                raw += self.params["bump"]
        else:
            raise ValueError(f"unknown skew shape {self.shape!r}")
        return min(max(raw, IV_FLOOR), IV_CEILING)


def draw_skew(rng: random.Random) -> Skew:
    shape = rng.choice(SKEW_SHAPES)
    params = {"base_iv": rng.uniform(*BASE_IV_RANGE)}
    if shape in ("put_skew", "steep_put_skew", "shallow_put_skew", "call_heavy"):
        slope_range = {
            "put_skew": _PUT_SKEW_SLOPE_RANGE, "steep_put_skew": _STEEP_PUT_SLOPE_RANGE,
            "shallow_put_skew": _SHALLOW_PUT_SLOPE_RANGE, "call_heavy": _CALL_HEAVY_SLOPE_RANGE,
        }[shape]
        params["slope"] = rng.uniform(*slope_range)
    elif shape == "smile":
        params["curvature"] = rng.uniform(*_SMILE_CURVATURE_RANGE)
    elif shape == "inverted_term":
        params["term_bump"] = rng.uniform(*_TERM_BUMP_RANGE)
    elif shape == "localized_distortion":
        params["target_moneyness"] = rng.choice(MONEYNESS_GRID)
        params["target_expiry_days"] = rng.choice(EXPIRY_DAYS)
        params["bump"] = rng.uniform(*_LOCALIZED_BUMP_RANGE)
    return Skew(shape=shape, params=params)


# --- chain rows and ground truth ----------------------------------------------


@dataclass(frozen=True)
class ChainRow:
    strike: float
    expiry_days: int
    moneyness: float
    sigma: float
    call: Quote
    put: Quote


@dataclass(frozen=True)
class GroundTruth:
    scenario_id: str
    entity_id: str
    symbol: str
    variant: str
    affected_strike: float | None
    affected_expiry_days: int | None
    injected_deviation: float | None
    expected_executable: bool
    expected_direction: str | None
    skew_shape: str
    skew_params: dict
    r: float
    q: float
    borrow_fee_annual: float | None
    # Additive, default None (cross-strike training increment, SS45's
    # deferred item) - existing summaries with neither field still parse.
    # affected_strikes: [k_prev, k_mid] for a cross-strike variant, k_mid
    # (the same value as affected_strike above) primary - affected_strike
    # itself is kept and reused as the primary strike rather than duplicated
    # under a new name, so every variant's "the strike that matters most"
    # lives in one field.
    affected_strikes: list | None = None
    # 'cross_strike' for the two genuine cross variants (bump/dip),
    # 'calendar' for the genuine calendar bump (§56); None for every other
    # variant, traps included - a trap's whole point is that it looks like
    # its genuine sibling but resolves to no opportunity, so it carries no
    # expected family to grade against.
    expected_family: str | None = None


@dataclass(frozen=True)
class ScenarioWorld:
    scenario_id: str
    entity_id: str
    symbol: str
    spot: float
    underlying: Quote
    r: float
    q: float
    borrow_fee_annual: float | None
    rows: tuple[ChainRow, ...]
    ground_truth: GroundTruth
    chatter: tuple[dict, ...]


# --- chain construction --------------------------------------------------------


def _spot_for_symbol(seed: int, symbol: str) -> float:
    """One spot per symbol, independent of scenario index or draw order, so
    the same symbol always gets the same simulated price within a config -
    per-branch seeding, the same idiom simulation/stage1.py uses per world."""
    rng = random.Random(f"{seed}:spot:{symbol}")
    return round(rng.uniform(*SPOT_RANGE), 2)


def _round_strike(raw: float) -> float:
    """Nearest 50-cent increment - a sensible listed-strike granularity,
    disclosed as a convention rather than any real exchange's tick table."""
    return round(raw * 2) / 2


def _draw_variant(rng: random.Random, scenario_mix: dict) -> str:
    names = list(scenario_mix.keys())
    weights = [scenario_mix[name] for name in names]
    return rng.choices(names, weights=weights, k=1)[0]


def _quote_from_mid(rng: random.Random, mid: float, half_spread: float, size_range: tuple[int, int], quoted_at: str) -> Quote:
    bid = max(mid - half_spread, 0.01)
    ask = max(mid + half_spread, bid + 0.01)
    return Quote(
        bid=round(bid, 4), ask=round(ask, 4),
        bid_size=rng.randint(*size_range), ask_size=rng.randint(*size_range),
        quoted_at=quoted_at,
    )


def _requote_keep_sizes(mid: float, half_spread: float, original: Quote, quoted_at: str | None = None) -> Quote:
    """Reprice a leg around a new mid/spread while keeping its sizes and (by
    default) its timestamp - used by every injector below so a mutation
    changes only what the variant actually intends to change."""
    bid = max(mid - half_spread, 0.01)
    ask = max(mid + half_spread, bid + 0.01)
    return Quote(
        bid=round(bid, 4), ask=round(ask, 4),
        bid_size=original.bid_size, ask_size=original.ask_size,
        quoted_at=quoted_at if quoted_at is not None else original.quoted_at,
    )


def _mid_and_half_spread(quote: Quote) -> tuple[float, float]:
    return (quote.bid + quote.ask) / 2, (quote.ask - quote.bid) / 2


def _build_underlying_quote(rng: random.Random, spot: float, spread_pct: float, quoted_at: str) -> Quote:
    half_spread = spot * spread_pct / 2
    return _quote_from_mid(rng, spot, half_spread, UNDERLYING_SIZE_RANGE, quoted_at)


def _build_rows(rng: random.Random, spot: float, r: float, q: float, skew: Skew, spread_pct: float, quoted_at: str) -> list[ChainRow]:
    """Every (moneyness, expiry) cell, priced from the same (spot, r, q,
    sigma) inputs for both legs - parity holds by construction unless a
    variant perturbs a specific row afterward."""
    rows = []
    for moneyness in MONEYNESS_GRID:
        strike = _round_strike(spot * (1 + moneyness))
        for expiry_days in EXPIRY_DAYS:
            t_years = expiry_days / 365
            sigma = skew.iv(moneyness, expiry_days)
            call_mid = pricing.bs_call(spot, strike, t_years, r, q, sigma)
            put_mid = pricing.bs_put(spot, strike, t_years, r, q, sigma)
            call_half_spread = max(call_mid, 0.01) * spread_pct / 2
            put_half_spread = max(put_mid, 0.01) * spread_pct / 2
            rows.append(ChainRow(
                strike=strike, expiry_days=expiry_days, moneyness=moneyness, sigma=sigma,
                call=_quote_from_mid(rng, call_mid, call_half_spread, OPTION_SIZE_RANGE, quoted_at),
                put=_quote_from_mid(rng, put_mid, put_half_spread, OPTION_SIZE_RANGE, quoted_at),
            ))
    return rows


# --- opportunity injection (addendum 25 SS9/SS21) ------------------------------

_INJECTION_COSTS = CostConfig()  # the detector's own defaults - what the answer key will actually charge


def _trial_chains(rows: list[ChainRow], underlying: Quote, r: float, q: float, spot: float,
                  borrow_fee_annual: float | None, as_of: str) -> list[ChainSnapshot]:
    """Every expiry's ladder from a candidate `rows` list, as the trial
    ChainSnapshots the injectors' verification loops scan. One expiry's
    chain used to be enough; once the answer key grew scan_calendar
    (ARB-012, SPEC_RECONCILIATION §56), a trap erased at its own expiry
    could still leak a cross-expiry package - the §46 lesson (injectors leak
    into whatever relations the answer key learns to check next) repeating
    one level up, closed the same way: verify against the organization's own
    scan, over everything the scan can see."""
    rows_by_expiry: dict[int, list[ChainRow]] = {}
    for row in rows:
        rows_by_expiry.setdefault(row.expiry_days, []).append(row)
    chains = []
    for expiry_days in sorted(rows_by_expiry):
        ladder = sorted(rows_by_expiry[expiry_days], key=lambda row: row.strike)
        chains.append(ChainSnapshot(
            entity_id="_trial", symbol="_trial", expiry_days=expiry_days, style="european",
            as_of=as_of, underlying=underlying, r=r,
            pv_div=pricing.pv_div(spot, q, expiry_days / 365),
            borrow_fee_annual=borrow_fee_annual,
            strikes=tuple(StrikeQuotes(strike=row.strike, call=row.call, put=row.put) for row in ladder),
        ))
    return chains


def _touches_cell(opportunity: Opportunity, strike: float, expiry_days: int) -> bool:
    """Whether a scan_chain or scan_calendar package trades a leg at this
    (strike, expiry) cell - the survivor filter the widening loops use, so a
    trap widens for exactly the leakage its own shifted cell causes."""
    inputs = opportunity.inputs
    if opportunity.detector_id == "ARB-012":
        return (inputs["k1"] == strike and inputs["expiry_days"] == expiry_days) or \
            (inputs["k2"] == strike and inputs["expiry2_days"] == expiry_days)
    if inputs.get("expiry_days") != expiry_days:
        return False
    return strike in {inputs.get("strike", inputs.get("k1")), inputs.get("k2"), inputs.get("k3")}


def _surviving_through_cell(rows: list[ChainRow], underlying: Quote, r: float, q: float, spot: float,
                            borrow_fee_annual: float | None, as_of: str,
                            strike: float, expiry_days: int) -> list[Opportunity]:
    """The full-library survivors a trap's shifted cell still causes: the
    cell's own expiry scanned with scan_chain plus every cross-expiry pair
    scanned with scan_calendar, filtered to packages trading that cell."""
    chains = _trial_chains(rows, underlying, r, q, spot, borrow_fee_annual, as_of)
    own = next(chain for chain in chains if chain.expiry_days == expiry_days)
    found = list(scan_chain(own, _INJECTION_COSTS))
    found.extend(scan_calendar(chains, _INJECTION_COSTS))
    return [o for o in found if _touches_cell(o, strike, expiry_days)]


def _conversion_net_at_zero_shift(row: ChainRow, r: float, pv_div_value: float, underlying: Quote) -> float:
    t_years = row.expiry_days / 365
    pvk = row.strike * math.exp(-r * t_years)
    return row.call.bid - row.put.ask - underlying.ask + pv_div_value + pvk - _INJECTION_COSTS.total_per_share


def _reversal_pre_borrow_net_at_zero_shift(row: ChainRow, r: float, pv_div_value: float, underlying: Quote) -> float:
    t_years = row.expiry_days / 365
    pvk = row.strike * math.exp(-r * t_years)
    return -row.call.ask + row.put.bid + underlying.bid - pv_div_value - pvk - _INJECTION_COSTS.total_per_share


def _inject_genuine(rng: random.Random, rows: list[ChainRow], idx: int, spot: float, r: float, q: float,
                     underlying: Quote, config: MissionConfig) -> tuple[list[ChainRow], float]:
    """Shift the put mid down or the call mid up (seeded) so the conversion
    direction clears spread+costs strictly - re-floored per addendum 25 so a
    small drawn deviation can never land right on the boundary."""
    row = rows[idx]
    t_years = row.expiry_days / 365
    pv_div_value = pricing.pv_div(spot, q, t_years)
    delta_min = max(0.0, -_conversion_net_at_zero_shift(row, r, pv_div_value, underlying))
    deviation = max(rng.uniform(*config.deviation_range), delta_min + 0.05)

    call_mid, call_hs = _mid_and_half_spread(row.call)
    put_mid, put_hs = _mid_and_half_spread(row.put)
    # The put_down branch clips at a 0.02 floor, and a clipped shift would
    # under-clear the edge this injector just floored - so a shift the floor
    # would clip falls back to call_up, which has no ceiling to clip against.
    # The rng.choice still always runs, keeping the seeded stream identical
    # whether or not the fallback fires.
    direction_pick = rng.choice(("call_up", "put_down"))
    if direction_pick == "put_down" and put_mid - deviation < 0.02:
        direction_pick = "call_up"
    if direction_pick == "call_up":
        call_mid += deviation
    else:
        put_mid = put_mid - deviation
    new_row = replace(row, call=_requote_keep_sizes(call_mid, call_hs, row.call),
                       put=_requote_keep_sizes(put_mid, put_hs, row.put))
    rows = list(rows)
    rows[idx] = new_row
    return rows, deviation


def _inject_spread_artifact(rng: random.Random, rows: list[ChainRow], idx: int, spot: float, r: float, q: float,
                             underlying: Quote, borrow_fee_annual: float | None,
                             config: MissionConfig) -> tuple[list[ChainRow], float]:
    """Same mid-shift mechanism as genuine, but the spread is then widened
    (both legs, to a shared half-spread) until the executable edge is <= 0 -
    a visible mid-price gap the spread itself erases, addendum 27's
    non-negotiable rule made concrete.

    Cross-strike verification (docs/SPEC_RECONCILIATION.md SS45's deferred
    item, found while building it): this injector's one-legged shift has the
    same structural property SS45's second finding names for the genuine
    variant - it also breaks monotonicity/vertical/box/butterfly bounds
    against the neighboring strike, and the closed-form half-spread above
    only floors the same-strike ARB-001 edge, not those. Once answer_key
    started running the full Phase 1 scan (this increment's own switch) that
    stopped being harmless: a trap that leaks a cross-strike detector is a
    trap that failed its one job. So the closed-form hs is now a starting
    point, verified (and widened further if needed) against an actual
    scan_chain call over the real chain at this row's own expiry - the same
    discipline _inject_cross_spread_artifact below uses for its own
    same-strike verification, applied here because the classic trap
    inherited the same exposure once the answer key it is graded against
    stopped being ARB-001-only."""
    row = rows[idx]
    t_years = row.expiry_days / 365
    pv_div_value = pricing.pv_div(spot, q, t_years)
    pvk = row.strike * math.exp(-r * t_years)
    deviation = rng.uniform(*config.deviation_range)

    call_mid, call_hs = _mid_and_half_spread(row.call)
    put_mid, put_hs = _mid_and_half_spread(row.put)
    # Same clip-fallback as _inject_genuine - the widened spread erases the
    # edge either way, but a clipped shift would make the recorded deviation
    # overstate the mid gap actually planted.
    direction_pick = rng.choice(("call_up", "put_down"))
    if direction_pick == "put_down" and put_mid - deviation < 0.02:
        direction_pick = "call_up"
    if direction_pick == "call_up":
        call_mid += deviation
    else:
        put_mid = put_mid - deviation

    # net_edge(hs) = (call_mid - put_mid - underlying.ask + pv_div + pvk - costs) - 2*hs,
    # for a shared half-spread hs applied to both legs; solve hs so the edge is <= 0.
    base_at_zero_extra = call_mid - put_mid - underlying.ask + pv_div_value + pvk - _INJECTION_COSTS.total_per_share
    required_hs = max(call_hs, put_hs, base_at_zero_extra / 2 + 0.01)

    def _trial_rows(hs: float) -> list[ChainRow]:
        trial = replace(row, call=_requote_keep_sizes(call_mid, hs, row.call),
                        put=_requote_keep_sizes(put_mid, hs, row.put))
        candidate = list(rows)
        candidate[idx] = trial
        return candidate

    # The verification scan is now the whole library over every expiry, not
    # just this row's own ladder - see _trial_chains' docstring for the §56
    # cross-expiry leak this closes (a widened cell whose bid still sat
    # above a longer expiry's ask was invisible to the same-expiry scan).
    for _ in range(50):
        surviving = _surviving_through_cell(
            _trial_rows(required_hs), underlying, r, q, spot, borrow_fee_annual,
            config.base_time, row.strike, row.expiry_days,
        )
        if not surviving:
            break
        required_hs += max(o.net_edge_per_share for o in surviving) + 0.05
    else:
        raise RuntimeError(  # pragma: no cover - safety valve, not expected to trigger
            f"spread-artifact trap failed to converge to zero opportunities at strike={row.strike} "
            f"expiry_days={row.expiry_days} after 50 widening iterations"
        )

    new_row = replace(row, call=_requote_keep_sizes(call_mid, required_hs, row.call),
                       put=_requote_keep_sizes(put_mid, required_hs, row.put))
    rows = list(rows)
    rows[idx] = new_row
    return rows, deviation


def _inject_borrow_cost(rng: random.Random, rows: list[ChainRow], idx: int, spot: float, r: float, q: float,
                         underlying: Quote, config: MissionConfig) -> tuple[list[ChainRow], float, float]:
    """Shift so the reversal direction shows a positive pre-borrow edge, then
    return a borrow fee override high enough to erase exactly that edge -
    the detector must never guess a borrow cost at zero (addendum 27 SS10),
    so the trap here is a real, if punitive, borrow rate, not a hidden one.

    Cross-strike verification (docs/SPEC_RECONCILIATION.md SS45's deferred
    item, found while building it, same reasoning as
    _inject_spread_artifact's own note above): the one-legged shift here has
    the same neighbor-breaking property, and a borrow fee cannot erase a
    box/vertical/butterfly violation - none of those packages' formulas
    depend on borrow cost at all. So after the borrow override is computed
    (unchanged, still solved against the original, unwidened quotes), the
    resulting chain is verified against an actual scan_chain call at this
    row's own expiry and widened (both legs, shared half-spread, the
    borrow-fee-erased reversal edge only gets safer as the spread widens
    further) if anything still trades a leg at this strike - the same
    scan-verified widening _inject_spread_artifact uses, layered on top of
    the borrow erasure rather than replacing it."""
    row = rows[idx]
    t_years = row.expiry_days / 365
    pv_div_value = pricing.pv_div(spot, q, t_years)
    delta_min = max(0.0, -_reversal_pre_borrow_net_at_zero_shift(row, r, pv_div_value, underlying))
    deviation = max(rng.uniform(*config.deviation_range), delta_min + 0.05)

    call_mid, call_hs = _mid_and_half_spread(row.call)
    put_mid, put_hs = _mid_and_half_spread(row.put)
    # Same clip-fallback as _inject_genuine, mirrored: call_down clips at the
    # 0.02 floor, put_up cannot clip.
    direction_pick = rng.choice(("call_down", "put_up"))
    if direction_pick == "call_down" and call_mid - deviation < 0.02:
        direction_pick = "put_up"
    if direction_pick == "call_down":
        call_mid = call_mid - deviation
    else:
        put_mid += deviation
    new_call = _requote_keep_sizes(call_mid, call_hs, row.call)
    new_put = _requote_keep_sizes(put_mid, put_hs, row.put)

    pvk = row.strike * math.exp(-r * t_years)
    pre_borrow_net_after = -new_call.ask + new_put.bid + underlying.bid - pv_div_value - pvk - _INJECTION_COSTS.total_per_share
    required_borrow = pre_borrow_net_after / (underlying.bid * t_years)
    override_borrow_fee = required_borrow + 0.01  # enough surplus to make the post-borrow edge strictly negative

    required_hs = max(call_hs, put_hs)

    def _trial_rows(hs: float) -> list[ChainRow]:
        trial = replace(row, call=_requote_keep_sizes(call_mid, hs, row.call),
                        put=_requote_keep_sizes(put_mid, hs, row.put))
        candidate = list(rows)
        candidate[idx] = trial
        return candidate

    # Whole-library, every-expiry verification - same §56 reasoning as
    # _inject_spread_artifact's loop above.
    for _ in range(50):
        surviving = _surviving_through_cell(
            _trial_rows(required_hs), underlying, r, q, spot, override_borrow_fee,
            config.base_time, row.strike, row.expiry_days,
        )
        if not surviving:
            break
        required_hs += max(o.net_edge_per_share for o in surviving) + 0.05
    else:
        raise RuntimeError(  # pragma: no cover - safety valve, not expected to trigger
            f"borrow-cost trap failed to converge to zero opportunities at strike={row.strike} "
            f"expiry_days={row.expiry_days} after 50 widening iterations"
        )

    new_row = replace(row, call=_requote_keep_sizes(call_mid, required_hs, row.call),
                       put=_requote_keep_sizes(put_mid, required_hs, row.put))
    rows = list(rows)
    rows[idx] = new_row

    return rows, deviation, override_borrow_fee


def _inject_stale_quote(rng: random.Random, rows: list[ChainRow], idx: int, spot: float, r: float, q: float,
                         underlying: Quote, config: MissionConfig) -> tuple[list[ChainRow], float]:
    """A genuine-sized shift, but the affected pair's option quotes are
    stamped stale (base_time minus 3x the tolerance) - the detector must
    refuse on data quality before it ever reaches the pricing math."""
    row = rows[idx]
    t_years = row.expiry_days / 365
    pv_div_value = pricing.pv_div(spot, q, t_years)
    delta_min = max(0.0, -_conversion_net_at_zero_shift(row, r, pv_div_value, underlying))
    deviation = max(rng.uniform(*config.deviation_range), delta_min + 0.05)

    call_mid, call_hs = _mid_and_half_spread(row.call)
    put_mid, put_hs = _mid_and_half_spread(row.put)
    # Same clip-fallback as _inject_genuine (the staleness, not the shift
    # size, is what this trap teaches - but a clipped shift would still make
    # the ground truth's recorded deviation a lie).
    direction_pick = rng.choice(("call_up", "put_down"))
    if direction_pick == "put_down" and put_mid - deviation < 0.02:
        direction_pick = "call_up"
    if direction_pick == "call_up":
        call_mid += deviation
    else:
        put_mid = put_mid - deviation

    stale_quoted_at = (parse_timestamp(config.base_time) - timedelta(seconds=config.stale_tolerance_seconds * 3)).isoformat()
    new_row = replace(
        row,
        call=_requote_keep_sizes(call_mid, call_hs, row.call, quoted_at=stale_quoted_at),
        put=_requote_keep_sizes(put_mid, put_hs, row.put, quoted_at=stale_quoted_at),
    )
    rows = list(rows)
    rows[idx] = new_row
    return rows, deviation


def _locate_row(rows: list[ChainRow], expiry_days: int, moneyness: float) -> int:
    for i, row in enumerate(rows):
        if row.expiry_days == expiry_days and abs(row.moneyness - moneyness) < 1e-9:
            return i
    raise ValueError(f"no row at expiry_days={expiry_days}, moneyness={moneyness}")  # pragma: no cover - grid is fixed


# --- cross-strike injection (SS45's deferred item: training injectors for the
# cross-strike detectors) -------------------------------------------------------
#
# A same-strike parallel shift - call AND put mids at one strike moved by the
# same amount d, unchanged half-spreads - leaves every executable parity edge
# at that strike invariant: new Cbid - new Pask = (Cbid+d) - (Pask+d) =
# Cbid-Pask, and new Pbid - new Cask = (Pbid+d) - (Cask+d) = Pbid-Cask,
# exactly the two executable parity edges detect_arb001 prices. Nothing about
# the underlying, PVK or pv_div moves either, so ARB-001/002/003/010 (every
# same-strike check) stay exactly as clean as they were before the shift.
# What does not survive is monotonicity against the neighboring strike - a
# call raised without its lower neighbor also being raised violates strike
# monotonicity/verticals/butterflies through that pair. That is the whole
# point: a scenario with a genuine, floored cross-strike opportunity and,
# by construction, zero ARB-001 co-fire. An ARB-001 hit on one of these
# scenarios is therefore not a second correct answer - it is a world-
# integrity alarm (simulation/parity_evaluation.py's cross-strike branch
# grades it FAIL('unexpected_parity_hit')).


def _cross_strike_indices(rows: list[ChainRow]) -> tuple[int, int]:
    """(idx_prev, idx_mid) into `rows` for the 30-day expiry's median-
    moneyness strike and its next-lower neighbor. MONEYNESS_GRID has an odd
    length (9), so index len//2 is always an interior strike with both
    neighbors present - a fixed structural position, not a drawn one, so
    every cross-strike scenario perturbs the same place in the grid (the
    same determinism VARIANT_CARRY_EFFECT's own _locate_row call already
    relies on for its own fixed target)."""
    thirty_day = sorted((i, row) for i, row in enumerate(rows) if row.expiry_days == 30)
    mid_pos = len(thirty_day) // 2
    idx_prev = thirty_day[mid_pos - 1][0]
    idx_mid = thirty_day[mid_pos][0]
    return idx_prev, idx_mid


def _inject_cross_bump(
    rng: random.Random, rows: list[ChainRow], idx_prev: int, idx_mid: int, config: MissionConfig,
) -> tuple[list[ChainRow], float]:
    """Raise k_mid's call AND put mids by the same d (module note above).
    Floored against the primary package this shift creates - ARB-011's
    monotonicity_calls at (k_prev, k_mid), buy C_prev at ask / sell C_mid at
    bid: post-shift C_mid.bid must clear C_prev.ask + for_legs(2) strictly.
    d_min uses the pre-shift C_mid.bid (shifting the mid by d shifts the bid
    by the same d, half-spread unchanged), the same re-flooring discipline
    every injector in this module uses so a small drawn deviation can never
    land right on the boundary."""
    row_prev, row_mid = rows[idx_prev], rows[idx_mid]
    costs2 = _INJECTION_COSTS.for_legs(2)

    call_mid, call_hs = _mid_and_half_spread(row_mid.call)
    put_mid, put_hs = _mid_and_half_spread(row_mid.put)

    d_min = max(0.0, row_prev.call.ask + costs2 - row_mid.call.bid)
    deviation = max(rng.uniform(*config.deviation_range), d_min + 0.05)

    new_call = _requote_keep_sizes(call_mid + deviation, call_hs, row_mid.call)
    new_put = _requote_keep_sizes(put_mid + deviation, put_hs, row_mid.put)
    new_row = replace(row_mid, call=new_call, put=new_put)
    rows = list(rows)
    rows[idx_mid] = new_row
    return rows, deviation


def _inject_cross_dip(
    rng: random.Random, rows: list[ChainRow], idx_prev: int, idx_mid: int, config: MissionConfig,
) -> tuple[list[ChainRow], float, str]:
    """Lower k_mid's call AND put mids by the same d - parity-preserving
    exactly as the bump is, breaking monotonicity through the lower
    neighbor's PUT instead of its call. Floored against ARB-011's
    monotonicity_puts at (k_prev, k_mid): post-shift P_prev.bid must clear
    P_mid.ask + for_legs(2) strictly; d_min = P_mid.ask - (P_prev.bid -
    for_legs(2)), using the pre-shift P_mid.ask.

    Clip-fallback: lowering both mids by a large d could push one below the
    0.02 floor _quote_from_mid/_requote_keep_sizes enforce, silently planting
    a weaker shift than ground truth would record - the same tail risk
    review closed for _inject_genuine (SPEC_RECONCILIATION.md SS41). Here the
    fallback is the bump direction, which has no floor to clip against: the
    already-drawn raw deviation is re-floored against the bump's own package
    (monotonicity_calls) rather than drawing a fresh value, so the rng
    stream consumed is identical whether or not the fallback fires (only the
    one `rng.uniform` call above runs either way). Ground truth then records
    the variant ACTUALLY applied (the caller reads this function's third
    return value) - a ground truth that lies about what was planted would
    defeat the Evaluator."""
    row_prev, row_mid = rows[idx_prev], rows[idx_mid]
    costs2 = _INJECTION_COSTS.for_legs(2)
    raw = rng.uniform(*config.deviation_range)

    call_mid, call_hs = _mid_and_half_spread(row_mid.call)
    put_mid, put_hs = _mid_and_half_spread(row_mid.put)

    dip_d_min = max(0.0, row_mid.put.ask - (row_prev.put.bid - costs2))
    dip_deviation = max(raw, dip_d_min + 0.05)

    if call_mid - dip_deviation < 0.02 or put_mid - dip_deviation < 0.02:
        bump_d_min = max(0.0, row_prev.call.ask + costs2 - row_mid.call.bid)
        bump_deviation = max(raw, bump_d_min + 0.05)
        new_call = _requote_keep_sizes(call_mid + bump_deviation, call_hs, row_mid.call)
        new_put = _requote_keep_sizes(put_mid + bump_deviation, put_hs, row_mid.put)
        new_row = replace(row_mid, call=new_call, put=new_put)
        rows = list(rows)
        rows[idx_mid] = new_row
        return rows, bump_deviation, VARIANT_CROSS_BUMP

    new_call = _requote_keep_sizes(call_mid - dip_deviation, call_hs, row_mid.call)
    new_put = _requote_keep_sizes(put_mid - dip_deviation, put_hs, row_mid.put)
    new_row = replace(row_mid, call=new_call, put=new_put)
    rows = list(rows)
    rows[idx_mid] = new_row
    return rows, dip_deviation, VARIANT_CROSS_DIP


def _inject_cross_spread_artifact(
    rng: random.Random, rows: list[ChainRow], idx_prev: int, idx_mid: int, r: float, q: float,
    spot: float, underlying: Quote, borrow_fee_annual: float | None, config: MissionConfig,
) -> tuple[list[ChainRow], float]:
    """The bump's own shift (same package/floor as _inject_cross_bump), then
    a shared half-spread at k_mid widened until the whole 30-day chain scans
    clean of every package trading a k_mid leg.

    A closed-form floor against the two packages the primary shift is known
    to create - ARB-011 monotonicity_calls at (k_prev, k_mid), and
    put_vertical_upper at the same pair - gives a starting half-spread,
    solved the same way _inject_spread_artifact solves its own required
    half-spread (+0.01 margin). That floor is a lower bound, not a proof:
    widening a strike's spread does not uniformly make every package
    touching it harder - a butterfly or vertical/box against a FARTHER
    strike (or the neighbor on the other side) can still clear after the
    closed-form floor, discovered by exactly the check this function now
    performs rather than asserted away. So the candidate half-spread is
    verified against an actual scan_chain call over the real 30-day ladder,
    widened further and re-checked when any package still trading a k_mid
    leg survives, until the scan agrees - the only way to be certain against
    every package the scan itself enumerates rather than trusting a
    per-package derivation to be exhaustive. A surviving opportunity that
    does NOT touch k_mid at all (an independent, unrelated violation - e.g.
    a co-drawn 'localized_distortion' skew bump elsewhere in the chain,
    docs/SPEC_RECONCILIATION.md SS45's first finding) is left alone: no
    amount of widening at k_mid could erase a violation that never touched
    it, and this injector's job is only the shift it itself planted.

    §56: the verification scan is now _surviving_through_cell - the whole
    library over every expiry, calendar packages included - because the
    parallel shift also lifts this 30-day cell against the 60-day ladder."""
    row_prev, row_mid = rows[idx_prev], rows[idx_mid]
    costs2 = _INJECTION_COSTS.for_legs(2)
    t_years = 30 / 365

    call_mid, call_hs = _mid_and_half_spread(row_mid.call)
    put_mid, put_hs = _mid_and_half_spread(row_mid.put)

    bump_d_min = max(0.0, row_prev.call.ask + costs2 - row_mid.call.bid)
    deviation = max(rng.uniform(*config.deviation_range), bump_d_min + 0.05)

    call_mid_shifted = call_mid + deviation
    put_mid_shifted = put_mid + deviation
    pv_width = (row_mid.strike - row_prev.strike) * math.exp(-r * t_years)

    # hs such that monotonicity_calls' net <= 0:
    #   (call_mid_shifted - hs) - row_prev.call.ask - costs2 <= 0
    hs_monotonicity = call_mid_shifted - row_prev.call.ask - costs2 + 0.01
    # hs such that put_vertical_upper's net <= 0:
    #   (put_mid_shifted - hs) - row_prev.put.ask - pv_width - costs2 <= 0
    hs_put_vertical_upper = put_mid_shifted - row_prev.put.ask - pv_width - costs2 + 0.01
    required_hs = max(call_hs, put_hs, hs_monotonicity, hs_put_vertical_upper)

    def _trial_rows(hs: float) -> list[ChainRow]:
        trial = replace(row_mid, call=_requote_keep_sizes(call_mid_shifted, hs, row_mid.call),
                        put=_requote_keep_sizes(put_mid_shifted, hs, row_mid.put))
        candidate = list(rows)
        candidate[idx_mid] = trial
        return candidate

    # Whole-library, every-expiry verification (§56): the parallel shift at
    # k_mid also lifts the 30-day cell against the 60-day ladder, which the
    # 30-day-only scan this loop used to run could never see.
    for _ in range(50):
        surviving = _surviving_through_cell(
            _trial_rows(required_hs), underlying, r, q, spot, borrow_fee_annual,
            config.base_time, row_mid.strike, 30,
        )
        if not surviving:
            break
        required_hs += max(o.net_edge_per_share for o in surviving) + 0.05
    else:
        raise RuntimeError(  # pragma: no cover - safety valve, not expected to trigger
            "cross-strike spread-artifact trap failed to converge to zero opportunities at k_mid "
            f"(strike={row_mid.strike}) after 50 widening iterations"
        )

    new_call = _requote_keep_sizes(call_mid_shifted, required_hs, row_mid.call)
    new_put = _requote_keep_sizes(put_mid_shifted, required_hs, row_mid.put)
    new_row = replace(row_mid, call=new_call, put=new_put)
    rows = list(rows)
    rows[idx_mid] = new_row
    return rows, deviation


def _lift_expiry(rows: list[ChainRow], expiry_days: int, lift: float) -> list[ChainRow]:
    """Every cell at one expiry, both legs' mids shifted by the same amount,
    half-spreads/sizes/timestamps untouched - the whole-ladder parallel lift
    whose invariances the calendar variants rest on (module note above
    VARIANT_CALENDAR_BUMP)."""
    lifted = []
    for row in rows:
        if row.expiry_days != expiry_days:
            lifted.append(row)
            continue
        call_mid, call_hs = _mid_and_half_spread(row.call)
        put_mid, put_hs = _mid_and_half_spread(row.put)
        lifted.append(replace(
            row,
            call=_requote_keep_sizes(call_mid + lift, call_hs, row.call),
            put=_requote_keep_sizes(put_mid + lift, put_hs, row.put),
        ))
    return lifted


def _calendar_lift_floor(rows: list[ChainRow], spot: float, r: float, q: float) -> float:
    """The smallest lift that makes the ATM same-strike near-vs-middle PUT
    package clear strictly: deviation > P_far_ask - P_near_bid + slack_p +
    costs, with slack_p per detect_arb012's own proven-rule derivation
    (backend/arbitrage.py). The put side, deliberately: it is the side with
    an unconditional proven rule - the call side is only scoreable on a
    dividend-free chain, and this world usually carries a dividend yield.
    Mirrors the detector's arithmetic so the floor and the answer key
    cannot disagree about what "clears" means."""
    near_expiry, far_expiry = EXPIRY_DAYS[0], EXPIRY_DAYS[1]
    near_atm = rows[_locate_row(rows, expiry_days=near_expiry, moneyness=0.00)]
    far_atm = rows[_locate_row(rows, expiry_days=far_expiry, moneyness=0.00)]
    df1 = math.exp(-r * near_expiry / 365)
    df2 = math.exp(-r * far_expiry / 365)
    slack_p = max(0.0, near_atm.strike * df1 - far_atm.strike * df2)
    return far_atm.put.ask - near_atm.put.bid + slack_p + _INJECTION_COSTS.for_legs(2)


def _inject_calendar_bump(rng: random.Random, rows: list[ChainRow], spot: float, r: float, q: float,
                          underlying: Quote, borrow_fee_annual: float | None,
                          config: MissionConfig) -> tuple[list[ChainRow], float]:
    """The genuine calendar variant (§56): lift the whole near-expiry ladder.

    Invariances, by the same algebra as the cross-strike shift one level up:
    parity at every strike (call and put shifted equally), every same-expiry
    cross-strike relation (all are differences of same-expiry prices, and
    every cell moved by the same constant), and the parity-implied dividend/
    financing (C-P unchanged). What moves is exactly the cross-expiry
    relation ARB-012 prices - so an ARB-001 or cross-strike detection on a
    calendar scenario is a world-integrity alarm, verified below with the
    organization's own scans rather than trusted to the algebra: rounding
    and the 0.01 bid floor are exactly the kind of seam §46 found closed
    forms leaking through."""
    near_expiry = EXPIRY_DAYS[0]
    floor = _calendar_lift_floor(rows, spot, r, q)
    deviation = max(rng.uniform(*config.deviation_range), floor + 0.05)
    lifted = _lift_expiry(rows, near_expiry, deviation)

    chains = _trial_chains(lifted, underlying, r, q, spot, borrow_fee_annual, config.base_time)
    for chain in chains:
        leaked = scan_chain(chain, _INJECTION_COSTS)
        if leaked:  # pragma: no cover - world-integrity check, not expected to trigger
            raise RuntimeError(
                f"calendar bump leaked {len(leaked)} same-expiry package(s) at "
                f"expiry_days={chain.expiry_days} (first: {leaked[0].detector_id} "
                f"{leaked[0].direction}) - the parallel-lift invariance failed"
            )
    fired = scan_calendar(chains, _INJECTION_COSTS)
    if not any(o.inputs["expiry_days"] == near_expiry for o in fired):  # pragma: no cover - same
        raise RuntimeError(
            f"calendar bump of {deviation:.4f} produced no ARB-012 package through the "
            f"{near_expiry}d ladder - the lift floor is wrong"
        )
    return lifted, deviation


def _inject_calendar_spread_artifact(rng: random.Random, rows: list[ChainRow], spot: float, r: float,
                                     q: float, underlying: Quote, borrow_fee_annual: float | None,
                                     config: MissionConfig) -> tuple[list[ChainRow], float]:
    """The calendar trap: the same whole-ladder lift, erased by widening
    every near-expiry cell's spread (both legs, an extra shared half-spread)
    until scan_calendar over all three ladders finds nothing at all. A
    mid-level calendar inversion the spread swallows - addendum 27's
    non-negotiable rule, in calendar form.

    Widening a whole ladder uniformly cannot create same-expiry packages
    (every executable edge is bid-minus-ask arithmetic that only worsens as
    spreads grow), so the loop's exit condition also asserts the same-expiry
    scans stayed clean rather than assuming it."""
    near_expiry = EXPIRY_DAYS[0]
    floor = _calendar_lift_floor(rows, spot, r, q)
    deviation = max(rng.uniform(*config.deviation_range), floor + 0.05)
    lifted = _lift_expiry(rows, near_expiry, deviation)

    extra_hs = deviation / 2
    for _ in range(50):
        widened = []
        for row in lifted:
            if row.expiry_days != near_expiry:
                widened.append(row)
                continue
            call_mid, call_hs = _mid_and_half_spread(row.call)
            put_mid, put_hs = _mid_and_half_spread(row.put)
            widened.append(replace(
                row,
                call=_requote_keep_sizes(call_mid, call_hs + extra_hs, row.call),
                put=_requote_keep_sizes(put_mid, put_hs + extra_hs, row.put),
            ))
        chains = _trial_chains(widened, underlying, r, q, spot, borrow_fee_annual, config.base_time)
        surviving = scan_calendar(chains, _INJECTION_COSTS)
        if not surviving:
            for chain in chains:
                leaked = scan_chain(chain, _INJECTION_COSTS)
                if leaked:  # pragma: no cover - world-integrity check, not expected to trigger
                    raise RuntimeError(
                        f"calendar trap's widening leaked a same-expiry package at "
                        f"expiry_days={chain.expiry_days}: {leaked[0].detector_id}"
                    )
            return widened, deviation
        extra_hs += max(o.net_edge_per_share for o in surviving) + 0.05
    raise RuntimeError(  # pragma: no cover - safety valve, not expected to trigger
        f"calendar trap failed to converge to zero calendar packages after 50 widening "
        f"iterations (lift={deviation:.4f})"
    )


# --- chatter (addendum 25 SS11/SS12) --------------------------------------------

_SIGNAL_TEMPLATES = (
    "unusual options activity in {symbol} today - someone's loading up on calls",
    "{symbol} volume at the {strike} strike looks off, feels like something's brewing",
    "not convinced this {symbol} move means anything, could just be noise",
    "{symbol} puts printing weird sizes, keeping an eye on it",
    "heard whispers about {symbol}, no idea if it's real",
)
_NOISE_TEMPLATES = (
    "anyone watching {symbol}? quiet session so far",
    "{symbol} earnings next month, setting a reminder",
    "heard {symbol} might get added to some index, totally unconfirmed",
    "market's dead today, nothing interesting anywhere",
)
_STANCES = ("bullish", "bearish", "skeptical", "neutral")


def _generate_chatter(rng: random.Random, gt: GroundTruth, focus_assets: list[dict], config: MissionConfig) -> tuple[dict, ...]:
    """chatter_per_scenario items, synchronized to the same simulated world
    (addendum 25 SS12): a `chatter_signal_ratio` fraction of items on an
    injected scenario mention the affected symbol; the rest are noise
    referencing some other focus security, or - for the 'nothing' case -
    generic text still filed under another focus entity, since an
    Observation requires an entity_id (backend/canonical.py) and chatter
    with no subject at all has nowhere canonical to attach."""
    others = [a for a in focus_assets if a["entity_id"] != gt.entity_id]
    items = []
    for _ in range(config.chatter_per_scenario):
        is_signal = gt.variant != VARIANT_NONE and rng.random() < config.chatter_signal_ratio
        if is_signal:
            symbol, entity_id = gt.symbol, gt.entity_id
            strike = gt.affected_strike if gt.affected_strike is not None else "?"
            text = rng.choice(_SIGNAL_TEMPLATES).format(symbol=symbol, strike=strike)
        else:
            other = rng.choice(others) if others else {"primary_identifier": gt.symbol, "entity_id": gt.entity_id}
            entity_id = other["entity_id"]
            if others and rng.random() < 0.75:
                symbol = other["primary_identifier"]
                text = rng.choice(_NOISE_TEMPLATES).format(symbol=symbol)
            else:
                symbol = None
                text = "market's dead today, nothing interesting anywhere"
        offset_minutes = rng.uniform(0, 120)
        posted_at = (parse_timestamp(config.base_time) - timedelta(minutes=offset_minutes)).isoformat()
        items.append({
            "posted_at": posted_at, "symbol": symbol, "entity_id": entity_id,
            "text": text, "stance": rng.choice(_STANCES),
            # author/engagement_score: what providers/stored_data.py's
            # StoredSocialProvider needs to satisfy Speculator's SocialPost
            # interface (source, author, posted_at, text, engagement_score) -
            # mission-only data, drawn from the seeded rng like everything
            # else here, never a function of the variant or signal/noise
            # split above.
            "author": rng.choice(CHATTER_HANDLE_POOL),
            "engagement_score": round(rng.uniform(0.0, 1.0), 3),
        })
    return tuple(items)


# --- scenario assembly ----------------------------------------------------------


def _skew_renders_clean(skew: Skew, config: MissionConfig, index: int, spot: float, r: float,
                        q: float, borrow_fee: float | None) -> bool:
    """Whether a candidate skew, rendered into a full trial world, scans
    clean - scan_chain on every expiry AND scan_calendar across them.

    Shape-based exclusion stopped being enough the day the answer key
    learned ARB-012 (§56): 'localized_distortion' was the one shape known to
    violate same-expiry bounds (§45's first finding), but a steep term-
    structure skew can genuinely violate CALENDAR bounds - the generator
    prices each expiry's IV independently and nothing ever constrained the
    cross-expiry surface. Same class of finding one level up, closed the
    same way as everything since §46: verify with the organization's own
    scans, not with a hand-enumerated list of dangerous shapes.

    The trial rows use their own derived rng (sizes only - sizes never move
    an edge), so probing a candidate skew consumes nothing from the main
    per-scenario stream and determinism is untouched."""
    trial_rng = random.Random(f"{config.seed}:scenario:{index}:clean-trial")
    trial_underlying = _build_underlying_quote(trial_rng, spot, config.spread_pct, config.base_time)
    trial_rows = _build_rows(trial_rng, spot, r, q, skew, config.spread_pct, config.base_time)
    chains = _trial_chains(trial_rows, trial_underlying, r, q, spot, borrow_fee, config.base_time)
    for chain in chains:
        if scan_chain(chain, _INJECTION_COSTS):
            return False
    return not scan_calendar(chains, _INJECTION_COSTS)


def _build_scenario(
    config: MissionConfig, focus_assets: list[dict], index: int, forced_asset: dict | None = None,
) -> ScenarioWorld:
    scenario_id = f"{config.mission_id}-s{index}"
    rng = random.Random(f"{config.seed}:scenario:{index}")

    # The choice draw always runs, even when forced_asset overrides it, so the
    # seeded stream behind every later draw (variant, carry, skew) is identical
    # whether or not a caller forced the security - one world per (seed, index),
    # differing only in whose name it happened under.
    drawn = rng.choice(focus_assets)
    asset = forced_asset if forced_asset is not None else drawn
    entity_id, symbol = asset["entity_id"], asset["primary_identifier"]
    spot = _spot_for_symbol(config.seed, symbol)

    variant = _draw_variant(rng, config.scenario_mix)
    r = rng.uniform(*config.r_range)
    q = rng.uniform(*config.q_range)
    if variant == VARIANT_CARRY_EFFECT:
        # Forced toward the top of the range, not drawn - the point of this
        # trap is a large naive |C - P - (S - K)| gap despite true parity
        # holding, and that needs q pinned high, not merely likely to be.
        q = config.q_range[1]
    borrow_fee = rng.uniform(*config.borrow_fee_range)
    skew = draw_skew(rng)
    if variant == VARIANT_NONE or variant in TRAP_VARIANTS or variant == VARIANT_CALENDAR_BUMP:
        # SS45's first finding: 'localized_distortion' is not itself an
        # injection, but its isolated IV mountain genuinely violates
        # cross-strike bounds around the bumped cell regardless of what (if
        # anything) a variant injects elsewhere - tests/test_arbitrage_phase1.py
        # already characterizes this as the world generator's own property,
        # not a detector bug. A clean-world variant (every trap, and 'none')
        # promises "no opportunity" in its own ground truth; drawing that one
        # shape would make the promise a lie, not an honest world failure to
        # be graded - so a clean variant redraws from its own salted,
        # deterministic stream until it lands on a different shape, keeping
        # full diversity minus that one shape. The main rng stream is
        # untouched (this loop reads only from clean_rng, never rng), so
        # every OTHER draw this scenario makes is bit-for-bit unaffected by
        # whether this branch fires, and every genuine/cross-strike
        # scenario's own skew keeps drawing 'localized_distortion' exactly
        # as before - richness helps there, where ground truth already
        # expects a real opportunity.
        #
        # The genuine calendar bump (§56) joins the redraw even though it is
        # not a clean-world variant: its 'calendar' family grades ANY
        # same-expiry detection as world drift ('unexpected_same_expiry_hit'),
        # a stronger promise than the cross family's primary-strike matching
        # can absorb - a distortion's pre-existing cross-strike violation
        # would poison the grade with a failure the lift never caused. Same
        # instrument (skew diversity minus one shape), same reason (ground
        # truth must not promise what the drawn world contradicts).
        clean_rng = random.Random(f"{config.seed}:scenario:{index}:clean-skew")
        # Two rejection criteria: the shape §45 identified (kept explicit, so
        # the guarantee does not silently rest on the property check alone),
        # and the rendered-world property itself (§56 - see
        # _skew_renders_clean for why shapes stopped being enough). Bounded:
        # most draws pass on the first try, and a failure to find any clean
        # skew in 200 draws would mean the generator itself has drifted.
        for _ in range(200):
            if skew.shape != "localized_distortion" and _skew_renders_clean(
                skew, config, index, spot, r, q, borrow_fee,
            ):
                break
            skew = draw_skew(clean_rng)
        else:  # pragma: no cover - safety valve, not expected to trigger
            raise RuntimeError(
                f"no clean skew found in 200 draws for scenario index {index} "
                f"(seed {config.seed}) - the skew generator has drifted"
            )

    underlying = _build_underlying_quote(rng, spot, config.spread_pct, config.base_time)
    rows = _build_rows(rng, spot, r, q, skew, config.spread_pct, config.base_time)

    affected_strike = affected_expiry_days = injected_deviation = None
    affected_strikes = None
    expected_executable = False
    expected_direction = None
    expected_family = None

    if variant == VARIANT_GENUINE:
        idx = rng.randrange(len(rows))
        rows, injected_deviation = _inject_genuine(rng, rows, idx, spot, r, q, underlying, config)
        affected_strike, affected_expiry_days = rows[idx].strike, rows[idx].expiry_days
        expected_executable, expected_direction = True, "conversion"
    elif variant == VARIANT_SPREAD_ARTIFACT:
        idx = rng.randrange(len(rows))
        rows, injected_deviation = _inject_spread_artifact(rng, rows, idx, spot, r, q, underlying, borrow_fee, config)
        affected_strike, affected_expiry_days = rows[idx].strike, rows[idx].expiry_days
    elif variant == VARIANT_CARRY_EFFECT:
        idx = _locate_row(rows, expiry_days=60, moneyness=0.00)
        affected_strike, affected_expiry_days = rows[idx].strike, rows[idx].expiry_days
    elif variant == VARIANT_BORROW_COST:
        idx = rng.randrange(len(rows))
        rows, injected_deviation, borrow_fee = _inject_borrow_cost(rng, rows, idx, spot, r, q, underlying, config)
        affected_strike, affected_expiry_days = rows[idx].strike, rows[idx].expiry_days
    elif variant == VARIANT_STALE_QUOTE:
        idx = rng.randrange(len(rows))
        rows, injected_deviation = _inject_stale_quote(rng, rows, idx, spot, r, q, underlying, config)
        affected_strike, affected_expiry_days = rows[idx].strike, rows[idx].expiry_days
    elif variant == VARIANT_CROSS_BUMP:
        idx_prev, idx_mid = _cross_strike_indices(rows)
        rows, injected_deviation = _inject_cross_bump(rng, rows, idx_prev, idx_mid, config)
        affected_strike, affected_expiry_days = rows[idx_mid].strike, 30
        affected_strikes = [rows[idx_prev].strike, rows[idx_mid].strike]
        expected_executable = True
        expected_family = "cross_strike"
    elif variant == VARIANT_CROSS_DIP:
        idx_prev, idx_mid = _cross_strike_indices(rows)
        rows, injected_deviation, actual_variant = _inject_cross_dip(rng, rows, idx_prev, idx_mid, config)
        affected_strike, affected_expiry_days = rows[idx_mid].strike, 30
        affected_strikes = [rows[idx_prev].strike, rows[idx_mid].strike]
        expected_executable = True
        expected_family = "cross_strike"
        # The clip-fallback may have actually planted a bump - ground truth
        # records what was ACTUALLY applied, not what was drawn (module note
        # above _inject_cross_dip).
        variant = actual_variant
    elif variant == VARIANT_CROSS_SPREAD_ARTIFACT:
        idx_prev, idx_mid = _cross_strike_indices(rows)
        rows, injected_deviation = _inject_cross_spread_artifact(
            rng, rows, idx_prev, idx_mid, r, q, spot, underlying, borrow_fee, config,
        )
        affected_strike, affected_expiry_days = rows[idx_mid].strike, 30
        affected_strikes = [rows[idx_prev].strike, rows[idx_mid].strike]
    elif variant == VARIANT_CALENDAR_BUMP:
        rows, injected_deviation = _inject_calendar_bump(
            rng, rows, spot, r, q, underlying, borrow_fee, config,
        )
        # The whole near ladder is lifted, so there is no single affected
        # strike - the affected *expiry* is the identity the evaluator keys
        # on. affected_strike deliberately stays None rather than electing
        # an arbitrary strike a grader might then wrongly require.
        affected_expiry_days = EXPIRY_DAYS[0]
        expected_executable = True
        expected_family = "calendar"
    elif variant == VARIANT_CALENDAR_SPREAD_ARTIFACT:
        rows, injected_deviation = _inject_calendar_spread_artifact(
            rng, rows, spot, r, q, underlying, borrow_fee, config,
        )
        affected_expiry_days = EXPIRY_DAYS[0]
    # VARIANT_NONE: nothing injected.

    ground_truth = GroundTruth(
        scenario_id=scenario_id, entity_id=entity_id, symbol=symbol, variant=variant,
        affected_strike=affected_strike, affected_expiry_days=affected_expiry_days,
        injected_deviation=injected_deviation, expected_executable=expected_executable,
        expected_direction=expected_direction, skew_shape=skew.shape, skew_params=skew.params,
        r=r, q=q, borrow_fee_annual=borrow_fee,
        affected_strikes=affected_strikes, expected_family=expected_family,
    )
    chatter = _generate_chatter(rng, ground_truth, focus_assets, config)

    return ScenarioWorld(
        scenario_id=scenario_id, entity_id=entity_id, symbol=symbol, spot=spot,
        underlying=underlying, r=r, q=q, borrow_fee_annual=borrow_fee,
        rows=tuple(rows), ground_truth=ground_truth, chatter=chatter,
    )


# --- observation feeds (addendum 25 SS10/SS11) ----------------------------------


def build_option_chain_observation(scenario: ScenarioWorld, config: MissionConfig) -> Observation:
    """Explorer's feed: one Observation per scenario, data_class
    'option_chain'. The payload carries only market shape - no variant, no
    ground truth, no is-this-an-opportunity marker (module docstring)."""
    pv_div_by_expiry = [
        {"expiry_days": dte, "pv_div": pricing.pv_div(scenario.spot, scenario.q, dte / 365)}
        for dte in EXPIRY_DAYS
    ]
    chain = [
        {
            "strike": row.strike, "expiry_days": row.expiry_days, "iv": row.sigma,
            "call": {"bid": row.call.bid, "ask": row.call.ask, "bid_size": row.call.bid_size,
                     "ask_size": row.call.ask_size, "quoted_at": row.call.quoted_at},
            "put": {"bid": row.put.bid, "ask": row.put.ask, "bid_size": row.put.bid_size,
                    "ask_size": row.put.ask_size, "quoted_at": row.put.quoted_at},
        }
        for row in scenario.rows
    ]
    payload = {
        "symbol": scenario.symbol,
        "as_of": config.base_time,
        # Constant across the whole chain in this mission (module docstring:
        # ARB-001 only prices European style) - carried in the payload anyway
        # so providers/stored_data.py's StoredChainProvider can reconstruct a
        # full ParitySnapshot (backend/arbitrage.py) without hardcoding a
        # value the payload itself should be the source of truth for.
        "style": "european",
        "underlying": {
            "bid": scenario.underlying.bid, "ask": scenario.underlying.ask,
            "bid_size": scenario.underlying.bid_size, "ask_size": scenario.underlying.ask_size,
            "quoted_at": scenario.underlying.quoted_at,
        },
        "carry": {"r": scenario.r, "q": scenario.q, "borrow_fee_annual": scenario.borrow_fee_annual,
                  "pv_div_by_expiry": pv_div_by_expiry},
        "chain": chain,
    }
    return Observation(
        entity_id=scenario.entity_id, data_class="option_chain", observed_at=config.base_time,
        payload=payload,
        provenance=Provenance(
            origin="synthetic", source=f"parity_world(seed={config.seed})",
            run_id=config.mission_id, scenario_id=scenario.scenario_id,
        ),
    )


def build_chatter_observations(scenario: ScenarioWorld, config: MissionConfig) -> list[Observation]:
    """Speculator's feed, reusing the existing 'social_post' data class
    (module docstring)."""
    return [
        Observation(
            entity_id=item["entity_id"], data_class="social_post", observed_at=item["posted_at"],
            payload={
                "symbol": item["symbol"], "text": item["text"], "stance": item["stance"],
                "author": item["author"], "engagement_score": item["engagement_score"],
            },
            provenance=Provenance(
                origin="synthetic", source=f"parity_world(seed={config.seed})",
                run_id=config.mission_id, scenario_id=scenario.scenario_id,
            ),
        )
        for item in scenario.chatter
    ]


def observations(scenario: ScenarioWorld, config: MissionConfig) -> list[Observation]:
    """Both feeds for one scenario, Explorer's and Speculator's, as the
    canonical Observations addendum 20's contract requires everything
    downstream to consume."""
    return [build_option_chain_observation(scenario, config)] + build_chatter_observations(scenario, config)


# --- answer key and evaluation (addendum 25 SS15-SS18) ---------------------------


def _chain_snapshots_from_scenario(scenario: ScenarioWorld, config: MissionConfig) -> list[ChainSnapshot]:
    """One backend/arbitrage.py ChainSnapshot per expiry, built directly from
    the in-memory ScenarioWorld - the offline-answer-key counterpart to
    providers/stored_data.py's `chain_snapshots`, which does the same grouping
    from a stored Observation's payload. A small internal builder rather than
    a reuse of that one: this runs during scenario assembly, before anything
    is stored (or ever will be, for run_parity_exercise's own self-test)."""
    rows_by_expiry: dict[int, list[ChainRow]] = {}
    for row in scenario.rows:
        rows_by_expiry.setdefault(row.expiry_days, []).append(row)

    chains = []
    for expiry_days in sorted(rows_by_expiry):
        rows_sorted = sorted(rows_by_expiry[expiry_days], key=lambda r: r.strike)
        pv_div_value = pricing.pv_div(scenario.spot, scenario.q, expiry_days / 365)
        strikes = tuple(
            StrikeQuotes(strike=row.strike, call=row.call, put=row.put) for row in rows_sorted
        )
        chains.append(ChainSnapshot(
            entity_id=scenario.entity_id, symbol=scenario.symbol, expiry_days=expiry_days,
            style="european", as_of=config.base_time, underlying=scenario.underlying,
            r=scenario.r, pv_div=pv_div_value, borrow_fee_annual=scenario.borrow_fee_annual,
            strikes=strikes,
        ))
    return chains


def answer_key(scenario: ScenarioWorld, config: MissionConfig) -> list[Opportunity]:
    """scan_chain (backend/arbitrage.py) run over every expiry's ChainSnapshot
    - the organization's own chain-level entry point, the same one a real
    deployment (and agents/explorer.py's `_parity_work`) would run, not a
    parallel reimplementation that could drift from it. Supersedes the old
    per-row detect_arb001 loop now that Phase 1 covers more than parity
    (docs/SPEC_RECONCILIATION.md SS45): ARB-001 is still in here (scan_chain
    runs it per strike), alongside every cross-strike detector the same scan
    already knows how to run."""
    costs = CostConfig()
    opportunities: list[Opportunity] = []
    chains = _chain_snapshots_from_scenario(scenario, config)
    for chain in chains:
        opportunities.extend(scan_chain(chain, costs, stale_tolerance_seconds=config.stale_tolerance_seconds))
    # §56: the answer key grew scan_calendar the day ARB-012 did - the same
    # entry point Explorer's _parity_work runs, so world and organization
    # keep judging the same relations.
    opportunities.extend(scan_calendar(chains, costs, stale_tolerance_seconds=config.stale_tolerance_seconds))
    return opportunities


def _detection_record(o: Opportunity) -> dict:
    return {
        "detector_id": o.detector_id, "direction": o.direction,
        "net_edge_per_share": o.net_edge_per_share, "classification": o.classification,
        "strike": o.inputs.get("strike", o.inputs.get("k1")),
        "k2": o.inputs.get("k2"), "k3": o.inputs.get("k3"),
        "expiry_days": o.inputs.get("expiry_days"),
        # ARB-012's far leg (§56); None for every single-expiry package.
        "expiry2_days": o.inputs.get("expiry2_days"),
    }


def _detection_strikes(detection: dict) -> set:
    return {v for v in (detection["strike"], detection["k2"], detection["k3"]) if v is not None}


def evaluate(scenario: ScenarioWorld, opportunities: list[Opportunity]) -> dict:
    """Grade one scenario's answer-key output against its ground truth.

    Three families, by `gt.expected_family` ('calendar' documented at its
    own branch above the cross-strike one):

    - 'cross_strike' (the two genuine cross variants, SS45's deferred item):
      PASS needs >=1 non-ARB-001 opportunity whose strikes include the
      primary affected strike, ZERO ARB-001 opportunities anywhere (an
      ARB-001 hit on a same-strike parallel shift is a world-integrity
      alarm, not a second correct answer - module note above the injectors),
      and every opportunity's strikes must include the primary strike (a hit
      elsewhere is a stray the injector should not have produced). Violating
      any of those is FAIL('unexpected_parity_hit' / 'stray_detection'); no
      matching opportunity at all is FAIL('injection_missed').
    - Everything else (the original six parity variants, and the
      cross-strike trap): unchanged logic from before scan_chain replaced
      detect_arb001 as the answer key's engine - a genuine scenario needs its
      affected (strike, expiry)'s ARB-001 hit in the expected direction; a
      trap or 'none' scenario needs zero detections at all, of anything."""
    gt = scenario.ground_truth
    detections = [_detection_record(o) for o in opportunities]

    if gt.expected_family == "calendar":
        # §56: the whole-ladder lift preserves parity and every same-expiry
        # relation exactly, so ANY non-ARB-012 detection is the world
        # drifting from that invariance - graded as its own named failure,
        # not as a stray. A matching detection is an ARB-012 package whose
        # near leg sits at the lifted expiry; an ARB-012 through some other
        # expiry pair would be a stray the injector should not have
        # produced.
        arb001_hits = [d for d in detections if d["detector_id"] == "ARB-001"]
        same_expiry_hits = [d for d in detections if d["detector_id"] not in ("ARB-001", "ARB-012")]
        calendar_hits = [d for d in detections if d["detector_id"] == "ARB-012"]
        matching = [d for d in calendar_hits if d["expiry_days"] == gt.affected_expiry_days]
        stray = [d for d in calendar_hits if d["expiry_days"] != gt.affected_expiry_days]

        if arb001_hits:
            outcome, reasons = "FAIL", ["unexpected_parity_hit"]
        elif same_expiry_hits:
            outcome, reasons = "FAIL", ["unexpected_same_expiry_hit"]
        elif stray:
            outcome, reasons = "FAIL", ["stray_detection"]
        elif matching:
            outcome, reasons = "PASS", []
        else:
            outcome, reasons = "FAIL", ["injection_missed"]
        return {
            "scenario_id": scenario.scenario_id, "ground_truth": asdict(gt),
            "detections": detections, "outcome": outcome, "reasons": reasons,
        }

    if gt.expected_family == "cross_strike":
        arb001_hits = [d for d in detections if d["detector_id"] == "ARB-001"]
        primary = gt.affected_strike
        cross_hits = [d for d in detections if d["detector_id"] != "ARB-001"]
        matching = [d for d in cross_hits if primary in _detection_strikes(d)]
        stray = [d for d in cross_hits if primary not in _detection_strikes(d)]

        if arb001_hits:
            outcome, reasons = "FAIL", ["unexpected_parity_hit"]
        elif stray:
            outcome, reasons = "FAIL", ["stray_detection"]
        elif matching:
            outcome, reasons = "PASS", []
        else:
            outcome, reasons = "FAIL", ["injection_missed"]
        return {
            "scenario_id": scenario.scenario_id, "ground_truth": asdict(gt),
            "detections": detections, "outcome": outcome, "reasons": reasons,
        }

    if gt.variant == VARIANT_GENUINE:
        affected_detection = next(
            (d for d in detections if d["detector_id"] == "ARB-001"
             and d["strike"] == gt.affected_strike and d["expiry_days"] == gt.affected_expiry_days),
            None,
        )
        if affected_detection is None:
            outcome, reasons = "FAIL", ["injection_missed"]
        elif affected_detection["direction"] == gt.expected_direction:
            outcome, reasons = "PASS", []
        else:
            outcome, reasons = "PARTIAL", []
    else:
        if not detections:
            outcome, reasons = "PASS", []
        else:
            outcome = "FAIL"
            reasons = ["trap_leaked"] if gt.variant != VARIANT_NONE else ["false_positive"]

    return {
        "scenario_id": scenario.scenario_id,
        "ground_truth": asdict(gt),
        "detections": detections,
        "outcome": outcome,
        "reasons": reasons,
    }


def _runs_dir() -> Path:
    """Lazy import, the same reason simulation/stage1.py's run_exercise
    imports simulation.harness inside the function rather than at module
    scope: importing harness at import time here would risk a cycle with
    modules that import parity_world before harness has finished loading."""
    from simulation import harness
    return harness.RUNS_DIR


def _require_reference_ready(conn, mission_id: str) -> list[dict]:
    """The reference gate (module docstring, addendum 25 SS3): refuses
    outright rather than degrading. Shared by run_parity_exercise and
    store_world so both mission entry points fail closed identically - a
    world stored for the real agents deserves exactly the same refusal a
    world generated for the simulator's own answer key does."""
    if not reference_data.is_ready(conn):
        raise ReferenceNotReady(
            f"Market Data Simulation Engine refused mission {mission_id!r}: reference data is not "
            f"READY (state={WAITING_FOR_REFERENCE_DATA}). Call reference_data.run_reference_engine(conn) first."
        )
    focus_assets = reference_data.list_focus_assets(conn)
    if not focus_assets:
        raise ReferenceNotReady(
            f"Market Data Simulation Engine refused mission {mission_id!r}: reference data is READY "
            f"but no focus assets exist (state={WAITING_FOR_REFERENCE_DATA}). The engine never invents identity."
        )
    return focus_assets


def _write_summary(mission_id: str, payload: dict, runs_dir: Path | None) -> str:
    """Write `payload` to runs_dir/parity-<mission_id>-<timestamp>.json and
    return the path as a str. Shared by run_parity_exercise and store_world so
    both mission entry points write the same summary shape the same way.

    The one wall-clock read in this module (module docstring): it names the
    file, and is never folded into scenario content, so it does not break
    the reproducibility property."""
    out_dir = Path(runs_dir) if runs_dir is not None else _runs_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc)
    out_path = out_dir / f"parity-{mission_id}-{timestamp:%Y%m%dT%H%M%S}.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(out_path)


def store_world(conn, config: MissionConfig, runs_dir: Path | None = None) -> dict:
    """The mission runner's other entry point: build the world and store its
    Observations into the Data Store (backend/observations.py) for the real
    agents to consume, instead of running the simulator's own answer key.

    Explorer now runs ARB-001 itself over the stored option_chain
    observations (agents/explorer.py's `_parity_work`), and Speculator reads
    the stored social_post observations - the mission's own answer_key/
    evaluate() are what proved the world and detector agree during
    development (run_parity_exercise, above); they play no role here. What
    this function still owes the Evaluator is the ground-truth summary -
    per-scenario ground truth and the mission config, written the same way
    run_parity_exercise writes its own summary - so a later grading pass can
    join stored parity_events (backend/fi_db.py, keyed by run_id/scenario_id)
    back to the answer nothing an agent ever read.

    Same reference gate as run_parity_exercise (module docstring's fail-closed
    rule): a mission whose world could not legitimately be built stores
    nothing."""
    focus_assets = _require_reference_ready(conn, config.mission_id)
    # One security per scenario, without replacement. The Data Store's
    # idempotency key is (entity_id, data_class, observed_at, origin, source),
    # and every chain in a mission shares base_time and source - so two
    # scenarios drawn onto the same entity would collapse to one stored chain,
    # and the Evaluator would blame the agents for a miss the store caused.
    # Explorer reads only the latest chain per entity anyway, so distinct
    # securities is not a workaround, it is the only shape a stored mission
    # can honestly take.
    if config.n_scenarios > len(focus_assets):
        raise ValueError(
            f"store_world needs one distinct focus asset per scenario: {config.n_scenarios} "
            f"scenario(s) over {len(focus_assets)} focus asset(s). Lower n_scenarios or widen the focus."
        )
    assignment = random.Random(f"{config.seed}:assignment").sample(focus_assets, k=config.n_scenarios)
    scenarios = [
        _build_scenario(config, focus_assets, i, forced_asset=assignment[i])
        for i in range(config.n_scenarios)
    ]

    all_observations = []
    for scenario in scenarios:
        all_observations.extend(observations(scenario, config))
    store_report = observation_store.store_many(conn, all_observations)

    summary = {
        "mission_id": config.mission_id,
        "config": asdict(config),
        "scenarios": [
            {"scenario_id": scenario.scenario_id, "ground_truth": asdict(scenario.ground_truth)}
            for scenario in scenarios
        ],
    }
    summary_path = _write_summary(config.mission_id, summary, runs_dir)

    return {"stored": store_report, "scenarios": len(scenarios), "summary_path": summary_path}


def run_parity_exercise(conn, config: MissionConfig, runs_dir: Path | None = None) -> dict:
    """The mission's entry point: reference gate, generate, evaluate, write
    the summary (addendum 25 SS17's completion loop, minus the agent stages
    this increment does not wire up - Explorer/Speculator/Analyst consume
    `observations()` in a later increment; this one proves the world and its
    own answer key are correct)."""
    # WAITING_FOR_REFERENCE_DATA appears in the traversal only when the gate
    # actually blocked - a run whose reference data was ready never waited,
    # and a state list that said otherwise would be a record of something
    # that did not happen.
    states = [NOT_STARTED]
    focus_assets = _require_reference_ready(conn, config.mission_id)

    states += [CONFIGURING, GENERATING_MARKET, GENERATING_OPTIONS, GENERATING_SKEW, INJECTING_OPPORTUNITIES]
    scenarios = [_build_scenario(config, focus_assets, i) for i in range(config.n_scenarios)]
    states += [GENERATING_INFORMATION_NOISE, READY, EVALUATING]

    scenario_reports = []
    contracts_generated = chatter_items = 0
    for scenario in scenarios:
        opportunities = answer_key(scenario, config)
        scenario_reports.append(evaluate(scenario, opportunities))
        contracts_generated += len(scenario.rows)
        chatter_items += len(scenario.chatter)

    # "genuine" for strategy-coverage purposes (addendum 25 SS18) means any
    # variant the mix could produce a real, floored opportunity from - the
    # original single VARIANT_GENUINE plus the two cross-strike genuine
    # variants (SS45's deferred item) plus the calendar bump (§56), since a
    # strategy's own curriculum may never draw the classic parity genuine at
    # all and still deserves to certify COMPLETED once it exercises its own
    # material.
    def _is_genuine(variant: str) -> bool:
        return (variant == VARIANT_GENUINE or variant in CROSS_GENUINE_VARIANTS
                or variant == VARIANT_CALENDAR_BUMP)

    strategy_exercised = any(
        _is_genuine(report["ground_truth"]["variant"]) and report["outcome"] == "PASS"
        for report in scenario_reports
    )
    final_state = COMPLETED if strategy_exercised else RETRY_REQUIRED
    states.append(final_state)

    detected = sum(1 for r in scenario_reports if _is_genuine(r["ground_truth"]["variant"]) and r["outcome"] == "PASS")
    missed = sum(1 for r in scenario_reports if _is_genuine(r["ground_truth"]["variant"]) and r["outcome"] != "PASS")
    false_positives = sum(1 for r in scenario_reports if not _is_genuine(r["ground_truth"]["variant"]) and r["outcome"] == "FAIL")
    opportunities_injected = sum(1 for s in scenarios if s.ground_truth.variant != VARIANT_NONE)
    pass_count = sum(1 for r in scenario_reports if r["outcome"] == "PASS")

    metrics = {
        "assets_simulated": len({s.entity_id for s in scenarios}),
        "contracts_generated": contracts_generated,
        "opportunities_injected": opportunities_injected,
        "chatter_items": chatter_items,
        "detected": detected,
        "missed": missed,
        "false_positives": false_positives,
        "pass_rate": pass_count / len(scenario_reports) if scenario_reports else None,
        "strategy_exercised": strategy_exercised,
    }

    report = {
        "mission_id": config.mission_id,
        "config": asdict(config),
        "states": states,
        "scenarios": scenario_reports,
        "metrics": metrics,
    }
    report["summary_path"] = _write_summary(config.mission_id, report, runs_dir)
    return report
