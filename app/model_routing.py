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

from app import confidence, model_calls, retry_queue, router_config, user_messages

LOG = logging.getLogger("model.routing")

# Why a call left the local tier. A closed vocabulary, because these end up in a
# log Krish reads from abroad and "escalated" on its own answers nothing.
NO_LOCAL_RUNTIME = "no local model runtime is installed on this machine"
LOCAL_UNAVAILABLE = "the local model is installed but reported itself unavailable"
LOCAL_FAILED = "the local model was called and failed"
LOCAL_NOT_OFFERED = "no local provider is configured in this deployment"
STREAM_NOT_LOCAL = "streaming was requested and the local tier does not stream"
LOCAL_NO_TOOLS = "the local model declares that it cannot invoke tools"
LOCAL_CONTEXT_EXCEEDED = "the request is longer than the local model's context window"
QUOTA_LOCAL_FALLBACK = "the remote model reported exhausted capacity, so the local attempt stands"

# The §3.1 escalation vocabulary is closed and short, and the sentences above
# are neither. This maps one to the other, and the mapping is the interesting
# part rather than a formality:
#
# "no local runtime is installed" is recorded as `local_error`. It is not an
# error in the ordinary sense - nothing broke - but the choice is between that
# and `not_applicable`, which would say the call never left local when it did.
# The schema's four permitted escalations are about the *local tier being
# unable to serve*, and a tier that does not exist is the limiting case of
# unable. docs/CONFIDENCE.md and docs/CURRENT_ARCHITECTURE.md both say this in
# words, because a reader of the nightly report will otherwise conclude the
# local model is crashing several hundred times a day.
_LOG_REASONS = {
    NO_LOCAL_RUNTIME: model_calls.REASON_LOCAL_ERROR,
    LOCAL_UNAVAILABLE: model_calls.REASON_LOCAL_ERROR,
    LOCAL_FAILED: model_calls.REASON_LOCAL_ERROR,
    LOCAL_NOT_OFFERED: model_calls.REASON_LOCAL_ERROR,
    LOCAL_NO_TOOLS: model_calls.REASON_TOOL_REQUIRED,
    LOCAL_CONTEXT_EXCEEDED: model_calls.REASON_CONTEXT_LENGTH,
}

# Characters per token. The same admitted approximation `app/model_tiering.py`
# makes, and for the same reason it gives: tokenising in order to decide which
# tokeniser to use would be circular, and the decision this feeds is "is this
# obviously too long", not "how much will it cost".
_CHARS_PER_TOKEN = 4


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


