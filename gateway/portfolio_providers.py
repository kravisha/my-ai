"""Where holdings come from, behind one interface (TASK_QUEUE TQ-45b,
docs/SPEC_RECONCILIATION.md §101).

Source: addendum 44 §6.1, §6.2, §6.3, §7, §15.3, §15.4, §17, §20 Phase 2.

## The problem this exists for

Holdings had exactly one source: the client said what they hold and
`holdings.record` wrote it down (§96). Honest, no leak surface — and the only
shape the code could imagine. A brokerage account arrives as a different thing
entirely: accounts, balances, a sync time, a provider that can be *down*, and
none of those had anywhere to live.

§6.3 asks that simulation implement the same interface a brokerage provider will,
so the switch is an adapter rather than a rewrite.

## The trap, and the countermeasure

The trap is building the interface around the one implementation that exists.
§15.4 is the answer and it is why `tests/test_portfolio_provider_contract.py` was
written before the second provider: **a contract with a single implementation is
a description of that implementation.** The suite is what turns it into a
contract, and writing it early is what stops `SchwabPortfolioProvider` from
discovering next month that the "interface" encoded three assumptions only a
local database could satisfy.

The concrete guard, applied to every test in that suite: could a provider that
must make a network call satisfy this? If it needs a local database, the test is
wrong.

## The gate stays in front of the provider

Addendum 44 §7's conceptual interface is `get_holdings(account_ref)`. **That
signature is not implemented here, deliberately** (spec §3.2).

A public function that takes a bare reference string and returns holdings is the
second by-id retrieval path TQ-44 exists to prevent, one layer below where
`test_nothing_outside_portfolios_queries_the_portfolios_table` looks. It would not
read as a bypass when somebody added it — it would read as implementing the
specification.

So every method that reaches data takes a **resolved portfolio**: a dict that came
back from `portfolios.resolve()`, carrying the proof that the ownership
comparison ran. The broker's own reference is read from that row
(`provider_account_ref`), never handed in by a caller.

A provider is an adapter to a data source. **It is not an authorization boundary
and must never become one.**

`list_accounts(owner)` keeps its owner-scoped shape, because it takes no id and
so cannot be tricked into returning somebody else's — the same property that lets
`portfolios.owned()` exist safely beside `resolve()`.

## A provider says what it cannot do

`get_balances` and `refresh` have no honest answer for a MANUAL portfolio. Nobody
told this system how much cash the client holds, and there is nothing to refresh
*from* — the source is a person who spoke last Tuesday.

`{}` would read as "no cash". `{"cash": 0}` would be a fabrication. `None` puts
the interpretation in every caller. So a provider declares its capabilities and an
undeclared one raises `ProviderCapabilityUnavailable` **with a reason a caller can
repeat aloud** — the same shape `gateway/skills.py` uses for a declared-and-unbuilt
skill, one layer down. The answer to "why can't you tell me my cash balance?" is a
sentence, not a blank field.

That is also the only reason `ManualPortfolioProvider` earns its place (spec §11
Q5): two providers that genuinely differ in what they can answer is what makes
`supports()` a contract rather than a decoration.

## Freshness is never invented

§17: if the broker is unavailable, retain the snapshot, **mark it stale, do not
silently claim it is current.** So `refresh` stamps `last_synced_at` only when
data was actually fetched; a failure leaves the old value alone and reports the
failure; and a provider that cannot refresh raises rather than stamping the time
somebody asked. A `last_synced_at` that moves on a failed sync is worse than a
NULL one — NULL says "never synced", which is true.

## Nothing here is priced

`portfolios.is_priced()` is untouched and still one line: `LIVE` only. A
`SIMULATED` portfolio is not priced (spec §11 Q2), because widening that rule to
"LIVE, or SIMULATED-and-labelled" makes it two branches and the second is where
the mistake eventually lives.

**A cash balance is not a price**, which is what keeps the rule narrow rather than
awkward. `is_priced` governs *market-derived* values — what a position is worth
now, gain, loss, performance. Cash is a quantity somebody holds, not a valuation
of anything.

## The simulated provider generates; it does not read the organization

`SimulatedPortfolioProvider` must not reach into `financial_intelligence.db`.
That is the §95 invariant — no skill a client can invoke may read organization
data — and naming a symbol is not the same as querying the organization's
database for one. Its positions come from a table in this file.

It **seeds** those positions into `portfolio_holdings` and reads them back like
any other provider, rather than generating them on every read (spec §11 Q3). If
it generated, a holding a demo client stated in conversation would be invisible —
exactly the data §96 exists to preserve. A provider decides where rows came from
and how they are labelled; it does not decide where they live.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from backend.db import Database, now_iso
from gateway import holdings, portfolios

# --- capabilities ------------------------------------------------------------------
#
# Closed vocabulary, fail-closed on an unknown one, matching gateway/portfolios.py.

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
    """Data a provider will not accept (§17): malformed, quarantined rather than
    stored, with whatever was already there left alone."""


class UnknownCapability(ValueError):
    """A capability outside the vocabulary. Fail closed: a question this build
    cannot name is not one it may answer."""


@dataclass(frozen=True)
class Holding:
    """One position, in the canonical shape (addendum 44 §3.4, TQ-45a).

    Frozen because it is what a provider returned, not a working variable - the
    same reasoning `OwnerContext` is frozen for.

    Deliberately carries no `market_price` or `market_value`. Every price this
    organization produces is simulated, and a field existing is not permission to
    fill it in."""

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
        return cls(
            symbol=row["symbol"],
            quantity=row["quantity"],
            average_cost=row["average_cost"],
            asset_class=row["asset_class"],
            as_of=row["as_of"],
            note=row.get("note"),
            acquired_on=row.get("acquired_on"),
            simulated=bool(row.get("simulated")),
        )


class PortfolioProvider(Protocol):
    """What the rest of the system may assume about holdings, whoever supplies
    them.

    A Protocol rather than an ABC, following `app/model_provider.ModelProvider`
    and `backend/reference_data.SourceAdapter`: conformance is demonstrated by
    passing `PortfolioProviderContract`, not by inheriting."""

    name: str
    provider_type: str

    def supports(self, capability: str) -> bool: ...
    def list_accounts(self, conn: Database, owner) -> list[dict]: ...
    def get_account(self, conn: Database, portfolio: dict) -> dict: ...
    def get_holdings(self, conn: Database, portfolio: dict) -> list[Holding]: ...
    def get_balances(self, conn: Database, portfolio: dict) -> dict: ...
    def get_positions(self, conn: Database, portfolio: dict) -> list[Holding]: ...
    def refresh(self, conn: Database, portfolio: dict) -> dict: ...
    def health_check(self) -> dict: ...


def _check_capability(capability: str) -> str:
    if capability not in CAPABILITIES:
        raise UnknownCapability(
            f"unknown capability {capability!r}; known are {list(CAPABILITIES)}")
    return capability


class _BaseProvider:
    """The parts every provider shares: capability declaration, the refusals, and
    reading the holdings table for a portfolio that has been through the gate.

    Shared by inheritance here only because both implementations happen to store
    rows in the same place. A provider that fetches over a network implements the
    Protocol directly and shares none of this - which is the case the conformance
    suite is written for."""

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

    def list_accounts(self, conn: Database, owner) -> list[dict]:
        self._require(CAP_ACCOUNTS)
        # Owner-scoped in the query and takes no id, so there is no id it could
        # be tricked into returning (spec §3.2).
        return [self._account(p) for p in portfolios.listing(conn, owner)
                if p["provider_type"] == self.provider_type]

    def get_account(self, conn: Database, portfolio: dict) -> dict:
        self._require(CAP_ACCOUNTS)
        return self._account(portfolio)

    def _account(self, portfolio: dict) -> dict:
        return {
            "portfolio_id": portfolio["portfolio_id"],
            "display_name": portfolio["display_name"],
            "provider_type": portfolio["provider_type"],
            "data_mode": portfolio["data_mode"],
            # The broker's own reference, read off the resolved row rather than
            # accepted from a caller.
            "provider_account_ref": portfolio.get("provider_account_ref"),
            "last_synced_at": portfolio.get("last_synced_at"),
            # Named on every account, so a caller never has to remember which
            # data modes are priced (portfolios.is_priced is the one rule).
            "priced": portfolios.is_priced(portfolio),
            "simulated": bool(portfolio.get("simulated")),
        }

    def get_holdings(self, conn: Database, portfolio: dict) -> list[Holding]:
        self._require(CAP_HOLDINGS)
        # `holdings.listing` refuses anything but a resolved portfolio, so the
        # ownership comparison has already run by the time a row is read.
        return [Holding.from_row(row) for row in holdings.listing(conn, portfolio)]

    def get_positions(self, conn: Database, portfolio: dict) -> list[Holding]:
        self._require(CAP_POSITIONS)
        return self.get_holdings(conn, portfolio)

    def get_balances(self, conn: Database, portfolio: dict) -> dict:
        self._require(CAP_BALANCES)
        raise NotImplementedError  # pragma: no cover - a supporting provider overrides

    def refresh(self, conn: Database, portfolio: dict) -> dict:
        self._require(CAP_REFRESH)
        raise NotImplementedError  # pragma: no cover - a supporting provider overrides

    def health_check(self) -> dict:
        return {"healthy": True, "detail": f"{self.name} is available."}


class ManualPortfolioProvider(_BaseProvider):
    """What the client told their representative (§96).

    Not a stopgap and not a null object. It is the honest description of the
    source that exists today, and having it means the client-stated path goes
    through the same interface as everything else rather than being the special
    case everything else is compared against (spec §11 Q5).

    It cannot refresh and cannot report balances, and says so in sentences rather
    than returning empty ones. Those two refusals are the first real test of
    whether the capability declaration works."""

    name = "manual"
    provider_type = portfolios.PROVIDER_MANUAL
    capabilities = (CAP_HOLDINGS, CAP_ACCOUNTS, CAP_POSITIONS)
    refusals = {
        CAP_BALANCES: (
            "I only know what you have told me about, and you have not told me "
            "about any cash. I could not give you a balance without inventing one."
        ),
        CAP_REFRESH: (
            "There is nothing for me to refresh from - these holdings are what you "
            "told me, so they change when you tell me they have changed."
        ),
    }


# The simulated portfolios (§6.1), with the diversity that section asks for.
#
# Deterministic and written down rather than generated at random, so the demo is
# reproducible and a test can assert against it.
#
# Synthetic symbols from this system's own universe, never real tickers - a demo
# portfolio of real companies is one screenshot away from being read as advice
# about them. Named here rather than read from `financial_intelligence.db`: the
# §95 invariant is about reaching organization *data*, and naming a symbol is not
# querying for one.
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
    # by real demo data rather than only by a test.
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

# What an owner with no written-down fixture gets. The provider stays usable for
# any owner - which matters for the conformance suite, since a contract that only
# works for three hard-coded names is not one.
_GENERIC_SYMBOLS = ("SYN1", "SYN2", "SYN3", "SYN4", "SYN5")


class SimulatedPortfolioProvider(_BaseProvider):
    """Invented positions, labelled as invented (§6.1, §6.2).

    Answers more of the interface than the manual provider does, and that
    asymmetry is the point: it can refresh (it can regenerate what it invented)
    and it knows a cash balance (it invented one), where the manual provider
    honestly cannot.

    It does **not** produce a price, a market value or a gain. §6.2 says
    simulated data must never appear as live brokerage data, and the mechanism
    that guarantees it is `portfolios.is_priced` - which is false here because
    `data_mode` is SIMULATED, not LIVE."""

    name = "simulated"
    provider_type = portfolios.PROVIDER_SIMULATED
    capabilities = (CAP_HOLDINGS, CAP_ACCOUNTS, CAP_POSITIONS, CAP_BALANCES, CAP_REFRESH)

    def _fixture(self, owner_id: str) -> dict:
        """This owner's invented portfolio. Deterministic for any owner, written
        down for the three §6.1 names.

        Private, and made private by its own contract test: the id-shape scan in
        `test_no_provider_method_accepts_a_bare_id` flagged it on the first run
        after that scan was widened to every public method. It was right to. A
        *public* provider method taking a bare `owner_id` is the shape that
        becomes a bypass, even when - as here - it only computes a template and
        touches no stored data. Owner-scoped operations take an `OwnerContext`;
        this is an implementation detail and now looks like one."""
        if owner_id in SIMULATED_PORTFOLIOS:
            return SIMULATED_PORTFOLIOS[owner_id]
        # Stable across runs and platforms - `hash()` is salted per process and
        # would make the same demo different tomorrow.
        digest = hashlib.sha256(owner_id.encode("utf-8")).digest()
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

    def seed(self, conn: Database, portfolio: dict, *, simulated: bool = True) -> int:
        """Write the invented positions into the holdings table.

        Seeded rather than generated on read (spec §11 Q3). A provider that
        generated on every read would make a holding the client stated in
        conversation invisible, which is the data §96 exists to preserve.

        Through `holdings.record`, so the demo goes down the same path a real
        client's statement does - a seeder with its own INSERT would be the one
        writer whose validation nobody checked."""
        fixture = self._fixture(portfolio["owner_id"])
        for position in fixture["positions"]:
            holdings.record(conn, portfolio, simulated=simulated, **position)
        return len(fixture["positions"])

    def get_balances(self, conn: Database, portfolio: dict) -> dict:
        """Cash, and nothing derived from a price.

        A balance is not a valuation: it is a quantity somebody holds, so it does
        not touch `is_priced`. `priced` is reported alongside it anyway, so a
        caller reading a number off this dict is told in the same breath that
        nothing here is market-derived."""
        self._require(CAP_BALANCES)
        fixture = self._fixture(portfolio["owner_id"])
        return {
            "cash": fixture["cash"],
            "currency": "USD",
            "simulated": True,
            "priced": portfolios.is_priced(portfolio),
            "note": ("This is a simulated cash balance, not a real account. It is not a "
                     "valuation of anything - this system has no market prices."),
        }

    def refresh(self, conn: Database, portfolio: dict) -> dict:
        """Re-seed from the fixture and record that data really was fetched.

        `mark_synced` runs only after the rows land, per §17. If seeding raised,
        `last_synced_at` keeps whatever it had - a timestamp that moved on a
        failed sync would assert a freshness nothing has."""
        self._require(CAP_REFRESH)
        owner = portfolios.for_client(portfolio["owner_id"])
        count = self.seed(conn, portfolio)
        synced = portfolios.mark_synced(conn, portfolio["portfolio_id"], owner)
        return {"refreshed": True, "holdings": count,
                "last_synced_at": synced["last_synced_at"], "simulated": True}

    def health_check(self) -> dict:
        return {"healthy": True,
                "detail": "Simulated provider: invented data, never a real brokerage."}


_PROVIDERS: dict[str, PortfolioProvider] = {
    portfolios.PROVIDER_MANUAL: ManualPortfolioProvider(),
    portfolios.PROVIDER_SIMULATED: SimulatedPortfolioProvider(),
    # PROVIDER_SCHWAB is deliberately absent until TQ-49. `for_portfolio` raises
    # for it rather than falling back, which is the honest behaviour: a Schwab
    # portfolio in this build is one nothing can read, and pretending otherwise
    # by serving it from the manual provider would show somebody their stated
    # holdings where they asked for their brokerage account.
}


def for_portfolio(portfolio: dict) -> PortfolioProvider:
    """The provider that stocks this portfolio.

    Raises on an unknown or unbuilt provider type rather than falling back to the
    manual one - the same fail-closed rule `portfolios._interpret` applies to
    every other vocabulary. A portfolio whose provider this build does not
    recognise is not one whose holdings it may present."""
    if not isinstance(portfolio, dict):
        raise TypeError(
            "a provider is chosen from a resolved portfolio, not from an id or a "
            "provider name. Use portfolios.resolve() first.")
    provider_type = portfolio.get("provider_type")
    if provider_type not in _PROVIDERS:
        raise ProviderRefused(
            f"no provider is built for {provider_type!r}. Known are "
            f"{sorted(_PROVIDERS)}; refusing rather than serving this portfolio "
            "from a different source than it claims.")
    return _PROVIDERS[provider_type]


def health() -> dict:
    """Every built provider's own report. For an operator asking what is up, and
    the shape TQ-49's Schwab provider reports a down API in."""
    return {name: provider.health_check() for name, provider in
            sorted((p.name, p) for p in _PROVIDERS.values())}
