"""Holdings a client has told their representative about (TASK_QUEUE TQ-42/TQ-44,
docs/SPEC_RECONCILIATION.md §96, §99).

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

## Owned through a portfolio, not by a client id (TQ-44)

Holdings used to carry `client_id` directly. That was safe but flat: one client
had one implicit portfolio, there was no portfolio identity, and nowhere to
record what addendum 44 §3.3 needs — provider, data mode, sync state, freshness.

They are now keyed by `portfolio_id`, and **`client_id` is gone rather than kept
alongside it** (§4.2). Two sources of truth for ownership can disagree, and the
one that disagrees quietly is the one that hands somebody the wrong positions.
Ownership is reached by joining through `portfolios`, which means it is reached
through `portfolios.resolve` — the one gate.

That is also why every function here takes a **portfolio**, not an id. A dict
that came back from `resolve` is proof the guard ran; an id is a claim that it
did. Passing a string raises rather than being helpfully accepted.

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

## The canonical holding shape (TQ-45a)

Fields are addendum 44 §3.4's — `symbol`, `quantity`, `average_cost` — renamed
from `ticker` / `shares` / `cost_basis` here rather than in TQ-44, because the
canonical shape is *what a provider returns* and TQ-45 is where
`PortfolioProvider` gets defined. Doing it in TQ-44 would have meant touching the
tool schemas and both test files twice.

`average_cost` is the better name for what was always stored: a per-share figure,
which is what `cost_basis` already meant here and what `holdings.concentration`
already assumed. `as_of` replaces `stated_at` for a subtler reason — a provider's
data is *as of* a time, and only a person "states" anything. The shape has to fit
a brokerage account as well as a conversation.

`asset_class` speaks the house vocabulary rather than addendum 44's EQUITY/OPTION.
See the constant below; §70 had already ruled on that kind of substitution.

Deliberately still absent: `market_price`, `market_value`, `provider_position_id`,
`currency`, `metadata`. A field existing is not permission to fill it in, and
none of these has a producer in this build. `currency` in particular was
considered and declined for TQ-49 (spec §11 Q4): `store._ADDITIVE_COLUMNS` makes
adding a column later a one-line change, so an always-NULL column now would be
machinery with no user.
"""

from __future__ import annotations

from backend.db import Database, now_iso
from backend.reference_data import ASSET_CLASSES as _HOUSE_ASSET_CLASSES
from gateway import portfolios

SCHEMA_VERSION = 2

# A ceiling on how many positions one portfolio may record. Not a storage
# concern: a "portfolio" of ten thousand lines is somebody using a
# conversational agent as a database, which is a different product.
MAX_POSITIONS = 200

# The house asset-class vocabulary, imported rather than mirrored (TQ-45a, spec
# §11 Q1).
#
# TQ-44 introduced EQUITY/OPTION from addendum 44 §3.4. This system already had
# eleven finer codes in backend/reference_data.py, and §70 had already refused
# exactly that substitution once - for addendum 39's EQUITIES/OPTIONS_ON_EQUITIES
# - because two naming schemes for one fact is what the Conflict Rule forbids.
# §3.4 asks for EQUITY and OPTION "at minimum", which the finer set satisfies
# rather than contradicts.
#
# Imported, not copied: a mirrored list would recreate the same two-models
# problem one scale smaller, with nothing to notice the drift. The import is
# safe - backend/reference_data opens no connection at import - and a constant
# tuple of class codes is a vocabulary, not organization data, so the §95
# invariant is untouched. `test_the_asset_class_vocabulary_is_the_house_one`
# fails if the two ever diverge.
ASSET_UNKNOWN = "unknown"
ASSET_CLASSES = tuple(code for code, _ in _HOUSE_ASSET_CLASSES) + (ASSET_UNKNOWN,)

# What a client may hold is deliberately NOT limited to boot configuration's
# `implemented_asset_classes`. That list says what this organization can
# process; somebody may own something it cannot, and refusing to record a fact
# about their money because our reference data is incomplete is the refusal
# `_clean_ticker` already declines to make about symbols.

_FIELDS = ("symbol", "quantity", "average_cost", "asset_class", "acquired_on", "note",
           "as_of", "simulated")

