"""Portfolio ownership and isolation (backend/portfolios.py; TQ-44,
docs/SPEC_RECONCILIATION.md §99; moved behind the backend by TQ-69, §110).

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

from backend import holdings, portfolio_providers, portfolios
from gateway import demo_clients


# --- ownership isolation (§15.1) ---------------------------------------------------


def test_an_owner_resolves_their_own_portfolio(portfolio_conn):
    avery = portfolios.for_client("avery")
    created = portfolios.create(portfolio_conn, avery, display_name="Portfolio")

    found = portfolios.resolve(portfolio_conn, created["portfolio_id"], avery)

    assert found["portfolio_id"] == created["portfolio_id"]
    assert (found["owner_type"], found["owner_id"]) == (portfolios.OWNER_CLIENT, "avery")


def test_a_client_cannot_resolve_another_clients_portfolio(portfolio_conn):
    """The property §93 established for conversations, applied to money - and
    the attack addendum 44 §5.2 says the new id makes possible at all."""
    avery = portfolios.for_client("avery")
    morgan = portfolios.for_client("morgan")
    theirs = portfolios.create(portfolio_conn, avery, display_name="Portfolio")

    with pytest.raises(portfolios.NotAuthorized):
        portfolios.resolve(portfolio_conn, theirs["portfolio_id"], morgan)


def test_a_client_cannot_resolve_a_superuser_portfolio(portfolio_conn):
    """SUPERUSER is a separate owner domain, and the separation runs both ways:
    §3.3 stops the operator reaching a client, and this stops the reverse."""
    operator = portfolios.for_superuser()
    theirs = portfolios.create(portfolio_conn, operator, display_name="House")

    with pytest.raises(portfolios.NotAuthorized):
        portfolios.resolve(portfolio_conn, theirs["portfolio_id"], portfolios.for_client("avery"))


def test_a_superuser_cannot_resolve_a_clients_portfolio(portfolio_conn):
    """There is no superuser branch (addendum 44 §5.3). The operator holds every
    *capability* in this system - and holds no client's portfolio, because
    ownership and capability are separate questions (§2.1).

    An administrative route to a client's holdings is not merely unbuilt, it is
    refused: §10 permits one only through an explicitly authorized workflow, and
    none exists to authorize it."""
    avery = portfolios.for_client("avery")
    theirs = portfolios.create(portfolio_conn, avery, display_name="Portfolio")

    with pytest.raises(portfolios.NotAuthorized):
        portfolios.resolve(portfolio_conn, theirs["portfolio_id"], portfolios.for_superuser())


def test_a_guessed_id_does_not_bypass_authorization(portfolio_conn):
    avery = portfolios.for_client("avery")
    portfolios.create(portfolio_conn, avery, display_name="Portfolio")

    for guess in ("pf-0", "pf-" + "0" * 32, "", None, "'; DROP TABLE portfolios; --"):
        with pytest.raises(portfolios.NotAuthorized):
            portfolios.resolve(portfolio_conn, guess, avery)


def test_a_portfolio_id_is_not_sequential(portfolio_conn):
    """§3.5. The guard makes enumeration useless; this makes it pointless. A
    sequential id would leak a portfolio count from any single id - a fact about
    other clients even when their data is unreachable."""
    avery = portfolios.for_client("avery")
    ids = {portfolios.create(portfolio_conn, avery, display_name=f"P{n}",
                             portfolio_type=portfolios.TYPE_SECONDARY)["portfolio_id"]
           for n in range(5)}

    assert len(ids) == 5
    assert all(pid.startswith("pf-") and len(pid) == 35 for pid in ids)
    # Nothing incrementing: no two differ only in a trailing digit.
    assert len({pid[:-1] for pid in ids}) == 5


def test_absent_foreign_and_archived_raise_the_same_refusal(portfolio_conn):
    """Addendum 44 §9.3 is about what a caller can *tell apart*, so this asserts
    the message as well as the type. A refusal that said "archived" for one and
    "not found" for another would confirm that somebody else's portfolio exists,
    which is the fact being withheld."""
    avery = portfolios.for_client("avery")
    morgan = portfolios.for_client("morgan")
    foreign = portfolios.create(portfolio_conn, morgan, display_name="Portfolio")
    archived = portfolios.create(portfolio_conn, avery, display_name="Old",
                                 portfolio_type=portfolios.TYPE_SECONDARY)
    portfolios.archive(portfolio_conn, archived["portfolio_id"], avery)

    refusals = []
    for portfolio_id in ("pf-does-not-exist", foreign["portfolio_id"],
                         archived["portfolio_id"]):
        with pytest.raises(portfolios.NotAuthorized) as raised:
            portfolios.resolve(portfolio_conn, portfolio_id, avery)
        refusals.append(str(raised.value))

    assert refusals == [portfolios.REFUSAL] * 3


def test_listing_returns_only_this_owners_portfolios(portfolio_conn):
    avery = portfolios.for_client("avery")
    morgan = portfolios.for_client("morgan")
    portfolios.create(portfolio_conn, avery, display_name="A")
    portfolios.create(portfolio_conn, morgan, display_name="M")
    portfolios.create(portfolio_conn, portfolios.for_superuser(), display_name="House")

    assert [p["display_name"] for p in portfolios.listing(portfolio_conn, avery)] == ["A"]
    assert [p["display_name"] for p in portfolios.listing(portfolio_conn, morgan)] == ["M"]


def test_listing_omits_archived(portfolio_conn):
    avery = portfolios.for_client("avery")
    kept = portfolios.create(portfolio_conn, avery, display_name="Kept")
    gone = portfolios.create(portfolio_conn, avery, display_name="Gone",
                             portfolio_type=portfolios.TYPE_SECONDARY)
    portfolios.archive(portfolio_conn, gone["portfolio_id"], avery)

    assert [p["portfolio_id"] for p in portfolios.listing(portfolio_conn, avery)] == [
        kept["portfolio_id"]]


def test_archiving_reaches_only_your_own(portfolio_conn):
    avery = portfolios.for_client("avery")
    theirs = portfolios.create(portfolio_conn, avery, display_name="Portfolio")

    with pytest.raises(portfolios.NotAuthorized):
        portfolios.archive(portfolio_conn, theirs["portfolio_id"],
                           portfolios.for_client("morgan"))

    assert portfolios.resolve(portfolio_conn, theirs["portfolio_id"], avery)["status"] == (
        portfolios.STATUS_ACTIVE)


# --- the §15.5 regression ----------------------------------------------------------


def test_a_client_cannot_receive_the_superuser_portfolio_when_it_is_the_only_one(portfolio_conn):
    """§93's leak, in portfolio form. Permanent.

    The original was a "newest wins" lookup with no owner filter: a client
    connecting received the operator's entire conversation, because it was the
    only one in the database. The shape is what recurs - a query that returns
    *the* row rather than *this owner's* row is indistinguishable from a correct
    one for as long as there is exactly one row.

    So: a SUPERUSER portfolio as the only row in the table, and a client context
    must resolve nothing and list nothing."""
    operator = portfolios.for_superuser()
    only_row = portfolios.create(portfolio_conn, operator, display_name="House")
    assert portfolio_conn.fetchone("SELECT COUNT(*) AS n FROM portfolios")["n"] == 1

    client = portfolios.for_client("avery")

    assert portfolios.listing(portfolio_conn, client) == []
    assert portfolios.owned(portfolio_conn, client) == []
    with pytest.raises(portfolios.NotAuthorized):
        portfolios.resolve(portfolio_conn, only_row["portfolio_id"], client)

    # And the operator still reaches their own, so this is isolation rather than
    # a check that refuses everybody.
    assert portfolios.resolve(portfolio_conn, only_row["portfolio_id"], operator)["display_name"] == (
        "House")


def test_primary_for_creates_rather_than_adopting_the_only_portfolio(portfolio_conn):
    """The same leak one layer up. `primary_for` creates on first use (§3.8), and
    the failure mode is that it finds the superuser's and calls it the client's."""
    operator = portfolios.for_superuser()
    house = portfolios.create(portfolio_conn, operator, display_name="House")

    mine = portfolios.primary_for(portfolio_conn, portfolios.for_client("avery"))

    assert mine["portfolio_id"] != house["portfolio_id"]
    assert (mine["owner_type"], mine["owner_id"]) == (portfolios.OWNER_CLIENT, "avery")


def test_primary_for_is_stable_across_calls(portfolio_conn):
    avery = portfolios.for_client("avery")
    first = portfolios.primary_for(portfolio_conn, avery)
    second = portfolios.primary_for(portfolio_conn, avery)

    assert first["portfolio_id"] == second["portfolio_id"]
    assert len(portfolios.listing(portfolio_conn, avery)) == 1


# --- ownership is resolved, never received (§9.2) ----------------------------------


def test_a_raw_client_id_cannot_be_passed_where_an_owner_is_required(portfolio_conn):
    """A string is a claim; an OwnerContext is a resolved fact. Accepting the
    string would put the decision about whose money is visible into whatever code
    happened to build it - and would look perfectly correct."""
    portfolios.create(portfolio_conn, portfolios.for_client("avery"), display_name="P")

    for wrong in ("avery", None, 42, {"owner_id": "avery"}):
        with pytest.raises(TypeError):
            portfolios.listing(portfolio_conn, wrong)
        with pytest.raises(TypeError):
            portfolios.resolve(portfolio_conn, "pf-whatever", wrong)


def test_an_owner_context_needs_an_owner(portfolio_conn):
    for nobody in ("", "   ", None, 7):
        with pytest.raises(portfolios.UnknownVocabulary):
            portfolios.for_client(nobody)


def test_an_owner_id_is_normalised_the_way_a_login_is(portfolio_conn):
    """Two normalisations that could disagree are two identities for one person.
    This is the same function `clients.normalise` applies at the door."""
    created = portfolios.create(portfolio_conn, portfolios.for_client("  AVERY  "),
                                display_name="P")

    assert created["owner_id"] == "avery"
    assert portfolios.resolve(portfolio_conn, created["portfolio_id"],
                              portfolios.for_client("Avery"))


def test_an_unknown_owner_type_is_refused(portfolio_conn):
    with pytest.raises(portfolios.UnknownVocabulary):
        portfolios.OwnerContext("ADMIN", "avery")


# --- fail closed on every vocabulary, writing and reading (§3.6) -------------------


@pytest.mark.parametrize("field,value", [
    ("portfolio_type", "RETIREMENT"),
    ("provider_type", "FIDELITY"),
    ("data_mode", "REAL"),
])
def test_an_unknown_vocabulary_value_is_refused_on_write(portfolio_conn, field, value):
    with pytest.raises(portfolios.UnknownVocabulary):
        portfolios.create(portfolio_conn, portfolios.for_client("avery"),
                          display_name="P", **{field: value})


@pytest.mark.parametrize("field,value", [
    ("portfolio_type", "RETIREMENT"),
    ("provider_type", "FIDELITY"),
    ("data_mode", "REAL"),
    ("status", "frozen"),
])
def test_an_unknown_vocabulary_value_raises_on_read(portfolio_conn, field, value):
    """Not only on write. A row that reached the database another way - an older
    build, a hand edit, a restored backup - must not be interpreted by guessing
    what its value meant. A portfolio whose data_mode is unreadable is one whose
    pricing rule cannot be applied, and guessing which side of `is_priced` it
    falls on is how a simulated number gets shown as somebody's money."""
    avery = portfolios.for_client("avery")
    created = portfolios.create(portfolio_conn, avery, display_name="P")
    portfolio_conn.execute(f"UPDATE portfolios SET {field} = ? WHERE portfolio_id = ?",
                         (value, created["portfolio_id"]))

    with pytest.raises(portfolios.UnknownVocabulary):
        portfolios.resolve(portfolio_conn, created["portfolio_id"], avery)
    with pytest.raises(portfolios.UnknownVocabulary):
        portfolios.listing(portfolio_conn, avery)


