"""Locks in the API call contract so an accidental change to model/max_tokens/
argument wiring is caught, without ever making a real network call."""

from unittest.mock import MagicMock

from app import model_gateway


def test_call_reasoning_model_forwards_arguments_correctly(monkeypatch):
    fake_create = MagicMock(return_value="fake-response")
    monkeypatch.setattr(model_gateway._client.messages, "create", fake_create)

    messages = [{"role": "user", "content": "hi"}]
    tools = [{"name": "x"}]
    result = model_gateway.call_reasoning_model("system prompt", messages, tools)

    assert result == "fake-response"
    fake_create.assert_called_once_with(
        model=model_gateway.MODEL,
        max_tokens=2048,
        system="system prompt",
        messages=messages,
        tools=tools,
    )
