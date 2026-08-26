"""What a holding is, and the arithmetic over a set of them (TASK_QUEUE TQ-42/44/45,
docs/SPEC_RECONCILIATION.md §96, §99, §100, §101; **custody removed by TQ-72, §111**).

## What this module used to be, and why half of it is gone

It used to store holdings. A client told their representative what they held and
this wrote it down — `record`, `listing`, `forget`, a `portfolio_holdings` table
and two migrations to keep it honest across schema changes.

**None of that exists any more**, by owner direction (§111):

> *"The portfolios don't live in this system. The portfolios are the personal
> property of the clients… holds no information of the portfolios in the
> system."*

Positions are fetched from the client's own external sources when an analysis is
asked for, held for the life of the session, and discarded when the client
disconnects (§115). There is nowhere for `record` to write and nothing for
`listing` to read, so both are gone rather than emptied.

## What survives, and it is the part that was always the point

`concentration` — the arithmetic — is untouched. §101 deliberately built it to
take **holdings, not a connection**:

> *"an analyzer that read the table itself would agree with every provider
> trivially, because they all write to the same table. This one has no idea
> where its input came from."*

That decision was made to keep a contract testable, and it is why the table could
be removed without the analysis noticing. A version that had read the database
directly would have had to be rewritten from scratch; this one needed no change
at all.

The vocabulary survives for the same reason: `asset_class` speaks the house codes
(§70, §100) whether a position came from a table, a broker, or a spreadsheet, and
`HoldingRefused` still refuses a quantity of zero or a symbol nobody sent —
validation is about what a holding *is*, not about where it is kept.

## The rules that outlived the storage

- **Nothing here is priced.** `concentration` weights by what the client paid,
  and says so in words a caller can repeat. What a position is worth *now* needs
  a price, and §113 puts prices in the market data store, where §115's greeks
  and valuations will read them — not here.
- **Arithmetic is computed, never narrated.** A model asked to percentage-weight
  a portfolio produces something *shaped* like arithmetic, and somebody's money
  is the last place a plausible-looking number belongs.
- **Short positions are counted but never weighted.** A short's `average_cost` is
  a credit received rather than an amount paid, so folding it into cost weights
  gives a percentage of a total that no longer means anything.
- **Absent is absent.** A holding with no cost basis is counted as a position and
  left out of the weights, and the report says so rather than leaving its absence
  to be noticed.
"""

from __future__ import annotations

from backend.reference_data import ASSET_CLASSES as _HOUSE_ASSET_CLASSES

SCHEMA_VERSION = 2

# A ceiling on how many positions one consolidated view may carry. Not a storage
# concern any more - nothing is stored - but a working-set one: a "portfolio" of
# ten thousand lines held in memory for a session is somebody using an analyst as
# a database, which is a different product.
MAX_POSITIONS = 200

# The house asset-class vocabulary, imported rather than mirrored (TQ-45a).
#
# A mirrored list would recreate the two-models problem one scale smaller, with
# nothing to notice the drift. The import is safe - backend/reference_data opens
# no connection at import - and a constant tuple of class codes is a vocabulary
# rather than organization data.
ASSET_UNKNOWN = "unknown"
ASSET_CLASSES = tuple(code for code, _ in _HOUSE_ASSET_CLASSES) + (ASSET_UNKNOWN,)

# What a client may hold is deliberately NOT limited to boot configuration's
# `implemented_asset_classes`. That list says what this organization can process;
# somebody may own something it cannot, and refusing to record a fact about their
# money because our reference data is incomplete is the refusal `_clean_symbol`
# already declines to make about symbols.

# The canonical field names (addendum 44 §3.4, TQ-45a). Kept as a tuple because
# it is the shape a source is expected to produce, and something to check an
# adapter against is worth more than a comment saying what the shape is.
FIELDS = ("symbol", "quantity", "average_cost", "asset_class", "acquired_on", "note",
          "as_of", "simulated")


class HoldingRefused(ValueError):
    """A holding this module will not accept, with a reason the client can act
    on. Refused rather than coerced: silently treating an unparseable number as
    zero shares is worse than saying the number would not parse."""


def clean_symbol(raw) -> str:
    symbol = str(raw or "").strip().upper()
    if not symbol:
        raise HoldingRefused("A holding needs a symbol.")
    if len(symbol) > 24:
        raise HoldingRefused("That is too long to be a symbol.")
    # Deliberately not checked against this organization's security universe. A
    # client may hold something this system has never heard of, and refusing it
    # would be refusing a fact about their money because our reference data is
    # incomplete.
    return symbol


def clean_asset_class(raw) -> str:
    if raw is None or raw == "":
        return ASSET_UNKNOWN
    value = str(raw).strip().lower()
    if value not in ASSET_CLASSES:
        raise HoldingRefused(
            f"I do not recognise {value!r} as an asset class. Known are "
            f"{', '.join(ASSET_CLASSES)}.")
    return value


