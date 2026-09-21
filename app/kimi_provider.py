"""Kimi as a ModelProvider, speaking the OpenAI dialect over plain HTTP.

Krish, 2026-09-16 from abroad: *"Stop the application from using Anthropic API
for normal model calls... When the local model genuinely cannot complete the
request... send the request to Kimi using the Kimi API."* This is the remote half
of that. The router that chooses between local and here is `app/model_routing.py`.

## The endpoint and the model id were measured, not assumed

He warned, correctly, *"Do not assume the marketing name and API model ID are
identical."* A session on this machine cannot make an outbound call - the
permission gate refuses every one - so the settling was done by a job,
`Deployments/probe-kimi-api.ps1`, and its trace is `_probe-kimi.log`. What it
established at 2026-09-16T22:40 local:

    base        https://api.kimi.com/coding/v1
    dialect     openai
    catalogue   kimi-for-coding, kimi-for-coding-highspeed, k3-256k, k3
    callable    k3-256k, proven by a real completion rather than by its name
    latency     1741 ms for an 8-token reply, cold

The two Moonshot developer bases - `api.moonshot.ai` and `api.moonshot.cn` -
both returned 401 for this credential, and `api.kimi.com/v1` returned 404. So the
key is a Kimi subscription credential rather than a Moonshot platform one, and
the working base has `/coding` in the path. That is why the default below is not
the address any documentation search would have produced, and why it is written
here with the measurement beside it: the next person to doubt it should re-run
the probe, not re-read a guess.

## Why the dialect is hand-written rather than an SDK

Nothing is added to the dependency set. The probe proved the wire format is
plain OpenAI-shaped JSON over HTTPS, `httpx` is already in this environment for
the test client, and the translation this module needs is not the part an SDK
would do for us - it is the part between *Anthropic's* message shape, which
every caller in this system already speaks, and OpenAI's. An SDK would still
leave that to us, while adding a package and a second opinion about retries.

## What the translation has to get right, and what happens when it cannot

Tool calls are the whole risk of this change. The Gateway assistant carries
tools on every single turn, so a mistranslation here is not a quality wobble -
it is a confident action with the wrong arguments, which is the one failure
`app/model_tiering.py` was already written to avoid. Two consequences:

- `_decoded_arguments` REFUSES an argument blob it cannot parse instead of
  passing an empty dict along. A tool executed with no arguments looks like a
  tool that worked. A refusal is loud, lands in the router's explicit failure,
  and costs one turn.
- `stop_reason` is `tool_use` whenever a tool call came back, whatever the
  provider put in `finish_reason`. Some OpenAI-dialect servers say `stop` on a
  turn that also asked for a tool; believing them would drop the call silently.

## What this deliberately does not carry over

`app/model_provider.cacheable_system` marks a cacheable prefix in Anthropic's
syntax. There is no equivalent field in this dialect, so the system prompt goes
as plain text and the prompt-cache release of 2026-09-16 16:25 buys nothing on
this path. Whether this provider caches implicitly is not something this file
will claim without a measurement.
"""

from __future__ import annotations

import json
import os
from typing import Iterator

from app import model_calls

# Measured, not assumed. See the module docstring and _probe-kimi.log.
DEFAULT_BASE_URL = "https://api.kimi.com/coding/v1"
DEFAULT_MODEL = "k3-256k"

API_KEY_ENV = "KIMI_API_KEY"
BASE_URL_ENV = "KIMI_BASE_URL"
MODEL_ENV = "KIMI_MODEL_REMOTE"
TIMEOUT_ENV = "KIMI_TIMEOUT_SECONDS"

# Generous. A tool-carrying turn on a long conversation is the slow case, and a
# timeout that fired mid-answer would look to Krish exactly like the model
# refusing him. The probe measured 1.7s cold for a trivial call; this is a
# ceiling, not an expectation.
DEFAULT_TIMEOUT_SECONDS = 120.0

# finish_reason -> the vocabulary every caller in this system already branches
# on. Only `tool_use` is actually tested against by callers
# (backend/main.py, gateway/conversation.py); the rest exist so a log line reads
# in one language.
_STOP_REASONS = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "content_filter": "stop_sequence",
}


