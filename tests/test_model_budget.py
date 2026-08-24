"""The cost circuit breaker (app/model_budget.py, addendum 28 §19.3, TQ-10).

Every test redirects the ledger to a temporary file; nothing here touches the
real model_spend.db, and no test constructs a real Anthropic client.
"""

from types import SimpleNamespace

import pytest

from app import model_budget
from app.model_budget import BudgetedProvider, BudgetExceededError


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv(model_budget.PATH_ENV, str(tmp_path / "spend.db"))
    monkeypatch.delenv(model_budget.TOKENS_ENV, raising=False)
    monkeypatch.delenv(model_budget.CALLS_ENV, raising=False)


class FakeInner:
    """A ModelProvider stand-in that reports usage the way the SDK does and
    counts how often it was actually touched."""

    def __init__(self, input_tokens=100, output_tokens=50, report_usage=True):
        self.calls = 0
        self._usage = (
            SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
            if report_usage else None
        )

    def complete(self, system, messages, tools, max_tokens=2048):
        self.calls += 1
        return SimpleNamespace(usage=self._usage, content=[], stop_reason="end_turn")

    def stream(self, system, messages, tools, max_tokens=2048):
        self.calls += 1
        yield {"type": "text", "text": "hello"}
        usage = None
        if self._usage is not None:
            usage = {"input_tokens": self._usage.input_tokens, "output_tokens": self._usage.output_tokens}
        yield {"type": "final", "content": [], "stop_reason": "end_turn", "usage": usage}


def test_complete_records_reported_usage_in_the_ledger():
    provider = BudgetedProvider(FakeInner(input_tokens=120, output_tokens=30))
    provider.complete("sys", [], [])
    provider.complete("sys", [], [])

    spend = model_budget.todays_spend()
    assert spend["calls"] == 2
    assert spend["input_tokens"] == 240
    assert spend["output_tokens"] == 60
    assert spend["refusals"] == 0


def test_call_limit_refuses_without_touching_the_inner_provider(monkeypatch):
    monkeypatch.setenv(model_budget.CALLS_ENV, "2")
    inner = FakeInner()
    provider = BudgetedProvider(inner)
    provider.complete("sys", [], [])
    provider.complete("sys", [], [])

    with pytest.raises(BudgetExceededError, match=model_budget.CALLS_ENV):
        provider.complete("sys", [], [])

    assert inner.calls == 2  # the refused call never reached the vendor
    assert model_budget.todays_spend()["refusals"] == 1


def test_token_limit_refuses_the_call_after_the_crossing(monkeypatch):
    """Post-hoc accounting: the call that crosses the limit completes (its cost
    is only known from its response), and the next one is refused. Damage is
    bounded to the limit plus one reply - the documented contract."""
    monkeypatch.setenv(model_budget.TOKENS_ENV, "100")
    provider = BudgetedProvider(FakeInner(input_tokens=90, output_tokens=20))
    provider.complete("sys", [], [])  # 110 recorded, limit 100

    with pytest.raises(BudgetExceededError, match=model_budget.TOKENS_ENV):
        provider.complete("sys", [], [])


def test_unreported_usage_counts_the_call_and_records_zero_tokens():
    provider = BudgetedProvider(FakeInner(report_usage=False))
    provider.complete("sys", [], [])

    spend = model_budget.todays_spend()
    assert spend["calls"] == 1
    assert spend["input_tokens"] == 0 and spend["output_tokens"] == 0


def test_stream_passes_events_through_and_records_final_usage():
    provider = BudgetedProvider(FakeInner(input_tokens=70, output_tokens=40))
    events = list(provider.stream("sys", [], []))

    assert [e["type"] for e in events] == ["text", "final"]
    spend = model_budget.todays_spend()
    assert spend["calls"] == 1
    assert spend["input_tokens"] == 70 and spend["output_tokens"] == 40


def test_an_abandoned_stream_still_counts_as_a_call():
    """The spend happened whether or not the caller finished reading it."""
    provider = BudgetedProvider(FakeInner())
    stream = provider.stream("sys", [], [])
    next(stream)  # read one fragment, then walk away
    stream.close()

    spend = model_budget.todays_spend()
    assert spend["calls"] == 1
    assert spend["input_tokens"] == 0  # never saw the final event: unreported, not guessed


def test_the_ledger_is_shared_across_provider_instances(monkeypatch):
    """The point of the file: separate processes (here, separate wrappers)
    spend against one budget, not one each."""
    monkeypatch.setenv(model_budget.CALLS_ENV, "2")
    first = BudgetedProvider(FakeInner())
    second = BudgetedProvider(FakeInner())
    first.complete("sys", [], [])
    second.complete("sys", [], [])

    with pytest.raises(BudgetExceededError):
        first.complete("sys", [], [])


def test_a_new_day_resets_the_window(monkeypatch):
    monkeypatch.setenv(model_budget.CALLS_ENV, "1")
    provider = BudgetedProvider(FakeInner())
    monkeypatch.setattr(model_budget, "_today", lambda: "2026-08-24")
    provider.complete("sys", [], [])
    with pytest.raises(BudgetExceededError):
        provider.complete("sys", [], [])

    monkeypatch.setattr(model_budget, "_today", lambda: "2026-08-25")
    provider.complete("sys", [], [])  # yesterday's exhaustion does not carry over


def test_a_malformed_limit_is_an_error_not_a_silent_default(monkeypatch):
    """A typo'd limit must not quietly become the default (or worse, no
    limit). Refusing to guess is the same contract the ledger keeps."""
    monkeypatch.setenv(model_budget.TOKENS_ENV, "five hundred thousand")
    provider = BudgetedProvider(FakeInner())
    with pytest.raises(ValueError, match=model_budget.TOKENS_ENV):
        provider.complete("sys", [], [])


def test_refusal_message_carries_numbers_and_remedy(monkeypatch):
    monkeypatch.setenv(model_budget.CALLS_ENV, "1")
    provider = BudgetedProvider(FakeInner())
    provider.complete("sys", [], [])

    with pytest.raises(BudgetExceededError) as excinfo:
        provider.complete("sys", [], [])
    message = str(excinfo.value)
    assert "1 calls" in message and "limit 1" in message and model_budget.CALLS_ENV in message


def test_anthropic_provider_final_event_reports_usage_strictly():
    """The stream's final event carries usage as reported, and a mock or
    partial object degrades to None - 'not reported' - never to garbage in
    the ledger."""
    from unittest.mock import MagicMock

    from app.model_provider import AnthropicProvider

    from contextlib import contextmanager

    @contextmanager
    def fake_stream(**kwargs):
        final = MagicMock(content=[], stop_reason="end_turn")
        final.usage = SimpleNamespace(input_tokens=12, output_tokens=34)
        yield MagicMock(text_stream=iter([]), get_final_message=lambda: final)

    provider = AnthropicProvider(model="test-model")
    provider._client = MagicMock(messages=MagicMock(stream=fake_stream))
    final = list(provider.stream("sys", [], []))[-1]
    assert final["usage"] == {"input_tokens": 12, "output_tokens": 34}

    @contextmanager
    def mock_usage_stream(**kwargs):
        yield MagicMock(text_stream=iter([]), get_final_message=lambda: MagicMock(content=[], stop_reason="end_turn"))

    provider._client = MagicMock(messages=MagicMock(stream=mock_usage_stream))
    final = list(provider.stream("sys", [], []))[-1]
    assert final["usage"] == {"input_tokens": None, "output_tokens": None}
