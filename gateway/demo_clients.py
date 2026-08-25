"""Simulated clients and holdings, for seeing the thing work (TQ-42,
docs/SPEC_RECONCILIATION.md §96).

Owner direction, 2026-08-26: *"simulate some clients and client holdings"*, and
*"use the simulated client data for now and remove it later before live"*.

The second half is the one that shapes this file. Demo data that is merely
*intended* to be removed is demo data that ships, because by the time anybody
looks for it nobody is certain which rows it was. So:

**Every simulated row is flagged, not named.** `client_holdings.simulated` and
`client_agents.simulated` carry it, so a demo client is identifiable rather than
guessed at from a naming convention somebody may have departed from.

**Clearing works by client, not by flag.** Talking to a demo client's agent
records holdings through the ordinary tool, which does not mark them simulated —
correctly, since the client did state them. Deleting only flagged rows left
those behind, orphaned to a customer who no longer existed. Anything owned by a
demo client is demo data, whatever route it arrived by.

**Seeding refuses outside a development stage.** The same gate, and the same
reasoning, as `backend/migrations.py`'s destructive hatches (§89): a convenience
that outlives its stage stops being a convenience. It fails closed when the
lifecycle stage cannot be read, because "I could not tell what stage this is"
must not resolve to "go ahead and invent some customers".

**There is a check that says whether any remains.** `outstanding()` is what a
pre-launch checklist calls, and what a test asserts — the difference between a
promise to clean up and a way to know.

## What these clients are

Names and positions invented here, holding this system's own synthetic symbols
(SYN1-SYN10) rather than real tickers. A demo portfolio of real companies is one
screenshot away from being read as advice about them.

Only `customer` can actually log in, because the Gateway has a single client
credential today. The rest exist as data — which is enough to show the property
that matters, that one client's representative cannot see another's positions.
Per-client credentials are a real gap and are queued as TQ-43 rather than faked
here.
"""

from __future__ import annotations

from gateway import client_agent, holdings
from backend.db import Database

# Development stages only. Same list and same reasoning as
# backend/migrations.DESTRUCTIVE_STAGES.
SEEDABLE_STAGES = ("PRE_ALPHA", "ALPHA")

# Synthetic symbols from this system's own universe, never real tickers: a demo
# portfolio of real companies is one screenshot away from being read as advice
# about them.
DEMO_CLIENTS: dict[str, list[dict]] = {
    # The one that can actually log in, because it matches GATEWAY_CLIENT_USER.
    "customer": [
        {"ticker": "SYN1", "shares": 400, "cost_basis": 42.50, "acquired_on": "2024-03-11"},
        {"ticker": "SYN3", "shares": 120, "cost_basis": 118.00, "acquired_on": "2024-09-02"},
        {"ticker": "SYN7", "shares": 250, "cost_basis": 61.25, "acquired_on": "2025-01-20"},
        {"ticker": "SYN10", "shares": 60, "cost_basis": 305.00, "acquired_on": "2025-06-30"},
    ],
    # Deliberately concentrated, so the concentration report has something true
    # and uncomfortable to say.
    "avery": [
        {"ticker": "SYN2", "shares": 3000, "cost_basis": 318.40, "acquired_on": "2023-11-05"},
        {"ticker": "SYN5", "shares": 90, "cost_basis": 180.10, "acquired_on": "2025-02-14"},
    ],
    # Deliberately missing a cost basis, so the "counted but not weighted" path
    # is exercised by real demo data rather than only by a test.
    "morgan": [
        {"ticker": "SYN4", "shares": 500, "cost_basis": 27.80, "acquired_on": "2024-06-18"},
        {"ticker": "SYN6", "shares": 75, "cost_basis": None,
         "note": "inherited; cost basis unknown"},
        {"ticker": "SYN9", "shares": 210, "cost_basis": 54.00, "acquired_on": "2025-04-09"},
    ],
}


class SeedRefused(RuntimeError):
    """Demo data was asked for somewhere it must not exist."""


def _require_development_stage() -> str:
    from backend import boot_config

    try:
        stage = boot_config.load().lifecycle_stage
    except Exception as exc:  # noqa: BLE001
        raise SeedRefused(
            f"refusing to seed demo clients: the boot configuration could not be read "
            f"({exc}), so the lifecycle stage is unknown."
        ) from exc
    if stage not in SEEDABLE_STAGES:
        raise SeedRefused(
            f"refusing to seed demo clients at lifecycle stage {stage}. Simulated "
            f"customers are a development convenience; allowed stages are "
            f"{', '.join(SEEDABLE_STAGES)}."
        )
    return stage


