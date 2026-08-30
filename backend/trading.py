"""A trader's own book: the calls one agent made, and how they turned out
(docs/SPEC_RECONCILIATION.md §162).

## Whose positions these are, and why that settles §111

A trader here is a character with a book of their own. The positions are **the
agent's personal record** - part of what a persistent agent carries alongside its
identity, role history and performance (addendum 47 §14) - and they are keyed on
`agent_id`, the durable anchor TQ-97 established, never on a display name.

That is what keeps §111 whole rather than merely adjacent to it. §111 says *"the
portfolios are the personal property of the clients"* and that this system holds
none of them. A client portfolio is somebody else's property, fetched per session
and discarded. A trader's book is the agent's own, taken on its own judgement,
and the self-evolution directive §11 asks for it in terms: analysts generate
ideas, traders decide execution and timing, and results determine whether the
process is working.

Two different subjects that must never become one, so the boundary is enforced:

- **Every position belongs to an agent, and no row carries a client.** No
  `client_id`, no `owner_type`, no `owner_id`, no session. `tests/test_trading.py`
  scans the schema and fails if one appears, because the way §111 gets undone is
  somebody adding an owner column to a table that already exists and calling it
  multi-tenancy.
- **Nothing here reads a client's positions.** The Trader never imports
  `consolidation`, `portfolio_providers` or `analysis_requests`, and a test
  asserts it.

**The word `portfolio` is deliberately not used in any name here.** Not to slip
past the tripwires at `tests/test_backend_portfolios.py` - those are untouched and
still forbid a `portfolios` or `portfolio_holdings` table - but because in this
codebase that word already means the client's property, and one concept keeping
one name is 47 §5. A trader has a book.

## What is actually traded

Implied volatility, in vol points. That is not a simplification chosen for
convenience - it is what this organization detects. The Explorer finds IV
anomalies, the Speculator investigates them, Analysis grades the reports, and the
thing the desk can act on is the anomaly itself. A spot price would have to be
invented; the surface is already there and already produced by the provider every
other agent reads.

**Every figure here is synthetic and says so.** Fills record `origin`, and it is
`synthetic` because the surface is (§113: every observation carries
`origin='synthetic'` against a security master whose identifiers are `JE-000001`).
`is_priced` stays false for anything this book produces. A P&L in vol points
against a generated surface is a measurement of the *process*, not of money, and
labelling it otherwise would be the first real lie this system told.

## Positions are derived, never stored

A position is its fills. Storing a running quantity beside them creates a second
answer to *what do we hold*, and the two drift - which is the same reasoning that
keeps engineering work scored on read rather than on a stored outcome (§119 §8).
"""

from __future__ import annotations

from backend.db import Database, now_iso

SCHEMA = """
-- An order the desk placed on its own account. One per analysis result, enforced
-- by the unique index below: the desk acts on a judgement once, and a second
-- order against the same result would be the same idea traded twice.
CREATE TABLE IF NOT EXISTS trader_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    -- Whose book this is. The durable agent id, never the display name: a
    -- renamed trader keeps one continuous record, and a name-keyed book would
    -- either break every join or hand somebody else's calls to whoever holds the
    -- name next (TQ-97, TQ-99).
    agent_id TEXT NOT NULL,
    security TEXT NOT NULL,
    -- long_vol | short_vol. What the desk did about the anomaly, not what the
    -- anomaly was: the analysis says whether volatility is rich or cheap and the
    -- trader decides whether that is worth acting on.
    side TEXT NOT NULL,
    -- Vol points of exposure. Deliberately not currency - see the module note.
    size REAL NOT NULL,
    -- The judgement this order acts on, and the report behind it. Both kept so a
    -- losing trade can be attributed to the idea or to the execution rather than
    -- to whoever is nearest.
    analysis_result_id INTEGER NOT NULL,
    report_id INTEGER,
    thesis TEXT NOT NULL,
    -- What the analysis believed, as a number, so the outcome can be compared
    -- against the expectation rather than against a sentence.
    analysis_confidence REAL,
    -- The desk identity that placed it, which is a job rather than a person.
    placed_by TEXT NOT NULL,
    -- open | closed
    status TEXT NOT NULL,
    closed_at TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);

-- One order per judgement. The desk does not trade the same idea twice, and this
-- is what makes the trader idempotent without needing a claim and a lease.
CREATE UNIQUE INDEX IF NOT EXISTS trader_orders_one_per_analysis
    ON trader_orders (analysis_result_id);

CREATE INDEX IF NOT EXISTS trader_orders_open ON trader_orders (status, id);

-- Entry and exit. A position is its fills; nothing stores a running quantity.
CREATE TABLE IF NOT EXISTS trader_fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    filled_at TEXT NOT NULL,
    -- entry | exit
    kind TEXT NOT NULL,
    -- The implied volatility the desk got, in vol points.
    level REAL NOT NULL,
    -- Where the level came from. 'synthetic' is the only value this system can
    -- currently produce and it is written rather than assumed, so the day a real
    -- surface arrives the old fills still say what they were (§113).
    origin TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS trader_fills_by_order ON trader_fills (order_id, id);

-- Why a closed trade made or lost. The specification asks the demo to expose the
-- evaluator's attribution rather than merely show final P&L.
CREATE TABLE IF NOT EXISTS trader_attributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL UNIQUE,
    judged_at TEXT NOT NULL,
    judged_by TEXT NOT NULL,
    -- bad_idea | bad_timing | bad_data | sound_and_profitable | market_randomness
    verdict TEXT NOT NULL,
    detail TEXT NOT NULL,
    pnl_vol_points REAL NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);
"""

