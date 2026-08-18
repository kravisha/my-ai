"""The model behind an interface (addendum 16 §24), and the import-time client
that used to sit in front of it.

`app/model_gateway.py`'s public contract is unchanged and still locked down in
tests/test_model_gateway.py; this file covers the provider underneath it.
"""

import os
import subprocess
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock

from app import model_gateway
from app.model_provider import AnthropicProvider
from backend.controller import PROJECT_ROOT


def test_constructing_a_provider_builds_no_client():
    """The whole point of the split. Constructing must be free - no SDK client,
    no key lookup - because a module that merely names a provider should not pay
    for one."""
    provider = AnthropicProvider()
    assert provider._client is None


def test_importing_the_model_gateway_needs_no_api_key():
    """The regression that motivated this, checked the only way that means
    anything: in a subprocess with the variable genuinely absent.

    `_client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])` at module
    level made `import app.model_gateway` raise KeyError in a clean environment,
    which is why tests/conftest.py has to set a fake key before any import. This
    process has one set; only a child without it can prove the import survives.

    HOME/USERPROFILE are kept because the SDK and dotenv read them, but the .env
    file that would supply a key is bypassed by running from a different working
    directory."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key in ("PATH", "SYSTEMROOT", "HOME", "USERPROFILE", "PYTHONPATH")
    }
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    assert "ANTHROPIC_API_KEY" not in env

    result = subprocess.run(
        [sys.executable, "-c", "import app.model_gateway; print('ok')"],
        cwd=PROJECT_ROOT.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, (
        "importing app.model_gateway without ANTHROPIC_API_KEY failed; the client "
        f"is being constructed at import again:\n{result.stderr}"
    )
    assert "ok" in result.stdout


def test_complete_forwards_every_argument_to_the_sdk():
    provider = AnthropicProvider(model="test-model")
    fake_create = MagicMock(return_value="fake-response")
    provider._client = MagicMock(messages=MagicMock(create=fake_create))

    messages = [{"role": "user", "content": "hi"}]
    tools = [{"name": "x"}]
    result = provider.complete("system prompt", messages, tools, max_tokens=99)

    assert result == "fake-response"
    fake_create.assert_called_once_with(
        model="test-model", max_tokens=99, system="system prompt", messages=messages, tools=tools
    )


def _fake_stream(fragments, content=None, stop_reason="end_turn", captured=None):
    """Stands in for the SDK's streaming context manager: a text_stream to
    iterate and a final message to read once it is exhausted."""

    @contextmanager
    def factory(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        blocks = content
        if blocks is None:
            blocks = [MagicMock(**{"model_dump.return_value": {"type": "text", "text": "".join(fragments)}})]
        final = MagicMock(content=blocks, stop_reason=stop_reason)
        yield MagicMock(text_stream=iter(fragments), get_final_message=lambda: final)

    return factory


def test_stream_yields_fragments_in_order_then_a_final_event():
    """The wrapper must yield fragments unchanged and in order rather than
    accumulating and returning one string, which would defeat streaming while
    still passing a naive content check - and it must end with exactly one final
    event, which is what lets a caller run a tool loop."""
    provider = AnthropicProvider(model="test-model")
    provider._client = MagicMock(
        messages=MagicMock(stream=_fake_stream(["Spec", "ification", " leads"]))
    )

    events = list(provider.stream("system", [{"role": "user", "content": "hi"}], []))

    assert [event["text"] for event in events[:-1]] == ["Spec", "ification", " leads"]
    assert events[-1]["type"] == "final"
    assert events[-1]["stop_reason"] == "end_turn"


def test_the_final_event_carries_plain_dictionaries_not_sdk_objects():
    """§24 in practice: a caller that had to walk SDK types would be written
    against Anthropic no matter what the interface claimed."""
    block = MagicMock()
    block.model_dump.return_value = {"type": "tool_use", "id": "tu_1", "name": "x", "input": {}}
    provider = AnthropicProvider(model="test-model")
    provider._client = MagicMock(
        messages=MagicMock(stream=_fake_stream([], content=[block], stop_reason="tool_use"))
    )

    final = list(provider.stream("system", [], []))[-1]

    assert final["content"] == [{"type": "tool_use", "id": "tu_1", "name": "x", "input": {}}]
    assert final["stop_reason"] == "tool_use"


def test_stream_passes_the_model_tools_and_token_budget():
    captured = {}
    provider = AnthropicProvider(model="test-model")
    provider._client = MagicMock(messages=MagicMock(stream=_fake_stream([], captured=captured)))

    messages = [{"role": "user", "content": "hi"}]
    tools = [{"name": "file_scoreboard_item"}]
    list(provider.stream("system", messages, tools, max_tokens=1234))

    assert captured == {
        "model": "test-model",
        "max_tokens": 1234,
        "system": "system",
        "messages": messages,
        "tools": tools,
    }


def test_set_provider_replaces_the_process_wide_default():
    """How every other test in the suite substitutes a model, and how a future
    configuration path would select a vendor at startup."""
    original = model_gateway.default_provider()
    substitute = MagicMock()
    try:
        model_gateway.set_provider(substitute)
        assert model_gateway.default_provider() is substitute
    finally:
        model_gateway.set_provider(None)

    assert model_gateway.default_provider() is not substitute
    assert type(model_gateway.default_provider()) is type(original)
