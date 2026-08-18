"""MarketDataProvider interface (addendum_10 §3) + one synthetic
implementation (addendum_10 §5: "Explorer consumes generated option
surfaces first through the provider interface" - a real HistoricalOptions/
live provider is explicitly later, Phase E).

A surface is a grid over (strike moneyness, expiry days). The synthetic
provider builds a smooth base surface (mild skew + term structure + small
seeded noise) and, optionally, one sharp Gaussian-falloff bump at a chosen
grid cell - the "mountain rising from a surrounding plain" mental model in
addendum_7 §4. The bump is targeted per security (via `anomalies`), so a
caller can force a dislocation onto specific securities in a peer group
while leaving the rest flat - what makes both peer-analysis scenarios
(addendum_7 §5: co-movement vs. an isolated anomaly) constructable without
any extra machinery. No numpy/scipy dependency: a handful of grid points
with plain arithmetic doesn't need it, and requirements.txt has neither.

A surface is generated once per security and cached - deterministic and
static across repeated calls with the same provider instance. This is
deliberate (see agents/explorer.py's dedup guard / the project plan's
decision 5): the surface represents "the market as it currently is", not a
live-advancing stream, so a real detected dislocation stays detectable
across repeated scans until something (Analysis, or a future respawn with a
new seed) changes it - unlike providers/social_data.py's stream, which
genuinely advances each call.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Protocol

STRIKES = (-0.20, -0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15, 0.20)
EXPIRIES_DAYS = (7, 14, 30, 60, 90)

# Defaults describing one market regime. base_level and noise_amplitude are
# overridable per provider instance (see `regime` below) because a market that
# cannot change conditions makes regime detection untestable - and a detector
# for a phenomenon that cannot occur is worse than no detector.
BASE_LEVEL = 0.25
SKEW_COEF = 0.15
TERM_COEF = 0.01
NOISE_AMPLITUDE = 0.01

DEFAULT_ANOMALY_HEIGHT = 0.40
DEFAULT_ANOMALY_WIDTH = 0.5  # in grid-index units - small on purpose, so the
# bump decays sharply and the surrounding plain stays genuinely flat just a
# cell or two away (see module docstring).


@dataclass(frozen=True)
class SurfacePoint:
    strike: float  # moneyness, e.g. -0.20..0.20
    expiry_days: int
    iv: float


@dataclass(frozen=True)
class OptionSurface:
    security: str
    points: tuple[SurfacePoint, ...]


class MarketDataProvider(Protocol):
    def get_option_surface(self, security: str, as_of: str | None = None) -> OptionSurface: ...


class SyntheticMarketDataProvider:
    def __init__(self, seed: int, anomalies: dict[str, dict] | None = None, regime: dict | None = None):
        """anomalies: maps security -> per-security bump config overrides
        (strike_idx/expiry_idx/height/width, each optional - see _generate's
        defaults). Only securities present in this dict get a forced bump;
        everything else stays flat/natural. An empty dict value ({}) bumps
        that security at the default center cell with default height/width -
        two securities both given {} bump at the *same* grid cell, which is
        a genuine "same shape/spike" co-movement fixture, not two unrelated
        anomalies that happen to coexist.

        regime: optional {"base_level": float, "noise_amplitude": float}
        describing the market conditions this provider generates under. This
        is *ground truth* the provider generates from - the system never sees
        it, and instead infers a characterization from the surfaces it
        observes (see agents/explorer.py and fi_db.market_regime). Keeping
        those separate is the point: the system estimates conditions, it is
        not told them.

        A regime change means a new provider instance; the per-security cache
        deliberately stays, since a surface still represents "the market as it
        currently is" within one regime."""
        self._seed = seed
        self._anomalies = anomalies or {}
        regime = regime or {}
        self._base_level = regime.get("base_level", BASE_LEVEL)
        self._noise_amplitude = regime.get("noise_amplitude", NOISE_AMPLITUDE)
        self._cache: dict[str, OptionSurface] = {}

    def get_option_surface(self, security: str, as_of: str | None = None) -> OptionSurface:
        """as_of is accepted for interface-compatibility with a future
        historical/live provider (addendum_8 §7's replay clock) but unused
        here - this synthetic provider has no time-series variation yet."""
        if security not in self._cache:
            self._cache[security] = self._generate(security)
        return self._cache[security]

    def observe(self, security: str, entity_id: str, observed_at: str, run_id: str | None = None,
                scenario_id: str | None = None):
        """The same surface, in the canonical contract (addendum 20 §3).

        A second method rather than a replacement for `get_option_surface`:
        Explorer and Speculator consume the surface object directly and rewriting
        them is a separate change with its own verification. What this proves is
        that the contract has a real producer - a contract nothing emits is a
        proposal, not a foundation.

        `entity_id` is passed in rather than looked up here, because a provider
        has no business owning identity resolution: it knows what it generated,
        not what the organization calls it. `backend/identifiers.py` owns that,
        and a historical provider will need the resolution done *as of the
        observation's own date* rather than as of now.

        Origin is fixed at 'synthetic' and cannot be overridden. That is §15
        structurally rather than by convention: this provider makes data up, and
        there is no argument that would make its output historical."""
        from backend.canonical import Observation, Provenance

        surface = self.get_option_surface(security, as_of=observed_at)
        return Observation(
            entity_id=entity_id,
            data_class="option_surface",
            observed_at=observed_at,
            payload={
                "security": surface.security,
                "points": [
                    {"strike": point.strike, "expiry_days": point.expiry_days, "iv": point.iv}
                    for point in surface.points
                ],
            },
            provenance=Provenance(
                origin="synthetic",
                source=f"SyntheticMarketDataProvider(seed={self._seed})",
                run_id=run_id,
                scenario_id=scenario_id,
            ),
        )

    def _generate(self, security: str) -> OptionSurface:
        rng = random.Random(f"{self._seed}:{security}")
        anomaly_config = self._anomalies.get(security)
        anomaly_strike_idx = (anomaly_config or {}).get("strike_idx", len(STRIKES) // 2)
        anomaly_expiry_idx = (anomaly_config or {}).get("expiry_idx", len(EXPIRIES_DAYS) // 2)
        height = (anomaly_config or {}).get("height", DEFAULT_ANOMALY_HEIGHT)
        width = (anomaly_config or {}).get("width", DEFAULT_ANOMALY_WIDTH)

        points = []
        for strike_idx, strike in enumerate(STRIKES):
            for expiry_idx, expiry_days in enumerate(EXPIRIES_DAYS):
                skew = SKEW_COEF * (strike ** 2)
                term = TERM_COEF * math.log(expiry_days)
                noise = rng.uniform(-self._noise_amplitude, self._noise_amplitude)
                iv = self._base_level + skew + term + noise
                if anomaly_config is not None:
                    dist_sq = (strike_idx - anomaly_strike_idx) ** 2 + (expiry_idx - anomaly_expiry_idx) ** 2
                    iv += height * math.exp(-dist_sq / (2 * width ** 2))
                points.append(SurfacePoint(strike=strike, expiry_days=expiry_days, iv=iv))
        return OptionSurface(security=security, points=tuple(points))
