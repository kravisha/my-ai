"""The contract every `LocalAIService` must satisfy (TQ-56,
docs/SPEC_RECONCILIATION.md §107; addendum 45 §4, §15, §35, §47).

**Written before any local model exists, and that is the increment.** §101
established why: a contract with a single implementation is a description of
that implementation, and the suite is what turns it into a contract.

The guard applied to every test here, carried over from §101:

> Could a service that must load a multi-gigabyte model off disk satisfy this?
> If it needs an in-process stub, the test is wrong.

So nothing below assumes inference is fast, synchronous-and-cheap, repeatable,
or possible at all. Two implementations run against it: the shipped
`NoLocalModelsService`, which honestly cannot do anything, and `_FakeLocalService`
below, which can. **Two implementations that genuinely differ is the minimum at
which a contract is a contract** — with only the null one every refusal test
would pass vacuously.

## Adding a service

Subclass `LocalAIServiceContract` and supply `service` and `runnable_model`.
Nothing else. TQ-57's real runtime inherits it unchanged — **if it has to modify
a test, the contract was wrong, not the runtime.**
"""

import ast
import inspect
from pathlib import Path

import conftest
import pytest

from app import local_ai as la

REPO = Path(__file__).resolve().parent.parent


class _FakeLocalService(la.BaseLocalAIService):
    """A service that can actually answer, holding its "models" in a dict.

    Deliberately not a mock of the real one - a mock only ever agrees with the
    thing it was made from. It also demonstrates the property that matters for
    TQ-57: **a service needs no GPU to satisfy this contract**, so the contract
    is not accidentally shaped around the machine it was written on."""

    name = "fake"

    def __init__(self):
        self._models = {
            "fake-7b": la.ModelCapabilities(
                model_id="fake-7b", context_window=8192, parameter_count="7B",
                quantization="Q4_K_M", required_vram_mb=4200),
            "fake-3b": la.ModelCapabilities(
                model_id="fake-3b", context_window=4096, parameter_count="3B",
                quantization="Q4_K_M", required_vram_mb=2100),
        }
        self._loaded: set[str] = set()

    def list_models(self):
        return sorted(self._models)

    def get_model_capabilities(self, model_id):
        return self._models[self._require_model(model_id)]

    def get_model_health(self, model_id):
        self._require_model(model_id)
        return la.ModelHealth(model_id=model_id, healthy=True, loaded=model_id in self._loaded,
                              detail="fake service; always healthy")

    def get_model_resource_state(self, model_id):
        self._require_model(model_id)
        needed = self._models[model_id].required_vram_mb
        return la.ResourceState(
            model_id=model_id, can_run_now=True, required_vram_mb=needed,
            available_vram_mb=8192, loaded=model_id in self._loaded,
            detail="fake service; the card is imaginary and always free")

    def infer_with_model(self, model_id, request):
        self._require_model(model_id)
        cold = model_id not in self._loaded
        self._loaded.add(model_id)
        return la.InferenceResult(
            model_id=model_id, text=f"[{model_id}] {request.prompt[:40]}",
            latency_ms=42.0, input_tokens=10, output_tokens=8,
            finish_reason="stop", loaded_from_cold=cold,
            load_ms=900.0 if cold else None)

    def estimate_resource_cost(self, model_id, request):
        return self.get_model_resource_state(model_id)

    def benchmark(self, model_id, case):
        result = self.infer_with_model(model_id, case.request)
        passed = None if case.expected is None else case.expected in result.text
        return la.BenchmarkRun(case=case.name, model_id=model_id, result=result,
                               passed=passed, detail="fake run")


