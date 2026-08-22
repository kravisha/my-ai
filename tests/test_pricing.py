"""Unit tests for simulation/pricing.py - the stdlib-only Black-Scholes
kernel the parity world (simulation/parity_world.py) and the ARB-001
detector (backend/arbitrage.py) both build on."""

import itertools
import math

import pytest

from simulation import pricing

# A grid of plausible inputs, not exhaustive - enough to exercise ITM/OTM/ATM
# strikes, short and long expiries, and a spread of rates/dividends/vols.
SPOTS = (50.0, 100.0, 250.0)
STRIKES = (80.0, 100.0, 120.0)
T_YEARS = (7 / 365, 30 / 365, 1.0)
RATES = (0.01, 0.04)
DIVIDENDS = (0.0, 0.02)
SIGMAS = (0.15, 0.30, 0.60)


def test_put_call_parity_identity_holds_across_a_grid():
    for spot, strike, t, r, q, sigma in itertools.product(SPOTS, STRIKES, T_YEARS, RATES, DIVIDENDS, SIGMAS):
        call = pricing.bs_call(spot, strike, t, r, q, sigma)
        put = pricing.bs_put(spot, strike, t, r, q, sigma)
        parity_rhs = spot * math.exp(-q * t) - strike * math.exp(-r * t)
        assert call - put == pytest.approx(parity_rhs, abs=1e-9)


def test_intrinsic_value_at_expiry():
    assert pricing.bs_call(110.0, 100.0, 0.0, 0.03, 0.01, 0.25) == pytest.approx(10.0)
    assert pricing.bs_call(90.0, 100.0, 0.0, 0.03, 0.01, 0.25) == pytest.approx(0.0)
    assert pricing.bs_put(90.0, 100.0, 0.0, 0.03, 0.01, 0.25) == pytest.approx(10.0)
    assert pricing.bs_put(110.0, 100.0, 0.0, 0.03, 0.01, 0.25) == pytest.approx(0.0)
    # negative t_years is treated the same as expired
    assert pricing.bs_call(110.0, 100.0, -0.01, 0.03, 0.01, 0.25) == pytest.approx(10.0)


def test_call_price_decreases_in_strike():
    prices = [pricing.bs_call(100.0, k, 0.5, 0.03, 0.01, 0.25) for k in (80.0, 90.0, 100.0, 110.0, 120.0)]
    assert all(earlier > later for earlier, later in zip(prices, prices[1:]))


def test_put_price_increases_in_strike():
    prices = [pricing.bs_put(100.0, k, 0.5, 0.03, 0.01, 0.25) for k in (80.0, 90.0, 100.0, 110.0, 120.0)]
    assert all(earlier < later for earlier, later in zip(prices, prices[1:]))


def test_call_and_put_price_increase_in_sigma():
    call_prices = [pricing.bs_call(100.0, 100.0, 0.5, 0.03, 0.01, s) for s in (0.10, 0.20, 0.30, 0.50, 0.80)]
    put_prices = [pricing.bs_put(100.0, 100.0, 0.5, 0.03, 0.01, s) for s in (0.10, 0.20, 0.30, 0.50, 0.80)]
    assert all(earlier < later for earlier, later in zip(call_prices, call_prices[1:]))
    assert all(earlier < later for earlier, later in zip(put_prices, put_prices[1:]))


def test_discount_factor_and_pv_helpers():
    assert pricing.discount_factor(0.05, 1.0) == pytest.approx(math.exp(-0.05))
    assert pricing.discount_factor(0.05, 0.0) == pytest.approx(1.0)
    assert pricing.pv_strike(100.0, 0.05, 1.0) == pytest.approx(100.0 * math.exp(-0.05))
    assert pricing.pv_div(100.0, 0.02, 1.0) == pytest.approx(100.0 * (1 - math.exp(-0.02)))
    assert pricing.pv_div(100.0, 0.02, 0.0) == pytest.approx(0.0)


def test_norm_cdf_matches_known_values():
    assert pricing.norm_cdf(0.0) == pytest.approx(0.5)
    assert pricing.norm_cdf(-10.0) == pytest.approx(0.0, abs=1e-9)
    assert pricing.norm_cdf(10.0) == pytest.approx(1.0, abs=1e-9)
