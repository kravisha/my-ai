"""Moving the portfolio subsystem's data from `gateway.db` into
`financial_intelligence.db` (TASK_QUEUE TQ-69, docs/SPEC_RECONCILIATION.md §110).

Source: owner direction 2026-08-26 (§109); spec §6, §11 Risk 1.

## This is the dangerous part, and it is dangerous in a specific way

Every other migration in this project moves rows between *tables*. This one moves
live client financial records between **databases**, which means the usual
safety - one transaction - is not available. Two files cannot be written
atomically, so the ordering has to supply what the transaction cannot:

1. bring the source to the current shape (the two pre-TQ-69 migrations),
2. copy into the destination, inside the destination's transaction,
3. **verify while the source is still intact**, and
4. only then rename the source tables away.

Step 3 before step 4 is the whole design. If verification fails, the destination
transaction has already rolled back and the source has not been touched, so the
system is exactly where it started - which is what "nothing was changed" has to
mean when it cannot be guaranteed by a single commit.

## Nothing is re-keyed, restamped or re-owned

Spec §6.3, and it is the rule this file exists to keep: *a migration that
restamps or re-keys anything has changed whose data it is.* `portfolio_id`,
`owner_type`, `owner_id`, `as_of`, `created_at`, `simulated` and every other
column land exactly as they left. There is no `INSERT ... VALUES (?, ?, now())`
anywhere here, and no defaulting: a column the source did not have is not one
this build may invent a value for.

That is also why the copy is written column by column rather than by
`SELECT *`. An explicit list fails loudly if the two shapes ever disagree; a
star would quietly copy whatever happened to be there in whatever order the
table was created in.

## Verification is by ownership, not by count

Counts are checked, and they are the weakest of the three checks. The one that
matters is that **every migrated portfolio is still reachable by the owner it
had**, asserted through `portfolios.owned()` - an owner-scoped query, so it is
proof about the owner rather than about the row. A migration that landed every
row and silently swapped two owners would pass a count check perfectly, and it
would be the worst possible outcome of this increment.

`owned()` rather than `resolve()`, deliberately: `resolve` refuses an archived
portfolio, correctly, so verifying with it would report a successfully migrated
archived portfolio as a failure - or, worse, tempt somebody to skip archived rows
and leave them behind.

## The source tables are renamed, never dropped

`portfolios_pre69` and `portfolio_holdings_pre69`, following
`client_holdings_legacy` (§99) and `portfolio_holdings_pre45` (§100). That makes
the migration idempotent by construction rather than by a flag - a second run
finds no `portfolios` table to read - and it means the copy can be compared
against its source after the fact, which is the only way anybody could ever
answer "did this move the data correctly?" a week later.

**Three legacy tables then exist in a fully migrated gateway.db.** That is now
worth its own deliberate decision rather than continued accumulation; it is
recorded in TASK_QUEUE.md rather than fixed here, because dropping a table
holding client financial records is not a side effect of moving one.

## Resuming an interrupted run

The window between step 2's commit and step 4's rename is real: a process killed
there leaves the rows in both places, with the source still named `portfolios`.
A naive re-run would try to copy them again and fail on the primary key.

So this checks first. If *every* source portfolio is already in the destination
with the same owner, the copy is skipped and the rename is completed - finishing
the job rather than redoing it. If only *some* are, it refuses and says so:
a half-copied state is one a person should look at, not one a script should
resolve by guessing which half is right.
"""

from __future__ import annotations

from pathlib import Path

from backend import holdings, migrations, portfolios
from backend.db import Database

PRE_69_PORTFOLIOS = "portfolios_pre69"
PRE_69_HOLDINGS = "portfolio_holdings_pre69"

# The columns, named rather than starred, in the order both schemas declare them.
# See the module docstring: an explicit list fails loudly when the two shapes
# disagree, which is the only moment anybody would want to know.
_PORTFOLIO_COLUMNS = (
    "portfolio_id", "owner_type", "owner_id", "portfolio_type", "display_name",
    "provider_type", "provider_account_ref", "data_mode", "status", "created_at",
    "updated_at", "last_synced_at", "simulated", "schema_version",
)
_HOLDING_COLUMNS = (
    "portfolio_id", "symbol", "quantity", "average_cost", "asset_class",
    "acquired_on", "note", "as_of", "simulated", "schema_version",
)

# One exception type for "the migration would not have been safe, and nothing was
# changed". Imported rather than redefined: two exception names for one outcome
# would mean a caller has to catch both to be correct, and the one that gets
# forgotten is the one that fires.
MigrationRefused = holdings.MigrationRefused


def _rows(conn: Database, table: str, columns: tuple[str, ...], order: str) -> list[dict]:
    return [dict(row) for row in conn.fetchall(
        f"SELECT {', '.join(columns)} FROM {table} ORDER BY {order}")]


def _insert(conn: Database, table: str, columns: tuple[str, ...], row: dict) -> None:
    conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' * len(columns))})",
        tuple(row[column] for column in columns))


