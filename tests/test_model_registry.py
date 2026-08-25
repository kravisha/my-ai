"""docs/model_registry.yaml must describe the model reality that actually runs.

The organization.yaml discipline applied to addendum 35's registry (TQ-16,
SPEC_RECONCILIATION §64): a hand-maintained registry drifts, and a drifted
registry is worse than none because a future router would believe it. These
tests make it an assertion - the registered model must be the one the code
constructs, every declared call size must match the constant that sizes it,
every model consumer in the code must carry a profile, and the pinned
`routing: none_single_model` decision trips the suite the day a second model
is registered, so routing gets revisited on purpose rather than by accident.

Two disciplines enforced rather than merely stated: every model and profile
is `provisional: true` (35 §2 - no first default earns permanent status
without a benchmark), and unmeasured fields carry no numbers (35 §3 -
empirical or absent, never a vendor spec sheet in this file's voice)."""

import importlib
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

from app import model_budget, model_gateway, model_provider
from backend import fi_db

REPO = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO / "docs" / "model_registry.yaml"

# Modules that DEFINE or WRAP the model interface rather than consuming it -
# the only files allowed to touch the provider without a profile.
_INTERFACE_MODULES = {"app/model_gateway.py", "app/model_provider.py", "app/model_budget.py"}


@pytest.fixture(scope="module")
def registry():
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def models(registry):
    return {m["id"]: m for m in registry["models"]}


@pytest.fixture(scope="module")
def profiles(registry):
    return {p["agent_class"]: p for p in registry["profiles"]}


def test_registry_parses_and_has_both_sections(registry):
    assert registry["version"] == 1
    assert registry["models"], "a registry with no models is not a registry of this system"
    assert registry["profiles"], "consumers exist, so profiles must"


def test_single_model_reality_matches_the_code(registry, models):
    """Exactly one configured model, and it is the one the code constructs -
    while `routing: none_single_model` stands, a second registered model is
    a suite failure by design: it means routing must be revisited on
    purpose (§60 disposition 2, §64), not acquired by drift."""
    assert registry["routing"] == "none_single_model"
    configured = [m for m in models.values() if m["status"] == "configured"]
    assert len(configured) == 1, (
        "a second configured model has arrived: revisit `routing: none_single_model` "
        "deliberately (SPEC_RECONCILIATION §64) before registering it"
    )
    model = configured[0]
    assert model["id"] == model_provider.DEFAULT_MODEL
    assert model["id"] == model_gateway.MODEL
    assert model["provider"] == "anthropic"
    assert hasattr(model_provider, "AnthropicProvider")
    assert model["interface"].split("::")[0] == "app/model_provider.py"


def test_budget_facts_match_the_breaker(models):
    model = models[model_provider.DEFAULT_MODEL]
    assert model["budget"]["daily_tokens"] == model_budget.DEFAULT_DAILY_TOKENS
    assert model["budget"]["daily_calls"] == model_budget.DEFAULT_DAILY_CALLS


def test_everything_is_provisional(models, profiles):
    """35 §2, enforced: no first default earns permanent status. The flag
    comes off a row only when a benchmark_date and evidence go on."""
    for model in models.values():
        assert model["provisional"] is True, f"{model['id']} lost its provisional flag without a benchmark"
    for profile in profiles.values():
        assert profile["provisional"] is True, f"{profile['agent_class']} lost its provisional flag"


def test_unmeasured_fields_carry_no_numbers(models):
    """Empirical or absent: an `unmeasured` entry is a name, and no field of
    that name appears on the model row with a value."""
    for model in models.values():
        for field_name in model.get("unmeasured", []):
            assert field_name not in model, (
                f"{model['id']}.{field_name} is listed unmeasured AND carries a value - pick one"
            )
        assert model["benchmark_date"] is None  # the day this is set, provisional flags may come off


def test_profiles_reference_registered_models_and_real_roles(models, profiles):
    for profile in profiles.values():
        assert profile["preferred_model"] in models
        assert models[profile["preferred_model"]]["status"] == "configured"
        # No routing engine with one route: fallback is honestly empty, and
        # populating it is part of the same deliberate routing revisit the
        # single-model pin protects.
        assert profile["fallback_models"] == []
        if profile["role"] is not None:
            assert profile["role"] in fi_db.ROLE_CHARTERS, (
                f"profile {profile['agent_class']} names role {profile['role']!r} "
                "that ROLE_CHARTERS does not define"
            )


def test_call_shapes_match_the_constants_that_size_them(profiles):
    """The TIMING_CONSTANTS drift guard applied to call sizing: a resized
    call fails here until the profile is updated."""
    for profile in profiles.values():
        module_name = profile["code_ref"].removesuffix(".py").replace("/", ".")
        module = importlib.import_module(module_name)
        for shape in profile["call_shape"]:
            assert getattr(module, shape["source"]) == shape["max_tokens"], (
                f"{profile['agent_class']}: {shape['source']} no longer equals {shape['max_tokens']}"
            )


def test_every_model_consumer_in_the_code_has_a_profile(profiles):
    """The check that earns this file's keep, organization.yaml's known_gap
    discipline for model consumption: scan every source file for a call
    into the model interface, and require a profile for each. A new
    consumer fails the suite until somebody declares what it needs from a
    model - which is exactly when a requirement profile is cheapest to
    write."""
    consumers = set()
    for top in ("agents", "backend", "app", "gateway"):
        for path in (REPO / top).rglob("*.py"):
            rel = path.relative_to(REPO).as_posix()
            if rel in _INTERFACE_MODULES:
                continue
            text = path.read_text(encoding="utf-8")
            if "call_reasoning_model(" in text or "default_provider(" in text:
                consumers.add(rel)
    declared = {profile["code_ref"] for profile in profiles.values()}
    assert consumers == declared, (
        f"undeclared model consumer(s): {sorted(consumers - declared)}; "
        f"stale profile(s): {sorted(declared - consumers)}"
    )
