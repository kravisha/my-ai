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

import os
import time

from app.model_budget import BudgetedProvider
from app.model_provider import DEFAULT_MODEL, AnthropicProvider, ModelProvider

MODEL = DEFAULT_MODEL

_provider: ModelProvider | None = None


# Fault injection: make a model call slow without making the agent sick
# (TASK_QUEUE TQ-94, docs/SPEC_RECONCILIATION.md §136).
#
# `simulation/faults.py` can kill a process, stop it, or lock its database.
# All three produce a **dead** agent, and the condition this organization has
# actually been getting wrong is a live one: an agent inside a slow model call,
# alive and not advancing, which COO twice mistook for a crash (§133).
#
# **A seam in production code, and it needs to be here rather than anywhere
# else.** The slowness that caused the defect originates at exactly this call.
# Pausing the process instead would stop the liveness thread too and produce a
# dead-looking agent - testing the opposite of what TQ-93 built. Delaying
# somewhere cheaper would exercise a different code path than the one that
# failed.
#
# Inert unless configured, and `tests/test_slow_model_fault.py` asserts that an
# unset environment produces no wrapper at all.
FAULT_DELAY_ENV = "FI_FAULT_MODEL_DELAY_SECONDS"
FAULT_DELAY_CALLS_ENV = "FI_FAULT_MODEL_DELAY_CALLS"


class SlowProvider:
    """A ModelProvider that wraps another and stalls the first N calls.

    Same decorator shape as `BudgetedProvider`, deliberately: the interface in
    between is unchanged, so nothing downstream can tell a stalled call from a
    genuinely slow vendor - which is the point.

    **The first N calls, not every call.** A provider that stalled forever would
    starve the pipeline and fail every property about work getting done, and a
    run in which everything went red proves nothing about which mechanism broke.
    Stalling once produces exactly one slow episode: the agent goes quiet, COO
    notices, and then it recovers - which is the whole sequence under test."""

    def __init__(self, inner, delay_seconds: float, calls: int = 1):
        self.inner = inner
        self.delay_seconds = delay_seconds
        self.remaining = calls

    def _stall(self) -> None:
        if self.remaining <= 0:
            return
        self.remaining -= 1
        print(f"[fault] stalling a model call for {self.delay_seconds}s "
              f"({self.remaining} more to stall)", flush=True)
        time.sleep(self.delay_seconds)

    def complete(self, system: str, messages: list, tools: list, max_tokens: int = 2048):
        self._stall()
        return self.inner.complete(system, messages, tools, max_tokens=max_tokens)

    def stream(self, system: str, messages: list, tools: list, max_tokens: int = 2048):
        self._stall()
        return self.inner.stream(system, messages, tools, max_tokens=max_tokens)


def _fault_delay() -> tuple[float, int] | None:
    """The configured stall, or None when nothing is configured.

    Refuses a value it cannot parse rather than falling back to no delay: a typo
    in a scenario's config would otherwise produce a run that looks like it
    exercised the fault and did not - which is the failure this whole entry is
    about, arriving through its own front door."""
    raw = os.environ.get(FAULT_DELAY_ENV)
    if not raw:
        return None
    try:
        seconds = float(raw)
        calls = int(os.environ.get(FAULT_DELAY_CALLS_ENV, "1"))
    except ValueError as bad:
        raise ValueError(
            f"{FAULT_DELAY_ENV}={raw!r} is not a number of seconds. Refusing to run a fault "
            f"nobody can read, because a run that quietly skipped it would look like one that "
            f"passed it.") from bad
    if seconds <= 0 or calls <= 0:
        raise ValueError(f"{FAULT_DELAY_ENV} and {FAULT_DELAY_CALLS_ENV} must both be above zero.")
    return seconds, calls


def default_provider() -> ModelProvider:
    """The process-wide provider, built on first use.

    A module-level singleton rather than a parameter threaded through every
    caller: there is one model in play, and the callers that would have to pass
    it are agent work functions whose signatures are fixed by `agents/base.py`'s
    run contract. Tests substitute it with `set_provider`.

    Wrapped in the cost circuit breaker (app/model_budget.py) here, at the one
    place the real vendor is constructed, so every caller in every process -
    agents, backend /chat, the Gateway's stream - spends against the same
    ledger. A test provider installed via set_provider is deliberately not
    wrapped: it spends nothing."""
    global _provider
    if _provider is None:
        _provider = BudgetedProvider(AnthropicProvider(model=MODEL))
        fault = _fault_delay()
        if fault is not None:
            # Outside the budget wrapper, so a stalled call still counts against
            # spend exactly as a slow real one would. Inside would make the fault
            # invisible to the ledger and the run cheaper than what it simulates.
            _provider = SlowProvider(_provider, fault[0], fault[1])
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
