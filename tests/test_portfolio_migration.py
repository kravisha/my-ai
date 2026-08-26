"""The three migrations the portfolio subsystem has been through, and the one
that moved it out of the Gateway (TQ-44 §99, TQ-45a §100, TQ-69 §110).

They are together in one file because they are one chain. A `gateway.db` that
has never been touched since TQ-42 has to pass through all three to reach
today's shape, in order, and the last one refuses to copy anything that has not
been through the first two - so testing them apart would leave the interesting
case untested, which is a database several versions behind rather than one.

**Every test here builds a database of the shape it is testing rather than
mutating the current one.** `gateway/store.py` no longer creates the portfolio
tables at all (TQ-69), so "the old shape" now has to be written out. That is a
gain rather than a chore: the fixtures below say exactly what a pre-TQ-44,
pre-TQ-45a and pre-TQ-69 database looked like, instead of describing it as
"whatever init_schema used to do".

The one to read first is
`test_the_move_changes_nobodys_owner`. Everything else here is about counts and
column names; that one is about whose money it is, and it is the only kind of
failure this file exists to prevent that nobody would notice afterwards.
"""

import pytest

from backend import holdings, portfolio_migration, portfolios
from backend.db import Database
from gateway import store


# --- the shapes ---------------------------------------------------------------------
#
# A pre-TQ-69 gateway.db is the current Gateway schema plus the two portfolio
# tables it used to create. Written out here because that is now the only place
# the old shape exists.

_PRE_69_HOLDINGS = """
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


def _gateway_database(tmp_path, name="gateway.db"):
    """A gateway.db carrying the portfolio tables, as every one did before
    TQ-69.

    `store.init_schema` is deliberately *not* called: it refuses a database with
    a live `portfolios` table now, which is the point of
    `test_the_gateway_refuses_to_start_on_an_unmigrated_database` below. What is
    needed here is the file, not the Gateway's blessing of it."""
    conn = Database(tmp_path / name)
    conn.executescript(portfolios.SCHEMA)
    conn.executescript(_PRE_69_HOLDINGS)
    return conn


def _fi_database(tmp_path, name="fi.db"):
    from backend import fi_db

    conn = fi_db.get_connection(tmp_path / name)
    fi_db.init_schema(conn)
    return conn


def _legacy_database(tmp_path, rows):
    """A gateway.db in its pre-TQ-44 shape, with holdings keyed by client id."""
    conn = _gateway_database(tmp_path, "legacy.db")
    conn.execute("DROP TABLE portfolio_holdings")
    conn.executescript("""
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
    """)
    conn.executescript(_PRE_69_HOLDINGS)
    for row in rows:
        conn.execute(
            "INSERT INTO client_holdings (client_id, ticker, shares, cost_basis, "
            "acquired_on, note, stated_at, simulated) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (row["client_id"], row["ticker"], row["shares"], row.get("cost_basis"),
             row.get("acquired_on"), row.get("note"),
             row.get("stated_at", "2026-01-01T00:00:00"), row.get("simulated", 0)))
    return conn


def _tq44_shaped_database(tmp_path, rows):
    """A gateway.db as TQ-44 left it: `portfolio_holdings` with the old column
    names."""
    conn = _gateway_database(tmp_path, "tq44.db")
    portfolio = portfolios.primary_for(conn, portfolios.for_client("avery"))
    conn.execute("DROP TABLE portfolio_holdings")
    conn.executescript("""
        CREATE TABLE portfolio_holdings (
            portfolio_id TEXT NOT NULL,
            ticker TEXT NOT NULL,
            shares REAL NOT NULL,
            cost_basis REAL,
            asset_class TEXT NOT NULL DEFAULT 'UNKNOWN',
            acquired_on TEXT,
            note TEXT,
            stated_at TEXT NOT NULL,
            simulated INTEGER NOT NULL DEFAULT 0,
            schema_version INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (portfolio_id, ticker)
        );
    """)
    for row in rows:
        conn.execute(
            "INSERT INTO portfolio_holdings (portfolio_id, ticker, shares, cost_basis, "
            "asset_class, acquired_on, note, stated_at, simulated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (portfolio["portfolio_id"], row["ticker"], row["shares"], row.get("cost_basis"),
             row.get("asset_class", "UNKNOWN"), row.get("acquired_on"), row.get("note"),
             row.get("stated_at", "2026-01-01T00:00:00"), row.get("simulated", 0)))
    return conn, portfolio


