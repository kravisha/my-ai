"""A fault that makes an agent slow rather than dead (TQ-94;
docs/SPEC_RECONCILIATION.md §135, §136).

`simulation/faults.py` can kill a process, stop it, or lock its database. All
three produce a **dead** agent, and the condition this organization has actually
been getting wrong is a live one: an agent inside a slow model call, alive and not
advancing, which COO twice mistook for a crash.

The first fully green verification did not exercise the fix for it, because
nothing happened to be slow that day (§135). **A green run over a condition that
never happened is not evidence about the condition**, so the condition has to be
producible on demand.
"""

from __future__ import annotations

import os
import time

import pytest

from app import model_gateway
from backend import fi_db, status_events
from simulation import metrics, scenario as scenario_module


class _Inner:
    """A provider that answers instantly, so any delay measured is the fault's."""

    def __init__(self):
        self.calls = 0

    def complete(self, system, messages, tools, max_tokens=2048):
        self.calls += 1
        return "answered"

    def stream(self, system, messages, tools, max_tokens=2048):
        self.calls += 1
        return "streamed"


# --- the fault is inert unless asked for ---------------------------------------------

def test_no_configuration_means_no_wrapper(monkeypatch):
    """A fault seam in production code that could fire without being asked would
    be a defect, not a fixture."""
    monkeypatch.delenv(model_gateway.FAULT_DELAY_ENV, raising=False)
    assert model_gateway._fault_delay() is None


def test_an_unreadable_delay_is_refused_rather_than_ignored(monkeypatch):
    """A typo in a scenario's config would otherwise produce a run that looks
    like it exercised the fault and did not — which is the failure this whole
    entry is about, arriving through its own front door."""
    monkeypatch.setenv(model_gateway.FAULT_DELAY_ENV, "soon")
    with pytest.raises(ValueError) as refusal:
        model_gateway._fault_delay()
    assert "not a number of seconds" in str(refusal.value)


@pytest.mark.parametrize("seconds,calls", [("0", "1"), ("5", "0"), ("-1", "1")])
def test_a_delay_that_could_not_stall_anything_is_refused(monkeypatch, seconds, calls):
    monkeypatch.setenv(model_gateway.FAULT_DELAY_ENV, seconds)
    monkeypatch.setenv(model_gateway.FAULT_DELAY_CALLS_ENV, calls)
    with pytest.raises(ValueError):
        model_gateway._fault_delay()


# --- what it does when it is asked for -----------------------------------------------

def test_it_stalls_the_first_call_and_not_the_rest():
    """The first N calls, not every call. A provider that stalled forever would
    starve the pipeline and fail every property about work getting done, and a
    run in which everything went red proves nothing about which mechanism
    broke."""
    inner = _Inner()
    provider = model_gateway.SlowProvider(inner, 0.3, calls=1)

    started = time.monotonic()
    provider.complete("", [], [])
    first = time.monotonic() - started

    started = time.monotonic()
    provider.complete("", [], [])
    second = time.monotonic() - started

    # Measured as a relationship with a loose floor, not against the exact
    # requested duration: Windows' timer granularity is ~15ms and `time.sleep`
    # can return a hair early, so `first >= 0.3` is a test of the clock rather
    # than of the fault.
    assert first >= 0.2
    assert second < 0.1
    assert first > second * 3
    assert inner.calls == 2, "the inner provider still answered both times"


def test_the_stall_does_not_change_what_comes_back():
    """Same decorator shape as `BudgetedProvider`: the interface in between is
    unchanged, so nothing downstream can tell a stalled call from a genuinely
    slow vendor — which is the point."""
    provider = model_gateway.SlowProvider(_Inner(), 0.01, calls=1)
    assert provider.complete("", [], []) == "answered"
    assert provider.stream("", [], []) == "streamed"


def test_the_fault_sits_outside_the_budget_wrapper():
    """A stalled call still counts against spend exactly as a slow real one
    would. Inside would make the fault invisible to the ledger and the run
    cheaper than what it simulates."""
    import inspect
    source = inspect.getsource(model_gateway.default_provider)
    assert source.index("BudgetedProvider(") < source.index("SlowProvider(")


# --- the episode is visible to a scenario --------------------------------------------

