"""Portfolio ownership and isolation (gateway/portfolios.py; TQ-44,
docs/SPEC_RECONCILIATION.md §99).

These are permanent regressions, not smoke tests. TQ-44 introduced a portfolio
id, and addendum 44 §5.2 is explicit that four attacks become possible only once
one exists — asking for another client's portfolio by id, reusing a stale one, a
mismatched client/portfolio pair, an agent retaining a previous client's context.
The entity and the guard shipped in one increment because of that, and this file
is the half that keeps the guard honest afterwards.

The one to read first is
`test_a_client_cannot_receive_the_superuser_portfolio_when_it_is_the_only_one`.
It is §15.5, and it is §93's conversation leak rewritten in portfolio form: a
lookup that fell back to "the only row there is" was how the operator's entire
transcript went out in a client's opening frame. The shape recurs, so the test
against it is permanent.
"""

import pytest

from gateway import demo_clients, holdings, portfolios, store


# --- ownership isolation (§15.1) ---------------------------------------------------


def test_an_owner_resolves_their_own_portfolio(gateway_conn):
    avery = portfolios.for_client("avery")
    created = portfolios.create(gateway_conn, avery, display_name="Portfolio")

    found = portfolios.resolve(gateway_conn, created["portfolio_id"], avery)

    assert found["portfolio_id"] == created["portfolio_id"]
    assert (found["owner_type"], found["owner_id"]) == (portfolios.OWNER_CLIENT, "avery")


def test_a_client_cannot_resolve_another_clients_portfolio(gateway_conn):
    """The property §93 established for conversations, applied to money - and
    the attack addendum 44 §5.2 says the new id makes possible at all."""
    avery = portfolios.for_client("avery")
    morgan = portfolios.for_client("morgan")
    theirs = portfolios.create(gateway_conn, avery, display_name="Portfolio")

    with pytest.raises(portfolios.NotAuthorized):
        portfolios.resolve(gateway_conn, theirs["portfolio_id"], morgan)


def test_a_client_cannot_resolve_a_superuser_portfolio(gateway_conn):
    """SUPERUSER is a separate owner domain, and the separation runs both ways:
    §3.3 stops the operator reaching a client, and this stops the reverse."""
    operator = portfolios.for_superuser()
    theirs = portfolios.create(gateway_conn, operator, display_name="House")

    with pytest.raises(portfolios.NotAuthorized):
        portfolios.resolve(gateway_conn, theirs["portfolio_id"], portfolios.for_client("avery"))


def test_a_superuser_cannot_resolve_a_clients_portfolio(gateway_conn):
    """There is no superuser branch (addendum 44 §5.3). The operator holds every
    *capability* in this system - and holds no client's portfolio, because
    ownership and capability are separate questions (§2.1).

    An administrative route to a client's holdings is not merely unbuilt, it is
    refused: §10 permits one only through an explicitly authorized workflow, and
    none exists to authorize it."""
    avery = portfolios.for_client("avery")
    theirs = portfolios.create(gateway_conn, avery, display_name="Portfolio")

    with pytest.raises(portfolios.NotAuthorized):
        portfolios.resolve(gateway_conn, theirs["portfolio_id"], portfolios.for_superuser())


def test_a_guessed_id_does_not_bypass_authorization(gateway_conn):
    avery = portfolios.for_client("avery")
    portfolios.create(gateway_conn, avery, display_name="Portfolio")

    for guess in ("pf-0", "pf-" + "0" * 32, "", None, "'; DROP TABLE portfolios; --"):
        with pytest.raises(portfolios.NotAuthorized):
            portfolios.resolve(gateway_conn, guess, avery)


def test_a_portfolio_id_is_not_sequential(gateway_conn):
    """§3.5. The guard makes enumeration useless; this makes it pointless. A
    sequential id would leak a portfolio count from any single id - a fact about
    other clients even when their data is unreachable."""
    avery = portfolios.for_client("avery")
    ids = {portfolios.create(gateway_conn, avery, display_name=f"P{n}",
                             portfolio_type=portfolios.TYPE_SECONDARY)["portfolio_id"]
           for n in range(5)}

    assert len(ids) == 5
    assert all(pid.startswith("pf-") and len(pid) == 35 for pid in ids)
    # Nothing incrementing: no two differ only in a trailing digit.
    assert len({pid[:-1] for pid in ids}) == 5


