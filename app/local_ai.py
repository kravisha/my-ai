"""Local intelligence behind one interface, whichever runtime supplies it
(TASK_QUEUE TQ-56, docs/SPEC_RECONCILIATION.md §107).

Source: addendum 45 §4 (the service), §5 (the candidate pool), §15 (challenger
comparisons), §16 (agents do not choose models), §35 (hardware-aware routing),
§44 (model setup), §45 Phase A + B, §47.

## Nothing is behind this yet, and that is the increment

There is no local model on this machine, no runtime installed, and no download.
What exists is the interface every local model will arrive behind, and a
conformance suite written *before* the second implementation.

That ordering is the whole point, and §101 is why it is trusted enough to repeat:
**a contract with a single implementation is a description of that
implementation.** The suite is what turns it into a contract. The guard applied
to every contract test there, applied again here:

> Could a provider that must load a multi-gigabyte model off disk satisfy this?
> If it needs an in-process stub, the test is wrong.

## Agents never call a local model directly

Addendum 45 §4 and §47 are explicit, and it is the reason this file exists rather
than agents importing a runtime each. `test_no_module_reaches_a_local_runtime_directly`
scans for imports of every known local runtime outside this module — a tripwire
planted before the thing it guards, the way §64's routing pin was, so the day a
runtime arrives it lands in one place or fails the suite.

## `infer()` refuses, and says which increment fixes it

§4's interface has both `infer(request)` — run this, you pick the model — and
`infer_with_model(model_id, request)`.

The first cannot be honestly implemented yet. Picking a model needs the
leaderboard *and* privacy, hardware load, availability and budget (§18, §35,
§36), which is TQ-60's whole entry. §16 is equally clear that the *agent* must
not pick either. So `infer` is declared, refuses with a reason naming TQ-60, and
callers can be written against the final shape today.

That is §101's declared-and-unbuilt pattern, one layer down: a refusal carrying a
sentence somebody can act on beats a method that quietly picks the only model
installed and calls that routing.

## A cold load is not slow thinking

`InferenceResult.loaded_from_cold` exists because of a finding recorded in §102
before any of this was built: this machine has **8 GB of VRAM**, so a leader and
a challenger cannot both be resident, and §15's comparisons are sequential.

The trap that sets: a model that had to be loaded from disk did not take longer
to *think*. Left unseparated, the ranking learns about SSD speed and files it as
reasoning quality. So the result carries whether the load was cold, and
`latency_ms` excludes it — `load_ms` is its own field. TQ-61 must score them
apart.

## What this abstracts

§4's list: runtime, prompt formatting, tokenizer, quantization, GPU/CPU
execution, model loading and unloading, batching, context limits, concurrency,
health checks, hardware monitoring. None of it appears in a caller's code — a
caller sends an `InferenceRequest` and receives an `InferenceResult`, and the
words "quantization" and "VRAM" appear in this file's types rather than in the
agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

SCHEMA_VERSION = 1

# Every local runtime this project knows the name of. The tripwire scans for
# imports of these outside this module (§4, §47).
#
# Listed before any is installed on purpose: a name added to the pool later is
# added here in the same increment, and the alternative - writing the tripwire
# once something has already leaked - is how the rule gets discovered to have
# been broken for a month.
KNOWN_LOCAL_RUNTIMES = (
    "ollama", "llama_cpp", "llama_cpp_python", "transformers", "vllm",
    "ctransformers", "exllamav2", "mlx_lm", "gpt4all", "text_generation",
)


class LocalAIError(RuntimeError):
    """Base for everything this service refuses."""


class LocalServiceUnavailable(LocalAIError):
    """No local intelligence is available, and this says why in a sentence
    somebody can act on.

    Not an empty result and not a fallback to an external model: a caller that
    asked for local inference and silently got something else would defeat §36's
    privacy rule, which is the one reason a task is ever pinned local."""


class UnknownModel(LookupError):
    """A model this service does not have. Fail closed - never substitute the
    nearest thing, because "the model I actually ran" is a fact every routing
    record depends on."""


class CapabilityUnavailable(NotImplementedError):
    """This service cannot answer that, and says why rather than guessing.

    The §101 pattern: `get_model_resource_state` on a service with no hardware
    monitoring must refuse in words, not return zeros that read as "plenty of
    VRAM free"."""


@dataclass(frozen=True)
class InferenceRequest:
    """What a caller asks for, in terms no runtime owns.

    Deliberately not a list of provider message dicts: §4 requires prompt
    formatting to be the service's problem, and a caller that assembled
    chat-template turns would be written against one runtime's convention."""

    prompt: str
    system: str | None = None
    max_tokens: int = 512
    stop: tuple[str, ...] = ()
    # The task this call serves, when the caller has one. Carried so a service
    # can honour context limits and so TQ-60 can record what was routed - never
    # read here to choose anything.
    task_category: str | None = None

    def __post_init__(self) -> None:
        if not (self.prompt or "").strip():
            raise ValueError("an inference request needs a prompt")
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")


