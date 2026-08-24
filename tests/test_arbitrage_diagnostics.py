"""ARB-015 / ARB-016 diagnostics (backend/arbitrage.py's Phase 2 section;
addendum 27 §11 Phase 2, SPEC_RECONCILIATION §55).

The load-bearing ideas under test: a diagnostic exists only when a *declared*
reference input falls outside the band of values consistent with executable
bid/ask quotes (a mid-price gap smaller than the spread is the market saying
nothing); wider spreads can only weaken a signal, never manufacture one; and
Diagnostics live under their own schema, never inside scan_chain's
opportunities (§8's schema-level separation of D from arbitrage).
"""

from __future__ import annotations

import math
from dataclasses import replace

from backend.arbitrage import (
    ChainSnapshot,
    Diagnostic,
    NoOpportunity,
    Opportunity,
    ParitySnapshot,
    Quote,
    StrikeQuotes,
    detect_arb015,
    detect_arb016,
    diagnose_chain,
    scan_chain,
)
from simulation import pricing

AS_OF = "2026-01-05T14:30:00+00:00"


def _quote(bid, ask, bid_size=200, ask_size=200, quoted_at=AS_OF):
    return Quote(bid=bid, ask=ask, bid_size=bid_size, ask_size=ask_size, quoted_at=quoted_at)


def _coherent_chain(
    strikes=(80.0, 90.0, 100.0, 110.0, 120.0), r=0.03, q=0.01, sigma=0.25,
    expiry_days=30, spot=100.0, spread_pct=0.01, borrow_fee=0.01,
):
    """Same construction as test_arbitrage_phase1's control fixture: priced
    from simulation/pricing.py's own kernel, so parity holds at every strike
    and both declared inputs (pv_div, r) sit inside every executable band."""
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
        entity_id="ENT-1", symbol="SYN1", expiry_days=expiry_days, style="european",
        as_of=AS_OF, underlying=underlying, r=r, pv_div=pv_div,
        borrow_fee_annual=borrow_fee, strikes=tuple(rows),
    )


def _snapshot(
    s_bid, s_ask, c_bid, c_ask, p_bid, p_ask, strike=100.0, r=0.0, pv_div=0.0,
    expiry_days=365, borrow_fee=0.01, as_of=AS_OF,
):
    return ParitySnapshot(
        entity_id="ENT-1", symbol="SYN1", strike=strike, expiry_days=expiry_days,
        style="european", as_of=as_of, underlying=_quote(s_bid, s_ask),
        call=_quote(c_bid, c_ask), put=_quote(p_bid, p_ask), r=r, pv_div=pv_div,
        borrow_fee_annual=borrow_fee,
    )


# --- ARB-015: option-implied dividend ---------------------------------------


def test_a_coherent_chain_yields_no_diagnostics():
    assert diagnose_chain(_coherent_chain()) == []


def test_arb015_band_is_hand_checkable_and_the_gap_is_to_the_nearest_edge():
    """r=0 so PVK=K exactly: band = [Sbid-K-(Cask-Pbid), Sask-K-(Cbid-Pask)]
    = [99.9-100-1.1, 100.1-100-0.9] = [-1.2, -0.8]. A declared dividend of
    zero sits 0.8 above the band's high edge."""
    snapshot = _snapshot(99.9, 100.1, 5.0, 5.1, 4.0, 4.1, pv_div=0.0)
    result = detect_arb015(snapshot)
    assert isinstance(result, Diagnostic)
    assert result.detector_id == "ARB-015"
    assert result.classification == "D"
    assert math.isclose(result.implied_low, -1.2)
    assert math.isclose(result.implied_high, -0.8)
    assert math.isclose(result.gap, 0.8)


def test_arb015_declared_inside_the_band_is_no_signal():
    snapshot = _snapshot(99.9, 100.1, 5.0, 5.1, 4.0, 4.1, pv_div=-1.0)
    result = detect_arb015(snapshot)
    assert isinstance(result, NoOpportunity)
    assert result.reason_codes == ["within_executable_band"]


