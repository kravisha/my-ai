"""Thin wrapper around the reasoning model call.

Every existing caller - the agents, `backend/main.py`'s `/chat` - reaches the
model through `call_reasoning_model`, and that has not changed. What changed is
underneath: the vendor now sits behind `app/model_provider.py`'s ModelProvider
(addendum 16 §24), and the client is built on first call rather than at import.

The module previously held `_client = Anthropic(api_key=os.environ[
"ANTHROPIC_API_KEY"])` at module level, which made importing it fail in any
environment without that variable and constructed a client for importers that
never called a model. `default_provider()` below is that same singleton, minus
the import-time cost.
"""

from app.model_provider import DEFAULT_MODEL, AnthropicProvider, ModelProvider

MODEL = DEFAULT_MODEL

_provider: ModelProvider | None = None


def default_provider() -> ModelProvider:
    """The process-wide provider, built on first use.

    A module-level singleton rather than a parameter threaded through every
    caller: there is one model in play, and the callers that would have to pass
    it are agent work functions whose signatures are fixed by `agents/base.py`'s
    run contract. Tests substitute it with `set_provider`."""
    global _provider
    if _provider is None:
        _provider = AnthropicProvider(model=MODEL)
    return _provider


def set_provider(provider: ModelProvider | None) -> None:
    """Replace the process-wide provider, or reset to the default with None.

    Exists for tests and for a future configuration path that chooses a vendor at
    startup. It is deliberately not a route or a request-time argument: which
    model reasons for this system is a deployment decision, not a caller's."""
    global _provider
    _provider = provider


def call_reasoning_model(system: str, messages: list, tools: list, max_tokens: int = 2048):
    return default_provider().complete(system, messages, tools, max_tokens=max_tokens)
