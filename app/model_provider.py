"""The model as a service behind an interface, rather than a vendor baked into
the call site (addendum 16 §24: the Gateway "must not fundamentally be a 'Claude
Gateway' or 'ChatGPT Gateway'... Models are services behind it").

Two operations, because the system genuinely needs two and not because a wider
interface looked more complete:

- `complete` — one blocking call returning the provider's own response object.
  This is what the agents and `backend/main.py`'s `/chat` have always done, and
  they need the raw object because they read `stop_reason` and walk `content`
  blocks to run tool loops.
- `stream` — the same call, delivered incrementally, and able to ask for tools.
  Addendum 16 §9 asks for streaming responses and low latency, and a Gateway that
  waited for a complete reply before showing anything would fail that on the
  first turn.

`stream` yields plain dictionaries rather than the SDK's event objects, and its
final event carries content blocks already converted to dictionaries. That is
what keeps §24 true in practice: a caller that walked SDK types would be written
against Anthropic no matter what the interface claimed.

**The client is constructed on first use, not at import.** This module was split
out of `app/model_gateway.py`, which held `_client = Anthropic(api_key=os.environ[
"ANTHROPIC_API_KEY"])` at module level: importing it raised `KeyError` in any
environment without the variable, so the test suite carried a `setdefault` to
make imports survive, and every importer paid for a client it might never call.
That is the same class of import-time side effect that made `import backend.main`
write to the developer's database. Constructing lazily also means the key is read
when it is used, so a process that loads `.env` after import still works.
"""

import os
from typing import Iterator, Protocol

from dotenv import load_dotenv

# At import, because it must happen before anything reads ANTHROPIC_API_KEY and
# because agent subprocesses depend on it: simulation/harness.py's
# model_is_available() documents that an agent picks the key up from .env even
# when the launching process has none. That behavior moved here with the client.
load_dotenv()

DEFAULT_MODEL = "claude-sonnet-5"

# What each content block may carry when it is sent *back* as part of a message
# list. A response block and a request block are not the same shape: the SDK's
# `model_dump()` includes response-only fields, and the API rejects them on the
# way in.
#
# Found by a real tool loop, not by the suite: a turn that called a tool and then
# replayed the assistant's own message failed with
# `messages.7.content.0.text.parsed_output: Extra inputs are not permitted`. The
# unit tests passed throughout, because a stand-in provider produces exactly the
# fields the test author thought of.
#
# A block type not listed here is passed through unchanged - dropping fields from
# a block nobody anticipated would be a worse failure than forwarding one, since
# it would corrupt the turn silently rather than loudly.
_REPLAYABLE_BLOCK_FIELDS = {
    "text": ("type", "text"),
    "tool_use": ("type", "id", "name", "input"),
    "thinking": ("type", "thinking", "signature"),
    "redacted_thinking": ("type", "data"),
}


def replayable_block(block: dict) -> dict:
    """One content block, reduced to what may be sent back to the API."""
    allowed = _REPLAYABLE_BLOCK_FIELDS.get(block.get("type"))
    if allowed is None:
        return block
    return {key: value for key, value in block.items() if key in allowed}


def _reported_usage(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class ModelProvider(Protocol):
    """What the rest of the system may assume about a model, whoever supplies it."""

    def complete(self, system: str, messages: list, tools: list, max_tokens: int = 2048):
        """One reply, as the provider's own response object."""
        ...

    def stream(
        self, system: str, messages: list, tools: list, max_tokens: int = 2048
    ) -> Iterator[dict]:
        """The reply as it arrives:

            {"type": "text", "text": "..."}                  zero or more
            {"type": "final", "content": [...], "stop_reason": "..."}   exactly one, last

        `content` is the assistant's full turn as plain dictionaries - text and
        tool_use blocks alike - so a caller can append it to the message list and
        continue a tool loop without touching a vendor type."""
        ...


class AnthropicProvider:
    """The one implementation there is. Named for its vendor so that a second one
    can exist without either pretending to be generic."""

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None):
        self.model = model
        self._api_key = api_key
        self._client = None

    def client(self):
        """Built once, on demand. The import of `anthropic` is deferred with it:
        a module that only names this class should not pay for the SDK, and a
        test that never calls a model should not need a key to exist."""
        if self._client is None:
            from anthropic import Anthropic

            self._client = Anthropic(api_key=self._api_key or os.environ["ANTHROPIC_API_KEY"])
        return self._client

    def complete(self, system: str, messages: list, tools: list, max_tokens: int = 2048):
        return self.client().messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools,
        )

    def stream(
        self, system: str, messages: list, tools: list, max_tokens: int = 2048
    ) -> Iterator[dict]:
        """Yields text fragments as they arrive, then one final event.

        The SDK's context manager owns the HTTP connection, so the generator must
        stay inside it while yielding - which also means an abandoned generator
        closes the connection when it is collected, rather than leaking it. The
        final message is read inside the block for the same reason: it is only
        complete once the stream has been consumed."""
        with self.client().messages.stream(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools,
        ) as stream:
            for fragment in stream.text_stream:
                yield {"type": "text", "text": fragment}
            final = stream.get_final_message()

        usage = getattr(final, "usage", None)
        yield {
            "type": "final",
            "content": [replayable_block(block.model_dump()) for block in final.content],
            "stop_reason": final.stop_reason,
            # For the budget ledger (app/model_budget.py). Strictly what the
            # provider reported: a non-integer (a test double, a partial mock)
            # becomes None - "not reported" - never a fabricated number.
            "usage": {
                "input_tokens": _reported_usage(getattr(usage, "input_tokens", None)),
                "output_tokens": _reported_usage(getattr(usage, "output_tokens", None)),
            },
        }