def test_arb015_wider_spreads_never_manufacture_a_diagnostic():
    """More quote uncertainty widens the band, so a within-band declaration
    stays within band under any symmetric widening - the diagnostics
    restatement of "adverse bid/ask cannot improve edge"."""
    base = _snapshot(99.9, 100.1, 5.0, 5.1, 4.0, 4.1, pv_div=-1.0)
    for widen in (0.1, 0.5, 2.0):
        widened = replace(
            base,
            underlying=_quote(base.underlying.bid - widen, base.underlying.ask + widen),
            call=_quote(max(base.call.bid - widen, 0.01), base.call.ask + widen),
            put=_quote(max(base.put.bid - widen, 0.01), base.put.ask + widen),
        )
        assert isinstance(detect_arb015(widened), NoOpportunity)


def test_arb015_hard_stops_apply_before_any_arithmetic():
    stale = _snapshot(99.9, 100.1, 5.0, 5.1, 4.0, 4.1,
                      as_of="2026-01-05T14:31:00+00:00")  # quotes are a minute old
    result = detect_arb015(stale)
    assert isinstance(result, NoOpportunity)
    assert "stale_quote" in result.reason_codes


# --- ARB-016: implied financing / borrow basis -------------------------------


def test_arb016_declared_rate_inside_the_implied_band_is_no_signal():
    """Quotes constructed from 2% financing exactly: C-P mid = S - K*exp(-0.02).
    A declared r of 2% sits inside the band the spreads allow."""
    snapshot = _snapshot(99.95, 100.05, 6.93, 7.03, 4.95, 5.05, r=0.02)
    result = detect_arb016(snapshot)
    assert isinstance(result, NoOpportunity)
    assert result.reason_codes == ["within_executable_band"]


def test_arb016_fires_when_borrow_is_the_explanation_and_says_so():
    """Same 2%-financing quotes with r declared at 5% and a 3% borrow fee:
    the declared rate is outside the implied band, but r minus borrow falls
    inside it - the B-versus-D evidence the spec draws, carried in inputs."""
    snapshot = _snapshot(99.95, 100.05, 6.93, 7.03, 4.95, 5.05, r=0.05, borrow_fee=0.03)
    result = detect_arb016(snapshot)
    assert isinstance(result, Diagnostic)
    assert result.detector_id == "ARB-016"
    assert result.gap > 0
    assert result.implied_low < 0.05 < result.declared + 1e-12
    assert result.inputs["borrow_explains_gap"] is True

    unexplained = replace(snapshot, borrow_fee_annual=0.001)
    result = detect_arb016(unexplained)
    assert isinstance(result, Diagnostic)
    assert result.inputs["borrow_explains_gap"] is False


def test_arb016_missing_borrow_is_a_refusal_not_a_zero():
    snapshot = _snapshot(99.95, 100.05, 6.93, 7.03, 4.95, 5.05, r=0.05, borrow_fee=None)
    result = detect_arb016(snapshot)
    assert isinstance(result, NoOpportunity)
    assert "missing_borrow" in result.reason_codes


def test_arb016_nonpositive_implied_df_is_a_broken_input_not_a_signal():
    snapshot = _snapshot(99.95, 100.05, 199.0, 201.0, 4.95, 5.05)
    result = detect_arb016(snapshot)
    assert isinstance(result, NoOpportunity)
    assert result.reason_codes == ["implied_df_not_positive"]


# --- diagnose_chain and schema separation ------------------------------------


def test_diagnose_chain_reports_misdeclared_dividends_sorted_by_gap():
    chain = _coherent_chain()
    misdeclared = replace(chain, pv_div=chain.pv_div + 2.0)
    diagnostics = diagnose_chain(misdeclared)
    assert diagnostics, "a 2.0 misdeclaration against ~1% spreads must be visible"
    assert all(isinstance(d, Diagnostic) and d.classification == "D" for d in diagnostics)
    gaps = [d.gap for d in diagnostics]
    assert gaps == sorted(gaps, reverse=True)
    assert any(d.detector_id == "ARB-015" for d in diagnostics)


def test_diagnostics_never_enter_the_opportunity_scan():
    """Addendum 27 §8: schema-level separation of D from arbitrage. The same
    misdeclared chain, both entry points: scan_chain's results carry no
    diagnostic detector ids and no Diagnostic objects, whatever it found."""
    misdeclared = replace(_coherent_chain(), pv_div=_coherent_chain().pv_div + 2.0)
    opportunities = scan_chain(misdeclared)
    assert all(isinstance(o, Opportunity) for o in opportunities)
    assert all(o.detector_id not in ("ARB-015", "ARB-016") for o in opportunities)
    assert not issubclass(Diagnostic, Opportunity)