SCHEMA = """
-- What a client has told their representative they hold (TQ-42), owned through
-- a portfolio rather than by a client id (TQ-44), in addendum 44 §3.4's names
-- (TQ-45a). One row per portfolio per symbol: telling your representative about
-- the same holding twice is a correction, not a second position.
--
-- `average_cost` is per share, which is what `cost_basis` already meant here and
-- what the new name says out loud. `as_of` replaces `stated_at` because a
-- provider's data is *as of* a time, and only a person "states" anything - the
-- shape has to fit a broker as well as a conversation (TQ-45b).
--
-- There is deliberately no client_id column beside portfolio_id. Two sources of
-- truth for ownership can disagree, and ownership is reached by joining through
-- `portfolios` - which means through portfolios.resolve, the one gate.
--
-- There is deliberately no account column either. app/privacy_filter.py strips
-- account_id on egress because it does not own that file's schema; this one is
-- ours, and a field that does not exist cannot be leaked by a reader who
-- forgets to sanitize.
--
-- `simulated` marks demo data (gateway/demo_clients.py). Marked rather than
-- inferred from a naming convention, so that clearing it before going live is
-- exact and auditable instead of a careful guess.
CREATE TABLE IF NOT EXISTS portfolio_holdings (
    portfolio_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    quantity REAL NOT NULL,
    average_cost REAL,
    asset_class TEXT NOT NULL DEFAULT 'unknown',
    acquired_on TEXT,
    note TEXT,
    as_of TEXT NOT NULL,
    simulated INTEGER NOT NULL DEFAULT 0,
    schema_version INTEGER NOT NULL DEFAULT 2,
    PRIMARY KEY (portfolio_id, symbol)
);
"""


class HoldingRefused(ValueError):
    """A holding this module will not record, with a reason the client can act
    on. Refused rather than coerced: silently storing zero shares because the
    number would not parse is worse than saying the number would not parse."""


def _portfolio_id(portfolio) -> str:
    """The id of a portfolio that has already been through the guard.

    Refuses a bare string on purpose. A `portfolio_id` on its own is something a
    caller might have got from anywhere - a URL, an argument, a model's
    imagination - and accepting one here would put the decision about whose
    positions these are in whatever code happened to build the string. A dict
    from `portfolios.resolve` is evidence that the ownership comparison ran."""
    if not isinstance(portfolio, dict) or not str(portfolio.get("portfolio_id") or "").strip():
        raise TypeError(
            "holdings are reached through a portfolio resolved by "
            "portfolios.resolve(), not through a portfolio id. Passing an id "
            "would skip the ownership check that makes these safe to read.")
    return portfolio["portfolio_id"]


def _clean_symbol(raw) -> str:
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


def _clean_asset_class(raw) -> str:
    if raw is None or raw == "":
        return ASSET_UNKNOWN
    value = str(raw).strip().lower()
    if value not in ASSET_CLASSES:
        raise HoldingRefused(
            f"I do not recognise {value!r} as an asset class. Known are "
            f"{', '.join(ASSET_CLASSES)}.")
    return value


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


def _interpret(row) -> dict:
    """A stored holding, with its asset class checked on read.

    Fail closed like everything else in this area (portfolios §3.6): a class this
    build does not recognise is not one it can report against."""
    holding = dict(row)
    if holding["asset_class"] not in ASSET_CLASSES:
        raise HoldingRefused(
            f"stored holding {holding['symbol']!r} has asset class "
            f"{holding['asset_class']!r}, which this build does not recognise; "
            "refusing rather than guessing what it is.")
    holding["simulated"] = bool(holding["simulated"])
    return holding