class KimiError(RuntimeError):
    """Base for everything this provider refuses."""


class KimiCredentialMissing(KimiError):
    """No API key. Named separately because the router's failure message must
    be able to say *which* precondition was missing - "no credential" and "the
    provider refused the call" need different actions from Krish."""


class KimiCallFailed(KimiError):
    """The call was made and did not produce a usable reply.

    Carries the HTTP status or the parse fault, never the request headers: the
    credential travels in a header and an exception string ends up in logs."""


class KimiQuotaExhausted(KimiError):
    """The remote model has nothing left to give today (Task 01 §4.2).

    Its own class rather than a `KimiCallFailed` with a particular status,
    because the router does something different with it - it falls back and
    queues a retry instead of failing - and because the two attributes below
    are what keep Krish from ever reading about it.

    `model_call_outcome` is what `app/model_calls.classify` writes in the call
    log. `user_message_category` is what `app/user_messages.classify` turns
    into a sentence: "I can't do that reliably right now - I'll retry shortly".
    Both are declared here, by the code that knows what happened, rather than
    pattern-matched from this message somewhere else."""

    model_call_outcome = "quota_exhausted"
    user_message_category = "capacity"


# HTTP statuses that mean "not now, and not because the request was wrong".
# 429 is the ordinary rate limit; 402 is what a subscription endpoint answers
# when the plan is spent. Both are capacity, and neither is a reason to retry
# immediately or to show anybody a number.
QUOTA_STATUSES = (402, 429)

# Servers in this dialect answer 400 with a body that says the real reason more
# often than they pick a status that does. Matched against the lower-cased body
# as a last resolution, never as the first: a status is a contract and a
# message is prose.
QUOTA_MARKERS = (
    "insufficient_quota", "insufficient quota", "quota exceeded",
    "exceeded your current quota", "insufficient balance",
    "rate_limit_exceeded", "rate limit", "billing", "out of credit",
)


def is_quota_exhaustion(status: int | None, body: str | None) -> bool:
    """Whether this refusal is capacity rather than a bad request.

    Errs towards "not quota": a genuine 400 misread as exhaustion would put the
    request in the retry queue to fail identically three more times, and would
    tell Krish to wait for something that is never going to work."""
    if status in QUOTA_STATUSES:
        return True
    if status != 400 or not body:
        return False
    lowered = body.lower()
    return any(marker in lowered for marker in QUOTA_MARKERS)


def _refusal(status: int, body: str) -> KimiError:
    """The right exception for a non-200, with the body truncated.

    300 characters, and never the headers: the credential travels in a header
    and an exception string ends up in a log."""
    if is_quota_exhaustion(status, body):
        return KimiQuotaExhausted(
            f"the remote model refused with HTTP {status}, which this provider "
            f"reads as exhausted capacity rather than a bad request. The router "
            f"falls back and queues a retry; nothing about this reaches the user. "
            f"First 300 characters of the body: {body[:300]!r}")
    return KimiCallFailed(
        f"the remote model answered HTTP {status}. "
        f"First 300 characters of the body: {body[:300]!r}")


class _Block:
    """One content block, with both shapes its readers use.

    `backend/main.py` walks `block.type`, `block.id`, `block.name`, `block.input`
    as attributes and then calls `block.model_dump()` to append the turn to the
    message list. `gateway/conversation.py` reads dictionaries. So the block is
    both, and `model_dump` returns a copy so a caller cannot mutate the reply."""

    def __init__(self, data: dict):
        self._data = dict(data)
        self.type = data.get("type")
        self.text = data.get("text", "")
        self.id = data.get("id")
        self.name = data.get("name")
        self.input = data.get("input")

    def model_dump(self) -> dict:
        return dict(self._data)

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return f"_Block({self._data!r})"


