"""One record per model call, written below the router so a call that skipped
the router is still recorded (Task 01, Deliverable A).

## Why this is not `LocalFirstRouter._record`

The router already logged a line per call. That line cannot answer the question
this task exists to answer, and no amount of extending it could: **it is written
by the router, so a code path that never reached the router produces no line at
all.** A log that can only see compliant callers reports perfect compliance.

So the instrumentation moved down. `KimiProvider` records inside its own
`complete`/`stream`, at the point the HTTP request is about to leave, below the
`_transport` seam and below anything a caller could substitute. A local provider
is recorded by `InstrumentedProvider`, which is the lowest layer this repository
owns for a tier whose implementation arrives later.

`routed_by` is the field that carries the finding:

- `router` — the router set a routing context immediately before the call.
- `direct_call` — **a bug.** Something reached a model without the router.
- `fallback_after_error` — the router called a second tier after the first
  failed.

## The guard, and why it raises for some callers and not others

A `direct_call` from `agents/`, `backend/`, `gateway/` or from `app/` outside
the routing modules is refused with `DirectModelCallError`, after the record is
written — the record first, because a refusal that left no trace would make the
bug harder to find than the behaviour it prevents.

A `direct_call` from anywhere else is recorded and allowed. That is not a
loophole left open by accident: the test suite constructs `KimiProvider`
directly on purpose (`tests/test_kimi_provider.py` is the conformance suite for
the wire format and would be testing the router otherwise), and so would an
operational probe. A guard that made the provider untestable in isolation would
be removed within a week, and a removed guard enforces nothing.
`tests/test_no_direct_model_calls.py` is the static half that covers what this
half deliberately allows.

## Context travels in contextvars, and streams capture it eagerly

A request id has to be shared across every call serving one user turn, and the
turn is a tool loop several calls deep. Threading an id through
`ModelProvider.complete`'s signature would change an interface four agents and
two chat surfaces implement against, to carry something none of them has an
opinion about.

The trap, found while writing this: `provider.stream(...)` returns a generator
whose body does not run until the caller iterates it, by which point the
router's `with` block has exited and the contextvar is back to its old value.
So `capture()` is called **eagerly**, in the function that returns the
generator, and the snapshot it returns is what the generator records against.
A contextvar read inside a deferred generator body is a bug that looks like
working code.

## What is never written

No prompt, no message content beyond the 200-character summary of what the user
originally typed, no system prompt, no tool arguments, no credential, no header.
`app/model_routing._record`'s rule, kept: the prompt is the one thing in a model
call certain to contain something private.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import jsonlog

SCHEMA_VERSION = 1

LOG = logging.getLogger("model.calls")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Where the JSONL lands. Environment-first for the same reason every database
# path in this project is: the test suite must be able to redirect it before
# anything writes, and a module-level constant resolved at import is already
# too late (tests/conftest.py).
LOG_DIR_ENV = "MODEL_CALL_LOG_DIR"
LOG_FILE_NAME = "model_calls.jsonl"

# §3.2: "Log rotation: daily, keep 30 days."
RETENTION_DAYS = 30

# §3.1: "first 200 chars of the originating user input".
SUMMARY_CHARS = 200

# --- closed vocabularies, fail-closed on write --------------------------------
#
# Every one of these ends up in a report Krish reads. A field that can hold any
# string is a field nobody can group by.

HANDLER_LOCAL = "local"
HANDLER_KIMI = "kimi_k2"
HANDLERS = (HANDLER_LOCAL, HANDLER_KIMI)

ROUTED_BY_ROUTER = "router"
ROUTED_BY_DIRECT = "direct_call"
ROUTED_BY_FALLBACK = "fallback_after_error"
ROUTED_BY = (ROUTED_BY_ROUTER, ROUTED_BY_DIRECT, ROUTED_BY_FALLBACK)

REASON_LOW_CONFIDENCE = "low_confidence"
REASON_TOOL_REQUIRED = "tool_required"
REASON_CONTEXT_LENGTH = "context_length"
REASON_LOCAL_ERROR = "local_error"
REASON_QUOTA_RETRY = "quota_retry"
REASON_NOT_APPLICABLE = "not_applicable"
ESCALATION_REASONS = (
    REASON_LOW_CONFIDENCE, REASON_TOOL_REQUIRED, REASON_CONTEXT_LENGTH,
    REASON_LOCAL_ERROR, REASON_QUOTA_RETRY, REASON_NOT_APPLICABLE,
)

# The four escalation reasons §4.1 permits. `quota_retry` is not one of them -
# it is what a retry *after* an escalation records - and `not_applicable` means
# the call never left local. Named as a set because the self-diagnosis in
# Deliverable C decides "avoidable" against exactly this list.
PERMITTED_ESCALATIONS = (
    REASON_LOW_CONFIDENCE, REASON_TOOL_REQUIRED, REASON_CONTEXT_LENGTH,
    REASON_LOCAL_ERROR,
)

OUTCOME_SUCCESS = "success"
OUTCOME_ERROR = "error"
OUTCOME_QUOTA_EXHAUSTED = "quota_exhausted"
OUTCOME_TIMEOUT = "timeout"
OUTCOMES = (OUTCOME_SUCCESS, OUTCOME_ERROR, OUTCOME_QUOTA_EXHAUSTED, OUTCOME_TIMEOUT)

# An exception may declare its own outcome by carrying this attribute, so that
# `app/kimi_provider.py` classifies its own failures rather than this module
# pattern-matching on message text from another file.
OUTCOME_ATTRIBUTE = "model_call_outcome"

# Packages whose code is the application runtime. A direct call from one of
# these is refused; a direct call from `tests`, `simulation`, `scripts` or an
# interactive session is recorded and allowed. See the module docstring.
RUNTIME_PACKAGES = ("agents", "backend", "gateway", "app")

# Modules that are the plumbing rather than a caller. `caller_module` skips
# them when walking the stack, so the field names the agent or the route that
# wanted an answer rather than the wrapper nearest the socket. `app.model_calls`
# is first because this file is always on the stack.
_PLUMBING_MODULES = (
    "app.model_calls", "app.model_routing", "app.model_gateway",
    "app.model_budget", "app.model_tiering", "app.kimi_provider",
    "app.model_provider", "contextlib",
)


class DirectModelCallError(RuntimeError):
    """A runtime module reached a model without the router.

    §4.1's single choke point, enforced rather than described. The record is
    written before this is raised: a guard that hid the event it fired on would
    be worse than no guard, because the only evidence would be a stack trace in
    whatever swallowed it."""


# --- the request, shared across every call serving one user turn --------------


class _Request:
    """One originating user request, and the calls made to serve it.

    `index` is mutable and shared, which is the point: the tool loop in
    `gateway/conversation.run_turn` makes several calls and `call_index` has to
    put them in order."""

    __slots__ = ("request_id", "summary", "index")

    def __init__(self, request_id: str, summary: str | None):
        self.request_id = request_id
        self.summary = summary
        self.index = 0

    def next_index(self) -> int:
        current = self.index
        self.index += 1
        return current


_REQUEST: contextvars.ContextVar[_Request | None] = contextvars.ContextVar(
    "model_call_request", default=None)
_ROUTING: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "model_call_routing", default=None)


def summarise(user_input: str | None) -> str | None:
    """The first 200 characters of what the user typed, or None.

    None rather than an empty string when an agent initiated the work on its
    own: "nobody asked for this in words" is a fact the self-diagnosis reads,
    and it is not the same as "they asked for nothing"."""
    text = (user_input or "").strip()
    if not text:
        return None
    return text[:SUMMARY_CHARS]


@contextlib.contextmanager
def request_context(user_input: str | None = None, request_id: str | None = None):
    """Everything inside belongs to one user request.

    Nested calls reuse the outer request rather than starting a second one - a
    tool loop inside a turn is still that turn. Passing `request_id` explicitly
    is for a queued retry, which is the same request served again and should
    carry the id it was queued under."""
    existing = _REQUEST.get()
    if existing is not None and request_id is None:
        yield existing.request_id
        return
    record = _Request(request_id or str(uuid.uuid4()), summarise(user_input))
    token = _REQUEST.set(record)
    try:
        yield record.request_id
    finally:
        _REQUEST.reset(token)


def current_request_id() -> str | None:
    request = _REQUEST.get()
    return request.request_id if request is not None else None


@contextlib.contextmanager
def routing_context(*, routed_by: str = ROUTED_BY_ROUTER,
                    escalation_reason: str = REASON_NOT_APPLICABLE,
                    confidence_score: float | None = None,
                    confidence_threshold: float | None = None):
    """The router, declaring that the call about to be made is its own.

    The absence of this context is what `direct_call` means, so it is
    deliberately not something a provider can set for itself."""
    _check(routed_by, ROUTED_BY, "routed_by")
    _check(escalation_reason, ESCALATION_REASONS, "escalation_reason")
    token = _ROUTING.set({
        "routed_by": routed_by,
        "escalation_reason": escalation_reason,
        "confidence_score": confidence_score,
        "confidence_threshold": confidence_threshold,
    })
    try:
        yield
    finally:
        _ROUTING.reset(token)


class Snapshot:
    """The context as it was when a call began.

    Exists because of the generator trap in the module docstring: a streaming
    call is *created* inside the router's routing context and *runs* outside
    it."""

    __slots__ = ("request_id", "summary", "call_index", "routing", "caller_module")

    def __init__(self, request_id, summary, call_index, routing, caller_module):
        self.request_id = request_id
        self.summary = summary
        self.call_index = call_index
        self.routing = routing
        self.caller_module = caller_module

    @property
    def routed_by(self) -> str:
        return self.routing["routed_by"] if self.routing else ROUTED_BY_DIRECT


def capture(*, skip_modules: tuple[str, ...] = ()) -> Snapshot:
    """Freeze the calling context. Call this eagerly, before any `yield`."""
    request = _REQUEST.get()
    if request is None:
        # A model call with no declared request still gets a record and an id.
        # An untraceable call is exactly the kind this task is looking for, and
        # dropping it would be the log agreeing with the bug.
        request = _Request(str(uuid.uuid4()), None)
    return Snapshot(
        request_id=request.request_id,
        summary=request.summary,
        call_index=request.next_index(),
        routing=_ROUTING.get(),
        caller_module=caller_module(skip_modules),
    )


# --- who asked ----------------------------------------------------------------


def _module_name(filename: str) -> str:
    path = Path(filename)
    try:
        relative = path.resolve().relative_to(PROJECT_ROOT)
    except (ValueError, OSError):
        return path.stem
    return ".".join(relative.with_suffix("").parts)


def caller_module(skip_modules: tuple[str, ...] = ()) -> str:
    """`module.path::function` of the first frame that is not plumbing.

    Walks outwards from this call rather than taking a fixed depth, because the
    depth differs between `complete` (three frames) and `stream` (a generator,
    a context manager and a wrapper). A fixed number would name a different
    thing depending on which path ran, which is the one property this field
    must not have."""
    skip = set(_PLUMBING_MODULES) | set(skip_modules)
    for frame in reversed(traceback.extract_stack()[:-1]):
        module = _module_name(frame.filename)
        if module in skip or module.startswith("importlib"):
            continue
        return f"{module}::{frame.name}"
    return "unknown"


def _is_runtime_caller(caller: str) -> bool:
    module = caller.split("::", 1)[0]
    root = module.split(".", 1)[0]
    if root not in RUNTIME_PACKAGES:
        return False
    return module not in _PLUMBING_MODULES


# --- the record ---------------------------------------------------------------


def _check(value, vocabulary: tuple[str, ...], field: str) -> str:
    if value not in vocabulary:
        raise ValueError(
            f"{field}={value!r} is not one of {vocabulary}. Refusing rather than "
            f"writing a value nothing can group by - this log is read as a report.")
    return value


def log_dir() -> Path:
    configured = (os.environ.get(LOG_DIR_ENV, "") or "").strip()
    return Path(configured) if configured else PROJECT_ROOT / "logs"


def log_path() -> Path:
    return log_dir() / LOG_FILE_NAME


def retention_days() -> int:
    """How many days of rotated logs to keep.

    Read from `config/router.yaml` rather than the constant below, which is what
    §3.2 asked for and what the config file has documented since it was written -
    the value was validated and exposed and then never consulted, so editing it
    did nothing. Falls back to the constant when the config cannot be read,
    because a log write must not fail on a policy file."""
    try:
        from app import router_config

        return int(router_config.retention_days())
    except Exception:  # noqa: BLE001 - telemetry never fails on configuration
        return RETENTION_DAYS


# Rotation and pruning moved to `app/jsonlog.py` when the event log arrived
# and was about to become a second copy of them. The behaviour is unchanged,
# including the deliberate tolerance of two processes racing to rename - see
# that module's docstring for why that trade is the right one.


def _rotate(path: Path, today: str) -> None:
    jsonlog.rotate(path, today, retention_days=retention_days())


def _prune(directory: Path, stem: str, suffix: str, today: str) -> None:
    jsonlog.prune(directory, stem, suffix, today, retention_days=retention_days())


def write(record: dict) -> dict:
    """Append one record to the JSONL and emit it at DEBUG. Returns it.

    A failure to write is swallowed and reported at WARNING rather than raised.
    This is telemetry wrapped around the one call the user is waiting for, and
    a full disk must not become a failed answer."""
    line = json.dumps(record, default=str)
    LOG.debug(line)
    try:
        directory = log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / LOG_FILE_NAME
        _rotate(path, record["timestamp"][:10])
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError as bad:  # pragma: no cover - a full or read-only disk
        LOG.warning("could not append to the model call log: %s", bad)
    return record


def build_record(*, handler: str, routed_by: str, escalation_reason: str,
                 outcome: str, request_id: str, user_request_summary: str | None,
                 call_index: int, caller: str, latency_ms: int,
                 confidence_score: float | None = None,
                 confidence_threshold: float | None = None,
                 prompt_tokens: int | None = None,
                 completion_tokens: int | None = None,
                 error_detail: str | None = None) -> dict:
    """§3.1's schema, in §3.1's field order, fail-closed on the vocabularies."""
    _check(handler, HANDLERS, "handler")
    _check(routed_by, ROUTED_BY, "routed_by")
    _check(escalation_reason, ESCALATION_REASONS, "escalation_reason")
    _check(outcome, OUTCOMES, "outcome")
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "user_request_summary": user_request_summary,
        "call_index": call_index,
        "handler": handler,
        "routed_by": routed_by,
        "escalation_reason": escalation_reason,
        "confidence_score": confidence_score,
        "confidence_threshold": confidence_threshold,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "latency_ms": latency_ms,
        "outcome": outcome,
        "error_detail": error_detail,
        "caller_module": caller,
    }


def classify(exc: BaseException) -> str:
    """The outcome an exception represents.

    An exception may name its own (`model_call_outcome`), which is how
    `app/kimi_provider.py` reports quota exhaustion without this module reading
    another file's message strings. Timeouts are recognised by class name
    because the two that can arrive here - `httpx.TimeoutException` and the
    builtin - share no base class, and importing httpx to check would put a
    network library's import cost inside an exception handler."""
    declared = getattr(exc, OUTCOME_ATTRIBUTE, None)
    if declared in OUTCOMES:
        return declared
    if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower():
        return OUTCOME_TIMEOUT
    return OUTCOME_ERROR


