"""What a holding is, the arithmetic over a set of them, and the providers that
now fetch rather than store (TQ-42/44/45; **reshaped by TQ-72, §111**).

This file used to be mostly isolation tests — one client's positions must not
reach another's — over a `portfolio_holdings` table. There is no table, so those
tests are not here. **The property did not go anywhere**: it moved to
`tests/test_tools_portfolio.py` and `tests/test_multi_user_isolation.py`, where a
source path is derived from the authenticated username and cannot be named by an
argument. Isolation is now a property of where a fetch looks rather than of which
rows a query returns.

What is here is what survived TQ-72 unchanged, and the reason it survived is the
one thing worth reading twice: §101 built `concentration` to take **holdings, not
a connection**, so that a contract test could not pass trivially. That decision
was made to keep a test honest, and it is why the analysis needed no edit at all
when the store was removed.
"""

import pytest

from backend import holdings, portfolio_providers, portfolios


def _source(name="fixture", provider_type=None, positions=(), **kwargs):
    return portfolio_providers.Source(
        provider_type=provider_type or portfolios.PROVIDER_MANUAL,
        name=name, positions=tuple(positions), **kwargs)


def _held(**overrides):
    row = {"symbol": "SYN1", "quantity": 10, "average_cost": 5.0,
           "asset_class": "stock", "as_of": "2026-01-01T00:00:00+00:00"}
    row.update(overrides)
    return row


# --- what a holding is, checked on the way in from a source ------------------------
#
# These checks used to run on the way into the table. They run on the way in from
# a fetch now, which is the same boundary one step earlier - and a more important
# one, because a source is somebody else's system rather than our own writer.


def test_a_symbol_is_normalised_rather_than_stored_as_typed():
    holding = portfolio_providers.Holding.from_row(_held(symbol=" syn1 "))
    assert holding.symbol == "SYN1"


def test_a_blank_symbol_is_refused():
    with pytest.raises(holdings.HoldingRefused):
        portfolio_providers.Holding.from_row(_held(symbol="   "))


def test_an_unknown_symbol_is_accepted():
    """A client may hold something this system has never heard of. Refusing it
    would be refusing a fact about their money because our reference data is
    incomplete."""
    holding = portfolio_providers.Holding.from_row(_held(symbol="NEVERHEARDOFIT"))
    assert holding.symbol == "NEVERHEARDOFIT"


@pytest.mark.parametrize("bad", [None, "", "lots", "  "])
def test_an_unusable_quantity_is_refused_rather_than_coerced(bad):
    """Silently treating an unparseable number as zero shares is worse than
    saying the number would not parse."""
    with pytest.raises(holdings.HoldingRefused):
        portfolio_providers.Holding.from_row(_held(quantity=bad))


def test_a_quantity_of_zero_is_not_a_position():
    with pytest.raises(holdings.HoldingRefused):
        portfolio_providers.Holding.from_row(_held(quantity=0))


def test_a_negative_quantity_is_a_short_position():
    """Found while building the fixtures (§101): addendum 44 §6.1 asks for a
    covered call, and a covered call is a *written* option - short four
    contracts, not long four."""
    holding = portfolio_providers.Holding.from_row(_held(quantity=-4, average_cost=1.85))
    assert holding.quantity == -4


def test_a_cost_basis_is_optional_because_people_do_not_always_know_it():
    holding = portfolio_providers.Holding.from_row(_held(average_cost=None))
    assert holding.average_cost is None


def test_the_asset_class_vocabulary_is_the_house_one():
    """Imported rather than mirrored (§70, §100). Two naming schemes for one fact
    is what the Conflict Rule forbids, and a copied list would recreate it one
    scale smaller with nothing to notice the drift."""
    from backend.reference_data import ASSET_CLASSES as house

    assert set(holdings.ASSET_CLASSES) == {code for code, _ in house} | {"unknown"}


def test_an_unrecognised_asset_class_is_refused():
    with pytest.raises(holdings.HoldingRefused):
        portfolio_providers.Holding.from_row(_held(asset_class="equity"))


def test_an_absent_asset_class_is_unknown_rather_than_guessed():
    holding = portfolio_providers.Holding.from_row(_held(asset_class=None))
    assert holding.asset_class == holdings.ASSET_UNKNOWN


def test_a_holding_carries_no_account_field():
    """§9.1's stronger form: a field that does not exist cannot be leaked by a
    future reader who forgets to sanitize."""
    holding = portfolio_providers.Holding.from_row(_held())
    assert not any("account" in field for field in vars(holding))


