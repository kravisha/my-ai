"""The router's decision, case by case (Task 01 §7).

Five decisions are named in the acceptance criteria and all five are here:
local sufficient, low confidence, tool required, context overflow, quota error.
The sixth section is §4.2's quota handling, which is the one with a user-facing
guarantee attached to it.
"""

import json
import logging

import pytest

from app import confidence, model_calls, model_routing, retry_queue, router_config
from app.model_routing import LocalFirstRouter, ModelRoutingFailure, ModelUnavailableNow


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(model_calls.LOG_DIR_ENV, str(tmp_path / "logs"))
    confidence.register(None)
    yield tmp_path / "logs"
    confidence.register(None)


def _records(directory):
    path = directory / model_calls.LOG_FILE_NAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


class _Usage:
    def __init__(self, input_tokens=5, output_tokens=6):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _Answer:
    def __init__(self, text):
        self.text = text
        self.usage = _Usage()


class _Provider:
    """A tier that answers, or fails in a stated way."""

    def __init__(self, name="stand-in", model="stand-in-model", fails=None, **declared):
        self.name = name
        self.model = model
        self.fails = fails
        self.calls = []
        for attribute, value in declared.items():
            setattr(self, attribute, value)

    def complete(self, system, messages, tools, max_tokens=2048):
        self.calls.append(("complete", tools))
        if self.fails is not None:
            raise self.fails
        return _Answer(f"{self.name} answered")

    def stream(self, system, messages, tools, max_tokens=2048):
        self.calls.append(("stream", tools))
        if self.fails is not None:
            raise self.fails
        return iter([{"type": "final", "content": [], "stop_reason": "end_turn",
                      "usage": {"input_tokens": 1, "output_tokens": 2}}])


class _QuotaSpent(RuntimeError):
    """What KimiProvider raises when the remote model has nothing left."""

    model_call_outcome = "quota_exhausted"
    user_message_category = "capacity"


def _router(local=None, remote=None, available=True):
    """A router whose remote tier records itself, as the real one does.

    `KimiProvider` records inside its own `complete`/`stream` - below the
    transport seam - so a stand-in has to be wrapped to produce the same log.
    The local tier needs no wrapping here: `LocalFirstRouter.__init__` wraps
    whatever it is given, which is what guarantees a local provider is
    instrumented on the first call it ever serves."""
    if remote is not None:
        remote = model_calls.InstrumentedProvider(remote, model_calls.HANDLER_KIMI)
    return LocalFirstRouter(local=local, remote=remote, local_available=lambda: available)


# --- 1. local sufficient ---------------------------------------------------------


def test_a_sufficient_local_answer_is_returned_and_nothing_is_escalated(_isolated):
    local, remote = _Provider("local"), _Provider("remote")
    router = _router(local=local, remote=remote)

    answer = router.complete("sys", [], [])

    assert answer.text == "local answered"
    assert remote.calls == []
    assert router.counts["escalated"] == 0
    assert [r["handler"] for r in _records(_isolated)] == ["local"]


def test_local_first_holds_even_when_the_request_carries_tools(_isolated):
    """The clause that made the bill what it was, inverted. `TieredProvider`
    sent every tool-carrying request to the expensive tier; here a local model
    that has not said it cannot use tools gets the request."""
    local, remote = _Provider("local"), _Provider("remote")
    router = _router(local=local, remote=remote)

    router.complete("sys", [], [{"name": "read_scoreboard"}])

    assert local.calls and remote.calls == []


# --- 2. low confidence ------------------------------------------------------------


def test_a_low_confidence_local_answer_escalates_with_that_reason(_isolated):
    local, remote = _Provider("local"), _Provider("remote")
    confidence.register(lambda **_: 0.10, "test-scorer")
    router = _router(local=local, remote=remote)

    answer = router.complete("sys", [], [])

    assert answer.text == "remote answered"
    assert local.calls, "local is attempted first - escalation happens after, not instead"
    escalated = [r for r in _records(_isolated) if r["handler"] == "kimi_k2"]
    assert escalated[0]["escalation_reason"] == "low_confidence"
    assert escalated[0]["confidence_score"] == 0.10
    assert escalated[0]["confidence_threshold"] == router_config.confidence_threshold()