# --- TQ-44: client-keyed holdings become owned portfolios (§99) ---------------------


def test_pre_tq44_rows_land_in_a_manual_portfolio_owned_by_their_client(tmp_path):
    conn = _legacy_database(tmp_path, [
        {"client_id": "avery", "ticker": "SYN1", "shares": 100, "cost_basis": 10,
         "note": "core"},
        {"client_id": "avery", "ticker": "SYN2", "shares": 5},
        {"client_id": "morgan", "ticker": "SYN3", "shares": 7, "cost_basis": 3},
    ])
    try:
        outcome = holdings.migrate_client_holdings(conn)

        assert (outcome["migrated"], outcome["clients"], outcome["holdings"]) == (True, 2, 3)
        avery = portfolios.primary_for(conn, portfolios.for_client("avery"))
        assert avery["provider_type"] == portfolios.PROVIDER_MANUAL
        assert avery["data_mode"] == portfolios.MODE_MANUAL
        assert sorted(h["symbol"] for h in holdings.listing(conn, avery)) == ["SYN1", "SYN2"]
    finally:
        conn.close()


def test_the_migration_changes_nobodys_owner(tmp_path):
    conn = _legacy_database(tmp_path, [
        {"client_id": "avery", "ticker": "SYN1", "shares": 1},
        {"client_id": "morgan", "ticker": "SYN2", "shares": 2},
    ])
    try:
        holdings.migrate_client_holdings(conn)

        avery = portfolios.primary_for(conn, portfolios.for_client("avery"))
        with pytest.raises(portfolios.NotAuthorized):
            portfolios.resolve(conn, avery["portfolio_id"], portfolios.for_client("morgan"))
    finally:
        conn.close()


def test_migrated_rows_are_not_given_an_asset_class_they_never_had(tmp_path):
    """The old table did not record one, so the new one says `unknown` rather
    than guessing. Absent is `unknown`, never a plausible default."""
    conn = _legacy_database(tmp_path, [{"client_id": "avery", "ticker": "SYN1", "shares": 1}])
    try:
        holdings.migrate_client_holdings(conn)
        avery = portfolios.primary_for(conn, portfolios.for_client("avery"))
        assert holdings.listing(conn, avery)[0]["asset_class"] == holdings.ASSET_UNKNOWN
    finally:
        conn.close()


def test_the_migration_preserves_the_simulated_flag(tmp_path):
    conn = _legacy_database(tmp_path, [
        {"client_id": "avery", "ticker": "SYN1", "shares": 1, "simulated": 1},
        {"client_id": "morgan", "ticker": "SYN2", "shares": 2, "simulated": 0},
    ])
    try:
        holdings.migrate_client_holdings(conn)
        assert portfolios.simulated_client_ids(conn) == ["avery"]
    finally:
        conn.close()


def test_the_migration_archives_the_old_table_rather_than_dropping_it(tmp_path):
    conn = _legacy_database(tmp_path, [{"client_id": "avery", "ticker": "SYN1", "shares": 1}])
    try:
        holdings.migrate_client_holdings(conn)
        assert holdings._table_exists(conn, holdings.LEGACY_ARCHIVE)
        assert not holdings._table_exists(conn, holdings.LEGACY_TABLE)
    finally:
        conn.close()


def test_the_migration_is_idempotent(tmp_path):
    """Idempotent by construction rather than by a flag: the rename removes what
    a second run would look for."""
    conn = _legacy_database(tmp_path, [
        {"client_id": "avery", "ticker": "SYN1", "shares": 1},
    ])
    try:
        holdings.migrate_client_holdings(conn)
        again = holdings.migrate_client_holdings(conn)

        assert again["migrated"] is False
        assert conn.fetchone("SELECT COUNT(*) AS n FROM portfolios")["n"] == 1
    finally:
        conn.close()


