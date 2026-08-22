"""Black-Scholes, continuous-dividend-yield form, stdlib only (no numpy/scipy -
this repo's math stays dependency-free by house rule).

This is the pricing kernel the Market Data Simulation Engine's parity world
(simulation/parity_world.py) uses to render option chains: call and put mid
prices computed from the *same* (spot, strike, T, r, q, sigma) inputs, so
European put-call parity holds by construction unless a scenario deliberately
perturbs one leg (addendum 25 SS9). It is also what backend/arbitrage.py's
ARB-001 detector uses on the pricing side of PVK/PVDiv - the two modules never
duplicate the discounting math.

## The continuous-dividend approximation, disclosed

Addendum 27's notation (SS"NOTATION") wants PVDiv as "PV of deterministic
[dated] distributions" and its critical-review list (SS9, item 4) explicitly
warns against ignoring discrete dividends. `pv_div` here uses the continuous
form `S*(1 - exp(-q*T))` instead - a disclosed convention standing in for
dated discrete cash flows, not a claim that discrete dividends do not matter.
Modeling an actual ex-dividend calendar is future work; this increment's
mission (put-call parity training data) does not yet need dated distributions
to teach the parity relationship, and a continuous yield keeps call/put
pricing and the detector's PVDiv term using one consistent formula.
"""

from __future__ import annotations

import math


def norm_cdf(x: float) -> float:
    """Standard normal CDF via math.erf - stdlib's own numerically stable
    implementation, no series expansion of our own to get subtly wrong."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def discount_factor(r: float, t_years: float) -> float:
    """DF = exp(-r*T), continuous compounding - the convention this entire
    pricing/detector pair uses throughout (addendum 27 NOTATION: "DF discount
    factor")."""
    return math.exp(-r * t_years)


def pv_strike(strike: float, r: float, t_years: float) -> float:
    """PVK = K*DF (addendum 27 NOTATION)."""
    return strike * discount_factor(r, t_years)


def pv_div(spot: float, q: float, t_years: float) -> float:
    """PV of dividends given up over [0, T] under a continuous yield q: the
    spot less what it would be worth ex-dividend at T under that yield.

    A convention standing in for dated discrete cash flows - see the module
    docstring. `spot * (1 - exp(-q*T))` is the continuous-yield approximation
    of PVDiv, not a measurement of any specific issuer's dividend schedule."""
    return spot * (1.0 - math.exp(-q * t_years))


def _d1_d2(spot: float, strike: float, t_years: float, r: float, q: float, sigma: float) -> tuple[float, float]:
    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r - q + 0.5 * sigma * sigma) * t_years) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    return d1, d2


def bs_call(spot: float, strike: float, t_years: float, r: float, q: float, sigma: float) -> float:
    """European call, continuous dividend yield q.

    t_years <= 0 returns intrinsic value rather than evaluating d1/d2 (which
    divide by sqrt(t_years) and would raise or blow up at expiry) - an expired
    or already-settled option has no time value left to price."""
    if t_years <= 0:
        return max(spot - strike, 0.0)
    d1, d2 = _d1_d2(spot, strike, t_years, r, q, sigma)
    return spot * math.exp(-q * t_years) * norm_cdf(d1) - strike * math.exp(-r * t_years) * norm_cdf(d2)


def bs_put(spot: float, strike: float, t_years: float, r: float, q: float, sigma: float) -> float:
    """European put, continuous dividend yield q. See bs_call for the
    t_years <= 0 intrinsic-value handling."""
    if t_years <= 0:
        return max(strike - spot, 0.0)
    d1, d2 = _d1_d2(spot, strike, t_years, r, q, sigma)
    return strike * math.exp(-r * t_years) * norm_cdf(-d2) - spot * math.exp(-q * t_years) * norm_cdf(-d1)