SCHEMA_VERSION = 1

SIDE_LONG_VOL = "long_vol"
SIDE_SHORT_VOL = "short_vol"
SIDES = (SIDE_LONG_VOL, SIDE_SHORT_VOL)

STATUS_OPEN = "open"
STATUS_CLOSED = "closed"

FILL_ENTRY = "entry"
FILL_EXIT = "exit"

ORIGIN_SYNTHETIC = "synthetic"

# Why a closed trade turned out as it did. A closed vocabulary, because the whole
# value of attribution is that it distinguishes causes - a free-text field would
# collapse back into "it lost money", which is the thing final P&L already says.
VERDICT_SOUND = "sound_and_profitable"
VERDICT_BAD_IDEA = "bad_idea"
VERDICT_BAD_TIMING = "bad_timing"
VERDICT_BAD_DATA = "bad_data"
VERDICT_RANDOMNESS = "market_randomness"
VERDICTS = (VERDICT_SOUND, VERDICT_BAD_IDEA, VERDICT_BAD_TIMING, VERDICT_BAD_DATA,
            VERDICT_RANDOMNESS)

# A move smaller than this is not evidence about anybody's judgement. Below it a
# trade is attributed to market randomness rather than to the analyst or the
# trader, because directive §11 is explicit that poor performance is attributed
# through diagnosis rather than by automatically blaming one role - and blaming
# somebody for noise is exactly that.
NOISE_VOL_POINTS = 0.005


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)


# --- placing and filling ------------------------------------------------------------


def place(conn: Database, *, agent_id: str, security: str, side: str, size: float,
          analysis_result_id: int, thesis: str, placed_by: str,
          report_id: int | None = None,
          analysis_confidence: float | None = None) -> int | None:
    """Take a position on the house's own account.

    Returns None when this judgement has already been traded - the unique index
    is the guard, so a trader that runs every cycle acts on each analysis once
    without needing a claim and the lease that would come with it."""
    if side not in SIDES:
        raise ValueError(f"unknown side {side!r}; known are {list(SIDES)}")
    if size <= 0:
        raise ValueError("an order with no size is not an order")
    existing = conn.fetchone(
        "SELECT id FROM trader_orders WHERE analysis_result_id = ?", (analysis_result_id,))
    if existing:
        return None
    return conn.execute_returning_id(
        "INSERT INTO trader_orders (created_at, agent_id, security, side, size,"
        " analysis_result_id, report_id, thesis, analysis_confidence, placed_by, status,"
        " schema_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (now_iso(), agent_id, security, side, size, analysis_result_id, report_id, thesis,
         analysis_confidence, placed_by, STATUS_OPEN, SCHEMA_VERSION))