def test_an_unreadable_row_still_refuses_a_stranger_without_telling_them_why(portfolio_conn):
    """The ordering in `resolve` matters. A corrupt row must fail closed for its
    owner *and* stay invisible to everybody else - if interpretation ran first,
    `UnknownVocabulary` where a stranger expected `NotAuthorized` would confirm
    that the id exists, which is exactly what §9.3 withholds."""
    avery = portfolios.for_client("avery")
    created = portfolios.create(portfolio_conn, avery, display_name="P")
    portfolio_conn.execute("UPDATE portfolios SET data_mode = 'REAL' WHERE portfolio_id = ?",
                         (created["portfolio_id"],))

    with pytest.raises(portfolios.NotAuthorized) as raised:
        portfolios.resolve(portfolio_conn, created["portfolio_id"],
                           portfolios.for_client("morgan"))
    assert str(raised.value) == portfolios.REFUSAL


def test_an_unreadable_owner_type_matches_nobody(portfolio_conn):
    """Fail closed by construction: a stored owner_type outside the vocabulary
    cannot equal either known one, so the row is unreachable rather than
    reachable-by-whoever-guesses-its-domain."""
    avery = portfolios.for_client("avery")
    created = portfolios.create(portfolio_conn, avery, display_name="P")
    portfolio_conn.execute("UPDATE portfolios SET owner_type = 'ADMIN' WHERE portfolio_id = ?",
                         (created["portfolio_id"],))

    for owner in (avery, portfolios.for_superuser(), portfolios.for_superuser("admin")):
        with pytest.raises(portfolios.NotAuthorized):
            portfolios.resolve(portfolio_conn, created["portfolio_id"], owner)


