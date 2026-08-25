"""Holdings a client has told their representative about (TASK_QUEUE TQ-42,
docs/SPEC_RECONCILIATION.md §96).

§95 left `portfolio_analysis` declared and unbuilt with a precise reason: there
is a portfolio in this system, but it is the operator's — one file, one owner,
no per-client holdings. Reading it for a client would hand them somebody else's
positions.

This is the data model that answers that, and the design turns on one question:
where do a client's holdings honestly come from?

## The client tells you

A brokerage integration does not exist. An upload needs a surface the Gateway's
client does not have. The operator provisioning them is the original bug wearing
a helpful face. What is left is the thing a personal representative actually
does: you tell them what you hold, and they remember.

That has no leak surface at all — the data is the client's because the client
supplied it — and it is the relationship addendum 43 §16 describes rather than a
mechanism bolted beside it.

## What this data is, and what it is not

It is what this client *said* they hold. It is not a broker account, not a
verified position, and not `data/portfolio.xlsx` — which remains the operator's,
reached by a different path, and deliberately untouched here.

Two portfolios for one person is a confusion worth naming. The operator holds
this capability as well — every role invariant in gateway/roles.py is "the
operator has all of them", and carving out an exception costs more surprise than
it buys — but the operator already owns a portfolio properly through
app/tools/portfolio.py. Naming is what keeps them apart: these are holdings
*told to a representative*, never a broker account.

## Classification, applied at ingestion rather than at egress

`app/privacy_filter.py` stores `account_id` and strips it on the way out. That is
right for a file somebody else wrote. Here the schema is ours, so the stronger
form is available and taken: **there is no account column at all.** A field that
does not exist cannot be leaked by a future reader who forgets to sanitize, and
"never stored" survives a refactor in a way "always stripped" does not.

## Arithmetic is computed, never narrated

`concentration` returns numbers this module worked out. A model asked to
percentage-weight a portfolio will produce something shaped like arithmetic, and
somebody's money is the last place a plausible-looking number belongs.

## Deliberately absent: anything needing a price

No market value, no gain or loss, no performance. Every price this organization
can produce is simulated training data (addendum 25), and applying it to a
client's real positions would be presenting synthetic output as real — what §95
refused for trade ideas, arriving one field over. Cost basis is a fact the
client stated; current value is a fact nobody here has.
"""

from __future__ import annotations

from backend.db import Database, now_iso

SCHEMA_VERSION = 1

# A ceiling on how many positions one client may record. Not a storage concern:
# a "portfolio" of ten thousand lines is somebody using a conversational agent
# as a database, which is a different product.
MAX_POSITIONS = 200

SCHEMA = """
-- What a client has told their representative they hold (TQ-42). One row per
-- client per ticker: telling your representative about the same holding twice
-- is a correction, not a second position.
--
-- There is deliberately no account column. app/privacy_filter.py strips
-- account_id on egress because it does not own that file's schema; this one is
-- ours, and a field that does not exist cannot be leaked by a reader who
-- forgets to sanitize.
--
-- `simulated` marks demo data (gateway/demo_clients.py). Marked rather than
-- inferred from a naming convention, so that clearing it before going live is
-- exact and auditable instead of a careful guess.
CREATE TABLE IF NOT EXISTS client_holdings (
    client_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    shares REAL NOT NULL,
    cost_basis REAL,
    acquired_on TEXT,
    note TEXT,
    stated_at TEXT NOT NULL,
    simulated INTEGER NOT NULL DEFAULT 0,
    schema_version INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (client_id, ticker)
);
"""


class HoldingRefused(ValueError):
    """A holding this module will not record, with a reason the client can act
    on. Refused rather than coerced: silently storing zero shares because the
    number would not parse is worse than saying the number would not parse."""


def _clean_ticker(raw) -> str:
    ticker = str(raw or "").strip().upper()
    if not ticker:
        raise HoldingRefused("A holding needs a ticker.")
    if len(ticker) > 24:
        raise HoldingRefused("That is too long to be a ticker.")
    # Deliberately not checked against this organization's security universe. A
    # client may hold something this system has never heard of, and refusing it
    # would be refusing a fact about their money because our reference data is
    # incomplete.
    return ticker


def _positive(value, field: str, *, required: bool) -> float | None:
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