class Recording:
    """One call in progress. Yielded by `record_call`.

    The provider reports what it learned - the tokens the vendor said it spent,
    an outcome it wants to name - and the timing, the context and the schema
    are this module's problem."""

    __slots__ = ("snapshot", "handler", "_started", "_prompt_tokens",
                 "_completion_tokens", "_outcome", "_error", "record")

    def __init__(self, snapshot: Snapshot, handler: str):
        self.snapshot = snapshot
        self.handler = handler
        self._started = time.monotonic()
        self._prompt_tokens = None
        self._completion_tokens = None
        self._outcome = OUTCOME_SUCCESS
        self._error = None
        self.record = None

    def usage(self, prompt_tokens: int | None, completion_tokens: int | None) -> None:
        """What the provider said it spent. None stays None: the ledger's rule,
        that "not reported" is a different fact from zero."""
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens

    def outcome(self, outcome: str, detail: str | None = None) -> None:
        self._outcome = _check(outcome, OUTCOMES, "outcome")
        self._error = detail

    def _emit(self) -> dict:
        routing = self.snapshot.routing or {}
        self.record = write(build_record(
            handler=self.handler,
            routed_by=self.snapshot.routed_by,
            escalation_reason=routing.get("escalation_reason", REASON_NOT_APPLICABLE),
            outcome=self._outcome,
            request_id=self.snapshot.request_id,
            user_request_summary=self.snapshot.summary,
            call_index=self.snapshot.call_index,
            caller=self.snapshot.caller_module,
            latency_ms=int((time.monotonic() - self._started) * 1000),
            confidence_score=routing.get("confidence_score"),
            confidence_threshold=routing.get("confidence_threshold"),
            prompt_tokens=self._prompt_tokens,
            completion_tokens=self._completion_tokens,
            error_detail=self._error,
        ))
        return self.record


