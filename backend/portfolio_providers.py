"""Where holdings come from, behind one interface (TASK_QUEUE TQ-45b,
docs/SPEC_RECONCILIATION.md §101; **reshaped from readers into fetchers by
TQ-72, §111**).

## What changed, and what did not

§101 built this so that the *source* of a portfolio could change without the
analyser changing:

> *"§6.3 asks that simulation implement the same interface a brokerage provider
> will, so the switch is an adapter rather than a rewrite."*

The source has now changed, in the largest way available: **there is no local
store to read.** Owner direction (§111, §115) — the client supplies a source name
and credentials, the agent fetches from the external system, analyses, and
retains nothing.

So the interface was built for exactly this and it still had to move, because
every method took two things it can no longer have: a database connection, and a
*resolved portfolio row*. Both were the store. What survives untouched is the
part that mattered — the capability declaration, the refusals with reasons, the
canonical `Holding`, and the rule that a provider is an adapter and **never an
authorization boundary**.

## A provider takes a source, not a portfolio

The old signature was `get_holdings(conn, portfolio)` where `portfolio` was a row
proving `portfolios.resolve()` had run. There is no row. A provider now takes a
`Source` — what the client named, and where it points.

**This is deliberately the minimum that removes the store, not the finished
shape.** TQ-73 owns the request: credentials, several sources per client,
consolidation across them, and the session that holds the result. Designing that
here would be designing it without its requirements. What is settled now is the
*direction* — a provider fetches rather than reads — and the signatures move once
more when TQ-73 knows what a credential looks like.

## A provider says what it cannot do

Unchanged from §101, and the reason it earns its place is unchanged too:
`get_balances` and `refresh` have no honest answer for a source that is a
supplied list of positions. `{}` would read as "no cash", `{"cash": 0}` would be
a fabrication, and `None` puts the interpretation in every caller. So a provider
declares its capabilities and an undeclared one raises **with a reason a caller
can repeat aloud**.

That is also the only reason two implementations exist here rather than one (§101
spec §11 Q5): **two providers that genuinely differ in what they can answer is
what makes `supports()` a contract rather than a decoration.**

## Nothing here is priced, and nothing is retained

`Holding` carries no `market_price` and no `market_value`, which is now a
statement about architecture rather than about caution: §113 puts prices in the
market data store, fetched at analysis time and joined to positions there. A
position and its price arrive from different places and are combined for the
length of a request.

And nothing a provider returns is written anywhere. There is no `seed`, because
seeding wrote rows; the simulated provider *returns* its fixtures now, which is
what a simulated exchange does (§115, TQ-77).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol

from backend import holdings, portfolios

# --- capabilities ------------------------------------------------------------------
#
# Closed vocabulary, fail-closed on an unknown one.

CAP_HOLDINGS = "holdings"
CAP_ACCOUNTS = "accounts"
CAP_BALANCES = "balances"
CAP_POSITIONS = "positions"
CAP_REFRESH = "refresh"
CAPABILITIES = (CAP_HOLDINGS, CAP_ACCOUNTS, CAP_BALANCES, CAP_POSITIONS, CAP_REFRESH)


class ProviderCapabilityUnavailable(NotImplementedError):
    """This provider cannot answer that, and says why rather than guessing.

    Carries a sentence meant to be repeated to the person who asked. A blank
    field or a zero would be an answer; this is an explanation."""


class ProviderRefused(RuntimeError):
    """Data a provider will not accept, or a source it cannot serve."""


class UnknownCapability(ValueError):
    """A capability outside the vocabulary. Fail closed: a question this build
    cannot name is not one it may answer."""


@dataclass(frozen=True)
class Holding:
    """One position, in the canonical shape (addendum 44 §3.4, TQ-45a).

    Frozen because it is what a source returned, not a working variable - the
    same reasoning `OwnerContext` is frozen for.

    Deliberately carries no `market_price` or `market_value`. Positions come from
    a broker and prices come from the market data store (§113); a value is
    computed by joining them at analysis time, not by a source asserting one."""

    symbol: str
    quantity: float
    average_cost: float | None
    asset_class: str
    as_of: str
    note: str | None = None
    acquired_on: str | None = None
    simulated: bool = False

    @classmethod
    def from_row(cls, row: dict) -> "Holding":
        """Build one from a mapping a source produced.

        Validated rather than trusted: a source is somebody else's system, and
        `holdings.clean_symbol` / `clean_asset_class` / `quantity` are the same
        checks that used to run on the way into the table. They run on the way
        *in from a fetch* now, which is the same boundary one step earlier."""
        return cls(
            symbol=holdings.clean_symbol(row["symbol"]),
            quantity=holdings.quantity(row["quantity"]),
            average_cost=holdings.positive(
                row.get("average_cost"), "an average cost", required=False),
            asset_class=holdings.clean_asset_class(row.get("asset_class")),
            as_of=row.get("as_of") or "",
            note=row.get("note"),
            acquired_on=row.get("acquired_on"),
            simulated=bool(row.get("simulated")),
        )


@dataclass(frozen=True)
class Source:
    """What the client named, and where it points (§115).

    > *"The portfolio is provided as an external source and all that is provided
    > is source name and credentials."*

    **Provisional, and TQ-73 finalises it.** There is no credential field yet
    because there is nothing to authenticate against and no envelope to carry one
    in; adding an always-empty one now would be the machinery-with-no-user this
    project refuses. What is here is what removing the store required: which
    provider serves this source, what it is called, and what it points at.

    `positions` exists for the one provider whose source *is* the positions - a
    manually maintained list that arrives with the request rather than being
    fetched. It is empty for every fetching provider."""

    provider_type: str
    name: str
    reference: str | None = None
    data_mode: str = portfolios.MODE_SIMULATED
    simulated: bool = True
    owner_hint: str | None = None
    positions: tuple = field(default_factory=tuple)

    def __post_init__(self) -> None:
        portfolios.check_vocabulary(
            self.provider_type, portfolios.PROVIDER_TYPES, "provider type")
        portfolios.check_vocabulary(self.data_mode, portfolios.DATA_MODES, "data mode")
        if not (self.name or "").strip():
            raise portfolios.UnknownVocabulary("a source needs a name")


class PortfolioProvider(Protocol):
    """What the rest of the system may assume about holdings, whoever supplies
    them.

    A Protocol rather than an ABC, following `app/model_provider.ModelProvider`
    and `backend/reference_data.SourceAdapter`: conformance is demonstrated by
    passing `PortfolioProviderContract`, not by inheriting.

    **A provider is an adapter to a data source. It is not an authorization
    boundary and must never become one** - unchanged from §101, and more
    important now that there is no table behind it to be the boundary instead.
    Who a fetch is for is decided before a provider is chosen."""

    name: str
    provider_type: str

    def supports(self, capability: str) -> bool: ...
    def get_account(self, source: Source) -> dict: ...
    def position_count(self, source: Source) -> int | None: ...
    def get_holdings(self, source: Source) -> list[Holding]: ...
    def get_balances(self, source: Source) -> dict: ...
    def get_positions(self, source: Source) -> list[Holding]: ...
    def refresh(self, source: Source) -> dict: ...
    def health_check(self) -> dict: ...


def _check_capability(capability: str) -> str:
    if capability not in CAPABILITIES:
        raise UnknownCapability(
            f"unknown capability {capability!r}; known are {list(CAPABILITIES)}")
    return capability


class _BaseProvider:
    """Capability declaration and the refusals - the parts every provider shares
    now that none of them shares a table.

    What it deliberately no longer shares is *how holdings are obtained*. That
    was the whole of the old base class and it was only shareable because both
    implementations read the same rows. A provider that fetches over a network
    implements the Protocol and shares none of this, which is the case the
    conformance suite was written for and is now the ordinary case."""

    name = "base"
    provider_type = ""
    capabilities: tuple[str, ...] = ()
    # Why each unsupported capability is unavailable, in words the caller can
    # repeat. Silence would leave the agent to invent an explanation.
    refusals: dict[str, str] = {}

    def supports(self, capability: str) -> bool:
        return _check_capability(capability) in self.capabilities

    def _require(self, capability: str) -> None:
        if not self.supports(capability):
            raise ProviderCapabilityUnavailable(
                self.refusals.get(capability)
                or f"{self.name} cannot answer {capability!r}, and will not guess.")

    def _check_source(self, source: Source) -> Source:
        if not isinstance(source, Source):
            raise TypeError(
                "a provider fetches from a Source, not from an id or a name. "
                "Build one from what the client supplied.")
        if source.provider_type != self.provider_type:
            raise ProviderRefused(
                f"{self.name} cannot serve a {source.provider_type!r} source; refusing "
                "rather than fetching from a different place than it claims.")
        return source

    def get_account(self, source: Source) -> dict:
        self._require(CAP_ACCOUNTS)
        source = self._check_source(source)
        return {
            "name": source.name,
            "provider_type": source.provider_type,
            "data_mode": source.data_mode,
            # The source's own reference - a broker account number, a file path -
            # read off the source the client named rather than invented here.
            "reference": source.reference,
            # Named on every account so a caller never has to remember which data
            # modes are priced. Still `portfolios.is_priced`, which §113 has put
            # on notice: the rule moves to the price's provenance when TQ-75
            # gives it one to read.
            "priced": portfolios.is_priced({"data_mode": source.data_mode}),
            "simulated": bool(source.simulated),
            # **How many positions this account says it holds** - the assertion
            # that makes a silently partial answer detectable (TQ-80).
            #
            # `None` means the source did not say, which is *unknown* and never
            # "therefore complete". That default was the actual defect: an
            # analyst treating "the positions I received" as "all the positions"
            # is defaulting an absence to the favourable value, which is what
            # §100 and §104 forbid everywhere else.
            #
            # It is on the account rather than beside the holdings because that
            # is where a real integration finds it: a broker's account endpoint
            # reports a position count, its positions endpoint returns rows, and
            # **the two disagreeing is the signal**.
            "position_count": self.position_count(source),
        }

    def position_count(self, source: Source) -> int | None:
        """How many positions this source says it holds, or None if it will not
        say.

        Overridden by any provider that can answer honestly. The base refuses to
        guess: a provider that does not know must say so rather than counting
        what it happened to return, which would make the assertion agree with
        the answer by construction and detect nothing."""
        return None

    def get_positions(self, source: Source) -> list[Holding]:
        self._require(CAP_POSITIONS)
        return self.get_holdings(source)

    def get_balances(self, source: Source) -> dict:
        self._require(CAP_BALANCES)
        raise NotImplementedError  # pragma: no cover - a supporting provider overrides

    def refresh(self, source: Source) -> dict:
        self._require(CAP_REFRESH)
        raise NotImplementedError  # pragma: no cover - a supporting provider overrides

    def health_check(self) -> dict:
        return {"healthy": True, "detail": f"{self.name} is available."}


class ManualPortfolioProvider(_BaseProvider):
    """A source somebody maintains by hand, whose positions arrive with the
    request rather than being fetched.

    §96's version of this was "what the client told their representative", which
    §115 retired: a client now names a source and supplies credentials rather
    than dictating positions. What remains genuinely manual is a source with no
    API behind it - a spreadsheet the operator keeps, an export somebody pastes -
    and for those the positions *are* the source.

    It cannot refresh and cannot report balances, and says so in sentences rather
    than returning empty ones. Those two refusals are still the only real test of
    whether the capability declaration works, which is why this provider exists
    beside the simulated one."""

    name = "manual"
    provider_type = portfolios.PROVIDER_MANUAL
    capabilities = (CAP_HOLDINGS, CAP_ACCOUNTS, CAP_POSITIONS)
    refusals = {
        CAP_BALANCES: (
            "This source is a list of positions and nothing else - there is no cash "
            "figure in it. I could not give you a balance without inventing one."
        ),
        CAP_REFRESH: (
            "There is nothing for me to refresh from - this source is maintained by "
            "hand, so it changes when whoever keeps it changes it."
        ),
    }

    def get_holdings(self, source: Source) -> list[Holding]:
        self._require(CAP_HOLDINGS)
        source = self._check_source(source)
        return [Holding.from_row(dict(row)) for row in source.positions]

    def position_count(self, source: Source) -> int | None:
        """A hand-maintained source *is* its positions, and they all arrived
        together, so this can answer honestly.

        It is not "count what I returned" dressed up: the count comes from the
        source descriptor rather than from the list this provider built, so a
        provider that dropped a row while converting would be caught by its own
        assertion."""
        return len(self._check_source(source).positions)


# The simulated portfolios (§6.1), with the diversity that section asks for.
#
# Deterministic and written down rather than generated at random, so an exercise
# is reproducible and a test can assert against it.
#
# **These are training fixtures now** (§114), not demo data awaiting deletion.
# They were built under §96's rule - "use the simulated client data for now and
# remove it later before live" - and the owner's reframing changed what they are:
# imaginary clients the Department of Education practises on, which do not get
# deleted. The `simulated` flag still marks them; what changed is the policy the
# flag implies, which is TQ-76's to draw.
#
# Synthetic symbols from this system's own universe, never real tickers - a demo
# portfolio of real companies is one screenshot away from being read as advice
# about them.
SIMULATED_PORTFOLIOS: dict[str, dict] = {
    # §6.1's Client 001: large-cap equities plus one covered call.
    "customer": {
        "cash": 18_400.00,
        "positions": [
            {"symbol": "SYN1", "quantity": 400, "average_cost": 42.50,
             "asset_class": "stock", "acquired_on": "2024-03-11"},
            {"symbol": "SYN3", "quantity": 120, "average_cost": 118.00,
             "asset_class": "stock", "acquired_on": "2024-09-02"},
            {"symbol": "SYN7", "quantity": 250, "average_cost": 61.25,
             "asset_class": "stock", "acquired_on": "2025-01-20"},
            {"symbol": "SYN1C50", "quantity": -4, "average_cost": 1.85,
             "asset_class": "stock_option", "acquired_on": "2025-07-01",
             "note": "covered call written against the SYN1 position"},
        ],
    },
    # §6.1's Client 002: growth equities plus long calls and a protective put.
    # Deliberately concentrated, so the concentration report has something true
    # and uncomfortable to say.
    "avery": {
        "cash": 2_150.00,
        "positions": [
            {"symbol": "SYN2", "quantity": 3000, "average_cost": 318.40,
             "asset_class": "stock", "acquired_on": "2023-11-05"},
            {"symbol": "SYN5", "quantity": 90, "average_cost": 180.10,
             "asset_class": "stock", "acquired_on": "2025-02-14"},
            {"symbol": "SYN2C350", "quantity": 10, "average_cost": 12.40,
             "asset_class": "stock_option", "acquired_on": "2025-06-11",
             "note": "long calls"},
            {"symbol": "SYN2P300", "quantity": 15, "average_cost": 8.05,
             "asset_class": "stock_option", "acquired_on": "2025-06-11",
             "note": "protective puts against the SYN2 position"},
        ],
    },
    # §6.1's Client 003: diversified, cash plus equities. Deliberately missing a
    # cost basis on one line, so the "counted but not weighted" path is exercised
    # by real fixture data rather than only by a test.
    "morgan": {
        "cash": 96_500.00,
        "positions": [
            {"symbol": "SYN4", "quantity": 500, "average_cost": 27.80,
             "asset_class": "stock", "acquired_on": "2024-06-18"},
            {"symbol": "SYN6", "quantity": 75, "average_cost": None,
             "asset_class": "stock", "note": "inherited; cost basis unknown"},
            {"symbol": "SYN9", "quantity": 210, "average_cost": 54.00,
             "asset_class": "stock", "acquired_on": "2025-04-09"},
            {"symbol": "SYN8", "quantity": 140, "average_cost": 31.15,
             "asset_class": "etf", "acquired_on": "2025-03-02"},
        ],
    },
}

# What a source with no written-down fixture gets. The provider stays usable for
# any name - which matters for the conformance suite, since a contract that only
# works for three hard-coded names is not one.
_GENERIC_SYMBOLS = ("SYN1", "SYN2", "SYN3", "SYN4", "SYN5")

# Fixtures carry no timestamp of their own, so one is stamped on the way out.
# Fixed rather than "now": a fixture that changed its `as_of` on every read would
# make an exercise unreproducible, and §115's simulated exchange has to be able
# to answer the same question twice the same way.
FIXTURE_AS_OF = "2026-01-01T00:00:00+00:00"


class SimulatedPortfolioProvider(_BaseProvider):
    """An invented source, labelled as invented (§6.1, §6.2).

    Answers more of the interface than the manual provider does, and that
    asymmetry is the point: it can refresh (it can re-answer) and it knows a cash
    balance (it invented one), where the manual provider honestly cannot.

    **It returns rather than seeds.** The old version wrote its fixtures into
    `portfolio_holdings` and read them back, which was right while a store
    existed and is exactly the custody §111 removed. A simulated *exchange*
    answers a query; it does not fill somebody's database first.

    It does **not** produce a price, a market value or a gain. §6.2 says
    simulated data must never appear as live brokerage data, and the mechanism is
    that a `SIMULATED` source is not `LIVE`."""

    name = "simulated"
    provider_type = portfolios.PROVIDER_SIMULATED
    capabilities = (CAP_HOLDINGS, CAP_ACCOUNTS, CAP_POSITIONS, CAP_BALANCES, CAP_REFRESH)

    def _fixture(self, name: str) -> dict:
        """This source's invented portfolio. Deterministic for any name, written
        down for the three §6.1 ones.

        Private, and made private by its own contract test: the id-shape scan in
        `test_no_provider_method_accepts_a_bare_id` flagged it on the first run
        after that scan was widened to every public method, and it was right to.
        A *public* provider method taking a bare name is the shape that becomes a
        bypass."""
        if name in SIMULATED_PORTFOLIOS:
            return SIMULATED_PORTFOLIOS[name]
        # Stable across runs and platforms - `hash()` is salted per process and
        # would make the same exercise different tomorrow.
        digest = hashlib.sha256(name.encode("utf-8")).digest()
        count = 2 + digest[0] % 3
        return {
            "cash": round(1_000 + digest[1] * 37.5, 2),
            "positions": [
                {"symbol": _GENERIC_SYMBOLS[(digest[2] + i) % len(_GENERIC_SYMBOLS)],
                 "quantity": 10 + digest[3 + i] % 90,
                 "average_cost": round(10 + digest[4 + i] % 200 + 0.25, 2),
                 "asset_class": "stock"}
                for i in range(count)
            ],
        }

    def get_holdings(self, source: Source) -> list[Holding]:
        self._require(CAP_HOLDINGS)
        source = self._check_source(source)
        fixture = self._fixture(source.owner_hint or source.name)
        return [Holding.from_row({**position, "as_of": FIXTURE_AS_OF, "simulated": True})
                for position in fixture["positions"]]

    def position_count(self, source: Source) -> int | None:
        return len(self._fixture(source.owner_hint or source.name)["positions"])

    def get_balances(self, source: Source) -> dict:
        """Cash, and nothing derived from a price.

        A balance is not a valuation: it is a quantity somebody holds, so it does
        not touch `is_priced`. `priced` is reported alongside it anyway, so a
        caller reading a number off this dict is told in the same breath that
        nothing here is market-derived."""
        self._require(CAP_BALANCES)
        source = self._check_source(source)
        fixture = self._fixture(source.owner_hint or source.name)
        return {
            "cash": fixture["cash"],
            "currency": "USD",
            "simulated": True,
            "priced": portfolios.is_priced({"data_mode": source.data_mode}),
            "note": ("This is a simulated cash balance, not a real account. It is not a "
                     "valuation of anything."),
        }

    def refresh(self, source: Source) -> dict:
        """Answer again, and say how many positions came back.

        There is no `last_synced_at` to stamp any more, and its absence is the
        §17 rule holding rather than being dropped: *mark it stale, do not
        silently claim it is current.* Nothing is retained, so nothing can go
        stale, and a freshness claim about stored data would be a claim about
        data that does not exist."""
        self._require(CAP_REFRESH)
        source = self._check_source(source)
        held = self.get_holdings(source)
        return {"refreshed": True, "holdings": len(held), "simulated": True}

    def health_check(self) -> dict:
        return {"healthy": True,
                "detail": "Simulated provider: invented data, never a real brokerage."}


_PROVIDERS: dict[str, PortfolioProvider] = {
    portfolios.PROVIDER_MANUAL: ManualPortfolioProvider(),
    portfolios.PROVIDER_SIMULATED: SimulatedPortfolioProvider(),
    # PROVIDER_SCHWAB is deliberately absent until TQ-49/TQ-50. `for_source`
    # raises for it rather than falling back, which is the honest behaviour: a
    # Schwab source in this build is one nothing can fetch, and pretending
    # otherwise by serving it from another provider would show somebody the wrong
    # account.
}


def for_source(source: Source) -> PortfolioProvider:
    """The provider that serves this source.

    Raises on an unknown or unbuilt provider type rather than falling back - the
    same fail-closed rule every other vocabulary here works under. A source whose
    provider this build does not recognise is not one whose holdings it may
    present."""
    if not isinstance(source, Source):
        raise TypeError(
            "a provider is chosen from a Source, not from an id or a provider name.")
    if source.provider_type not in _PROVIDERS:
        raise ProviderRefused(
            f"no provider is built for {source.provider_type!r}. Known are "
            f"{sorted(_PROVIDERS)}; refusing rather than serving this source from a "
            "different place than it claims.")
    return _PROVIDERS[source.provider_type]


def health() -> dict:
    """Every built provider's own report. For an operator asking what is up, and
    the shape TQ-49's Schwab provider reports a down API in."""
    return {name: provider.health_check() for name, provider in
            sorted((p.name, p) for p in _PROVIDERS.values())}