def record(conn: Database, client_id: str, *, ticker: str, shares,
           cost_basis=None, acquired_on: str | None = None,
           note: str | None = None, simulated: bool = False) -> dict:
    """Record what this client says they hold, replacing any earlier statement
    about the same ticker.

    Replacing rather than appending: a client mentioning a holding twice is
    correcting themselves, and a representative who accumulated both would be
    reporting a position its owner never held."""
    if not (client_id or "").strip():
        raise HoldingRefused("A holding has to belong to somebody.")
    symbol = _clean_ticker(ticker)
    quantity = _positive(shares, "a number of shares", required=True)
    cost = _positive(cost_basis, "a cost basis", required=False)

    held = conn.fetchone(
        "SELECT COUNT(*) AS n FROM client_holdings WHERE client_id = ? AND ticker != ?",
        (client_id, symbol))["n"]
    if held >= MAX_POSITIONS:
        raise HoldingRefused(
            f"That would be more than {MAX_POSITIONS} positions. I am your point of "
            "contact, not a book of record.")

    conn.execute(
        "INSERT INTO client_holdings "
        "(client_id, ticker, shares, cost_basis, acquired_on, note, stated_at, "
        "simulated, schema_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(client_id, ticker) DO UPDATE SET "
        "shares = excluded.shares, cost_basis = excluded.cost_basis, "
        "acquired_on = excluded.acquired_on, note = excluded.note, "
        "stated_at = excluded.stated_at, simulated = excluded.simulated",
        (client_id, symbol, quantity, cost, (acquired_on or None), (note or None),
         now_iso(), 1 if simulated else 0, SCHEMA_VERSION),
    )
    return one(conn, client_id, symbol)


def one(conn: Database, client_id: str, ticker: str) -> dict | None:
    row = conn.fetchone(
        "SELECT ticker, shares, cost_basis, acquired_on, note, stated_at, simulated "
        "FROM client_holdings WHERE client_id = ? AND ticker = ?",
        (client_id, _clean_ticker(ticker)))
    return dict(row) if row else None


def listing(conn: Database, client_id: str) -> list[dict]:
    """This client's holdings, and only ever this client's.

    The `client_id` filter is the whole security property, and it is the same
    one §93 put on conversations: a personal representative that could reach
    another client's positions would be a worse version of the bug that started
    all this."""
    return conn.fetchall(
        "SELECT ticker, shares, cost_basis, acquired_on, note, stated_at, simulated "
        "FROM client_holdings WHERE client_id = ? ORDER BY ticker", (client_id,))


def forget(conn: Database, client_id: str, ticker: str) -> bool:
    """Remove one holding; returns whether there was one to remove.

    It is the client's data, so they can take it back. A representative who
    could be told something but never told to forget it is keeping a record
    rather than holding a relationship."""
    return conn.execute_returning_rowcount(
        "DELETE FROM client_holdings WHERE client_id = ? AND ticker = ?",
        (client_id, _clean_ticker(ticker))) > 0


def forget_all(conn: Database, client_id: str) -> int:
    return conn.execute_returning_rowcount(
        "DELETE FROM client_holdings WHERE client_id = ?", (client_id,))


def concentration(conn: Database, client_id: str) -> dict:
    """Weights and concentration, by stated cost basis.

    Computed here rather than described to a model, because a model asked to
    percentage-weight a portfolio produces something *shaped* like arithmetic.

    By cost, never by market value: every price this organization can produce is
    simulated (addendum 25), and applying it to a client's real positions would
    present synthetic output as real. Cost basis is a fact the client stated.
    Current value is a fact nobody here has, and the report says so rather than
    leaving its absence to be noticed."""
    rows = listing(conn, client_id)
    if not rows:
        return {"positions": 0, "known_cost": None, "weights": [], "priced": False,
                "note": "You have not told me about any holdings yet."}

    with_cost = [r for r in rows if r["cost_basis"] is not None]
    missing_cost = [r["ticker"] for r in rows if r["cost_basis"] is None]
    total = sum(r["shares"] * r["cost_basis"] for r in with_cost)

    weights = []
    for row in sorted(with_cost, key=lambda r: r["shares"] * r["cost_basis"], reverse=True):
        value = row["shares"] * row["cost_basis"]
        weights.append({
            "ticker": row["ticker"],
            "cost": round(value, 2),
            "weight_pct": round(100 * value / total, 2) if total else None,
        })

    return {
        "positions": len(rows),
        "known_cost": round(total, 2) if with_cost else None,
        "weights": weights,
        # Named rather than implied. A report that simply omitted market value
        # would read as a portfolio worth its cost basis.
        "priced": False,
        "priced_note": (
            "These are weights by what you paid, not by what the positions are worth "
            "now. This system has no real market prices — everything it generates is "
            "simulated training data — so it cannot tell you current value, gain or loss."
        ),
        "largest_position": weights[0] if weights else None,
        "top_three_pct": (round(sum(w["weight_pct"] or 0 for w in weights[:3]), 2)
                          if weights else None),
        "missing_cost_basis": missing_cost,
        "missing_cost_note": (
            f"{len(missing_cost)} holding(s) have no cost basis, so they are counted as "
            "positions but left out of the weights."
        ) if missing_cost else None,
    }


def simulated_client_ids(conn: Database) -> list[str]:
    """Which clients in this database are demo data.

    Read from the flag rather than from a naming convention, so that clearing
    demo data before going live is exact rather than a careful guess."""
    return [r["client_id"] for r in conn.fetchall(
        "SELECT DISTINCT client_id FROM client_holdings WHERE simulated = 1 "
        "ORDER BY client_id")]
