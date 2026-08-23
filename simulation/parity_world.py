"""The Market Data Simulation Engine, Version 1 mission: put-call parity
arbitrage training worlds (addendum 25; docs/SPEC_RECONCILIATION.md SS39/SS41).

**An engine, not an agent** - same precedent as backend/reference_data.py
(addendum 24 SS1, SPEC_RECONCILIATION SS40): pure functions over a database
connection, invoked from orchestration, no charter, no watcher.

## What this mission actually generates

For each scenario: draw one canonical security from the Reference Data
Engine's focus universe (never invented - addendum 25 SS3), price a full
listed option chain on it with simulation/pricing.py's Black-Scholes kernel
so European put-call parity holds by construction, then - for five of six
scenario variants - deliberately perturb exactly one (strike, expiry) pair
into either a genuine executable arbitrage or one of four traps that *look*
like one at mid prices but are not (addendum 27's non-negotiable rule, lived
out as training data rather than only stated as a rule). The sixth variant,
'none', injects nothing - false-positive material, the same role Stage 1's
zero-plant worlds play (simulation/stage1.py).

The simulator's own answer key is backend/arbitrage.py's detect_arb001 run
over every (strike, expiry) pair - the organization's own detector, not a
reimplementation that could quietly drift from it (the same reasoning
stage1._answer_key gives for reusing scan_for_anomaly rather than
reinventing it).

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
from backend.arbitrage import CostConfig, NoOpportunity, Opportunity, ParitySnapshot, Quote, detect_arb001
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
# system"). Exactly one member today.
STRATEGIES = ("put_call_parity_arbitrage",)

# A convention, not a measurement: an arbitrary fixed Monday afternoon inside
# a nominal equity session. Every timestamp a run produces derives from this
# (config.base_time), never from datetime.now() - the addendum 25 SS20
# reproducibility rule made literal. Callers needing a different clock supply
# their own base_time; this is only the shipped default.
BASE_TIME_DEFAULT = "2026-01-05T14:30:00+00:00"

# The six scenario variants addendum 25 SS9/SS21 asks for: one genuine
# executable opportunity, four traps that look like one at mid prices but
# are not, and a clean no-injection control.
VARIANT_GENUINE = "genuine"
VARIANT_SPREAD_ARTIFACT = "spread_artifact"
VARIANT_CARRY_EFFECT = "carry_effect"
VARIANT_BORROW_COST = "borrow_cost"
VARIANT_STALE_QUOTE = "stale_quote"
VARIANT_NONE = "none"
VARIANTS = (
    VARIANT_GENUINE, VARIANT_SPREAD_ARTIFACT, VARIANT_CARRY_EFFECT,
    VARIANT_BORROW_COST, VARIANT_STALE_QUOTE, VARIANT_NONE,
)
TRAP_VARIANTS = (VARIANT_SPREAD_ARTIFACT, VARIANT_CARRY_EFFECT, VARIANT_BORROW_COST, VARIANT_STALE_QUOTE)

# Equal weight per variant - a convention (scenario diversity, addendum 25
# SS21), not a measured training-curriculum split. A caller wanting a
# genuine-only or trap-only run overrides scenario_mix directly (the property
# tests below do exactly that).
DEFAULT_SCENARIO_MIX = {variant: 1.0 for variant in VARIANTS}

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
    scenario_mix: dict = field(default_factory=lambda: dict(DEFAULT_SCENARIO_MIX))
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
                             underlying: Quote, config: MissionConfig) -> tuple[list[ChainRow], float]:
    """Same mid-shift mechanism as genuine, but the spread is then widened
    (both legs, to a shared half-spread) until the executable edge is <= 0 -
    a visible mid-price gap the spread itself erases, addendum 27's
    non-negotiable rule made concrete."""
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
    so the trap here is a real, if punitive, borrow rate, not a hidden one."""
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
    new_row = replace(row, call=new_call, put=new_put)
    rows = list(rows)
    rows[idx] = new_row

    pvk = row.strike * math.exp(-r * t_years)
    pre_borrow_net_after = -new_call.ask + new_put.bid + underlying.bid - pv_div_value - pvk - _INJECTION_COSTS.total_per_share
    required_borrow = pre_borrow_net_after / (underlying.bid * t_years)
    override_borrow_fee = required_borrow + 0.01  # enough surplus to make the post-borrow edge strictly negative

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

    underlying = _build_underlying_quote(rng, spot, config.spread_pct, config.base_time)
    rows = _build_rows(rng, spot, r, q, skew, config.spread_pct, config.base_time)

    affected_strike = affected_expiry_days = injected_deviation = None
    expected_executable = False
    expected_direction = None

    if variant == VARIANT_GENUINE:
        idx = rng.randrange(len(rows))
        rows, injected_deviation = _inject_genuine(rng, rows, idx, spot, r, q, underlying, config)
        affected_strike, affected_expiry_days = rows[idx].strike, rows[idx].expiry_days
        expected_executable, expected_direction = True, "conversion"
    elif variant == VARIANT_SPREAD_ARTIFACT:
        idx = rng.randrange(len(rows))
        rows, injected_deviation = _inject_spread_artifact(rng, rows, idx, spot, r, q, underlying, config)
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
    # VARIANT_NONE: nothing injected.

    ground_truth = GroundTruth(
        scenario_id=scenario_id, entity_id=entity_id, symbol=symbol, variant=variant,
        affected_strike=affected_strike, affected_expiry_days=affected_expiry_days,
        injected_deviation=injected_deviation, expected_executable=expected_executable,
        expected_direction=expected_direction, skew_shape=skew.shape, skew_params=skew.params,
        r=r, q=q, borrow_fee_annual=borrow_fee,
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


def _snapshot_for_row(scenario: ScenarioWorld, row: ChainRow, config: MissionConfig) -> ParitySnapshot:
    pv_div_value = pricing.pv_div(scenario.spot, scenario.q, row.expiry_days / 365)
    return ParitySnapshot(
        entity_id=scenario.entity_id, symbol=scenario.symbol, strike=row.strike, expiry_days=row.expiry_days,
        style="european", as_of=config.base_time, underlying=scenario.underlying, call=row.call, put=row.put,
        r=scenario.r, pv_div=pv_div_value, borrow_fee_annual=scenario.borrow_fee_annual,
    )


def answer_key(scenario: ScenarioWorld, config: MissionConfig) -> list[Opportunity | NoOpportunity]:
    """detect_arb001 run over every (strike, expiry) pair in the chain - the
    organization's own detector, the same one a real deployment would run,
    not a parallel reimplementation that could drift from it."""
    costs = CostConfig()
    return [
        detect_arb001(_snapshot_for_row(scenario, row, config), costs, stale_tolerance_seconds=config.stale_tolerance_seconds)
        for row in scenario.rows
    ]


def evaluate(scenario: ScenarioWorld, results: list[Opportunity | NoOpportunity]) -> dict:
    gt = scenario.ground_truth
    detections = [
        {"strike": row.strike, "expiry_days": row.expiry_days, "direction": result.direction,
         "net_edge_per_share": result.net_edge_per_share, "classification": result.classification}
        for row, result in zip(scenario.rows, results) if isinstance(result, Opportunity)
    ]

    affected_result = None
    if gt.affected_strike is not None:
        for row, result in zip(scenario.rows, results):
            if row.strike == gt.affected_strike and row.expiry_days == gt.affected_expiry_days:
                affected_result = result
                break
    reasons = list(affected_result.reason_codes) if isinstance(affected_result, NoOpportunity) else []

    if gt.variant == VARIANT_GENUINE:
        affected_detection = next(
            (d for d in detections if d["strike"] == gt.affected_strike and d["expiry_days"] == gt.affected_expiry_days),
            None,
        )
        if affected_detection is None:
            outcome = "FAIL"
            reasons = reasons or ["injection_missed"]
        elif affected_detection["direction"] == gt.expected_direction:
            outcome = "PASS"
        else:
            outcome = "PARTIAL"
    else:
        if not detections:
            outcome = "PASS"
        else:
            outcome = "FAIL"
            reasons = reasons or (["trap_leaked"] if gt.variant != VARIANT_NONE else ["false_positive"])

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
        results = answer_key(scenario, config)
        scenario_reports.append(evaluate(scenario, results))
        contracts_generated += len(scenario.rows)
        chatter_items += len(scenario.chatter)

    strategy_exercised = any(
        report["ground_truth"]["variant"] == VARIANT_GENUINE and report["outcome"] == "PASS"
        for report in scenario_reports
    )
    final_state = COMPLETED if strategy_exercised else RETRY_REQUIRED
    states.append(final_state)

    detected = sum(1 for r in scenario_reports if r["ground_truth"]["variant"] == VARIANT_GENUINE and r["outcome"] == "PASS")
    missed = sum(1 for r in scenario_reports if r["ground_truth"]["variant"] == VARIANT_GENUINE and r["outcome"] != "PASS")
    false_positives = sum(1 for r in scenario_reports if r["ground_truth"]["variant"] != VARIANT_GENUINE and r["outcome"] == "FAIL")
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
