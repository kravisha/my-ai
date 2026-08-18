"""Locks in the API call contract so an accidental change to model/max_tokens/
argument wiring is caught, without ever making a real network call.

The contract is unchanged since this file was written; what moved is where it is
implemented. `call_reasoning_model` now delegates to app/model_provider.py's
provider (addendum 16 §24), so the assertion goes through the provider the
process would actually use rather than through a module-level client that no
longer exists. tests/test_model_provider.py covers the provider itself.
"""

from unittest.mock import MagicMock

from app import model_gateway


def test_call_reasoning_model_forwards_arguments_correctly():
    provider = MagicMock()
    provider.complete.return_value = "fake-response"

    messages = [{"role": "user", "content": "hi"}]
    tools = [{"name": "x"}]
    try:
        model_gateway.set_provider(provider)
        result = model_gateway.call_reasoning_model("system prompt", messages, tools)
    finally:
        model_gateway.set_provider(None)

    assert result == "fake-response"
    provider.complete.assert_called_once_with("system prompt", messages, tools, max_tokens=2048)


def test_call_reasoning_model_passes_a_larger_token_budget_through():
    """Analysis asks for 4096 where Explorer's judgment gate asks for 300, so the
    override is load-bearing rather than decorative."""
    provider = MagicMock()
    try:
        model_gateway.set_provider(provider)
        model_gateway.call_reasoning_model("system", [], [], max_tokens=4096)
    finally:
        model_gateway.set_provider(None)

    assert provider.complete.call_args.kwargs["max_tokens"] == 4096


def test_the_default_model_is_unchanged():
    """A change here changes what every agent reasons with, so it should be a
    deliberate edit that also edits this line."""
    assert model_gateway.MODEL == "claude-sonnet-5"
