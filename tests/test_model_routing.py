"""app/model_routing.py - the seven things Krish asked to be proven.

He listed them himself on 2026-09-16 from abroad, and they are the section
headings below:

    normal request -> local model
    local failure/capability escalation -> Kimi remote
    Kimi failure -> explicit failure, NOT Anthropic
    Anthropic cannot be accidentally selected by the runtime router
    missing KIMI_API_KEY does not cause Anthropic fallback
    secrets never appear in logs

The seventh - that the router is enforced in code rather than in a prompt - is
not a single test but the shape of the whole file: every assertion here is
against a constructed object, and the vendor check runs at construction so that
the failure arrives before a request does rather than after a bill.

One honest limit, stated here rather than left to be discovered. There is no
local model on this machine, so "normal request -> local model" is asserted
against a stand-in local provider. That is not a weaker test of the routing
rule - the rule is what is under test, and a stand-in exercises it exactly - but
it is a weaker statement about this deployment, where local is `None` today and
every request therefore escalates to remote with a reason saying why.
"""

import logging

import pytest

from app import kimi_provider, model_gateway, model_routing
from app.model_budget import BudgetExceededError
from app.model_routing import LocalFirstRouter, ModelRoutingFailure


class _Provider:
    """A provider that records what it was asked and answers predictably."""

    def __init__(self, name="stand-in", model="stand-in-model", fails=None):
        self.name = name
        self.model = model
        self.fails = fails
        self.calls = []

    def complete(self, system, messages, tools, max_tokens=2048):
        self.calls.append(("complete", max_tokens))
        if self.fails is not None:
            raise self.fails
        return f"{self.name} answered"

    def stream(self, system, messages, tools, max_tokens=2048):
        self.calls.append(("stream", max_tokens))
        if self.fails is not None:
            raise self.fails
        return iter([{"type": "final", "content": [], "stop_reason": "end_turn"}])


def _router(local=None, remote=None, available=True):
    return LocalFirstRouter(local=local, remote=remote, local_available=lambda: available)


# --- normal request -> local model ----------------------------------------------


def test_a_normal_request_goes_to_the_local_model():
    local, remote = _Provider("local"), _Provider("remote")
    router = _router(local=local, remote=remote)

    assert router.complete("sys", [], []) == "local answered"
    assert remote.calls == []
    assert router.counts["local"] == 1
    assert router.counts["remote"] == 0


def test_streaming_also_prefers_local():
    local, remote = _Provider("local"), _Provider("remote")
    router = _router(local=local, remote=remote)

    list(router.stream("sys", [], []))
    assert local.calls == [("stream", 2048)]
    assert remote.calls == []


def test_local_is_skipped_when_the_service_reports_itself_unavailable():
    local, remote = _Provider("local"), _Provider("remote")
    router = _router(local=local, remote=remote, available=False)

    assert router.complete("sys", [], []) == "remote answered"
    assert local.calls == []


def test_a_broken_availability_check_is_not_availability():
    """A local tier whose own health check raises has not shown it can serve a
    request, and treating the exception as a yes would call it anyway."""
    def explode():
        raise RuntimeError("the runtime socket is gone")

    router = LocalFirstRouter(local=_Provider("local"), remote=_Provider("remote"),
                              local_available=explode)
    assert router.complete("sys", [], []) == "remote answered"


# --- local failure / escalation -> Kimi remote ----------------------------------


def test_a_local_failure_escalates_to_the_remote_model():
    local = _Provider("local", fails=RuntimeError("context window exceeded"))
    remote = _Provider("remote")
    router = _router(local=local, remote=remote)

    assert router.complete("sys", [], []) == "remote answered"
    assert router.counts["escalated"] == 1
    assert router.counts["remote"] == 1


def test_the_escalation_reason_says_which_of_the_two_it_was(caplog):
    """"The local model could not cope" and "there is no local model installed"
    are different facts, and only one of them is worth acting on from another
    continent."""
    router = _router(local=None, remote=_Provider("remote"))
    with caplog.at_level(logging.INFO, logger="model.routing"):
        router.complete("sys", [], [])
    assert model_routing.LOCAL_NOT_OFFERED in caplog.text

    caplog.clear()
    failing = _Provider("local", fails=RuntimeError("out of memory"))
    router = _router(local=failing, remote=_Provider("remote"))
    with caplog.at_level(logging.INFO, logger="model.routing"):
        router.complete("sys", [], [])
    assert "out of memory" in caplog.text


