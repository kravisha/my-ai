"""The contract every `PortfolioProvider` must satisfy (TQ-45b §101, addendum 44
§15.4; **reshaped for fetchers by TQ-72, §111**).

**This file was written before the second provider existed, and that is the
point.** A contract with a single implementation is a description of that
implementation. The suite is what turns it into a contract.

It has now survived the thing it was insurance against, which is worth recording
because insurance is usually bought and never claimed. §101's Risk 1 set the
guard applied to every test here:

> While writing each contract test, ask whether a provider that must make a
> network call could satisfy it. If the answer needs a local database, the test
> is wrong.

TQ-72 removed the local database entirely. The tests that had to go are exactly
the ones that guard would have caught if it had been applied more strictly — the
ones about `last_synced_at` being stamped on a stored row, and about
`list_accounts` reading an owner's rows. Everything written to the guard survived
untouched.

## Adding a provider

Subclass `PortfolioProviderContract` and supply the two fixtures. Nothing else.
`SchwabPortfolioProvider` inherits this class unchanged in TQ-49 — **if it has to
modify a test, the contract was wrong, not the broker.**
"""

import inspect

import pytest

from backend import consolidation, holdings, portfolio_providers, portfolios

# The interface a provider offers. Asserted as *present*; the shape check below
# deliberately scans every public method instead, because the method that
# reintroduces a bypass is the one nobody thought to list.
PROVIDER_METHODS = ("get_account", "get_holdings", "get_balances", "get_positions",
                    "refresh", "health_check", "supports")