def quantity(value) -> float:
    """How much is held. **Negative means short**, and zero is still refused.

    Found while building the demo (§101): addendum 44 §6.1 asks for a covered
    call, and a covered call is a *written* option - you are short four
    contracts, not long four. Storing it as positive would have been the wrong
    fact about somebody's position.

    Zero stays refused: a position of zero is not a position, and silently
    accepting one because a number would not parse is worse than saying the
    number would not parse."""
    if value is None or value == "":
        raise HoldingRefused("A holding needs a quantity.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise HoldingRefused("That is not a number I can use for a quantity.") from None
    if number == 0:
        raise HoldingRefused(
            "A quantity of zero is not a position. If it has been closed, it is not "
            "part of the portfolio.")
    return number


def positive(value, field: str, *, required: bool) -> float | None:
    if value is None or value == "":
        if required:
            raise HoldingRefused(f"A holding needs {field}.")
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise HoldingRefused(f"That is not a number I can use for {field}.") from None
    if number <= 0:
        raise HoldingRefused(f"{field} has to be greater than zero.")
    return number


def concentration(positions) -> dict:
    """Weights and concentration, over canonical holdings from anywhere.

    **Takes holdings, not a connection** (TQ-45b, §101), and that is the decision
    this whole module survived TQ-72 on. It was made so that §15.3's "switching
    provider does not change analyzer contract" would be a real claim rather than
    a tautology - an analyzer reading the table itself would agree with every
    provider trivially, because they all wrote to the same table.

    The table is gone now and this function did not change. A version that had
    read the database would have needed rewriting from scratch.

    `positions` is a sequence of `portfolio_providers.Holding`. Not imported here
    - that module imports this one - so the contract is the attribute names
    rather than the type, which is also what lets a future source return its own
    canonical object.

    Computed here rather than described to a model, because a model asked to
    percentage-weight a portfolio produces something *shaped* like arithmetic,
    and somebody's money is the last place a plausible-looking number belongs.

    By cost, never by market value. Average cost is a fact the source stated;
    what a position is worth today needs a price, which §113 puts in the market
    data store rather than here.

    **Short positions are counted but not weighted** - see the comment below. The
    weights are across long positions; `short_positions` lists the rest."""
    rows = list(positions)
    if not rows:
        return {"positions": 0, "known_cost": None, "weights": [], "priced": False,
                "note": "There are no positions in this portfolio."}

    # Short positions are counted but never weighted (§101). A short's
    # `average_cost` is a credit *received*, not an amount paid, so folding it
    # into cost weights would produce a negative share of a total that no longer
    # means anything - a percentage that looks like arithmetic and is not. They
    # are reported separately rather than dropped, because they are real
    # positions and leaving them out silently would understate what somebody
    # holds.
    longs = [r for r in rows if r.quantity > 0]
    shorts = [r for r in rows if r.quantity < 0]

    with_cost = [r for r in longs if r.average_cost is not None]
    missing_cost = [r.symbol for r in longs if r.average_cost is None]
    total = sum(r.quantity * r.average_cost for r in with_cost)

    weights = []
    for row in sorted(with_cost, key=lambda r: r.quantity * r.average_cost, reverse=True):
        value = row.quantity * row.average_cost
        weights.append({
            "symbol": row.symbol,
            "cost": round(value, 2),
            "weight_pct": round(100 * value / total, 2) if total else None,
        })

    return {
        "positions": len(rows),
        "known_cost": round(total, 2) if with_cost else None,
        "weights": weights,
        # Named rather than implied. A report that simply omitted market value
        # would read as a portfolio worth its cost basis.
        #
        # Hard False here, and that is not a second copy of any pricing rule:
        # this report is *by cost* whatever its input, so there is no source that
        # would make it priced.
        "priced": False,
        "priced_note": (
            "These are weights by what was paid, not by what the positions are worth "
            "now. Current value, gain and loss need a market price, which this report "
            "does not use."
        ),
        "largest_position": weights[0] if weights else None,
        "top_three_pct": (round(sum(w["weight_pct"] or 0 for w in weights[:3]), 2)
                          if weights else None),
        "short_positions": [
            {"symbol": r.symbol, "quantity": r.quantity, "asset_class": r.asset_class,
             "average_cost": r.average_cost}
            for r in sorted(shorts, key=lambda r: r.symbol)
        ],
        "short_note": (
            f"{len(shorts)} position(s) are short, so they are counted but not weighted: "
            "what was received for writing them is a credit, not an amount paid, and "
            "mixing it into cost weights would give a percentage that means nothing."
        ) if shorts else None,
        "missing_average_cost": missing_cost,
        "missing_cost_note": (
            f"{len(missing_cost)} holding(s) have no average cost recorded, so they are "
            "counted as positions but left out of the weights."
        ) if missing_cost else None,
    }
