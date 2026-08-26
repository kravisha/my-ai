"""The imaginary clients — training fixtures, and the logins that let you walk
into them (TASK_QUEUE TQ-42, docs/SPEC_RECONCILIATION.md §96; **reframed by
§114, custody removed by TQ-72/§111**).

## What these are now

They were *demo data awaiting deletion*. Owner direction, 2026-08-26 (§96):
*"use the simulated client data for now and remove it later before live"*, and
this file was built around the second half of that sentence.

§114 changed what they are:

> *"If only holds simulated data, that means the whole process is a simulation.
> Agents are being trained and we need simulation exercises for simulated
> requests for portfolio analysis from imaginary clients as part of training."*

They are **training fixtures**. They do not get deleted, because the curriculum
needs them next year as much as it does today.

## Two opposite policies wore one flag, and they have been separated

That reframing collided with the reason this file exists. `simulated` marked two
different things:

- **contamination** — simulated data that must be gone before a real client
  exists; and
- **fixtures** — imaginary clients the Department of Education practises on,
  which must still be there in a year.

`outstanding()` used to ask *"is any simulated client data present?"* and call
any of it unclean. Under §114 the honest question is **"is there simulated data
outside the training environment?"**, and the lazy way to get there — widening
the check to ignore anything tagged training — would recreate §100's finding
exactly: a clean report that is not true, which is the one a pre-launch checklist
believes.

So the split is drawn where it can be checked rather than asserted. A **login**
is contamination: a credential that can reach this system from outside is real
whatever it is labelled, and one left behind before launch is a way in. A
**portfolio fixture** is not, and cannot be: since §111 there is nowhere for a
portfolio to be stored, so `SIMULATED_PORTFOLIOS` is a constant in
`backend/portfolio_providers.py` that no client can log into.

`outstanding()` therefore reports on **logins and representatives**, which is
what it can see and what actually matters, and says so rather than implying it
checked everything.

## What seeding does now

It creates the logins and the representatives, and stops. It used to also create
a portfolio and seed positions into it; there is no portfolio to create (§111),
and the positions are a constant the simulated provider returns when asked.

So the demo is *walk-into-able* exactly as before — three clients, three
passwords, three agents — and the portfolios arrive the way a real one will: by
being fetched when somebody asks for an analysis, not by sitting in a table
waiting.

## Seeding still refuses outside a development stage

Unchanged, and the reasoning is unchanged: the same gate as
`backend/migrations.py`'s destructive hatches (§89), failing closed when the
lifecycle stage cannot be read, because *"I could not tell what stage this is"*
must not resolve to *"go ahead and invent some customers"*.

That matters more rather than less now that the fixtures are permanent. Fixtures
that live forever are fixtures nobody re-examines, and the gate is what keeps
"forever" meaning "in the training environment" rather than "everywhere".
"""

from __future__ import annotations

from backend.db import Database
from gateway import client_agent, clients

# Development stages only. Same list and same reasoning as
# backend/migrations.DESTRUCTIVE_STAGES.
SEEDABLE_STAGES = ("PRE_ALPHA", "ALPHA")

# Fixed, and only for these clients: a demonstration you cannot log into twice is
# not one. Real clients get a generated password shown once (gateway/clients.py);
# this is a convenience for accounts that exist to be practised on.
DEMO_PASSWORD = "demo-client-password"

# Who the imaginary clients are. Their *positions* live in
# `backend/portfolio_providers.SIMULATED_PORTFOLIOS`, because a simulated source
# is answered by the simulated provider - keeping a second copy here would be two
# descriptions of one fixture, and the one that drifts is the one nobody looks at.
DEMO_CLIENTS: tuple[str, ...] = ("customer", "avery", "morgan")


class SeedRefused(RuntimeError):
    """Imaginary clients were asked for somewhere they must not exist."""


def _require_development_stage() -> str:
    from backend import boot_config

    try:
        stage = boot_config.load().lifecycle_stage
    except Exception as exc:  # noqa: BLE001
        raise SeedRefused(
            f"refusing to seed imaginary clients: the boot configuration could not be "
            f"read ({exc}), so the lifecycle stage is unknown."
        ) from exc
    if stage not in SEEDABLE_STAGES:
        raise SeedRefused(
            f"refusing to seed imaginary clients at lifecycle stage {stage}. They are a "
            f"training convenience; allowed stages are {', '.join(SEEDABLE_STAGES)}."
        )
    return stage