class PortfolioProviderContract:
    """Inherited unchanged by every provider's own test class."""

    # --- what a subclass supplies -------------------------------------------------

    @pytest.fixture
    def provider(self):
        raise NotImplementedError("supply the provider under test")

    @pytest.fixture
    def source(self):
        """A `Source` this provider can serve, with at least two positions
        behind it."""
        raise NotImplementedError("supply a source this provider can fetch from")

    # --- shape ---------------------------------------------------------------------

    def test_a_provider_implements_the_whole_interface(self, provider):
        for method in PROVIDER_METHODS:
            assert callable(getattr(provider, method, None)), (
                f"{provider.name} is missing {method}")

    def test_holdings_are_canonical_objects(self, provider, source):
        """Never a broker dict and never a raw row. The whole value of the
        abstraction is that the analyser never learns where data came from."""
        held = provider.get_holdings(source)
        assert held, "the fixture source should carry positions"
        assert all(isinstance(h, portfolio_providers.Holding) for h in held)

    def test_a_holding_is_well_formed(self, provider, source):
        for held in provider.get_holdings(source):
            assert held.symbol and held.symbol == held.symbol.upper()
            assert held.quantity != 0, "a position of zero is not a position"
            assert held.asset_class in holdings.ASSET_CLASSES

    def test_a_holding_cannot_be_mutated_after_it_is_returned(self, provider, source):
        """Frozen because it is what a source returned, not a working variable.
        A caller that could edit one could edit somebody's position between the
        fetch and the analysis."""
        held = provider.get_holdings(source)[0]
        with pytest.raises(Exception):
            held.quantity = 999

    def test_an_unknown_average_cost_is_none_rather_than_zero(self, provider, source):
        """Absent is absent. A zero cost basis is a claim that something was
        free."""
        for held in provider.get_holdings(source):
            assert held.average_cost is None or held.average_cost > 0

    # --- capabilities ----------------------------------------------------------------

    def test_every_provider_can_at_least_answer_holdings(self, provider):
        assert provider.supports(portfolio_providers.CAP_HOLDINGS)

    def test_an_unknown_capability_raises_rather_than_returning_false(self, provider):
        """Fail closed. `False` would read as "this provider cannot do that",
        when the truth is that nobody knows what was asked."""
        with pytest.raises(portfolio_providers.UnknownCapability):
            provider.supports("teleportation")

    @pytest.mark.parametrize("capability,call", [
        (portfolio_providers.CAP_ACCOUNTS, "get_account"),
        (portfolio_providers.CAP_BALANCES, "get_balances"),
        (portfolio_providers.CAP_POSITIONS, "get_positions"),
        (portfolio_providers.CAP_REFRESH, "refresh"),
    ])
    def test_an_unsupported_capability_refuses_with_a_reason(self, provider, source,
                                                            capability, call):
        """A refusal a caller can repeat aloud. The answer to "why can't you tell
        me my cash balance?" is a sentence, not a blank field."""
        if provider.supports(capability):
            pytest.skip(f"{provider.name} supports {capability}")
        with pytest.raises(portfolio_providers.ProviderCapabilityUnavailable) as refusal:
            getattr(provider, call)(source)
        assert len(str(refusal.value)) > 30, "a refusal without a reason is a blank field"

    # --- the gate stays in front of the provider ------------------------------------

    def test_no_provider_method_accepts_a_bare_id(self, provider):
        """Addendum 44 §7's conceptual `get_holdings(account_ref)` is deliberately
        not implemented (§101 spec §3.2). A public method taking a bare reference
        string is the by-id retrieval path that would not read as a bypass when
        somebody added it - it would read as implementing the specification.

        Scanned over **every** public method rather than a fixed list, because
        §101 found the hole this way: the scan walked a list of names and a newly
        added method slipped past it."""
        offenders = []
        for name, member in inspect.getmembers(provider, callable):
            if name.startswith("_"):
                continue
            try:
                parameters = inspect.signature(member).parameters
            except (TypeError, ValueError):  # pragma: no cover - builtins
                continue
            for argument in parameters:
                if argument in ("account_ref", "portfolio_id", "owner_id", "client_id",
                                "reference"):
                    offenders.append(f"{name}({argument})")
        assert not offenders, (
            f"{provider.name} takes a bare identifier: {offenders}. A provider fetches "
            "from a Source, and the broker's own reference is read off that rather than "
            "handed in by a caller.")

    def test_a_provider_is_chosen_from_a_source(self, provider):
        for claim in (provider.provider_type, None, {"provider_type": "MANUAL"}):
            with pytest.raises(TypeError):
                portfolio_providers.for_source(claim)

    def test_a_provider_refuses_a_source_it_does_not_serve(self, provider):
        """A provider that served somebody else's source would show a client the
        wrong account, and it would look like it worked."""
        other = next(t for t in portfolios.PROVIDER_TYPES if t != provider.provider_type)
        foreign = portfolio_providers.Source(provider_type=other, name="elsewhere")
        with pytest.raises(portfolio_providers.ProviderRefused):
            provider.get_holdings(foreign)

    # --- nothing is priced, and nothing is kept --------------------------------------

    def test_no_provider_returns_a_price(self, provider, source):
        """Positions come from a source and prices from the market data store
        (§113). A provider asserting a value would be a source deciding what
        somebody's money is worth."""
        for held in provider.get_holdings(source):
            assert not any(field in vars(held)
                           for field in ("market_price", "market_value", "gain", "pnl"))

    def test_nothing_a_provider_fetches_is_priced(self, provider, source):
        """`is_priced` is one line and LIVE-only. Neither provider in this build
        serves a LIVE source."""
        if not provider.supports(portfolio_providers.CAP_ACCOUNTS):
            pytest.skip(f"{provider.name} does not describe accounts")
        assert provider.get_account(source)["priced"] is False

    def test_a_balance_is_not_a_valuation(self, provider, source):
        """A cash balance is a quantity somebody holds, not a valuation of
        anything - which is what keeps the pricing rule narrow rather than
        awkward."""
        if not provider.supports(portfolio_providers.CAP_BALANCES):
            pytest.skip(f"{provider.name} cannot report balances")
        balances = provider.get_balances(source)
        assert balances["priced"] is False
        assert "cash" in balances

    def test_a_provider_writes_nothing(self, provider, source, tmp_path):
        """§111, as a property rather than a promise. A provider that cached its
        answer would pass every other test here."""
        before = {p for p in tmp_path.rglob("*")}
        provider.get_holdings(source)
        if provider.supports(portfolio_providers.CAP_REFRESH):
            provider.refresh(source)
        assert {p for p in tmp_path.rglob("*")} == before

    def test_a_provider_answers_the_same_question_the_same_way(self, provider, source):
        """Two fetches, one answer. A source that drifted between reads would
        make an exercise unreproducible and a comparison meaningless."""
        assert [vars(h) for h in provider.get_holdings(source)] == \
               [vars(h) for h in provider.get_holdings(source)]

    # --- the analyser does not change with the provider ------------------------------

    def test_the_analyser_does_not_change_with_the_provider(self, provider, source):
        """§15.3, and the reason `concentration` takes holdings rather than a
        connection. An analyser that read the source itself would agree with
        every provider trivially."""
        report = holdings.concentration(provider.get_holdings(source))
        assert report["positions"] == len(provider.get_holdings(source))
        assert report["priced"] is False

    def test_health_check_reports_without_being_asked_about_data(self, provider):
        """An operator asking "is this source up" must not have to fetch somebody's
        portfolio to find out."""
        report = provider.health_check()
        assert set(report) >= {"healthy", "detail"}
        assert isinstance(report["healthy"], bool)