def test_a_confident_local_answer_is_kept(_isolated):
    local, remote = _Provider("local"), _Provider("remote")
    confidence.register(lambda **_: 0.99, "test-scorer")
    router = _router(local=local, remote=remote)

    assert router.complete("sys", [], []).text == "local answered"
    assert remote.calls == []


def test_a_broken_scorer_keeps_the_local_answer_rather_than_escalating(_isolated):
    """A scorer that throws must not become an escalation policy - it would
    send every request to the paid API and look like the local model degrading."""
    local, remote = _Provider("local"), _Provider("remote")

    def broken(**_):
        raise RuntimeError("the scorer is down")

    confidence.register(broken, "broken-scorer")
    router = _router(local=local, remote=remote)

    assert router.complete("sys", [], []).text == "local answered"
    assert remote.calls == []


def test_the_threshold_comes_from_the_file_and_not_from_the_code(tmp_path, monkeypatch):
    """§7: "Router threshold is read from config, not hard-coded.\""""
    policy = tmp_path / "router.yaml"
    policy.write_text("router:\n  confidence_threshold: 0.9\n", encoding="utf-8")
    monkeypatch.setenv(router_config.PATH_ENV, str(policy))

    assert router_config.confidence_threshold() == 0.9

    local, remote = _Provider("local"), _Provider("remote")
    confidence.register(lambda **_: 0.8, "test-scorer")
    router = _router(local=local, remote=remote)

    # 0.8 clears the shipped 0.65 and fails the configured 0.9. If the
    # threshold were hard-coded this would return the local answer.
    assert router.complete("sys", [], []).text == "remote answered"


# --- 3. tool required --------------------------------------------------------------


def test_a_local_tier_that_declares_it_cannot_use_tools_escalates(_isolated):
    local = _Provider("local", supports_tools=False)
    remote = _Provider("remote")
    router = _router(local=local, remote=remote)

    answer = router.complete("sys", [], [{"name": "read_scoreboard"}])

    assert answer.text == "remote answered"
    assert local.calls == [], "a declared incapacity skips the attempt"
    escalated = [r for r in _records(_isolated) if r["handler"] == "kimi_k2"]
    assert escalated[0]["escalation_reason"] == "tool_required"


def test_a_local_tier_that_says_nothing_about_tools_still_gets_the_request(_isolated):
    """An absent attribute is not a claim. Inferring one would turn "we do not
    know" into "do not try", which is how local-first quietly stops happening."""
    local, remote = _Provider("local"), _Provider("remote")
    router = _router(local=local, remote=remote)

    router.complete("sys", [], [{"name": "read_scoreboard"}])

    assert local.calls and remote.calls == []


# --- 4. context overflow -------------------------------------------------------------


def test_a_request_longer_than_the_declared_window_escalates(_isolated):
    local = _Provider("local", context_window=128)
    remote = _Provider("remote")
    router = _router(local=local, remote=remote)

    answer = router.complete("sys", [{"role": "user", "content": "x" * 20_000}], [])

    assert answer.text == "remote answered"
    assert local.calls == []
    escalated = [r for r in _records(_isolated) if r["handler"] == "kimi_k2"]
    assert escalated[0]["escalation_reason"] == "context_length"


def test_a_request_that_fits_the_declared_window_stays_local(_isolated):
    local = _Provider("local", context_window=8192)
    remote = _Provider("remote")
    router = _router(local=local, remote=remote)

    router.complete("sys", [{"role": "user", "content": "short"}], [], max_tokens=64)

    assert local.calls and remote.calls == []


# --- 5. local error ---------------------------------------------------------------


def test_a_local_failure_escalates_and_is_recorded_as_a_fallback(_isolated):
    local = _Provider("local", fails=RuntimeError("out of memory"))
    remote = _Provider("remote")
    router = _router(local=local, remote=remote)

    assert router.complete("sys", [], []).text == "remote answered"
    escalated = [r for r in _records(_isolated) if r["handler"] == "kimi_k2"]
    assert escalated[0]["routed_by"] == "fallback_after_error"
    assert escalated[0]["escalation_reason"] == "local_error"


# --- 6. quota exhaustion (§4.2) -----------------------------------------------------


def test_exhausted_capacity_falls_back_to_the_local_attempt(_isolated):
    """§4.2.2. An answer judged imperfect beats no answer, and the judgement
    that sent it upstream does not make it worthless."""
    local, remote = _Provider("local"), _Provider("remote", fails=_QuotaSpent("spent"))
    confidence.register(lambda **_: 0.1, "test-scorer")
    router = _router(local=local, remote=remote)

    answer = router.complete("sys", [], [])

    assert answer.text == "local answered"
    assert router.counts["quota_exhausted"] == 1