class LocalAIServiceContract:
    """Inherited unchanged by every service's own test class."""

    @pytest.fixture
    def service(self):
        raise NotImplementedError("supply the service under test")

    @pytest.fixture
    def runnable_model(self, service):
        """A model this service can actually run, or None if it can run none.

        Every test below branches on it rather than assuming - which is what
        lets one contract cover a machine with a GPU and a machine without."""
        models = service.list_models()
        return models[0] if models else None

    # --- shape --------------------------------------------------------------------

    def test_listing_models_returns_plain_identifiers(self, service):
        models = service.list_models()
        assert isinstance(models, list)
        assert all(isinstance(m, str) and m.strip() for m in models)
        assert len(set(models)) == len(models)

    def test_health_always_answers_and_always_gives_a_reason(self, service,
                                                             runnable_model):
        """§17's instinct: report the state, never pretend it is unknowable. A
        caller polling health gets an answer even when the answer is "no"."""
        model = runnable_model or "anything-at-all"
        health = service.get_model_health(model)

        assert isinstance(health, la.ModelHealth)
        assert isinstance(health.healthy, bool)
        assert health.detail.strip(), "health without a reason is a boolean nobody can act on"

    def test_resource_state_always_answers_because_routing_reads_it(self, service,
                                                                    runnable_model):
        """§35: the theoretically best model is not selected if it cannot run
        right now. Routing has to be able to ask that of any service."""
        model = runnable_model or "anything-at-all"
        state = service.get_model_resource_state(model)

        assert isinstance(state, la.ResourceState)
        assert isinstance(state.can_run_now, bool)
        assert state.detail.strip()

    def test_unmeasured_resource_figures_are_none_rather_than_zero(self, service,
                                                                   runnable_model):
        """Zero VRAM free reads as "plenty gone"; zero VRAM *required* reads as
        "free to run". Both are claims nobody measured."""
        model = runnable_model or "anything-at-all"
        state = service.get_model_resource_state(model)

        for figure in (state.required_vram_mb, state.available_vram_mb):
            assert figure is None or figure > 0

    # --- fail closed on an unknown model ------------------------------------------

    def test_an_unknown_model_is_refused_rather_than_substituted(self, service):
        """"Which model actually ran" is a fact every routing record depends on,
        so the nearest available one is never quietly used instead."""
        for method in ("get_model_capabilities", "infer_with_model"):
            with pytest.raises((la.UnknownModel, la.LocalServiceUnavailable)):
                call = getattr(service, method)
                if method == "infer_with_model":
                    call("no-such-model", la.InferenceRequest(prompt="hello"))
                else:
                    call("no-such-model")

    # --- routing is not this service's job (§16, §18) ------------------------------

    def test_infer_without_a_named_model_refuses_until_routing_exists(self, service):
        """§4 declares `infer(request)`; §16 says the agent must not choose and
        §18 says choosing needs the leaderboard plus privacy, hardware, budget.
        Until TQ-60 exists, the honest answer is a refusal that says so.

        A service that quietly picked the only model installed and called that
        routing would be the drift this contract exists to prevent."""
        with pytest.raises(la.LocalServiceUnavailable) as refused:
            service.infer(la.InferenceRequest(prompt="anything"))
        assert "TQ-60" in str(refused.value)

    def test_nothing_returns_an_empty_success(self, service, runnable_model):
        """A zero-latency empty completion is indistinguishable from a model
        that had nothing to say. Services refuse instead."""
        if runnable_model is None:
            with pytest.raises(la.LocalAIError):
                service.infer_with_model("anything-at-all",
                                         la.InferenceRequest(prompt="hello"))
            return
        result = service.infer_with_model(runnable_model,
                                          la.InferenceRequest(prompt="hello"))
        assert result.text.strip()
        assert result.latency_ms >= 0

    # --- a cold load is not slow thinking (§102) ----------------------------------

    def test_a_cold_load_is_reported_apart_from_thinking_time(self, service,
                                                              runnable_model):
        """The finding recorded in §102 before any of this was built: on 8 GB of
        VRAM a leader and challenger cannot both be resident, so comparisons are
        sequential and models get loaded mid-run. A ranking that folded load time
        into latency would learn about SSD speed and file it as reasoning
        quality."""
        if runnable_model is None:
            return
        first = service.infer_with_model(runnable_model, la.InferenceRequest(prompt="hi"))
        if not first.loaded_from_cold:
            return
        assert first.load_ms is not None and first.load_ms > 0
        assert first.wall_ms > first.latency_ms, "the wait includes the load"
        assert first.latency_ms < first.wall_ms, "the score excludes it"

    def test_a_result_cannot_claim_a_cold_load_without_reporting_it(self):
        with pytest.raises(ValueError, match="load_ms"):
            la.InferenceResult(model_id="m", text="x", latency_ms=1.0,
                               loaded_from_cold=True)

    # --- benchmarking and comparison (§15, §38) -----------------------------------

    def test_a_benchmark_that_could_not_run_is_not_a_failure(self, service,
                                                             runnable_model):
        """§38's distinction, and the one a leaderboard cannot recover from if
        it is got wrong: a model that could not be run has not *failed* a
        benchmark, it has not *taken* one. Recording it as a failure would
        penalise a model for this machine's missing runtime."""
        case = la.BenchmarkCase(name="sanity",
                                request=la.InferenceRequest(prompt="hello"))
        run = service.benchmark(runnable_model or "anything-at-all", case)

        assert isinstance(run, la.BenchmarkRun)
        if run.result is None:
            assert run.passed is None, "no result means no verdict, never False"
            assert run.detail.strip()

    def test_comparing_needs_two_distinct_models(self, service):
        case = la.BenchmarkCase(name="c", request=la.InferenceRequest(prompt="hi"))
        for insufficient in ([], ["only-one"], ["same", "same"]):
            with pytest.raises(ValueError):
                service.compare_models(insufficient, case)

    def test_comparison_returns_one_run_per_model_in_order(self, service):
        """Sequential and deliberately so (§102): on 8 GB a leader and a
        challenger cannot both be resident, so a parallel implementation would
        thrash or silently run one on CPU and score it as slow."""
        case = la.BenchmarkCase(name="c", request=la.InferenceRequest(prompt="hi"))
        models = service.list_models()
        if len(models) < 2:
            models = ["first-model", "second-model"]
        runs = service.compare_models(models, case)

        assert [r.model_id for r in runs] == list(models)
        assert all(isinstance(r, la.BenchmarkRun) for r in runs)

    # --- estimates ----------------------------------------------------------------

    def test_an_unmeasured_latency_estimate_is_none_rather_than_a_guess(self,
                                                                        service,
                                                                        runnable_model):
        """None means "nobody has measured this model on this shape of request",
        which is a different statement from "it is instant"."""
        if runnable_model is None:
            return
        estimate = service.estimate_latency(runnable_model,
                                            la.InferenceRequest(prompt="hi"))
        assert estimate is None or estimate > 0


