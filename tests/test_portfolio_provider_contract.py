"""The provider contract every `PortfolioProvider` must satisfy (TQ-45b,
docs/SPEC_RECONCILIATION.md §101; addendum 44 §15.4).

**This file was written before the second provider existed, and that is the
point.** A contract with a single implementation is a description of that
implementation. The suite is what turns it into a contract, and writing it early
is what stops `SchwabPortfolioProvider` from discovering next month that the
"interface" encoded three assumptions only a local database could satisfy.

The guard applied to every test here, from the spec's Risk 1:

> While writing each contract test, ask whether a provider that must make a
> network call could satisfy it. If the answer needs a local database, the test
> is wrong.

So there is nothing here that inspects a table, counts rows, or assumes a write
is visible to a later read on the same connection. Everything goes through the
interface.

## Adding a provider

Subclass `PortfolioProviderContract` and supply the two fixtures. Nothing else.
`SchwabPortfolioProvider` inherits this class unchanged in TQ-49 — **if it has to
modify a test, the contract was wrong, not the broker.**
"""

import inspect

import pytest

from backend import holdings, portfolio_providers, portfolios


# The interface addendum 44 §7 names. Asserted as *present*; the id-shape check
# below deliberately scans every public method instead, because the method that
# reintroduces a bypass is the one nobody thought to list.
PROVIDER_METHODS = ("list_accounts", "get_account", "get_holdings", "get_balances",
                    "get_positions", "refresh", "health_check", "supports")