def fill(conn: Database, order_id: int, *, kind: str, level: float,
         origin: str = ORIGIN_SYNTHETIC) -> int:
    if kind not in (FILL_ENTRY, FILL_EXIT):
        raise ValueError(f"unknown fill kind {kind!r}")
    return conn.execute_returning_id(
        "INSERT INTO trader_fills (order_id, filled_at, kind, level, origin, schema_version)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (order_id, now_iso(), kind, level, origin, SCHEMA_VERSION))


def close(conn: Database, order_id: int) -> None:
    conn.execute("UPDATE trader_orders SET status = ?, closed_at = ? WHERE id = ?",
                 (STATUS_CLOSED, now_iso(), order_id))


# --- reading the book ---------------------------------------------------------------


def get_order(conn: Database, order_id: int) -> dict | None:
    return conn.fetchone("SELECT * FROM trader_orders WHERE id = ?", (order_id,))


def open_orders(conn: Database) -> list[dict]:
    return conn.fetchall("SELECT * FROM trader_orders WHERE status = ? ORDER BY id",
                         (STATUS_OPEN,))


def fills_of(conn: Database, order_id: int) -> list[dict]:
    return conn.fetchall("SELECT * FROM trader_fills WHERE order_id = ? ORDER BY id",
                         (order_id,))


def entry_level(conn: Database, order_id: int) -> float | None:
    row = conn.fetchone(
        "SELECT level FROM trader_fills WHERE order_id = ? AND kind = ? ORDER BY id LIMIT 1",
        (order_id, FILL_ENTRY))
    return None if row is None else row["level"]


def _direction(side: str) -> int:
    return 1 if side == SIDE_LONG_VOL else -1


def pnl_vol_points(conn: Database, order_id: int) -> float | None:
    """What this trade is worth, in vol points, derived from its fills.

    None when it has no entry: an order placed and never filled has no result,
    and returning zero would make an unfilled order indistinguishable from a
    trade that broke even. Absence is `unknown`, never a plausible default
    (§100)."""
    order = get_order(conn, order_id)
    if order is None:
        return None
    entry = entry_level(conn, order_id)
    if entry is None:
        return None
    exit_row = conn.fetchone(
        "SELECT level FROM trader_fills WHERE order_id = ? AND kind = ? ORDER BY id DESC LIMIT 1",
        (order_id, FILL_EXIT))
    if exit_row is None:
        return None
    return round((exit_row["level"] - entry) * _direction(order["side"]) * order["size"], 6)


def mark(conn: Database, order_id: int, current_level: float) -> float | None:
    """Unrealised, against a level the caller supplies from the same provider
    every other agent reads. Not stored: a mark is true for an instant."""
    order = get_order(conn, order_id)
    entry = entry_level(conn, order_id)
    if order is None or entry is None:
        return None
    return round((current_level - entry) * _direction(order["side"]) * order["size"], 6)


def book_summary(conn: Database) -> dict:
    """The desk's state, derived. Every figure is in vol points against a
    synthetic surface, which is why nothing here is called a value."""
    orders = conn.fetchall("SELECT * FROM trader_orders")
    closed = [o for o in orders if o["status"] == STATUS_CLOSED]
    realised = [pnl_vol_points(conn, o["id"]) for o in closed]
    realised = [p for p in realised if p is not None]
    return {
        "orders": len(orders),
        "open": sum(1 for o in orders if o["status"] == STATUS_OPEN),
        "closed": len(closed),
        "realised_vol_points": round(sum(realised), 6) if realised else 0.0,
        "winners": sum(1 for p in realised if p > 0),
        "losers": sum(1 for p in realised if p < 0),
        # Stated on every read rather than left to the reader. A P&L against a
        # generated surface measures the process and not money.
        "is_priced": False,
        "origin": ORIGIN_SYNTHETIC,
    }


# --- attribution --------------------------------------------------------------------


def attribute(conn: Database, order_id: int, *, judged_by: str) -> dict | None:
    """Why this trade turned out as it did.

    Directive §11: *"Poor performance should be attributed through diagnosis
    rather than automatically blaming one role."* So the verdict distinguishes
    the idea from the execution from the data from the noise, and the ordering
    below is the diagnosis:

    - **No entry level** is `bad_data`. The desk could not see what it was
      trading, and that is neither the analyst's fault nor the trader's.
    - **A move smaller than the noise floor** is `market_randomness`. A sound
      decision may still lose money, and attributing noise to a person is how a
      metric starts punishing correct behaviour.
    - **The volatility moved against the thesis** is `bad_idea`. The analysis
      said rich and it got richer; the desk did what it was told.
    - **It moved with the thesis and the trade still lost** is `bad_timing`. The
      idea was right and the entry or the exit was not, which is precisely the
      distinction the specification asks the demo to expose.
    - Otherwise `sound_and_profitable`.

    Judged by whoever is not the trader; `judged_by` is recorded so producer and
    judge can be checked apart, the fifth application of a rule this system
    already makes five times."""
    order = get_order(conn, order_id)
    if order is None:
        return None
    pnl = pnl_vol_points(conn, order_id)
    entry = entry_level(conn, order_id)

    if entry is None or pnl is None:
        verdict, detail = VERDICT_BAD_DATA, (
            "the desk had no level to trade against, so nothing here is evidence "
            "about the idea or the execution")
        pnl = 0.0
    else:
        exit_row = conn.fetchone(
            "SELECT level FROM trader_fills WHERE order_id = ? AND kind = ? "
            "ORDER BY id DESC LIMIT 1", (order_id, FILL_EXIT))
        move = (exit_row["level"] - entry) if exit_row else 0.0
        with_thesis = move * _direction(order["side"]) > 0
        if abs(move) < NOISE_VOL_POINTS:
            verdict, detail = VERDICT_RANDOMNESS, (
                f"volatility moved {move:+.4f}, inside the noise floor of "
                f"{NOISE_VOL_POINTS}. Not evidence about anybody's judgement.")
        elif not with_thesis:
            verdict, detail = VERDICT_BAD_IDEA, (
                f"the thesis called for {order['side']} and volatility moved {move:+.4f} "
                "against it. The desk executed the judgement it was given.")
        elif pnl < 0:
            verdict, detail = VERDICT_BAD_TIMING, (
                f"volatility moved {move:+.4f} with the thesis and the trade still lost "
                f"{pnl:.4f} vol points. The idea held; the entry or the exit did not.")
        else:
            verdict, detail = VERDICT_SOUND, (
                f"volatility moved {move:+.4f} with the thesis for {pnl:+.4f} vol points.")

    conn.execute(
        "INSERT OR IGNORE INTO trader_attributions (order_id, judged_at, judged_by, verdict,"
        " detail, pnl_vol_points, schema_version) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (order_id, now_iso(), judged_by, verdict, detail, pnl, SCHEMA_VERSION))
    return {"order_id": order_id, "verdict": verdict, "detail": detail,
            "pnl_vol_points": pnl}


def trader_record(conn: Database, agent_id: str) -> dict:
    """One trader's own book and record, keyed on the durable agent id.

    This is what the trader takes on air. It is personal data in the sense
    addendum 47 §14 means - identity, experience, performance history - and it
    survives a rename because a rename changes the desk and not the person.

    The verdict breakdown is reported rather than a score. A trader with three
    `bad_idea` losses executed correctly three times, and a single number would
    charge them for the analyst's judgement - which is the attribution the
    directive asks for, thrown away at the last step."""
    orders = conn.fetchall(
        "SELECT * FROM trader_orders WHERE agent_id = ? ORDER BY id", (agent_id,))
    closed = [o for o in orders if o["status"] == STATUS_CLOSED]
    results = [(o, pnl_vol_points(conn, o["id"])) for o in closed]
    realised = [p for _, p in results if p is not None]
    verdicts: dict[str, int] = {}
    for row in conn.fetchall(
            "SELECT a.verdict, COUNT(*) AS n FROM trader_attributions a"
            " JOIN trader_orders o ON o.id = a.order_id WHERE o.agent_id = ?"
            " GROUP BY a.verdict", (agent_id,)):
        verdicts[row["verdict"]] = row["n"]
    best = max(results, key=lambda r: (r[1] is not None, r[1] or 0), default=(None, None))
    worst = min(results, key=lambda r: (r[1] is None, r[1] or 0), default=(None, None))
    return {
        "agent_id": agent_id,
        "orders": len(orders),
        "open": sum(1 for o in orders if o["status"] == STATUS_OPEN),
        "closed": len(closed),
        "realised_vol_points": round(sum(realised), 6) if realised else 0.0,
        "winners": sum(1 for p in realised if p > 0),
        "losers": sum(1 for p in realised if p < 0),
        "verdicts": verdicts,
        "best_call": {"security": best[0]["security"], "pnl": best[1]} if best[0] else None,
        "worst_call": {"security": worst[0]["security"], "pnl": worst[1]} if worst[0] else None,
        "open_positions": [
            {"security": o["security"], "side": o["side"], "size": o["size"],
             "thesis": o["thesis"]}
            for o in orders if o["status"] == STATUS_OPEN],
        "is_priced": False,
        "origin": ORIGIN_SYNTHETIC,
    }


def attributions(conn: Database, limit: int = 20) -> list[dict]:
    return conn.fetchall(
        "SELECT * FROM trader_attributions ORDER BY id DESC LIMIT ?", (limit,))


def unattributed_closed_orders(conn: Database) -> list[dict]:
    return conn.fetchall(
        "SELECT o.* FROM trader_orders o"
        " LEFT JOIN trader_attributions a ON a.order_id = o.id"
        " WHERE o.status = ? AND a.id IS NULL ORDER BY o.id", (STATUS_CLOSED,))