def _already_there(fi_conn: Database, source: list[dict]) -> list[dict]:
    """Which source portfolios the destination already holds, matched on id.

    Returned as the destination's own rows, not the source's, because the
    interesting question is whether they *agree* - and comparing a row against
    itself would answer yes."""
    if not source:
        return []
    ids = [row["portfolio_id"] for row in source]
    placeholders = ",".join("?" * len(ids))
    return [dict(row) for row in fi_conn.fetchall(
        f"SELECT {', '.join(_PORTFOLIO_COLUMNS)} FROM portfolios "
        f"WHERE portfolio_id IN ({placeholders})", tuple(ids))]


def _verify_owners(fi_conn: Database, source: list[dict]) -> None:
    """Every migrated portfolio is reachable by the owner it had.

    The check the whole file is for, and the one a count cannot make. Owner-scoped
    through `portfolios.owned`, so what is proven is a statement about the owner:
    *this owner can reach this portfolio*, which is exactly what the guard is
    supposed to mean and exactly what a swapped owner would break.

    Grouped by owner so `owned()` is called once per owner rather than once per
    portfolio, and so the failure message can say whose data went missing."""
    by_owner: dict[tuple[str, str], set[str]] = {}
    for row in source:
        by_owner.setdefault((row["owner_type"], row["owner_id"]), set()).add(
            row["portfolio_id"])

    for (owner_type, owner_id), expected in by_owner.items():
        try:
            owner = portfolios.OwnerContext(owner_type, owner_id)
        except portfolios.UnknownVocabulary as unknown:
            # A stored owner_type this build cannot interpret. It arrived that
            # way; the migration will not quietly normalise it into something
            # readable, because "readable" would mean choosing an owner.
            raise MigrationRefused(
                f"portfolio(s) {sorted(expected)} are stored under an owner this build "
                f"cannot interpret ({unknown}); rolling back and changing nothing.") from None
        reachable = {p["portfolio_id"] for p in portfolios.owned(fi_conn, owner)}
        missing = expected - reachable
        if missing:
            raise MigrationRefused(
                f"after the copy, {owner_type}/{owner_id} could not reach "
                f"{sorted(missing)}; rolling back and changing nothing.")


def _rename_source(gateway_conn: Database) -> None:
    with gateway_conn.transaction():
        gateway_conn.execute(f"ALTER TABLE portfolios RENAME TO {PRE_69_PORTFOLIOS}")
        gateway_conn.execute(
            f"ALTER TABLE portfolio_holdings RENAME TO {PRE_69_HOLDINGS}")


