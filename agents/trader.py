"""Trader: takes a position on the analysis, and owns the result.

A character with a book of their own. The positions are the agent's personal
record, keyed on its durable `agent_id`, and the trader goes on air to talk about
them - the calls that worked, the ones that did not, and what is still open.

## What the trader decides, and what it does not

The analyst says whether volatility is rich or cheap. **The trader decides
whether that judgement is worth acting on, and when to get out.** Directive §11
draws the line there: analysts generate ideas, traders decide execution and
timing, and poor performance is attributed through diagnosis rather than by
blaming whichever role is nearest.

So the trader never re-does the analysis. It reads the conviction the analyst
recorded, applies its own threshold, sizes by that conviction, and exits on its
own rule. A trader that second-guessed the thesis would be a second analyst, and
the attribution would have nothing left to separate.

## Reads the same world as everyone else

The surface comes from `providers.market_data`, the provider the Explorer already
uses - the same shared simulated world, reached through the production data path.
Nothing here knows it is in a simulation (§115); what differs is what answers the
call, not what makes it.

Run directly as: python -m agents.trader <identity>
"""

from __future__ import annotations

import os
import statistics
import sys

from agents import discovery_config as config
from agents.base import run_agent
from backend import fi_db, trading
from providers.market_data import SyntheticMarketDataProvider

ROLE = "trader"

# How convinced the analysis has to be before the desk will act. Below it the
# idea is noted and not traded - a desk that took every judgement handed to it
# would not be deciding anything, which is the half directive section 11 gives it.
#
# **Measured, not guessed**, and the first value was a guess that made the role
# inert. Across 414 analyses in this project's run history the confidence this
# organization actually produces is: min 0.12, median 0.22, p75 0.25, max 0.60 -
# and only 4 of 414 reached 0.5. A floor at 0.5 therefore sat above the entire
# working distribution, so the desk declined every idea it was ever shown and
# looked like it was deciding.
#
# 0.25 is the observed upper quartile: the desk acts on roughly the top quarter
# of what the organization believes, which is a selection rather than everything
# or nothing. It moves when the distribution does.
CONVICTION_FLOOR = float(os.environ.get("FI_TRADER_CONVICTION_FLOOR", "0.25"))

# Vol points of exposure at full conviction. Small on purpose: this is a
# measurement of the process against a generated surface, not a bet.
MAX_SIZE = float(os.environ.get("FI_TRADER_MAX_SIZE", "1.0"))

# How far volatility must move before the desk takes the trade off. Symmetric,
# because a stop tighter than the target turns every position into a coin flip
# the trader is then blamed for.
EXIT_MOVE = float(os.environ.get("FI_TRADER_EXIT_MOVE", "0.01"))

# How many cycles a position may stay open. A trade nobody ever closes has no
# result, and an unattributed position is a judgement nobody is accountable for.
MAX_CYCLES_OPEN = int(os.environ.get("FI_TRADER_MAX_CYCLES_OPEN", "3"))


def _reference_iv(provider, security: str) -> float | None:
    """One number for where volatility is, from the surface every agent reads.

    The mean across the surface rather than a single point: a strike-specific
    level would make the trade depend on which strike the detector happened to
    flag, and the desk is trading the security's volatility rather than one point
    on its smile."""
    try:
        surface = provider.get_option_surface(security)
    except Exception:  # noqa: BLE001 - no surface is a data problem, not a crash
        return None
    ivs = [point.iv for point in surface.points]
    return round(statistics.fmean(ivs), 6) if ivs else None


def _side_for(thesis: str) -> str:
    """Which way to trade the analyst's conclusion.

    Read from the thesis text, which is what the analyst actually wrote. Crude
    and provisional: a model reading the thesis is Stage 3 work, and a missing
    decision is a Stage 1 problem. The default is `short_vol` because this
    pipeline detects volatility that has run *above* its peers - a high
    `peak_iv / baseline_iv` is what a detection means here - so the ordinary case
    is that the anomaly is richness."""
    lowered = (thesis or "").lower()
    cheap = any(word in lowered for word in ("cheap", "underpriced", "too low", "depressed"))
    return trading.SIDE_LONG_VOL if cheap else trading.SIDE_SHORT_VOL