@dataclass(frozen=True)
class InferenceResult:
    """What came back, in canonical form.

    `latency_ms` is **thinking time only**. A cold load goes in `load_ms`, for
    the reason in the module docstring: on 8 GB of VRAM a comparison is
    sequential, and a ranking that folded load time into latency would learn
    about disk speed and record it as reasoning quality (§102)."""

    model_id: str
    text: str
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None
    loaded_from_cold: bool = False
    load_ms: float | None = None

    def __post_init__(self) -> None:
        if self.loaded_from_cold and self.load_ms is None:
            raise ValueError(
                "a cold load must report load_ms separately from latency_ms - "
                "otherwise a slow disk is scored as slow thinking (§102)")
        if not self.loaded_from_cold and self.load_ms:
            raise ValueError("load_ms without a cold load is a contradiction")

    @property
    def wall_ms(self) -> float:
        """What the caller actually waited. The number a user feels, as opposed
        to the number a leaderboard should score."""
        return self.latency_ms + (self.load_ms or 0.0)


@dataclass(frozen=True)
class ModelCapabilities:
    """What a model can do, as measured or declared by its runtime.

    Unmeasured fields are `None`, never a vendor spec-sheet figure —
    `docs/model_registry.yaml`'s discipline, which this file is downstream of:
    *empirical or absent, never somebody else's claim wearing our authority*."""

    model_id: str
    context_window: int | None = None
    parameter_count: str | None = None
    quantization: str | None = None
    tool_support: bool = False
    streaming: bool = False
    # What it needs to run at all, which §35's hardware-aware routing reads.
    required_vram_mb: int | None = None


@dataclass(frozen=True)
class ModelHealth:
    """Whether the model is usable *right now*, and why not when it is not."""

    model_id: str
    healthy: bool
    detail: str
    loaded: bool = False

    def __post_init__(self) -> None:
        if not (self.detail or "").strip():
            raise ValueError("health without a reason is a boolean nobody can act on")


@dataclass(frozen=True)
class ResourceState:
    """What running this model would cost the machine right now (§35).

    `can_run_now` is the field routing reads. It is deliberately a decision this
    service makes rather than arithmetic a caller redoes: the service is the only
    thing that knows about loading, unloading, queueing and what else is
    resident."""

    model_id: str
    can_run_now: bool
    detail: str
    required_vram_mb: int | None = None
    available_vram_mb: int | None = None
    loaded: bool = False
    queue_depth: int = 0


@dataclass(frozen=True)
class BenchmarkCase:
    """One reproducible task two models can be asked to do (§15, §27).

    `expected` is optional because §38 is explicit that validation comes in
    several forms - a known answer is the cheapest, and where there is none an
    evaluator judges instead. A case with neither is a case nobody can score,
    and `benchmark` refuses it rather than recording an unscored run as a pass."""

    name: str
    request: InferenceRequest
    expected: str | None = None
    validator: str | None = None
    task_category: str | None = None

    def __post_init__(self) -> None:
        if not (self.name or "").strip():
            raise ValueError("a benchmark case needs a name")


@dataclass(frozen=True)
class BenchmarkRun:
    """What one model did on one case."""

    case: str
    model_id: str
    result: InferenceResult | None
    passed: bool | None
    detail: str = ""


class LocalAIService(Protocol):
    """What the rest of the system may assume about local intelligence,
    whichever runtime supplies it.

    A Protocol rather than an ABC, following `app/model_provider.ModelProvider`
    and `gateway/portfolio_providers.PortfolioProvider`: conformance is
    demonstrated by passing `LocalAIServiceContract`, not by inheriting."""

    name: str

    def list_models(self) -> list[str]: ...
    def get_model_capabilities(self, model_id: str) -> ModelCapabilities: ...
    def get_model_health(self, model_id: str) -> ModelHealth: ...
    def get_model_resource_state(self, model_id: str) -> ResourceState: ...
    def infer(self, request: InferenceRequest) -> InferenceResult: ...
    def infer_with_model(self, model_id: str, request: InferenceRequest) -> InferenceResult: ...
    def estimate_latency(self, model_id: str, request: InferenceRequest) -> float | None: ...
    def estimate_resource_cost(self, model_id: str, request: InferenceRequest) -> ResourceState: ...
    def benchmark(self, model_id: str, case: BenchmarkCase) -> BenchmarkRun: ...
    def compare_models(self, model_ids: list[str], case: BenchmarkCase) -> list[BenchmarkRun]: ...


# The refusal `infer` carries until routing exists. Written once, so the reason a
# caller sees is the same everywhere and says which increment changes it.
NO_ROUTING = (
    "I cannot choose a local model for you yet. Choosing needs the leaderboard "
    "and the constraints around it - privacy, hardware load, availability, "
    "budget - which is TQ-60. Call infer_with_model() with a model you have "
    "already chosen, or wait for routing."
)


