"""ARB-012 calendar consistency (backend/arbitrage.py; addendum 27 §11
Phase 2, SPEC_RECONCILIATION §56).

The load-bearing idea: the spec forbids hard-coding "longer expiry always
costs more", so the detector applies the *proven* dominance rule — the
unconditional theorem C(K2,T2) >= C(K1,T1) - slack, where the slack is
exactly what deterministic dividends and rates can legitimately invert. The
test that matters most here is the one where a real executable inversion
exists and the detector stays silent because the slack explains it.
"""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from backend.arbitrage import (
    ChainSnapshot,
    CostConfig,
    NoOpportunity,
    Opportunity,
    Quote,
    StrikeQuotes,
    detect_arb012,
    scan_calendar,
    scan_chain,
)
from simulation import pricing

AS_OF = "2026-01-05T14:30:00+00:00"
COSTS = CostConfig()


def _quote(bid, ask, bid_size=200, ask_size=200, quoted_at=AS_OF):
    return Quote(bid=bid, ask=ask, bid_size=bid_size, ask_size=ask_size, quoted_at=quoted_at)


def _chain(expiry_days, strikes_quotes, r=0.03, pv_div=0.0, symbol="SYN1", as_of=AS_OF):
    """A hand-built single-expiry ladder: strikes_quotes is
    {strike: (c_bid, c_ask, p_bid, p_ask)}."""
    rows = tuple(
        StrikeQuotes(strike=k, call=_quote(cb, ca), put=_quote(pb, pa))
        for k, (cb, ca, pb, pa) in sorted(strikes_quotes.items())
    )
    return ChainSnapshot(
        entity_id="ENT-1", symbol=symbol, expiry_days=expiry_days, style="european",
        as_of=as_of, underlying=_quote(99.9, 100.1), r=r, pv_div=pv_div,
        borrow_fee_annual=0.01, strikes=rows,
    )


def _coherent_chains(expiries=(7, 30, 60), r=0.03, q=0.01, sigma=0.25, spot=100.0,
                     spread_pct=0.01, strikes=(80.0, 90.0, 100.0, 110.0, 120.0)):
    """BS-coherent ladders at several expiries from one (spot, r, q, sigma) -
    the same construction the world generator uses, so the model's own
    no-arbitrage guarantees the calendar bounds hold at mids."""
    chains = []
    for expiry_days in expiries:
        t = expiry_days / 365
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
        chains.append(ChainSnapshot(
            entity_id="ENT-1", symbol="SYN1", expiry_days=expiry_days, style="european",
            as_of=AS_OF, underlying=_quote(spot * 0.9995, spot * 1.0005), r=r,
            pv_div=pricing.pv_div(spot, q, t), borrow_fee_annual=0.01, strikes=tuple(rows),
        ))
    return chains


def test_coherent_chains_are_calendar_clean_across_rate_and_dividend_regimes():
    """Including the regimes that invert the naive rule: high dividends, low
    and negative rates. BS prices obey their own no-arbitrage bounds, so any
    firing here is a false positive by construction."""
    for r, q in ((0.03, 0.01), (0.01, 0.04), (0.06, 0.0), (0.0, 0.04), (-0.01, 0.03)):
        assert scan_calendar(_coherent_chains(r=r, q=q)) == [], f"false positive at r={r}, q={q}"


def test_a_call_inversion_on_a_dividend_bearing_chain_is_never_scored():
    """The spec's own warning as a test, sharpened by what the clean-world
    property test found (§56): with dividends of unknown *model* (pv_div is
    a PV, not a cash-vs-yield declaration), no call-side dominance rule is
    provable at all - a proportional yield makes the shortfall unbounded.
    The near call's bid sits a full 0.60 above the far call's ask - a naive
    calendar rule would fire - and the detector refuses to score it."""
    near = _chain(7, {100.0: (3.00, 3.10, 3.00, 3.10)}, r=0.0, pv_div=0.0)
    far = _chain(30, {100.0: (2.30, 2.40, 3.00, 3.10)}, r=0.0, pv_div=1.0)
    result = detect_arb012(near, far, 100.0, 100.0, COSTS)
    assert isinstance(result, NoOpportunity)
    assert result.reason_codes == ["no_edge"]


