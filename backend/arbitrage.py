"""The Options Arbitrage Library, Phase 1 (addendum 27 SS11: "Phase 1:
ARB-001/2/3/6/7/8/9/10/11/13 plus architecture, costs, audit and replay").
ARB-001 (European put-call parity) shipped first as the simulation's answer
key (docs/SPEC_RECONCILIATION.md SS39/SS41); this module now also carries
ARB-002, 003, 006, 007, 008, 009, 010 and 011, plus the Phase 2 members
with data to work with: ARB-012 (calendar consistency, cross-expiry, via
its own scan_calendar entry point) and ARB-015/ARB-016 as D-class
Diagnostics under their own schema (the Phase 2 sections at the bottom).
The rest of ARB-013 through ARB-030 stays roadmap.

## ARB-013 is not built

Addendum 27's Phase 1 list names ARB-013 (forward/futures vs synthetic
forward), but no forward/futures instrument exists anywhere in this system -
not in backend/canonical.py's asset classes ("stock", "stock_option"), not in
simulation/parity_world.py's generator, not in any provider. A detector for
an instrument nothing produces and nothing consumes would be exactly the
empty machinery this project refuses elsewhere (docs/SPEC_RECONCILIATION.md
SS39's stance on network source adapters, SS34's stance on Issuer Master).
Left for a future reconciliation entry to record alongside the rest of this
increment.

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

    def for_legs(self, n: int) -> float:
        """n legs at per_share_fee each, plus the flat buffer once - the one
        formula every detector's cost total routes through, so a 2-leg
        vertical, a 3-leg conversion and a 4-leg box never carry independently
        drifting cost arithmetic (Phase 1 note, module docstring)."""
        return self.per_share_fee * n + self.buffer_per_share

    @property
    def total_per_share(self) -> float:
        """ARB-001's 3-leg convention (stock, call, put), kept for existing
        callers - now just for_legs(3)."""
        return self.for_legs(3)


@dataclass(frozen=True)
class Opportunity:
    detector_id: str
    direction: str  # 'conversion' | 'reversal' | the cross-strike and calendar directions
    gross_edge_per_share: float
    net_edge_per_share: float
    capacity_units: float
    classification: str  # 'A' | 'B' | 'C' (addendum 27 CLASSIFICATION)
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


def _capacity(units: list[float]) -> float:
    """min() over already-normalized per-contract-equivalent unit counts,
    floored at 0 - the shared capacity rule every detector below applies to
    however many legs its package actually trades. Options are already in
    contracts; an underlying leg must be pre-divided by multiplier by the
    caller before it goes in this list, so every entry is in the same unit."""
    return max(0.0, min(units)) if units else 0.0


def _capacity_units(snapshot: ParitySnapshot, direction: str) -> float:
    """ARB-001's 3-leg capacity: call size, put size, underlying size
    normalized by multiplier, for the sides `direction` actually trades -
    now just _capacity() over those three normalized sides."""
    if direction == "conversion":
        # sell call at bid, buy put at ask, buy stock at ask.
        units = [snapshot.call.bid_size, snapshot.put.ask_size, snapshot.underlying.ask_size / snapshot.multiplier]
    else:
        # buy call at ask, sell put at bid, sell (short) stock at bid.
        units = [snapshot.call.ask_size, snapshot.put.bid_size, snapshot.underlying.bid_size / snapshot.multiplier]
    return _capacity(units)


def _t_years(expiry_days: int) -> float:
    return expiry_days / 365  # ACT/365 convention, matching simulation/pricing.py's own T


def _discount_factor(r: float, expiry_days: int) -> float:
    """DF = exp(-r*T). Every PVK/PV(width) below routes through this one
    function so the math stays DF-based rather than a shortcut that only
    works for positive rates - addendum 27's ARB-030 names this "the
    framework rule" for every detector, not a special case owned by ARB-010:
    for r<0, DF>1 and PV(width) exceeds the raw width, and the formulas here
    carry that through unchanged."""
    return math.exp(-r * _t_years(expiry_days))


def _pvk(strike: float, r: float, expiry_days: int) -> float:
    return strike * _discount_factor(r, expiry_days)


def _pv_width(k1: float, k2: float, r: float, expiry_days: int) -> float:
    return (k2 - k1) * _discount_factor(r, expiry_days)


def _package_hard_stops(legs: tuple[Quote, ...], as_of: str, style: str, stale_tolerance_seconds: float) -> set[str]:
    """The shared package-level hard-stop check (addendum 27 SS5): style is
    checked once, then _leg_hard_stops is collected over exactly the legs a
    package actually trades - never a leg it does not touch, so a stale or
    crossed quote on an instrument outside this package cannot refuse it
    (e.g. a bad put never blocks a call-only vertical)."""
    stops: set[str] = set()
    if style not in STYLES:
        stops.add("non_european_style")
    for quote in legs:
        stops |= _leg_hard_stops(quote, as_of, stale_tolerance_seconds)
    return stops


def _conversion_gross_edge(snapshot: ParitySnapshot) -> float:
    """CONVERSION's pre-cost edge (addendum 27 SS"ARB-002"): fair cost
    (PVK + pv_div) minus executable cost (Sask + Pask - Cbid). Algebraically
    identical to detect_arb001's conversion_gross - shared here so ARB-001's
    conversion branch and detect_arb002's standalone package route through
    one formula and cannot drift apart (ARB-001 is the parity-relation
    detector; ARB-002 is the same package's standalone entry point)."""
    pvk = _pvk(snapshot.strike, snapshot.r, snapshot.expiry_days)
    executable_cost = snapshot.underlying.ask + snapshot.put.ask - snapshot.call.bid
    fair = pvk + snapshot.pv_div
    return fair - executable_cost


def _reversal_gross_edge(snapshot: ParitySnapshot) -> float:
    """REVERSE CONVERSION's pre-cost, pre-borrow edge (addendum 27
    SS"ARB-003"): initial proceeds (Sbid + Pbid - Cask) minus (PVK + pv_div).
    Shared by detect_arb001's reversal branch and detect_arb003's standalone
    package for the same reason _conversion_gross_edge is shared."""
    pvk = _pvk(snapshot.strike, snapshot.r, snapshot.expiry_days)
    proceeds = snapshot.underlying.bid + snapshot.put.bid - snapshot.call.ask
    return proceeds - pvk - snapshot.pv_div


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

    t_years = _t_years(snapshot.expiry_days)
    costs_total = costs.for_legs(3)

    # Shared with detect_arb002/003 (module-level _conversion_gross_edge /
    # _reversal_gross_edge) so ARB-001's two directions and their standalone
    # package entry points cannot compute different numbers for the same
    # trade.
    conversion_gross = _conversion_gross_edge(snapshot)
    conversion_net = conversion_gross - costs_total

    reversal_gross = _reversal_gross_edge(snapshot)
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


# =============================================================================
# ARB-002 / ARB-003 - the parity package's standalone entry points
# =============================================================================
#
# ARB-001 above is the *parity-relation* detector: it evaluates both
# directions of C - P = S - PVDiv - PVK on one snapshot and returns whichever
# clears costs. ARB-002 (CONVERSION) and ARB-003 (REVERSE CONVERSION) are the
# same two packages addendum 27 gives standalone identities and standalone
# entry points for - a caller who already knows which package they want (not
# "check parity both ways") calls these directly. Both route their pre-cost
# math through _conversion_gross_edge / _reversal_gross_edge above, the same
# functions detect_arb001 uses, so the numbers cannot drift between the two
# names for one package.


def detect_arb002(
    snapshot: ParitySnapshot, costs: CostConfig, stale_tolerance_seconds: float = 10.0
) -> Opportunity | NoOpportunity:
    """CONVERSION (addendum 27 SS"ARB-002"): +stock +put -call, terminal
    payoff K. Executable cost = Sask + Pask - Cbid; fair cost = PVK + pv_div.
    Positive net (after for_legs(3)) -> Opportunity(direction='conversion',
    classification 'A')."""
    stops = _package_hard_stops(
        (snapshot.underlying, snapshot.call, snapshot.put), snapshot.as_of, snapshot.style, stale_tolerance_seconds
    )
    if stops:
        return NoOpportunity(reason_codes=[code for code in _HARD_STOP_ORDER if code in stops])

    gross = _conversion_gross_edge(snapshot)
    net = gross - costs.for_legs(3)
    if net > 0:
        return Opportunity(
            detector_id="ARB-002",
            direction="conversion",
            gross_edge_per_share=gross,
            net_edge_per_share=net,
            capacity_units=_capacity_units(snapshot, "conversion"),
            classification="A",
            inputs={
                "strike": snapshot.strike, "expiry_days": snapshot.expiry_days,
                "symbol": snapshot.symbol, "entity_id": snapshot.entity_id, "as_of": snapshot.as_of,
            },
        )
    return NoOpportunity(reason_codes=["no_edge"])


def detect_arb003(
    snapshot: ParitySnapshot, costs: CostConfig, stale_tolerance_seconds: float = 10.0
) -> Opportunity | NoOpportunity:
    """REVERSE CONVERSION (addendum 27 SS"ARB-003"): -stock -put +call,
    terminal payoff -K. Initial proceeds = Sbid + Pbid - Cask; net = proceeds
    - PVK - pv_div - borrow_cost - for_legs(3), borrow_cost = Sbid *
    borrow_fee_annual * T. Borrow is mandatory (module docstring's "never
    guessed at zero"): with borrow_fee_annual None, a pre-borrow net that
    would have been positive reports ['missing_borrow'] rather than pricing
    at free borrow; otherwise ['no_edge']. Classification 'B' - conditional
    on the borrow assumption holding."""
    stops = _package_hard_stops(
        (snapshot.underlying, snapshot.call, snapshot.put), snapshot.as_of, snapshot.style, stale_tolerance_seconds
    )
    if stops:
        return NoOpportunity(reason_codes=[code for code in _HARD_STOP_ORDER if code in stops])

    t_years = _t_years(snapshot.expiry_days)
    pre_borrow_gross = _reversal_gross_edge(snapshot)
    pre_borrow_net = pre_borrow_gross - costs.for_legs(3)

    if snapshot.borrow_fee_annual is None:
        if pre_borrow_net > 0:
            return NoOpportunity(reason_codes=["missing_borrow"])
        return NoOpportunity(reason_codes=["no_edge"])

    borrow_cost = snapshot.underlying.bid * snapshot.borrow_fee_annual * t_years
    net = pre_borrow_net - borrow_cost
    if net > 0:
        return Opportunity(
            detector_id="ARB-003",
            direction="reversal",
            gross_edge_per_share=pre_borrow_gross,
            net_edge_per_share=net,
            capacity_units=_capacity_units(snapshot, "reversal"),
            classification="B",
            inputs={
                "strike": snapshot.strike, "expiry_days": snapshot.expiry_days,
                "symbol": snapshot.symbol, "entity_id": snapshot.entity_id, "as_of": snapshot.as_of,
            },
        )
    return NoOpportunity(reason_codes=["no_edge"])


# =============================================================================
# ChainSnapshot - the multi-strike shape ARB-006 through ARB-011 need
# =============================================================================
#
# ParitySnapshot above is one (strike, expiry) triangle. Every remaining
# Phase 1 detector compares *across* strikes at one expiry (a box, a vertical,
# a butterfly, monotonicity), so they need the whole strike ladder for one
# underlying/expiry at once - ChainSnapshot is that shape.


@dataclass(frozen=True)
class StrikeQuotes:
    """One strike's call/put pair within a ChainSnapshot."""

    strike: float
    call: Quote
    put: Quote


@dataclass(frozen=True)
class ChainSnapshot:
    """One expiry's full strike ladder for one underlying, at one moment.

    `strikes` must be sorted ascending with no duplicates - validated in
    __post_init__ rather than sorted for the caller, so a caller that hands
    in an unsorted or duplicated ladder finds out immediately rather than
    getting silently-reordered results from a detector that assumed order.
    Field order here (strikes before multiplier) is a dataclass-field-order
    constraint, not a reordering of the spec's prose: a field without a
    default cannot follow one that has one."""

    entity_id: str
    symbol: str
    expiry_days: int
    style: str
    as_of: str
    underlying: Quote
    r: float
    pv_div: float
    borrow_fee_annual: float | None
    strikes: tuple[StrikeQuotes, ...]
    multiplier: float = 100

    def __post_init__(self) -> None:
        if not self.strikes:
            raise ValueError("ChainSnapshot requires at least one strike")
        values = [sq.strike for sq in self.strikes]
        if values != sorted(values):
            raise ValueError(f"ChainSnapshot.strikes must be sorted ascending; got {values!r}")
        if len(set(values)) != len(values):
            raise ValueError(f"ChainSnapshot.strikes must not contain duplicate strikes; got {values!r}")


def _find_strike(chain: ChainSnapshot, strike: float) -> StrikeQuotes:
    for sq in chain.strikes:
        if sq.strike == strike:
            return sq
    raise ValueError(f"strike {strike!r} not found in chain (symbol={chain.symbol!r}, expiry_days={chain.expiry_days})")


def _parity_snapshot_from_chain(chain: ChainSnapshot, sq: StrikeQuotes) -> ParitySnapshot:
    """One (strike, expiry) triangle out of a ChainSnapshot row - what
    scan_chain feeds detect_arb001/detect_arb010 per strike."""
    return ParitySnapshot(
        entity_id=chain.entity_id, symbol=chain.symbol, strike=sq.strike, expiry_days=chain.expiry_days,
        style=chain.style, as_of=chain.as_of, underlying=chain.underlying, call=sq.call, put=sq.put,
        r=chain.r, pv_div=chain.pv_div, borrow_fee_annual=chain.borrow_fee_annual, multiplier=chain.multiplier,
    )


# =============================================================================
# ARB-006 EUROPEAN BOX
# =============================================================================


def detect_arb006(
    chain: ChainSnapshot, k1: float, k2: float, costs: CostConfig, stale_tolerance_seconds: float = 10.0
) -> Opportunity | NoOpportunity:
    """EUROPEAN BOX (addendum 27 SS"ARB-006"), k1<k2: +C1 -C2 +P2 -P1,
    terminal payoff K2-K1.

    Long-box debit = C1ask - C2bid + P2ask - P1bid, compared with
    PV(width); short-box credit = C1bid - C2ask + P2bid - P1ask, compared
    the other way. Best positive wins. Both directions classification 'A'
    (European, no early exercise). Short-box funding/collateral economics
    beyond this module's flat cost model (addendum 27's COST MODEL names
    them explicitly: "collateral/margin funding") are not modeled here - the
    buffer_per_share stands in for them, a disclosed convention, not a
    measurement of real financing cost."""
    if not k1 < k2:
        raise ValueError(f"detect_arb006 requires k1 < k2; got k1={k1!r}, k2={k2!r}")
    sq1, sq2 = _find_strike(chain, k1), _find_strike(chain, k2)

    stops = _package_hard_stops(
        (sq1.call, sq2.call, sq1.put, sq2.put), chain.as_of, chain.style, stale_tolerance_seconds
    )
    if stops:
        return NoOpportunity(reason_codes=[code for code in _HARD_STOP_ORDER if code in stops])

    pv_width = _pv_width(k1, k2, chain.r, chain.expiry_days)
    costs4 = costs.for_legs(4)

    long_debit = sq1.call.ask - sq2.call.bid + sq2.put.ask - sq1.put.bid
    net_long = pv_width - long_debit - costs4

    short_credit = sq1.call.bid - sq2.call.ask + sq2.put.bid - sq1.put.ask
    net_short = short_credit - pv_width - costs4

    candidates = []
    if net_long > 0:
        sides = [sq1.call.ask_size, sq2.call.bid_size, sq2.put.ask_size, sq1.put.bid_size]
        candidates.append(("long_box", net_long, pv_width - long_debit, sides))
    if net_short > 0:
        sides = [sq1.call.bid_size, sq2.call.ask_size, sq2.put.bid_size, sq1.put.ask_size]
        candidates.append(("short_box", net_short, short_credit - pv_width, sides))

    if candidates:
        direction, net, gross, sides = max(candidates, key=lambda c: c[1])
        return Opportunity(
            detector_id="ARB-006", direction=direction, gross_edge_per_share=gross, net_edge_per_share=net,
            capacity_units=_capacity(sides), classification="A",
            inputs={
                "k1": k1, "k2": k2, "expiry_days": chain.expiry_days,
                "symbol": chain.symbol, "entity_id": chain.entity_id, "as_of": chain.as_of,
            },
        )
    return NoOpportunity(reason_codes=["no_edge"])


# =============================================================================
# ARB-007 CALL VERTICAL BOUNDS / ARB-008 PUT VERTICAL BOUNDS
# =============================================================================


def detect_arb007(
    chain: ChainSnapshot, k1: float, k2: float, costs: CostConfig,
    include_monotonicity: bool = True, stale_tolerance_seconds: float = 10.0,
) -> Opportunity | NoOpportunity:
    """CALL VERTICAL BOUNDS (addendum 27 SS"ARB-007"), k1<k2:
    0 <= C1-C2 <= PV(width).

    (a) monotonicity/zero-bound violation: net = C2bid - C1ask - for_legs(2),
    direction 'call_vertical_lower' (buy C1 at ask, sell C2 at bid - a
    nonnegative-payoff package sold for a credit). Only evaluated when
    `include_monotonicity` is True: scan_chain runs this detector with it
    False because ARB-011 (strike monotonicity) already attributes this exact
    package - running both would double-report one violation under two
    detector ids. A standalone caller wanting ARB-007's full spec definition
    (both bound violations) gets it via the default True.

    (b) width violation: net = (C1bid - C2ask) - pv_width - for_legs(2),
    direction 'call_vertical_upper' (sell C1 at bid, buy C2 at ask - a
    credit larger than the max possible width). Best positive wins.
    Classification 'A' throughout (European)."""
    if not k1 < k2:
        raise ValueError(f"detect_arb007 requires k1 < k2; got k1={k1!r}, k2={k2!r}")
    sq1, sq2 = _find_strike(chain, k1), _find_strike(chain, k2)

    stops = _package_hard_stops((sq1.call, sq2.call), chain.as_of, chain.style, stale_tolerance_seconds)
    if stops:
        return NoOpportunity(reason_codes=[code for code in _HARD_STOP_ORDER if code in stops])

    costs2 = costs.for_legs(2)
    pv_width = _pv_width(k1, k2, chain.r, chain.expiry_days)
    candidates = []

    if include_monotonicity:
        gross_lower = sq2.call.bid - sq1.call.ask
        net_lower = gross_lower - costs2
        if net_lower > 0:
            candidates.append(("call_vertical_lower", net_lower, gross_lower, [sq1.call.ask_size, sq2.call.bid_size]))

    gross_upper = (sq1.call.bid - sq2.call.ask) - pv_width
    net_upper = gross_upper - costs2
    if net_upper > 0:
        candidates.append(("call_vertical_upper", net_upper, gross_upper, [sq1.call.bid_size, sq2.call.ask_size]))

    if candidates:
        direction, net, gross, sides = max(candidates, key=lambda c: c[1])
        return Opportunity(
            detector_id="ARB-007", direction=direction, gross_edge_per_share=gross, net_edge_per_share=net,
            capacity_units=_capacity(sides), classification="A",
            inputs={
                "k1": k1, "k2": k2, "expiry_days": chain.expiry_days,
                "symbol": chain.symbol, "entity_id": chain.entity_id, "as_of": chain.as_of,
            },
        )
    return NoOpportunity(reason_codes=["no_edge"])


def detect_arb008(
    chain: ChainSnapshot, k1: float, k2: float, costs: CostConfig,
    include_monotonicity: bool = True, stale_tolerance_seconds: float = 10.0,
) -> Opportunity | NoOpportunity:
    """PUT VERTICAL BOUNDS (addendum 27 SS"ARB-008"), k1<k2:
    0 <= P2-P1 <= PV(width).

    (a) net = P1bid - P2ask - for_legs(2), direction 'put_vertical_lower'
    (sell P1 at bid, buy P2 at ask - nonnegative payoff since puts are
    nondecreasing in strike). Only evaluated when `include_monotonicity` is
    True, for the same reason as detect_arb007's flag: scan_chain leaves this
    to ARB-011 to avoid double-reporting the identical package.

    (b) net = (P2bid - P1ask) - pv_width - for_legs(2), direction
    'put_vertical_upper' (sell P2 at bid, buy P1 at ask). Best positive
    wins. 'A' throughout."""
    if not k1 < k2:
        raise ValueError(f"detect_arb008 requires k1 < k2; got k1={k1!r}, k2={k2!r}")
    sq1, sq2 = _find_strike(chain, k1), _find_strike(chain, k2)

    stops = _package_hard_stops((sq1.put, sq2.put), chain.as_of, chain.style, stale_tolerance_seconds)
    if stops:
        return NoOpportunity(reason_codes=[code for code in _HARD_STOP_ORDER if code in stops])

    costs2 = costs.for_legs(2)
    pv_width = _pv_width(k1, k2, chain.r, chain.expiry_days)
    candidates = []

    if include_monotonicity:
        gross_lower = sq1.put.bid - sq2.put.ask
        net_lower = gross_lower - costs2
        if net_lower > 0:
            candidates.append(("put_vertical_lower", net_lower, gross_lower, [sq1.put.bid_size, sq2.put.ask_size]))

    gross_upper = (sq2.put.bid - sq1.put.ask) - pv_width
    net_upper = gross_upper - costs2
    if net_upper > 0:
        candidates.append(("put_vertical_upper", net_upper, gross_upper, [sq2.put.bid_size, sq1.put.ask_size]))

    if candidates:
        direction, net, gross, sides = max(candidates, key=lambda c: c[1])
        return Opportunity(
            detector_id="ARB-008", direction=direction, gross_edge_per_share=gross, net_edge_per_share=net,
            capacity_units=_capacity(sides), classification="A",
            inputs={
                "k1": k1, "k2": k2, "expiry_days": chain.expiry_days,
                "symbol": chain.symbol, "entity_id": chain.entity_id, "as_of": chain.as_of,
            },
        )
    return NoOpportunity(reason_codes=["no_edge"])


# =============================================================================
# ARB-009 STRIKE CONVEXITY/BUTTERFLY
# =============================================================================


def detect_arb009(
    chain: ChainSnapshot, k1: float, k2: float, k3: float, costs: CostConfig, stale_tolerance_seconds: float = 10.0
) -> Opportunity | NoOpportunity:
    """STRIKE CONVEXITY/BUTTERFLY (addendum 27 SS"ARB-009"), k1<k2<k3,
    general (unequal-spacing) weights: w1 = (k3-k2)/(k3-k1), w3 =
    (k2-k1)/(k3-k1) - the correctly-weighted slope-monotonicity form the
    spec asks for when spacing is not equal; equal spacing (k2-k1 == k3-k2)
    makes w1 = w3 = 0.5, the spec's C1 - 2*C2 + C3 >= 0 divided by 2 (i.e.
    normalized per middle contract rather than per raw butterfly unit).

    Executable cost per unit of the middle contract = w1*C1ask - C2bid +
    w3*C3ask (wings bought at ask, middle sold at bid). A violation is cost
    < 0 beyond costs: net = -cost - for_legs(3). The 3-leg cost convention
    is a disclosed stand-in for the fact this package's wing quantities are
    fractional (w1, w3 contracts per middle contract) rather than a literal
    per-share fee schedule for exactly three contracts - addendum 27's cost
    model does not define fractional-leg fee accounting, so for_legs(3)
    (one count per distinct instrument traded: wing1, middle, wing2) is the
    convention used here, not a measurement.

    Puts mirrored (same w1/w3, same wing-buy/middle-sell structure).
    Directions 'call_butterfly'/'put_butterfly'; best positive wins. 'A'
    (European)."""
    if not (k1 < k2 < k3):
        raise ValueError(f"detect_arb009 requires k1 < k2 < k3; got k1={k1!r}, k2={k2!r}, k3={k3!r}")
    sq1, sq2, sq3 = _find_strike(chain, k1), _find_strike(chain, k2), _find_strike(chain, k3)
    w1 = (k3 - k2) / (k3 - k1)
    w3 = (k2 - k1) / (k3 - k1)
    costs3 = costs.for_legs(3)
    candidates = []

    call_stops = _package_hard_stops(
        (sq1.call, sq2.call, sq3.call), chain.as_of, chain.style, stale_tolerance_seconds
    )
    if not call_stops:
        call_cost = w1 * sq1.call.ask - sq2.call.bid + w3 * sq3.call.ask
        net_call = -call_cost - costs3
        if net_call > 0:
            sides = [sq1.call.ask_size / w1, sq2.call.bid_size, sq3.call.ask_size / w3]
            candidates.append(("call_butterfly", net_call, -call_cost, sides))

    put_stops = _package_hard_stops(
        (sq1.put, sq2.put, sq3.put), chain.as_of, chain.style, stale_tolerance_seconds
    )
    if not put_stops:
        put_cost = w1 * sq1.put.ask - sq2.put.bid + w3 * sq3.put.ask
        net_put = -put_cost - costs3
        if net_put > 0:
            sides = [sq1.put.ask_size / w1, sq2.put.bid_size, sq3.put.ask_size / w3]
            candidates.append(("put_butterfly", net_put, -put_cost, sides))

    if candidates:
        direction, net, gross, sides = max(candidates, key=lambda c: c[1])
        return Opportunity(
            detector_id="ARB-009", direction=direction, gross_edge_per_share=gross, net_edge_per_share=net,
            capacity_units=_capacity(sides), classification="A",
            inputs={
                "k1": k1, "k2": k2, "k3": k3, "expiry_days": chain.expiry_days,
                "symbol": chain.symbol, "entity_id": chain.entity_id, "as_of": chain.as_of,
            },
        )
    if call_stops and put_stops:
        return NoOpportunity(reason_codes=[code for code in _HARD_STOP_ORDER if code in (call_stops | put_stops)])
    return NoOpportunity(reason_codes=["no_edge"])


# =============================================================================
# ARB-010 INTRINSIC/UPPER BOUNDS
# =============================================================================


def detect_arb010(
    snapshot: ParitySnapshot, costs: CostConfig, stale_tolerance_seconds: float = 10.0
) -> Opportunity | NoOpportunity:
    """INTRINSIC/UPPER BOUNDS (addendum 27 SS"ARB-010"), four independent
    checks per (K,T), best positive wins. Each check's hard stops are
    collected only over the legs *that* check trades (module docstring's
    shared package-level rule) - e.g. a stale call cannot block 'put_upper',
    which never touches the call.

    'call_upper': net = Cbid - Sask - for_legs(2) (sell call at bid, buy
    stock at ask - enforces C<=S). 'A' - conservative, since foregone
    dividends on the long stock only help the package, never hurt it.

    'call_lower': net = Sbid - pv_div - PVK - Cask - borrow_cost -
    for_legs(2) (short stock at bid, long call at ask - enforces C >= S -
    PVDiv - PVK). Borrow mandatory: None + an otherwise-positive pre-borrow
    net reports ['missing_borrow'] rather than pricing free borrow. 'B'.

    'put_lower': net = PVK + pv_div - Sask - Pask - for_legs(2) (long stock
    at ask, long put at ask - enforces P >= PVK - (S - PVDiv)). 'A'.

    'put_upper': net = Pbid - PVK - for_legs(1) (sell put at bid alone -
    enforces P <= PVK). 'A'."""
    t_years = _t_years(snapshot.expiry_days)
    pvk = _pvk(snapshot.strike, snapshot.r, snapshot.expiry_days)
    candidates = []
    all_stops: set[str] = set()
    missing_borrow = False
    any_clean_check = False

    stops = _package_hard_stops((snapshot.call, snapshot.underlying), snapshot.as_of, snapshot.style, stale_tolerance_seconds)
    if stops:
        all_stops |= stops
    else:
        any_clean_check = True
        gross = snapshot.call.bid - snapshot.underlying.ask
        net = gross - costs.for_legs(2)
        if net > 0:
            sides = [snapshot.call.bid_size, snapshot.underlying.ask_size / snapshot.multiplier]
            candidates.append(("call_upper", net, gross, "A", sides))

    stops = _package_hard_stops((snapshot.call, snapshot.underlying), snapshot.as_of, snapshot.style, stale_tolerance_seconds)
    if stops:
        all_stops |= stops
    else:
        any_clean_check = True
        pre_borrow_gross = snapshot.underlying.bid - snapshot.pv_div - pvk - snapshot.call.ask
        pre_borrow_net = pre_borrow_gross - costs.for_legs(2)
        if snapshot.borrow_fee_annual is None:
            if pre_borrow_net > 0:
                missing_borrow = True
        else:
            borrow_cost = snapshot.underlying.bid * snapshot.borrow_fee_annual * t_years
            net = pre_borrow_net - borrow_cost
            if net > 0:
                sides = [snapshot.call.ask_size, snapshot.underlying.bid_size / snapshot.multiplier]
                candidates.append(("call_lower", net, pre_borrow_gross, "B", sides))

    stops = _package_hard_stops((snapshot.put, snapshot.underlying), snapshot.as_of, snapshot.style, stale_tolerance_seconds)
    if stops:
        all_stops |= stops
    else:
        any_clean_check = True
        gross = pvk + snapshot.pv_div - snapshot.underlying.ask - snapshot.put.ask
        net = gross - costs.for_legs(2)
        if net > 0:
            sides = [snapshot.underlying.ask_size / snapshot.multiplier, snapshot.put.ask_size]
            candidates.append(("put_lower", net, gross, "A", sides))

    stops = _package_hard_stops((snapshot.put,), snapshot.as_of, snapshot.style, stale_tolerance_seconds)
    if stops:
        all_stops |= stops
    else:
        any_clean_check = True
        gross = snapshot.put.bid - pvk
        net = gross - costs.for_legs(1)
        if net > 0:
            candidates.append(("put_upper", net, gross, "A", [snapshot.put.bid_size]))

    if candidates:
        direction, net, gross, classification, sides = max(candidates, key=lambda c: c[1])
        return Opportunity(
            detector_id="ARB-010", direction=direction, gross_edge_per_share=gross, net_edge_per_share=net,
            capacity_units=_capacity(sides), classification=classification,
            inputs={
                "strike": snapshot.strike, "expiry_days": snapshot.expiry_days,
                "symbol": snapshot.symbol, "entity_id": snapshot.entity_id, "as_of": snapshot.as_of,
            },
        )

    reasons = [code for code in _HARD_STOP_ORDER if code in all_stops]
    if missing_borrow:
        reasons.append("missing_borrow")
    if any_clean_check or not reasons:
        reasons.append("no_edge")
    return NoOpportunity(reason_codes=reasons)


# =============================================================================
# ARB-011 STRIKE MONOTONICITY
# =============================================================================


def detect_arb011(
    chain: ChainSnapshot, k1: float, k2: float, costs: CostConfig, stale_tolerance_seconds: float = 10.0
) -> Opportunity | NoOpportunity:
    """STRIKE MONOTONICITY (addendum 27 SS"ARB-011"), k1<k2 (adjacent or
    any pair): calls nonincreasing in strike, puts nondecreasing.

    Call violation: net = C2bid - C1ask - for_legs(2), direction
    'monotonicity_calls' (buy C1 at ask, sell C2 at bid).
    Put violation: net = P1bid - P2ask - for_legs(2), direction
    'monotonicity_puts' (sell P1 at bid, buy P2 at ask).
    'A' throughout. These are the same two packages detect_arb007's (a)
    branch and detect_arb008's (a) branch compute (module docstrings on
    those detectors) - scan_chain runs this detector for exactly that reason
    and calls 007/008 with include_monotonicity=False, so the scan attributes
    a zero-bound violation to ARB-011 once rather than reporting it under
    three detector ids.

    Calls and puts are hard-stop-checked independently, each over only the
    two legs its own package trades, so a stale/crossed leg on one side
    never blocks evaluating the other."""
    if not k1 < k2:
        raise ValueError(f"detect_arb011 requires k1 < k2; got k1={k1!r}, k2={k2!r}")
    sq1, sq2 = _find_strike(chain, k1), _find_strike(chain, k2)
    costs2 = costs.for_legs(2)
    candidates = []

    call_stops = _package_hard_stops((sq1.call, sq2.call), chain.as_of, chain.style, stale_tolerance_seconds)
    if not call_stops:
        gross = sq2.call.bid - sq1.call.ask
        net = gross - costs2
        if net > 0:
            candidates.append(("monotonicity_calls", net, gross, [sq1.call.ask_size, sq2.call.bid_size]))

    put_stops = _package_hard_stops((sq1.put, sq2.put), chain.as_of, chain.style, stale_tolerance_seconds)
    if not put_stops:
        gross = sq1.put.bid - sq2.put.ask
        net = gross - costs2
        if net > 0:
            candidates.append(("monotonicity_puts", net, gross, [sq1.put.bid_size, sq2.put.ask_size]))

    if candidates:
        direction, net, gross, sides = max(candidates, key=lambda c: c[1])
        return Opportunity(
            detector_id="ARB-011", direction=direction, gross_edge_per_share=gross, net_edge_per_share=net,
            capacity_units=_capacity(sides), classification="A",
            inputs={
                "k1": k1, "k2": k2, "expiry_days": chain.expiry_days,
                "symbol": chain.symbol, "entity_id": chain.entity_id, "as_of": chain.as_of,
            },
        )
    if call_stops and put_stops:
        return NoOpportunity(reason_codes=[code for code in _HARD_STOP_ORDER if code in (call_stops | put_stops)])
    return NoOpportunity(reason_codes=["no_edge"])


# =============================================================================
# scan_chain - the library's chain-level entry point
# =============================================================================


def _leg_signature(
    direction: str, k1: float | None, k2: float | None = None, k3: float | None = None
) -> frozenset:
    """A package's canonical leg signature - frozenset of (instrument, side,
    strike-or-None, weight) tuples - keyed off `direction` and the strikes
    involved rather than off which detector function produced the
    Opportunity. Two different detector calls that happen to describe the
    identical trade (e.g. a hypothetical ARB-007 run with
    include_monotonicity=True alongside ARB-011) collide to one signature by
    design; scan_chain keeps the first Opportunity found for a signature and
    discards the rest."""
    if direction in ("call_vertical_lower", "monotonicity_calls"):
        return frozenset({("call", "long", k1, 1.0), ("call", "short", k2, 1.0)})
    if direction == "call_vertical_upper":
        return frozenset({("call", "short", k1, 1.0), ("call", "long", k2, 1.0)})
    if direction in ("put_vertical_lower", "monotonicity_puts"):
        return frozenset({("put", "short", k1, 1.0), ("put", "long", k2, 1.0)})
    if direction == "put_vertical_upper":
        return frozenset({("put", "short", k2, 1.0), ("put", "long", k1, 1.0)})
    if direction == "long_box":
        return frozenset({
            ("call", "long", k1, 1.0), ("call", "short", k2, 1.0),
            ("put", "long", k2, 1.0), ("put", "short", k1, 1.0),
        })
    if direction == "short_box":
        return frozenset({
            ("call", "short", k1, 1.0), ("call", "long", k2, 1.0),
            ("put", "short", k2, 1.0), ("put", "long", k1, 1.0),
        })
    if direction == "call_butterfly":
        w1, w3 = (k3 - k2) / (k3 - k1), (k2 - k1) / (k3 - k1)
        return frozenset({("call", "long", k1, w1), ("call", "short", k2, 1.0), ("call", "long", k3, w3)})
    if direction == "put_butterfly":
        w1, w3 = (k3 - k2) / (k3 - k1), (k2 - k1) / (k3 - k1)
        return frozenset({("put", "long", k1, w1), ("put", "short", k2, 1.0), ("put", "long", k3, w3)})
    if direction == "conversion":
        return frozenset({("stock", "long", None, 1.0), ("put", "long", k1, 1.0), ("call", "short", k1, 1.0)})
    if direction == "reversal":
        return frozenset({("stock", "short", None, 1.0), ("put", "short", k1, 1.0), ("call", "long", k1, 1.0)})
    if direction == "call_upper":
        return frozenset({("call", "short", k1, 1.0), ("stock", "long", None, 1.0)})
    if direction == "call_lower":
        return frozenset({("stock", "short", None, 1.0), ("call", "long", k1, 1.0)})
    if direction == "put_lower":
        return frozenset({("stock", "long", None, 1.0), ("put", "long", k1, 1.0)})
    if direction == "put_upper":
        return frozenset({("put", "short", k1, 1.0)})
    raise ValueError(f"no leg signature defined for direction {direction!r}")  # pragma: no cover - exhaustive above


def scan_chain(
    chain: ChainSnapshot, costs: CostConfig = CostConfig(), stale_tolerance_seconds: float = 10.0
) -> list[Opportunity]:
    """The library's chain-level entry point (addendum 27 Phase 1): run
    every Phase 1 chain-shaped detector over one ChainSnapshot and return
    the deduplicated, edge-sorted opportunities.

    Per strike: ARB-001 (via a ParitySnapshot built from the chain's own
    fields) and ARB-010. ARB-002/003 are NOT also run here - they are the
    same conversion/reversal package as ARB-001 under standalone names
    (module docstring above), so running them here would just report ARB-001's
    own findings again under two more detector ids.

    Over every pair k1<k2: ARB-006, ARB-007(include_monotonicity=False),
    ARB-008(include_monotonicity=False), ARB-011 - the flags avoid ARB-011
    and 007/008's dropped (a) branches double-reporting one package (see
    detect_arb007's docstring).

    Over every triple k1<k2<k3: ARB-009.

    Hard-stopped candidates are silently skipped here (NoOpportunity is
    simply not appended) - the per-detector functions above still return
    their NoOpportunity/reason_codes for a caller that invokes them
    directly; only the scan discards the refusal reason.

    Deduplication: identical packages (by _leg_signature) collapse to the
    first one found, in the strike/pair/triple iteration order above.
    Results are sorted by net_edge_per_share, descending."""
    found: list[Opportunity] = []
    seen: set[frozenset] = set()

    def _add(result: Opportunity | NoOpportunity) -> None:
        if not isinstance(result, Opportunity):
            return
        k1 = result.inputs.get("k1", result.inputs.get("strike"))
        k2 = result.inputs.get("k2")
        k3 = result.inputs.get("k3")
        sig = _leg_signature(result.direction, k1, k2, k3)
        if sig in seen:
            return
        seen.add(sig)
        found.append(result)

    for sq in chain.strikes:
        snapshot = _parity_snapshot_from_chain(chain, sq)
        _add(detect_arb001(snapshot, costs, stale_tolerance_seconds))
        _add(detect_arb010(snapshot, costs, stale_tolerance_seconds))

    strikes = [sq.strike for sq in chain.strikes]
    for i in range(len(strikes)):
        for j in range(i + 1, len(strikes)):
            k1, k2 = strikes[i], strikes[j]
            _add(detect_arb006(chain, k1, k2, costs, stale_tolerance_seconds))
            _add(detect_arb007(chain, k1, k2, costs, include_monotonicity=False, stale_tolerance_seconds=stale_tolerance_seconds))
            _add(detect_arb008(chain, k1, k2, costs, include_monotonicity=False, stale_tolerance_seconds=stale_tolerance_seconds))
            _add(detect_arb011(chain, k1, k2, costs, stale_tolerance_seconds))

    for i in range(len(strikes)):
        for j in range(i + 1, len(strikes)):
            for k in range(j + 1, len(strikes)):
                _add(detect_arb009(chain, strikes[i], strikes[j], strikes[k], costs, stale_tolerance_seconds))

    found.sort(key=lambda o: o.net_edge_per_share, reverse=True)
    return found


# =============================================================================
# ARB-012 MATURITY/CALENDAR CONSISTENCY (addendum 27 §11 Phase 2)
# =============================================================================
#
# The spec's own warning is the design: "Never hard-code 'longer expiry always
# costs more.' Dividends, rates ... can invalidate it. Apply only proven
# dominance rules." What is actually provable depends on what the snapshot
# can promise about dividends - and pv_div promises a PV, not a *model*
# (deterministic cash vs proportional yield), so each side gets the rule
# that survives every admissible nonnegative dividend process:
#
# PUTS - proven unconditionally. Long P(K2,T2), short P(K1,T1). At T1 the
# short leg settles at (K1-S1)+ and the far put's model-free European lower
# bound is K2*DF(T1,T2) - S1 (dividends only lower the future stock, which
# helps a put, so ignoring them keeps the bound valid under ANY dividend
# process). Worst shortfall, over all S1: max(0, K1 - K2*DF(T1,T2)) -
# constant in S1 - which discounted to today gives
#
#       slack_p = max(0, K1*DF1 - K2*DF2)
#
# with DF_i each chain's own discount factor. No dividend credit is taken:
# under a proportional yield the dividend contribution vanishes exactly in
# the states (S1 -> 0) where the put bound binds, so crediting PVDiv here
# was a real false-positive generator - found by the clean-world property
# test, not by inspection (SPEC_RECONCILIATION §56).
#
# CALLS - proven only on a dividend-free underlying. The far call's bound at
# T1 is S1 - PVDiv@T1 - K2*DF(T1,T2), and under a proportional yield
# PVDiv@T1 grows with S1, making the shortfall UNBOUNDED in S1 - no
# call calendar dominance exists from prices and a PV alone. When the chain
# declares no dividends at all through the far expiry (far.pv_div == 0),
# the bound is S1 - K2*DF(T1,T2), the shortfall against (S1-K1)+ caps at
# max(0, K2*DF(T1,T2) - K1), and discounting gives
#
#       slack_c = max(0, K2*DF2 - K1*DF1)
#
# which also covers negative rates (ARB-030: DF2 > DF1 makes it positive).
# A dividend-bearing chain simply has no call-side rule to violate - the
# spec's "otherwise classify as D" arm, which stays with the reference-data
# consumer named in §56 rather than being faked here.
#
# Classification C, not A: the violation is a genuine no-arbitrage breach
# locked at the initial fills *as a bound*, but monetizing it at T1 requires
# either liquidating the far leg at its no-arbitrage value or re-hedging the
# expiry settlement into a stock-and-carry package - addendum 27's own C
# ("no-arbitrage violation with ... settlement path complexity"). Nothing
# here pretends the T1 leg's realization is a contractual cash flow.


def _pair_coherence(near: ChainSnapshot, far: ChainSnapshot) -> None:
    """Structural validation for a calendar pair - caller errors, raised
    rather than returned as reason codes, the same split _find_strike makes:
    a data-quality problem is a NoOpportunity, but comparing two different
    underlyings (or the same expiry twice) is a bug at the call site."""
    if near.entity_id != far.entity_id or near.symbol != far.symbol:
        raise ValueError(
            f"calendar pair must share an underlying; got {near.symbol!r}/{far.symbol!r}"
        )
    if near.style != far.style:
        raise ValueError(f"calendar pair must share a style; got {near.style!r}/{far.style!r}")
    if near.as_of != far.as_of:
        raise ValueError(
            f"calendar pair must be snapped at one moment; got {near.as_of!r}/{far.as_of!r}"
        )
    if near.multiplier != far.multiplier:
        raise ValueError(
            f"calendar pair must share a multiplier; got {near.multiplier!r}/{far.multiplier!r}"
        )
    if not near.expiry_days < far.expiry_days:
        raise ValueError(
            f"calendar pair requires near.expiry_days < far.expiry_days; "
            f"got {near.expiry_days} and {far.expiry_days}"
        )


def _calendar_slacks(near: ChainSnapshot, far: ChainSnapshot, k1: float, k2: float) -> tuple[float | None, float]:
    """(slack_c, slack_p) per the derivation above; slack_c is None when no
    proven call-side rule exists (the chain carries dividends). Each chain's
    own r prices its own DF, so a term structure (different r per expiry)
    flows through without a flat-rate assumption; the ARB-030 discipline
    (DF-based, valid for negative rates) is inherited from _discount_factor.

    Deliberately no dividend credit anywhere: pv_div is a PV, not a dividend
    *model*, and the credit is only valid for deterministic cash dividends -
    the clean-world property test caught the yield-model counterexample
    (§56). What is proven is kept; what is not is refused."""
    df1 = _discount_factor(near.r, near.expiry_days)
    df2 = _discount_factor(far.r, far.expiry_days)
    slack_p = max(0.0, k1 * df1 - k2 * df2)
    slack_c = max(0.0, k2 * df2 - k1 * df1) if far.pv_div == 0.0 else None
    return slack_c, slack_p


def detect_arb012(
    near: ChainSnapshot, far: ChainSnapshot, k1: float, k2: float,
    costs: CostConfig, stale_tolerance_seconds: float = 10.0,
) -> Opportunity | NoOpportunity:
    """One calendar package: strike k1 at the near expiry against strike k2
    at the far expiry, both option types, best violation wins (the ARB-011
    shape, across expiries instead of across strikes).

    Put violation ('put_calendar'): sell the near put at bid, buy the far
    put at ask; gross = P1bid - P2ask - slack_p, the size of the
    no-arbitrage breach itself, with the slack reserved before any edge is
    claimed. Call violation ('call_calendar') symmetric - but only on a
    dividend-free chain, because that is the only case a call-side rule is
    proven for (module comment above); a dividend-bearing chain's call
    inversion is not scored at all rather than scored under an unproven
    theorem.

    Calls and puts are hard-stop-checked independently over only the two
    legs each package trades - the underlying is not a leg here and is
    deliberately not checked."""
    _pair_coherence(near, far)
    sq1, sq2 = _find_strike(near, k1), _find_strike(far, k2)
    slack_c, slack_p = _calendar_slacks(near, far, k1, k2)
    costs2 = costs.for_legs(2)
    candidates = []

    call_stops = _package_hard_stops((sq1.call, sq2.call), near.as_of, near.style, stale_tolerance_seconds)
    if not call_stops and slack_c is not None:
        gross = sq1.call.bid - sq2.call.ask - slack_c
        net = gross - costs2
        if net > 0:
            candidates.append(("call_calendar", net, gross, slack_c, [sq1.call.bid_size, sq2.call.ask_size]))

    put_stops = _package_hard_stops((sq1.put, sq2.put), near.as_of, near.style, stale_tolerance_seconds)
    if not put_stops:
        gross = sq1.put.bid - sq2.put.ask - slack_p
        net = gross - costs2
        if net > 0:
            candidates.append(("put_calendar", net, gross, slack_p, [sq1.put.bid_size, sq2.put.ask_size]))

    if candidates:
        direction, net, gross, slack, sides = max(candidates, key=lambda c: c[1])
        return Opportunity(
            detector_id="ARB-012", direction=direction, gross_edge_per_share=gross, net_edge_per_share=net,
            capacity_units=_capacity(sides), classification="C",
            inputs={
                "k1": k1, "k2": k2,
                "expiry_days": near.expiry_days, "expiry2_days": far.expiry_days,
                "slack_per_share": slack,
                "symbol": near.symbol, "entity_id": near.entity_id, "as_of": near.as_of,
            },
        )
    if call_stops and put_stops:
        return NoOpportunity(reason_codes=[code for code in _HARD_STOP_ORDER if code in (call_stops | put_stops)])
    return NoOpportunity(reason_codes=["no_edge"])


def scan_calendar(
    chains: list[ChainSnapshot] | tuple[ChainSnapshot, ...],
    costs: CostConfig = CostConfig(),
    stale_tolerance_seconds: float = 10.0,
) -> list[Opportunity]:
    """The cross-expiry entry point, parallel to scan_chain: every ordered
    expiry pair, every (k1, k2) strike pair across it, ARB-012 on each.
    Hard-stopped and no-edge packages are silently skipped, matching
    scan_chain's own convention; results sorted by net edge descending.

    Fewer than two chains is a legitimate no-op (a single-expiry world has
    no calendar to check), but two chains at the same expiry for the same
    underlying is a caller error surfaced by _pair_coherence."""
    ordered = sorted(chains, key=lambda c: c.expiry_days)
    found: list[Opportunity] = []
    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            near, far = ordered[i], ordered[j]
            for sq1 in near.strikes:
                for sq2 in far.strikes:
                    result = detect_arb012(near, far, sq1.strike, sq2.strike, costs, stale_tolerance_seconds)
                    if isinstance(result, Opportunity):
                        found.append(result)
    found.sort(key=lambda o: o.net_edge_per_share, reverse=True)
    return found


# --- Phase 2 diagnostics: ARB-015 / ARB-016 (addendum 27 §11 Phase 2) -------
#
# The first Phase 2 members that have data to work with in this system.
# ARB-014 (cash-and-carry) needs the same forward/futures instruments ARB-013
# does; ARB-012 needs a second expiry no snapshot carries; 017/019/020 need
# American worlds STYLES refuses. What remains buildable is the pair the spec
# itself marks as *signals*: option-implied dividend (015) and implied
# borrow/financing basis (016) — "difference alone is not arbitrage" (015),
# "usually B/D rather than A" (016).
#
# Hence a separate schema. Addendum 27 §8 requires "schema-level separation
# of D from arbitrage": a Diagnostic is not an Opportunity, has no edge, no
# direction, no capacity, and no path into scan_chain's results — a consumer
# that wants diagnostics asks diagnose_chain for them. What a diagnostic
# reports is an *executable band*: the interval of values consistent with
# actual bid/ask quotes. Only a declared input lying outside that band is a
# signal at all — a mid-price gap smaller than the spread is the market
# saying nothing, and reporting it would be the mid-price error in
# diagnostic clothing.


@dataclass(frozen=True)
class Diagnostic:
    """A D-class signal: a declared reference input inconsistent with what
    executable quotes imply. Never tradeable as-is (the spec's own words for
    015/016); `gap` is the distance from the declared value to the nearest
    edge of the implied band, so a consumer can rank by how far outside the
    market's own uncertainty the declaration sits."""

    detector_id: str
    strike: float
    implied_low: float
    implied_high: float
    declared: float
    gap: float
    classification: str = "D"
    inputs: dict = field(default_factory=dict)


def _implied_pv_div_band(snapshot: ParitySnapshot) -> tuple[float, float]:
    """PVDiv = S - PVK - (C-P), evaluated at executable extremes.

    (C-P) ranges from Cbid-Pask to Cask-Pbid and S from Sbid to Sask, so the
    implied-dividend band is [Sbid - PVK - (Cask-Pbid), Sask - PVK - (Cbid-Pask)].
    Wider spreads widen the band — more quote uncertainty can only ever
    weaken a diagnostic, never manufacture one."""
    pvk = _pvk(snapshot.strike, snapshot.r, snapshot.expiry_days)
    low = snapshot.underlying.bid - pvk - (snapshot.call.ask - snapshot.put.bid)
    high = snapshot.underlying.ask - pvk - (snapshot.call.bid - snapshot.put.ask)
    return low, high


def detect_arb015(
    snapshot: ParitySnapshot, stale_tolerance_seconds: float = 10.0
) -> Diagnostic | NoOpportunity:
    """ARB-015: option-implied dividend versus the declared distribution.

    A Diagnostic only when the declared pv_div lies outside the entire
    executable band — the spec's list of innocent explanations (borrow,
    funding, taxes, stale quotes) is exactly why the band, not a mid-point
    difference, is the test, and why the result is D rather than an
    opportunity: nothing here constructs the "complete locking package" §
    ARB-015 requires before elevation."""
    stops = _package_hard_stops(
        (snapshot.underlying, snapshot.call, snapshot.put),
        snapshot.as_of, snapshot.style, stale_tolerance_seconds,
    )
    if stops:
        return NoOpportunity(sorted(stops))

    low, high = _implied_pv_div_band(snapshot)
    if low <= snapshot.pv_div <= high:
        return NoOpportunity(["within_executable_band"])
    gap = (low - snapshot.pv_div) if snapshot.pv_div < low else (snapshot.pv_div - high)
    return Diagnostic(
        detector_id="ARB-015", strike=snapshot.strike,
        implied_low=low, implied_high=high, declared=snapshot.pv_div, gap=gap,
        inputs={"r": snapshot.r, "expiry_days": snapshot.expiry_days},
    )


def detect_arb016(
    snapshot: ParitySnapshot, stale_tolerance_seconds: float = 10.0
) -> Diagnostic | NoOpportunity:
    """ARB-016: implied financing versus the declared rate and borrow.

    Inverts parity for the discount factor — DF_implied = (S - PVDiv - (C-P))/K
    — at executable extremes, converts to a continuously-compounded rate band,
    and compares the declared r against it. The borrow fee is required
    reference data here, not because the arithmetic needs it but because the
    *interpretation* does: an implied-financing basis on a stock whose borrow
    state is unknown cannot distinguish "mispriced" from "hard to borrow",
    which is precisely the spec's warning. Missing borrow is a refusal
    (§10: never silently substitute zero). `inputs['borrow_explains_gap']`
    reports whether r minus the declared borrow fee falls inside the band —
    the B-versus-D distinction the spec draws, carried as evidence rather
    than as a different class, since no locking package exists either way."""
    stops = _package_hard_stops(
        (snapshot.underlying, snapshot.call, snapshot.put),
        snapshot.as_of, snapshot.style, stale_tolerance_seconds,
    )
    if snapshot.borrow_fee_annual is None:
        stops = set(stops) | {"missing_borrow"}
    if stops:
        return NoOpportunity(sorted(stops))

    t = _t_years(snapshot.expiry_days)
    # DF at executable extremes: the small DF comes from the high (C-P) side.
    df_low = (snapshot.underlying.bid - snapshot.pv_div - (snapshot.call.ask - snapshot.put.bid)) / snapshot.strike
    df_high = (snapshot.underlying.ask - snapshot.pv_div - (snapshot.call.bid - snapshot.put.ask)) / snapshot.strike
    if df_low <= 0 or df_high <= 0:
        # A non-positive implied DF is not a financing signal, it is a broken
        # input (deep-ITM quotes crossing the dividend-adjusted spot).
        return NoOpportunity(["implied_df_not_positive"])

    r_low = -math.log(df_high) / t
    r_high = -math.log(df_low) / t
    if r_low <= snapshot.r <= r_high:
        return NoOpportunity(["within_executable_band"])
    gap = (r_low - snapshot.r) if snapshot.r < r_low else (snapshot.r - r_high)
    borrow_adjusted = snapshot.r - snapshot.borrow_fee_annual
    return Diagnostic(
        detector_id="ARB-016", strike=snapshot.strike,
        implied_low=r_low, implied_high=r_high, declared=snapshot.r, gap=gap,
        inputs={
            "borrow_fee_annual": snapshot.borrow_fee_annual,
            "borrow_explains_gap": r_low <= borrow_adjusted <= r_high,
            "expiry_days": snapshot.expiry_days,
        },
    )


def diagnose_chain(
    chain: ChainSnapshot, stale_tolerance_seconds: float = 10.0
) -> list[Diagnostic]:
    """The diagnostics entry point, parallel to scan_chain and deliberately
    not part of it (§8's schema separation): ARB-015 and ARB-016 over every
    strike, hard-stopped and within-band strikes silently skipped, sorted by
    gap descending so the least-explainable inconsistency leads."""
    found: list[Diagnostic] = []
    for sq in chain.strikes:
        snapshot = _parity_snapshot_from_chain(chain, sq)
        for result in (
            detect_arb015(snapshot, stale_tolerance_seconds),
            detect_arb016(snapshot, stale_tolerance_seconds),
        ):
            if isinstance(result, Diagnostic):
                found.append(result)
    found.sort(key=lambda d: d.gap, reverse=True)
    return found