def test_absent_foreign_and_archived_raise_the_same_refusal(gateway_conn):
    """Addendum 44 §9.3 is about what a caller can *tell apart*, so this asserts
    the message as well as the type. A refusal that said "archived" for one and
    "not found" for another would confirm that somebody else's portfolio exists,
    which is the fact being withheld."""
    avery = portfolios.for_client("avery")
    morgan = portfolios.for_client("morgan")
    foreign = portfolios.create(gateway_conn, morgan, display_name="Portfolio")
    archived = portfolios.create(gateway_conn, avery, display_name="Old",
                                 portfolio_type=portfolios.TYPE_SECONDARY)
    portfolios.archive(gateway_conn, archived["portfolio_id"], avery)

    refusals = []
    for portfolio_id in ("pf-does-not-exist", foreign["portfolio_id"],
                         archived["portfolio_id"]):
        with pytest.raises(portfolios.NotAuthorized) as raised:
            portfolios.resolve(gateway_conn, portfolio_id, avery)
        refusals.append(str(raised.value))

    assert refusals == [portfolios.REFUSAL] * 3


def test_listing_returns_only_this_owners_portfolios(gateway_conn):
    avery = portfolios.for_client("avery")
    morgan = portfolios.for_client("morgan")
    portfolios.create(gateway_conn, avery, display_name="A")
    portfolios.create(gateway_conn, morgan, display_name="M")
    portfolios.create(gateway_conn, portfolios.for_superuser(), display_name="House")

    assert [p["display_name"] for p in portfolios.listing(gateway_conn, avery)] == ["A"]
    assert [p["display_name"] for p in portfolios.listing(gateway_conn, morgan)] == ["M"]


def test_listing_omits_archived(gateway_conn):
    avery = portfolios.for_client("avery")
    kept = portfolios.create(gateway_conn, avery, display_name="Kept")
    gone = portfolios.create(gateway_conn, avery, display_name="Gone",
                             portfolio_type=portfolios.TYPE_SECONDARY)
    portfolios.archive(gateway_conn, gone["portfolio_id"], avery)

    assert [p["portfolio_id"] for p in portfolios.listing(gateway_conn, avery)] == [
        kept["portfolio_id"]]


def test_archiving_reaches_only_your_own(gateway_conn):
    avery = portfolios.for_client("avery")
    theirs = portfolios.create(gateway_conn, avery, display_name="Portfolio")

    with pytest.raises(portfolios.NotAuthorized):
        portfolios.archive(gateway_conn, theirs["portfolio_id"],
                           portfolios.for_client("morgan"))

    assert portfolios.resolve(gateway_conn, theirs["portfolio_id"], avery)["status"] == (
        portfolios.STATUS_ACTIVE)


# --- the §15.5 regression ----------------------------------------------------------


def test_a_client_cannot_receive_the_superuser_portfolio_when_it_is_the_only_one(gateway_conn):
    """§93's leak, in portfolio form. Permanent.

    The original was a "newest wins" lookup with no owner filter: a client
    connecting received the operator's entire conversation, because it was the
    only one in the database. The shape is what recurs - a query that returns
    *the* row rather than *this owner's* row is indistinguishable from a correct
    one for as long as there is exactly one row.

    So: a SUPERUSER portfolio as the only row in the table, and a client context
    must resolve nothing and list nothing."""
    operator = portfolios.for_superuser()
    only_row = portfolios.create(gateway_conn, operator, display_name="House")
    assert gateway_conn.fetchone("SELECT COUNT(*) AS n FROM portfolios")["n"] == 1

    client = portfolios.for_client("avery")

    assert portfolios.listing(gateway_conn, client) == []
    assert portfolios.owned(gateway_conn, client) == []
    with pytest.raises(portfolios.NotAuthorized):
        portfolios.resolve(gateway_conn, only_row["portfolio_id"], client)

    # And the operator still reaches their own, so this is isolation rather than
    # a check that refuses everybody.
    assert portfolios.resolve(gateway_conn, only_row["portfolio_id"], operator)["display_name"] == (
        "House")