def record(conn: Database, portfolio, *, symbol: str, quantity,
           average_cost=None, asset_class: str | None = None,
           acquired_on: str | None = None, note: str | None = None,
           simulated: bool = False, as_of: str | None = None) -> dict:
    """Record what this client says they hold, replacing any earlier statement
    about the same symbol.

    Replacing rather than appending: a client mentioning a holding twice is
    correcting themselves, and a representative who accumulated both would be
    reporting a position its owner never held.

    `as_of` defaults to now, which is right for a client speaking. A provider
    supplying its own timestamp passes it, because when the *data* is from is not
    the same fact as when it was written down (TQ-45b)."""
    portfolio_id = _portfolio_id(portfolio)
    ticker = _clean_symbol(symbol)
    amount = _positive(quantity, "a quantity", required=True)
    cost = _positive(average_cost, "an average cost", required=False)
    classification = _clean_asset_class(asset_class)

    held = conn.fetchone(
        "SELECT COUNT(*) AS n FROM portfolio_holdings WHERE portfolio_id = ? AND symbol != ?",
        (portfolio_id, ticker))["n"]
    if held >= MAX_POSITIONS:
        raise HoldingRefused(
            f"That would be more than {MAX_POSITIONS} positions. I am your point of "
            "contact, not a book of record.")

    conn.execute(
        "INSERT INTO portfolio_holdings "
        "(portfolio_id, symbol, quantity, average_cost, asset_class, acquired_on, note, "
        "as_of, simulated, schema_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(portfolio_id, symbol) DO UPDATE SET "
        "quantity = excluded.quantity, average_cost = excluded.average_cost, "
        "asset_class = excluded.asset_class, acquired_on = excluded.acquired_on, "
        "note = excluded.note, as_of = excluded.as_of, "
        "simulated = excluded.simulated",
        (portfolio_id, ticker, amount, cost, classification, (acquired_on or None),
         (note or None), (as_of or now_iso()), 1 if simulated else 0, SCHEMA_VERSION),
    )
    return one(conn, portfolio, ticker)


def one(conn: Database, portfolio, symbol: str) -> dict | None:
    row = conn.fetchone(
        f"SELECT {', '.join(_FIELDS)} FROM portfolio_holdings "
        "WHERE portfolio_id = ? AND symbol = ?",
        (_portfolio_id(portfolio), _clean_symbol(symbol)))
    return _interpret(row) if row else None


def listing(conn: Database, portfolio) -> list[dict]:
    """This portfolio's holdings, and only ever this portfolio's.

    The `portfolio_id` filter is the whole security property at this layer, and
    the layer above is what makes it worth anything: the portfolio arrived from
    `portfolios.resolve`, so the owner comparison has already happened. A
    personal representative that could reach another client's positions would be
    a worse version of the bug that started all this (§93)."""
    rows = conn.fetchall(
        f"SELECT {', '.join(_FIELDS)} FROM portfolio_holdings "
        "WHERE portfolio_id = ? ORDER BY symbol", (_portfolio_id(portfolio),))
    return [_interpret(row) for row in rows]


def forget(conn: Database, portfolio, symbol: str) -> bool:
    """Remove one holding; returns whether there was one to remove.

    It is the client's data, so they can take it back. A representative who
    could be told something but never told to forget it is keeping a record
    rather than holding a relationship."""
    return conn.execute_returning_rowcount(
        "DELETE FROM portfolio_holdings WHERE portfolio_id = ? AND symbol = ?",
        (_portfolio_id(portfolio), _clean_symbol(symbol))) > 0


def forget_all(conn: Database, portfolio) -> int:
    return conn.execute_returning_rowcount(
        "DELETE FROM portfolio_holdings WHERE portfolio_id = ?", (_portfolio_id(portfolio),))