def seed(conn: Database) -> dict:
    """Create the demo clients and their holdings, all flagged simulated."""
    stage = _require_development_stage()
    created = {}
    for client_id, positions in DEMO_CLIENTS.items():
        agent = client_agent.ensure(conn, client_id)
        conn.execute("UPDATE client_agents SET simulated = 1 WHERE client_id = ?",
                     (client_id,))
        for position in positions:
            holdings.record(conn, client_id, simulated=True, **position)
        created[client_id] = {"agent": agent["name"], "positions": len(positions)}
    return {"stage": stage, "clients": created}


def simulated_clients(conn: Database) -> list[str]:
    """Every client this database considers demo data.

    The union of both flags, because they can disagree in one direction that
    matters: a holding recorded *during* a demo session arrives through the
    ordinary tool and is not flagged, since the client genuinely stated it. It
    is still demo data, and it belongs to a demo client."""
    ids = {r["client_id"] for r in conn.fetchall(
        "SELECT client_id FROM client_agents WHERE simulated = 1")}
    ids |= set(holdings.simulated_client_ids(conn))
    return sorted(ids)


def clear(conn: Database) -> dict:
    """Remove every simulated client, and everything belonging to them.

    This is the half of the owner's instruction that matters — "remove it later
    before live".

    Removal is **by client, not by row flag**, and that distinction was found by
    looking rather than by reasoning. Talking to a demo client's agent records
    holdings through the ordinary tool, which does not mark them simulated -
    correctly, because the client did state them. Deleting only flagged rows
    left those behind: an orphaned position belonging to a customer who no
    longer existed. Anything owned by a demo client is demo data, whatever route
    it arrived by.

    Still driven by the flags rather than by `DEMO_CLIENTS`, so a demo client
    added by hand is cleared too, and a real client is never touched."""
    targets = simulated_clients(conn)
    if not targets:
        return {"clients_removed": 0, "holdings_removed": 0, "agents_removed": 0}

    placeholders = ",".join("?" * len(targets))
    holdings_removed = conn.execute_returning_rowcount(
        f"DELETE FROM client_holdings WHERE client_id IN ({placeholders})", tuple(targets))
    agents_removed = conn.execute_returning_rowcount(
        f"DELETE FROM client_agents WHERE client_id IN ({placeholders})", tuple(targets))
    return {"clients_removed": len(targets), "holdings_removed": holdings_removed,
            "agents_removed": agents_removed}


def outstanding(conn: Database) -> dict:
    """Whether any simulated client data is still present.

    The difference between intending to clean up and being able to check. A
    pre-launch step calls this; so does a test."""
    present = simulated_clients(conn)
    return {
        "clean": not present,
        "simulated_clients": present,
        "note": ("No simulated client data is present." if not present else
                 f"{len(present)} simulated client(s) still present: "
                 f"{', '.join(present)}. Clear before going live."),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    from dotenv import load_dotenv

    load_dotenv()

    from gateway import store

    parser = argparse.ArgumentParser(
        prog="python -m gateway.demo_clients",
        description="Simulated clients and holdings for development (TQ-42, §96).")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="create the demo clients and their holdings")
    sub.add_parser("clear", help="remove every simulated client and holding")
    sub.add_parser("status", help="report whether any simulated data is present")
    sub.add_parser("show", help="print each demo client's holdings and concentration")
    args = parser.parse_args(argv)

    conn = store.get_connection()
    store.init_schema(conn)
    try:
        if args.command == "seed":
            try:
                outcome = seed(conn)
            except SeedRefused as refusal:
                print(f"refused: {refusal}")
                return 1
            print(f"seeded at stage {outcome['stage']}:")
            for client_id, detail in outcome["clients"].items():
                print(f"  {client_id}: {detail['positions']} position(s), "
                      f"represented by {detail['agent']}")
            return 0

        if args.command == "clear":
            outcome = clear(conn)
            print(f"removed {outcome['clients_removed']} client(s): "
                  f"{outcome['holdings_removed']} holding(s) and "
                  f"{outcome['agents_removed']} agent(s)")
            print(outstanding(conn)["note"])
            return 0

        if args.command == "status":
            report = outstanding(conn)
            print(report["note"])
            return 0 if report["clean"] else 1

        if args.command == "show":
            for client_id in holdings.simulated_client_ids(conn) or []:
                agent = client_agent.load(conn, client_id)
                print(f"--- {client_id} (represented by "
                      f"{agent['name'] if agent else 'nobody'}) ---")
                for row in holdings.listing(conn, client_id):
                    cost = "unknown" if row["cost_basis"] is None else f"{row['cost_basis']:.2f}"
                    print(f"  {row['ticker']:<6} {row['shares']:>8.0f} shares @ {cost}")
                report = holdings.concentration(conn, client_id)
                print(f"  positions {report['positions']}, cost {report['known_cost']}, "
                      f"top three {report['top_three_pct']}%")
                if report.get("missing_cost_note"):
                    print(f"  {report['missing_cost_note']}")
            return 0

        raise AssertionError(f"unhandled command {args.command!r}")  # pragma: no cover
    finally:
        conn.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