class TestManualProviderContract(PortfolioProviderContract):
    """A source somebody maintains by hand: the positions arrive with it."""

    @pytest.fixture
    def provider(self):
        return portfolio_providers.ManualPortfolioProvider()

    @pytest.fixture
    def source(self):
        return portfolio_providers.Source(
            provider_type=portfolios.PROVIDER_MANUAL,
            name="a-spreadsheet",
            data_mode=portfolios.MODE_MANUAL,
            simulated=False,
            positions=(
                {"symbol": "SYN1", "quantity": 100, "average_cost": 10.0,
                 "asset_class": "stock", "as_of": "2026-01-01T00:00:00+00:00"},
                {"symbol": "SYN2", "quantity": 50, "average_cost": None,
                 "asset_class": "stock", "as_of": "2026-01-01T00:00:00+00:00"},
            ),
        )


class TestSimulatedProviderContract(PortfolioProviderContract):
    """An invented source, labelled as invented - and answering more of the
    interface than the manual one, which is what makes `supports()` a contract
    rather than a decoration."""

    @pytest.fixture
    def provider(self):
        return portfolio_providers.SimulatedPortfolioProvider()

    @pytest.fixture
    def source(self):
        return portfolio_providers.Source(
            provider_type=portfolios.PROVIDER_SIMULATED,
            name="morgan-simulated",
            owner_hint="morgan",
        )


def test_the_two_providers_answer_differently(monkeypatch):
    """The asymmetry is the point (§101 spec §11 Q5). If both providers answered
    everything, `supports()` would be decoration and the refusals would never
    run."""
    manual = portfolio_providers.ManualPortfolioProvider()
    simulated = portfolio_providers.SimulatedPortfolioProvider()

    differ = [c for c in portfolio_providers.CAPABILITIES
              if manual.supports(c) != simulated.supports(c)]
    assert differ, "two providers that answer identically do not test a contract"


def test_every_built_provider_passes_the_contract():
    """A provider added to the registry without a contract class would be a
    provider nothing checks. §101 found a hole exactly this way."""
    # Read from the classes themselves rather than by calling their fixtures,
    # which pytest rightly refuses. The `provider` fixture's body is a one-line
    # constructor, so the class it builds is what identifies the coverage.
    covered = (TestManualProviderContract, TestSimulatedProviderContract)
    tested = set()
    for klass in covered:
        returned = inspect.getsource(klass.provider).rsplit("return ", 1)[1].strip()
        constructor = getattr(portfolio_providers, returned.split("(")[0].split(".")[-1])
        tested.add(constructor().provider_type)

    built = {p.provider_type for p in portfolio_providers._PROVIDERS.values()}
    assert built <= tested, f"providers with no contract class: {sorted(built - tested)}"

def test_a_provider_that_does_not_answer_the_count_refuses_to_guess_it():
    """The default a future broker adapter inherits, and the one place TQ-80's
    detection can be silently undone.

    Both built providers override `position_count`, so nothing above this
    exercises the base. That matters because the base is what an adapter written
    against a broker with no account-summary endpoint will get - and the tempting
    implementation there is `len(self.get_holdings(source))`, which reads like a
    sensible default and is not one. It makes the assertion agree with the answer
    by construction: a source that truncated its response would confirm its own
    truncated count, and `SourceAnswer.short_by` would be `0` forever.

    So the base says **unknown**, and the consolidation carries that source as
    *unconfirmed* rather than as complete. A provider that cannot check is worse
    than one that says it cannot; a provider that pretends to check is worse than
    both, because the report then claims a completeness nobody verified.
    """
    class NoSummaryEndpoint(portfolio_providers._BaseProvider):
        """A perfectly ordinary adapter - it fetches holdings and never
        implements the count."""

        name = "no-summary"
        provider_type = portfolios.PROVIDER_MANUAL
        capabilities = (portfolio_providers.CAP_HOLDINGS,
                        portfolio_providers.CAP_ACCOUNTS,
                        portfolio_providers.CAP_POSITIONS)

        def get_holdings(self, source):
            return [portfolio_providers.Holding.from_row(row)
                    for row in self._check_source(source).positions]

    source = portfolio_providers.Source(
        provider_type=portfolios.PROVIDER_MANUAL,
        name="a-broker-with-no-summary",
        data_mode=portfolios.MODE_MANUAL,
        simulated=False,
        positions=({"symbol": "SYN1", "quantity": 10, "average_cost": 5.0,
                    "asset_class": "stock", "as_of": "2026-01-01T00:00:00+00:00"},),
    )
    provider = NoSummaryEndpoint()

    # It does return holdings - so counting them was available and was declined.
    assert [h.symbol for h in provider.get_holdings(source)] == ["SYN1"]
    assert provider.position_count(source) is None
    assert provider.get_account(source)["position_count"] is None

    # And the consolidation reads that as unknown rather than as agreement.
    answer = consolidation.SourceAnswer(
        holdings=tuple(provider.get_holdings(source)),
        expected_positions=provider.position_count(source))
    assert answer.confirmed is False
    assert answer.short_by == 0, "unknown is not a shortfall either"