def test_primary_for_creates_rather_than_adopting_the_only_portfolio(gateway_conn):
    """The same leak one layer up. `primary_for` creates on first use (§3.8), and
    the failure mode is that it finds the superuser's and calls it the client's."""
    operator = portfolios.for_superuser()
    house = portfolios.create(gateway_conn, operator, display_name="House")

    mine = portfolios.primary_for(gateway_conn, portfolios.for_client("avery"))

    assert mine["portfolio_id"] != house["portfolio_id"]
    assert (mine["owner_type"], mine["owner_id"]) == (portfolios.OWNER_CLIENT, "avery")


def test_primary_for_is_stable_across_calls(gateway_conn):
    avery = portfolios.for_client("avery")
    first = portfolios.primary_for(gateway_conn, avery)
    second = portfolios.primary_for(gateway_conn, avery)

    assert first["portfolio_id"] == second["portfolio_id"]
    assert len(portfolios.listing(gateway_conn, avery)) == 1


# --- ownership is resolved, never received (§9.2) ----------------------------------


def test_a_raw_client_id_cannot_be_passed_where_an_owner_is_required(gateway_conn):
    """A string is a claim; an OwnerContext is a resolved fact. Accepting the
    string would put the decision about whose money is visible into whatever code
    happened to build it - and would look perfectly correct."""
    portfolios.create(gateway_conn, portfolios.for_client("avery"), display_name="P")

    for wrong in ("avery", None, 42, {"owner_id": "avery"}):
        with pytest.raises(TypeError):
            portfolios.listing(gateway_conn, wrong)
        with pytest.raises(TypeError):
            portfolios.resolve(gateway_conn, "pf-whatever", wrong)


def test_an_owner_context_needs_an_owner(gateway_conn):
    for nobody in ("", "   ", None, 7):
        with pytest.raises(portfolios.UnknownVocabulary):
            portfolios.for_client(nobody)


def test_an_owner_id_is_normalised_the_way_a_login_is(gateway_conn):
    """Two normalisations that could disagree are two identities for one person.
    This is the same function `clients.normalise` applies at the door."""
    created = portfolios.create(gateway_conn, portfolios.for_client("  AVERY  "),
                                display_name="P")

    assert created["owner_id"] == "avery"
    assert portfolios.resolve(gateway_conn, created["portfolio_id"],
                              portfolios.for_client("Avery"))


def test_an_unknown_owner_type_is_refused(gateway_conn):
    with pytest.raises(portfolios.UnknownVocabulary):
        portfolios.OwnerContext("ADMIN", "avery")


# --- fail closed on every vocabulary, writing and reading (§3.6) -------------------


@pytest.mark.parametrize("field,value", [
    ("portfolio_type", "RETIREMENT"),
    ("provider_type", "FIDELITY"),
    ("data_mode", "REAL"),
])
def test_an_unknown_vocabulary_value_is_refused_on_write(gateway_conn, field, value):
    with pytest.raises(portfolios.UnknownVocabulary):
        portfolios.create(gateway_conn, portfolios.for_client("avery"),
                          display_name="P", **{field: value})


@pytest.mark.parametrize("field,value", [
    ("portfolio_type", "RETIREMENT"),
    ("provider_type", "FIDELITY"),
    ("data_mode", "REAL"),
    ("status", "frozen"),
])
def test_an_unknown_vocabulary_value_raises_on_read(gateway_conn, field, value):
    """Not only on write. A row that reached the database another way - an older
    build, a hand edit, a restored backup - must not be interpreted by guessing
    what its value meant. A portfolio whose data_mode is unreadable is one whose
    pricing rule cannot be applied, and guessing which side of `is_priced` it
    falls on is how a simulated number gets shown as somebody's money."""
    avery = portfolios.for_client("avery")
    created = portfolios.create(gateway_conn, avery, display_name="P")
    gateway_conn.execute(f"UPDATE portfolios SET {field} = ? WHERE portfolio_id = ?",
                         (value, created["portfolio_id"]))

    with pytest.raises(portfolios.UnknownVocabulary):
        portfolios.resolve(gateway_conn, created["portfolio_id"], avery)
    with pytest.raises(portfolios.UnknownVocabulary):
        portfolios.listing(gateway_conn, avery)