def test_a_holding_carries_no_price():
    """Positions come from a broker and prices from the market data store
    (§113). A source asserting a value would be a source deciding what somebody's
    money is worth."""
    holding = portfolio_providers.Holding.from_row(_held())
    assert not any(field in vars(holding) for field in ("market_price", "market_value"))


# --- arithmetic, computed rather than narrated -------------------------------------


def _holdings(*rows):
    return [portfolio_providers.Holding.from_row(_held(**row)) for row in rows]


def test_weights_are_computed_from_stated_cost():
    report = holdings.concentration(_holdings(
        {"symbol": "SYN1", "quantity": 100, "average_cost": 10},
        {"symbol": "SYN2", "quantity": 100, "average_cost": 30}))

    assert report["known_cost"] == 4000
    assert report["weights"][0] == {"symbol": "SYN2", "cost": 3000.0, "weight_pct": 75.0}


def test_concentration_reports_the_top_three():
    report = holdings.concentration(_holdings(
        *({"symbol": f"SYN{n}", "quantity": 1, "average_cost": 100 - n} for n in range(1, 6))))
    assert report["top_three_pct"] > 60


def test_nothing_is_ever_valued():
    """`concentration` is by cost whatever its input, so there is no source that
    would make it priced. That hard `False` is not a second copy of a pricing
    rule - it is a statement about this report."""
    report = holdings.concentration(_holdings({"symbol": "SYN1", "quantity": 1,
                                               "average_cost": 10}))
    assert report["priced"] is False
    assert "market" in report["priced_note"].lower()


def test_the_absence_of_a_price_is_stated_rather_than_left_to_be_noticed():
    """A report that simply omitted market value would read as a portfolio worth
    its cost basis."""
    report = holdings.concentration(_holdings({"symbol": "SYN1", "quantity": 1,
                                               "average_cost": 10}))
    assert "not by what the positions are worth now" in report["priced_note"]


def test_a_holding_without_a_cost_basis_is_counted_but_not_weighted():
    report = holdings.concentration(_holdings(
        {"symbol": "SYN1", "quantity": 100, "average_cost": 10},
        {"symbol": "SYN6", "quantity": 75, "average_cost": None}))

    assert report["positions"] == 2
    assert [w["symbol"] for w in report["weights"]] == ["SYN1"]
    assert report["missing_average_cost"] == ["SYN6"]
    assert "left out of the weights" in report["missing_cost_note"]


def test_a_short_position_is_counted_but_not_weighted():
    """A short's `average_cost` is a credit received, not an amount paid, so
    folding it into cost weights gives a percentage of a total that no longer
    means anything."""
    report = holdings.concentration(_holdings(
        {"symbol": "SYN1", "quantity": 400, "average_cost": 42.50},
        {"symbol": "SYN1C50", "quantity": -4, "average_cost": 1.85,
         "asset_class": "stock_option"}))

    assert report["positions"] == 2
    assert [w["symbol"] for w in report["weights"]] == ["SYN1"]
    assert report["short_positions"][0]["symbol"] == "SYN1C50"
    assert "counted but not weighted" in report["short_note"]


def test_an_empty_portfolio_says_so():
    report = holdings.concentration([])
    assert report["positions"] == 0
    assert report["known_cost"] is None
    assert "no positions" in report["note"].lower()


def test_the_analyser_does_not_know_where_its_input_came_from():
    """§101's design decision, asserted as the property it was made for - and the
    reason this module survived TQ-72 without an edit.

    Two providers, two sources, one analyser. If `concentration` had read a table
    it would have agreed with every provider trivially; comparing their output is
    only a test because it cannot."""
    fixture = portfolio_providers.SIMULATED_PORTFOLIOS["morgan"]["positions"]
    simulated = _source("morgan", portfolios.PROVIDER_SIMULATED, owner_hint="morgan")
    manual = _source("a-file", positions=[
        {**row, "as_of": "2026-01-01T00:00:00+00:00"} for row in fixture])

    from_simulated = holdings.concentration(
        portfolio_providers.for_source(simulated).get_holdings(simulated))
    from_manual = holdings.concentration(
        portfolio_providers.for_source(manual).get_holdings(manual))

    assert from_simulated["weights"] == from_manual["weights"]
    assert from_simulated["known_cost"] == from_manual["known_cost"]


# --- providers fetch, and never persist --------------------------------------------


def test_a_provider_is_chosen_from_a_source_not_from_a_name():
    with pytest.raises(TypeError):
        portfolio_providers.for_source("simulated")


def test_an_unbuilt_provider_refuses_rather_than_falling_back():
    """A Schwab source in this build is one nothing can fetch. Serving it from
    another provider would show somebody the wrong account."""
    source = _source("brokerage", portfolios.PROVIDER_SCHWAB)
    with pytest.raises(portfolio_providers.ProviderRefused):
        portfolio_providers.for_source(source)


