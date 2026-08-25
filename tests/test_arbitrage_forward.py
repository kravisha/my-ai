"""ARB-013 (forward vs synthetic forward) and ARB-014 (cash-and-carry) -
the forward leg (backend/arbitrage.py, addendum 27 §11, SPEC_RECONCILIATION
§61, TQ-14).

The arithmetic tests pin hand-checkable numbers at r=0 (DF=1), the same
style the other detector suites use: every expected edge below is computable
on paper from the quoted bids and asks. Cost model: CostConfig() defaults,
0.01/leg + 0.01 buffer, so a 3-leg package charges 0.04 and a 2-leg one 0.03.
"""

import pytest

from backend.arbitrage import (
    ChainSnapshot, CostConfig, ForwardQuote, NoOpportunity, Opportunity, Quote, StrikeQuotes,
    detect_arb013, detect_arb014, scan_chain, scan_forward,
)

AS_OF = "2026-01-05T14:30:00+00:00"


def _q(bid, ask, quoted_at=AS_OF, bid_size=50, ask_size=50):
    return Quote(bid=bid, ask=ask, bid_size=bid_size, ask_size=ask_size, quoted_at=quoted_at)


def _chain(strikes=None, r=0.0, pv_div=0.0, borrow_fee_annual=0.0,
           underlying=None, expiry_days=30, style="european"):
    """One parity-consistent strike at K=100 by default: mid C - P = 0 =
    S_mid - K at r=0, pv_div=0, so nothing option-side is ever mispriced
    and every edge in these tests comes from the forward quote alone."""
    if strikes is None:
        strikes = (StrikeQuotes(strike=100.0, call=_q(4.9, 5.1), put=_q(4.9, 5.1)),)
    return ChainSnapshot(
        entity_id="E1", symbol="TEST", expiry_days=expiry_days, style=style, as_of=AS_OF,
        underlying=underlying if underlying is not None else _q(99.9, 100.1),
        r=r, pv_div=pv_div, borrow_fee_annual=borrow_fee_annual, strikes=strikes,
    )


def _fwd(bid, ask, expiry_days=30, **kwargs):
    return ForwardQuote(expiry_days=expiry_days, quote=_q(bid, ask, **kwargs))


# --- ARB-013: forward vs synthetic forward -----------------------------------


