"""Client-owned holdings (gateway/holdings.py + gateway/demo_clients.py;
TQ-42, SPEC_RECONCILIATION §96).

§95 left `portfolio_analysis` unbuilt because the only portfolio in this system
belongs to the operator. This is the data model that answers it, and the first
section is the property that makes it safe to exist at all: **one client's
representative cannot reach another client's positions.**

The rest is about not lying with numbers. Weights are computed here rather than
described to a model, because a model asked to percentage-weight a portfolio
produces something *shaped* like arithmetic. And nothing is valued, because
every price this system can produce is simulated and applying it to somebody's
real positions would present synthetic output as real.
"""

import pytest

from gateway import client_agent, demo_clients, holdings, portfolios, roles, tools


def _pf(conn, client_id):
    """This client's own portfolio, through the gate (TQ-44).

    Holdings are no longer keyed by client id: they hang off a portfolio, and a
    portfolio is reached only through `portfolios.resolve` - which `primary_for`
    goes through. So every call below carries the ownership check with it, which
    is exactly the property these tests are about."""
    return portfolios.primary_for(conn, portfolios.for_client(client_id))


# --- isolation, which is the whole reason this may exist --------------------------


def test_one_client_cannot_see_another_s_positions(gateway_conn):
    """The property §93 established for conversations, applied to money."""
    avery = _pf(gateway_conn, "avery")
    morgan = _pf(gateway_conn, "morgan")
    holdings.record(gateway_conn, avery, symbol="SYN1", quantity=100, average_cost=10)
    holdings.record(gateway_conn, morgan, symbol="SYN2", quantity=5, average_cost=200)

    assert [h["symbol"] for h in holdings.listing(gateway_conn, avery)] == ["SYN1"]
    assert [h["symbol"] for h in holdings.listing(gateway_conn, morgan)] == ["SYN2"]
    assert holdings.one(gateway_conn, avery, "SYN2") is None


def test_forgetting_reaches_only_your_own(gateway_conn):
    avery = _pf(gateway_conn, "avery")
    morgan = _pf(gateway_conn, "morgan")
    holdings.record(gateway_conn, avery, symbol="SYN1", quantity=100, average_cost=10)
    holdings.record(gateway_conn, morgan, symbol="SYN1", quantity=7, average_cost=11)

    assert holdings.forget(gateway_conn, avery, "SYN1") is True

    assert holdings.listing(gateway_conn, avery) == []
    assert len(holdings.listing(gateway_conn, morgan)) == 1


def test_forget_all_is_also_per_client(gateway_conn):
    avery = _pf(gateway_conn, "avery")
    morgan = _pf(gateway_conn, "morgan")
    holdings.record(gateway_conn, avery, symbol="SYN1", quantity=1, average_cost=1)
    holdings.record(gateway_conn, morgan, symbol="SYN2", quantity=1, average_cost=1)

    assert holdings.forget_all(gateway_conn, avery) == 1
    assert len(holdings.listing(gateway_conn, morgan)) == 1


def test_a_holding_has_to_belong_to_somebody(gateway_conn):
    """No default owner. A blank owner would become a shared bucket, which is the
    shape of the bug this whole area exists downstream of.

    Since TQ-44 the refusal happens one layer earlier and harder: holdings take a
    *resolved portfolio*, so there is no argument here that could be blank. A
    client id, blank or not, is not something this function accepts at all."""
    for nobody in ("", "   ", None, "avery"):
        with pytest.raises(TypeError):
            holdings.record(gateway_conn, nobody, symbol="SYN1", quantity=1)

    for nobody in ("", "   ", None):
        with pytest.raises(portfolios.UnknownVocabulary):
            portfolios.for_client(nobody)