def concentration(conn: Database, portfolio) -> dict:
    """Weights and concentration, by stated cost basis.

    Computed here rather than described to a model, because a model asked to
    percentage-weight a portfolio produces something *shaped* like arithmetic.

    By cost, never by market value: every price this organization can produce is
    simulated (addendum 25), and applying it to a client's real positions would
    present synthetic output as real. Cost basis is a fact the client stated.
    Current value is a fact nobody here has, and the report says so rather than
    leaving its absence to be noticed.

    `asset_class` is deliberately not read here (spec §10 Q3). Weights are by
    cost regardless of class, so an unknown class costs this report nothing; a
    class-aware view belongs to TQ-45, where the provider defines what a holding
    is."""
    rows = listing(conn, portfolio)
    if not rows:
        return {"positions": 0, "known_cost": None, "weights": [], "priced": False,
                "note": "You have not told me about any holdings yet."}

    with_cost = [r for r in rows if r["average_cost"] is not None]
    missing_cost = [r["symbol"] for r in rows if r["average_cost"] is None]
    total = sum(r["quantity"] * r["average_cost"] for r in with_cost)

    weights = []
    for row in sorted(with_cost, key=lambda r: r["quantity"] * r["average_cost"], reverse=True):
        value = row["quantity"] * row["average_cost"]
        weights.append({
            "symbol": row["symbol"],
            "cost": round(value, 2),
            "weight_pct": round(100 * value / total, 2) if total else None,
        })

    return {
        "positions": len(rows),
        "known_cost": round(total, 2) if with_cost else None,
        "weights": weights,
        # Named rather than implied. A report that simply omitted market value
        # would read as a portfolio worth its cost basis. Routed through the one
        # pricing rule (§3.7) so this cannot drift from every other caller's
        # answer to the same question.
        "priced": portfolios.is_priced(portfolio),
        "priced_note": (
            "These are weights by what you paid, not by what the positions are worth "
            "now. This system has no real market prices — everything it generates is "
            "simulated training data — so it cannot tell you current value, gain or loss."
        ),
        "largest_position": weights[0] if weights else None,
        "top_three_pct": (round(sum(w["weight_pct"] or 0 for w in weights[:3]), 2)
                          if weights else None),
        "missing_average_cost": missing_cost,
        "missing_cost_note": (
            f"{len(missing_cost)} holding(s) have no average cost recorded, so they are "
            "counted as positions but left out of the weights."
        ) if missing_cost else None,
    }


# --- the migration (spec §6, §10 Q1) -----------------------------------------------
#
# The dangerous part of TQ-44: it moves real client holdings between tables.
#
# It lives here, called from gateway/store.init_schema, rather than in
# backend/migrations.py. That pipeline's step 2 backs up the *backend's*
# continuity domain, so registering a Gateway store would have it announce
# "backed up before migrating" while the file being migrated was not in the
# backup - a false safety claim at the exact moment §23's ordering is supposed to
# be true. The safety is supplied locally instead: one transaction, and counts
# verified before anything is renamed.

LEGACY_TABLE = "client_holdings"
LEGACY_ARCHIVE = "client_holdings_legacy"


class MigrationRefused(RuntimeError):
    """The migration would not have been safe. Nothing was changed."""


def _table_exists(conn: Database, name: str) -> bool:
    return conn.fetchone(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)) is not None