class BaseLocalAIService:
    """The parts every implementation shares: the model check, the sequential
    comparison, and the refusals.

    Shared by inheritance only because both implementations here happen to be
    small. A service wrapping a real runtime implements the Protocol directly and
    shares none of this - which is the case the conformance suite is written for."""

    name = "base"

    def list_models(self) -> list[str]:
        return []

    def _require_model(self, model_id: str) -> str:
        if model_id not in self.list_models():
            raise UnknownModel(
                f"no local model {model_id!r}. Available: {self.list_models() or 'none'}. "
                "Refusing rather than substituting the nearest one - which model "
                "actually ran is a fact every routing record depends on.")
        return model_id

    def infer(self, request: InferenceRequest) -> InferenceResult:
        """Declared, and refuses. See NO_ROUTING and the module docstring."""
        raise LocalServiceUnavailable(NO_ROUTING)

    def compare_models(self, model_ids: list[str], case: BenchmarkCase) -> list[BenchmarkRun]:
        """§15's challenger comparison, run **sequentially and deliberately so**.

        This machine has 8 GB of VRAM (§102): a leader and a challenger cannot
        both be resident, so a parallel implementation would either thrash or
        silently run one of them on CPU and score it as slow. Sequential is the
        honest shape, and `InferenceResult.load_ms` is what keeps the loading it
        forces out of the latency each model is judged on."""
        if len(set(model_ids)) < 2:
            raise ValueError("a comparison needs at least two distinct models")
        return [self.benchmark(model_id, case) for model_id in model_ids]

    def estimate_latency(self, model_id: str, request: InferenceRequest) -> float | None:
        """None means "nobody has measured this model on this shape of request",
        which is a different statement from "it is instant"."""
        self._require_model(model_id)
        return None


class NoLocalModelsService(BaseLocalAIService):
    """The honest implementation for a machine with no local runtime installed —
    which is every machine this project runs on today.

    Not a placeholder and not a mock. It is the accurate description of the
    current situation, and having it means the interface is exercised, the
    conformance suite has a real subject, and the day TQ-57 installs a runtime
    the change is *adding* an implementation rather than replacing a stub nobody
    ever ran.

    Every method refuses with a sentence naming what is missing. None returns an
    empty success: a zero-latency empty completion would be indistinguishable
    from a model that had nothing to say."""

    name = "none"

    def list_models(self) -> list[str]:
        return []

    def _unavailable(self, what: str) -> LocalServiceUnavailable:
        return LocalServiceUnavailable(
            f"no local model runtime is installed, so I cannot {what}. Local "
            "intelligence arrives in TQ-57; until then every model call on this "
            "machine goes to an external provider, and a task pinned LOCAL_ONLY "
            "cannot run at all.")

    def get_model_capabilities(self, model_id: str) -> ModelCapabilities:
        raise self._unavailable(f"describe {model_id!r}")

    def get_model_health(self, model_id: str) -> ModelHealth:
        """The one method that answers rather than raising.

        "Is it healthy?" has a true answer here — no — and a caller polling
        health should get that answer rather than an exception. §17's failure
        behaviour is the same instinct: report the state, do not pretend it is
        unknowable."""
        return ModelHealth(
            model_id=model_id, healthy=False, loaded=False,
            detail="No local model runtime is installed on this machine (TQ-57).")

    def get_model_resource_state(self, model_id: str) -> ResourceState:
        """Also answers: `can_run_now` is False, which is exactly what §35's
        hardware-aware routing needs to hear. Returning zeros for VRAM would have
        read as "plenty free"; they are None, meaning nobody measured."""
        return ResourceState(
            model_id=model_id, can_run_now=False, loaded=False,
            detail="No local model runtime is installed on this machine (TQ-57).")

    def infer_with_model(self, model_id: str, request: InferenceRequest) -> InferenceResult:
        raise self._unavailable(f"run {model_id!r}")

    def estimate_resource_cost(self, model_id: str, request: InferenceRequest) -> ResourceState:
        return self.get_model_resource_state(model_id)

    def benchmark(self, model_id: str, case: BenchmarkCase) -> BenchmarkRun:
        """Returns a run with `passed=None` rather than raising or reporting
        False.

        The distinction is §38's: a model that could not be run has not failed a
        benchmark, it has not taken one. Recording it as a failure would penalise
        a model for this machine's missing runtime, which is precisely the kind of
        wrong signal a leaderboard cannot recover from."""
        return BenchmarkRun(
            case=case.name, model_id=model_id, result=None, passed=None,
            detail="Not run: no local model runtime is installed (TQ-57). Not a "
                   "failure - an absence of a result.")


# The service the rest of the system gets today. A module-level accessor rather
# than a constant so TQ-57 can swap what is returned without every caller
# importing a different name.
_SERVICE: LocalAIService = NoLocalModelsService()


def service() -> LocalAIService:
    """The local AI service. **The only supported way to reach local
    intelligence** (§4, §47) - agents never import a runtime."""
    return _SERVICE


def available() -> bool:
    """Whether any local model can be reached right now. The cheap question
    routing asks before the expensive one."""
    return bool(service().list_models())
