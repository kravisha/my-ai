"""Local first, Kimi remote second, explicit failure third - and no vendor
after that.

Krish, 2026-09-16 from abroad, in his own ordering:

    LOCAL KIMI
            down-arrow  only when escalation is justified
    REMOTE KIMI API
            down-arrow  if unavailable
    EXPLICIT FAILURE / USER DECISION

    Never:  LOCAL -> ANTHROPIC   or   KIMI -> ANTHROPIC

and, in the same instruction, *"Do not rely on prompts saying 'use local first.'
Enforce this at the code/config/router level."* That sentence is why this module
exists rather than a paragraph in a system prompt.

## The answer to "why was Anthropic being called despite the local-first policy"

Nothing bypassed the policy. **There has never been a local model on this
machine** - `app/local_ai.NoLocalModelsService` is the honest implementation and
it reports zero models and refuses every call, which is not a bug but the
accurate description of a machine with no runtime installed. So local-first had
nothing to be first to, and every call went to the only provider that existed.

What looked like routing was `app/model_tiering.TieredProvider`, which chose
between a cheap Anthropic model and a capable one. Its hard boundary sends every
request carrying tools to the capable model, and the Gateway assistant carries
tools on every turn - so his traffic took the most expensive path by design,
correctly, for a policy written before there was a second vendor to route to.

## What enforcement means here, as opposed to what it would have meant

It would have been one line to add a `USE_ANTHROPIC` switch and default it off.
He asked for two things that pull against each other - a rollback path, and that
Anthropic can never be *accidentally* selected - and a switch satisfies the
first by breaking the second: a flag that can be turned on can be turned on by
accident, by a stale `.env`, by a copied deployment, by a test that forgets to
clear it. So there is no switch. `assert_no_anthropic` walks the provider graph
at construction and refuses to build a router with that vendor anywhere inside
it, and the rollback path is putting the previous release back - which every
release here already does by itself when its checks fail.

The `anthropic_runtime` counter is therefore structurally zero rather than
observed to be zero, and `counters()` says so in those words. A counter that
could only ever read zero is worth having precisely because he asked to see the
number: it is the difference between "we looked and it was zero" and "there is
no code path that could make it anything else".

## Escalation is a decision with a reason attached

`escalate_reason` is recorded on every call that leaves local, because "the
local model could not cope" and "there is no local model installed" are
different facts and only one of them is worth acting on. A budget refusal is
never escalated: the ceiling exists to stop work, not to move it somewhere else,
which is the same rule `TieredProvider` follows and for the same reason.
"""

from __future__ import annotations

import logging
import time

LOG = logging.getLogger("model.routing")

# Why a call left the local tier. A closed vocabulary, because these end up in a
# log Krish reads from abroad and "escalated" on its own answers nothing.
NO_LOCAL_RUNTIME = "no local model runtime is installed on this machine"
LOCAL_UNAVAILABLE = "the local model is installed but reported itself unavailable"
LOCAL_FAILED = "the local model was called and failed"
LOCAL_NOT_OFFERED = "no local provider is configured in this deployment"
STREAM_NOT_LOCAL = "streaming was requested and the local tier does not stream"


class ModelRoutingFailure(RuntimeError):
    """Both tiers are unusable, so the request fails and says why.

    This is the third rung of his ladder, and it is a refusal rather than a
    fallback on purpose: *"If both local Kimi and remote Kimi fail, return an
    explicit model-routing failure rather than sending the request to
    Anthropic."*

    The message names every precondition that was checked, in order, because the
    thing he can act on from another continent is which one failed - a missing
    credential, an endpoint refusing, or a machine with no local model - and
    those need three different responses."""