def test_slow_episodes_are_counted_from_what_coo_said(conn):
    """A scenario cannot assert on a condition it cannot see. §135's green run
    passed `no agent was respawned` without the condition ever arising, which is
    consistent with the fix working and with nothing having happened."""
    status_events.publish(conn, "agent_slow", "analysis-1 is alive and not advancing.",
                          severity=status_events.SEVERITY_WARNING, agent="analysis-1")
    status_events.publish(conn, "agent_slow", "analysis-1 is advancing again.",
                          severity=status_events.SEVERITY_INFO, agent="analysis-1")

    population = metrics.collect_from(conn)["population"]
    assert population["slow_reported"] == 1
    assert population["slow_recovered"] == 1


def test_a_stall_with_no_recovery_is_a_different_reading(conn):
    """An organization that noticed a stall and never noticed it ending would
    leave a permanent warning, which is its own kind of wrong. The two counts
    have to move independently or a scenario cannot tell them apart."""
    status_events.publish(conn, "agent_slow", "analysis-1 is alive and not advancing.",
                          severity=status_events.SEVERITY_WARNING, agent="analysis-1")
    population = metrics.collect_from(conn)["population"]
    assert population["slow_reported"] == 1 and population["slow_recovered"] == 0


# --- the scenario says what it is for -------------------------------------------------

def test_the_scenario_produces_the_condition_it_asserts_on():
    """The two halves that stop this being another vacuous green: it asserts no
    respawn AND that an agent was actually reported slow."""
    scenario = scenario_module.load("simulation/scenarios/slow_agent.yaml")
    metrics_asserted = {p["metric"] for p in scenario.expected_properties}

    assert "population.respawns" in metrics_asserted, "the thing that used to fail"
    assert "population.slow_reported" in metrics_asserted, "and that it could have"
    assert "population.slow_recovered" in metrics_asserted
    assert scenario.config[model_gateway.FAULT_DELAY_ENV], "it has to inject the stall"


def test_the_stall_is_longer_than_the_threshold_it_has_to_cross():
    """A 46-second stall against a 45-second threshold would be a test of the
    clock's precision instead of the organization's judgement."""
    from agents import coo
    scenario = scenario_module.load("simulation/scenarios/slow_agent.yaml")
    stall = float(scenario.config[model_gateway.FAULT_DELAY_ENV])
    assert stall >= coo.HEALTH_STALE_THRESHOLD_SECONDS * 1.5


def test_the_run_is_long_enough_to_contain_the_whole_episode():
    """A shorter run would end mid-stall and assert on half of it — the recovery
    half would never happen and the property would fail for the wrong reason."""
    scenario = scenario_module.load("simulation/scenarios/slow_agent.yaml")
    stall = float(scenario.config[model_gateway.FAULT_DELAY_ENV])
    assert scenario.duration_seconds >= stall * 2


def test_the_provider_is_actually_wrapped_when_the_fault_is_configured(monkeypatch):
    """Mutation testing caught this hole: disabling the branch that applies
    `SlowProvider` changed nothing, because the only test looking at it read the
    *source* and the source still mentioned the class.

    **A seam asserted by reading code is not a seam that runs.** Same finding as
    §132 and §134, and the third time it has been the surviving mutation."""
    monkeypatch.setenv(model_gateway.FAULT_DELAY_ENV, "0.01")
    monkeypatch.setenv(model_gateway.FAULT_DELAY_CALLS_ENV, "1")
    monkeypatch.setattr(model_gateway, "_provider", None)

    provider = model_gateway.default_provider()
    try:
        assert isinstance(provider, model_gateway.SlowProvider)
        # And the budget still sees the call, so a stalled run costs what it
        # simulates.
        from app.model_budget import BudgetedProvider
        assert isinstance(provider.inner, BudgetedProvider)
    finally:
        model_gateway.set_provider(None)


def test_no_fault_configured_leaves_the_provider_unwrapped(monkeypatch):
    """The other half. A fault seam that fired without being asked would be a
    defect, not a fixture — and this is what says so about the wiring rather than
    about the parser."""
    monkeypatch.delenv(model_gateway.FAULT_DELAY_ENV, raising=False)
    monkeypatch.setattr(model_gateway, "_provider", None)

    provider = model_gateway.default_provider()
    try:
        assert not isinstance(provider, model_gateway.SlowProvider)
    finally:
        model_gateway.set_provider(None)