def test_a_budget_refusal_is_not_escalated():
    """The ceiling exists to stop work, not to move it somewhere more
    expensive. Escalating here would make crossing the budget cost MORE than
    staying under it."""
    local = _Provider("local", fails=BudgetExceededError("daily token ceiling reached"))
    remote = _Provider("remote")
    router = _router(local=local, remote=remote)

    with pytest.raises(BudgetExceededError):
        router.complete("sys", [], [])
    assert remote.calls == []
    assert router.counts["escalated"] == 0


def test_the_log_line_carries_what_he_asked_to_see(caplog):
    router = _router(local=_Provider("local", model="qwen-stand-in"),
                     remote=_Provider("remote"))
    with caplog.at_level(logging.INFO, logger="model.routing"):
        router.complete("sys", [], [])
    assert "provider=local" in caplog.text
    assert "model=qwen-stand-in" in caplog.text
    assert "location=LOCAL" in caplog.text
    assert "latency_ms=" in caplog.text


# --- Kimi failure -> explicit failure, NOT Anthropic ----------------------------


def test_both_tiers_failing_is_an_explicit_routing_failure():
    local = _Provider("local", fails=RuntimeError("no runtime"))
    remote = _Provider("remote", fails=RuntimeError("502 from the endpoint"))
    router = _router(local=local, remote=remote)

    with pytest.raises(ModelRoutingFailure) as failed:
        router.complete("sys", [], [])
    message = str(failed.value)
    assert "502 from the endpoint" in message
    assert "no runtime" in message
    assert router.counts["failed"] == 1


def test_the_failure_names_both_preconditions_so_he_knows_which_to_act_on():
    router = _router(local=None, remote=None)
    with pytest.raises(ModelRoutingFailure) as failed:
        router.complete("sys", [], [])
    message = str(failed.value)
    assert model_routing.LOCAL_NOT_OFFERED in message
    assert kimi_provider.API_KEY_ENV in message or "wiring fault" in message


def test_a_streaming_request_with_nothing_to_serve_it_fails_rather_than_degrades():
    router = _router(local=None, remote=None)
    with pytest.raises(ModelRoutingFailure):
        router.stream("sys", [], [])


# --- Anthropic cannot be accidentally selected ----------------------------------


class _AnthropicLookalike:
    """A provider whose class name names the vendor. The check is on the name
    and the defining module, which is what makes it enforcement: a provider that
    talks to that vendor has to live somewhere, and both places are checked."""

    name = "sneaked-in"
    model = "claude-anything"

    def complete(self, *args, **kwargs):  # pragma: no cover - never reached
        raise AssertionError("this must never be called")

    def stream(self, *args, **kwargs):  # pragma: no cover - never reached
        raise AssertionError("this must never be called")


def test_the_router_refuses_to_be_built_with_that_vendor_as_the_local_tier():
    with pytest.raises(ModelRoutingFailure):
        LocalFirstRouter(local=_AnthropicLookalike(), remote=_Provider("remote"))


def test_the_router_refuses_to_be_built_with_that_vendor_as_the_remote_tier():
    with pytest.raises(ModelRoutingFailure):
        LocalFirstRouter(local=None, remote=_AnthropicLookalike())


def test_the_real_provider_class_is_refused_too():
    """The lookalike above proves the mechanism; this proves it is aimed at the
    class that actually exists in this repository."""
    from app.model_provider import AnthropicProvider

    with pytest.raises(ModelRoutingFailure):
        LocalFirstRouter(local=None, remote=AnthropicProvider())


def test_that_vendor_is_refused_however_deeply_it_is_wrapped():
    """A wrapper added around a provider is exactly how a vendor gets back in by
    accident, so the check walks the graph rather than looking at one object."""
    from app.model_budget import BudgetedProvider

    with pytest.raises(ModelRoutingFailure):
        model_routing.assert_no_anthropic(
            BudgetedProvider(BudgetedProvider(_AnthropicLookalike())))


def test_a_cycle_in_the_provider_graph_fails_a_check_rather_than_hanging():
    first = _Provider("a")
    second = _Provider("b")
    first.inner = second
    second.inner = first
    model_routing.assert_no_anthropic(first)  # returns rather than recursing forever