def test_a_provider_refuses_a_source_it_does_not_serve():
    simulated = portfolio_providers.SimulatedPortfolioProvider()
    with pytest.raises(portfolio_providers.ProviderRefused):
        simulated.get_holdings(_source("a-file"))


def test_the_manual_provider_returns_what_the_source_carried():
    source = _source("a-file", positions=[_held(symbol="AAPL", quantity=25,
                                                average_cost=172.34)])
    provider = portfolio_providers.for_source(source)
    assert [h.symbol for h in provider.get_holdings(source)] == ["AAPL"]


def test_the_manual_provider_says_why_it_cannot_answer():
    """A refusal with a reason, in words a caller can repeat. `{}` would read as
    "no cash" and `0` would be a fabrication."""
    source = _source("a-file")
    provider = portfolio_providers.for_source(source)

    for capability in ("get_balances", "refresh"):
        with pytest.raises(portfolio_providers.ProviderCapabilityUnavailable) as refusal:
            getattr(provider, capability)(source)
        assert len(str(refusal.value)) > 40, "a refusal without a reason is a blank field"


def test_the_two_providers_differ_in_what_they_can_answer():
    """§101 spec §11 Q5: two providers that genuinely differ is what makes
    `supports()` a contract rather than a decoration."""
    manual = portfolio_providers.ManualPortfolioProvider()
    simulated = portfolio_providers.SimulatedPortfolioProvider()

    assert manual.supports(portfolio_providers.CAP_BALANCES) is False
    assert simulated.supports(portfolio_providers.CAP_BALANCES) is True


def test_the_simulated_provider_returns_rather_than_seeding(portfolio_conn_free=None):
    """The old version wrote its fixtures into `portfolio_holdings` and read them
    back. A simulated *exchange* answers a query; it does not fill somebody's
    database first (§115)."""
    assert not hasattr(portfolio_providers.SimulatedPortfolioProvider, "seed")

    source = _source("avery", portfolios.PROVIDER_SIMULATED, owner_hint="avery")
    provider = portfolio_providers.for_source(source)
    held = provider.get_holdings(source)

    assert [h.symbol for h in held] == ["SYN2", "SYN5", "SYN2C350", "SYN2P300"]
    assert all(h.simulated for h in held)


def test_the_simulated_provider_answers_the_same_question_the_same_way():
    """An exercise that gave different answers on two runs would not be
    reproducible, and §115's simulated exchange has to be able to answer twice."""
    source = _source("someone-new", portfolios.PROVIDER_SIMULATED,
                     owner_hint="someone-new")
    provider = portfolio_providers.for_source(source)

    first = provider.get_holdings(source)
    second = provider.get_holdings(source)

    assert [vars(h) for h in first] == [vars(h) for h in second]


def test_a_simulated_balance_is_labelled_and_unpriced():
    source = _source("morgan", portfolios.PROVIDER_SIMULATED, owner_hint="morgan")
    balances = portfolio_providers.for_source(source).get_balances(source)

    assert balances["simulated"] is True
    assert balances["priced"] is False
    assert "not a real account" in balances["note"]


def test_the_fixtures_hold_synthetic_symbols_only():
    """A fixture portfolio of real companies is one screenshot away from being
    read as advice about them."""
    for fixture in portfolio_providers.SIMULATED_PORTFOLIOS.values():
        for position in fixture["positions"]:
            assert position["symbol"].startswith("SYN")


def test_the_fixtures_exercise_the_awkward_paths():
    """Fixture data that only shows the happy case is a screenshot, not a
    demonstration: one is concentrated and one is missing a cost basis, so the
    report has something true and uncomfortable to say."""
    def report_for(name):
        source = _source(name, portfolios.PROVIDER_SIMULATED, owner_hint=name)
        return holdings.concentration(
            portfolio_providers.for_source(source).get_holdings(source))

    assert report_for("avery")["top_three_pct"] > 90
    assert report_for("morgan")["missing_average_cost"]


def test_no_provider_method_writes_anything(tmp_path):
    """§111 as a property of the filesystem. A provider that cached its answer
    would pass every other test in this file."""
    before = {p for p in tmp_path.rglob("*")}
    for name in ("customer", "avery", "morgan"):
        source = _source(name, portfolios.PROVIDER_SIMULATED, owner_hint=name)
        provider = portfolio_providers.for_source(source)
        provider.get_holdings(source)
        provider.get_balances(source)
        provider.refresh(source)
    assert {p for p in tmp_path.rglob("*")} == before