def test_arb013_sell_forward_hand_arithmetic():
    """Forward rich: sell it at bid, buy the synthetic long. At r=0:
    gross = (Fbid - K) - (Cask - Pbid) = (102 - 100) - (5.1 - 4.9) = 1.8."""
    result = detect_arb013(_chain(), _fwd(102.0, 102.2), 100.0, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.detector_id == "ARB-013"
    assert result.direction == "sell_forward"
    assert result.gross_edge_per_share == pytest.approx(1.8)
    assert result.net_edge_per_share == pytest.approx(1.8 - 0.04)
    assert result.classification == "A"
    assert result.capacity_units == 50
    assert result.inputs["strike"] == 100.0
    assert result.inputs["expiry_days"] == 30


def test_arb013_buy_forward_hand_arithmetic():
    """Forward cheap: buy it at ask, sell the synthetic. At r=0:
    gross = (Cbid - Pask) - (Fask - K) = (4.9 - 5.1) - (98 - 100) = 1.8."""
    result = detect_arb013(_chain(), _fwd(97.8, 98.0), 100.0, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.direction == "buy_forward"
    assert result.gross_edge_per_share == pytest.approx(1.8)
    assert result.net_edge_per_share == pytest.approx(1.8 - 0.04)
    assert result.classification == "A"


def test_arb013_fair_forward_is_silent():
    """A forward at fair value with an honest spread: both executable sides
    are strictly negative - the market is saying nothing."""
    result = detect_arb013(_chain(), _fwd(99.9, 100.1), 100.0, CostConfig())
    assert isinstance(result, NoOpportunity)
    assert result.reason_codes == ["no_edge"]


def test_arb013_needs_no_borrow():
    """The whole point of the forward completing the market: neither ARB-013
    direction touches stock, so unknown borrow refuses nothing here."""
    chain = _chain(borrow_fee_annual=None)
    result = detect_arb013(chain, _fwd(102.0, 102.2), 100.0, CostConfig())
    assert isinstance(result, Opportunity)
    assert result.classification == "A"


def test_arb013_widening_the_forward_spread_only_shrinks_the_edge():
    """Adverse quotes cannot improve edge, forward form: the same mid with a
    wider band never scores better, and past the band's edge scores nothing."""
    nets = []
    for half_spread in (0.1, 0.5, 2.5):  # same mid 102.1, widening band
        result = detect_arb013(
            _chain(), _fwd(102.1 - half_spread, 102.1 + half_spread), 100.0, CostConfig(),
        )
        nets.append(result.net_edge_per_share if isinstance(result, Opportunity) else 0.0)
    assert nets[0] > nets[1] > nets[2] == 0.0


def test_arb013_hard_stops_on_the_legs_it_trades():
    stale = detect_arb013(
        _chain(), _fwd(102.0, 102.2, quoted_at="2026-01-05T14:29:00+00:00"), 100.0, CostConfig(),
    )
    assert isinstance(stale, NoOpportunity)
    assert "stale_quote" in stale.reason_codes

    crossed = detect_arb013(_chain(), _fwd(102.4, 102.2), 100.0, CostConfig())
    assert isinstance(crossed, NoOpportunity)
    assert "crossed_market" in crossed.reason_codes

    american = detect_arb013(_chain(style="american"), _fwd(102.0, 102.2), 100.0, CostConfig())
    assert isinstance(american, NoOpportunity)
    assert "non_european_style" in american.reason_codes


def test_arb013_expiry_mismatch_is_a_caller_error():
    with pytest.raises(ValueError, match="expiry mismatch"):
        detect_arb013(_chain(expiry_days=30), _fwd(102.0, 102.2, expiry_days=60), 100.0, CostConfig())


# --- ARB-014: cash-and-carry --------------------------------------------------


def test_arb014_carry_hand_arithmetic():
    """Forward rich vs the carried stock: buy at Sask, sell the forward at
    bid. At r=0, pv_div=0: gross = Fbid - Sask = 102 - 100.1 = 1.9. Long
    stock needs no borrow - classification A."""
    result = detect_arb014(_chain(), _fwd(102.0, 102.2), CostConfig())
    assert isinstance(result, Opportunity)
    assert result.detector_id == "ARB-014"
    assert result.direction == "carry"
    assert result.gross_edge_per_share == pytest.approx(1.9)
    assert result.net_edge_per_share == pytest.approx(1.9 - 0.03)
    assert result.classification == "A"
    assert "strike" not in result.inputs  # no option leg, no strike - by design


def test_arb014_reverse_carry_charges_borrow_explicitly():
    """Forward cheap: short stock at bid, buy the forward at ask. Gross =
    Sbid - Fask = 99.9 - 98 = 1.9, minus an explicit borrow cost
    Sbid * fee * T - classification B, the borrow assumption must hold."""
    result = detect_arb014(_chain(borrow_fee_annual=0.02), _fwd(97.8, 98.0), CostConfig())
    assert isinstance(result, Opportunity)
    assert result.direction == "reverse_carry"
    assert result.gross_edge_per_share == pytest.approx(1.9)
    borrow_cost = 99.9 * 0.02 * (30 / 365)
    assert result.net_edge_per_share == pytest.approx(1.9 - 0.03 - borrow_cost)
    assert result.classification == "B"


def test_arb014_missing_borrow_refuses_the_reverse_direction():
    """Never guessed at zero: an unknown borrow fee makes the reverse
    direction unavailable and says so, exactly as ARB-001's reversal does."""
    result = detect_arb014(_chain(borrow_fee_annual=None), _fwd(97.8, 98.0), CostConfig())
    assert isinstance(result, NoOpportunity)
    assert result.reason_codes == ["no_edge", "missing_borrow"]


def test_arb014_fair_forward_is_silent():
    result = detect_arb014(_chain(borrow_fee_annual=0.01), _fwd(99.9, 100.1), CostConfig())
    assert isinstance(result, NoOpportunity)
    assert result.reason_codes == ["no_edge"]


def test_arb014_dated_pv_div_enters_the_carry():
    """pv_div is a dated PV the carry receives: fair forward drops to
    S - pv_div at r=0, and a quote at the OLD fair level is now rich by
    exactly pv_div."""
    chain = _chain(pv_div=1.0)
    result = detect_arb014(chain, _fwd(99.9, 100.1), CostConfig())
    assert isinstance(result, Opportunity)
    assert result.direction == "carry"
    # gross = Fbid + pv_div - Sask = 99.9 + 1.0 - 100.1 = 0.8
    assert result.gross_edge_per_share == pytest.approx(0.8)


# --- scan_forward -------------------------------------------------------------


def test_scan_forward_pairs_each_forward_with_its_own_expiry():
    chains = [_chain(expiry_days=7), _chain(expiry_days=30)]
    found = scan_forward(chains, [_fwd(102.0, 102.2, expiry_days=30)], CostConfig())
    assert found  # ARB-014 plus ARB-013 at the one strike
    assert {o.inputs["expiry_days"] for o in found} == {30}
    assert {o.detector_id for o in found} == {"ARB-013", "ARB-014"}
    # Sorted by net edge descending, the siblings' convention.
    nets = [o.net_edge_per_share for o in found]
    assert nets == sorted(nets, reverse=True)


def test_scan_forward_no_forwards_is_a_noop():
    assert scan_forward([_chain()], [], CostConfig()) == []


def test_scan_forward_orphan_forward_is_a_caller_error():
    with pytest.raises(ValueError, match="no chain at that expiry"):
        scan_forward([_chain(expiry_days=7)], [_fwd(102.0, 102.2, expiry_days=30)], CostConfig())


def test_scan_forward_duplicate_chain_expiry_is_a_caller_error():
    with pytest.raises(ValueError, match="duplicate chain"):
        scan_forward([_chain(), _chain()], [_fwd(102.0, 102.2)], CostConfig())


def test_mispriced_forward_leaves_the_option_scan_silent():
    """The independence the world's forward variants rest on (§61): a forward
    shifted off fair moves nothing scan_chain prices - the option relations
    are untouched - while scan_forward fires. And it fires with borrow
    unknown, which is exactly why the world refuses to put a fair forward
    beside a borrow_cost trap."""
    chain = _chain(borrow_fee_annual=None)
    assert scan_chain(chain, CostConfig()) == []
    found = scan_forward([chain], [_fwd(102.0, 102.2)], CostConfig())
    assert any(o.detector_id == "ARB-013" and o.classification == "A" for o in found)