def test_exhausted_capacity_with_no_local_answer_queues_a_retry(_isolated):
    """§4.2.3, both halves: the request is written down, and the refusal is
    one the user can be told."""
    remote = _Provider("remote", fails=_QuotaSpent("spent"))
    router = _router(local=None, remote=remote)

    with model_calls.request_context("what do I hold?"):
        with pytest.raises(ModelUnavailableNow):
            router.complete("sys", [], [])

    assert router.counts["queued_retries"] == 1
    queued = retry_queue.entries()
    assert len(queued) == 1
    assert queued[0]["status"] == "queued"
    assert queued[0]["request_summary"] is None or "hold" in queued[0]["request_summary"]


def test_exhausted_capacity_is_logged_at_warning_not_shown(_isolated, caplog):
    """§4.2.4. WARN rather than ERROR: nothing is broken, and a page for a spent
    allowance trains somebody to ignore the pager."""
    remote = _Provider("remote", fails=_QuotaSpent("spent"))
    router = _router(local=None, remote=remote)

    with caplog.at_level(logging.WARNING, logger="model.routing"):
        with pytest.raises(ModelUnavailableNow):
            router.complete("sys", [], [])

    assert caplog.records
    assert caplog.records[0].levelno == logging.WARNING
    assert "exhausted capacity" in caplog.text


def test_the_refusal_the_user_would_see_says_nothing_about_the_accounting(_isolated):
    from app import user_messages

    remote = _Provider("remote", fails=_QuotaSpent("spent"))
    router = _router(local=None, remote=remote)

    with pytest.raises(ModelUnavailableNow) as raised:
        router.complete("sys", [], [])

    spoken = user_messages.for_user(raised.value)
    assert spoken == "I can't do that reliably right now - I'll retry shortly."
    assert user_messages.is_clean(spoken)
    assert user_messages.should_retry(raised.value)


def test_a_streamed_quota_refusal_is_caught_while_the_stream_is_consumed(_isolated):
    """The remote provider's stream raises during iteration, not at the call,
    so the guard has to be there rather than around the choice."""
    class _QuotaStream(_Provider):
        def stream(self, system, messages, tools, max_tokens=2048):
            def events():
                raise _QuotaSpent("spent")
                yield  # pragma: no cover - unreachable, keeps this a generator
            return events()

    router = _router(local=None, remote=_QuotaStream("remote"))

    with pytest.raises(ModelUnavailableNow):
        list(router.stream("sys", [], []))

    assert router.counts["queued_retries"] == 1


def test_an_ordinary_remote_failure_is_still_an_explicit_routing_failure(_isolated):
    remote = _Provider("remote", fails=RuntimeError("upstream refused"))
    router = _router(local=None, remote=remote)

    with pytest.raises(ModelRoutingFailure) as raised:
        router.complete("sys", [], [])
    assert not isinstance(raised.value, ModelUnavailableNow)
    assert router.counts["failed"] == 1


def test_a_queued_request_is_not_retried_before_its_wait_elapses(_isolated):
    remote = _Provider("remote", fails=_QuotaSpent("spent"))
    router = _router(local=None, remote=remote)
    with pytest.raises(ModelUnavailableNow):
        router.complete("sys", [], [])

    assert retry_queue.due() == [], "the whole point of a delay is that it delays"


# --- the counters Krish reads ---------------------------------------------------


def test_the_counters_report_the_quota_events_and_the_queue(_isolated):
    remote = _Provider("remote", fails=_QuotaSpent("spent"))
    router = _router(local=None, remote=remote)
    with pytest.raises(ModelUnavailableNow):
        router.complete("sys", [], [])

    counters = model_routing.counters(router)
    assert counters["quota_exhaustions"] == 1
    assert counters["queued_retries"] == 1
    assert counters["anthropic_runtime_requests"] == 0


def test_describe_names_the_confidence_mechanism_and_the_policy_file(_isolated):
    described = _router().describe()
    assert described["confidence"]["mechanism"] == "none"
    assert described["confidence"]["implemented"] is False
    assert described["policy"]["config"]["router"]["confidence_threshold"] == \
        router_config.confidence_threshold()
