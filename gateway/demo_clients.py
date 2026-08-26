"""Simulated clients and holdings, for seeing the thing work (TQ-42,
docs/SPEC_RECONCILIATION.md §96).

Owner direction, 2026-08-26: *"simulate some clients and client holdings"*, and
*"use the simulated client data for now and remove it later before live"*.

The second half is the one that shapes this file. Demo data that is merely
*intended* to be removed is demo data that ships, because by the time anybody
looks for it nobody is certain which rows it was. So:

**Every simulated row is flagged, not named.** `portfolio_holdings.simulated` and
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

All three can log in, each as themselves. That stopped being a gap when TQ-43
gave clients a registry (§98) — before it they shared one credential and
therefore one subject, so the demo could show isolation in the data and not at
the door. Seeding now registers each client with a generated password, printed
once, so the isolation can be *walked into* rather than only asserted.

The passwords are fixed for demo clients and only for them, because a
demonstration you cannot log into twice is not one. `DEMO_PASSWORD` is not a
secret and is not a pattern for real clients, whose passwords are generated and
shown once by `python -m gateway.clients add`.
"""

from __future__ import annotations

from gateway import client_agent, clients, holdings, portfolios
from backend.db import Database

# Development stages only. Same list and same reasoning as
# backend/migrations.DESTRUCTIVE_STAGES.
SEEDABLE_STAGES = ("PRE_ALPHA", "ALPHA")

# Synthetic symbols from this system's own universe, never real tickers: a demo
# portfolio of real companies is one screenshot away from being read as advice
# about them.
# Fixed, and only for demo clients: a demonstration you cannot log into twice is
# not one. Real clients get a generated password shown once (gateway/clients.py);
# this is a convenience for data that is going to be deleted.
DEMO_PASSWORD = "demo-client-password"

