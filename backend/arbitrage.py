"""The Options Arbitrage Library's first detector: ARB-001, European put-call
parity (addendum 27 SS"ARB-001 EUROPEAN PUT-CALL PARITY";
docs/SPEC_RECONCILIATION.md SS39). ARB-002 through ARB-030 are roadmap - not
built here (SS39: "ARB-001 ships ... because the simulation's evaluation loop
needs it as the answer key").

Pure module, no schema, no imports from fi_db or backend.db's Database class -
a detector is "a pure deterministic function over a versioned MarketSnapshot +
ReferenceSnapshot" (addendum 27 SS10), not a database participant. The one
thing it borrows from backend.db is parse_timestamp, for the same reason
canonical.py does: comparing timestamp strings without it is fragile.

## The non-negotiable rule this module exists to enforce

Addendum 27's opening line: "A theoretical violation at mid prices is not
executable arbitrage." Every quote here carries a bid AND an ask; every edge
computed here is computed on the *executable* side (sell at bid, buy at ask),
never at a mid. There is no code path in this module that reads a mid price.

## Data-quality hard stops (addendum 27 SS5)

Checked and collected across all three legs (underlying, call, put) rather
than short-circuited on the first failure, because a caller diagnosing a
refused snapshot wants to know everything wrong with it, not just the first
thing found - the same reasoning reference_data.validate() gives for running
every check rather than stopping at the first failed one.

## Never guessed at zero (addendum 27 SS10: "Never silently substitute missing
reference data with zero")

`borrow_fee_annual: float | None` is the one input this module accepts as
possibly absent. When it is None, the reversal direction is not merely priced
at zero borrow cost - it is unavailable, and 'missing_borrow' says so as a
reason code rather than the reversal edge silently assuming free borrow.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from backend.db import parse_timestamp

DETECTOR_ID = "ARB-001"

# The one style this detector prices. American exercise changes the theorem
# entirely (addendum 27 SS9 critical-review item 2: "applying European parity
# to American options" is a named error) - a non-european snapshot is a hard
# stop, not a detector that tries anyway.
STYLES = ("european",)

# direction -> classification (addendum 27 CLASSIFICATION). Fixed by which
# side of the parity trade is taken, not by anything measured per snapshot:
# conversion (+stock +put -call) is contractually locked once filled for
# European style with deterministic carry inputs (A); reversal (-stock -put
# +call) additionally depends on the borrow assumption holding (B).
_CLASSIFICATION_BY_DIRECTION = {"conversion": "A", "reversal": "B"}

# The hard-stop reason codes, in the fixed order they are checked and
# reported - so two refusals with the same set of problems always print the
# same list, which is what makes a NoOpportunity diffable across runs.
_HARD_STOP_ORDER = ("non_european_style", "stale_quote", "crossed_market", "invalid_bid")


@dataclass(frozen=True)
class Quote:
    """One executable two-sided market: what you could actually sell at
    (bid) and buy at (ask), with the size available at each and when it was
    last seen. `quoted_at` is an ISO timestamp string, parsed with
    backend.db.parse_timestamp - never compared as a raw string."""

    bid: float
    ask: float
    bid_size: float
    ask_size: float
    quoted_at: str


@dataclass(frozen=True)
class ParitySnapshot:
    """One (underlying, strike, expiry) parity triangle at one moment.

    `r` and `pv_div` are typed floats, not Optional - addendum 27 SS10's
    "missing reference data" concern does not apply to them: a snapshot
    without a rate or a dividend PV cannot be constructed at all, so "missing
    r/pv_div" is impossible by construction rather than a runtime check.
    `borrow_fee_annual` is the one carry input that legitimately can be
    unknown (see module docstring)."""

    entity_id: str
    symbol: str
    strike: float
    expiry_days: int
    style: str
    as_of: str
    underlying: Quote
    call: Quote
    put: Quote
    r: float
    pv_div: float
    borrow_fee_annual: float | None
    multiplier: float = 100


@dataclass(frozen=True)
class CostConfig:
    """Disclosed conventions, not measurements - a real cost model belongs to
    the broker/venue integration this repo does not have yet. per_share_fee
    is charged per leg (three legs: stock, call, put - addendum 27 COST MODEL
    lists commissions among the mandatory costs), buffer_per_share is a flat
    safety margin on top (addendum 27 UNIVERSAL PIPELINE step 8: "and
    buffer")."""

    per_share_fee: float = 0.01
    buffer_per_share: float = 0.01

    @property
    def total_per_share(self) -> float:
        """Three legs (stock, call, put) at per_share_fee each, plus the flat
        buffer - the 3-leg convention this detector discloses rather than
        hides."""
        return self.per_share_fee * 3 + self.buffer_per_share


@dataclass(frozen=True)
class Opportunity:
    detector_id: str
    direction: str  # 'conversion' | 'reversal'
    gross_edge_per_share: float
    net_edge_per_share: float
    capacity_units: float
    classification: str  # 'A' | 'B'
    inputs: dict = field(default_factory=dict)


@dataclass(frozen=True)
class NoOpportunity:
    reason_codes: list[str] = field(default_factory=list)


def _leg_hard_stops(quote: Quote, as_of: str, stale_tolerance_seconds: float) -> set[str]:
    """The per-leg checks (stale/crossed/invalid) for one Quote. Style is
    checked once at the snapshot level, not per leg, since it is a property
    of the option contracts, not of any one quote."""
    stops: set[str] = set()
    age_seconds = (parse_timestamp(as_of) - parse_timestamp(quote.quoted_at)).total_seconds()
    if age_seconds > stale_tolerance_seconds:
        stops.add("stale_quote")
    if quote.bid > quote.ask:
        stops.add("crossed_market")
    if quote.bid <= 0:
        stops.add("invalid_bid")
    return stops


def _capacity_units(snapshot: ParitySnapshot, direction: str) -> float:
    """min(call size, put size, underlying size normalized by multiplier)
    for the sides this direction actually trades, floored at 0. Underlying
    size is in shares; option size is in contracts, each worth `multiplier`
    shares - dividing the underlying leg's size by multiplier expresses all
    three legs in the same contract-equivalent unit before taking the min."""
    if direction == "conversion":
        # sell call at bid, buy put at ask, buy stock at ask.
        call_units = snapshot.call.bid_size
        put_units = snapshot.put.ask_size
        underlying_units = snapshot.underlying.ask_size / snapshot.multiplier
    else:
        # buy call at ask, sell put at bid, sell (short) stock at bid.
        call_units = snapshot.call.ask_size
        put_units = snapshot.put.bid_size
        underlying_units = snapshot.underlying.bid_size / snapshot.multiplier
    return max(0.0, min(call_units, put_units, underlying_units))


def detect_arb001(
    snapshot: ParitySnapshot, costs: CostConfig, stale_tolerance_seconds: float = 10.0
) -> Opportunity | NoOpportunity:
    """European put-call parity, executable sides only (addendum 27
    SS"ARB-001").

    C - P = S - PVDiv - PVK.

    Conversion (rich call): sell call at bid, buy put at ask, buy stock at
    ask. Pre-cost edge = Cbid - Pask - Sask + PVDiv + PVK.

    Reversal (rich put/cheap call): buy call at ask, sell put at bid, short
    stock at bid. Pre-cost edge = -Cask + Pbid + Sbid - PVDiv - PVK, minus an
    explicit borrow cost - never assumed free (module docstring).

    Returns the better of the two directions if either clears costs
    strictly positive; otherwise NoOpportunity(['no_edge'], plus
    'missing_borrow' when the only positive direction was an unpriceable
    reversal)."""
    stops: set[str] = set()
    if snapshot.style not in STYLES:
        stops.add("non_european_style")
    for quote in (snapshot.underlying, snapshot.call, snapshot.put):
        stops |= _leg_hard_stops(quote, snapshot.as_of, stale_tolerance_seconds)

    if stops:
        return NoOpportunity(reason_codes=[code for code in _HARD_STOP_ORDER if code in stops])

    t_years = snapshot.expiry_days / 365  # ACT/365 convention, matching pricing.py's own T
    discount_factor = math.exp(-snapshot.r * t_years)
    pvk = snapshot.strike * discount_factor
    costs_total = costs.total_per_share

    conversion_gross = snapshot.call.bid - snapshot.put.ask - snapshot.underlying.ask + snapshot.pv_div + pvk
    conversion_net = conversion_gross - costs_total

    reversal_gross = -snapshot.call.ask + snapshot.put.bid + snapshot.underlying.bid - snapshot.pv_div - pvk
    reversal_pre_borrow_net = reversal_gross - costs_total
    reversal_available = snapshot.borrow_fee_annual is not None
    reversal_net = None
    if reversal_available:
        borrow_cost = snapshot.underlying.bid * snapshot.borrow_fee_annual * t_years
        reversal_net = reversal_pre_borrow_net - borrow_cost

    candidates = []
    if conversion_net > 0:
        candidates.append(("conversion", conversion_net, conversion_gross))
    if reversal_available and reversal_net is not None and reversal_net > 0:
        candidates.append(("reversal", reversal_net, reversal_gross))

    if candidates:
        direction, net_edge, gross_edge = max(candidates, key=lambda c: c[1])
        return Opportunity(
            detector_id=DETECTOR_ID,
            direction=direction,
            gross_edge_per_share=gross_edge,
            net_edge_per_share=net_edge,
            capacity_units=_capacity_units(snapshot, direction),
            classification=_CLASSIFICATION_BY_DIRECTION[direction],
            inputs={
                "strike": snapshot.strike,
                "expiry_days": snapshot.expiry_days,
                "symbol": snapshot.symbol,
                "entity_id": snapshot.entity_id,
                "as_of": snapshot.as_of,
            },
        )

    reasons = ["no_edge"]
    # 'missing_borrow': the reversal direction was never priced (borrow
    # unknown), and it would have been the only positive direction had it
    # been priceable - recorded rather than guessed at zero (module
    # docstring). Conversion already being positive rules this out: a run
    # with a positive conversion edge returned above, so reaching here with
    # conversion_net > 0 is unreachable, but the explicit check keeps the
    # condition legible without relying on that.
    if not reversal_available and conversion_net <= 0 and reversal_pre_borrow_net > 0:
        reasons.append("missing_borrow")
    return NoOpportunity(reason_codes=reasons)