def migrate_client_holdings(conn: Database) -> dict:
    """Move pre-TQ-44 holdings into owned portfolios.

    Idempotent by construction rather than by a flag: the last step renames
    `client_holdings` away, so a second run finds nothing to do. That also makes
    the aborted-run case visible - if both tables exist, something stopped
    half-way, and this refuses rather than clobbering the archived copy.

    Each client's rows become one MANUAL portfolio owned by that client. Nothing
    is valued and nothing is classified: `data_mode` is MANUAL because these
    numbers came from a person, and `asset_class` is UNKNOWN because the old rows
    genuinely do not say (spec §10 Q3)."""
    if not _table_exists(conn, LEGACY_TABLE):
        return {"migrated": False, "reason": "no legacy table", "clients": 0, "holdings": 0}
    if _table_exists(conn, LEGACY_ARCHIVE):
        raise MigrationRefused(
            f"both {LEGACY_TABLE!r} and {LEGACY_ARCHIVE!r} exist, which means an earlier "
            "migration did not finish. Refusing rather than overwriting the archived copy - "
            "inspect both tables and remove one deliberately.")

    rows = conn.fetchall(
        "SELECT client_id, ticker, shares, cost_basis, acquired_on, note, stated_at, "
        f"simulated FROM {LEGACY_TABLE} ORDER BY client_id, ticker")
    # Reads the pre-TQ-44 names and writes the canonical ones (TQ-45a). A
    # database that never ran TQ-44 arrives at today's shape in one step rather
    # than through an intermediate that no longer exists in this build.
    before = len(rows)

    by_client: dict[str, list[dict]] = {}
    for row in rows:
        by_client.setdefault(row["client_id"], []).append(dict(row))

    with conn.transaction():
        created: dict[str, str] = {}
        for client_id, holdings_for_client in by_client.items():
            owner = portfolios.for_client(client_id)
            # Simulated if any of this client's rows were flagged. A client with
            # one demo row and one real one is a demo client either way - the
            # §96 rule that clearing works by client, not by row.
            simulated = any(h["simulated"] for h in holdings_for_client)
            portfolio = portfolios.create(
                conn, owner,
                display_name=portfolios.DEFAULT_DISPLAY_NAME,
                portfolio_type=portfolios.TYPE_PRIMARY,
                provider_type=portfolios.PROVIDER_MANUAL,
                data_mode=portfolios.MODE_MANUAL,
                simulated=simulated)
            created[client_id] = portfolio["portfolio_id"]

            for holding in holdings_for_client:
                # Written directly rather than through `record`, which stamps a
                # fresh `as_of`. When the client said it is a fact about them,
                # and a migration that rewrote every one to today would have
                # quietly destroyed it.
                conn.execute(
                    "INSERT INTO portfolio_holdings (portfolio_id, symbol, quantity, "
                    "average_cost, asset_class, acquired_on, note, as_of, simulated, "
                    "schema_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (portfolio["portfolio_id"], holding["ticker"], holding["shares"],
                     holding["cost_basis"], ASSET_UNKNOWN, holding["acquired_on"],
                     holding["note"], holding["stated_at"], holding["simulated"],
                     SCHEMA_VERSION))

        # Verify before renaming (§6.4). Inside the transaction, so a failure
        # here leaves the original table untouched and nothing applied.
        if created:
            placeholders = ",".join("?" * len(created))
            after = conn.fetchone(
                "SELECT COUNT(*) AS n FROM portfolio_holdings "
                f"WHERE portfolio_id IN ({placeholders})", tuple(created.values()))["n"]
        else:
            after = 0
        if after != before:
            raise MigrationRefused(
                f"migration would have moved {before} holding(s) but landed {after}; "
                "rolling back and changing nothing.")

        for client_id, portfolio_id in created.items():
            owned = portfolios.for_client(client_id)
            # Every migrated holding must be reachable through the gate by the
            # client who stated it - which is the actual claim being made, and
            # the one worth checking rather than assuming.
            portfolios.resolve(conn, portfolio_id, owned)

        conn.execute(f"ALTER TABLE {LEGACY_TABLE} RENAME TO {LEGACY_ARCHIVE}")

    return {"migrated": True, "clients": len(created), "holdings": before,
            "portfolios": sorted(created.values()), "archived_table": LEGACY_ARCHIVE}


# --- the field rename (TQ-45a, spec §6) --------------------------------------------
#
# The second migration in this file, and much smaller than the first: it moves
# `portfolio_holdings` from TQ-44's column names to addendum 44 §3.4's.
#
# Same place and same reasoning as the first (spec §10 Q1 of TQ-44):
# backend/migrations.py backs up the backend's continuity domain, not gateway.db,
# so registering a Gateway store there would announce a backup that did not
# contain the file being migrated.
#
# SQLite can ALTER TABLE ... RENAME COLUMN, which is tempting and deliberately
# not used: four separate renames cannot be made atomic with the verification
# step, and the copy-verify-rename shape above is already proven against a real
# database. Matching it costs a few more lines and no thought.

PRE_45_ARCHIVE = "portfolio_holdings_pre45"

# What the old vocabulary maps to. UNKNOWN has an exact counterpart; the other
# two deliberately do not (spec §11 Q1).
_ASSET_CLASS_RENAMES = {"UNKNOWN": ASSET_UNKNOWN}


def _columns(conn: Database, table: str) -> set[str]:
    return {row["name"] for row in conn.fetchall(f"PRAGMA table_info({table})")}


