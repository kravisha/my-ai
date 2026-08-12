"""Regression tests for main.chat_turn using a fake Anthropic response, so no
real model call is made. Covers the scaffolding-level guarantees behind the
two real bugs found during Milestone 2 verification:

1. chat_turn must never answer a portfolio question from a cached tool
   result - it re-invokes the model (and, when the model calls the tool,
   re-invokes execute_tool) on every single chat_turn call, so a permission
   change between turns is always picked up. (The instruction to actually
   call the tool every time is the model's job, enforced via the system
   prompt - not testable here - but the mechanical guarantee that chat_turn
   never short-circuits a tool call itself IS testable, and is what these
   tests lock in.)
2. The tool's exact `error` text (which differs between the two denial
   kinds) must reach the model unmodified, with is_error set - chat_turn
   must not collapse or rewrite it.
"""

import json
from unittest.mock import MagicMock

from app.main import chat_turn
from app.tools.portfolio import FORWARDING_KEY


class FakeBlock:
    def __init__(self, type, text=None, name=None, id=None):
        self.type = type
        self.text = text
        self.name = name
        self.id = id


class FakeResponse:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


def text_response(text):
    return FakeResponse("end_turn", [FakeBlock("text", text=text)])


def tool_use_response(tool_name="retrieve_portfolio", tool_id="tool_1"):
    return FakeResponse("tool_use", [FakeBlock("tool_use", name=tool_name, id=tool_id)])


def _extract_tool_results(messages):
    """Pulls out every tool_result block appended to the conversation."""
    results = []
    for msg in messages:
        if msg["role"] == "user" and isinstance(msg["content"], list):
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    results.append(block)
    return results


def test_simple_text_reply_prints_and_returns(monkeypatch, capsys, permissions_store, preferences_store):
    monkeypatch.setattr("app.main.call_reasoning_model", MagicMock(return_value=text_response("Hello!")))

    chat_turn("hi", [], permissions_store, preferences_store)

    assert "Hello!" in capsys.readouterr().out


def test_tool_use_with_stored_disposition_reaches_model_without_reprompt(
    monkeypatch, permissions_store, preferences_store, mock_portfolio_path,
):
    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "always")

    call_model = MagicMock(side_effect=[tool_use_response(), text_response("Here are your holdings.")])
    monkeypatch.setattr("app.main.call_reasoning_model", call_model)

    messages = []
    chat_turn("What stocks do I own?", messages, permissions_store, preferences_store)

    assert call_model.call_count == 2
    tool_results = _extract_tool_results(messages)
    assert len(tool_results) == 1
    payload = json.loads(tool_results[0]["content"])
    assert "holdings" in payload
    assert tool_results[0]["is_error"] is False


def test_tool_use_needing_consent_pauses_for_input_then_continues(
    monkeypatch, permissions_store, preferences_store, mock_portfolio_path,
):
    permissions_store.grant("portfolio")
    monkeypatch.setattr("builtins.input", lambda _: "always")

    call_model = MagicMock(side_effect=[tool_use_response(), text_response("Here you go.")])
    monkeypatch.setattr("app.main.call_reasoning_model", call_model)

    messages = []
    chat_turn("What stocks do I own?", messages, permissions_store, preferences_store)

    assert preferences_store.get(FORWARDING_KEY) == "always"
    tool_results = _extract_tool_results(messages)
    assert len(tool_results) == 1
    payload = json.loads(tool_results[0]["content"])
    assert "holdings" in payload, "the model must never see the needs_consent status itself"