def guard(snapshot: Snapshot, handler: str) -> None:
    """§4.1's runtime guard. Records the event, then refuses it."""
    if snapshot.routed_by != ROUTED_BY_DIRECT:
        return
    if not _is_runtime_caller(snapshot.caller_module):
        return
    write(build_record(
        handler=handler, routed_by=ROUTED_BY_DIRECT,
        escalation_reason=REASON_NOT_APPLICABLE, outcome=OUTCOME_ERROR,
        request_id=snapshot.request_id, user_request_summary=snapshot.summary,
        call_index=snapshot.call_index, caller=snapshot.caller_module,
        latency_ms=0,
        error_detail="refused: a runtime module called a model without the router",
    ))
    raise DirectModelCallError(
        f"{snapshot.caller_module} called the {handler} model without going "
        f"through app/model_routing.LocalFirstRouter. Every external call goes "
        f"through one choke point (Task 01 §4.1) so that local-first is a "
        f"property of the code rather than of everybody remembering. Call "
        f"app.model_gateway.default_provider() instead. This call was recorded "
        f"in the model call log before being refused.")


@contextlib.contextmanager
def record_call(handler: str, snapshot: Snapshot | None = None):
    """Wrap one model call. Records it whatever happens to it.

    `snapshot` is passed by streaming callers, which captured their context
    eagerly; everything else lets this capture at entry."""
    _check(handler, HANDLERS, "handler")
    taken = snapshot if snapshot is not None else capture()
    guard(taken, handler)
    recording = Recording(taken, handler)
    try:
        yield recording
    except GeneratorExit:
        # The caller stopped consuming a stream - a closed browser tab, most
        # often. That is not an error, and recording it as one inflated the
        # nightly report's error count with every abandoned reply. The call is
        # still recorded, with what it managed to produce.
        recording.outcome(OUTCOME_SUCCESS, "the caller stopped reading the stream")
        recording._emit()
        raise
    except BaseException as bad:
        recording.outcome(classify(bad), f"{type(bad).__name__}: {bad}")
        recording._emit()
        raise
    recording._emit()