def _renamed_asset_class(value):
    """The house code for a stored TQ-44 asset class.

    `EQUITY` and `OPTION` are refused rather than mapped. `EQUITY` does not
    determine `stock` versus `etf`, and picking one is the fabrication this
    project refuses everywhere else - so the migration says which two codes it
    could mean and stops, rather than choosing.

    This costs nothing real: no row can hold either value, because the only
    writer defaulted to `UNKNOWN` and no tool ever supplied a class. It is here
    so that the rule holds even in the case that cannot happen."""
    if value in _ASSET_CLASS_RENAMES:
        return _ASSET_CLASS_RENAMES[value]
    if value in ASSET_CLASSES:
        return value
    raise MigrationRefused(
        f"stored asset class {value!r} has no unambiguous house code. "
        f"{value!r} could be more than one of {list(ASSET_CLASSES)}, and this "
        "migration will not choose for you - set the column deliberately and re-run.")


def migrate_holding_field_names(conn: Database) -> dict:
    """Move `portfolio_holdings` to the canonical column names.

    Fires only on a database that ran TQ-44 but not this: detected by the old
    `ticker` column still being present, which is a fact about the table rather
    than a version number that can disagree with it."""
    if not _table_exists(conn, "portfolio_holdings"):
        return {"migrated": False, "reason": "no holdings table", "holdings": 0}
    if "ticker" not in _columns(conn, "portfolio_holdings"):
        return {"migrated": False, "reason": "already canonical", "holdings": 0}
    if _table_exists(conn, PRE_45_ARCHIVE):
        raise MigrationRefused(
            f"both 'portfolio_holdings' and {PRE_45_ARCHIVE!r} exist, which means an "
            "earlier rename did not finish. Refusing rather than overwriting the "
            "archived copy - inspect both tables and remove one deliberately.")

    rows = conn.fetchall(
        "SELECT portfolio_id, ticker, shares, cost_basis, asset_class, acquired_on, "
        "note, stated_at, simulated FROM portfolio_holdings ORDER BY portfolio_id, ticker")
    before = len(rows)

    with conn.transaction():
        # `execute`, not `executescript`: sqlite3 commits before running a
        # script, which would end this transaction and make the rollback below
        # impossible while still looking atomic. backend/db.py refuses it
        # outright, and this is the case that guard exists for.
        conn.execute(
            "CREATE TABLE portfolio_holdings_canonical ("
            "portfolio_id TEXT NOT NULL, "
            "symbol TEXT NOT NULL, "
            "quantity REAL NOT NULL, "
            "average_cost REAL, "
            "asset_class TEXT NOT NULL DEFAULT 'unknown', "
            "acquired_on TEXT, "
            "note TEXT, "
            "as_of TEXT NOT NULL, "
            "simulated INTEGER NOT NULL DEFAULT 0, "
            "schema_version INTEGER NOT NULL DEFAULT 2, "
            "PRIMARY KEY (portfolio_id, symbol))")
        for row in rows:
            conn.execute(
                "INSERT INTO portfolio_holdings_canonical (portfolio_id, symbol, quantity, "
                "average_cost, asset_class, acquired_on, note, as_of, simulated, "
                "schema_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (row["portfolio_id"], row["ticker"], row["shares"], row["cost_basis"],
                 _renamed_asset_class(row["asset_class"]), row["acquired_on"], row["note"],
                 row["stated_at"], row["simulated"], SCHEMA_VERSION))

        after = conn.fetchone(
            "SELECT COUNT(*) AS n FROM portfolio_holdings_canonical")["n"]
        if after != before:
            raise MigrationRefused(
                f"rename would have moved {before} holding(s) but landed {after}; "
                "rolling back and changing nothing.")
        moved = conn.fetchone(
            "SELECT COUNT(*) AS n FROM portfolio_holdings_canonical c "
            "JOIN portfolio_holdings o ON o.portfolio_id = c.portfolio_id "
            "AND o.ticker = c.symbol")["n"]
        if moved != before:
            raise MigrationRefused(
                f"{before - moved} holding(s) did not land under the same portfolio and "
                "symbol; rolling back and changing nothing.")

        conn.execute(f"ALTER TABLE portfolio_holdings RENAME TO {PRE_45_ARCHIVE}")
        conn.execute("ALTER TABLE portfolio_holdings_canonical RENAME TO portfolio_holdings")

    return {"migrated": True, "holdings": before, "archived_table": PRE_45_ARCHIVE}