def assert_no_anthropic(provider) -> None:
    """Refuse a provider graph with that vendor anywhere inside it.

    Walks the wrapper attributes this codebase actually uses - `inner`, `local`,
    `remote`, `cheap`, `capable` - rather than everything reachable, so it cannot
    be fooled by a wrapper nobody has written yet, and it says so here instead
    of implying otherwise. Anything new that wraps a provider adds its attribute
    name to `_WRAPPED_ATTRIBUTES` in the same increment.

    Matches on the class name and its defining module, which is what makes it
    enforcement rather than a naming convention: a provider that talks to that
    vendor has to live somewhere, and the two places it could live are both
    checked."""
    for holder in _provider_graph(provider):
        cls = type(holder)
        origin = f"{getattr(cls, '__module__', '')}.{cls.__name__}".lower()
        if "anthropic" in origin:
            raise ModelRoutingFailure(
                f"the runtime router was built with {cls.__name__} inside it, from "
                f"{getattr(cls, '__module__', '?')}. Krish's instruction of "
                f"2026-09-16 removes that vendor from the application's routing "
                f"chain entirely, so this is refused at construction rather than "
                f"discovered on a bill. Claude development tooling is unaffected - "
                f"it does not run through this router.")


_WRAPPED_ATTRIBUTES = ("inner", "local", "remote", "cheap", "capable")


def _provider_graph(provider, seen=None) -> list:
    """Every provider reachable through the known wrapper attributes, including
    the one passed in. Cycle-safe by identity, because a decorator chain built
    by mistake should fail a check rather than hang it."""
    seen = seen if seen is not None else set()
    if provider is None or id(provider) in seen:
        return []
    seen.add(id(provider))
    found = [provider]
    for attribute in _WRAPPED_ATTRIBUTES:
        found.extend(_provider_graph(getattr(provider, attribute, None), seen))
    return found