def test_the_tools_take_the_subject_from_the_session_not_the_arguments(gateway_conn):
    """The model is never asked whose holdings to read, so "read somebody
    else's" is not a call it can construct."""
    avery = _pf(gateway_conn, "avery")
    holdings.record(gateway_conn, avery, symbol="SYN1", quantity=100, average_cost=10)

    # Even naming another client in the arguments changes nothing.
    result = tools.execute(gateway_conn, "list_holdings",
                           {"client_id": "avery", "subject": "avery"},
                           role=roles.ROLE_CLIENT, subject="morgan")
    assert result["holdings"] == []


def test_a_holdings_tool_without_a_subject_is_refused(gateway_conn):
    """Refused rather than defaulted: a holdings call with no owner has nobody
    to answer for, and picking somebody would be the bug."""
    for nobody in (None, "", "  "):
        outcome = tools.execute(gateway_conn, "list_holdings", {},
                                role=roles.ROLE_CLIENT, subject=nobody)
        assert "error" in outcome and "whose" in outcome["error"]


def test_holdings_tools_are_refused_to_a_role_without_the_capability(gateway_conn):
    """The capability check still runs first, as it does for every other tool."""
    import dataclasses  # noqa: F401  (kept for symmetry with the roles suite)

    from gateway import roles as roles_module

    assert not roles_module.allows(roles_module.ROLE_INTERNAL, roles_module.CAP_HOLDINGS)
    outcome = tools.execute(gateway_conn, "list_holdings", {},
                            role=roles_module.ROLE_INTERNAL, subject="staff")
    assert "Not permitted" in outcome["error"]


# --- what gets recorded, and what is refused ---------------------------------------


def test_a_holding_is_recorded_as_stated(gateway_conn):
    avery = _pf(gateway_conn, "avery")
    recorded = holdings.record(gateway_conn, avery, symbol="syn1", quantity=100,
                               average_cost=42.5, acquired_on="2024-03-11")
    assert recorded["symbol"] == "SYN1", "tickers are normalised, not stored as typed"
    assert recorded["quantity"] == 100
    assert recorded["average_cost"] == 42.5
    assert recorded["as_of"]


def test_stating_a_holding_twice_is_a_correction_not_a_second_position(gateway_conn):
    """A representative who accumulated both would be reporting a position its
    owner never held."""
    avery = _pf(gateway_conn, "avery")
    holdings.record(gateway_conn, avery, symbol="SYN1", quantity=100, average_cost=10)
    holdings.record(gateway_conn, avery, symbol="SYN1", quantity=150, average_cost=11)

    rows = holdings.listing(gateway_conn, avery)
    assert len(rows) == 1
    assert rows[0]["quantity"] == 150


def test_a_cost_basis_is_optional_because_people_do_not_always_know_it(gateway_conn):
    avery = _pf(gateway_conn, "avery")
    recorded = holdings.record(gateway_conn, avery, symbol="SYN1", quantity=100)
    assert recorded["average_cost"] is None


@pytest.mark.parametrize("bad", [0, -5, "not a number", ""])
def test_an_unusable_share_count_is_refused_rather_than_coerced(gateway_conn, bad):
    """Silently storing zero because the number would not parse is worse than
    saying the number would not parse."""
    avery = _pf(gateway_conn, "avery")
    with pytest.raises(holdings.HoldingRefused):
        holdings.record(gateway_conn, avery, symbol="SYN1", quantity=bad)


def test_a_blank_ticker_is_refused(gateway_conn):
    avery = _pf(gateway_conn, "avery")
    with pytest.raises(holdings.HoldingRefused):
        holdings.record(gateway_conn, avery, symbol="   ", quantity=1)


def test_an_unknown_ticker_is_accepted(gateway_conn):
    """Deliberately not validated against this organization's security universe:
    a client may hold something this system has never heard of, and refusing it
    would be refusing a fact about their money because our reference data is
    incomplete."""
    avery = _pf(gateway_conn, "avery")
    recorded = holdings.record(gateway_conn, avery, symbol="NOTINOURUNIVERSE",
                               quantity=1, average_cost=1)
    assert recorded["symbol"] == "NOTINOURUNIVERSE"


