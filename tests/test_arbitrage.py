"""Unit tests for backend/arbitrage.py's ARB-001 detector - mirrors addendum
27 SS7's unit list: exact parity is silent, adverse bid/ask cannot improve
edge, added cost cannot improve edge, hard stops are named, borrow is never
guessed at zero, capacity is the min-across-legs with multiplier
normalization."""

import math
from dataclasses import replace

import pytest

from backend.arbitrage import CostConfig, NoOpportunity, Opportunity, ParitySnapshot, Quote, detect_arb001

AS_OF = "2026-01-05T14:30:00+00:00"
STALE_AS_OF = "2026-01-05T14:30:00+00:00"


def _quote(bid, ask, bid_size=100, ask_size=100, quoted_at=AS_OF):
    return Quote(bid=bid, ask=ask, bid_size=bid_size, ask_size=ask_size, quoted_at=quoted_at)


def _shift(quote, delta):
    """Move a whole quote's mid by delta, keeping its spread - what a real
    price move looks like, as opposed to independently editing one side
    into a crossed market."""
    return replace(quote, bid=quote.bid + delta, ask=quote.ask + delta)


def _exact_parity_snapshot(spread=0.02, r=0.03, q=0.01, strike=100.0, expiry_days=30, borrow_fee=0.01):
    """A snapshot built so C - P = S - PVDiv - PVK exactly at mid, with a
    symmetric spread on every leg - the arbitrage-free control case."""
    spot_mid = 100.0
    t_years = expiry_days / 365
    pvk = strike * math.exp(-r * t_years)
    pv_div = spot_mid * (1 - math.exp(-q * t_years))
    call_mid = 8.0
    put_mid = call_mid - (spot_mid - pv_div - pvk)  # forces exact parity at mid

    half = spread / 2
    return ParitySnapshot(
        entity_id="ENT-1", symbol="SYN1", strike=strike, expiry_days=expiry_days, style="european",
        as_of=AS_OF,
        underlying=_quote(spot_mid - half, spot_mid + half),
        call=_quote(call_mid - half, call_mid + half),
        put=_quote(put_mid - half, put_mid + half),
        r=r, pv_div=pv_div, borrow_fee_annual=borrow_fee,
    )


def test_exact_parity_chain_yields_no_opportunity():
    snapshot = _exact_parity_snapshot()
    result = detect_arb001(snapshot, CostConfig())
    assert isinstance(result, NoOpportunity)
    assert "no_edge" in result.reason_codes