def test_an_unreadable_row_still_refuses_a_stranger_without_telling_them_why(gateway_conn):
    """The ordering in `resolve` matters. A corrupt row must fail closed for its
    owner *and* stay invisible to everybody else - if interpretation ran first,
    `UnknownVocabulary` where a stranger expected `NotAuthorized` would confirm
    that the id exists, which is exactly what §9.3 withholds."""
    avery = portfolios.for_client("avery")
    created = portfolios.create(gateway_conn, avery, display_name="P")
    gateway_conn.execute("UPDATE portfolios SET data_mode = 'REAL' WHERE portfolio_id = ?",
                         (created["portfolio_id"],))

    with pytest.raises(portfolios.NotAuthorized) as raised:
        portfolios.resolve(gateway_conn, created["portfolio_id"],
                           portfolios.for_client("morgan"))
    assert str(raised.value) == portfolios.REFUSAL


def test_an_unreadable_owner_type_matches_nobody(gateway_conn):
    """Fail closed by construction: a stored owner_type outside the vocabulary
    cannot equal either known one, so the row is unreachable rather than
    reachable-by-whoever-guesses-its-domain."""
    avery = portfolios.for_client("avery")
    created = portfolios.create(gateway_conn, avery, display_name="P")
    gateway_conn.execute("UPDATE portfolios SET owner_type = 'ADMIN' WHERE portfolio_id = ?",
                         (created["portfolio_id"],))

    for owner in (avery, portfolios.for_superuser(), portfolios.for_superuser("admin")):
        with pytest.raises(portfolios.NotAuthorized):
            portfolios.resolve(gateway_conn, created["portfolio_id"], owner)


def test_a_portfolio_needs_a_display_name(gateway_conn):
    with pytest.raises(portfolios.UnknownVocabulary):
        portfolios.create(gateway_conn, portfolios.for_client("avery"), display_name="  ")


def test_the_schema_refuses_an_unowned_portfolio(gateway_conn):
    """§2.3's "a missing owner denies", as a schema fact rather than a runtime
    hope. Asserted at the database because the column being NOT NULL is the part
    that survives somebody adding a new insert path."""
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        gateway_conn.execute(
            "INSERT INTO portfolios (portfolio_id, owner_type, owner_id, portfolio_type, "
            "display_name, provider_type, data_mode, status, created_at, updated_at) "
            "VALUES ('pf-x', NULL, NULL, 'PRIMARY', 'P', 'MANUAL', 'MANUAL', 'active', "
            "'2026-01-01', '2026-01-01')")


# --- the pricing rule (§3.7) -------------------------------------------------------


def test_only_a_live_portfolio_is_priced(gateway_conn):
    """The single condition for whether anything market-derived may be shown.

    Everything this system generates is simulated (addendum 25), which is why
    §96 refused market value and `portfolio_valuation` stands declared-and-unbuilt.
    Addendum 44 supplied the field that could one day say otherwise; it did not
    supply prices."""
    avery = portfolios.for_client("avery")
    made = {}
    for mode in portfolios.DATA_MODES:
        made[mode] = portfolios.create(
            gateway_conn, avery, display_name=mode, data_mode=mode,
            portfolio_type=portfolios.TYPE_SECONDARY,
            provider_type=(portfolios.PROVIDER_MANUAL if mode == portfolios.MODE_MANUAL
                           else portfolios.PROVIDER_SIMULATED))

    assert portfolios.is_priced(made[portfolios.MODE_LIVE]) is True
    assert portfolios.is_priced(made[portfolios.MODE_SIMULATED]) is False
    assert portfolios.is_priced(made[portfolios.MODE_MANUAL]) is False


def test_a_portfolio_made_by_ordinary_use_is_not_priced(gateway_conn):
    """What a client actually gets. `primary_for` builds a MANUAL portfolio, so
    the answer for every real portfolio in this build today is False - and it is
    False because of the rule, not because the feature is missing."""
    assert portfolios.is_priced(
        portfolios.primary_for(gateway_conn, portfolios.for_client("avery"))) is False


def test_the_concentration_report_takes_its_priced_flag_from_the_one_rule(gateway_conn):
    """Not a second hard-coded False. Routed through `is_priced` so the report
    cannot drift from every other caller's answer to the same question."""
    portfolio = portfolios.primary_for(gateway_conn, portfolios.for_client("avery"))
    holdings.record(gateway_conn, portfolio, ticker="SYN1", shares=10, cost_basis=5)

    report = holdings.concentration(gateway_conn, portfolio)

    assert report["priced"] is False
    assert report["priced"] == portfolios.is_priced(portfolio)