def test_an_unfinished_migration_refuses_rather_than_overwriting_the_archive(tmp_path):
    conn = _legacy_database(tmp_path, [{"client_id": "avery", "ticker": "SYN1", "shares": 1}])
    try:
        conn.execute(
            f"CREATE TABLE {holdings.LEGACY_ARCHIVE} (client_id TEXT)")
        with pytest.raises(holdings.MigrationRefused):
            holdings.migrate_client_holdings(conn)
        assert conn.fetchone("SELECT COUNT(*) AS n FROM portfolios")["n"] == 0
    finally:
        conn.close()


def test_a_fresh_database_has_nothing_to_migrate(portfolio_conn):
    assert holdings.migrate_client_holdings(portfolio_conn)["migrated"] is False


# --- TQ-45a: the field rename (§100) ------------------------------------------------


def test_the_rename_moves_every_holding_under_the_canonical_names(tmp_path):
    conn, portfolio = _tq44_shaped_database(tmp_path, [
        {"ticker": "SYN1", "shares": 100, "cost_basis": 10.5, "stated_at": "2025-05-05"},
        {"ticker": "SYN2", "shares": -4, "cost_basis": 1.85},
    ])
    try:
        outcome = holdings.migrate_holding_field_names(conn)

        assert (outcome["migrated"], outcome["holdings"]) == (True, 2)
        held = {h["symbol"]: h for h in holdings.listing(conn, portfolio)}
        assert held["SYN1"]["quantity"] == 100
        assert held["SYN1"]["average_cost"] == 10.5
        assert held["SYN1"]["as_of"] == "2025-05-05"
        assert held["SYN2"]["quantity"] == -4
    finally:
        conn.close()


def test_the_rename_maps_the_old_unknown_to_the_house_unknown(tmp_path):
    conn, portfolio = _tq44_shaped_database(
        tmp_path, [{"ticker": "SYN1", "shares": 1, "asset_class": "UNKNOWN"}])
    try:
        holdings.migrate_holding_field_names(conn)
        assert holdings.listing(conn, portfolio)[0]["asset_class"] == holdings.ASSET_UNKNOWN
    finally:
        conn.close()


@pytest.mark.parametrize("ambiguous", ["EQUITY", "OPTION"])
def test_the_rename_refuses_an_asset_class_it_would_have_to_guess(tmp_path, ambiguous):
    """`EQUITY` does not settle stock versus etf, and picking one would be the
    fabrication this project refuses everywhere else."""
    conn, _ = _tq44_shaped_database(
        tmp_path, [{"ticker": "SYN1", "shares": 1, "asset_class": ambiguous}])
    try:
        with pytest.raises(holdings.MigrationRefused):
            holdings.migrate_holding_field_names(conn)
        assert "ticker" in {r["name"] for r in conn.fetchall(
            "PRAGMA table_info(portfolio_holdings)")}
    finally:
        conn.close()


def test_the_rename_is_idempotent(tmp_path):
    conn, _ = _tq44_shaped_database(
        tmp_path, [{"ticker": "SYN1", "shares": 1}, {"ticker": "SYN2", "shares": 2}])
    try:
        holdings.migrate_holding_field_names(conn)
        again = holdings.migrate_holding_field_names(conn)

        assert again["migrated"] is False
        assert conn.fetchone("SELECT COUNT(*) AS n FROM portfolio_holdings")["n"] == 2
    finally:
        conn.close()


def test_the_rename_archives_the_old_table_rather_than_dropping_it(tmp_path):
    conn, _ = _tq44_shaped_database(tmp_path, [{"ticker": "SYN1", "shares": 1}])
    try:
        holdings.migrate_holding_field_names(conn)
        assert holdings._table_exists(conn, holdings.PRE_45_ARCHIVE)
    finally:
        conn.close()


def test_an_unfinished_rename_refuses_rather_than_overwriting_the_archive(tmp_path):
    conn, _ = _tq44_shaped_database(tmp_path, [{"ticker": "SYN1", "shares": 1}])
    try:
        conn.execute(f"CREATE TABLE {holdings.PRE_45_ARCHIVE} (portfolio_id TEXT)")
        with pytest.raises(holdings.MigrationRefused):
            holdings.migrate_holding_field_names(conn)
    finally:
        conn.close()


# --- TQ-69: the move between databases (§110) ---------------------------------------


