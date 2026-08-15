"""MarketDataProvider interface (addendum_10 §3) + one synthetic
implementation (addendum_10 §5: "Explorer consumes generated option
surfaces first through the provider interface" - a real HistoricalOptions/
live provider is explicitly later, Phase E).

A surface is a grid over (strike moneyness, expiry days). The synthetic
provider builds a smooth base surface (mild skew + term structure + small
seeded noise) and, optionally, one sharp Gaussian-falloff bump at a chosen
grid cell - the "mountain rising from a surrounding plain" mental model in
addendum_7 §4. No numpy/scipy dependency: a handful of grid points with
plain arithmetic doesn't need it, and requirements.txt has neither.

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
    def __init__(self, seed: int, force_anomaly: bool = False, anomaly_config: dict | None = None):
        self._seed = seed
        self._force_anomaly = force_anomaly
        self._anomaly_config = anomaly_config or {}
        self._cache: dict[str, OptionSurface] = {}

    def get_option_surface(self, security: str, as_of: str | None = None) -> OptionSurface:
        """as_of is accepted for interface-compatibility with a future
        historical/live provider (addendum_8 §7's replay clock) but unused
        here - this synthetic provider has no time-series variation yet."""
        if security not in self._cache:
            self._cache[security] = self._generate(security)
        return self._cache[security]

    def _generate(self, security: str) -> OptionSurface:
        rng = random.Random(f"{self._seed}:{security}")
        anomaly_strike_idx = self._anomaly_config.get("strike_idx", len(STRIKES) // 2)
        anomaly_expiry_idx = self._anomaly_config.get("expiry_idx", len(EXPIRIES_DAYS) // 2)
        height = self._anomaly_config.get("height", DEFAULT_ANOMALY_HEIGHT)
        width = self._anomaly_config.get("width", DEFAULT_ANOMALY_WIDTH)

        points = []
        for strike_idx, strike in enumerate(STRIKES):
            for expiry_idx, expiry_days in enumerate(EXPIRIES_DAYS):
                skew = SKEW_COEF * (strike ** 2)
                term = TERM_COEF * math.log(expiry_days)
                noise = rng.uniform(-NOISE_AMPLITUDE, NOISE_AMPLITUDE)
                iv = BASE_LEVEL + skew + term + noise
                if self._force_anomaly:
                    dist_sq = (strike_idx - anomaly_strike_idx) ** 2 + (expiry_idx - anomaly_expiry_idx) ** 2
                    iv += height * math.exp(-dist_sq / (2 * width ** 2))
                points.append(SurfacePoint(strike=strike, expiry_days=expiry_days, iv=iv))
        return OptionSurface(security=security, points=tuple(points))