# --- the migration (§6) ------------------------------------------------------------


def _legacy_database(tmp_path, rows):
    """A gateway.db in its pre-TQ-44 shape, with holdings keyed by client id.

    Built by creating the current schema and then putting the old table back,
    which is closer to the real upgrade than hand-writing every table: the rows
    being migrated are the only thing that has to be historical."""
    conn = store.get_connection(tmp_path / "legacy.db")
    store.init_schema(conn)
    conn.execute(f"DROP TABLE IF EXISTS {holdings.LEGACY_ARCHIVE}")
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
    for row in rows:
        conn.execute(
            "INSERT INTO client_holdings (client_id, ticker, shares, cost_basis, "
            "acquired_on, note, stated_at, simulated) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (row["client_id"], row["ticker"], row["shares"], row.get("cost_basis"),
             row.get("acquired_on"), row.get("note"), row.get("stated_at", "2026-01-01T00:00:00"),
             row.get("simulated", 0)))
    return conn


def test_pre_tq44_rows_land_in_a_manual_portfolio_owned_by_their_client(tmp_path):
    conn = _legacy_database(tmp_path, [
        {"client_id": "avery", "ticker": "SYN1", "shares": 100, "cost_basis": 10,
         "stated_at": "2025-05-05T09:00:00"},
        {"client_id": "avery", "ticker": "SYN2", "shares": 5, "cost_basis": 200},
        {"client_id": "morgan", "ticker": "SYN3", "shares": 7},
    ])
    try:
        outcome = holdings.migrate_client_holdings(conn)

        assert outcome["migrated"] is True
        assert (outcome["clients"], outcome["holdings"]) == (2, 3)

        avery = portfolios.primary_for(conn, portfolios.for_client("avery"))
        assert avery["provider_type"] == portfolios.PROVIDER_MANUAL
        assert avery["data_mode"] == portfolios.MODE_MANUAL
        assert avery["portfolio_type"] == portfolios.TYPE_PRIMARY
        assert portfolios.is_priced(avery) is False

        moved = holdings.listing(conn, avery)
        assert [h["ticker"] for h in moved] == ["SYN1", "SYN2"]
        # The client said it then, not today. A migration that restamped every
        # row would have quietly destroyed a fact about them.
        assert moved[0]["stated_at"] == "2025-05-05T09:00:00"
    finally:
        conn.close()


def test_the_migration_changes_nobodys_owner(tmp_path):
    conn = _legacy_database(tmp_path, [
        {"client_id": "avery", "ticker": "SYN1", "shares": 100},
        {"client_id": "morgan", "ticker": "SYN2", "shares": 5},
    ])
    try:
        holdings.migrate_client_holdings(conn)

        avery = portfolios.primary_for(conn, portfolios.for_client("avery"))
        morgan = portfolios.primary_for(conn, portfolios.for_client("morgan"))

        assert [h["ticker"] for h in holdings.listing(conn, avery)] == ["SYN1"]
        assert [h["ticker"] for h in holdings.listing(conn, morgan)] == ["SYN2"]
        # And neither can reach the other's, which is the point of having moved
        # them into owned entities at all.
        with pytest.raises(portfolios.NotAuthorized):
            portfolios.resolve(conn, morgan["portfolio_id"], portfolios.for_client("avery"))
    finally:
        conn.close()


def test_migrated_rows_are_not_given_an_asset_class_they_never_had(tmp_path):
    """§10 Q3. EQUITY would be a guess, and this project does not fabricate:
    absent is `unknown`, never a plausible default."""
    conn = _legacy_database(tmp_path, [{"client_id": "avery", "ticker": "SYN1", "shares": 1}])
    try:
        holdings.migrate_client_holdings(conn)
        avery = portfolios.primary_for(conn, portfolios.for_client("avery"))

        assert holdings.listing(conn, avery)[0]["asset_class"] == holdings.ASSET_UNKNOWN
    finally:
        conn.close()