def test_a_portfolio_needs_a_display_name(portfolio_conn):
    with pytest.raises(portfolios.UnknownVocabulary):
        portfolios.create(portfolio_conn, portfolios.for_client("avery"), display_name="  ")


def test_the_schema_refuses_an_unowned_portfolio(portfolio_conn):
    """§2.3's "a missing owner denies", as a schema fact rather than a runtime
    hope. Asserted at the database because the column being NOT NULL is the part
    that survives somebody adding a new insert path."""
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        portfolio_conn.execute(
            "INSERT INTO portfolios (portfolio_id, owner_type, owner_id, portfolio_type, "
            "display_name, provider_type, data_mode, status, created_at, updated_at) "
            "VALUES ('pf-x', NULL, NULL, 'PRIMARY', 'P', 'MANUAL', 'MANUAL', 'active', "
            "'2026-01-01', '2026-01-01')")


# --- the pricing rule (§3.7) -------------------------------------------------------


def test_only_a_live_portfolio_is_priced(portfolio_conn):
    """The single condition for whether anything market-derived may be shown.

    Everything this system generates is simulated (addendum 25), which is why
    §96 refused market value and `portfolio_valuation` stands declared-and-unbuilt.
    Addendum 44 supplied the field that could one day say otherwise; it did not
    supply prices."""
    avery = portfolios.for_client("avery")
    made = {}
    for mode in portfolios.DATA_MODES:
        made[mode] = portfolios.create(
            portfolio_conn, avery, display_name=mode, data_mode=mode,
            portfolio_type=portfolios.TYPE_SECONDARY,
            provider_type=(portfolios.PROVIDER_MANUAL if mode == portfolios.MODE_MANUAL
                           else portfolios.PROVIDER_SIMULATED))

    assert portfolios.is_priced(made[portfolios.MODE_LIVE]) is True
    assert portfolios.is_priced(made[portfolios.MODE_SIMULATED]) is False
    assert portfolios.is_priced(made[portfolios.MODE_MANUAL]) is False