class _Usage:
    """Token counts as attributes, because `app/model_budget.BudgetedProvider`
    reads `response.usage.input_tokens`.

    None means the provider did not report it. Never zero: the ledger treats a
    zero as a call that cost nothing, and "not reported" is a different fact."""

    def __init__(self, input_tokens: int | None, output_tokens: int | None):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class KimiResponse:
    """The shape `complete` returns: what an Anthropic response object looks
    like to the three places that consume one, and nothing more.

    Deliberately not a subclass of anything in the vendor SDK. The point of
    `app/model_provider.ModelProvider` is that callers walk plain values; this
    class is the evidence that a second vendor can satisfy that."""

    def __init__(self, content: list[dict], stop_reason: str,
                 usage: _Usage | None = None, model: str = ""):
        self.content = [_Block(block) for block in content]
        self.stop_reason = stop_reason
        self.usage = usage or _Usage(None, None)
        self.model = model


def _reported_int(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _decoded_arguments(raw, tool_name: str) -> dict:
    """A tool call's arguments, or a refusal.

    Empty is legitimate - a tool with no parameters is called with `{}` and
    several servers send an empty string for it. Anything else that will not
    parse is refused, for the reason in the module docstring: a tool executed
    with the wrong arguments is an action, and it looks like success."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError) as bad:
        raise KimiCallFailed(
            f"the model asked to call {tool_name!r} with arguments that are not "
            f"JSON, so this turn is refused rather than run with the wrong ones. "
            f"First 200 characters: {str(raw)[:200]!r}") from bad
    if not isinstance(decoded, dict):
        raise KimiCallFailed(
            f"the model asked to call {tool_name!r} with arguments that parsed to "
            f"{type(decoded).__name__} rather than an object; refusing rather than "
            f"guessing what the parameters were meant to be")
    return decoded


def _tool_result_text(block: dict) -> str:
    """A tool_result block's payload as text.

    Every producer in this repository already puts a JSON string here
    (`backend/main.py`, `gateway/conversation.py`). The list form is Anthropic's
    other legal shape and is handled so a future producer does not silently send
    the model the word "None"."""
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text", "")))
            else:
                parts.append(str(part))
        return "".join(parts)
    return "" if content is None else str(content)


def to_openai_tools(tools: list | None) -> list | None:
    """Anthropic tool definitions in the function-calling shape.

    Returns None rather than an empty list when there are no tools, for the
    reason `app/model_provider._tool_argument` gives: "no tools" and "an empty
    tools array" are different requests, and the client role is offered none at
    all - so an empty array turning into a 400 would break the only capability
    they have."""
    if not tools:
        return None
    converted = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        converted.append({
            "type": "function",
            "function": {
                "name": tool.get("name", ""),
                "description": tool.get("description", "") or "",
                # `input_schema` is the Anthropic name for the same JSON Schema
                # this dialect calls `parameters`. An absent schema becomes an
                # empty object rather than being omitted: a function with no
                # `parameters` key is rejected by some servers.
                "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
            },
        })
    return converted or None


def to_openai_messages(system: str, messages: list | None) -> list:
    """The conversation in this dialect's shape.

    Three translations, and the third is the one with a trap in it:

    1. The system prompt becomes a leading `system` message instead of a
       top-level field.
    2. An assistant turn's `tool_use` blocks become `tool_calls` alongside its
       text, with the arguments re-encoded as a JSON string.
    3. `tool_result` blocks arrive from callers inside a *user* turn, which is
       Anthropic's convention. This dialect has no such thing: each result is
       its own `tool` message keyed by `tool_call_id`. So one incoming turn can
       become several outgoing ones, and the results must precede any ordinary
       text that shared the turn with them - otherwise the reply to a tool call
       arrives after the next question.

    `thinking` and `redacted_thinking` blocks are dropped. They are Anthropic's
    own reasoning trace, they carry a signature only that vendor can verify, and
    forwarding them to another provider would at best waste tokens."""
    converted: list[dict] = []
    if system and system.strip():
        converted.append({"role": "system", "content": system})

    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = message.get("role") or "user"
        content = message.get("content")

        if isinstance(content, str):
            if content:
                converted.append({"role": role, "content": content})
            continue

        text_parts: list[str] = []
        tool_calls: list[dict] = []
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                text_parts.append(str(block))
                continue
            kind = block.get("type")
            if kind == "text":
                text_parts.append(str(block.get("text", "")))
            elif kind == "tool_use":
                tool_calls.append({
                    "id": block.get("id") or "",
                    "type": "function",
                    "function": {
                        "name": block.get("name") or "",
                        "arguments": json.dumps(block.get("input") or {}),
                    },
                })
            elif kind == "tool_result":
                converted.append({
                    "role": "tool",
                    "tool_call_id": block.get("tool_use_id") or "",
                    "content": _tool_result_text(block),
                })
            # thinking / redacted_thinking: see the docstring.

        text = "".join(text_parts)
        if tool_calls:
            # `content` is required even when the whole turn was a tool call, and
            # None is this dialect's way of saying there was no prose with it.
            converted.append({"role": role, "content": text or None,
                              "tool_calls": tool_calls})
        elif text:
            converted.append({"role": role, "content": text})
        # A turn that reduced to nothing is dropped rather than sent empty: an
        # empty assistant message is rejected, and it carries no information.

    return converted


def from_openai_message(message: dict) -> list[dict]:
    """One reply, as the content blocks the rest of this system reads."""
    blocks: list[dict] = []
    content = message.get("content")
    if isinstance(content, list):
        # Some servers in this dialect answer with content parts rather than a
        # string. Flattened rather than rejected.
        content = "".join(
            str(part.get("text", "")) if isinstance(part, dict) else str(part)
            for part in content)
    if content:
        blocks.append({"type": "text", "text": str(content)})

    for index, call in enumerate(message.get("tool_calls") or []):
        if not isinstance(call, dict):
            continue
        function = call.get("function") or {}
        name = function.get("name") or ""
        blocks.append({
            "type": "tool_use",
            # An id is load-bearing: the result is matched back to the call by
            # it. A server that omitted one would otherwise produce a turn whose
            # results can never be paired, so a positional one is synthesised.
            "id": call.get("id") or f"call_{index}",
            "name": name,
            "input": _decoded_arguments(function.get("arguments"), name),
        })
    return blocks


def stop_reason_for(finish_reason: str | None, blocks: list[dict]) -> str:
    """The stop reason, with the tool check winning.

    A turn carrying a tool call is `tool_use` whatever `finish_reason` said. See
    the module docstring: a server that reports `stop` on a turn that also asked
    for a tool would otherwise have its call dropped, and the caller would
    answer Krish as though the tool had been consulted."""
    if any(block.get("type") == "tool_use" for block in blocks):
        return "tool_use"
    return _STOP_REASONS.get((finish_reason or "").strip(), "end_turn")


def configured_base_url() -> str:
    return (os.environ.get(BASE_URL_ENV, "") or DEFAULT_BASE_URL).strip().rstrip("/")


def configured_model() -> str:
    return (os.environ.get(MODEL_ENV, "") or DEFAULT_MODEL).strip()


def configured_timeout() -> float:
    raw = (os.environ.get(TIMEOUT_ENV, "") or "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError as bad:
        raise ValueError(
            f"{TIMEOUT_ENV}={raw!r} is not a number of seconds. Refusing rather "
            f"than falling back to a default nobody chose.") from bad
    if value <= 0:
        raise ValueError(f"{TIMEOUT_ENV} must be above zero, got {value}.")
    return value


def credential_present() -> bool:
    """Whether a key exists at all. The cheap question the router asks before
    building anything, so that "no credential" is reported as its own condition
    rather than as a failed call."""
    return bool((os.environ.get(API_KEY_ENV, "") or "").strip())


class KimiProvider:
    """The remote tier. Satisfies `app/model_provider.ModelProvider`.

    Named for its vendor, following `AnthropicProvider`, so that neither
    implementation has to pretend to be generic."""

    # What the router and the status surface call this, for the log line and the
    # counters. Not derived from the class name: an identity a log depends on
    # should not change because somebody renames a class.
    name = "kimi-remote"
    location = "REMOTE"

    def __init__(self, model: str | None = None, api_key: str | None = None,
                 base_url: str | None = None, timeout: float | None = None,
                 transport=None):
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
        # A seam for the tests, and only that: a callable taking (url, headers,
        # payload, stream, timeout). Left None in every real construction, so
        # the production path is the one the suite cannot accidentally bypass.
        self._transport = transport

    @property
    def model(self) -> str:
        return self._model or configured_model()

    def base_url(self) -> str:
        return self._base_url or configured_base_url()

    def timeout(self) -> float:
        return self._timeout if self._timeout is not None else configured_timeout()

    def api_key(self) -> str:
        key = self._api_key or (os.environ.get(API_KEY_ENV, "") or "").strip()
        if not key:
            raise KimiCredentialMissing(
                f"{API_KEY_ENV} is not set, so the remote model cannot be called. "
                f"This is a missing credential rather than a provider failure, and "
                f"nothing falls back to another vendor - see app/model_routing.py.")
        return key

    # --- the wire ----------------------------------------------------------

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key()}",
                "Content-Type": "application/json"}

    def _payload(self, system: str, messages: list, tools: list,
                 max_tokens: int, stream: bool) -> dict:
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": to_openai_messages(system, messages),
        }
        converted_tools = to_openai_tools(tools)
        if converted_tools:
            payload["tools"] = converted_tools
        if stream:
            payload["stream"] = True
            # Asked for, not relied on. A server that ignores it leaves the
            # ledger's counts as None, which `record_usage` treats as "not
            # reported" rather than as zero.
            payload["stream_options"] = {"include_usage": True}
        return payload

    def complete(self, system: str, messages: list, tools: list, max_tokens: int = 2048):
        """One blocking call, recorded whatever becomes of it.

        THE RECORDING IS HERE, not in the router, and that is the whole point of
        Task 01 Deliverable A: a caller that skipped the router still lands in
        `logs/model_calls.jsonl` with `routed_by: direct_call`. It is also below
        `self._transport`, so a substituted transport cannot make a call
        invisible - only unreal."""
        import httpx

        url = f"{self.base_url()}/chat/completions"
        payload = self._payload(system, messages, tools, max_tokens, stream=False)
        with model_calls.record_call(model_calls.HANDLER_KIMI) as call:
            if self._transport is not None:
                body = self._transport(url, self._headers(), payload, False, self.timeout())
            else:
                try:
                    response = httpx.post(url, headers=self._headers(), json=payload,
                                          timeout=self.timeout())
                except httpx.HTTPError as bad:
                    raise KimiCallFailed(
                        f"the call to the remote model did not complete: {bad}") from bad
                if response.status_code != 200:
                    raise _refusal(response.status_code, response.text)
                try:
                    body = response.json()
                except ValueError as bad:
                    raise KimiCallFailed(
                        f"the remote model answered HTTP 200 with a body that is not JSON. "
                        f"First 300 characters: {response.text[:300]!r}") from bad
            answer = self._response_from(body)
            call.usage(answer.usage.input_tokens, answer.usage.output_tokens)
            return answer

    def _response_from(self, body: dict) -> KimiResponse:
        choices = (body or {}).get("choices") or []
        if not choices:
            raise KimiCallFailed(
                "the remote model answered with no choices, so there is no reply to "
                "return. Refusing rather than handing back an empty turn, which "
                "reads to a caller as a model that had nothing to say.")
        choice = choices[0] or {}
        message = choice.get("message") or {}
        blocks = from_openai_message(message)
        usage = (body or {}).get("usage") or {}
        return KimiResponse(
            content=blocks,
            stop_reason=stop_reason_for(choice.get("finish_reason"), blocks),
            usage=_Usage(_reported_int(usage.get("prompt_tokens")),
                         _reported_int(usage.get("completion_tokens"))),
            model=str((body or {}).get("model") or self.model),
        )

    # --- streaming ---------------------------------------------------------

    def stream(self, system: str, messages: list, tools: list,
               max_tokens: int = 2048) -> Iterator[dict]:
        """The same call, delivered incrementally, in the event shape
        `app/model_provider.ModelProvider.stream` documents.

        Tool-call fragments arrive spread across chunks and keyed by index
        rather than by id - the name lands once, the arguments in pieces - so
        they are accumulated here and only turned into blocks at the end. That
        is also why nothing about a tool call is yielded mid-stream: a partially
        decoded argument string is not a tool call, and a caller that acted on
        one would act on half an instruction."""
        # EAGER CAPTURE, DEFERRED BODY. `stream` is deliberately not a generator
        # function: a generator's body does not run until the caller iterates
        # it, and by then the router's routing context has been reset and every
        # streamed call would be recorded as `direct_call`. The snapshot is
        # taken here, while the router's `with` block is still open, and the
        # generator below records against it. See app/model_calls.py.
        snapshot = model_calls.capture()
        return self._streamed(snapshot, system, messages, tools, max_tokens)

    def _streamed(self, snapshot, system: str, messages: list, tools: list,
                  max_tokens: int) -> Iterator[dict]:
        import httpx

        url = f"{self.base_url()}/chat/completions"
        payload = self._payload(system, messages, tools, max_tokens, stream=True)

        with model_calls.record_call(model_calls.HANDLER_KIMI, snapshot) as call:
            if self._transport is not None:
                lines = self._transport(url, self._headers(), payload, True, self.timeout())
                yield from self._recorded(self._events_from(lines), call)
                return

            try:
                with httpx.Client(timeout=self.timeout()) as client:
                    with client.stream("POST", url, headers=self._headers(),
                                       json=payload) as response:
                        if response.status_code != 200:
                            response.read()
                            raise _refusal(response.status_code, response.text)
                        # Inside both context managers while yielding, the same
                        # discipline AnthropicProvider.stream documents: the
                        # connection belongs to the manager, so an abandoned
                        # generator closes it rather than leaking it.
                        yield from self._recorded(
                            self._events_from(response.iter_lines()), call)
            except httpx.HTTPError as bad:
                raise KimiCallFailed(
                    f"the streaming call to the remote model failed: {bad}") from bad

    @staticmethod
    def _recorded(events: Iterator[dict], call) -> Iterator[dict]:
        """Pass events through, keeping the token counts the final one carries.

        Separate from `_events_from` so the translation of the wire format and
        the accounting of it stay two things - `_events_from` is what
        `tests/test_kimi_provider.py` holds to the dialect, and it should not
        have to know a call log exists."""
        for event in events:
            if event.get("type") == "final":
                usage = event.get("usage") or {}
                call.usage(usage.get("input_tokens"), usage.get("output_tokens"))
            yield event

    def _events_from(self, lines) -> Iterator[dict]:
        text_parts: list[str] = []
        # index -> {"id", "name", "arguments"}. A dict rather than a list
        # because the indices are the server's and need not start at zero or
        # arrive in order.
        calls: dict[int, dict] = {}
        finish_reason = None
        input_tokens = output_tokens = None

        for raw in lines:
            line = (raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)).strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except ValueError:
                # One unreadable chunk is not a reason to discard a reply that
                # is otherwise arriving. The final event still reports what did
                # arrive, and a turn that loses a fragment reads as a short
                # answer rather than as an error.
                continue

            usage = chunk.get("usage") or {}
            if usage:
                input_tokens = _reported_int(usage.get("prompt_tokens")) or input_tokens
                output_tokens = _reported_int(usage.get("completion_tokens")) or output_tokens

            for choice in chunk.get("choices") or []:
                if not isinstance(choice, dict):
                    continue
                finish_reason = choice.get("finish_reason") or finish_reason
                delta = choice.get("delta") or {}
                fragment = delta.get("content")
                if isinstance(fragment, str) and fragment:
                    text_parts.append(fragment)
                    yield {"type": "text", "text": fragment}
                for call in delta.get("tool_calls") or []:
                    if not isinstance(call, dict):
                        continue
                    index = call.get("index", 0)
                    slot = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    if call.get("id"):
                        slot["id"] = call["id"]
                    function = call.get("function") or {}
                    if function.get("name"):
                        slot["name"] = function["name"]
                    piece = function.get("arguments")
                    if isinstance(piece, str):
                        slot["arguments"] += piece

        blocks: list[dict] = []
        text = "".join(text_parts)
        if text:
            blocks.append({"type": "text", "text": text})
        for position, index in enumerate(sorted(calls)):
            slot = calls[index]
            blocks.append({
                "type": "tool_use",
                "id": slot["id"] or f"call_{position}",
                "name": slot["name"],
                "input": _decoded_arguments(slot["arguments"], slot["name"]),
            })

        yield {
            "type": "final",
            "content": blocks,
            "stop_reason": stop_reason_for(finish_reason, blocks),
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        }
