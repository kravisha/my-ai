"""docs/model_registry.yaml must describe the model reality that actually runs.

The organization.yaml discipline applied to addendum 35's registry (TQ-16,
SPEC_RECONCILIATION §64): a hand-maintained registry drifts, and a drifted
registry is worse than none because a future router would believe it. These
tests make it an assertion - the registered model must be the one the code
constructs, every declared call size must match the constant that sizes it,
every model consumer in the code must carry a profile, and the pinned
`routing` decision trips the suite the day a second model is registered, so
routing gets revisited on purpose rather than by accident.

TQ-51 (§103) turned that pin into a ladder, because addendum 45 needs four to
eight models and the tripwire fired on its first real step - which is what §64
built it for. **It was re-aimed, not removed.** Each rung of `routing_stages`
carries its own assertion; a rung whose enforcement is not built yet refuses to
be stood on, so advancing the marker early fails loudly instead of passing
silently and leaving a second model reachable by nothing.

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

# The rungs of `routing_stages` this file actually asserts.
#
# It exists because §103's ladder had a hole its author walked straight into
# (§105): `enforced` is a flag in a YAML file, so setting it to true without
# writing the assertion is exactly the silent pass the ladder was built to
# prevent. Declaring the enforced set *here*, next to the tests, and requiring
# the YAML to match it, makes `enforced: true` a statement about code that
# exists rather than an intention.
ENFORCED_STAGES = {"none_single_model", "seeded_leaderboard"}


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


@pytest.fixture(scope="module")
def stages(registry):
    return {s["stage"]: s for s in registry["routing_stages"]}


def test_the_routing_marker_names_a_rung_of_the_ladder(registry, stages):
    """Fail closed on an unknown routing value, the house rule every other
    closed vocabulary in this codebase works under. A marker nobody can
    interpret is not one this suite may assert against."""
    assert registry["routing"] in stages, (
        f"routing {registry['routing']!r} is not a stage in routing_stages: "
        f"{sorted(stages)}. Add the rung and its tripwire before standing on it."
    )


def test_an_unenforced_rung_refuses_to_be_stood_on(registry, stages):
    """The half of the re-aim that keeps the discipline (§103).

    Turning one pin into a ladder invites a quiet failure: somebody advances
    `routing` to a rung whose assertion nobody has written, the suite goes
    green, and a second configured model is now reachable by nothing. So a rung
    must declare `enforced: true` before the marker may sit on it, and the
    queue entry that earns it is named in the failure."""
    stage = stages[registry["routing"]]
    assert stage["enforced"] is True, (
        f"routing is set to {stage['stage']!r}, whose tripwire is not built yet "
        f"({stage['earned_by']} earns it). Build the assertion in that increment "
        "before moving the marker - an unenforced rung is a silent pass."
    )


def test_enforced_is_a_fact_about_this_file_rather_than_a_claim(stages):
    """The hole §103 left, closed in §105 by the increment that fell in it.

    `enforced` lives in a YAML file, so nothing stopped somebody - the author,
    as it turned out - from setting it true and moving the marker without ever
    writing the rung's assertion. The suite went green and the discipline was
    gone, which is precisely the failure the ladder exists to prevent.

    So the enforced set is declared beside the tests that implement it, and the
    YAML has to agree. A rung claiming enforcement this file does not provide
    fails here; so does a rung this file asserts but the YAML calls unenforced."""
    claimed = {name for name, stage in stages.items() if stage["enforced"]}
    assert claimed == ENFORCED_STAGES, (
        f"routing_stages claims to enforce {sorted(claimed)} but "
        f"tests/test_model_registry.py implements {sorted(ENFORCED_STAGES)}. "
        "Write the rung's assertion and add it to ENFORCED_STAGES, or set "
        "enforced: false - a flag is not a tripwire."
    )


def test_the_seeded_leaderboard_rung(registry, models):
    """The `seeded_leaderboard` rung's own tripwire (TQ-54, §105).

    What the rung demands: every configured model has a seeded entry on every
    one of the eight leaderboards. A configured model no routing decision can
    reach is the failure it exists to catch - and it is checkable here, from
    committed metadata, precisely because §105 put the hand-authored seed
    *ordering* in this file and left only the measurements in the database. A
    tripwire that read the runtime database would assert nothing in CI, which
    has no database."""
    if registry["routing"] != "seeded_leaderboard":
        pytest.skip("a different rung governs; its own tripwire applies")

    from app.task_signature import TASK_CATEGORIES

    ordering = registry["seed_ordering"]
    assert set(ordering) == set(TASK_CATEGORIES), (
        f"seed_ordering covers {sorted(ordering)}; the eight leaderboards are "
        f"{sorted(TASK_CATEGORIES)}"
    )

    configured = {m["id"] for m in models.values() if m["status"] == "configured"}
    for category, ordered in ordering.items():
        assert ordered, f"{category} has an empty seed ordering"
        assert len(set(ordered)) == len(ordered), f"{category} seeds a model twice"
        missing = configured - set(ordered)
        assert not missing, (
            f"configured model(s) {sorted(missing)} have no seeded entry on "
            f"{category} - nothing could route to them there")
        unknown = set(ordered) - set(models)
        assert not unknown, (
            f"{category} seeds {sorted(unknown)}, which the registry does not list. "
            "Register the model before ranking it.")


def test_each_rung_says_what_it_demands(stages):
    """A ladder whose rungs carry no requirement is a comment. Every stage
    names the queue entry that earns it and what its tripwire will check."""
    for stage in stages.values():
        assert stage["earned_by"].strip()
        assert stage["requires"].strip()
        assert isinstance(stage["enforced"], bool)


def test_single_model_reality_matches_the_code(registry, models):
    """Exactly one configured model, and it is the one the code constructs.

    This is the `none_single_model` rung's own tripwire: while that marker
    stands, a second registered model is a suite failure by design - routing
    must be revisited on purpose (§60 disposition 2, §64), not acquired by
    drift. Addendum 45 needs four to eight models, so the way past this is
    TQ-54: seed the leaderboards, then advance the marker."""
    if registry["routing"] != "none_single_model":
        pytest.skip("a later rung governs; its own tripwire applies")
    configured = [m for m in models.values() if m["status"] == "configured"]
    assert len(configured) == 1, (
        "a second configured model has arrived: advance `routing` to a rung that "
        "can reach it (SPEC_RECONCILIATION §64, §103) before registering it"
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


def test_profiles_reference_registered_models_and_real_roles(registry, models, profiles):
    """`preferred_model` is a hand-authored guess, and from TQ-60 it becomes the
    *seed* a leaderboard starts from rather than the answer read at call time -
    addendum 45 §16 is explicit that an agent does not choose its own model.
    Asserted as a real registered model either way, because a seed pointing at
    nothing is worse than no seed."""
    for profile in profiles.values():
        assert profile["preferred_model"] in models
        assert models[profile["preferred_model"]]["status"] == "configured"
        # No routing engine with one route: fallback is honestly empty while
        # `none_single_model` stands, and populating it is part of the same
        # deliberate revisit that rung protects.
        if registry["routing"] == "none_single_model":
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