def test_a_portfolio_made_by_ordinary_use_is_not_priced(portfolio_conn):
    """What a client actually gets. `primary_for` builds a MANUAL portfolio, so
    the answer for every real portfolio in this build today is False - and it is
    False because of the rule, not because the feature is missing."""
    assert portfolios.is_priced(
        portfolios.primary_for(portfolio_conn, portfolios.for_client("avery"))) is False


def test_the_concentration_report_takes_its_priced_flag_from_the_one_rule(portfolio_conn):
    """Not a second hard-coded False. Routed through `is_priced` so the report
    cannot drift from every other caller's answer to the same question."""
    portfolio = portfolios.primary_for(portfolio_conn, portfolios.for_client("avery"))
    holdings.record(portfolio_conn, portfolio, symbol="SYN1", quantity=10, average_cost=5)

    provider = portfolio_providers.for_portfolio(portfolio)
    report = holdings.concentration(provider.get_holdings(portfolio_conn, portfolio))

    assert report["priced"] is False
    assert report["priced"] == portfolios.is_priced(portfolio)


# --- demo data (§96's convention, applied to portfolios) ---------------------------
#
# These now span both databases (TQ-69, §110): the login and the representative
# are the Gateway's, the portfolio and its positions are the backend's, and the
# seeder reaches the second over HTTP through the same client the client's own
# agent uses. Every one of them therefore takes `gateway_conn` *and*
# `portfolios_client`, which is the increment made visible in a fixture list.