def test_the_migration_preserves_the_simulated_flag(tmp_path):
    conn = _legacy_database(tmp_path, [
        {"client_id": "demo", "ticker": "SYN1", "shares": 1, "simulated": 1},
        {"client_id": "real", "ticker": "SYN2", "shares": 1, "simulated": 0},
    ])
    try:
        holdings.migrate_client_holdings(conn)

        assert portfolios.simulated_client_ids(conn) == ["demo"]
        demo = portfolios.primary_for(conn, portfolios.for_client("demo"))
        assert demo["simulated"] is True
        assert holdings.listing(conn, demo)[0]["simulated"] is True
    finally:
        conn.close()


def test_the_migration_archives_the_old_table_rather_than_dropping_it(tmp_path):
    """§10 Q2, and §22's preserve-for-diagnosis habit."""
    conn = _legacy_database(tmp_path, [{"client_id": "avery", "ticker": "SYN1", "shares": 1}])
    try:
        holdings.migrate_client_holdings(conn)

        assert holdings._table_exists(conn, holdings.LEGACY_ARCHIVE)
        assert not holdings._table_exists(conn, holdings.LEGACY_TABLE)
        assert conn.fetchone(
            f"SELECT COUNT(*) AS n FROM {holdings.LEGACY_ARCHIVE}")["n"] == 1
    finally:
        conn.close()


def test_the_migration_is_idempotent(tmp_path):
    """§6.6. Idempotent by construction: the rename removes what a second run
    would look for, so there is no version flag to get out of step."""
    conn = _legacy_database(tmp_path, [
        {"client_id": "avery", "ticker": "SYN1", "shares": 1},
        {"client_id": "avery", "ticker": "SYN2", "shares": 2},
    ])
    try:
        holdings.migrate_client_holdings(conn)
        again = holdings.migrate_client_holdings(conn)
        store.init_schema(conn)
        store.init_schema(conn)

        assert again["migrated"] is False
        avery = portfolios.primary_for(conn, portfolios.for_client("avery"))
        assert len(holdings.listing(conn, avery)) == 2
        assert len(portfolios.listing(conn, portfolios.for_client("avery"))) == 1
    finally:
        conn.close()


def test_an_unfinished_migration_refuses_rather_than_overwriting_the_archive(tmp_path):
    """Both tables present means an earlier run stopped half-way. Clobbering the
    archived copy would destroy the only evidence of what it was doing."""
    conn = _legacy_database(tmp_path, [{"client_id": "avery", "ticker": "SYN1", "shares": 1}])
    try:
        conn.executescript(
            f"CREATE TABLE {holdings.LEGACY_ARCHIVE} (client_id TEXT, ticker TEXT);")

        with pytest.raises(holdings.MigrationRefused):
            holdings.migrate_client_holdings(conn)

        # Nothing moved, nothing renamed.
        assert holdings._table_exists(conn, holdings.LEGACY_TABLE)
        assert conn.fetchone("SELECT COUNT(*) AS n FROM portfolio_holdings")["n"] == 0
    finally:
        conn.close()


def test_a_fresh_database_has_nothing_to_migrate(gateway_conn):
    assert holdings.migrate_client_holdings(gateway_conn)["migrated"] is False


# --- demo data (§96's convention, applied to portfolios) ---------------------------


def test_demo_portfolios_are_flagged_and_cleared(gateway_conn, monkeypatch):
    monkeypatch.setattr(demo_clients, "_require_development_stage", lambda: "PRE_ALPHA")
    demo_clients.seed(gateway_conn)

    assert len(portfolios.simulated_portfolio_ids(gateway_conn)) == len(demo_clients.DEMO_CLIENTS)

    demo_clients.clear(gateway_conn)

    assert portfolios.simulated_portfolio_ids(gateway_conn) == []
    assert gateway_conn.fetchone("SELECT COUNT(*) AS n FROM portfolios")["n"] == 0
    assert gateway_conn.fetchone("SELECT COUNT(*) AS n FROM portfolio_holdings")["n"] == 0
    assert demo_clients.outstanding(gateway_conn)["clean"] is True


def test_clearing_reaches_an_archived_demo_portfolio(gateway_conn, monkeypatch):
    """`listing` would not have seen it, and its holdings would have stayed in
    the database after a clear that reported success."""
    monkeypatch.setattr(demo_clients, "_require_development_stage", lambda: "PRE_ALPHA")
    demo_clients.seed(gateway_conn)
    owner = portfolios.for_client("avery")
    retired = portfolios.create(gateway_conn, owner, display_name="Old",
                                portfolio_type=portfolios.TYPE_SECONDARY, simulated=True)
    holdings.record(gateway_conn, retired, ticker="SYN8", shares=3, simulated=True)
    portfolios.archive(gateway_conn, retired["portfolio_id"], owner)

    demo_clients.clear(gateway_conn)

    assert gateway_conn.fetchone("SELECT COUNT(*) AS n FROM portfolios")["n"] == 0
    assert gateway_conn.fetchone("SELECT COUNT(*) AS n FROM portfolio_holdings")["n"] == 0