def test_injected_conversion_violation_clears_costs():
    snapshot = _exact_parity_snapshot()
    # Rich call: shift the whole call quote up well past parity + costs.
    snapshot = replace(snapshot, call=_shift(snapshot.call, 5.0))
    result = detect_arb001(snapshot, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.direction == "conversion"
    assert result.classification == "A"
    assert result.net_edge_per_share > 0


def test_injected_reversal_violation_clears_costs():
    snapshot = _exact_parity_snapshot()
    # Cheap call / rich put: shift the put quote up and the call quote down.
    snapshot = replace(snapshot, put=_shift(snapshot.put, 5.0), call=_shift(snapshot.call, -5.0))
    result = detect_arb001(snapshot, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.direction == "reversal"
    assert result.classification == "B"
    assert result.net_edge_per_share > 0


def test_widening_any_leg_spread_never_increases_net_edge():
    for widen_leg in ("underlying", "call", "put"):
        for seed_spread in (0.01, 0.05, 0.20):
            base = _exact_parity_snapshot(spread=seed_spread)
            base = replace(base, call=_shift(base.call, 3.0))
            base_result = detect_arb001(base, CostConfig())
            base_edge = base_result.net_edge_per_share if isinstance(base_result, Opportunity) else None

            leg = getattr(base, widen_leg)
            wider = replace(leg, bid=leg.bid - 0.10, ask=leg.ask + 0.10)
            widened = replace(base, **{widen_leg: wider})
            widened_result = detect_arb001(widened, CostConfig())
            widened_edge = widened_result.net_edge_per_share if isinstance(widened_result, Opportunity) else None

            if base_edge is None:
                assert widened_edge is None or widened_edge <= 0
            elif widened_edge is not None:
                assert widened_edge <= base_edge
            # else: widening pushed a positive edge to NoOpportunity - edge did not increase.


def test_increasing_cost_config_never_increases_net_edge():
    snapshot = _exact_parity_snapshot()
    snapshot = replace(snapshot, call=_shift(snapshot.call, 3.0))
    cheap = detect_arb001(snapshot, CostConfig(per_share_fee=0.01, buffer_per_share=0.01))
    expensive = detect_arb001(snapshot, CostConfig(per_share_fee=0.05, buffer_per_share=0.10))

    cheap_edge = cheap.net_edge_per_share if isinstance(cheap, Opportunity) else None
    expensive_edge = expensive.net_edge_per_share if isinstance(expensive, Opportunity) else None
    if cheap_edge is None:
        assert expensive_edge is None
    elif expensive_edge is not None:
        assert expensive_edge <= cheap_edge


def test_stale_quote_is_rejected():
    snapshot = _exact_parity_snapshot()
    stale_call = replace(snapshot.call, quoted_at="2026-01-05T14:29:00+00:00")  # 60s before as_of
    snapshot = replace(snapshot, call=stale_call)
    result = detect_arb001(snapshot, CostConfig(), stale_tolerance_seconds=10.0)
    assert isinstance(result, NoOpportunity)
    assert "stale_quote" in result.reason_codes


def test_crossed_market_is_rejected():
    snapshot = _exact_parity_snapshot()
    snapshot = replace(snapshot, put=replace(snapshot.put, bid=snapshot.put.ask + 1.0))
    result = detect_arb001(snapshot, CostConfig())
    assert isinstance(result, NoOpportunity)
    assert "crossed_market" in result.reason_codes


def test_invalid_bid_is_rejected():
    snapshot = _exact_parity_snapshot()
    snapshot = replace(snapshot, underlying=replace(snapshot.underlying, bid=0.0))
    result = detect_arb001(snapshot, CostConfig())
    assert isinstance(result, NoOpportunity)
    assert "invalid_bid" in result.reason_codes


def test_american_style_is_rejected():
    snapshot = replace(_exact_parity_snapshot(), style="american")
    result = detect_arb001(snapshot, CostConfig())
    assert isinstance(result, NoOpportunity)
    assert "non_european_style" in result.reason_codes


def test_borrow_fee_none_still_detects_conversion():
    snapshot = _exact_parity_snapshot(borrow_fee=None)
    snapshot = replace(snapshot, call=_shift(snapshot.call, 5.0))
    result = detect_arb001(snapshot, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.direction == "conversion"


def test_borrow_fee_none_with_reversal_only_edge_reports_missing_borrow():
    snapshot = _exact_parity_snapshot(borrow_fee=None)
    snapshot = replace(snapshot, put=_shift(snapshot.put, 5.0), call=_shift(snapshot.call, -5.0))
    result = detect_arb001(snapshot, CostConfig())
    assert isinstance(result, NoOpportunity)
    assert "missing_borrow" in result.reason_codes
    assert "no_edge" in result.reason_codes


def test_capacity_is_min_across_legs_normalized_by_multiplier():
    snapshot = _exact_parity_snapshot()
    snapshot = replace(
        snapshot,
        call=replace(_shift(snapshot.call, 5.0), bid_size=7),
        put=replace(snapshot.put, ask_size=50),
        underlying=replace(snapshot.underlying, ask_size=1000),
        multiplier=100,
    )
    result = detect_arb001(snapshot, CostConfig())
    assert isinstance(result, Opportunity)
    # call bid_size=7, put ask_size=50, underlying ask_size=1000/multiplier(100)=10 -> min is 7
    assert result.capacity_units == pytest.approx(7)


def test_capacity_floors_at_zero():
    snapshot = _exact_parity_snapshot()
    snapshot = replace(snapshot, call=replace(_shift(snapshot.call, 5.0), bid_size=0))
    result = detect_arb001(snapshot, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.capacity_units == pytest.approx(0.0)