class InstrumentedProvider:
    """A `ModelProvider` that records every call made through it.

    The local tier's equivalent of the recording built into `KimiProvider`. A
    wrapper rather than a change to the local provider because the local
    provider does not exist yet and will arrive from
    `app/local_ai.LocalAIService`: the day it does, it is wrapped here and is
    logged on the first call it ever serves, which is the ordering the rest of
    this repository already insists on.

    `inner` is the attribute name `app/model_routing._WRAPPED_ATTRIBUTES`
    already walks, so `assert_no_anthropic` sees straight through this."""

    def __init__(self, inner, handler: str = HANDLER_LOCAL):
        self.inner = inner
        self.handler = _check(handler, HANDLERS, "handler")

    @property
    def model(self) -> str:
        return str(getattr(self.inner, "model", self.handler))

    @property
    def name(self) -> str:
        return str(getattr(self.inner, "name", self.handler))

    def __getattr__(self, attribute: str):
        """Anything this wrapper does not define belongs to what it wraps.

        Needed rather than tidy: `LocalFirstRouter._capability_block` asks the
        local tier whether it can invoke tools and how wide its context window
        is, and a wrapper that swallowed those questions would answer "does not
        say" to both - which the router reads as "attempt it anyway". The
        instrumentation would then have silently changed a routing decision,
        which is the one thing instrumentation must never do.

        Only reached for attributes that are genuinely absent here, so `inner`,
        `handler`, `model`, `name`, `complete` and `stream` never come through
        it and there is no recursion risk on `inner` itself."""
        if attribute.startswith("__"):
            raise AttributeError(attribute)
        return getattr(self.inner, attribute)

    def complete(self, system: str, messages: list, tools: list, max_tokens: int = 2048):
        with record_call(self.handler) as call:
            answer = self.inner.complete(system, messages, tools, max_tokens=max_tokens)
            usage = getattr(answer, "usage", None)
            call.usage(getattr(usage, "input_tokens", None),
                       getattr(usage, "output_tokens", None))
            return answer

    def stream(self, system: str, messages: list, tools: list, max_tokens: int = 2048):
        # Eager capture, deferred body. See the module docstring.
        snapshot = capture()
        return self._stream(snapshot, system, messages, tools, max_tokens)

    def _stream(self, snapshot: Snapshot, system, messages, tools, max_tokens):
        with record_call(self.handler, snapshot) as call:
            for event in self.inner.stream(system, messages, tools, max_tokens=max_tokens):
                if event.get("type") == "final":
                    usage = event.get("usage") or {}
                    call.usage(usage.get("input_tokens"), usage.get("output_tokens"))
                yield event


def read_records(since: datetime | None = None, until: datetime | None = None,
                 directory: Path | None = None) -> list[dict]:
    """Every record in the window, live file and rotated files together.

    Unparseable lines are skipped rather than raising. A log read is a report,
    and a report that refuses to run because one line was truncated by a crash
    is a report nobody gets on the morning it matters."""
    directory = directory or log_dir()
    if not directory.exists():
        return []
    records: list[dict] = []
    stem = Path(LOG_FILE_NAME).stem
    suffix = Path(LOG_FILE_NAME).suffix
    for path in sorted(directory.glob(f"{stem}*{suffix}")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict) or "timestamp" not in record:
                continue
            moment = _parse(record["timestamp"])
            if moment is None:
                continue
            if since is not None and moment < since:
                continue
            if until is not None and moment >= until:
                continue
            records.append(record)
    records.sort(key=lambda item: (item.get("timestamp", ""), item.get("call_index", 0)))
    return records


def _parse(stamp: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