def test_a_real_clients_portfolio_is_never_cleared(gateway_conn, monkeypatch):
    monkeypatch.setattr(demo_clients, "_require_development_stage", lambda: "PRE_ALPHA")
    demo_clients.seed(gateway_conn)
    real = portfolios.primary_for(gateway_conn, portfolios.for_client("paying-client"))
    holdings.record(gateway_conn, real, ticker="SYN1", shares=10, cost_basis=4)

    demo_clients.clear(gateway_conn)

    still_there = portfolios.primary_for(gateway_conn, portfolios.for_client("paying-client"))
    assert still_there["portfolio_id"] == real["portfolio_id"]
    assert len(holdings.listing(gateway_conn, still_there)) == 1


# --- the tripwire (§7, Risk 3) -----------------------------------------------------


def test_nothing_outside_portfolios_queries_the_portfolios_table():
    """The single-gate property is only as strong as review, so this is the
    review written down.

    `resolve()` is worth having only while it is the *only* way to a portfolio. A
    second retrieval path would not look like a bypass when it was added - it
    would look like a convenience - and it would be found later, by somebody
    reading the wrong client's positions.

    Scanned by source rather than by naming convention, in the style of
    `test_no_route_is_reachable_without_a_declared_capability`."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    allowed = {"portfolios.py"}
    # The table in SQL position, matched against the whole file with whitespace
    # collapsed - a statement broken across several source lines is still one
    # statement, and a per-line scan would let exactly that through.
    sql = re.compile(r"(?:FROM|INTO|UPDATE|JOIN)\s+portfolios", re.IGNORECASE)
    offenders = []
    for path in sorted((root / "gateway").glob("*.py")):
        if path.name in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        # The DDL a module hands to executescript is not a query; the schema
        # itself has to name its own table.
        flattened = " ".join(text.replace("portfolios.SCHEMA", "").split())
        if sql.search(flattened):
            offenders.append(f"{path.name}: {sql.search(flattened).group(0)}")

    assert not offenders, (
        "these query the portfolios table directly, going around portfolios.resolve():\n  "
        + "\n  ".join(offenders)
        + "\nReach a portfolio through portfolios.resolve() or portfolios.listing()."
    )


def test_holdings_cannot_be_reached_without_a_resolved_portfolio(gateway_conn):
    """The other half of the same property. A portfolio id is something a caller
    could have got anywhere; a resolved portfolio is evidence the guard ran."""
    real = portfolios.primary_for(gateway_conn, portfolios.for_client("avery"))

    for wrong in (real["portfolio_id"], "avery", None, {"portfolio_id": ""}):
        with pytest.raises(TypeError):
            holdings.listing(gateway_conn, wrong)
        with pytest.raises(TypeError):
            holdings.record(gateway_conn, wrong, ticker="SYN1", shares=1)


# --- agent context isolation (§9.4) ------------------------------------------------


def test_a_turn_reaches_the_portfolio_of_whoever_is_speaking(gateway_conn):
    """Addendum 44 §9.4: when a turn changes clients, the previous portfolio
    context must not persist. Structurally satisfied - the tools take `subject`
    from the session on every call (§96) - and asserted here rather than assumed,
    because "structurally satisfied" is a claim about code that can change."""
    from gateway import roles, tools

    def run(subject, name, arguments=None):
        return tools.execute(gateway_conn, name, arguments or {},
                             role=roles.ROLE_CLIENT, subject=subject)

    run("avery", "record_holding", {"ticker": "SYN1", "shares": 100})
    run("morgan", "record_holding", {"ticker": "SYN2", "shares": 5})

    assert [h["ticker"] for h in run("avery", "list_holdings")["holdings"]] == ["SYN1"]
    assert [h["ticker"] for h in run("morgan", "list_holdings")["holdings"]] == ["SYN2"]