def test_demo_portfolios_are_flagged_and_cleared(gateway_conn, portfolio_conn,
                                                 portfolios_client, monkeypatch):
    monkeypatch.setattr(demo_clients, "_require_development_stage", lambda: "PRE_ALPHA")
    demo_clients.seed(gateway_conn, portfolios_client)

    assert len(portfolios.simulated_portfolio_ids(portfolio_conn)) == len(demo_clients.DEMO_CLIENTS)

    demo_clients.clear(gateway_conn, portfolios_client)

    assert portfolios.simulated_portfolio_ids(portfolio_conn) == []
    assert portfolio_conn.fetchone("SELECT COUNT(*) AS n FROM portfolios")["n"] == 0
    assert portfolio_conn.fetchone("SELECT COUNT(*) AS n FROM portfolio_holdings")["n"] == 0
    assert demo_clients.outstanding(gateway_conn, portfolios_client)["clean"] is True


def test_clearing_reaches_an_archived_demo_portfolio(gateway_conn, portfolio_conn,
                                                     portfolios_client, monkeypatch):
    """`listing` would not have seen it, and its holdings would have stayed in
    the database after a clear that reported success."""
    monkeypatch.setattr(demo_clients, "_require_development_stage", lambda: "PRE_ALPHA")
    demo_clients.seed(gateway_conn, portfolios_client)
    owner = portfolios.for_client("avery")
    retired = portfolios.create(portfolio_conn, owner, display_name="Old",
                                portfolio_type=portfolios.TYPE_SECONDARY, simulated=True)
    holdings.record(portfolio_conn, retired, symbol="SYN8", quantity=3, simulated=True)
    portfolios.archive(portfolio_conn, retired["portfolio_id"], owner)

    demo_clients.clear(gateway_conn, portfolios_client)

    assert portfolio_conn.fetchone("SELECT COUNT(*) AS n FROM portfolios")["n"] == 0
    assert portfolio_conn.fetchone("SELECT COUNT(*) AS n FROM portfolio_holdings")["n"] == 0


def test_a_real_clients_portfolio_is_never_cleared(gateway_conn, portfolio_conn,
                                                   portfolios_client, monkeypatch):
    monkeypatch.setattr(demo_clients, "_require_development_stage", lambda: "PRE_ALPHA")
    demo_clients.seed(gateway_conn, portfolios_client)
    real = portfolios.primary_for(portfolio_conn, portfolios.for_client("paying-client"))
    holdings.record(portfolio_conn, real, symbol="SYN1", quantity=10, average_cost=4)

    demo_clients.clear(gateway_conn, portfolios_client)

    still_there = portfolios.primary_for(portfolio_conn, portfolios.for_client("paying-client"))
    assert still_there["portfolio_id"] == real["portfolio_id"]
    assert len(holdings.listing(portfolio_conn, still_there)) == 1


# --- the tripwire (§7, Risk 3) -----------------------------------------------------