def test_negative_rates_give_the_call_side_a_real_slack_on_dividend_free_chains():
    """ARB-030's regime: r < 0 makes DF2 > DF1, so a dividend-free chain has
    slack_c = K*(DF2-DF1) > 0 at the same strike - an executable call
    inversion inside that slack is the market pricing negative carry, not an
    opportunity, and one beyond it is real."""
    r = -0.05
    df1, df2 = math.exp(-r * 7 / 365), math.exp(-r * 30 / 365)
    slack_c = 100.0 * (df2 - df1)
    assert slack_c > 0

    inside = _chain(7, {100.0: (2.50 + slack_c * 0.5, 2.60 + slack_c * 0.5, 2.0, 2.1)}, r=r)
    far = _chain(30, {100.0: (2.40, 2.50, 2.0, 2.1)}, r=r)
    assert isinstance(detect_arb012(inside, far, 100.0, 100.0, COSTS), NoOpportunity)

    beyond = _chain(7, {100.0: (3.10 + slack_c, 3.20 + slack_c, 2.0, 2.1)}, r=r)
    result = detect_arb012(beyond, far, 100.0, 100.0, COSTS)
    assert isinstance(result, Opportunity)
    assert result.direction == "call_calendar"
    assert math.isclose(result.inputs["slack_per_share"], slack_c, abs_tol=1e-12)


def test_call_calendar_violation_is_hand_checkable_and_class_c():
    """No dividends, r=0: slack_c = 0 at the same strike, so the theorem is
    strict dominance. Near call bid 3.00 vs far call ask 2.40: gross = 0.60,
    net = 0.60 - for_legs(2) = 0.57."""
    near = _chain(7, {100.0: (3.00, 3.10, 2.00, 2.10)}, r=0.0)
    far = _chain(30, {100.0: (2.30, 2.40, 2.50, 2.60)}, r=0.0)
    result = detect_arb012(near, far, 100.0, 100.0, COSTS)
    assert isinstance(result, Opportunity)
    assert result.detector_id == "ARB-012"
    assert result.direction == "call_calendar"
    assert result.classification == "C"
    assert math.isclose(result.gross_edge_per_share, 0.60, abs_tol=1e-9)
    assert math.isclose(result.net_edge_per_share, 0.60 - COSTS.for_legs(2), abs_tol=1e-9)
    assert result.inputs["expiry_days"] == 7 and result.inputs["expiry2_days"] == 30
    assert result.inputs["slack_per_share"] == 0.0


def test_put_calendar_violation_with_rate_slack_reserved():
    """Puts' slack comes from interest on the strike: r=5%, K=100, T1=7d,
    T2=30d gives slack_p = K*(DF1-DF2) ~ 0.3139. Near put bid 3.00 vs far
    put ask 2.40 grosses 0.60 before the reserve; the edge that survives is
    0.60 - slack - costs, and the slack rides along in inputs."""
    near = _chain(7, {100.0: (2.00, 2.10, 3.00, 3.10)}, r=0.05)
    far = _chain(30, {100.0: (2.50, 2.60, 2.30, 2.40)}, r=0.05)
    df1, df2 = math.exp(-0.05 * 7 / 365), math.exp(-0.05 * 30 / 365)
    slack_p = 100.0 * (df1 - df2)
    result = detect_arb012(near, far, 100.0, 100.0, COSTS)
    assert isinstance(result, Opportunity)
    assert result.direction == "put_calendar"
    assert math.isclose(result.gross_edge_per_share, 0.60 - slack_p, abs_tol=1e-9)
    assert math.isclose(result.inputs["slack_per_share"], slack_p, abs_tol=1e-12)


def test_adverse_spreads_and_added_cost_can_only_shrink_the_edge():
    near = _chain(7, {100.0: (3.00, 3.10, 2.00, 2.10)}, r=0.0)
    far = _chain(30, {100.0: (2.30, 2.40, 2.50, 2.60)}, r=0.0)
    base = detect_arb012(near, far, 100.0, 100.0, COSTS)
    assert isinstance(base, Opportunity)

    # Sell side worse (near bid down), buy side worse (far ask up).
    worse_near = _chain(7, {100.0: (2.50, 3.10, 2.00, 2.10)}, r=0.0)
    worse_far = _chain(30, {100.0: (2.30, 2.95, 2.50, 2.60)}, r=0.0)
    worse = detect_arb012(worse_near, worse_far, 100.0, 100.0, COSTS)
    assert isinstance(worse, NoOpportunity) or worse.net_edge_per_share < base.net_edge_per_share

    expensive = detect_arb012(near, far, 100.0, 100.0, CostConfig(per_share_fee=0.25, buffer_per_share=0.25))
    assert isinstance(expensive, NoOpportunity)