def migrate(gateway_conn: Database, fi_conn: Database) -> dict:
    """Move portfolios and their holdings from the Gateway's database to the
    backend's.

    Both connections are arguments rather than opened here, so the whole thing
    can be pointed at a **copy** of a seeded database - which is the standing
    rule for any migration in this project (§99, §100) and the one that matters
    most for this one.

    Returns what it did. A no-op says so rather than reporting success, because
    "migrated: true" about a database that had nothing to migrate is the kind of
    clean report §100 already caught being untrue once."""
    if not migrations.table_exists(gateway_conn, "portfolios"):
        return {"migrated": False, "reason": "no portfolios table in the Gateway database",
                "portfolios": 0, "holdings": 0}
    if migrations.table_exists(gateway_conn, PRE_69_PORTFOLIOS) or \
            migrations.table_exists(gateway_conn, PRE_69_HOLDINGS):
        raise MigrationRefused(
            f"both 'portfolios' and {PRE_69_PORTFOLIOS!r} (or their holdings tables) "
            "exist, which means an earlier move did not finish. Refusing rather than "
            "overwriting the archived copy - inspect both and remove one deliberately.")

    # The source has to be at the current shape before it can be copied. A
    # database that never ran TQ-44 has holdings keyed by client; one that never
    # ran TQ-45a has them under `ticker`/`shares`. Copying either would move
    # columns whose meaning this build no longer holds.
    legacy = holdings.migrate_client_holdings(gateway_conn)
    renamed = holdings.migrate_holding_field_names(gateway_conn)

    source_portfolios = _rows(gateway_conn, "portfolios", _PORTFOLIO_COLUMNS, "portfolio_id")
    source_holdings = _rows(gateway_conn, "portfolio_holdings", _HOLDING_COLUMNS,
                            "portfolio_id, symbol")

    existing = _already_there(fi_conn, source_portfolios)
    if existing and len(existing) == len(source_portfolios):
        # An interrupted run that got as far as committing the copy. Finish it
        # rather than redo it - but only after confirming the destination agrees
        # about who owns what, since "the id is there" is not the same fact.
        _verify_owners(fi_conn, source_portfolios)
        _rename_source(gateway_conn)
        return {"migrated": True, "resumed": True,
                "portfolios": len(source_portfolios), "holdings": len(source_holdings),
                "archived_tables": [PRE_69_PORTFOLIOS, PRE_69_HOLDINGS],
                "pre_tq44": legacy, "pre_tq45a": renamed}
    if existing:
        raise MigrationRefused(
            f"{len(existing)} of {len(source_portfolios)} portfolio(s) are already in the "
            "backend database and the rest are not. That is a half-finished move, and "
            "resolving it means deciding which copy is right - which is a person's "
            "decision, not this script's. Nothing was changed.")

    with fi_conn.transaction():
        for row in source_portfolios:
            _insert(fi_conn, "portfolios", _PORTFOLIO_COLUMNS, row)
        for row in source_holdings:
            _insert(fi_conn, "portfolio_holdings", _HOLDING_COLUMNS, row)

        # Verified inside the transaction, so a failure rolls the copy back and
        # leaves the source - which has not been renamed yet - untouched.
        landed_portfolios = fi_conn.fetchone(
            "SELECT COUNT(*) AS n FROM portfolios")["n"]
        landed_holdings = fi_conn.fetchone(
            "SELECT COUNT(*) AS n FROM portfolio_holdings")["n"]
        if landed_portfolios != len(source_portfolios):
            raise MigrationRefused(
                f"move would have landed {len(source_portfolios)} portfolio(s) but the "
                f"destination holds {landed_portfolios}; rolling back and changing nothing.")
        if landed_holdings != len(source_holdings):
            raise MigrationRefused(
                f"move would have landed {len(source_holdings)} holding(s) but the "
                f"destination holds {landed_holdings}; rolling back and changing nothing.")

        # No holding changed portfolio, and no portfolio changed owner. Compared
        # row against row rather than count against count: §6.4 asks for ids and
        # owners preserved *exactly*, and a total cannot say that.
        for row in source_portfolios:
            landed = fi_conn.fetchone(
                f"SELECT {', '.join(_PORTFOLIO_COLUMNS)} FROM portfolios "
                "WHERE portfolio_id = ?", (row["portfolio_id"],))
            if landed is None or dict(landed) != row:
                raise MigrationRefused(
                    f"portfolio {row['portfolio_id']!r} did not land unchanged; rolling "
                    "back and changing nothing.")
        for row in source_holdings:
            landed = fi_conn.fetchone(
                f"SELECT {', '.join(_HOLDING_COLUMNS)} FROM portfolio_holdings "
                "WHERE portfolio_id = ? AND symbol = ?",
                (row["portfolio_id"], row["symbol"]))
            if landed is None or dict(landed) != row:
                raise MigrationRefused(
                    f"holding {row['symbol']!r} in portfolio {row['portfolio_id']!r} did "
                    "not land unchanged; rolling back and changing nothing.")

        _verify_owners(fi_conn, source_portfolios)

    _rename_source(gateway_conn)
    return {"migrated": True, "resumed": False,
            "portfolios": len(source_portfolios), "holdings": len(source_holdings),
            "archived_tables": [PRE_69_PORTFOLIOS, PRE_69_HOLDINGS],
            "pre_tq44": legacy, "pre_tq45a": renamed}


def migrate_paths(gateway_db: str | Path, fi_db_path: str | Path) -> dict:
    """`migrate`, given two file paths. Opens both, and closes both.

    Separate from `migrate` so that the function doing the dangerous work takes
    connections a test can hand it, and the function opening real database files
    is a thin one with nothing to get wrong."""
    from backend import fi_db

    gateway_conn = Database(gateway_db)
    fi_conn = fi_db.get_connection(fi_db_path)
    try:
        fi_db.init_schema(fi_conn)
        return migrate(gateway_conn, fi_conn)
    finally:
        gateway_conn.close()
        fi_conn.close()


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - operator entry point
    import argparse

    from dotenv import load_dotenv

    load_dotenv()

    from backend import fi_db
    from gateway import store as gateway_store

    parser = argparse.ArgumentParser(
        prog="python -m backend.portfolio_migration",
        description=("Move portfolios and holdings from gateway.db into "
                     "financial_intelligence.db (TQ-69). Point it at copies first."))
    parser.add_argument("--gateway-db", default=str(gateway_store.DB_PATH),
                        help="source database (default: the Gateway's)")
    parser.add_argument("--fi-db", default=str(fi_db.DB_PATH),
                        help="destination database (default: the backend's)")
    args = parser.parse_args(argv)

    print(f"source:      {args.gateway_db}")
    print(f"destination: {args.fi_db}")
    try:
        outcome = migrate_paths(args.gateway_db, args.fi_db)
    except MigrationRefused as refusal:
        print(f"refused: {refusal}")
        return 1

    if not outcome["migrated"]:
        print(f"nothing to do: {outcome['reason']}")
        return 0
    print(f"moved {outcome['portfolios']} portfolio(s) and {outcome['holdings']} holding(s)"
          + (" (resumed an interrupted run)" if outcome["resumed"] else ""))
    print(f"the Gateway's copies are now {', '.join(outcome['archived_tables'])}, "
          "renamed rather than dropped")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
