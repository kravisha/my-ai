"""Spend the small model by default and the large one only when the work needs it.

Krish, 2026-09-14: keep the Anthropic key, but Jarvis's use of it must be
"limited and marginal", and when he does go remote he should use "low level
models that don't consume much resources". This is the half of that directive
that can be built safely tonight. The other half - trying a local Ollama model
first - needs a response adapter that mimics the vendor SDK object every caller
consumes, and a conformance suite to prove it does. That is tomorrow's work, and
a half-built version of it would fail on the one path he cannot afford to lose.

## Why tiering, and not just a cheaper default

Setting DEFAULT_MODEL to the small model would be one line and would break the
work that genuinely needs the large one. The thing that actually predicts which
is needed is not the caller's identity or a config flag someone must remember to
set - it is the SHAPE OF THE REQUEST, and that is available here for free.

## The routing rule, and why each clause earns its place

TOOLS ARE THE HARD BOUNDARY. A request carrying tools goes to the capable model,
always. Small models emit plausible tool calls with wrong arguments, and a wrong
argument is not a visible failure - it is a confident action against the real
system. Everything else here is an optimisation; this clause is a correctness
guard, and `tests/test_model_tiering.py` mutation-checks it.

SIZE IS A PROXY, AND ONLY A PROXY. A long conversation is more likely to need
the capable model, so a generous threshold routes it there. It will sometimes be
wrong in both directions. That is acceptable because the failure is a
quality wobble on a cheap call, not an action - and because the escalation below
catches the case that matters.

ESCALATE ON FAILURE, NEVER SILENTLY DEGRADE. If the cheap model raises, the same
request is retried once against the capable one. This is the local-first shape
applied to tiers: attempt the frugal option, judge the result, escalate only on
failure. A budget refusal is deliberately NOT escalated - the whole point of the
ceiling is that crossing it stops work rather than making it more expensive.

## Mode is configuration, not code

MODEL_TIER_MODE=auto     route by request shape (default)
MODEL_TIER_MODE=cheap    force the small model, for deliberate frugality
MODEL_TIER_MODE=capable  disable tiering entirely, the pre-2026-09-14 behaviour

The escape hatch matters: if tiering ever degrades Jarvis while Krish is abroad
and cannot debug it, one environment variable restores the old behaviour without
a code change or a deploy.
"""

import os

CHEAP_MODEL_ENV = "MODEL_CHEAP"
CAPABLE_MODEL_ENV = "MODEL_CAPABLE"
MODE_ENV = "MODEL_TIER_MODE"
SIZE_LIMIT_ENV = "MODEL_TIER_CHEAP_MAX_CHARS"

# Haiku is the small model in the current family. Named here rather than
# inlined so that a family change is one edit in one place.
DEFAULT_CHEAP = "claude-haiku-4-5-20251001"
DEFAULT_CAPABLE = "claude-sonnet-5"

# Generous on purpose. This is a proxy for "is this a substantial piece of
# reasoning", and the cost of routing a medium request to the capable model is
# one slightly expensive call, while the cost of routing a hard one to the small
# model is an answer Krish cannot trust from abroad.
DEFAULT_SIZE_LIMIT = 8000

MODES = ("auto", "cheap", "capable")


class UnknownTierMode(ValueError):
    """Raised at construction rather than per call.

    A mistyped mode must fail loudly at startup. Falling back to a default would
    mean an operator who typed `MODEL_TIER_MODE=cheep` gets the capable model
    and a larger bill, and nothing anywhere would say so."""


def configured_mode() -> str:
    mode = (os.environ.get(MODE_ENV, "") or "auto").strip().lower()
    if mode not in MODES:
        raise UnknownTierMode(
            f"{MODE_ENV}={mode!r} is not a routing mode; known modes are {list(MODES)}")
    return mode


def cheap_model() -> str:
    return (os.environ.get(CHEAP_MODEL_ENV, "") or DEFAULT_CHEAP).strip()


def capable_model() -> str:
    return (os.environ.get(CAPABLE_MODEL_ENV, "") or DEFAULT_CAPABLE).strip()


def size_limit() -> int:
    raw = (os.environ.get(SIZE_LIMIT_ENV, "") or "").strip()
    if not raw:
        return DEFAULT_SIZE_LIMIT
    try:
        value = int(raw)
    except ValueError as bad:
        raise ValueError(
            f"{SIZE_LIMIT_ENV}={raw!r} is not a number of characters.") from bad
    if value <= 0:
        raise ValueError(f"{SIZE_LIMIT_ENV} must be above zero, got {value}.")
    return value


def request_size(system: str, messages: list) -> int:
    """Characters of prompt, counted cheaply and approximately.

    Not tokens. Tokenising to decide which tokeniser to use would be circular,
    and the threshold is a proxy that does not deserve that precision."""
    total = len(system or "")
    for message in messages or []:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total += len(str(block.get("text", "")))
                else:
                    total += len(str(block))
        elif content is not None:
            total += len(str(content))
    return total


def wants_capable(system: str, messages: list, tools: list, mode: str | None = None) -> bool:
    """The routing decision, isolated so it can be tested without a model."""
    mode = mode or configured_mode()
    if mode == "capable":
        return True
    if mode == "cheap":
        return False
    if tools:
        return True
    return request_size(system, messages) > size_limit()


class TieredProvider:
    """Routes between two providers of the same shape.

    Takes providers rather than model names so that the thing it selects between
    stays substitutable - a local provider drops in here tomorrow as `cheap`
    without this class changing."""

    def __init__(self, cheap, capable, mode: str | None = None):
        self.cheap = cheap
        self.capable = capable
        # Validated at construction, not per call: see UnknownTierMode.
        self.mode = mode or configured_mode()
        if self.mode not in MODES:
            raise UnknownTierMode(
                f"{self.mode!r} is not a routing mode; known modes are {list(MODES)}")
        # Observability for the status surface. Krish is operating this from
        # abroad and "is Jarvis being expensive" must be answerable without a
        # vendor dashboard.
        self.counts = {"cheap": 0, "capable": 0, "escalated": 0}

    def _pick(self, system, messages, tools):
        if wants_capable(system, messages, tools, self.mode):
            return self.capable, "capable"
        return self.cheap, "cheap"

    def complete(self, system: str, messages: list, tools: list, max_tokens: int = 2048):
        # Imported here rather than at module scope so this module stays
        # testable without the ledger, and so importing it costs nothing.
        from app.model_budget import BudgetExceededError

        provider, tier = self._pick(system, messages, tools)
        self.counts[tier] += 1
        try:
            return provider.complete(system, messages, tools, max_tokens=max_tokens)
        except BudgetExceededError:
            # The ceiling exists to stop work, not to redirect it somewhere more
            # expensive. Escalating here would make crossing the budget cost
            # MORE than staying under it, which is the opposite of a ceiling.
            raise
        except Exception:
            if tier != "cheap":
                raise
            self.counts["escalated"] += 1
            return self.capable.complete(system, messages, tools, max_tokens=max_tokens)

    def stream(self, system: str, messages: list, tools: list, max_tokens: int = 2048):
        """Streaming does not escalate.

        A stream that has already emitted fragments cannot be retried against
        another model without the caller seeing two different answers spliced
        together. Better one honest failure than a seam."""
        provider, tier = self._pick(system, messages, tools)
        self.counts[tier] += 1
        return provider.stream(system, messages, tools, max_tokens=max_tokens)