def _seeded_gateway(tmp_path):
    """A pre-TQ-69 gateway.db with two clients, an archived portfolio and a
    superuser one - the awkward cases rather than the easy one."""
    conn = _gateway_database(tmp_path)
    avery = portfolios.for_client("avery")
    morgan = portfolios.for_client("morgan")
    operator = portfolios.for_superuser()

    a = portfolios.primary_for(conn, avery)
    holdings.record(conn, a, symbol="SYN1", quantity=100, average_cost=10.5,
                    as_of="2025-05-05T00:00:00")
    holdings.record(conn, a, symbol="SYN2", quantity=-4, average_cost=1.85)
    m = portfolios.primary_for(conn, morgan, simulated=True)
    holdings.record(conn, m, symbol="SYN3", quantity=7, simulated=True)
    retired = portfolios.create(conn, avery, display_name="Old",
                                portfolio_type=portfolios.TYPE_SECONDARY)
    holdings.record(conn, retired, symbol="SYN9", quantity=1)
    portfolios.archive(conn, retired["portfolio_id"], avery)
    portfolios.create(conn, operator, display_name="House")
    return conn


def test_the_move_lands_every_portfolio_and_every_holding(tmp_path):
    gateway_conn = _seeded_gateway(tmp_path)
    fi_conn = _fi_database(tmp_path)
    try:
        outcome = portfolio_migration.migrate(gateway_conn, fi_conn)

        assert outcome["migrated"] is True
        assert outcome["portfolios"] == 4
        assert outcome["holdings"] == 4
        assert fi_conn.fetchone("SELECT COUNT(*) AS n FROM portfolios")["n"] == 4
        assert fi_conn.fetchone("SELECT COUNT(*) AS n FROM portfolio_holdings")["n"] == 4
    finally:
        gateway_conn.close()
        fi_conn.close()


def test_the_move_changes_nobodys_owner(tmp_path):
    """**The test this file exists for.** A move that landed every row and
    swapped two owners would pass every count check perfectly, and it would be
    the worst outcome this increment could have."""
    gateway_conn = _seeded_gateway(tmp_path)
    fi_conn = _fi_database(tmp_path)
    try:
        before = {r["portfolio_id"]: (r["owner_type"], r["owner_id"]) for r in
                  gateway_conn.fetchall(
                      "SELECT portfolio_id, owner_type, owner_id FROM portfolios")}

        portfolio_migration.migrate(gateway_conn, fi_conn)

        after = {r["portfolio_id"]: (r["owner_type"], r["owner_id"]) for r in
                 fi_conn.fetchall(
                     "SELECT portfolio_id, owner_type, owner_id FROM portfolios")}
        assert after == before

        # And the property that ownership actually *means*, asserted through the
        # guard rather than against the column.
        avery = portfolios.for_client("avery")
        mine = {p["portfolio_id"] for p in portfolios.owned(fi_conn, avery)}
        assert len(mine) == 2
        for portfolio_id, owner in before.items():
            if owner != (portfolios.OWNER_CLIENT, "avery"):
                with pytest.raises(portfolios.NotAuthorized):
                    portfolios.resolve(fi_conn, portfolio_id, avery)
    finally:
        gateway_conn.close()
        fi_conn.close()


def test_the_move_re_keys_and_restamps_nothing(tmp_path):
    """Spec §6.3: *a migration that restamps or re-keys anything has changed
    whose data it is.* Compared column by column rather than by count, because a
    total cannot say this."""
    gateway_conn = _seeded_gateway(tmp_path)
    fi_conn = _fi_database(tmp_path)
    try:
        columns = ", ".join(portfolio_migration._PORTFOLIO_COLUMNS)
        holding_columns = ", ".join(portfolio_migration._HOLDING_COLUMNS)
        before = [dict(r) for r in gateway_conn.fetchall(
            f"SELECT {columns} FROM portfolios ORDER BY portfolio_id")]
        before_holdings = [dict(r) for r in gateway_conn.fetchall(
            f"SELECT {holding_columns} FROM portfolio_holdings "
            "ORDER BY portfolio_id, symbol")]

        portfolio_migration.migrate(gateway_conn, fi_conn)

        assert [dict(r) for r in fi_conn.fetchall(
            f"SELECT {columns} FROM portfolios ORDER BY portfolio_id")] == before
        assert [dict(r) for r in fi_conn.fetchall(
            f"SELECT {holding_columns} FROM portfolio_holdings "
            "ORDER BY portfolio_id, symbol")] == before_holdings
    finally:
        gateway_conn.close()
        fi_conn.close()


