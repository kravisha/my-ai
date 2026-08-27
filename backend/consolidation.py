"""Several sources, one view (TASK_QUEUE TQ-78; addendum 9 §3,
docs/SPEC_RECONCILIATION.md §112).

Addendum 9 §3, canonical and never built:

> *"Normalize and reconcile positions sufficiently to analyze the portfolio as a
> whole. Combine duplicate or overlapping exposures where appropriate."*

And the owner, on what the product is (§112):

> *"Client needs consolidated portfolio analysis that is usually not provided by
> discount brokers."*

**A broker can already show a client their own account.** The consolidation is
the thing being sold, and until now every caller in this system handled exactly
one source.

## What "combine where appropriate" turns out to mean

The word doing the work in addendum 9 §3 is *appropriate*, and most of this
module is the four places it turns out not to be.

### A merge is by symbol; a disagreement about the symbol is not a merge

Two sources reporting `SYN1` hold one security between them. Two sources
disagreeing about what `SYN1` **is** — one calling it a stock, the other an ETF —
are not describing one position from two angles; one of them is wrong, and this
module does not know which.

So the position merges and the class becomes `unknown`, with the disagreement
reported. Picking the first, the commonest, or the more specific would be the
fabrication §100 refused when TQ-45a's rename declined to map `EQUITY` to a house
code: *"this migration will not choose for you."*

### A long at one broker and a short at another do not net to nothing

They offset economically, and reporting `0` would be arithmetically defensible
and materially false. Two real positions exist, at two brokers, with two cost
bases and — where anybody cares — different tax treatment and different
counterparty risk. A client who sees `0` cannot tell that from holding neither.

So `net_quantity` is reported **and the legs are kept**. This is §101's rule
about short positions one level up: *counted but not weighted*, because a number
that erases what it summarises is worse than no number.

### A consolidated view is as fresh as its **oldest** source

Sources are fetched at different moments. A view built from one broker at 09:00
and another at 15:00 is current as of neither, and reporting the newest timestamp
would be a freshness claim about data that does not have it — §17's *"do not
silently claim it is current"*, arriving in the one place where two honest
timestamps make a dishonest third.

`as_of` is therefore the **minimum** across contributing sources, and
`stale_sources` names the ones lagging behind.

### A partial consolidation is not a portfolio

If three sources are asked for and two answer, what comes back is not the
client's portfolio — it is most of it, and the missing part is invisible in every
number derived from it. Concentration computed over two accounts of three will
understate concentration if the third holds more of the same thing, and *nothing
in the arithmetic reveals that*.

So a failure is carried into the result rather than raised past it: `complete` is
False, `failed_sources` names them with their reasons, and every caller has to
decide what to do about it. **Refusing outright would be wrong too** — a client
whose third broker is down still deserves to see the two that answered, provided
they are told what they are looking at.

## What it does not do

No prices, no valuation, no greeks. Positions come from sources and prices come
from the market data store (§113), and this module joins nothing — it produces
the consolidated *positions* that a valuation would later be computed over.

Nothing is stored. This returns a value; the caller holds it for the life of a
session and discards it (§111, §115).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend import holdings as holdings_module
from backend import portfolio_providers


@dataclass(frozen=True)
class SourceAnswer:
    """What one source returned, and how much it said it holds (TQ-80).

    A bare list of holdings cannot express the difference between *"here is the
    account"* and *"here is some of the account"*, and that difference is the
    whole of the silently-partial failure. So an answer carries the account's own
    assertion alongside the rows.

    `expected_positions` is `None` when the source did not say — **unknown, and
    never "therefore complete"**. Defaulting an absence to the favourable value
    is exactly what §100 and §104 forbid, and it was the actual defect behind
    `portfolio.detects_a_silently_partial_account`.

    A plain list is still accepted by `consolidate` and means the same as an
    answer with no assertion, so nothing that already worked had to change to
    keep working - it simply stops claiming to be complete."""

    holdings: tuple
    expected_positions: int | None = None

    @property
    def confirmed(self) -> bool:
        return self.expected_positions is not None

    @property
    def short_by(self) -> int:
        if not self.confirmed:
            return 0
        return max(0, self.expected_positions - len(self.holdings))


class ConsolidationRefused(ValueError):
    """A consolidation this module will not perform, with the reason.

    Distinct from a source *failing*, which is carried in the result: this is a
    request that cannot be answered at all, and the only one today is the same
    source twice."""


@dataclass(frozen=True)
class Lot:
    """One source's contribution to a consolidated position.

    Kept rather than summed away, which is the whole design. A consolidated
    number that cannot be taken apart again is one a client cannot check against
    their own statements - and checking against their own statements is what a
    client with several brokers will do first."""

    source: str
    quantity: float
    average_cost: float | None
    as_of: str
    asset_class: str


@dataclass(frozen=True)
class Position:
    """One security, across every source that reports it."""

    symbol: str
    asset_class: str
    net_quantity: float
    long_quantity: float
    short_quantity: float
    average_cost: float | None
    lots: tuple[Lot, ...]
    sources: tuple[str, ...]
    class_conflict: tuple[str, ...] = ()
    cost_basis_complete: bool = True

    @property
    def is_offsetting(self) -> bool:
        """Held long at one source and short at another.

        Named rather than left for a caller to derive from two quantities,
        because the derivation is the kind somebody gets wrong once and then
        copies."""
        return self.long_quantity > 0 and self.short_quantity < 0


@dataclass(frozen=True)
class Consolidated:
    """The whole view, and everything a caller needs to know about how good it
    is."""

    positions: tuple[Position, ...]
    sources: tuple[str, ...]
    as_of: str | None
    complete: bool
    failed_sources: tuple[dict, ...] = ()
    # Answered, and returned fewer positions than the account says it holds.
    # **Detected rather than suspected** - the account's own assertion disagrees
    # with what arrived.
    incomplete_sources: tuple[dict, ...] = ()
    # Answered, and would not say how much it holds. Not a failure and not a
    # clean bill of health: completeness is *unknown*, which is a third thing.
    unconfirmed_sources: tuple[str, ...] = ()
    stale_sources: tuple[str, ...] = ()
    conflicts: tuple[dict, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    def holdings(self) -> list[portfolio_providers.Holding]:
        """The consolidated positions in the canonical shape, so the existing
        analysis can read them.

        This is what makes `holdings.concentration` work over a consolidated
        portfolio without a line of change — the same property §101 built it for,
        collected one more time. The analyser still has no idea where its input
        came from, and now "where" is several places.

        Offsetting positions are emitted at their **net** quantity, because
        weights by cost over a long and a short of the same security would double
        count exposure the client does not have. `Consolidated.positions` keeps
        the legs for anybody who needs them, which is why flattening here is safe
        rather than lossy."""
        return [
            portfolio_providers.Holding(
                symbol=position.symbol,
                quantity=position.net_quantity,
                average_cost=position.average_cost,
                asset_class=position.asset_class,
                as_of=min(lot.as_of for lot in position.lots if lot.as_of) if any(
                    lot.as_of for lot in position.lots) else "",
                note=None,
                acquired_on=None,
                simulated=False,
            )
            for position in self.positions
            if position.net_quantity != 0
        ]


def _weighted_average_cost(lots) -> tuple[float | None, bool]:
    """Quantity-weighted average cost across the lots that have one.

    Returns `(cost, complete)`. **Weighted by quantity rather than averaged**,
    because two lots of one security bought in different sizes do not contribute
    equally to what the client paid, and a plain mean would be a plausible number
    that is wrong.

    Only long lots count. A short's `average_cost` is a credit received rather
    than an amount paid (§101), so folding it in would produce a blended figure
    that is neither.

    `complete` is False when any long lot has no cost, and a caller must not
    treat the number as the whole cost basis - it is the cost of the part that
    is known, which is a different fact."""
    priced = [lot for lot in lots if lot.quantity > 0 and lot.average_cost is not None]
    unpriced = [lot for lot in lots if lot.quantity > 0 and lot.average_cost is None]
    if not priced:
        return None, not unpriced
    quantity = sum(lot.quantity for lot in priced)
    total = sum(lot.quantity * lot.average_cost for lot in priced)
    return round(total / quantity, 6), not unpriced


def consolidate(fetched) -> Consolidated:
    """Combine what several sources reported into one view.

    `fetched` is a sequence of `(source_name, holdings_or_failure)`. A failure is
    a `str` or an `Exception` rather than a list, which is how a source that
    could not be reached travels **into** the result rather than past it - see
    the module docstring on partial consolidation.

    Takes fetched holdings rather than sources-and-a-fetcher, deliberately, and
    for exactly the reason §101 gave for `concentration`: a function that did its
    own fetching could only be tested against whatever the fetcher does, and the
    interesting cases here - a source that failed, two sources disagreeing about
    an asset class, a long and a short of the same security - are ones no real
    provider would produce on demand."""
    seen: list[str] = []
    failures: list[dict] = []
    incomplete: list[dict] = []
    unconfirmed: list[str] = []
    by_symbol: dict[str, list[Lot]] = {}

    for source_name, result in fetched:
        name = str(source_name)
        if name in seen:
            # Double-counting somebody's money is the worst arithmetic error
            # available here, and it is silent: every number simply comes out
            # twice as large, and nothing looks broken.
            raise ConsolidationRefused(
                f"source {name!r} appears twice. Consolidating it with itself would "
                "double every position it holds, and nothing in the result would look "
                "wrong.")
        seen.append(name)

        if isinstance(result, (str, Exception)):
            failures.append({"source": name, "reason": str(result)})
            continue

        answer = result if isinstance(result, SourceAnswer) else SourceAnswer(
            holdings=tuple(result))
        if not answer.confirmed:
            unconfirmed.append(name)
        elif answer.short_by:
            incomplete.append({
                "source": name,
                "expected": answer.expected_positions,
                "received": len(answer.holdings),
                "reason": (f"the account says it holds {answer.expected_positions} "
                           f"position(s) and sent {len(answer.holdings)}"),
            })

        for held in answer.holdings:
            by_symbol.setdefault(held.symbol, []).append(Lot(
                source=name,
                quantity=held.quantity,
                average_cost=held.average_cost,
                as_of=held.as_of,
                asset_class=held.asset_class,
            ))

    positions = []
    conflicts = []
    for symbol in sorted(by_symbol):
        lots = tuple(by_symbol[symbol])
        classes = {lot.asset_class for lot in lots}
        known = classes - {holdings_module.ASSET_UNKNOWN}

        if len(known) > 1:
            # Two sources describing one security differently. One of them is
            # wrong and this module does not know which, so it says so rather
            # than choosing (§100).
            asset_class = holdings_module.ASSET_UNKNOWN
            conflict = tuple(sorted(known))
            conflicts.append({
                "symbol": symbol, "field": "asset_class", "values": conflict,
                "sources": tuple(sorted({lot.source for lot in lots})),
                "resolution": "reported as unknown; this build will not choose between them",
            })
        else:
            asset_class = next(iter(known), holdings_module.ASSET_UNKNOWN)
            conflict = ()

        long_quantity = sum(lot.quantity for lot in lots if lot.quantity > 0)
        short_quantity = sum(lot.quantity for lot in lots if lot.quantity < 0)
        average_cost, complete = _weighted_average_cost(lots)

        positions.append(Position(
            symbol=symbol,
            asset_class=asset_class,
            net_quantity=long_quantity + short_quantity,
            long_quantity=long_quantity,
            short_quantity=short_quantity,
            average_cost=average_cost,
            lots=lots,
            sources=tuple(sorted({lot.source for lot in lots})),
            class_conflict=conflict,
            cost_basis_complete=complete,
        ))

    answered = [name for name in seen
                if name not in {failure["source"] for failure in failures}]
    stamps = sorted({lot.as_of for lots in by_symbol.values() for lot in lots if lot.as_of})
    # The oldest, not the newest. A view assembled from two honest timestamps
    # must not report a third that neither source would recognise.
    as_of = stamps[0] if stamps else None
    stale = tuple(sorted({
        lot.source for lots in by_symbol.values() for lot in lots
        if lot.as_of and as_of and lot.as_of > as_of}))

    return Consolidated(
        positions=tuple(positions),
        sources=tuple(answered),
        as_of=as_of,
        # **Strict since TQ-80.** It used to mean "no source failed", which
        # quietly equated "nothing went wrong that announced itself" with "this
        # is the whole portfolio". Complete now means every source answered,
        # every source said how much it holds, and every one sent that much.
        complete=not failures and not incomplete and not unconfirmed,
        failed_sources=tuple(failures),
        incomplete_sources=tuple(incomplete),
        unconfirmed_sources=tuple(sorted(unconfirmed)),
        stale_sources=stale,
        conflicts=tuple(conflicts),
        notes=tuple(_notes(positions, failures, incomplete, unconfirmed,
                           conflicts, stale, as_of)),
    )


def _notes(positions, failures, incomplete, unconfirmed, conflicts, stale,
           as_of) -> list[str]:
    """Everything a reader has to be told, in words they can repeat.

    Assembled here rather than left to each caller, because a caller that forgot
    one would produce a report that looks complete. Every one of these describes
    a way the numbers above are *less* than they appear."""
    notes = []
    if failures:
        notes.append(
            f"{len(failures)} source(s) could not be reached, so this is part of the "
            f"portfolio rather than all of it: "
            f"{', '.join(f['source'] for f in failures)}. Anything computed from it - "
            "concentration especially - describes only what answered.")
    if incomplete:
        notes.append(
            f"{len(incomplete)} source(s) sent fewer positions than they say they hold, "
            "so positions are missing from this view and it is not known which: "
            + "; ".join(f"{entry['source']} ({entry['reason']})" for entry in incomplete)
            + ". Every figure below understates the portfolio by whatever is absent.")
    if unconfirmed:
        notes.append(
            f"{len(unconfirmed)} source(s) did not say how many positions they hold, so "
            f"this view cannot be confirmed complete: {', '.join(sorted(unconfirmed))}. "
            "That is unknown rather than wrong - but it is also not a clean bill of "
            "health.")
    if conflicts:
        notes.append(
            f"{len(conflicts)} security(ies) are described differently by different "
            "sources. They are reported as unknown rather than guessed at.")
    offsetting = [p for p in positions if p.is_offsetting]
    if offsetting:
        notes.append(
            f"{len(offsetting)} security(ies) are held long at one source and short at "
            "another. The net is shown and both legs are kept: they are two real "
            "positions with two cost bases, and a net of zero is not the same as "
            "holding neither.")
    partial = [p for p in positions if not p.cost_basis_complete]
    if partial:
        notes.append(
            f"{len(partial)} position(s) have a cost basis for only part of what is "
            "held, so their average cost is the cost of the known part rather than the "
            "whole.")
    if stale:
        notes.append(
            f"This view is as of {as_of}, the oldest of its sources. "
            f"{', '.join(stale)} reported later data, which is not shown as current "
            "because the rest of the portfolio is not.")
    return notes