class LocalFirstRouter:
    """The one place the runtime chooses a vendor.

    Takes providers rather than names, following `TieredProvider`: the local tier
    is a provider that does not exist on this machine yet, and the day it does
    it drops in here without this class changing.

    `local=None` is the honest state of this deployment today and is reported as
    `LOCAL_NOT_OFFERED` rather than as a local failure - a tier that was never
    offered has not let anybody down."""

    name = "local-first"

    def __init__(self, local=None, remote=None, local_available=None):
        self.local = local
        self.remote = remote
        # Injected so the router can be tested without a runtime, and so the
        # availability question stays the local service's to answer rather than
        # something this class infers from a provider being non-None.
        self._local_available = local_available
        assert_no_anthropic(self)
        self.counts = {
            "local": 0,
            "remote": 0,
            "escalated": 0,
            "failed": 0,
            # Structurally zero. See the module docstring.
            "anthropic_runtime": 0,
        }

    # --- the decision ------------------------------------------------------

    def local_is_usable(self) -> tuple[bool, str]:
        """Whether the local tier can take this request, and why not when it
        cannot. The reason is the return value, not a log line, because the
        caller has to put it in the failure message if remote also fails."""
        if self.local is None:
            return False, LOCAL_NOT_OFFERED
        checker = self._local_available
        if checker is None:
            from app import local_ai

            checker = local_ai.available
        try:
            if checker():
                return True, ""
        except Exception as bad:  # a broken availability check is not availability
            return False, f"{LOCAL_UNAVAILABLE} ({bad})"
        return False, NO_LOCAL_RUNTIME

    def _record(self, tier: str, model: str, started: float | None,
                reason: str, usage=None) -> None:
        """The observability he listed, in one line per request.

        Chosen provider, chosen model, LOCAL or REMOTE, the escalation reason,
        the latency, and the token counts when the provider reported them.
        Estimated cost is deliberately absent rather than guessed: this
        deployment meters spend in tokens and calls, and inventing a currency
        figure here would put a number in a log that nothing measured.

        `started` is None for a streaming call, and the latency is then logged as
        `unmeasured` rather than as a number. The line has to be written when the
        tier is chosen - a stream is handed to the caller and consumed
        afterwards, so the only figure available at this point would be the time
        taken to decide, which is microseconds and would read as a model
        answering instantly. A wrong number in a latency field is worse than an
        absent one, because somebody will average it.

        No key, no header and no message content is logged. The prompt is the
        one thing in a model call that is certain to contain something private."""
        latency = "unmeasured" if started is None else f"{(time.monotonic() - started) * 1000:.0f}"
        LOG.info(
            "provider=%s model=%s location=%s escalation=%s latency_ms=%s "
            "input_tokens=%s output_tokens=%s",
            tier, model, "LOCAL" if tier == "local" else "REMOTE",
            reason or "none", latency,
            getattr(usage, "input_tokens", None) if usage is not None else None,
            getattr(usage, "output_tokens", None) if usage is not None else None,
        )

    def _no_remote(self, escalation: str) -> ModelRoutingFailure:
        from app import kimi_provider

        if self.remote is None and not kimi_provider.credential_present():
            detail = (f"and no remote model is configured - "
                      f"{kimi_provider.API_KEY_ENV} is not set")
        elif self.remote is None:
            detail = ("and no remote provider was built for this process, even "
                      "though a credential exists - that is a wiring fault, not "
                      "a configuration one")
        else:
            detail = "and the remote model is unusable"
        return ModelRoutingFailure(
            f"no model could serve this request. Local: {escalation}; {detail}. "
            f"Nothing falls back to another vendor by design (Krish, 2026-09-16), "
            f"so this is an explicit routing failure rather than a silent charge "
            f"somewhere else.")

    def _remote_model_name(self) -> str:
        return str(getattr(self.remote, "model", "") or "unknown")

    # --- the interface -----------------------------------------------------

    def complete(self, system: str, messages: list, tools: list, max_tokens: int = 2048):
        from app.model_budget import BudgetExceededError

        usable, escalation = self.local_is_usable()
        if usable:
            started = time.monotonic()
            self.counts["local"] += 1
            try:
                answer = self.local.complete(system, messages, tools, max_tokens=max_tokens)
            except BudgetExceededError:
                # The ceiling stops work; it does not redirect it somewhere more
                # expensive. Escalating here would make crossing the budget cost
                # MORE than staying under it.
                raise
            except Exception as bad:
                escalation = f"{LOCAL_FAILED}: {bad}"
                self.counts["escalated"] += 1
            else:
                self._record("local", str(getattr(self.local, "model", "local")),
                             started, "", getattr(answer, "usage", None))
                return answer

        if self.remote is None:
            self.counts["failed"] += 1
            raise self._no_remote(escalation)

        started = time.monotonic()
        self.counts["remote"] += 1
        try:
            answer = self.remote.complete(system, messages, tools, max_tokens=max_tokens)
        except BudgetExceededError:
            raise
        except Exception as bad:
            self.counts["failed"] += 1
            raise ModelRoutingFailure(
                f"no model could serve this request. Local: {escalation}; the remote "
                f"model {self._remote_model_name()} failed: {bad}. Nothing falls back "
                f"to another vendor by design (Krish, 2026-09-16).") from bad
        self._record("remote", self._remote_model_name(), started, escalation,
                     getattr(answer, "usage", None))
        return answer

    def stream(self, system: str, messages: list, tools: list, max_tokens: int = 2048):
        """Streaming does not retry across tiers.

        The same rule `TieredProvider.stream` states: a stream that has already
        emitted fragments cannot be moved to another model without the reader
        seeing two different answers spliced together. So the tier is chosen
        once, and a failure part-way through is one honest failure rather than a
        seam. The choice itself is identical to `complete`'s."""
        usable, escalation = self.local_is_usable()
        if usable:
            self.counts["local"] += 1
            self._record("local", str(getattr(self.local, "model", "local")), None, "")
            return self.local.stream(system, messages, tools, max_tokens=max_tokens)

        if self.remote is None:
            self.counts["failed"] += 1
            raise self._no_remote(escalation)

        self.counts["remote"] += 1
        self._record("remote", self._remote_model_name(), None, escalation)
        return self.remote.stream(system, messages, tools, max_tokens=max_tokens)

    # --- what Krish can see ------------------------------------------------

    def describe(self) -> dict:
        """The routing path as data, for a status surface and for the suite.

        Exists so "which vendor is this system using" is answerable without
        reading code or a bill, which was the position he was in when he sent
        the instruction."""
        usable, reason = self.local_is_usable()
        return {
            "order": ["local", "remote", "explicit-failure"],
            "local": {
                "configured": self.local is not None,
                "usable": usable,
                "detail": reason or "available",
            },
            "remote": {
                "configured": self.remote is not None,
                "provider": getattr(self.remote, "name", None),
                "model": self._remote_model_name() if self.remote is not None else None,
            },
            "anthropic": "not in the runtime routing chain (refused at construction)",
            "counts": dict(self.counts),
        }