def test_a_stale_leg_stops_only_the_package_that_trades_it():
    """The near call is stale; the call package is refused but the put
    package (whose legs are all fresh) still fires."""
    stale_call = Quote(bid=3.00, ask=3.10, bid_size=200, ask_size=200,
                       quoted_at="2026-01-05T14:29:00+00:00")
    near = replace(
        _chain(7, {100.0: (2.00, 2.10, 3.00, 3.10)}, r=0.0),
        strikes=(StrikeQuotes(strike=100.0, call=stale_call, put=_quote(3.00, 3.10)),),
    )
    far = _chain(30, {100.0: (2.50, 2.60, 2.30, 2.40)}, r=0.0)
    result = detect_arb012(near, far, 100.0, 100.0, COSTS)
    assert isinstance(result, Opportunity)
    assert result.direction == "put_calendar"


def test_pair_coherence_is_a_caller_error_not_a_reason_code():
    near = _chain(7, {100.0: (3.0, 3.1, 2.0, 2.1)})
    with pytest.raises(ValueError, match="near.expiry_days < far.expiry_days"):
        detect_arb012(near, _chain(7, {100.0: (3.0, 3.1, 2.0, 2.1)}), 100.0, 100.0, COSTS)
    with pytest.raises(ValueError, match="share an underlying"):
        detect_arb012(near, _chain(30, {100.0: (3.0, 3.1, 2.0, 2.1)}, symbol="OTHER"), 100.0, 100.0, COSTS)
    with pytest.raises(ValueError, match="one moment"):
        detect_arb012(near, _chain(30, {100.0: (3.0, 3.1, 2.0, 2.1)}, as_of="2026-01-05T14:31:00+00:00"),
                      100.0, 100.0, COSTS)


def test_scan_calendar_finds_a_planted_same_strike_violation():
    """The put side, because the fixture carries a dividend yield and the
    put rule is the one proven there."""
    chains = _coherent_chains()
    near = chains[0]
    lifted_rows = []
    for sq in near.strikes:
        if sq.strike == 100.0:
            lifted_rows.append(StrikeQuotes(
                strike=sq.strike,
                call=sq.call,
                put=_quote(sq.put.bid + 3.0, sq.put.ask + 3.0),
            ))
        else:
            lifted_rows.append(sq)
    chains[0] = replace(near, strikes=tuple(lifted_rows))

    found = scan_calendar(chains)
    assert found, "a 3.0 lift against ~1% spreads must be visible"
    assert all(o.detector_id == "ARB-012" for o in found)
    nets = [o.net_edge_per_share for o in found]
    assert nets == sorted(nets, reverse=True)
    assert any(o.inputs["k1"] == 100.0 and o.inputs["k2"] == 100.0 and o.direction == "put_calendar"
               for o in found)


def test_a_whole_ladder_parallel_lift_is_calendar_visible_and_same_expiry_invisible():
    """The world injector's algebra, proven at detector level before any
    world uses it: shifting every near-expiry call AND put mid by one
    constant preserves parity at each strike and every same-expiry
    cross-strike relation (all differences are shift-invariant), while
    making the near ladder rich against the far ones - so scan_chain stays
    silent on every expiry and only scan_calendar speaks."""
    chains = _coherent_chains()
    near = chains[0]
    lift = 2.5
    lifted = tuple(
        StrikeQuotes(
            strike=sq.strike,
            call=_quote(round(sq.call.bid + lift, 4), round(sq.call.ask + lift, 4),
                        sq.call.bid_size, sq.call.ask_size),
            put=_quote(round(sq.put.bid + lift, 4), round(sq.put.ask + lift, 4),
                       sq.put.bid_size, sq.put.ask_size),
        )
        for sq in near.strikes
    )
    chains[0] = replace(near, strikes=lifted)

    for chain in chains:
        assert scan_chain(chain) == [], f"same-expiry leak at {chain.expiry_days}d"
    found = scan_calendar(chains)
    assert found
    assert {o.inputs["expiry_days"] for o in found} == {7}