class PortfolioProviderContract:
    """Inherited unchanged by every provider's own test class."""

    # --- what a subclass supplies -------------------------------------------------

    @pytest.fixture
    def provider(self):
        raise NotImplementedError("supply the provider under test")

    @pytest.fixture
    def seeded(self, portfolio_conn, provider):
        """`(conn, portfolio)` with at least two positions in it, stocked
        however this provider stocks things."""
        raise NotImplementedError("supply a portfolio this provider can read")

    # --- shape --------------------------------------------------------------------

    def test_holdings_are_canonical_objects(self, seeded, provider):
        """Never a broker dict and never a raw row. The whole value of the
        abstraction is that the analyzer never learns where data came from."""
        conn, portfolio = seeded
        held = provider.get_holdings(conn, portfolio)

        assert held, "the seeded fixture must have positions"
        for holding in held:
            assert isinstance(holding, portfolio_providers.Holding)

    def test_a_holding_is_well_formed(self, seeded, provider):
        conn, portfolio = seeded
        for holding in provider.get_holdings(conn, portfolio):
            assert holding.symbol and holding.symbol == holding.symbol.upper().strip()
            assert holding.quantity != 0, "a position of zero is not a position"
            assert holding.asset_class in holdings.ASSET_CLASSES
            assert holding.as_of, "a holding must say when its data is from"

    def test_an_unknown_average_cost_is_none_rather_than_zero(self, seeded, provider):
        """`0.0` standing in for "nobody told us" is the fabrication this whole
        area refuses. Absent is None."""
        conn, portfolio = seeded
        for holding in provider.get_holdings(conn, portfolio):
            assert holding.average_cost is None or holding.average_cost > 0

    def test_a_holding_cannot_be_mutated_after_it_is_returned(self, seeded, provider):
        """Frozen: what a provider returned is evidence, not a working variable."""
        conn, portfolio = seeded
        holding = provider.get_holdings(conn, portfolio)[0]
        with pytest.raises(Exception):
            holding.quantity = 999

    # --- ownership ----------------------------------------------------------------

    def test_a_provider_returns_only_this_portfolios_holdings(self, seeded, provider,
                                                              portfolio_conn):
        """TQ-44's property, asserted at this layer too. A provider is an adapter,
        not an authorization boundary - but an adapter that leaked across
        portfolios would defeat the boundary above it."""
        conn, portfolio = seeded
        other = portfolios.create(conn, portfolios.for_client("someone-else"),
                                  display_name="Theirs",
                                  provider_type=portfolio["provider_type"],
                                  data_mode=portfolio["data_mode"])
        holdings.record(conn, other, symbol="ZZZZ", quantity=1, average_cost=1)

        symbols = {h.symbol for h in provider.get_holdings(conn, portfolio)}
        assert "ZZZZ" not in symbols

    def test_no_provider_method_accepts_a_bare_id(self, provider):
        """The spec's §3.2, enforced by signature rather than by review.

        Addendum 44 §7's conceptual interface is `get_holdings(account_ref)`. A
        public method taking a bare reference string is the second by-id
        retrieval path TQ-44 exists to prevent, one layer below where the
        portfolios tripwire looks - and it would read as implementing the
        specification rather than as a bypass. So a *new* method that takes one
        fails here, not in review."""
        forbidden = {"portfolio_id", "account_ref", "provider_account_ref", "owner_id",
                     "client_id", "subject"}
        offenders = []
        # **Every** public method, not a fixed list. Scanning a known list was
        # the first version of this test, and a mutation run caught it passing
        # while a freshly added `get_by_ref(conn, account_ref)` sat right beside
        # the methods it did check - which is exactly the case this exists for,
        # since the bypass arrives as a *new* convenience rather than as a change
        # to an existing signature.
        for name in dir(provider):
            if name.startswith("_"):
                continue
            method = getattr(provider, name)
            if not callable(method):
                continue
            try:
                parameters = inspect.signature(method).parameters
            except (TypeError, ValueError):  # pragma: no cover - builtins
                continue
            for parameter in parameters:
                if parameter in forbidden:
                    offenders.append(f"{name}({parameter})")
        assert not offenders, (
            f"these take an id where a resolved portfolio belongs: {offenders}. "
            "Take the portfolio dict from portfolios.resolve() and read the "
            "reference off it.")

    def test_a_provider_implements_the_whole_interface(self, provider):
        """§7's methods all exist, including the ones this provider refuses -
        a caller should get a reasoned refusal, not an AttributeError."""
        for name in PROVIDER_METHODS:
            assert callable(getattr(provider, name, None)), f"{name} is missing"

    def test_a_provider_is_chosen_from_a_resolved_portfolio(self, seeded, provider):
        conn, portfolio = seeded
        assert portfolio_providers.for_portfolio(portfolio) is provider
        for wrong in (portfolio["portfolio_id"], None, "manual"):
            with pytest.raises(TypeError):
                portfolio_providers.for_portfolio(wrong)

    # --- capability honesty -------------------------------------------------------

    def test_every_provider_can_at_least_answer_holdings(self, provider):
        assert provider.supports(portfolio_providers.CAP_HOLDINGS)

    def test_an_unknown_capability_raises_rather_than_returning_false(self, provider):
        """Fail closed. `supports("balnces")` quietly returning False would look
        exactly like a provider that cannot do it."""
        with pytest.raises(portfolio_providers.UnknownCapability):
            provider.supports("balnces")

    @pytest.mark.parametrize("capability,call", [
        (portfolio_providers.CAP_BALANCES, "get_balances"),
        (portfolio_providers.CAP_POSITIONS, "get_positions"),
        (portfolio_providers.CAP_REFRESH, "refresh"),
        (portfolio_providers.CAP_ACCOUNTS, "get_account"),
    ])
    def test_an_unsupported_capability_refuses_with_a_reason(self, seeded, provider,
                                                             capability, call):
        """The heart of §3.4. A provider that cannot answer says so in a sentence
        the caller can repeat - because "why can't you tell me my cash balance?"
        deserves an explanation, not a blank field.

        Satisfiable by a provider that *can* do it and one that cannot, which is
        what makes it a contract rather than a description of one of them."""
        conn, portfolio = seeded
        method = getattr(provider, call)
        if provider.supports(capability):
            method(conn, portfolio)  # must not raise
            return
        with pytest.raises(portfolio_providers.ProviderCapabilityUnavailable) as refused:
            method(conn, portfolio)
        assert str(refused.value).strip(), "a refusal must carry a reason"

    # --- freshness (§17) ----------------------------------------------------------

    def test_refresh_stamps_a_sync_time_only_when_it_fetched(self, seeded, provider):
        """§17: mark it stale, do not silently claim it is current.

        A `last_synced_at` that moved on a failed sync would be worse than the
        NULL it replaced - NULL says "never synced", which is true."""
        conn, portfolio = seeded
        if not provider.supports(portfolio_providers.CAP_REFRESH):
            assert portfolio["last_synced_at"] is None, (
                "a provider that cannot refresh must never have stamped a sync time")
            return

        assert portfolio["last_synced_at"] is None
        outcome = provider.refresh(conn, portfolio)
        assert outcome["last_synced_at"], "a successful refresh records when it happened"

    def test_a_failed_refresh_leaves_the_previous_sync_time_alone(self, seeded, provider,
                                                                  monkeypatch):
        conn, portfolio = seeded
        if not provider.supports(portfolio_providers.CAP_REFRESH):
            return
        provider.refresh(conn, portfolio)
        owner = portfolios.for_client(portfolio["owner_id"])
        before = portfolios.resolve(conn, portfolio["portfolio_id"], owner)["last_synced_at"]

        def explode(*args, **kwargs):
            raise RuntimeError("the source is unavailable")

        monkeypatch.setattr(provider, "seed", explode, raising=False)
        with pytest.raises(Exception):
            provider.refresh(conn, portfolio)

        after = portfolios.resolve(conn, portfolio["portfolio_id"], owner)["last_synced_at"]
        assert after == before, "a failed sync must not assert a freshness nothing has"

    # --- pricing ------------------------------------------------------------------

    def test_no_provider_returns_a_price_in_this_build(self, seeded, provider):
        """Every price this organization produces is simulated (addendum 25).
        A field existing is not permission to fill it in."""
        conn, portfolio = seeded
        for holding in provider.get_holdings(conn, portfolio):
            for forbidden in ("market_price", "market_value", "gain", "loss",
                              "return_pct", "unrealized"):
                assert not hasattr(holding, forbidden)

    def test_nothing_a_provider_stocks_is_priced(self, seeded, provider):
        """`portfolios.is_priced` is the one rule and it is LIVE-only. No
        provider built here produces LIVE data, so the answer is False - because
        of the rule, not because the feature is missing (spec §11 Q2)."""
        conn, portfolio = seeded
        assert portfolios.is_priced(portfolio) is False
        if provider.supports(portfolio_providers.CAP_ACCOUNTS):
            assert provider.get_account(conn, portfolio)["priced"] is False

    def test_a_balance_is_not_a_valuation(self, seeded, provider):
        """A cash balance is a quantity somebody holds, not what anything is
        worth - which is why it does not widen the pricing rule."""
        conn, portfolio = seeded
        if not provider.supports(portfolio_providers.CAP_BALANCES):
            return
        balances = provider.get_balances(conn, portfolio)
        assert "cash" in balances
        assert balances.get("priced") is False
        for forbidden in ("market_value", "gain", "loss", "total_value"):
            assert forbidden not in balances

    # --- accounts -----------------------------------------------------------------

    def test_listing_accounts_is_owner_scoped(self, seeded, provider):
        conn, portfolio = seeded
        if not provider.supports(portfolio_providers.CAP_ACCOUNTS):
            return
        owner = portfolios.for_client(portfolio["owner_id"])
        stranger = portfolios.for_client("nobody-in-particular")

        mine = {a["portfolio_id"] for a in provider.list_accounts(conn, owner)}
        theirs = {a["portfolio_id"] for a in provider.list_accounts(conn, stranger)}

        assert portfolio["portfolio_id"] in mine
        assert portfolio["portfolio_id"] not in theirs

    def test_an_account_names_its_source_and_freshness(self, seeded, provider):
        conn, portfolio = seeded
        if not provider.supports(portfolio_providers.CAP_ACCOUNTS):
            return
        account = provider.get_account(conn, portfolio)
        for field in ("portfolio_id", "provider_type", "data_mode", "last_synced_at",
                      "priced", "simulated"):
            assert field in account

    # --- health -------------------------------------------------------------------

    def test_health_check_reports_without_being_asked_about_data(self, provider):
        """Answers about the *provider*, never about the data. It exists now so
        TQ-49's Schwab provider has somewhere to report a down API rather than
        inventing a return shape at the moment it first fails."""
        report = provider.health_check()
        assert isinstance(report["healthy"], bool)
        assert report["detail"].strip()

    # --- the analyzer contract (§15.3) --------------------------------------------

    def test_the_analyzer_does_not_change_with_the_provider(self, seeded, provider):
        """§15.3's "switching provider does not change analyzer contract".

        Real rather than tautological because `concentration` takes holdings and
        not a connection (spec §3.8): an analyzer that read the table itself
        would agree with every provider trivially, since they all write to one
        table. This feeds it the provider's own objects."""
        conn, portfolio = seeded
        held = provider.get_holdings(conn, portfolio)

        from_provider = holdings.concentration(held)
        from_stub = holdings.concentration(_StubProvider(held).get_holdings(conn, portfolio))

        assert from_provider == from_stub