class ModelUnavailableNow(ModelRoutingFailure):
    """Nothing can serve this request *right now*, and it has been queued.

    Distinct from `ModelRoutingFailure`, which means nothing can serve it at
    all, because the two need different things from the user: wait, or rephrase.
    `user_message_category` is what turns this into Krish's own sentence - "I
    can't do that reliably right now - I'll retry shortly" (§4.2.3) - instead of
    the accounting underneath it.

    The message this carries is for the log and the brief. `app/user_messages.py`
    is the only thing allowed to write what the user reads, and
    `tests/test_user_facing_language.py` holds that line."""

    user_message_category = "capacity"
    capability_gap_type = "missing_integration"


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
        # The local tier is wrapped here rather than in `build_router`, so that
        # every construction is instrumented - including the ones tests and
        # future callers make directly. The remote tier is not wrapped: it
        # records itself, inside `KimiProvider`, below the transport seam.
        # Instrumenting it here as well would double every remote record and
        # would sit above the seam, which is the layering Deliverable A exists
        # to avoid.
        self.local = (model_calls.InstrumentedProvider(local)
                      if local is not None
                      and not isinstance(local, model_calls.InstrumentedProvider)
                      else local)
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
            # §4.2: how often the remote tier had nothing left, and how many
            # requests were written down to be tried again. Counted because
            # "did that ever actually happen" is the first question anybody
            # asks of a fallback, and a fallback nobody can count is a fallback
            # nobody trusts.
            "quota_exhausted": 0,
            "queued_retries": 0,
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

    # --- capability pre-checks ---------------------------------------------

    def _estimated_context(self, system: str, messages: list, max_tokens: int) -> int:
        """Roughly how many tokens this request needs, reply included.

        Deliberately crude, and only ever compared against a window a provider
        *declared*. It exists to catch "this conversation is four times the
        window", not to shave the last ten per cent."""
        text = len(system or "")
        for message in messages or []:
            text += len(str(message.get("content", "") if isinstance(message, dict) else message))
        return text // _CHARS_PER_TOKEN + max_tokens

    def _capability_block(self, system: str, messages: list, tools: list,
                          max_tokens: int) -> tuple[str, str] | None:
        """A reason to escalate *without* attempting local, or None.

        §4.1 says local attempts every request, and then lists two exceptions
        that are about the request rather than the answer: a tool the local
        model cannot invoke, and a context length it cannot hold. Both are here.

        **Only a declared incapacity counts.** A local tier that says nothing
        about tools gets the request and is allowed to fail at it; an absent
        attribute is not a claim, and inferring one would turn "we do not know"
        into "do not try", which is how local-first quietly stops happening.
        That is the difference between this and `app/model_tiering.py`'s hard
        boundary, which sends every tool-carrying request to the capable model
        on suspicion - the right rule there, because both tiers could run it,
        and the wrong rule here, because skipping local is the thing this task
        exists to stop."""
        if tools and getattr(self.local, "supports_tools", None) is False:
            return model_calls.REASON_TOOL_REQUIRED, LOCAL_NO_TOOLS
        window = getattr(self.local, "context_window", None)
        if isinstance(window, int) and window > 0:
            needed = self._estimated_context(system, messages, max_tokens)
            if needed > window:
                return (model_calls.REASON_CONTEXT_LENGTH,
                        f"{LOCAL_CONTEXT_EXCEEDED} (about {needed} tokens against a "
                        f"declared window of {window})")
        return None

    @staticmethod
    def _log_reason(escalation: str) -> str:
        """The closed-vocabulary code for a human escalation sentence."""
        for sentence, code in _LOG_REASONS.items():
            if escalation.startswith(sentence):
                return code
        return model_calls.REASON_LOCAL_ERROR

    @staticmethod
    def _is_quota(bad: BaseException) -> bool:
        """Whether a provider failure was exhausted capacity.

        Asks the exception rather than importing the provider's class: the
        router is the one place that must work with a second remote provider
        the day there is one, and `model_call_outcome` is the contract
        `app/model_calls.classify` already reads."""
        return getattr(bad, model_calls.OUTCOME_ATTRIBUTE, None) == \
            model_calls.OUTCOME_QUOTA_EXHAUSTED

    # --- quota exhaustion (§4.2) -------------------------------------------

    def _after_quota(self, bad: BaseException, local_answer, escalation: str):
        """What happens when the remote model has nothing left.

        §4.2, in its four numbered parts:

        1. Nothing about the API's state reaches the user. Every path out of
           here either returns an answer or raises `ModelUnavailableNow`, whose
           user-facing wording is `app/user_messages.py`'s and contains no
           number, no limit and no vendor.
        2. The local model's best attempt is returned if there is one. "Best
           attempt" means an answer the local tier actually produced and that
           the router was escalating for some *other* reason, most usually low
           confidence: an answer judged imperfect is better than no answer, and
           the judgement that sent it upstream does not make it worthless.
        3. Otherwise the request is queued and the refusal says so in Krish's
           own words.
        4. WARN, once, with the operator's version of the sentence. Not ERROR:
           nothing is broken, and a page for a spent allowance would train
           somebody to ignore the pager."""
        self.counts["quota_exhausted"] += 1
        LOG.warning(
            "the remote model reported exhausted capacity; falling back rather than "
            "surfacing it. detail=%s local_answer_available=%s",
            user_messages.for_operator(bad), local_answer is not None)

        if local_answer is not None:
            self._record("local", str(getattr(self.local, "model", "local")), None,
                         QUOTA_LOCAL_FALLBACK, getattr(local_answer, "usage", None))
            return local_answer

        self.counts["queued_retries"] += 1
        retry_queue.enqueue(reason="remote capacity exhausted")
        raise ModelUnavailableNow(
            f"the remote model reported exhausted capacity and there is no local "
            f"answer to fall back on. Local: {escalation}. The request has been "
            f"queued for retry in {router_config.retry_after_seconds()}s and the "
            f"user is told only that this will be retried shortly.") from bad

    # --- the interface -----------------------------------------------------

    def complete(self, system: str, messages: list, tools: list, max_tokens: int = 2048):
        """Local first, then - and only then - Kimi.

        The shape §4.1 asks for, with every branch recorded:

            request -> router -> local attempt -> confidence assessment
                                   sufficient?   return the local answer
                                   insufficient? escalate

        `confidence.assess` returns "sufficient, unmeasured" today, so the
        escalations that happen are the availability ones. See
        docs/CONFIDENCE.md, which says that in more words rather than leaving
        somebody to deduce it from a threshold that never fires."""
        from app.model_budget import BudgetExceededError

        local_answer = None
        verdict = None
        routed_by = model_calls.ROUTED_BY_ROUTER

        usable, escalation = self.local_is_usable()
        if usable:
            blocked = self._capability_block(system, messages, tools, max_tokens)
            if blocked is not None:
                usable, escalation = False, blocked[1]

        if usable:
            started = time.monotonic()
            self.counts["local"] += 1
            try:
                with model_calls.routing_context(
                        routed_by=model_calls.ROUTED_BY_ROUTER,
                        escalation_reason=model_calls.REASON_NOT_APPLICABLE):
                    answer = self.local.complete(system, messages, tools,
                                                 max_tokens=max_tokens)
            except BudgetExceededError:
                # The ceiling stops work; it does not redirect it somewhere more
                # expensive. Escalating here would make crossing the budget cost
                # MORE than staying under it.
                raise
            except Exception as bad:
                escalation = f"{LOCAL_FAILED}: {bad}"
                routed_by = model_calls.ROUTED_BY_FALLBACK
                self.counts["escalated"] += 1
            else:
                verdict = confidence.assess(answer=answer, request=messages)
                if verdict.sufficient:
                    self._record("local", str(getattr(self.local, "model", "local")),
                                 started, "", getattr(answer, "usage", None))
                    return answer
                # An answer exists and was judged short. It is kept, because
                # §4.2 needs something to fall back to if the remote tier turns
                # out to have nothing left.
                local_answer = answer
                escalation = verdict.detail
                self.counts["escalated"] += 1
                self._record("local", str(getattr(self.local, "model", "local")),
                             started, verdict.detail, getattr(answer, "usage", None))

        if self.remote is None:
            self.counts["failed"] += 1
            raise self._no_remote(escalation)

        reason = (model_calls.REASON_LOW_CONFIDENCE if local_answer is not None
                  else self._log_reason(escalation))
        started = time.monotonic()
        self.counts["remote"] += 1
        try:
            with model_calls.routing_context(
                    routed_by=routed_by, escalation_reason=reason,
                    confidence_score=verdict.score if verdict else None,
                    confidence_threshold=verdict.threshold if verdict else None):
                answer = self.remote.complete(system, messages, tools, max_tokens=max_tokens)
        except BudgetExceededError:
            raise
        except Exception as bad:
            if self._is_quota(bad):
                return self._after_quota(bad, local_answer, escalation)
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
        seam. The choice itself is identical to `complete`'s, minus the
        confidence assessment - there is no answer to assess until the stream
        has been consumed, and by then it has been read.

        **Not a generator**, deliberately. A generator would defer the tier
        choice until the caller iterated, which would move an unservable request
        from a raise at the call site to a raise inside somebody's `for` loop,
        and would leave the routing context closed by the time the provider ran.
        The choice is made here; only the quota guard is deferred, because that
        failure genuinely arrives during consumption."""
        usable, escalation = self.local_is_usable()
        if usable:
            blocked = self._capability_block(system, messages, tools, max_tokens)
            if blocked is not None:
                usable, escalation = False, blocked[1]

        if usable:
            self.counts["local"] += 1
            self._record("local", str(getattr(self.local, "model", "local")), None, "")
            with model_calls.routing_context(
                    routed_by=model_calls.ROUTED_BY_ROUTER,
                    escalation_reason=model_calls.REASON_NOT_APPLICABLE):
                return self.local.stream(system, messages, tools, max_tokens=max_tokens)

        if self.remote is None:
            self.counts["failed"] += 1
            raise self._no_remote(escalation)

        self.counts["remote"] += 1
        self._record("remote", self._remote_model_name(), None, escalation)
        with model_calls.routing_context(
                routed_by=model_calls.ROUTED_BY_ROUTER,
                escalation_reason=self._log_reason(escalation)):
            events = self.remote.stream(system, messages, tools, max_tokens=max_tokens)
        return self._guarded(events, escalation)

    def _guarded(self, events, escalation: str):
        """Pass a stream through, turning exhausted capacity into a queued retry.

        The provider's `stream` returns an iterator whose body runs while the
        caller consumes it, so a quota refusal arrives here rather than at the
        call above. There is nothing to fall back to - the local tier was not
        chosen, and a stream cannot be restarted on another model without the
        reader seeing the seam - so this queues and raises the user-safe
        refusal."""
        from app.model_budget import BudgetExceededError

        try:
            for event in events:
                yield event
        except BudgetExceededError:
            raise
        except Exception as bad:
            if self._is_quota(bad):
                self._after_quota(bad, None, escalation)
            raise

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
            "confidence": confidence.describe(),
            "policy": router_config.describe(),
            "call_log": str(model_calls.log_path()),
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
        "quota_exhaustions": counts.get("quota_exhausted", 0),
        "queued_retries": counts.get("queued_retries", 0),
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