def test_tool_use_answered_once_returns_holdings_without_persisting(
    monkeypatch, permissions_store, preferences_store, mock_portfolio_path,
):
    """Regression test for the bug where answering 'once' never actually
    granted the pending call - execute_tool was re-invoked with no way to
    bypass the still-unset disposition, so it returned needs_consent a
    second time and that raw status/prompt dict leaked to the model instead
    of the holdings."""
    permissions_store.grant("portfolio")
    monkeypatch.setattr("builtins.input", lambda _: "once")

    call_model = MagicMock(side_effect=[tool_use_response(), text_response("Here you go.")])
    monkeypatch.setattr("app.main.call_reasoning_model", call_model)

    messages = []
    chat_turn("What stocks do I own?", messages, permissions_store, preferences_store)

    assert preferences_store.get(FORWARDING_KEY) is None
    tool_results = _extract_tool_results(messages)
    assert len(tool_results) == 1
    payload = json.loads(tool_results[0]["content"])
    assert "holdings" in payload, "the model must never see a raw needs_consent status"
    assert tool_results[0]["is_error"] is False


def test_denial_reasons_reach_the_model_verbatim_and_distinctly(
    monkeypatch, permissions_store, preferences_store, mock_portfolio_path,
):
    """Regression test for the bug where both denial kinds were narrated
    identically - the raw tool_result payload passed to the model must
    already carry two different error strings for chat_turn to have any
    chance of relaying them distinctly."""
    call_model = MagicMock(side_effect=[tool_use_response(), text_response("denied")])
    monkeypatch.setattr("app.main.call_reasoning_model", call_model)
    messages_not_granted = []
    chat_turn("Analyze my portfolio", messages_not_granted, permissions_store, preferences_store)
    not_granted_error = json.loads(_extract_tool_results(messages_not_granted)[0]["content"])["error"]
    assert _extract_tool_results(messages_not_granted)[0]["is_error"] is True

    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "never")
    call_model.side_effect = [tool_use_response(), text_response("denied")]
    messages_never = []
    chat_turn("Analyze my portfolio", messages_never, permissions_store, preferences_store)
    never_error = json.loads(_extract_tool_results(messages_never)[0]["content"])["error"]
    assert _extract_tool_results(messages_never)[0]["is_error"] is True

    assert not_granted_error != never_error


def test_each_chat_turn_call_invokes_the_model_fresh_no_client_side_cache(
    monkeypatch, permissions_store, preferences_store, mock_portfolio_path,
):
    """Two separate chat_turn calls for the same kind of question must each
    trigger their own model call and, when the model asks for the tool,
    their own execute_tool call - chat_turn must never answer a later turn
    from an earlier turn's tool_result without asking the model again."""
    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "always")

    call_model = MagicMock(side_effect=[
        tool_use_response(tool_id="t1"), text_response("First answer."),
        tool_use_response(tool_id="t2"), text_response("Second answer."),
    ])
    monkeypatch.setattr("app.main.call_reasoning_model", call_model)

    messages = []
    chat_turn("What stocks do I own?", messages, permissions_store, preferences_store)
    chat_turn("What price did I buy NVDA at?", messages, permissions_store, preferences_store)

    assert call_model.call_count == 4
    assert len(_extract_tool_results(messages)) == 2


def test_permission_revoked_between_turns_is_reflected_in_the_next_tool_call(
    monkeypatch, permissions_store, preferences_store, mock_portfolio_path,
):
    """The concrete case the first Milestone 2 bug was about: state changes
    between turns (here, revoke) must be visible to the very next tool call,
    proving chat_turn never bypasses execute_tool with a stale result."""
    permissions_store.grant("portfolio")
    preferences_store.set(FORWARDING_KEY, "always")

    call_model = MagicMock(side_effect=[tool_use_response(), text_response("Here you go.")])
    monkeypatch.setattr("app.main.call_reasoning_model", call_model)
    messages = []
    chat_turn("What stocks do I own?", messages, permissions_store, preferences_store)
    assert "holdings" in json.loads(_extract_tool_results(messages)[0]["content"])

    permissions_store.revoke("portfolio")
    call_model.side_effect = [tool_use_response(), text_response("Can't help with that.")]
    chat_turn("Analyze my portfolio", messages, permissions_store, preferences_store)

    second_result = json.loads(_extract_tool_results(messages)[1]["content"])
    assert "error" in second_result