def test_there_is_a_ceiling_on_positions(gateway_conn, monkeypatch):
    avery = _pf(gateway_conn, "avery")
    monkeypatch.setattr(holdings, "MAX_POSITIONS", 3)
    for i in range(3):
        holdings.record(gateway_conn, avery, symbol=f"SYN{i}", quantity=1, average_cost=1)
    with pytest.raises(holdings.HoldingRefused, match="book of record"):
        holdings.record(gateway_conn, avery, symbol="SYN9", quantity=1, average_cost=1)


def test_correcting_a_holding_at_the_ceiling_is_still_allowed(gateway_conn, monkeypatch):
    """The ceiling counts *other* positions, so somebody at the limit can still
    fix one. A limit that blocked corrections would freeze a portfolio at
    whatever it last said."""
    avery = _pf(gateway_conn, "avery")
    monkeypatch.setattr(holdings, "MAX_POSITIONS", 3)
    for i in range(3):
        holdings.record(gateway_conn, avery, symbol=f"SYN{i}", quantity=1, average_cost=1)
    corrected = holdings.record(gateway_conn, avery, symbol="SYN1", quantity=99, average_cost=1)
    assert corrected["quantity"] == 99


def test_there_is_no_account_column(gateway_conn):
    """The classification decision (§96): `app/privacy_filter.py` strips
    `account_id` on egress because it does not own that file's schema. This one
    is ours, so the field does not exist - and a field that does not exist
    cannot be leaked by a reader who forgets to sanitize."""
    columns = {row["name"] for row in
               gateway_conn.fetchall("PRAGMA table_info(portfolio_holdings)")}
    for forbidden in ("account_id", "account", "account_number"):
        assert forbidden not in columns


# --- arithmetic, computed rather than narrated -------------------------------------


def test_weights_are_computed_from_stated_cost(gateway_conn):
    avery = _pf(gateway_conn, "avery")
    holdings.record(gateway_conn, avery, symbol="SYN1", quantity=100, average_cost=30)   # 3000
    holdings.record(gateway_conn, avery, symbol="SYN2", quantity=100, average_cost=10)   # 1000

    report = holdings.concentration(gateway_conn, avery)

    assert report["positions"] == 2
    assert report["known_cost"] == 4000
    assert report["weights"][0] == {"symbol": "SYN1", "cost": 3000.0, "weight_pct": 75.0}
    assert report["weights"][1]["weight_pct"] == 25.0
    assert report["largest_position"]["symbol"] == "SYN1"


def test_concentration_reports_the_top_three(gateway_conn):
    avery = _pf(gateway_conn, "avery")
    for i, cost in enumerate([50, 30, 15, 5], start=1):
        holdings.record(gateway_conn, avery, symbol=f"SYN{i}", quantity=1, average_cost=cost)
    assert holdings.concentration(gateway_conn, avery)["top_three_pct"] == 95.0


def test_nothing_is_ever_valued(gateway_conn):
    """The line §96 will not cross. Every price this organization can produce is
    simulated; applying one to a client's real positions would present synthetic
    output as real - what §95 refused for trade ideas, one field over."""
    avery = _pf(gateway_conn, "avery")
    holdings.record(gateway_conn, avery, symbol="SYN1", quantity=100, average_cost=30)
    report = holdings.concentration(gateway_conn, avery)

    assert report["priced"] is False
    assert "simulated" in report["priced_note"]
    for absent in ("market_value", "current_value", "gain", "loss", "return_pct"):
        assert absent not in report


def test_the_absence_of_a_price_is_stated_rather_than_left_to_be_noticed(gateway_conn):
    """A report that simply omitted market value would read as a portfolio worth
    its cost basis."""
    avery = _pf(gateway_conn, "avery")
    holdings.record(gateway_conn, avery, symbol="SYN1", quantity=1, average_cost=1)
    assert holdings.concentration(gateway_conn, avery)["priced_note"]


