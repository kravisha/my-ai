"""Unit and property tests for backend/arbitrage.py's Phase 1 additions
(addendum 27 SS11: ARB-002/003/006/007/008/009/010/011, CostConfig.for_legs,
ChainSnapshot, scan_chain) - kept in a separate file from tests/test_arbitrage.py
(which stays ARB-001-only) since Phase 1 is a large, self-contained addition
with its own fixtures (a multi-strike, Black-Scholes-coherent ChainSnapshot
builder) that ARB-001's tests never needed.

Mirrors addendum 27 SS7's unit list per detector: exact-parity/BS-coherent
fixtures yield NoOpportunity('no_edge'); one constructed violation per
detector/direction fires the right detector, direction, classification and a
positive, hand-checkable edge; adverse bid/ask and added cost cannot improve
edge; hard stops are checked per-package, never on legs a package does not
trade; missing borrow is never guessed at zero; negative rates generalize the
box's PV(width). The two "property against the real generator" tests at the
bottom use simulation/parity_world.py directly and are the reason this file
exists in the first place - see their docstrings for what they found."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from backend.arbitrage import (
    ChainSnapshot,
    CostConfig,
    NoOpportunity,
    Opportunity,
    ParitySnapshot,
    Quote,
    StrikeQuotes,
    detect_arb001,
    detect_arb002,
    detect_arb003,
    detect_arb006,
    detect_arb007,
    detect_arb008,
    detect_arb009,
    detect_arb010,
    detect_arb011,
    scan_chain,
)
from simulation import pricing

AS_OF = "2026-01-05T14:30:00+00:00"


# --- shared fixtures ---------------------------------------------------------


def _quote(bid, ask, bid_size=200, ask_size=200, quoted_at=AS_OF):
    return Quote(bid=bid, ask=ask, bid_size=bid_size, ask_size=ask_size, quoted_at=quoted_at)


def _coherent_chain(
    strikes, r=0.03, q=0.01, sigma=0.25, expiry_days=30, spot=100.0, spread_pct=0.01,
    borrow_fee=0.01, entity_id="ENT-1", symbol="SYN1", as_of=AS_OF,
):
    """A ChainSnapshot priced from simulation/pricing.py's own Black-Scholes
    kernel - the same kernel simulation/parity_world.py uses to render its
    chains, so this fixture is BS-coherent by construction: European parity
    holds at every strike, and calls/puts are automatically monotone and
    convex in strike (BS prices always satisfy their own no-arbitrage
    bounds). This is the "exact parity / arbitrage-free chain" control case
    every no-edge test below starts from."""
    t = expiry_days / 365
    pv_div = pricing.pv_div(spot, q, t)
    rows = []
    for strike in strikes:
        call_mid = pricing.bs_call(spot, strike, t, r, q, sigma)
        put_mid = pricing.bs_put(spot, strike, t, r, q, sigma)
        call_half = max(call_mid, 0.01) * spread_pct / 2
        put_half = max(put_mid, 0.01) * spread_pct / 2
        rows.append(StrikeQuotes(
            strike=strike,
            call=_quote(call_mid - call_half, call_mid + call_half),
            put=_quote(put_mid - put_half, put_mid + put_half),
        ))
    underlying = _quote(spot - spot * spread_pct / 2, spot + spot * spread_pct / 2)
    return ChainSnapshot(
        entity_id=entity_id, symbol=symbol, expiry_days=expiry_days, style="european", as_of=as_of,
        underlying=underlying, r=r, pv_div=pv_div, borrow_fee_annual=borrow_fee, strikes=tuple(rows),
    )


DEFAULT_STRIKES = (80.0, 85.0, 90.0, 95.0, 100.0, 105.0, 110.0, 115.0, 120.0)


def _bump_strike(chain: ChainSnapshot, strike: float, call_delta: float = 0.0, put_delta: float = 0.0) -> ChainSnapshot:
    """A new ChainSnapshot with one strike's call and/or put quote shifted by
    a flat delta on both sides (keeping the spread width), the rest
    untouched - the standard way every violation test below perturbs exactly
    one leg of a coherent chain."""
    new_strikes = []
    for sq in chain.strikes:
        if sq.strike == strike:
            call = replace(sq.call, bid=sq.call.bid + call_delta, ask=sq.call.ask + call_delta) if call_delta else sq.call
            put = replace(sq.put, bid=sq.put.bid + put_delta, ask=sq.put.ask + put_delta) if put_delta else sq.put
            new_strikes.append(StrikeQuotes(strike=sq.strike, call=call, put=put))
        else:
            new_strikes.append(sq)
    return replace(chain, strikes=tuple(new_strikes))


def _parity_snapshot(chain: ChainSnapshot, strike: float) -> ParitySnapshot:
    sq = next(s for s in chain.strikes if s.strike == strike)
    return ParitySnapshot(
        entity_id=chain.entity_id, symbol=chain.symbol, strike=sq.strike, expiry_days=chain.expiry_days,
        style=chain.style, as_of=chain.as_of, underlying=chain.underlying, call=sq.call, put=sq.put,
        r=chain.r, pv_div=chain.pv_div, borrow_fee_annual=chain.borrow_fee_annual, multiplier=chain.multiplier,
    )


# =============================================================================
# CostConfig.for_legs
# =============================================================================


def test_for_legs_matches_total_per_share_at_three_legs():
    costs = CostConfig(per_share_fee=0.02, buffer_per_share=0.03)
    assert costs.for_legs(3) == pytest.approx(costs.total_per_share)


def test_for_legs_scales_linearly_with_leg_count():
    costs = CostConfig(per_share_fee=0.02, buffer_per_share=0.03)
    assert costs.for_legs(1) == pytest.approx(0.05)
    assert costs.for_legs(2) == pytest.approx(0.07)
    assert costs.for_legs(4) == pytest.approx(0.11)


# =============================================================================
# ChainSnapshot validation
# =============================================================================


def test_chain_snapshot_requires_nonempty_strikes():
    with pytest.raises(ValueError):
        ChainSnapshot(
            entity_id="E", symbol="S", expiry_days=30, style="european", as_of=AS_OF,
            underlying=_quote(99, 101), r=0.03, pv_div=0.0, borrow_fee_annual=0.01, strikes=(),
        )


def test_chain_snapshot_requires_sorted_strikes():
    with pytest.raises(ValueError):
        ChainSnapshot(
            entity_id="E", symbol="S", expiry_days=30, style="european", as_of=AS_OF,
            underlying=_quote(99, 101), r=0.03, pv_div=0.0, borrow_fee_annual=0.01,
            strikes=(StrikeQuotes(100.0, _quote(1, 2), _quote(1, 2)), StrikeQuotes(90.0, _quote(1, 2), _quote(1, 2))),
        )


def test_chain_snapshot_rejects_duplicate_strikes():
    with pytest.raises(ValueError):
        ChainSnapshot(
            entity_id="E", symbol="S", expiry_days=30, style="european", as_of=AS_OF,
            underlying=_quote(99, 101), r=0.03, pv_div=0.0, borrow_fee_annual=0.01,
            strikes=(StrikeQuotes(100.0, _quote(1, 2), _quote(1, 2)), StrikeQuotes(100.0, _quote(1, 2), _quote(1, 2))),
        )


# =============================================================================
# Exact-parity / BS-coherent fixture -> no edge, for every detector
# =============================================================================


def test_coherent_chain_yields_no_opportunity_for_every_detector():
    chain = _coherent_chain(DEFAULT_STRIKES)
    costs = CostConfig()
    for strike in DEFAULT_STRIKES:
        snap = _parity_snapshot(chain, strike)
        assert isinstance(detect_arb001(snap, costs), NoOpportunity)
        assert isinstance(detect_arb002(snap, costs), NoOpportunity)
        assert isinstance(detect_arb003(snap, costs), NoOpportunity)
        assert isinstance(detect_arb010(snap, costs), NoOpportunity)
    strikes = list(DEFAULT_STRIKES)
    for i in range(len(strikes)):
        for j in range(i + 1, len(strikes)):
            k1, k2 = strikes[i], strikes[j]
            assert isinstance(detect_arb006(chain, k1, k2, costs), NoOpportunity)
            assert isinstance(detect_arb007(chain, k1, k2, costs), NoOpportunity)
            assert isinstance(detect_arb008(chain, k1, k2, costs), NoOpportunity)
            assert isinstance(detect_arb011(chain, k1, k2, costs), NoOpportunity)
    for i in range(len(strikes)):
        for j in range(i + 1, len(strikes)):
            for k in range(j + 1, len(strikes)):
                result = detect_arb009(chain, strikes[i], strikes[j], strikes[k], costs)
                assert isinstance(result, NoOpportunity)
    assert scan_chain(chain, costs) == []


# =============================================================================
# ARB-002 / ARB-003
# =============================================================================


def test_arb002_matches_arb001_conversion_edge_exactly():
    """The shared-math guarantee (module docstring on _conversion_gross_edge):
    ARB-001's conversion branch and ARB-002's standalone package must report
    the identical gross and net edge on the same snapshot."""
    chain = _coherent_chain(DEFAULT_STRIKES)
    chain = _bump_strike(chain, 100.0, call_delta=5.0)
    snap = _parity_snapshot(chain, 100.0)
    costs = CostConfig()
    r1 = detect_arb001(snap, costs)
    r2 = detect_arb002(snap, costs)
    assert isinstance(r1, Opportunity) and r1.direction == "conversion"
    assert isinstance(r2, Opportunity) and r2.direction == "conversion"
    assert r2.gross_edge_per_share == pytest.approx(r1.gross_edge_per_share)
    assert r2.net_edge_per_share == pytest.approx(r1.net_edge_per_share)
    assert r2.classification == "A"


def test_arb003_missing_borrow_reports_reason_not_free_borrow():
    chain = _coherent_chain(DEFAULT_STRIKES, borrow_fee=None)
    chain = _bump_strike(chain, 100.0, call_delta=-1.5, put_delta=1.5)
    snap = _parity_snapshot(chain, 100.0)
    result = detect_arb003(snap, CostConfig())
    assert isinstance(result, NoOpportunity)
    assert result.reason_codes == ["missing_borrow"]


def test_arb003_fires_once_borrow_is_available_and_cheap_enough():
    chain = _coherent_chain(DEFAULT_STRIKES, borrow_fee=0.001)
    chain = _bump_strike(chain, 100.0, call_delta=-1.5, put_delta=1.5)
    snap = _parity_snapshot(chain, 100.0)
    result = detect_arb003(snap, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.direction == "reversal"
    assert result.classification == "B"
    assert result.net_edge_per_share > 0


# =============================================================================
# ARB-006 EUROPEAN BOX
# =============================================================================


def test_arb006_requires_k1_less_than_k2():
    chain = _coherent_chain(DEFAULT_STRIKES)
    with pytest.raises(ValueError):
        detect_arb006(chain, 100.0, 95.0, CostConfig())


def test_arb006_long_box_violation_hand_checked():
    """Bump put(k1)'s bid up (rich put at the lower strike) - this reduces
    long_debit = C1ask - C2bid + P2ask - P1bid directly, below PV(width)."""
    chain = _coherent_chain(DEFAULT_STRIKES)
    k1, k2 = 95.0, 105.0
    chain = _bump_strike(chain, k1, put_delta=6.0)
    result = detect_arb006(chain, k1, k2, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.direction == "long_box"
    assert result.classification == "A"

    sq1 = next(s for s in chain.strikes if s.strike == k1)
    sq2 = next(s for s in chain.strikes if s.strike == k2)
    pv_width = (k2 - k1) * math.exp(-chain.r * chain.expiry_days / 365)
    debit = sq1.call.ask - sq2.call.bid + sq2.put.ask - sq1.put.bid
    expected_net = pv_width - debit - CostConfig().for_legs(4)
    assert result.net_edge_per_share == pytest.approx(expected_net)
    assert expected_net > 0


def test_arb006_short_box_violation_hand_checked():
    """Bump call(k1)'s bid up (rich call at the lower strike) - this raises
    short_credit = C1bid - C2ask + P2bid - P1ask directly, above PV(width)."""
    chain = _coherent_chain(DEFAULT_STRIKES)
    k1, k2 = 95.0, 105.0
    chain = _bump_strike(chain, k1, call_delta=6.0)
    result = detect_arb006(chain, k1, k2, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.direction == "short_box"

    sq1 = next(s for s in chain.strikes if s.strike == k1)
    sq2 = next(s for s in chain.strikes if s.strike == k2)
    pv_width = (k2 - k1) * math.exp(-chain.r * chain.expiry_days / 365)
    credit = sq1.call.bid - sq2.call.ask + sq2.put.bid - sq1.put.ask
    expected_net = credit - pv_width - CostConfig().for_legs(4)
    assert result.net_edge_per_share == pytest.approx(expected_net)


def test_arb006_negative_rate_still_detects_the_violation():
    """ARB-030's generalization: with r<0, DF>1 so PV(width) exceeds the raw
    strike width, and the box formulas (DF-based throughout) must still hold
    and still catch a real violation."""
    k1, k2 = 95.0, 105.0
    chain = _coherent_chain(DEFAULT_STRIKES, r=-0.01)
    assert isinstance(detect_arb006(chain, k1, k2, CostConfig()), NoOpportunity)  # still clean

    pv_width = (k2 - k1) * math.exp(0.01 * chain.expiry_days / 365)
    assert pv_width > (k2 - k1)  # DF > 1 under negative rates

    violated = _bump_strike(chain, k1, put_delta=6.0)
    result = detect_arb006(violated, k1, k2, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.direction == "long_box"
    assert result.net_edge_per_share > 0


def test_arb006_hard_stop_on_a_traded_leg_refuses():
    chain = _coherent_chain(DEFAULT_STRIKES)
    stale = replace(next(s for s in chain.strikes if s.strike == 95.0).call, quoted_at="2026-01-05T14:00:00+00:00")
    new_strikes = tuple(
        StrikeQuotes(s.strike, stale, s.put) if s.strike == 95.0 else s for s in chain.strikes
    )
    chain = replace(chain, strikes=new_strikes)
    result = detect_arb006(chain, 95.0, 105.0, CostConfig())
    assert isinstance(result, NoOpportunity)
    assert "stale_quote" in result.reason_codes


# =============================================================================
# ARB-007 CALL VERTICAL BOUNDS / ARB-008 PUT VERTICAL BOUNDS
# =============================================================================


def test_arb007_lower_bound_violation_only_when_include_monotonicity():
    chain = _coherent_chain(DEFAULT_STRIKES)
    chain = _bump_strike(chain, 105.0, call_delta=6.0)  # rich call at higher strike
    with_mono = detect_arb007(chain, 100.0, 105.0, CostConfig(), include_monotonicity=True)
    without_mono = detect_arb007(chain, 100.0, 105.0, CostConfig(), include_monotonicity=False)
    assert isinstance(with_mono, Opportunity)
    assert with_mono.direction == "call_vertical_lower"
    assert with_mono.classification == "A"
    assert isinstance(without_mono, NoOpportunity)  # (a) branch suppressed, (b) does not fire here


def test_arb007_upper_bound_width_violation_hand_checked():
    chain = _coherent_chain(DEFAULT_STRIKES)
    k1, k2 = 90.0, 95.0
    chain = _bump_strike(chain, k1, call_delta=40.0)  # deeply rich call at the lower strike
    result = detect_arb007(chain, k1, k2, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.direction == "call_vertical_upper"

    sq1 = next(s for s in chain.strikes if s.strike == k1)
    sq2 = next(s for s in chain.strikes if s.strike == k2)
    pv_width = (k2 - k1) * math.exp(-chain.r * chain.expiry_days / 365)
    expected = (sq1.call.bid - sq2.call.ask) - pv_width - CostConfig().for_legs(2)
    assert result.net_edge_per_share == pytest.approx(expected)


def test_arb008_lower_bound_violation_only_when_include_monotonicity():
    chain = _coherent_chain(DEFAULT_STRIKES)
    chain = _bump_strike(chain, 95.0, put_delta=6.0)  # rich put at the lower strike
    with_mono = detect_arb008(chain, 95.0, 100.0, CostConfig(), include_monotonicity=True)
    without_mono = detect_arb008(chain, 95.0, 100.0, CostConfig(), include_monotonicity=False)
    assert isinstance(with_mono, Opportunity)
    assert with_mono.direction == "put_vertical_lower"
    assert isinstance(without_mono, NoOpportunity)


def test_arb008_upper_bound_width_violation_hand_checked():
    chain = _coherent_chain(DEFAULT_STRIKES)
    k1, k2 = 115.0, 120.0
    chain = _bump_strike(chain, k2, put_delta=40.0)  # deeply rich put at the higher strike
    result = detect_arb008(chain, k1, k2, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.direction == "put_vertical_upper"

    sq1 = next(s for s in chain.strikes if s.strike == k1)
    sq2 = next(s for s in chain.strikes if s.strike == k2)
    pv_width = (k2 - k1) * math.exp(-chain.r * chain.expiry_days / 365)
    expected = (sq2.put.bid - sq1.put.ask) - pv_width - CostConfig().for_legs(2)
    assert result.net_edge_per_share == pytest.approx(expected)


# =============================================================================
# ARB-009 STRIKE CONVEXITY/BUTTERFLY
# =============================================================================


def test_arb009_requires_strictly_increasing_strikes():
    chain = _coherent_chain(DEFAULT_STRIKES)
    with pytest.raises(ValueError):
        detect_arb009(chain, 100.0, 95.0, 110.0, CostConfig())


def test_arb009_equal_spacing_weights_are_one_half():
    k1, k2, k3 = 90.0, 100.0, 110.0
    w1 = (k3 - k2) / (k3 - k1)
    w3 = (k2 - k1) / (k3 - k1)
    assert w1 == pytest.approx(0.5)
    assert w3 == pytest.approx(0.5)


def test_arb009_call_butterfly_violation_equal_spacing_hand_checked():
    chain = _coherent_chain(DEFAULT_STRIKES)
    k1, k2, k3 = 90.0, 100.0, 110.0
    chain = _bump_strike(chain, k2, call_delta=3.0)  # rich middle call -> convexity violation
    result = detect_arb009(chain, k1, k2, k3, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.direction == "call_butterfly"
    assert result.classification == "A"

    sq1 = next(s for s in chain.strikes if s.strike == k1)
    sq2 = next(s for s in chain.strikes if s.strike == k2)
    sq3 = next(s for s in chain.strikes if s.strike == k3)
    cost = 0.5 * sq1.call.ask - sq2.call.bid + 0.5 * sq3.call.ask
    expected = -cost - CostConfig().for_legs(3)
    assert result.net_edge_per_share == pytest.approx(expected)
    assert expected > 0


def test_arb009_put_butterfly_unequal_spacing_hand_checked():
    """k1,k2,k3 unequally spaced (10 then 5) - the general-weights form the
    spec asks for when spacing is not equal."""
    chain = _coherent_chain(DEFAULT_STRIKES)
    k1, k2, k3 = 90.0, 100.0, 105.0
    w1 = (k3 - k2) / (k3 - k1)  # 5/15 = 1/3
    w3 = (k2 - k1) / (k3 - k1)  # 10/15 = 2/3
    assert w1 == pytest.approx(1 / 3)
    assert w3 == pytest.approx(2 / 3)

    chain = _bump_strike(chain, k2, put_delta=2.0)  # rich middle put
    result = detect_arb009(chain, k1, k2, k3, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.direction == "put_butterfly"

    sq1 = next(s for s in chain.strikes if s.strike == k1)
    sq2 = next(s for s in chain.strikes if s.strike == k2)
    sq3 = next(s for s in chain.strikes if s.strike == k3)
    cost = w1 * sq1.put.ask - sq2.put.bid + w3 * sq3.put.ask
    expected = -cost - CostConfig().for_legs(3)
    assert result.net_edge_per_share == pytest.approx(expected)


def test_arb009_hard_stops_are_independent_for_calls_and_puts():
    """A stale put must not block the call_butterfly package, which never
    trades puts (module docstring's shared package-level rule)."""
    chain = _coherent_chain(DEFAULT_STRIKES)
    k1, k2, k3 = 90.0, 100.0, 110.0
    chain = _bump_strike(chain, k2, call_delta=3.0)  # call violation planted
    stale_put = replace(next(s for s in chain.strikes if s.strike == k2).put, quoted_at="2026-01-05T14:00:00+00:00")
    new_strikes = tuple(
        StrikeQuotes(s.strike, s.call, stale_put) if s.strike == k2 else s for s in chain.strikes
    )
    chain = replace(chain, strikes=new_strikes)
    result = detect_arb009(chain, k1, k2, k3, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.direction == "call_butterfly"  # unaffected by the put's stale quote


# =============================================================================
# ARB-010 INTRINSIC/UPPER BOUNDS
# =============================================================================


def test_arb010_call_upper_violation():
    snap = ParitySnapshot(
        entity_id="E", symbol="S", strike=100.0, expiry_days=30, style="european", as_of=AS_OF,
        underlying=_quote(99.9, 100.1), call=_quote(150.0, 150.1), put=_quote(0.1, 0.2),
        r=0.03, pv_div=0.0, borrow_fee_annual=0.01,
    )
    result = detect_arb010(snap, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.direction == "call_upper"
    assert result.classification == "A"
    expected = snap.call.bid - snap.underlying.ask - CostConfig().for_legs(2)
    assert result.net_edge_per_share == pytest.approx(expected)


def test_arb010_call_lower_violation():
    snap = ParitySnapshot(
        entity_id="E", symbol="S", strike=50.0, expiry_days=30, style="european", as_of=AS_OF,
        underlying=_quote(199.9, 200.1), call=_quote(0.5, 0.6), put=_quote(0.01, 0.02),
        r=0.03, pv_div=0.0, borrow_fee_annual=0.0001,
    )
    result = detect_arb010(snap, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.direction == "call_lower"
    assert result.classification == "B"


def test_arb010_call_lower_missing_borrow():
    snap = ParitySnapshot(
        entity_id="E", symbol="S", strike=50.0, expiry_days=30, style="european", as_of=AS_OF,
        underlying=_quote(199.9, 200.1), call=_quote(0.5, 0.6), put=_quote(0.01, 0.02),
        r=0.03, pv_div=0.0, borrow_fee_annual=None,
    )
    result = detect_arb010(snap, CostConfig())
    assert isinstance(result, NoOpportunity)
    assert "missing_borrow" in result.reason_codes


def test_arb010_put_lower_violation():
    snap = ParitySnapshot(
        entity_id="E", symbol="S", strike=200.0, expiry_days=30, style="european", as_of=AS_OF,
        underlying=_quote(49.9, 50.1), call=_quote(0.01, 0.02), put=_quote(0.5, 0.6),
        r=0.03, pv_div=0.0, borrow_fee_annual=0.01,
    )
    result = detect_arb010(snap, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.direction == "put_lower"
    assert result.classification == "A"


def test_arb010_put_upper_violation():
    snap = ParitySnapshot(
        entity_id="E", symbol="S", strike=100.0, expiry_days=30, style="european", as_of=AS_OF,
        underlying=_quote(99.9, 100.1), call=_quote(0.1, 0.2), put=_quote(150.0, 150.1),
        r=0.03, pv_div=0.0, borrow_fee_annual=0.01,
    )
    result = detect_arb010(snap, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.direction == "put_upper"
    expected = snap.put.bid - snap.strike * math.exp(-snap.r * snap.expiry_days / 365) - CostConfig().for_legs(1)
    assert result.net_edge_per_share == pytest.approx(expected)


def test_arb010_stale_leg_does_not_block_a_check_that_never_touches_it():
    """A stale call must not block 'put_upper', which trades only the put."""
    snap = ParitySnapshot(
        entity_id="E", symbol="S", strike=100.0, expiry_days=30, style="european", as_of=AS_OF,
        underlying=_quote(99.9, 100.1), call=_quote(5.75, 5.85), put=_quote(150.0, 150.1),
        r=0.03, pv_div=0.0, borrow_fee_annual=0.01,
    )
    stale_call = replace(snap.call, quoted_at="2026-01-05T14:00:00+00:00")
    snap = replace(snap, call=stale_call)
    result = detect_arb010(snap, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.direction == "put_upper"


# =============================================================================
# ARB-011 STRIKE MONOTONICITY
# =============================================================================


def test_arb011_calls_violation():
    chain = _coherent_chain(DEFAULT_STRIKES)
    chain = _bump_strike(chain, 105.0, call_delta=6.0)
    result = detect_arb011(chain, 100.0, 105.0, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.direction == "monotonicity_calls"
    assert result.classification == "A"

    sq1 = next(s for s in chain.strikes if s.strike == 100.0)
    sq2 = next(s for s in chain.strikes if s.strike == 105.0)
    expected = sq2.call.bid - sq1.call.ask - CostConfig().for_legs(2)
    assert result.net_edge_per_share == pytest.approx(expected)


def test_arb011_puts_violation():
    chain = _coherent_chain(DEFAULT_STRIKES)
    chain = _bump_strike(chain, 95.0, put_delta=6.0)
    result = detect_arb011(chain, 95.0, 100.0, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.direction == "monotonicity_puts"


def test_arb011_hard_stops_are_independent_for_calls_and_puts():
    chain = _coherent_chain(DEFAULT_STRIKES)
    chain = _bump_strike(chain, 105.0, call_delta=6.0)  # call violation planted
    stale_put = replace(next(s for s in chain.strikes if s.strike == 105.0).put, quoted_at="2026-01-05T14:00:00+00:00")
    new_strikes = tuple(
        StrikeQuotes(s.strike, s.call, stale_put) if s.strike == 105.0 else s for s in chain.strikes
    )
    chain = replace(chain, strikes=new_strikes)
    result = detect_arb011(chain, 100.0, 105.0, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.direction == "monotonicity_calls"  # call package unaffected by the put's stale quote


# =============================================================================
# Property: widening a traded leg's spread never increases net edge
# =============================================================================


def _widen_strike(chain: ChainSnapshot, strike: float, widen: float) -> ChainSnapshot:
    new_strikes = []
    for sq in chain.strikes:
        if sq.strike == strike:
            call = replace(sq.call, bid=sq.call.bid - widen, ask=sq.call.ask + widen)
            put = replace(sq.put, bid=sq.put.bid - widen, ask=sq.put.ask + widen)
            new_strikes.append(StrikeQuotes(sq.strike, call, put))
        else:
            new_strikes.append(sq)
    return replace(chain, strikes=tuple(new_strikes))


def _net_edge(result):
    return result.net_edge_per_share if isinstance(result, Opportunity) else None


@pytest.mark.parametrize("widen", (0.02, 0.10, 0.50))
def test_widening_a_traded_leg_never_increases_box_edge(widen):
    chain = _coherent_chain(DEFAULT_STRIKES)
    chain = _bump_strike(chain, 95.0, put_delta=6.0)
    base = detect_arb006(chain, 95.0, 105.0, CostConfig())
    for strike in (95.0, 105.0):
        widened = _widen_strike(chain, strike, widen)
        after = detect_arb006(widened, 95.0, 105.0, CostConfig())
        base_edge, after_edge = _net_edge(base), _net_edge(after)
        if base_edge is None:
            assert after_edge is None or after_edge <= 0
        elif after_edge is not None:
            assert after_edge <= base_edge


@pytest.mark.parametrize("widen", (0.02, 0.10, 0.50))
def test_widening_a_traded_leg_never_increases_butterfly_edge(widen):
    chain = _coherent_chain(DEFAULT_STRIKES)
    chain = _bump_strike(chain, 100.0, call_delta=3.0)
    base = detect_arb009(chain, 90.0, 100.0, 110.0, CostConfig())
    for strike in (90.0, 100.0, 110.0):
        widened = _widen_strike(chain, strike, widen)
        after = detect_arb009(widened, 90.0, 100.0, 110.0, CostConfig())
        base_edge, after_edge = _net_edge(base), _net_edge(after)
        if base_edge is None:
            assert after_edge is None or after_edge <= 0
        elif after_edge is not None:
            assert after_edge <= base_edge


# =============================================================================
# Property: raising CostConfig never increases net edge
# =============================================================================


def test_increasing_cost_config_never_increases_edge_across_detectors():
    cheap = CostConfig(per_share_fee=0.01, buffer_per_share=0.01)
    expensive = CostConfig(per_share_fee=0.05, buffer_per_share=0.10)

    chain = _coherent_chain(DEFAULT_STRIKES)
    box_chain = _bump_strike(chain, 95.0, put_delta=6.0)
    fly_chain = _bump_strike(chain, 100.0, call_delta=3.0)
    vert_chain = _bump_strike(chain, 90.0, call_delta=40.0)
    mono_chain = _bump_strike(chain, 105.0, call_delta=6.0)

    checks = [
        (detect_arb006(box_chain, 95.0, 105.0, cheap), detect_arb006(box_chain, 95.0, 105.0, expensive)),
        (detect_arb009(fly_chain, 90.0, 100.0, 110.0, cheap), detect_arb009(fly_chain, 90.0, 100.0, 110.0, expensive)),
        (detect_arb007(vert_chain, 90.0, 95.0, cheap), detect_arb007(vert_chain, 90.0, 95.0, expensive)),
        (detect_arb011(mono_chain, 100.0, 105.0, cheap), detect_arb011(mono_chain, 100.0, 105.0, expensive)),
    ]
    for cheap_result, expensive_result in checks:
        cheap_edge, expensive_edge = _net_edge(cheap_result), _net_edge(expensive_result)
        if cheap_edge is None:
            assert expensive_edge is None
        elif expensive_edge is not None:
            assert expensive_edge <= cheap_edge


# =============================================================================
# scan_chain: dedup and sorting
# =============================================================================


def test_scan_chain_reports_one_monotonicity_opportunity_attributed_to_arb011():
    chain = _coherent_chain(DEFAULT_STRIKES)
    chain = _bump_strike(chain, 105.0, call_delta=2.0)  # small enough to violate only the (100,105) pair
    opps = scan_chain(chain, CostConfig())
    mono_opps = [o for o in opps if o.direction == "monotonicity_calls"]
    assert len(mono_opps) == 1
    assert mono_opps[0].detector_id == "ARB-011"
    # ARB-007's identical (a)-branch package must not also appear under a
    # different detector id (scan_chain runs ARB-007 with
    # include_monotonicity=False for exactly this reason).
    assert not any(o.detector_id == "ARB-007" and o.direction == "call_vertical_lower" for o in opps)


def test_scan_chain_sorts_by_net_edge_descending():
    chain = _coherent_chain(DEFAULT_STRIKES)
    chain = _bump_strike(chain, 90.0, call_delta=40.0)   # a big vertical-upper violation
    chain = _bump_strike(chain, 105.0, call_delta=6.0)   # a smaller monotonicity violation
    opps = scan_chain(chain, CostConfig())
    assert len(opps) >= 2
    edges = [o.net_edge_per_share for o in opps]
    assert edges == sorted(edges, reverse=True)


def test_scan_chain_skips_hard_stopped_packages_silently():
    chain = _coherent_chain(DEFAULT_STRIKES)
    chain = _bump_strike(chain, 105.0, call_delta=6.0)
    stale_underlying = replace(chain.underlying, quoted_at="2026-01-05T14:00:00+00:00")
    chain = replace(chain, underlying=stale_underlying)
    # Every package touching the underlying (ARB-001/002/003/010) is now
    # hard-stopped, but ARB-006/007/008/009/011 never touch the underlying,
    # so the planted monotonicity violation must still be found.
    opps = scan_chain(chain, CostConfig())
    assert any(o.detector_id == "ARB-011" and o.direction == "monotonicity_calls" for o in opps)
    assert not any(o.detector_id in ("ARB-001", "ARB-010") for o in opps)


# =============================================================================
# Property against the real generator (simulation/parity_world.py)
# =============================================================================
#
# addendum 27 SS7 asks for "generate arbitrage-free European chains, verify no
# executable positives." simulation/parity_world.py's 'none' variant is that
# generator: every scenario is priced from one Black-Scholes kernel so
# parity holds by construction, and nothing is injected. Running scan_chain's
# full Phase 1 suite over it found two real findings, both investigated and
# both traced to the *world generator* (simulation/parity_world.py, built
# earlier for ARB-001 only) rather than to a Phase 1 detector formula bug:
#
# 1. The 'localized_distortion' skew shape (simulation/parity_world.py's
#    draw_skew) intentionally bumps implied vol at exactly one
#    (moneyness, expiry) grid cell, leaving its neighbors untouched. Because
#    call and put at that one cell still share the same (bumped) sigma,
#    ARB-001/002/003/010 (same-strike checks) stay clean - but the resulting
#    price at that one strike can genuinely violate strike monotonicity or
#    convexity relative to its neighbors, which ARB-006/007/008/009/011
#    (cross-strike checks) correctly catch. A 25-seed, 150-scenario sweep
#    found this is the *only* skew shape that ever produces a cross-strike
#    opportunity on a 'none'-mix world; every other shape (flat, put_skew,
#    call_heavy, smile, steep/shallow put skew, inverted_term) was clean
#    across every seed and scenario tried.
# 2. Single-strike detectors (ARB-001/002/003/010) never fired on a single
#    non-distorted scenario in that same sweep.
#
# The tests below assert exactly these two properties, which the sweep
# confirmed hold and which a real ARB-006-011 formula bug would violate
# (since only ~1 shape in 8 gets excluded, the second test still exercises
# every cross-strike detector against the overwhelming majority of
# scenarios).


def _reference_ready_conn():
    from backend import fi_db, reference_data as rd
    conn = fi_db.get_connection(":memory:")
    fi_db.init_schema(conn)
    rd.run_reference_engine(conn)
    return conn


def test_none_mix_single_strike_detectors_never_fire_across_seeds():
    from simulation import parity_world as pw
    from providers.stored_data import chain_snapshots

    conn = _reference_ready_conn()
    focus_assets_cache = None
    for seed in (101, 102, 103):
        config = pw.MissionConfig(
            mission_id=f"m-none-single-{seed}", run_mode="simulation", strategy="put_call_parity_arbitrage",
            seed=seed, n_scenarios=5, scenario_mix={"none": 1.0},
        )
        from backend import reference_data as rd
        focus_assets_cache = focus_assets_cache or rd.list_focus_assets(conn)
        for i in range(config.n_scenarios):
            scenario = pw._build_scenario(config, focus_assets_cache, i)
            obs = pw.build_option_chain_observation(scenario, config)
            for chain in chain_snapshots(obs):
                for sq in chain.strikes:
                    snap = ParitySnapshot(
                        entity_id=chain.entity_id, symbol=chain.symbol, strike=sq.strike,
                        expiry_days=chain.expiry_days, style=chain.style, as_of=chain.as_of,
                        underlying=chain.underlying, call=sq.call, put=sq.put, r=chain.r,
                        pv_div=chain.pv_div, borrow_fee_annual=chain.borrow_fee_annual,
                    )
                    for detector in (detect_arb001, detect_arb002, detect_arb003, detect_arb010):
                        result = detector(snap, CostConfig())
                        assert isinstance(result, NoOpportunity), (
                            f"seed={seed} scenario={i} strike={sq.strike} expiry={chain.expiry_days} "
                            f"skew={scenario.ground_truth.skew_shape}: {detector.__name__} found {result!r} "
                            "on a 'none'-mix (uninjected) world"
                        )


def test_none_mix_full_scan_chain_clean_except_localized_distortion_skew():
    from simulation import parity_world as pw
    from providers.stored_data import chain_snapshots

    conn = _reference_ready_conn()
    from backend import reference_data as rd
    checked_non_distorted = 0
    for seed in (201, 202, 203):
        config = pw.MissionConfig(
            mission_id=f"m-none-full-{seed}", run_mode="simulation", strategy="put_call_parity_arbitrage",
            seed=seed, n_scenarios=6, scenario_mix={"none": 1.0},
        )
        focus_assets = rd.list_focus_assets(conn)
        for i in range(config.n_scenarios):
            scenario = pw._build_scenario(config, focus_assets, i)
            gt = scenario.ground_truth
            obs = pw.build_option_chain_observation(scenario, config)
            for chain in chain_snapshots(obs):
                opps = scan_chain(chain, CostConfig())
                if gt.skew_shape == "localized_distortion":
                    # May legitimately fire cross-strike detectors (module
                    # note above) but never a same-strike one.
                    assert not any(o.detector_id in ("ARB-001", "ARB-010") for o in opps)
                else:
                    checked_non_distorted += 1
                    assert opps == [], (
                        f"seed={seed} scenario={i} expiry={chain.expiry_days} skew={gt.skew_shape}: "
                        f"scan_chain found {[(o.detector_id, o.direction) for o in opps]} on an "
                        "arbitrage-free chain"
                    )
    assert checked_non_distorted > 20  # the property actually got exercised, not vacuously true


def test_genuine_mix_finds_arb001_and_any_other_hit_traces_to_a_known_source():
    """Genuine-mix worlds (mix genuine 1.0): the injected (strike, expiry)
    cell must show up as an ARB-001 opportunity in the expected direction.

    simulation/parity_world.py's injector (built for ARB-001 only) shifts
    one strike's mid price without preserving cross-strike coherence, so it
    can also - correctly - trip ARB-006/007/008/009/011 at strike pairs that
    include the same injected strike; every such hit's leg strikes must
    include the injected strike.

    Separately - and independently of which variant is injected - the skew
    generator (draw_skew) can pick 'localized_distortion' for the scenario,
    which bumps IV at one unrelated (moneyness, expiry) cell and, as the
    module note above the 'none'-mix tests documents, is the one skew shape
    that legitimately produces cross-strike violations on its own. A
    'genuine' scenario can therefore carry a second, independent cross-strike
    violation that has nothing to do with the injected strike at all. Any hit
    that does not trace to the injected strike is only accepted when this
    scenario's skew_shape is 'localized_distortion' (the already-characterized
    source); anything else would be an unexplained violation and a real bug."""
    from simulation import parity_world as pw
    from providers.stored_data import chain_snapshots

    conn = _reference_ready_conn()
    from backend import reference_data as rd
    for seed in (301, 302, 303):
        config = pw.MissionConfig(
            mission_id=f"m-genuine-{seed}", run_mode="simulation", strategy="put_call_parity_arbitrage",
            seed=seed, n_scenarios=5, scenario_mix={"genuine": 1.0},
        )
        focus_assets = rd.list_focus_assets(conn)
        for i in range(config.n_scenarios):
            scenario = pw._build_scenario(config, focus_assets, i)
            gt = scenario.ground_truth
            obs = pw.build_option_chain_observation(scenario, config)
            found_injected = False
            for chain in chain_snapshots(obs):
                opps = scan_chain(chain, CostConfig())
                for o in opps:
                    if o.detector_id == "ARB-001" and chain.expiry_days == gt.affected_expiry_days:
                        if o.inputs.get("strike") == gt.affected_strike:
                            assert o.direction == gt.expected_direction
                            found_injected = True
                            continue
                    leg_strikes = {o.inputs.get("strike"), o.inputs.get("k1"), o.inputs.get("k2"), o.inputs.get("k3")}
                    leg_strikes.discard(None)
                    traces_to_injection = gt.affected_strike in leg_strikes
                    assert traces_to_injection or gt.skew_shape == "localized_distortion", (
                        f"seed={seed} scenario={i} skew={gt.skew_shape}: opportunity "
                        f"{o.detector_id}/{o.direction} at strikes {leg_strikes} does not trace back "
                        f"to the injected strike {gt.affected_strike} (expiry {gt.affected_expiry_days}) "
                        "and is not explained by a localized_distortion skew"
                    )
            assert found_injected, f"seed={seed} scenario={i}: injected conversion opportunity not found"