def test_nothing_outside_portfolios_queries_the_portfolios_table():
    """The single-gate property is only as strong as review, so this is the
    review written down.

    `resolve()` is worth having only while it is the *only* way to a portfolio. A
    second retrieval path would not look like a bypass when it was added - it
    would look like a convenience - and it would be found later, by somebody
    reading the wrong client's positions.

    Scanned by source rather than by naming convention, in the style of
    `test_no_route_is_reachable_without_a_declared_capability`.

    **Both trees since TQ-69** (§110). The table moved to `backend/`, and a scan
    that had stayed pointed at `gateway/` would have gone on passing while saying
    nothing - a tripwire aimed at where the danger used to be. That is §105's
    lesson in a different costume: a check that cannot fail is not a check."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    allowed = {"portfolios.py", "portfolio_migration.py"}
    # The table in SQL position, matched against the whole file with whitespace
    # collapsed - a statement broken across several source lines is still one
    # statement, and a per-line scan would let exactly that through.
    sql = re.compile(r"(?:FROM|INTO|UPDATE|JOIN)\s+portfolios", re.IGNORECASE)
    offenders = []
    for tree in ("gateway", "backend"):
        for path in sorted((root / tree).glob("*.py")):
            if path.name in allowed:
                continue
            text = path.read_text(encoding="utf-8")
            # The DDL a module hands to executescript is not a query; the schema
            # itself has to name its own table.
            flattened = " ".join(text.replace("portfolios.SCHEMA", "").split())
            if sql.search(flattened):
                offenders.append(f"{tree}/{path.name}: {sql.search(flattened).group(0)}")

    assert not offenders, (
        "these query the portfolios table directly, going around portfolios.resolve():\n  "
        + "\n  ".join(offenders)
        + "\nReach a portfolio through portfolios.resolve() or portfolios.listing()."
    )


def test_no_gateway_module_reaches_the_backends_portfolio_subsystem():
    """The tripwire TQ-69 needs and TQ-44 did not (§110).

    The scan above catches SQL. It does not catch a Gateway module that imports
    `backend.portfolios` and calls `resolve(gateway_conn, ...)` - which would
    look entirely reasonable, would pass every other check here, and would put
    the guard back on the wrong side of the boundary this increment moved it
    across.

    **One exception, and it is a rule rather than a capability:**
    `gateway/clients.py` imports `normalise`, so that there is one definition of
    when two owner ids are the same person. A second normalisation that drifted
    would make one client into two owners, and no ownership comparison could
    detect it - both comparisons would be correct, about different people. The
    exception is narrow enough to state, so it is stated, and this checks that
    nothing else is taken from that module."""
    import re
    from pathlib import Path

    from conftest import executable_source

    root = Path(__file__).resolve().parent.parent
    forbidden = re.compile(
        r"backend[.](portfolios|holdings|portfolio_providers|portfolio_migration)\b")
    offenders = []
    for path in sorted((root / "gateway").glob("*.py")):
        text = executable_source(path)
        if path.name == "clients.py":
            # Allowed to name the module; not allowed to use more of it than the
            # one shared rule.
            used = set(re.findall(r"portfolios[.](\w+)", text)) - {"normalise"}
            assert not used, (
                f"gateway/clients.py uses backend.portfolios.{sorted(used)}. It may "
                "share the one normalisation rule and nothing else.")
            continue
        found = forbidden.search(text)
        if found:
            offenders.append(f"{path.name}: {found.group(0)}")

    assert not offenders, (
        "these Gateway modules reach the backend's portfolio subsystem directly:\n  "
        + "\n  ".join(offenders)
        + "\nThe Gateway reaches portfolios over HTTP, through "
          "gateway/portfolio_client.py. Importing those modules would put the "
          "ownership guard back on the Gateway's side of the boundary."
    )


def test_holdings_cannot_be_reached_without_a_resolved_portfolio(portfolio_conn):
    """The other half of the same property. A portfolio id is something a caller
    could have got anywhere; a resolved portfolio is evidence the guard ran."""
    real = portfolios.primary_for(portfolio_conn, portfolios.for_client("avery"))

    for wrong in (real["portfolio_id"], "avery", None, {"portfolio_id": ""}):
        with pytest.raises(TypeError):
            holdings.listing(portfolio_conn, wrong)
        with pytest.raises(TypeError):
            holdings.record(portfolio_conn, wrong, symbol="SYN1", quantity=1)


# --- agent context isolation (§9.4) ------------------------------------------------


def test_a_turn_reaches_the_portfolio_of_whoever_is_speaking(gateway_conn,
                                                             portfolios_client):
    """Addendum 44 §9.4: when a turn changes clients, the previous portfolio
    context must not persist. Structurally satisfied - the tools take `subject`
    from the session on every call (§96) - and asserted here rather than assumed,
    because "structurally satisfied" is a claim about code that can change.

    Since TQ-69 it is asserted **over HTTP**, which makes it a stronger claim
    than it was: the tools no longer read a local table, so what this proves is
    that two clients speaking through one Gateway process reach two different
    portfolios in the backend, through a check the Gateway does not perform."""
    from gateway import roles, tools

    def run(subject, name, arguments=None):
        return tools.execute(gateway_conn, name, arguments or {},
                             role=roles.ROLE_CLIENT, subject=subject,
                             portfolios_client=portfolios_client)

    run("avery", "record_holding", {"symbol": "SYN1", "quantity": 100})
    run("morgan", "record_holding", {"symbol": "SYN2", "quantity": 5})

    assert [h["symbol"] for h in run("avery", "list_holdings")["holdings"]] == ["SYN1"]
    assert [h["symbol"] for h in run("morgan", "list_holdings")["holdings"]] == ["SYN2"]


# --- the canonical holding shape (TQ-45a) ------------------------------------------


def test_the_asset_class_vocabulary_is_the_house_one():
    """One model of one fact (spec §11 Q1).

    TQ-44 introduced EQUITY/OPTION from addendum 44 §3.4 while this system
    already had eleven finer codes, which is the second naming scheme §70 refused
    once before for addendum 39's labels. This asserts the two can never drift:
    the Gateway's vocabulary is `reference_data`'s codes plus `unknown`, and a
    class added to the registry appears here without anybody remembering to
    copy it."""
    from backend.reference_data import ASSET_CLASSES as house

    assert set(holdings.ASSET_CLASSES) == {code for code, _ in house} | {"unknown"}
    assert holdings.ASSET_UNKNOWN == "unknown"
    for retired in ("EQUITY", "OPTION", "UNKNOWN"):
        assert retired not in holdings.ASSET_CLASSES


def test_a_client_may_hold_a_class_this_system_cannot_process(portfolio_conn):
    """`implemented_asset_classes` says what this organization can *process*, not
    what somebody is allowed to own. Refusing to record a fact about their money
    because our reference data is incomplete is the refusal `_clean_symbol`
    already declines to make about symbols."""
    from backend import boot_config

    portfolio = portfolios.primary_for(portfolio_conn, portfolios.for_client("avery"))
    unimplemented = [c for c in holdings.ASSET_CLASSES
                     if c not in boot_config.load().implemented_asset_classes
                     and c != holdings.ASSET_UNKNOWN]
    assert unimplemented, "this test needs a class the system does not implement"

    recorded = holdings.record(portfolio_conn, portfolio, symbol="XYZ", quantity=1,
                               asset_class=unimplemented[0])
    assert recorded["asset_class"] == unimplemented[0]


def test_an_asset_class_is_normalised_rather_than_case_sensitive(portfolio_conn):
    portfolio = portfolios.primary_for(portfolio_conn, portfolios.for_client("avery"))
    recorded = holdings.record(portfolio_conn, portfolio, symbol="SYN1", quantity=1,
                               asset_class="  Stock_Option  ")
    assert recorded["asset_class"] == "stock_option"


def test_an_unrecognised_asset_class_is_refused(portfolio_conn):
    """`equity` is addendum 44's word, and it is deliberately not a house code -
    it does not settle stock versus etf. Refused rather than interpreted."""
    portfolio = portfolios.primary_for(portfolio_conn, portfolios.for_client("avery"))
    with pytest.raises(holdings.HoldingRefused):
        holdings.record(portfolio_conn, portfolio, symbol="SYN1", quantity=1,
                        asset_class="equity")


def test_a_holding_records_when_its_data_is_from_not_when_it_was_written(portfolio_conn):
    """`as_of` is supplied by a provider that knows when its data is from, and
    defaults to now for a client speaking. That distinction is why the field was
    renamed from `stated_at` - only a person states anything, and the shape has
    to fit a brokerage account too."""
    portfolio = portfolios.primary_for(portfolio_conn, portfolios.for_client("avery"))

    default = holdings.record(portfolio_conn, portfolio, symbol="SYN1", quantity=1)
    supplied = holdings.record(portfolio_conn, portfolio, symbol="SYN2", quantity=1,
                               as_of="2024-01-01T00:00:00+00:00")

    assert default["as_of"]
    assert supplied["as_of"] == "2024-01-01T00:00:00+00:00"