def test_a_holding_without_a_cost_basis_is_counted_but_not_weighted(gateway_conn):
    """Counted, because they own it. Not weighted, because weighting it would
    need a number nobody has."""
    avery = _pf(gateway_conn, "avery")
    holdings.record(gateway_conn, avery, symbol="SYN1", quantity=100, average_cost=30)
    holdings.record(gateway_conn, avery, symbol="SYN6", quantity=75)

    report = holdings.concentration(gateway_conn, avery)

    assert report["positions"] == 2
    assert [w["symbol"] for w in report["weights"]] == ["SYN1"]
    assert report["missing_average_cost"] == ["SYN6"]
    assert "counted as positions" in report["missing_cost_note"]


def test_an_empty_portfolio_says_so(gateway_conn):
    nobody = _pf(gateway_conn, "nobody")
    report = holdings.concentration(gateway_conn, nobody)
    assert report["positions"] == 0
    assert report["note"]


# --- the demo data, and being able to remove it -------------------------------------


def _pre_alpha(monkeypatch, tmp_path):
    import json

    from backend import boot_config

    config = tmp_path / "boot-dev.json"
    config.write_text(json.dumps({
        "lifecycle_stage": "PRE_ALPHA",
        "global_asset_classes": ["stock", "stock_option"],
        "implemented_asset_classes": ["stock", "stock_option"],
        "current_focus": ["REFERENCE_DATA"],
        "simulation_focus": ["OPTIONS_ON_EQUITIES_PRICING"],
    }), encoding="utf-8")
    monkeypatch.setenv(boot_config.PATH_ENV, str(config))


def _production(monkeypatch, tmp_path):
    import json

    from backend import boot_config

    config = tmp_path / "boot-prod.json"
    config.write_text(json.dumps({
        "lifecycle_stage": "PRODUCTION",
        "global_asset_classes": ["stock", "stock_option"],
        "implemented_asset_classes": ["stock", "stock_option"],
        "current_focus": ["REFERENCE_DATA"],
        "simulation_focus": ["OPTIONS_ON_EQUITIES_PRICING"],
    }), encoding="utf-8")
    monkeypatch.setenv(boot_config.PATH_ENV, str(config))


def test_demo_clients_are_refused_in_production(gateway_conn, monkeypatch, tmp_path):
    """Inventing customers in production is not a development convenience."""
    _production(monkeypatch, tmp_path)
    with pytest.raises(demo_clients.SeedRefused, match="PRODUCTION"):
        demo_clients.seed(gateway_conn)
    assert portfolios.simulated_client_ids(gateway_conn) == []


def test_demo_clients_are_refused_when_the_stage_cannot_be_read(gateway_conn, monkeypatch,
                                                                tmp_path):
    """Fail closed: "I could not tell what stage this is" must not resolve to
    "go ahead and invent some customers"."""
    from backend import boot_config

    monkeypatch.setenv(boot_config.PATH_ENV, str(tmp_path / "missing.json"))
    with pytest.raises(demo_clients.SeedRefused):
        demo_clients.seed(gateway_conn)


def test_seeding_creates_clients_with_agents_and_holdings(gateway_conn, monkeypatch, tmp_path):
    _pre_alpha(monkeypatch, tmp_path)
    outcome = demo_clients.seed(gateway_conn)

    assert set(outcome["clients"]) == set(demo_clients.DEMO_CLIENTS)
    for client_id, positions in demo_clients.DEMO_CLIENTS.items():
        portfolio = _pf(gateway_conn, client_id)
        assert len(holdings.listing(gateway_conn, portfolio)) == len(positions)
        assert client_agent.load(gateway_conn, client_id) is not None
        # Seeded through the ordinary path, so each demo client owns their
        # positions the same way a real one does (TQ-44).
        assert portfolio["owner_id"] == client_id
        assert portfolio["simulated"] is True


