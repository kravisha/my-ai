"""The governor that keeps Anthropic use marginal (Krish, 2026-09-14).

The assertion that matters most here is the tool boundary. Everything else in
`app/model_tiering.py` is an optimisation whose worst failure is a mediocre
answer; routing a TOOL-BEARING request to a small model risks a confident call
with wrong arguments against the real system, which is an action rather than a
wobble. So that one is tested from several directions and the others once.
"""

import pytest

from app.model_budget import BudgetExceededError
from app.model_tiering import (
    DEFAULT_CAPABLE,
    DEFAULT_CHEAP,
    MODE_ENV,
    SIZE_LIMIT_ENV,
    TieredProvider,
    UnknownTierMode,
    capable_model,
    cheap_model,
    configured_mode,
    request_size,
    wants_capable,
)


class Recorder:
    """A provider that records what it was asked and can be told to fail."""

    def __init__(self, name, fail_with=None):
        self.name = name
        self.fail_with = fail_with
        self.calls = []

    def complete(self, system, messages, tools, max_tokens=2048):
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        if self.fail_with is not None:
            raise self.fail_with
        return f"{self.name}-reply"

    def stream(self, system, messages, tools, max_tokens=2048):
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        if self.fail_with is not None:
            raise self.fail_with
        return iter([{"type": "text", "text": f"{self.name}-chunk"}])


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (MODE_ENV, SIZE_LIMIT_ENV, "MODEL_CHEAP", "MODEL_CAPABLE"):
        monkeypatch.delenv(name, raising=False)


def tiered(**kwargs):
    return TieredProvider(Recorder("cheap"), Recorder("capable"), **kwargs)


# --- the tool boundary, which is the correctness guard -----------------------


def test_a_request_carrying_tools_always_goes_to_the_capable_model():
    provider = tiered()
    provider.complete("short system", [{"role": "user", "content": "hi"}],
                      [{"name": "delete_everything"}])
    assert provider.capable.calls, "a tool-bearing request must reach the capable model"
    assert not provider.cheap.calls, (
        "a small model emitting a plausible tool call with wrong arguments is an "
        "action against the real system, not a quality wobble")


def test_the_tool_boundary_beats_a_tiny_request():
    """Size would route this to the cheap model. Tools must override that."""
    assert wants_capable("", [], [{"name": "anything"}], mode="auto") is True
    assert wants_capable("", [], [], mode="auto") is False


def test_the_tool_boundary_holds_even_in_cheap_mode_is_false_and_that_is_deliberate():
    """`cheap` is an operator forcing frugality with their eyes open.

    Documented rather than silently true: in forced-cheap mode the operator has
    overridden the router entirely, and the escape hatch would be worthless if
    it quietly declined to apply."""
    assert wants_capable("", [], [{"name": "t"}], mode="cheap") is False


# --- the size proxy ----------------------------------------------------------


def test_a_small_toolless_request_goes_to_the_cheap_model():
    provider = tiered()
    provider.complete("system", [{"role": "user", "content": "what time is it"}], [])
    assert provider.cheap.calls
    assert not provider.capable.calls


def test_a_large_request_goes_to_the_capable_model(monkeypatch):
    monkeypatch.setenv(SIZE_LIMIT_ENV, "100")
    provider = tiered()
    provider.complete("x" * 500, [{"role": "user", "content": "y" * 500}], [])
    assert provider.capable.calls
    assert not provider.cheap.calls


def test_request_size_counts_structured_content_blocks():
    """Anthropic content is often a list of blocks, not a string.

    Counting only `str` content would report a long conversation as tiny and
    route it to the cheap model - a silent under-count, which is the failure
    shape that has bitten this project repeatedly."""
    size = request_size("abc", [{"role": "user", "content": [{"type": "text", "text": "12345"}]}])
    assert size == 8


# --- escalation --------------------------------------------------------------


def test_a_cheap_failure_escalates_once_to_the_capable_model():
    provider = TieredProvider(Recorder("cheap", fail_with=RuntimeError("overloaded")),
                              Recorder("capable"))
    assert provider.complete("s", [{"role": "user", "content": "hi"}], []) == "capable-reply"
    assert provider.counts["escalated"] == 1


def test_a_capable_failure_is_not_retried():
    provider = TieredProvider(Recorder("cheap"),
                              Recorder("capable", fail_with=RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        provider.complete("s", [], [{"name": "t"}])


def test_a_budget_refusal_stops_work_rather_than_escalating():
    """The ceiling must not make crossing it cost more than staying under it."""
    cheap = Recorder("cheap", fail_with=BudgetExceededError("daily limit reached"))
    provider = TieredProvider(cheap, Recorder("capable"))
    with pytest.raises(BudgetExceededError):
        provider.complete("s", [{"role": "user", "content": "hi"}], [])
    assert not provider.capable.calls, (
        "escalating past the budget ceiling would spend MORE once the limit is hit")
    assert provider.counts["escalated"] == 0


def test_streaming_never_escalates():
    """Two models spliced into one stream would show the user a seam."""
    provider = tiered()
    provider.stream("s", [{"role": "user", "content": "hi"}], [])
    assert provider.cheap.calls and not provider.capable.calls


# --- configuration -----------------------------------------------------------


def test_capable_mode_restores_the_old_behaviour(monkeypatch):
    """The escape hatch Krish can use from abroad without a code change."""
    monkeypatch.setenv(MODE_ENV, "capable")
    provider = tiered()
    provider.complete("s", [{"role": "user", "content": "hi"}], [])
    assert provider.capable.calls and not provider.cheap.calls


def test_a_mistyped_mode_fails_loudly_at_construction(monkeypatch):
    monkeypatch.setenv(MODE_ENV, "cheep")
    with pytest.raises(UnknownTierMode):
        configured_mode()
    with pytest.raises(UnknownTierMode):
        TieredProvider(Recorder("cheap"), Recorder("capable"))


def test_the_default_cheap_model_is_actually_the_small_one():
    """Guards the whole point of the directive.

    If someone sets MODEL_CHEAP to the large model the router still 'works' and
    saves nothing, so the default is asserted rather than assumed."""
    assert cheap_model() == DEFAULT_CHEAP
    assert capable_model() == DEFAULT_CAPABLE
    assert cheap_model() != capable_model()


def test_a_nonsense_size_limit_is_refused(monkeypatch):
    monkeypatch.setenv(SIZE_LIMIT_ENV, "not-a-number")
    with pytest.raises(ValueError):
        from app.model_tiering import size_limit

        size_limit()