def test_an_archived_portfolio_moves_too(tmp_path):
    """`resolve` refuses an archived portfolio, so a migration verified with
    `resolve` would either report a false failure or be tempted to skip archived
    rows and leave somebody's retired positions behind."""
    gateway_conn = _seeded_gateway(tmp_path)
    fi_conn = _fi_database(tmp_path)
    try:
        portfolio_migration.migrate(gateway_conn, fi_conn)

        avery = portfolios.for_client("avery")
        statuses = sorted(p["status"] for p in portfolios.owned(fi_conn, avery))
        assert statuses == ["active", "archived"]
    finally:
        gateway_conn.close()
        fi_conn.close()


def test_the_move_archives_the_gateways_tables_rather_than_dropping_them(tmp_path):
    gateway_conn = _seeded_gateway(tmp_path)
    fi_conn = _fi_database(tmp_path)
    try:
        portfolio_migration.migrate(gateway_conn, fi_conn)

        tables = {r["name"] for r in gateway_conn.fetchall(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert portfolio_migration.PRE_69_PORTFOLIOS in tables
        assert portfolio_migration.PRE_69_HOLDINGS in tables
        assert "portfolios" not in tables
        assert "portfolio_holdings" not in tables
    finally:
        gateway_conn.close()
        fi_conn.close()


def test_the_move_is_idempotent(tmp_path):
    gateway_conn = _seeded_gateway(tmp_path)
    fi_conn = _fi_database(tmp_path)
    try:
        portfolio_migration.migrate(gateway_conn, fi_conn)
        again = portfolio_migration.migrate(gateway_conn, fi_conn)

        assert again["migrated"] is False
        assert fi_conn.fetchone("SELECT COUNT(*) AS n FROM portfolios")["n"] == 4
    finally:
        gateway_conn.close()
        fi_conn.close()


def test_an_interrupted_move_is_finished_rather_than_redone(tmp_path):
    """The window between the copy committing and the rename is real: a process
    killed there leaves the rows in both places. Finishing it is right;
    re-copying would fail on the primary key, and clobbering would be worse."""
    gateway_conn = _seeded_gateway(tmp_path)
    fi_conn = _fi_database(tmp_path)
    try:
        portfolio_migration.migrate(gateway_conn, fi_conn)
        # Put the source back as an interrupted run would have left it.
        gateway_conn.execute(
            f"ALTER TABLE {portfolio_migration.PRE_69_PORTFOLIOS} RENAME TO portfolios")
        gateway_conn.execute(
            f"ALTER TABLE {portfolio_migration.PRE_69_HOLDINGS} "
            "RENAME TO portfolio_holdings")

        outcome = portfolio_migration.migrate(gateway_conn, fi_conn)

        assert (outcome["migrated"], outcome["resumed"]) == (True, True)
        assert fi_conn.fetchone("SELECT COUNT(*) AS n FROM portfolios")["n"] == 4
    finally:
        gateway_conn.close()
        fi_conn.close()


def test_a_half_copied_move_refuses_rather_than_guessing(tmp_path):
    """Deciding which copy is right is a person's decision. This one says so and
    changes nothing."""
    gateway_conn = _seeded_gateway(tmp_path)
    fi_conn = _fi_database(tmp_path)
    try:
        one = gateway_conn.fetchone("SELECT * FROM portfolios LIMIT 1")
        columns = portfolio_migration._PORTFOLIO_COLUMNS
        fi_conn.execute(
            f"INSERT INTO portfolios ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' * len(columns))})",
            tuple(one[c] for c in columns))

        with pytest.raises(portfolio_migration.MigrationRefused):
            portfolio_migration.migrate(gateway_conn, fi_conn)

        assert fi_conn.fetchone("SELECT COUNT(*) AS n FROM portfolios")["n"] == 1
        assert holdings._table_exists(gateway_conn, "portfolios")
    finally:
        gateway_conn.close()
        fi_conn.close()


def test_a_failed_verification_leaves_the_source_untouched(tmp_path):
    """Two files cannot be written atomically, so the ordering has to supply
    what a transaction cannot: verify while the source is still intact, and
    rename only afterwards."""
    gateway_conn = _seeded_gateway(tmp_path)
    fi_conn = _fi_database(tmp_path)
    try:
        # A stored owner_type this build cannot interpret. It has to fail the
        # ownership verification rather than be normalised into something
        # readable, because "readable" would mean choosing an owner.
        gateway_conn.execute(
            "UPDATE portfolios SET owner_type = 'ACCOUNTANT' WHERE owner_type = 'SUPERUSER'")

        with pytest.raises(portfolio_migration.MigrationRefused):
            portfolio_migration.migrate(gateway_conn, fi_conn)

        assert fi_conn.fetchone("SELECT COUNT(*) AS n FROM portfolios")["n"] == 0
        assert holdings._table_exists(gateway_conn, "portfolios")
        assert gateway_conn.fetchone("SELECT COUNT(*) AS n FROM portfolios")["n"] == 4
    finally:
        gateway_conn.close()
        fi_conn.close()


def test_a_database_several_versions_behind_arrives_in_one_move(tmp_path):
    """A gateway.db untouched since TQ-42 has to pass through all three
    migrations, in order, and land in the backend. Testing them apart would
    leave exactly this case untested."""
    gateway_conn = _legacy_database(tmp_path, [
        {"client_id": "avery", "ticker": "SYN1", "shares": 100, "cost_basis": 10,
         "stated_at": "2025-02-02T00:00:00"},
        {"client_id": "morgan", "ticker": "SYN3", "shares": 7},
    ])
    fi_conn = _fi_database(tmp_path)
    try:
        outcome = portfolio_migration.migrate(gateway_conn, fi_conn)

        assert outcome["migrated"] is True
        assert outcome["holdings"] == 2
        avery = portfolios.primary_for(fi_conn, portfolios.for_client("avery"))
        held = holdings.listing(fi_conn, avery)
        assert [h["symbol"] for h in held] == ["SYN1"]
        # `as_of` is when the client said it, not when the migration ran.
        assert held[0]["as_of"] == "2025-02-02T00:00:00"
        assert held[0]["asset_class"] == holdings.ASSET_UNKNOWN
    finally:
        gateway_conn.close()
        fi_conn.close()


def test_a_gateway_database_with_no_portfolios_is_a_no_op(tmp_path, gateway_conn):
    fi_conn = _fi_database(tmp_path)
    try:
        outcome = portfolio_migration.migrate(gateway_conn, fi_conn)
        assert outcome["migrated"] is False
    finally:
        fi_conn.close()


# --- the Gateway refuses to run against an unmigrated database ----------------------


def test_the_gateway_refuses_to_start_on_an_unmigrated_database(tmp_path):
    """A refusal rather than a warning, because the failure it prevents does not
    look like a failure.

    An un-migrated client is not shown an error - they are given a brand-new
    empty portfolio while their real one sits unreachable in gateway.db, which
    reads as a working system with nothing in it. They would then record
    holdings into the new one, and a migration afterwards would restore the old
    portfolio as the older 'primary', hiding everything recorded in between."""
    conn = _seeded_gateway(tmp_path)
    try:
        with pytest.raises(store.UnmigratedGatewayDatabase) as refusal:
            store.init_schema(conn)
        assert "portfolio_migration" in str(refusal.value)
    finally:
        conn.close()


def test_a_migrated_gateway_database_starts_normally(tmp_path):
    """The archive left behind by a completed move is the normal, migrated
    state - so the check has to look at the live table and not at the name."""
    gateway_conn = _seeded_gateway(tmp_path)
    fi_conn = _fi_database(tmp_path)
    try:
        portfolio_migration.migrate(gateway_conn, fi_conn)
        store.init_schema(gateway_conn)  # does not raise
        assert holdings._table_exists(gateway_conn, portfolio_migration.PRE_69_PORTFOLIOS)
    finally:
        gateway_conn.close()
        fi_conn.close()