def test_every_demo_row_is_flagged_simulated(gateway_conn, monkeypatch, tmp_path):
    """The instruction was to use this now and remove it before live. Demo data
    that is merely *intended* to be removed is demo data that ships, because by
    the time anybody looks nobody is certain which rows it was."""
    _pre_alpha(monkeypatch, tmp_path)
    demo_clients.seed(gateway_conn)

    unflagged = gateway_conn.fetchall("SELECT symbol FROM portfolio_holdings WHERE simulated = 0")
    assert unflagged == []
    assert set(portfolios.simulated_client_ids(gateway_conn)) == set(demo_clients.DEMO_CLIENTS)


def test_clearing_removes_every_simulated_row_and_nothing_else(gateway_conn, monkeypatch,
                                                               tmp_path):
    _pre_alpha(monkeypatch, tmp_path)
    demo_clients.seed(gateway_conn)
    # A real client, recorded the ordinary way.
    real_person = _pf(gateway_conn, "real-person")
    holdings.record(gateway_conn, real_person, symbol="SYN1", quantity=10, average_cost=5)
    client_agent.ensure(gateway_conn, "real-person")

    demo_clients.clear(gateway_conn)

    assert portfolios.simulated_client_ids(gateway_conn) == []
    assert len(holdings.listing(gateway_conn, real_person)) == 1
    assert client_agent.load(gateway_conn, "real-person") is not None


def test_outstanding_is_how_you_know_rather_than_hope(gateway_conn, monkeypatch, tmp_path):
    """The difference between intending to clean up and being able to check."""
    assert demo_clients.outstanding(gateway_conn)["clean"] is True

    _pre_alpha(monkeypatch, tmp_path)
    demo_clients.seed(gateway_conn)
    dirty = demo_clients.outstanding(gateway_conn)
    assert dirty["clean"] is False
    assert "before going live" in dirty["note"]

    demo_clients.clear(gateway_conn)
    assert demo_clients.outstanding(gateway_conn)["clean"] is True


def test_the_demo_portfolios_hold_synthetic_symbols_only(gateway_conn):
    """A demo portfolio of real companies is one screenshot away from being read
    as advice about them."""
    for positions in demo_clients.DEMO_CLIENTS.values():
        for position in positions:
            assert position["symbol"].startswith("SYN"), (
                f"{position['symbol']} is not one of this system's synthetic symbols")


def test_the_demo_data_exercises_the_awkward_paths(gateway_conn, monkeypatch, tmp_path):
    """Demo data that only shows the happy case is a screenshot, not a
    demonstration: one client is concentrated and one is missing a cost basis,
    so the report has something true and uncomfortable to say."""
    avery = _pf(gateway_conn, "avery")
    morgan = _pf(gateway_conn, "morgan")
    _pre_alpha(monkeypatch, tmp_path)
    demo_clients.seed(gateway_conn)

    concentrated = holdings.concentration(gateway_conn, avery)
    assert concentrated["top_three_pct"] > 90

    incomplete = holdings.concentration(gateway_conn, morgan)
    assert incomplete["missing_average_cost"]


def test_clearing_removes_holdings_a_demo_client_stated_in_conversation(gateway_conn,
                                                                        monkeypatch, tmp_path):
    """Found by looking at the database after a real demo conversation.

    Talking to a demo client's agent records holdings through the ordinary tool,
    which does not flag them simulated - correctly, because the client did state
    them. Clearing only flagged rows left those behind: an orphaned position
    belonging to a customer who no longer existed. Anything owned by a demo
    client is demo data, whatever route it arrived by."""
    _pre_alpha(monkeypatch, tmp_path)
    demo_clients.seed(gateway_conn)
    customer = _pf(gateway_conn, "customer")

    # Exactly what the live session did: a holding stated in conversation.
    stated = holdings.record(gateway_conn, customer, symbol="SYN5", quantity=80,
                             average_cost=179.40)
    assert stated["simulated"] is False, "a stated holding is not demo data by flag"

    demo_clients.clear(gateway_conn)

    assert holdings.listing(gateway_conn, customer) == []
    assert demo_clients.outstanding(gateway_conn)["clean"] is True