def seed(conn: Database) -> dict:
    """Create the imaginary clients' logins and representatives.

    No portfolio is created and no position is written. There is nowhere to write
    one (§111), and there does not need to be: the positions are a constant the
    simulated provider returns when an analysis asks for them, which is how a
    real client's will arrive too."""
    stage = _require_development_stage()
    created = {}
    for client_id in DEMO_CLIENTS:
        if clients.get(conn, client_id) is None:
            clients.register(conn, client_id, display_name=client_id.title(),
                             password=DEMO_PASSWORD, simulated=True)
        agent = client_agent.ensure(conn, client_id)
        conn.execute("UPDATE client_agents SET simulated = 1 WHERE client_id = ?",
                     (client_id,))
        created[client_id] = {"agent": agent["name"]}
    return {"stage": stage, "clients": created, "password": DEMO_PASSWORD}


def simulated_clients(conn: Database) -> list[str]:
    """Every simulated client *login* this Gateway holds.

    Both flags, because they can disagree: a representative created for a client
    whose registration was removed by hand is still a simulated agent, and the
    union catches it.

    The third source this used to consult - portfolios flagged simulated - is
    gone with the portfolios (§111). Its absence costs nothing, and that is
    checkable rather than hopeful: it existed to catch a simulated portfolio
    whose client registration had been deleted, and there are no stored
    portfolios for such a row to be."""
    ids = {r["client_id"] for r in conn.fetchall(
        "SELECT client_id FROM client_agents WHERE simulated = 1")}
    ids |= {r["client_id"] for r in conn.fetchall(
        "SELECT client_id FROM clients WHERE simulated = 1")}
    return sorted(ids)


def clear(conn: Database) -> dict:
    """Remove every simulated client login and representative.

    This is the half of the owner's original instruction that survives §114 -
    *"remove it later before live"* - narrowed to the thing it was always really
    about. **A login is a way in.** A credential that can reach this system from
    outside is real whatever it is labelled, and one left behind at launch is an
    open door.

    The portfolio fixtures are not cleared and cannot be: they are a constant in
    `backend/portfolio_providers.py`, not data. Clearing the logins is what stops
    anybody logging in as one of them."""
    targets = simulated_clients(conn)
    if not targets:
        return {"clients_removed": 0, "agents_removed": 0, "logins_removed": 0,
                "legacy_removed": 0}

    placeholders = ",".join("?" * len(targets))
    agents_removed = conn.execute_returning_rowcount(
        f"DELETE FROM client_agents WHERE client_id IN ({placeholders})", tuple(targets))
    logins_removed = conn.execute_returning_rowcount(
        f"DELETE FROM clients WHERE client_id IN ({placeholders})", tuple(targets))
    return {"clients_removed": len(targets), "agents_removed": agents_removed,
            "logins_removed": logins_removed,
            "legacy_removed": _clear_archives(conn, targets)}


# The retired holdings tables, all of them in gateway.db - that database's own
# history, renamed rather than dropped as each migration ran (§99, §100, §110),
# plus `*_pre72` if this build archived a portfolio table an older one left here.
#
# A list rather than hand-written blocks, because the count keeps growing and the
# failure mode is a new archive nobody adds a clearing step for - which is
# exactly how §100's finding happened.
_ARCHIVES_BY_CLIENT = ("client_holdings_legacy",)
_ARCHIVES_BY_PORTFOLIO = ("portfolio_holdings_pre45", "portfolio_holdings_pre69",
                          "portfolio_holdings_pre72", "portfolios_pre69",
                          "portfolios_pre72")


def _table_exists(conn: Database, name: str) -> bool:
    return conn.fetchone(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,)) is not None


def _clear_archives(conn: Database, client_ids: list[str]) -> int:
    """Remove simulated rows from every retired holdings table.

    Keeping a copy for diagnosis is not a reason to keep simulated *customers*.
    Found by looking rather than by reasoning (§100): after the TQ-45a rename,
    `clear()` emptied the live table and `outstanding()` reported "No simulated
    client data is present" while ten demo holdings sat in
    `portfolio_holdings_pre45`. A clean report that is not true is worse than no
    report, because it is the one a pre-launch checklist believes.

    The portfolio-keyed archives can no longer be reached by client id, because
    the live table that mapped one to the other is gone. **They are reported as
    unreachable rather than silently skipped** - TQ-71 disposes of them
    deliberately, and a checklist should know they are there."""
    removed = 0
    for table in _ARCHIVES_BY_CLIENT:
        if client_ids and _table_exists(conn, table):
            placeholders = ",".join("?" * len(client_ids))
            removed += conn.execute_returning_rowcount(
                f"DELETE FROM {table} WHERE client_id IN ({placeholders})",
                tuple(client_ids))
    return removed