def test_the_process_wide_provider_has_no_path_to_that_vendor(monkeypatch):
    """The end-to-end form of the rule: whatever the environment says, the
    provider the whole system shares contains no such provider anywhere in it."""
    monkeypatch.setattr(model_gateway, "_provider", None)
    try:
        provider = model_gateway.default_provider()
        graph = model_routing._provider_graph(provider)
        assert graph, "the provider graph should contain at least the wrapper"
        for member in graph:
            origin = f"{type(member).__module__}.{type(member).__name__}".lower()
            assert "anthropic" not in origin, f"{origin} is in the runtime routing chain"
    finally:
        model_gateway.set_provider(None)


def test_the_runtime_counter_for_that_vendor_is_structurally_zero():
    router = _router(local=None, remote=_Provider("remote"))
    router.complete("sys", [], [])
    counts = model_routing.counters(router)
    assert counts["anthropic_runtime_requests"] == 0
    assert counts["kimi_remote_requests"] == 1
    assert "structurally zero" in counts["anthropic_runtime_note"]


def test_the_key_the_development_tooling_needs_is_named_rather_than_removed():
    """*"Do not delete credentials or configuration blindly if other development
    tooling needs them."* The runtime half is what this change makes
    unreachable; the tooling half is listed so nobody tidies it away."""
    consumers = model_routing.anthropic_key_consumers()
    assert consumers["development_and_test_tooling"]
    assert "development" in consumers["note"]


# --- missing KIMI_API_KEY does not cause a fallback -----------------------------


def test_no_credential_builds_a_router_with_no_remote_rather_than_another_vendor(monkeypatch):
    monkeypatch.delenv(kimi_provider.API_KEY_ENV, raising=False)
    router = model_routing.build_router()

    assert router.remote is None
    assert router.local is None
    with pytest.raises(ModelRoutingFailure) as failed:
        router.complete("sys", [], [])
    assert kimi_provider.API_KEY_ENV in str(failed.value)


def test_a_credential_builds_the_remote_tier_against_the_verified_model(monkeypatch):
    monkeypatch.setenv(kimi_provider.API_KEY_ENV, "not-a-real-key")
    monkeypatch.delenv(kimi_provider.MODEL_ENV, raising=False)
    router = model_routing.build_router()

    assert isinstance(router.remote, kimi_provider.KimiProvider)
    assert router.remote.model == "k3-256k"


def test_the_routing_order_is_reportable_without_reading_code(monkeypatch):
    """"Which vendor is this system using" has to be answerable from abroad,
    which is the position he was in when he sent the instruction."""
    monkeypatch.setenv(kimi_provider.API_KEY_ENV, "not-a-real-key")
    described = model_routing.build_router().describe()

    assert described["order"] == ["local", "remote", "explicit-failure"]
    assert described["local"]["configured"] is False
    assert described["remote"]["model"] == kimi_provider.configured_model()
    assert "not in the runtime routing chain" in described["anthropic"]


# --- secrets never appear in logs -----------------------------------------------


def test_the_routing_log_carries_no_credential_and_no_prompt(caplog, monkeypatch):
    """The prompt is the one part of a model call certain to contain something
    private, and the key is the one part certain to be a secret. Neither is in
    the line, and this asserts it against the real provider object rather than
    against a stand-in that has no key to leak."""
    secret = "sk-kimi-THIS-MUST-NOT-BE-LOGGED"
    monkeypatch.setenv(kimi_provider.API_KEY_ENV, secret)
    remote = kimi_provider.KimiProvider(
        transport=lambda *a: {"choices": [{"finish_reason": "stop",
                                           "message": {"content": "hello"}}]})
    router = _router(local=None, remote=remote)

    with caplog.at_level(logging.INFO, logger="model.routing"):
        router.complete("a private system prompt about his portfolio",
                        [{"role": "user", "content": "how much do I hold"}], [])

    assert secret not in caplog.text
    assert "portfolio" not in caplog.text
    assert "how much do I hold" not in caplog.text
    assert "provider=remote" in caplog.text


def test_a_failure_message_does_not_carry_the_credential(monkeypatch):
    secret = "sk-kimi-ALSO-NOT-IN-A-TRACEBACK"
    monkeypatch.setenv(kimi_provider.API_KEY_ENV, secret)
    remote = _Provider("remote", fails=kimi_provider.KimiCallFailed(
        "the remote model answered HTTP 401"))
    router = _router(local=None, remote=remote)

    with pytest.raises(ModelRoutingFailure) as failed:
        router.complete("sys", [], [])
    assert secret not in str(failed.value)
    assert "401" in str(failed.value)