DEMO_CLIENTS: dict[str, list[dict]] = {
    "customer": [
        {"symbol": "SYN1", "quantity": 400, "average_cost": 42.50, "acquired_on": "2024-03-11"},
        {"symbol": "SYN3", "quantity": 120, "average_cost": 118.00, "acquired_on": "2024-09-02"},
        {"symbol": "SYN7", "quantity": 250, "average_cost": 61.25, "acquired_on": "2025-01-20"},
        {"symbol": "SYN10", "quantity": 60, "average_cost": 305.00, "acquired_on": "2025-06-30"},
    ],
    # Deliberately concentrated, so the concentration report has something true
    # and uncomfortable to say.
    "avery": [
        {"symbol": "SYN2", "quantity": 3000, "average_cost": 318.40, "acquired_on": "2023-11-05"},
        {"symbol": "SYN5", "quantity": 90, "average_cost": 180.10, "acquired_on": "2025-02-14"},
    ],
    # Deliberately missing a cost basis, so the "counted but not weighted" path
    # is exercised by real demo data rather than only by a test.
    "morgan": [
        {"symbol": "SYN4", "quantity": 500, "average_cost": 27.80, "acquired_on": "2024-06-18"},
        {"symbol": "SYN6", "quantity": 75, "average_cost": None,
         "note": "inherited; cost basis unknown"},
        {"symbol": "SYN9", "quantity": 210, "average_cost": 54.00, "acquired_on": "2025-04-09"},
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
        if clients.get(conn, client_id) is None:
            clients.register(conn, client_id, display_name=client_id.title(),
                             password=DEMO_PASSWORD, simulated=True)
        agent = client_agent.ensure(conn, client_id)
        conn.execute("UPDATE client_agents SET simulated = 1 WHERE client_id = ?",
                     (client_id,))
        # Through the same gate the client's own representative uses (TQ-44), so
        # the demo exercises the real path rather than a seeding shortcut beside
        # it. A seeder that wrote holdings directly would be the one caller whose
        # ownership was never checked.
        portfolio = portfolios.primary_for(
            conn, portfolios.for_client(client_id), simulated=True)
        for position in positions:
            holdings.record(conn, portfolio, simulated=True, **position)
        created[client_id] = {"agent": agent["name"], "positions": len(positions),
                              "portfolio": portfolio["portfolio_id"]}
    return {"stage": stage, "clients": created, "password": DEMO_PASSWORD}


def simulated_clients(conn: Database) -> list[str]:
    """Every client this database considers demo data.

    The union of both flags, because they can disagree in one direction that
    matters: a holding recorded *during* a demo session arrives through the
    ordinary tool and is not flagged, since the client genuinely stated it. It
    is still demo data, and it belongs to a demo client."""
    ids = {r["client_id"] for r in conn.fetchall(
        "SELECT client_id FROM client_agents WHERE simulated = 1")}
    ids |= {r["client_id"] for r in conn.fetchall(
        "SELECT client_id FROM clients WHERE simulated = 1")}
    ids |= set(portfolios.simulated_client_ids(conn))
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
        return {"clients_removed": 0, "holdings_removed": 0, "agents_removed": 0,
                "portfolios_removed": 0, "legacy_removed": 0}

    holdings_removed = 0
    portfolios_removed = 0
    # Gathered *before* the portfolios are purged, because the pre-TQ-45 archive
    # is keyed by portfolio id and there is no way back to it afterwards.
    demo_portfolio_ids: list[str] = []
    for client_id in targets:
        owner = portfolios.for_client(client_id)
        # `owned`, not `listing`: an archived demo portfolio is still demo data,
        # and a listing that showed only active ones would leave it behind with
        # its holdings intact. Both are owner-scoped queries, so each portfolio
        # here is already proven to belong to this client.
        for portfolio in portfolios.owned(conn, owner):
            demo_portfolio_ids.append(portfolio["portfolio_id"])
            holdings_removed += holdings.forget_all(conn, portfolio)
        portfolios_removed += portfolios.purge_owner(conn, owner)

    placeholders = ",".join("?" * len(targets))
    agents_removed = conn.execute_returning_rowcount(
        f"DELETE FROM client_agents WHERE client_id IN ({placeholders})", tuple(targets))
    logins_removed = conn.execute_returning_rowcount(
        f"DELETE FROM clients WHERE client_id IN ({placeholders})", tuple(targets))
    return {"clients_removed": len(targets), "holdings_removed": holdings_removed,
            "agents_removed": agents_removed, "logins_removed": logins_removed,
            "portfolios_removed": portfolios_removed,
            "legacy_removed": _clear_archives(conn, targets, demo_portfolio_ids)}


def _clear_archives(conn: Database, client_ids: list[str],
                    portfolio_ids: list[str]) -> int:
    """Remove demo rows from every retired holdings table.

    Keeping a copy for diagnosis (TQ-44 spec §10 Q2) is not a reason to keep
    simulated *customers*. Found by looking rather than by reasoning: after the
    TQ-45a rename, `clear()` emptied the live table and `outstanding()` reported
    "No simulated client data is present" while ten demo holdings sat in
    `portfolio_holdings_pre45`. A clean report that is not true is worse than no
    report, because it is the one a pre-launch checklist believes.

    The two archives are keyed differently, which is the whole reason this is
    easy to get half-right: the pre-TQ-44 table is keyed by *client*, and the
    pre-TQ-45 one by *portfolio* - so the portfolio ids have to be collected
    before the portfolios are purged."""
    removed = 0
    if client_ids and holdings._table_exists(conn, holdings.LEGACY_ARCHIVE):
        placeholders = ",".join("?" * len(client_ids))
        removed += conn.execute_returning_rowcount(
            f"DELETE FROM {holdings.LEGACY_ARCHIVE} WHERE client_id IN ({placeholders})",
            tuple(client_ids))
    if portfolio_ids and holdings._table_exists(conn, holdings.PRE_45_ARCHIVE):
        placeholders = ",".join("?" * len(portfolio_ids))
        removed += conn.execute_returning_rowcount(
            f"DELETE FROM {holdings.PRE_45_ARCHIVE} WHERE portfolio_id IN ({placeholders})",
            tuple(portfolio_ids))
    return removed


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
            print(f"all of them log in with the password: {outcome['password']}")
            return 0

        if args.command == "clear":
            outcome = clear(conn)
            print(f"removed {outcome['clients_removed']} client(s): "
                  f"{outcome['holdings_removed']} holding(s), "
                  f"{outcome['agents_removed']} agent(s), "
                  f"{outcome['logins_removed']} login(s)")
            print(outstanding(conn)["note"])
            return 0

        if args.command == "status":
            report = outstanding(conn)
            print(report["note"])
            return 0 if report["clean"] else 1

        if args.command == "show":
            for client_id in portfolios.simulated_client_ids(conn) or []:
                agent = client_agent.load(conn, client_id)
                print(f"--- {client_id} (represented by "
                      f"{agent['name'] if agent else 'nobody'}) ---")
                portfolio = portfolios.primary_for(conn, portfolios.for_client(client_id))
                print(f"  portfolio {portfolio['portfolio_id']} "
                      f"({portfolio['data_mode']}, priced: "
                      f"{portfolios.is_priced(portfolio)})")
                for row in holdings.listing(conn, portfolio):
                    cost = ("unknown" if row["average_cost"] is None
                            else f"{row['average_cost']:.2f}")
                    print(f"  {row['symbol']:<6} {row['quantity']:>8.0f} @ {cost} "
                          f"({row['asset_class']})")
                report = holdings.concentration(conn, portfolio)
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