def unreachable_archives(conn: Database) -> list[str]:
    """Retired tables holding client financial records that this build can no
    longer clear selectively.

    They are keyed by `portfolio_id`, and the live table that mapped a portfolio
    to its owner is gone (§111). So "delete this client's archived rows" is a
    question nothing here can answer any more.

    Reported rather than ignored. A pre-launch check that could not see them
    would be exactly §100's clean-report-that-is-not-true, and dropping them
    automatically would be this system destroying client financial records to
    tidy up after its own architectural change. TQ-71 disposes of them
    deliberately."""
    return [t for t in _ARCHIVES_BY_PORTFOLIO if _table_exists(conn, t)]


def outstanding(conn: Database) -> dict:
    """Whether any simulated client can still log in.

    The difference between intending to clean up and being able to check. A
    pre-launch step calls this; so does a test.

    **It reports on logins and representatives, and says so.** §114 made the
    portfolio fixtures permanent training data rather than contamination, and
    §111 removed the stored portfolios entirely - so this checks the thing that
    is both checkable and dangerous: whether a credential exists that can reach
    this system from outside."""
    present = simulated_clients(conn)
    archives = unreachable_archives(conn)
    notes = []
    if present:
        notes.append(f"{len(present)} simulated client login(s) still present: "
                     f"{', '.join(present)}. Clear before going live.")
    else:
        notes.append("No simulated client logins are present.")
    if archives:
        notes.append(
            f"{len(archives)} retired holdings table(s) remain and cannot be cleared by "
            f"client: {', '.join(archives)}. They hold client financial records from "
            "before this system stopped storing portfolios; TQ-71 disposes of them.")
    return {
        "clean": not present and not archives,
        "checked": "logins and representatives",
        "simulated_clients": present,
        "unreachable_archives": archives,
        "note": " ".join(notes),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    from dotenv import load_dotenv

    load_dotenv()

    from gateway import store

    parser = argparse.ArgumentParser(
        prog="python -m gateway.demo_clients",
        description="Imaginary clients for training (TQ-42, §96; §114).")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="create the imaginary clients and their representatives")
    sub.add_parser("clear", help="remove every simulated client login")
    sub.add_parser("status", help="report whether any simulated login is present")
    sub.add_parser("show", help="print each imaginary client's fixture portfolio")
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
                print(f"  {client_id}: represented by {detail['agent']}")
            print(f"all of them log in with the password: {outcome['password']}")
            print("their portfolios are fixtures, fetched when an analysis asks for "
                  "them - nothing was written.")
            return 0

        if args.command == "clear":
            outcome = clear(conn)
            print(f"removed {outcome['clients_removed']} client(s): "
                  f"{outcome['agents_removed']} agent(s), "
                  f"{outcome['logins_removed']} login(s)")
            print(outstanding(conn)["note"])
            return 0

        if args.command == "status":
            report = outstanding(conn)
            print(report["note"])
            return 0 if report["clean"] else 1

        if args.command == "show":
            # Read straight from the fixtures. Nothing is fetched and nothing is
            # stored - this prints what the simulated provider would answer.
            from backend import holdings, portfolio_providers

            for client_id in DEMO_CLIENTS:
                agent = client_agent.load(conn, client_id)
                print(f"--- {client_id} (represented by "
                      f"{agent['name'] if agent else 'nobody'}) ---")
                source = portfolio_providers.Source(
                    provider_type=portfolio_providers.portfolios.PROVIDER_SIMULATED,
                    name=f"{client_id}-simulated", owner_hint=client_id)
                provider = portfolio_providers.for_source(source)
                positions = provider.get_holdings(source)
                for row in positions:
                    cost = ("unknown" if row.average_cost is None
                            else f"{row.average_cost:.2f}")
                    print(f"  {row.symbol:<9} {row.quantity:>8.0f} @ {cost} "
                          f"({row.asset_class})")
                balances = provider.get_balances(source)
                print(f"  cash {balances['cash']:.2f} {balances['currency']} (simulated)")
                report = holdings.concentration(positions)
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