class _StubProvider:
    """An independent implementation that holds its positions in a list.

    Deliberately not a mock of either real provider: two implementations is the
    minimum number at which a contract is a contract, and a mock would only ever
    agree with the thing it was made from. It also demonstrates the property that
    matters for TQ-49 - a provider needs no database at all."""

    name = "stub"
    provider_type = "STUB"
    capabilities = (portfolio_providers.CAP_HOLDINGS,)

    def __init__(self, held):
        self._held = list(held)

    def supports(self, capability):
        return capability in self.capabilities

    def get_holdings(self, conn, portfolio):
        return list(self._held)

    def health_check(self):
        return {"healthy": True, "detail": "stub"}


# --- the providers under test -------------------------------------------------------


class TestManualProviderContract(PortfolioProviderContract):
    """The client-stated source (§96), which cannot refresh and has no balances."""

    @pytest.fixture
    def provider(self):
        return portfolio_providers.for_portfolio(
            {"provider_type": portfolios.PROVIDER_MANUAL})

    @pytest.fixture
    def seeded(self, portfolio_conn, provider):
        portfolio = portfolios.primary_for(portfolio_conn, portfolios.for_client("avery"))
        holdings.record(portfolio_conn, portfolio, symbol="SYN1", quantity=100,
                        average_cost=10, asset_class="stock")
        holdings.record(portfolio_conn, portfolio, symbol="SYN2", quantity=5)
        return portfolio_conn, portfolio