def _agent_id_of(conn, identity: str) -> str:
    """The durable id behind this desk.

    A book keyed on the desk identity would be reassigned with the desk; keyed on
    the agent it follows the trader through a rename (TQ-97, TQ-99). Falls back
    to the identity when no assignment exists yet, so a trader that starts before
    its personnel record does still has a coherent book."""
    assignment = fi_db.current_assignment(conn, identity=identity)
    return (assignment or {}).get("agent_id") or identity


def _open_new_positions(conn, identity: str, agent_id: str, provider) -> int:
    """Act on judgements the desk has not seen yet.

    `place` refuses a second order against the same analysis, so this is
    idempotent without a claim - the desk acts on each judgement once, and no
    lease is needed for a queue nobody contends for."""
    placed = 0
    untraded = conn.fetchall(
        "SELECT r.id, r.security, r.thesis, r.confidence, r.report_id"
        " FROM analysis_results r"
        " LEFT JOIN trader_orders o ON o.analysis_result_id = r.id"
        " WHERE o.id IS NULL ORDER BY r.id DESC LIMIT 5")
    for result in untraded:
        confidence = result["confidence"]
        if confidence is not None and confidence < CONVICTION_FLOOR:
            # Noted and not traded. The desk declining is itself a decision.
            continue
        level = _reference_iv(provider, result["security"])
        if level is None:
            continue
        side = _side_for(result["thesis"])
        size = round(MAX_SIZE * (confidence if confidence is not None else 0.5), 4)
        if size <= 0:
            continue
        order_id = trading.place(
            conn, agent_id=agent_id, security=result["security"], side=side, size=size,
            analysis_result_id=result["id"], report_id=result["report_id"],
            thesis=(result["thesis"] or "").strip()[:400] or "no thesis was recorded",
            analysis_confidence=confidence, placed_by=identity)
        if order_id is None:
            continue
        trading.fill(conn, order_id, kind=trading.FILL_ENTRY, level=level)
        placed += 1
        print(f"[trader] {side} {size} vol on {result['security']} "
              f"at {level:.4f} (conviction {confidence})")
    return placed


def _manage_open_positions(conn, identity: str, provider, cycles: dict) -> int:
    """Mark what is open, and take off what has run its course."""
    closed = 0
    for order in trading.open_orders(conn):
        cycles[order["id"]] = cycles.get(order["id"], 0) + 1
        level = _reference_iv(provider, order["security"])
        if level is None:
            continue
        entry = trading.entry_level(conn, order["id"])
        moved = abs(level - entry) if entry is not None else 0.0
        if moved < EXIT_MOVE and cycles[order["id"]] < MAX_CYCLES_OPEN:
            continue

        unrealised = trading.mark(conn, order["id"], level)
        trading.fill(conn, order["id"], kind=trading.FILL_EXIT, level=level)
        trading.close(conn, order["id"])
        closed += 1
        print(f"[trader] closed {order['security']} at {level:.4f} for "
              f"{(unrealised if unrealised is not None else 0):+.4f} vol points")
    return closed


def _trader_work(conn, identity: str, agent_id: str, provider, cycles: dict) -> None:
    _open_new_positions(conn, identity, agent_id, provider)
    _manage_open_positions(conn, identity, provider, cycles)


def main() -> None:  # pragma: no cover - process entry point
    if len(sys.argv) != 2:
        print("usage: python -m agents.trader <identity>", file=sys.stderr)
        raise SystemExit(1)
    identity = sys.argv[1]
    anomalies = {security: {} for security in config.FORCE_ANOMALY_SECURITIES}
    anomalies.update(config.ANOMALY_SPEC)
    provider = SyntheticMarketDataProvider(
        seed=config.MARKET_PROVIDER_SEED, anomalies=anomalies, regime=config.MARKET_REGIME)
    cycles: dict = {}
    cache: dict = {}

    def work_fn(conn) -> None:
        if "agent_id" not in cache:
            cache["agent_id"] = _agent_id_of(conn, identity)
        _trader_work(conn, identity, cache["agent_id"], provider, cycles)

    run_agent(identity=identity, role=ROLE, work_fn=work_fn)


if __name__ == "__main__":  # pragma: no cover
    main()
