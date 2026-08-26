"""The simulated exchange: what answers when the analyst calls out (TASK_QUEUE
TQ-77; docs/SPEC_RECONCILIATION.md §114, §115).

Owner direction, 2026-08-27:

> *"The simulation engine simulates all external calls the agent makes and also
> the task that is assigned to the agent… using the simulation engine to mimic
> client requests and also provide the portfolio to the agents through simulated
> exchanges."*

## The substitution is at the boundary, and the agent has one code path

§115 corrected an earlier framing that treated "training must match production"
as a discipline to maintain. It is not: the analyst is tasked, it fetches from a
source, and it consolidates — **in both modes**. What differs is what answers the
call.

So there is no simulation branch in `agents/portfolio_analyst.py`, and there is
nothing there for one to be added to. This exchange is registered as an ordinary
provider; the analyst reaches it through `for_source` like any other, because
what it fetches from is decided by the request rather than by the mode.

`simulation/harness.py` states the principle this follows: *"It does not import
agents, stub providers, or drive the pipeline… Isolation is the database, not a
flag."*

## An exchange that never fails is the wrong teacher

`SimulatedPortfolioProvider` always succeeds. That is right for a fixture and
wrong for an *exchange*, because a broker that never fails trains an analyst on a
world that does not exist — and every habit it forms about partial data, stale
data and unreachable sources would be formed in a world where those never happen.

That is §114's trap in its sharpest form: the exercise has to be the production
workflow, and production includes the broker being down.

`simulation/faults.py` already exists for this at the process level and states
why it matters, quoting the Fault Tolerance Framework §15: the purpose *"is not
merely to prove that processes restart. It is to prove that the organization
notices, assigns responsibility, recovers coherently, and learns."* This is the
same argument one boundary further out.

So an exchange can be asked to be:

- **healthy** — answers with the fixture;
- **unreachable** — refuses, as a broker whose API is down does;
- **slow** — answers, eventually, which is what a timeout is made of;
- **partial** — answers with some of the account, which is the failure nobody
  notices because it looks like an answer;
- **malformed** — answers with something that is not a position.

**`partial` is the one worth having.** Unreachable and malformed announce
themselves; a broker that quietly returns three of five positions produces a
consolidation that is wrong and looks right, and the only thing standing between
that and a client is whether the analyst noticed the account did not add up.

## Faults are declared, deterministic, and never random

A fault is attached to a source by name in the scenario. Two runs of one exercise
must produce the same answer or a curriculum cannot grade it and a regression
cannot be reproduced — the same reasoning `SimulatedPortfolioProvider._fixture`
gives for hashing a name rather than calling `random`.

## Nothing here is real, and everything says so

Every holding this exchange returns carries `simulated=True`, and the data mode
is `SIMULATED`, so `portfolios.is_priced` is False and §6.2's rule holds: **the
mechanism that stops simulated data being mistaken for a live brokerage account
is not a label somebody remembered to add, it is that a SIMULATED source is not
LIVE.**
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from backend import portfolio_providers, portfolios

# What an exchange can be asked to be. A closed vocabulary, fail-closed on an
# unknown one: a behaviour this build cannot produce is not one a scenario may
# quietly get something else for.
BEHAVIOUR_HEALTHY = "healthy"
BEHAVIOUR_UNREACHABLE = "unreachable"
BEHAVIOUR_SLOW = "slow"
BEHAVIOUR_PARTIAL = "partial"
BEHAVIOUR_MALFORMED = "malformed"
BEHAVIOURS = (BEHAVIOUR_HEALTHY, BEHAVIOUR_UNREACHABLE, BEHAVIOUR_SLOW,
              BEHAVIOUR_PARTIAL, BEHAVIOUR_MALFORMED)

# The provider type a simulated exchange serves. Deliberately the same
# `SIMULATED` the fixture provider uses, because from the analyst's side they are
# the same kind of thing - an invented source - and giving the exchange its own
# type would be a way for a caller to tell them apart, which is the property
# TQ-77 exists to remove.
PROVIDER_TYPE = portfolios.PROVIDER_SIMULATED

DEFAULT_SLOW_SECONDS = 0.25


class ExchangeError(ValueError):
    """A scenario asked for an exchange this build cannot produce."""


@dataclass(frozen=True)
class ExchangeBehaviour:
    """How one named source behaves in this exercise.

    Attached to a *source name* rather than to a client, because that is what a
    scenario can state and what an outage actually is: one broker is down, not
    one customer."""

    source: str
    behaviour: str = BEHAVIOUR_HEALTHY
    # For `partial`: how many positions the account actually returns. `None`
    # means half, rounded down, which is enough to be wrong and not enough to be
    # obvious.
    returns: int | None = None
    slow_seconds: float = DEFAULT_SLOW_SECONDS
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.behaviour not in BEHAVIOURS:
            raise ExchangeError(
                f"unknown exchange behaviour {self.behaviour!r}; known are "
                f"{list(BEHAVIOURS)}")
        if self.returns is not None and self.returns < 0:
            raise ExchangeError("an account cannot return fewer than no positions")


@dataclass
class SimulatedExchange:
    """An external system that answers the analyst's call — sometimes badly.

    Holds its behaviours rather than reading them from anywhere global, so two
    exercises can run against different worlds in one process and neither can
    reach into the other's."""

    behaviours: dict = field(default_factory=dict)
    name = "simulated-exchange"
    provider_type = PROVIDER_TYPE
    capabilities = (portfolio_providers.CAP_HOLDINGS, portfolio_providers.CAP_ACCOUNTS,
                    portfolio_providers.CAP_POSITIONS, portfolio_providers.CAP_BALANCES)
    refusals = {
        portfolio_providers.CAP_REFRESH: (
            "This exchange answers a query; it does not hold a copy to refresh."
        ),
    }

    @classmethod
    def from_scenario(cls, declared) -> "SimulatedExchange":
        """Build one from a scenario's list of `{source, behaviour, ...}` maps.

        Refuses an unknown behaviour at construction rather than at fetch time,
        because a scenario that asks for something this build cannot produce
        should fail when it is loaded and not halfway through an exercise."""
        behaviours = {}
        for entry in declared or ():
            behaviour = ExchangeBehaviour(**dict(entry))
            behaviours[behaviour.source] = behaviour
        return cls(behaviours=behaviours)

    # --- the provider interface -----------------------------------------------

    def supports(self, capability: str) -> bool:
        if capability not in portfolio_providers.CAPABILITIES:
            raise portfolio_providers.UnknownCapability(
                f"unknown capability {capability!r}; known are "
                f"{list(portfolio_providers.CAPABILITIES)}")
        return capability in self.capabilities

    def _require(self, capability: str) -> None:
        if not self.supports(capability):
            raise portfolio_providers.ProviderCapabilityUnavailable(
                self.refusals.get(capability)
                or f"{self.name} cannot answer {capability!r}, and will not guess.")

    def behaviour_for(self, source) -> ExchangeBehaviour:
        return self.behaviours.get(source.name, ExchangeBehaviour(source=source.name))

    def get_account(self, source) -> dict:
        self._require(portfolio_providers.CAP_ACCOUNTS)
        return {
            "name": source.name,
            "provider_type": source.provider_type,
            "data_mode": source.data_mode,
            "reference": source.reference,
            "priced": portfolios.is_priced({"data_mode": source.data_mode}),
            "simulated": True,
        }

    def get_holdings(self, source) -> list:
        """What this account returns — which is not always what it holds.

        The behaviours here are the ones that produce the failures worth
        training on, and `partial` is the one that matters: unreachable and
        malformed announce themselves, while a broker quietly returning three of
        five positions produces a consolidation that is wrong and looks right."""
        self._require(portfolio_providers.CAP_HOLDINGS)
        behaviour = self.behaviour_for(source)

        if behaviour.behaviour == BEHAVIOUR_UNREACHABLE:
            raise portfolio_providers.ProviderRefused(
                behaviour.reason
                or f"{source.name} did not answer (the exchange is unreachable).")

        if behaviour.behaviour == BEHAVIOUR_SLOW:
            # A real delay rather than a mocked clock, because what this
            # exercises is a caller's patience and a heartbeat's staleness
            # threshold, and neither of those is fooled by a fake clock.
            time.sleep(max(0.0, behaviour.slow_seconds))

        if behaviour.behaviour == BEHAVIOUR_MALFORMED:
            # Not a position. The canonical shape's own validation is what has
            # to catch this, which is the point of asserting it here rather than
            # trusting it.
            return [portfolio_providers.Holding.from_row(
                {"symbol": "", "quantity": 1, "asset_class": "stock", "as_of": ""})]

        held = self._fixture_holdings(source)
        if behaviour.behaviour == BEHAVIOUR_PARTIAL:
            keep = behaviour.returns if behaviour.returns is not None else len(held) // 2
            return held[:max(0, keep)]
        return held

    def get_positions(self, source) -> list:
        self._require(portfolio_providers.CAP_POSITIONS)
        return self.get_holdings(source)

    def get_balances(self, source) -> dict:
        self._require(portfolio_providers.CAP_BALANCES)
        behaviour = self.behaviour_for(source)
        if behaviour.behaviour == BEHAVIOUR_UNREACHABLE:
            raise portfolio_providers.ProviderRefused(
                behaviour.reason or f"{source.name} did not answer.")
        fixture = portfolio_providers.SIMULATED_PORTFOLIOS.get(
            source.owner_hint or source.name, {})
        return {
            "cash": fixture.get("cash", 0.0),
            "currency": "USD",
            "simulated": True,
            "priced": False,
            "note": "This is a simulated cash balance, not a real account.",
        }

    def refresh(self, source) -> dict:
        self._require(portfolio_providers.CAP_REFRESH)
        raise NotImplementedError  # pragma: no cover - never supported

    def health_check(self) -> dict:
        """What an operator asking "is this exchange up" gets.

        Reports the *declared* faults rather than probing, so asking does not
        itself trigger one - and so a scenario's intent is visible without
        reading the scenario."""
        failing = sorted(name for name, behaviour in self.behaviours.items()
                         if behaviour.behaviour != BEHAVIOUR_HEALTHY)
        return {
            "healthy": not failing,
            "detail": ("Simulated exchange: invented data, never a real brokerage."
                       + (f" Declared faults on: {', '.join(failing)}." if failing else "")),
            "faults": {name: self.behaviours[name].behaviour for name in failing},
        }

    # --- the data behind it ---------------------------------------------------

    def _fixture_holdings(self, source) -> list:
        """The positions this account really holds, before any fault is applied.

        Private, and reusing `SIMULATED_PORTFOLIOS` rather than inventing a
        second set: two descriptions of one imaginary client is what §101 refused
        for the demo, and the one that drifts is the one nobody is looking at."""
        provider = portfolio_providers.SimulatedPortfolioProvider()
        return provider.get_holdings(source)

    def truth_for(self, source) -> list:
        """What the account *holds*, regardless of what it returned.

        **Ground truth, and it is the reason a simulated client can grade.** A
        real client cannot tell you whether a report about their portfolio is
        correct; a simulated one can, because the exercise knows what it gave
        them. §115 makes the client's satisfaction the grading signal, and this
        is what lets a simulated client have an informed opinion rather than a
        random one.

        Not part of the provider interface, and deliberately not reachable
        through it: an analyst that could ask an exchange what it *really* holds
        would be an analyst that never has to notice a partial answer."""
        return self._fixture_holdings(source)