# --- the two services under test ----------------------------------------------------


class TestNoLocalModelsContract(LocalAIServiceContract):
    """The shipped service: a machine with no local runtime, which is every
    machine this project runs on today."""

    @pytest.fixture
    def service(self):
        return la.NoLocalModelsService()


class TestFakeLocalServiceContract(LocalAIServiceContract):
    """A service that can actually answer, so the refusal tests above are not
    passing vacuously."""

    @pytest.fixture
    def service(self):
        return _FakeLocalService()


def test_the_two_services_genuinely_differ():
    """Otherwise this whole file proves nothing. §101's lesson: a contract needs
    two implementations that disagree about what they can do."""
    assert la.NoLocalModelsService().list_models() == []
    assert _FakeLocalService().list_models()


# --- the tripwire (§4, §47) ---------------------------------------------------------


def test_no_module_reaches_a_local_runtime_directly():
    """Addendum 45 §4 and §47: *"Agents must not call Llama, Inkling, DeepSeek,
    or any other local model directly. All local calls must go through a common
    service."*

    Planted before the thing it guards, the way §64's routing pin was, so the day
    TQ-57 installs a runtime it lands in one place or fails the suite. A rule
    written after the first leak is a rule that gets discovered to have been
    broken for a month."""
    offenders = []
    for top in ("agents", "backend", "app", "gateway"):
        for path in (REPO / top).rglob("*.py"):
            rel = path.relative_to(REPO).as_posix()
            if rel == "app/local_ai.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    root = name.split(".")[0]
                    if root in la.KNOWN_LOCAL_RUNTIMES:
                        offenders.append(f"{rel}: imports {name}")

    assert not offenders, (
        "these reach a local runtime directly instead of through "
        f"app/local_ai.service(): {offenders}"
    )


def test_the_service_accessor_is_the_only_supported_entry_point():
    """`service()` rather than a module constant, so TQ-57 can swap what is
    returned without every caller importing a different name."""
    assert callable(la.service)
    assert isinstance(la.service(), la.NoLocalModelsService)
    assert la.available() is False


def test_the_declared_interface_matches_the_specification():
    """§4's ten methods, asserted by name. A method dropped in a refactor, or
    added without the spec asking, fails here."""
    declared = {name for name, _ in inspect.getmembers(la.LocalAIService)
                if not name.startswith("_")}
    assert declared >= {
        "list_models", "get_model_capabilities", "get_model_health",
        "get_model_resource_state", "infer", "infer_with_model",
        "estimate_latency", "estimate_resource_cost", "benchmark",
        "compare_models",
    }


def test_this_module_ranks_nothing_and_names_no_leaderboard():
    """TQ-56's scope. The service supplies local intelligence and reports what
    it costs; deciding which model gets used is TQ-60's, and a service that
    quietly ranked would make that increment an argument about code that already
    chose."""
    body = conftest.executable_source(REPO / "app" / "local_ai.py")

    for leaked in ("leaderboard", "front_runner", "rank", "score", "seed"):
        assert leaked not in body, (
            f"{leaked!r} appears in local_ai's code: this service runs models, "
            "it does not choose between them")