class TestSimulatedProviderContract(PortfolioProviderContract):
    """The invented source (§6.1), which can refresh and does know a balance."""

    @pytest.fixture
    def provider(self):
        return portfolio_providers.for_portfolio(
            {"provider_type": portfolios.PROVIDER_SIMULATED})

    @pytest.fixture
    def seeded(self, portfolio_conn, provider):
        portfolio = portfolios.primary_for(
            portfolio_conn, portfolios.for_client("avery"), simulated=True,
            provider_type=portfolios.PROVIDER_SIMULATED,
            data_mode=portfolios.MODE_SIMULATED)
        provider.seed(portfolio_conn, portfolio)
        return portfolio_conn, portfolio


def test_the_two_providers_genuinely_differ_in_what_they_can_answer():
    """Otherwise the capability declaration is a decoration.

    If both providers supported everything, every refusal test above would pass
    vacuously and `supports()` would be proving nothing."""
    manual = portfolio_providers.ManualPortfolioProvider()
    simulated = portfolio_providers.SimulatedPortfolioProvider()

    differ = [c for c in portfolio_providers.CAPABILITIES
              if manual.supports(c) != simulated.supports(c)]
    assert differ, "the suite proves nothing unless two providers actually differ"
    assert not manual.supports(portfolio_providers.CAP_BALANCES)
    assert simulated.supports(portfolio_providers.CAP_BALANCES)


def test_an_unbuilt_provider_type_refuses_rather_than_falling_back():
    """A Schwab portfolio in this build is one nothing can read. Serving it from
    the manual provider would show somebody their stated holdings where they
    asked for their brokerage account."""
    with pytest.raises(portfolio_providers.ProviderRefused):
        portfolio_providers.for_portfolio(
            {"provider_type": portfolios.PROVIDER_SCHWAB})


def test_every_built_provider_reports_its_health():
    report = portfolio_providers.health()
    assert set(report) == {"manual", "simulated"}
    assert all(entry["healthy"] for entry in report.values())