def build_router(local=None) -> LocalFirstRouter:
    """The router this deployment runs, assembled from the environment.

    The remote tier is built only when a credential exists. That is not
    politeness about missing configuration - it is what makes the failure
    message able to distinguish "no key" from "the endpoint refused us", which
    are the two states Krish has actually been in today and they need different
    replies from him.

    `local` stays None until a runtime is installed. `app/local_ai.py` is the
    interface it will arrive behind, and the router's local branch is fully
    implemented and tested against a stand-in today, so that release is an
    argument to this function rather than a change to the routing rule."""
    from app import kimi_provider

    remote = kimi_provider.KimiProvider() if kimi_provider.credential_present() else None
    return LocalFirstRouter(local=local, remote=remote)


def counters(router) -> dict:
    """The three counts he asked to be able to see, named as he named them.

    `anthropic_runtime` is zero because no code path increments it, not because
    a measurement came back zero - and that distinction is the whole value of
    reporting it."""
    counts = dict(getattr(router, "counts", {}) or {})
    return {
        "local_requests": counts.get("local", 0),
        "kimi_remote_requests": counts.get("remote", 0),
        "anthropic_runtime_requests": counts.get("anthropic_runtime", 0),
        "escalations": counts.get("escalated", 0),
        "routing_failures": counts.get("failed", 0),
        "anthropic_runtime_note": (
            "structurally zero: app/model_routing.assert_no_anthropic refuses to "
            "build a router containing that vendor, so there is no path that could "
            "increment this"),
    }


def development_tooling_note() -> str:
    """Why `ANTHROPIC_API_KEY` is still in the environment and must stay there.

    He was explicit: *"Do not delete credentials or configuration blindly if
    other development tooling needs them."* The Claude sessions that build this
    system read that variable; the application no longer does. Written as a
    function rather than a comment so the status surface can say it to him in
    the same words."""
    return (
        "ANTHROPIC_API_KEY remains in the environment for the Claude development "
        "sessions on this machine, which are not part of the application runtime. "
        "No application model call reads it: the runtime router refuses to be "
        "constructed with that vendor in it.")


def anthropic_key_consumers() -> dict:
    """Where `ANTHROPIC_API_KEY` is read, separated as he asked, so that
    retiring the application's use of it does not break the tooling that builds
    it.

    Hand-authored from a scan of this repository on 2026-09-16 and therefore a
    snapshot; the runtime half is the half this module makes unreachable."""
    return {
        "application_runtime": [
            "app/model_provider.py::AnthropicProvider.client - constructed by "
            "nothing in the runtime path after 2026-09-16; kept because the class "
            "is what the registry's retired row points at and deleting it would "
            "make that row unverifiable",
        ],
        "development_and_test_tooling": [
            "tests/conftest.py - sets a placeholder so imports survive without a key",
            "simulation/harness.py - reports whether an agent subprocess could "
            "reach a model at all",
            "my-ai/scripts/wake-claude-dev.ps1 - the Claude Dev session's own wake",
        ],
        "note": development_tooling_note(),
    }
