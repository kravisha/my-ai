"""The vocabulary routing decides on (app/task_signature.py; TQ-53,
docs/SPEC_RECONCILIATION.md §104).

Nothing here calls a model or ranks one. These tests protect the terms every
later increment in the addendum 45 lineage keys off - TQ-54's leaderboards are
per task category, TQ-59 decides escalation from a signature, TQ-60 maps
signature to leaderboard - so a term that drifts here drifts in four places.

The three worth reading first:

- `test_there_are_exactly_eight_categories` — §42's instruction, and the same
  one §70 and §100 each enforced under a different name.
- `test_error_cost_and_registry_criticality_are_one_vocabulary` — the tie that
  stops "how bad is it to be wrong here" being asked in two vocabularies.
- `test_a_local_only_field_forces_a_local_only_task` — §36 made mechanical, and
  the guard against the one genuine name collision in this module.
"""

import dataclasses
from pathlib import Path

import conftest
import pytest

yaml = pytest.importorskip("yaml")

from app import task_signature as ts
from app.data_classification import PORTFOLIO_FIELD_CLASSES, DataClass
from backend import fi_db

REPO = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO / "docs" / "model_registry.yaml"


def _signature(**overrides):
    base = dict(task_category=ts.CATEGORY_FINANCIAL,
                complexity=ts.COMPLEXITY_MODERATE,
                privacy_level=ts.PRIVACY_LOCAL_ONLY,
                error_cost=ts.ERROR_COST_HIGH)
    base.update(overrides)
    return ts.TaskSignature(**base)


# --- exactly eight, and exactly §20's fifteen fields --------------------------------


def test_there_are_exactly_eight_categories():
    """§42: "Start with exactly these eight… Do not prematurely create dozens."

    A ninth category is a decision with evidence behind it, and this is where
    somebody adding one on a hunch finds out. The same instruction this project
    enforced in §70 (addendum 39's parallel asset-class labels) and §100
    (addendum 44's EQUITY/OPTION) - one model of one fact."""
    assert len(ts.TASK_CATEGORIES) == 8
    assert len(set(ts.TASK_CATEGORIES)) == 8
    assert set(ts.TASK_CATEGORIES) == {
        "GENERAL_REASONING_AND_PLANNING",
        "CODING_AND_DEBUGGING",
        "LONG_CONTEXT_AND_MEMORY",
        "CLASSIFICATION_AND_ROUTING",
        "FINANCIAL_AND_ANALYTICAL_REASONING",
        "SUMMARIZATION_AND_KNOWLEDGE_EXTRACTION",
        "CREATIVE_GENERATION",
        "CAPABILITY_AND_ESCALATION_DECISION",
    }


def test_the_escalation_decision_has_its_own_category():
    """§17: deciding whether local intelligence suffices is itself an
    intelligent task, so it gets a leaderboard rather than a constant - and the
    model best at that call need not be the one best at the work."""
    assert ts.ESCALATION_CATEGORY in ts.TASK_CATEGORIES


def test_the_signature_carries_exactly_the_fifteen_fields_the_spec_names():
    """§20's list, asserted by name so a field cannot be dropped in a refactor
    or added without the spec saying so."""
    assert {f.name for f in dataclasses.fields(ts.TaskSignature)} == {
        "agent_role", "task_category", "domain", "complexity", "context_length",
        "coding_required", "math_required", "structured_output_required",
        "external_data_required", "latency_sensitivity", "privacy_level",
        "error_cost", "tool_use_required", "novelty", "ambiguity",
    }


def test_complexity_has_the_six_levels_the_spec_names():
    assert set(ts.COMPLEXITIES) == {"TRIVIAL", "SIMPLE", "MODERATE", "COMPLEX",
                                    "HIGH_STAKES", "SPECIALIZED"}


def test_privacy_has_the_four_levels_the_spec_names():
    assert set(ts.PRIVACY_LEVELS) == {"LOCAL_ONLY", "LOCAL_PREFERRED",
                                      "EXTERNAL_ALLOWED", "EXTERNAL_REQUIRED"}


# --- one model of one fact: the vocabularies that already existed -------------------


def test_error_cost_and_registry_criticality_are_one_vocabulary():
    """"How much does it cost to be wrong here" asked twice is one fact.

    `model_registry.yaml` has said `criticality` since TQ-16; addendum 45 §20
    calls it `error_cost`. Two vocabularies for it is exactly what §70 and §100
    each refused once, so this ties them: every criticality the registry
    actually uses must be a valid error cost, and a new value on either side
    fails here."""
    registry = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    used = {p["criticality"] for p in registry["profiles"]}

    assert used, "the registry has profiles, so it has criticalities"
    unmatched = used - set(ts.ERROR_COSTS)
    assert not unmatched, (
        f"registry criticality {sorted(unmatched)} is not a valid error_cost "
        f"{list(ts.ERROR_COSTS)} - one fact, one vocabulary")


def test_agent_role_is_the_charter_list_rather_than_a_second_one():
    """A role this system cannot charter is not one a task may claim."""
    for role in fi_db.ROLE_CHARTERS:
        assert _signature(agent_role=role).agent_role == role

    with pytest.raises(ts.UnknownVocabulary):
        _signature(agent_role="router")


def test_a_task_may_have_no_role_because_not_every_consumer_is_an_agent():
    """`model_registry.yaml` carries `role: null` for three consumers - the
    /chat surface, the Gateway socket, and introspection, which is a capability
    every agent process has rather than a role of its own."""
    assert _signature(agent_role=None).agent_role is None


# --- the name collision, and the derivation across it -------------------------------


def test_a_local_only_field_forces_a_local_only_task():
    """§36 made mechanical rather than remembered.

    `DataClass.LOCAL_ONLY` classifies a *field*; `PRIVACY_LOCAL_ONLY`
    classifies a *task*. Different facts, one name - and this is the derivation
    between them, so "sensitive data should never be sent externally merely
    because the external model ranks higher" is enforced rather than stated."""
    assert ts.privacy_floor_for([DataClass.LOCAL_ONLY]) == ts.PRIVACY_LOCAL_ONLY
    assert ts.privacy_floor_for(
        [DataClass.SERVICE_SHAREABLE, DataClass.LOCAL_ONLY]) == ts.PRIVACY_LOCAL_ONLY


def test_a_shareable_field_forces_nothing():
    """The derivation runs one way. `SERVICE_SHAREABLE` says a field *may* be
    sent once the user has granted a disposition - it does not say the task is
    free to go anywhere, and it does not say the task must stay."""
    assert ts.privacy_floor_for([DataClass.SERVICE_SHAREABLE]) is None
    assert ts.privacy_floor_for([]) is None


def test_the_real_portfolio_classification_forces_a_local_only_task():
    """Against real data rather than an invented example: `account_id` is
    LOCAL_ONLY in `PORTFOLIO_FIELD_CLASSES`, so any task carrying a whole
    portfolio row is a local-only task."""
    assert ts.privacy_floor_for(PORTFOLIO_FIELD_CLASSES.values()) == ts.PRIVACY_LOCAL_ONLY


def test_the_floor_takes_strings_as_well_as_enum_members():
    assert ts.privacy_floor_for(["local_only"]) == ts.PRIVACY_LOCAL_ONLY


@pytest.mark.parametrize("level,floor,ok", [
    (ts.PRIVACY_LOCAL_ONLY, ts.PRIVACY_LOCAL_ONLY, True),
    (ts.PRIVACY_LOCAL_ONLY, ts.PRIVACY_EXTERNAL_ALLOWED, True),
    (ts.PRIVACY_EXTERNAL_ALLOWED, ts.PRIVACY_LOCAL_ONLY, False),
    (ts.PRIVACY_LOCAL_PREFERRED, ts.PRIVACY_LOCAL_ONLY, False),
])
def test_restrictiveness_is_ordered_rather_than_guessed(level, floor, ok):
    assert ts.at_least_as_restrictive(level, floor) is ok


# --- fail closed, on construction and on read ---------------------------------------


@pytest.mark.parametrize("field,value", [
    ("task_category", "PORTFOLIO_ANALYSIS"),
    ("complexity", "VERY_HARD"),
    ("privacy_level", "PRIVATE"),
    ("error_cost", "critical"),
    ("latency_sensitivity", "fast"),
    ("novelty", "novel"),
    ("ambiguity", "vague"),
])
def test_an_unknown_vocabulary_value_is_refused(field, value):
    with pytest.raises(ts.UnknownVocabulary):
        _signature(**{field: value})


def test_a_signature_round_trips_through_storage():
    original = _signature(agent_role="analysis", context_length=4096,
                          coding_required=True, novelty=ts.JUDGEMENT_HIGH)
    assert ts.TaskSignature.from_dict(original.as_dict()) == original


def test_a_stored_signature_is_validated_on_read_not_only_on_write():
    """Fail closed on read, the rule every closed vocabulary here works under.

    A signature written by an older build, hand-edited, or restored from a
    backup must not be interpreted by guessing what its values meant - a routing
    decision replayed against an uninterpretable signature is a decision about a
    task nobody can describe."""
    stored = _signature().as_dict()
    stored["task_category"] = "PORTFOLIO_ANALYSIS"

    with pytest.raises(ts.UnknownVocabulary):
        ts.TaskSignature.from_dict(stored)


def test_an_unexpected_stored_field_is_refused_rather_than_ignored():
    """A field this build does not know is a signature it does not fully
    understand. Silently dropping it would route on a partial description while
    reporting a complete one."""
    stored = _signature().as_dict()
    stored["urgency"] = "high"

    with pytest.raises(ts.UnknownVocabulary, match="urgency"):
        ts.TaskSignature.from_dict(stored)


def test_privacy_is_required_rather_than_defaulted():
    """§36's rule is that sensitive data never leaves because a model ranked
    higher, and a default would be the quietest way to break it. A task whose
    privacy nobody stated must not acquire EXTERNAL_ALLOWED for free."""
    with pytest.raises(TypeError):
        ts.TaskSignature(task_category=ts.CATEGORY_FINANCIAL,
                         complexity=ts.COMPLEXITY_SIMPLE,
                         error_cost=ts.ERROR_COST_LOW)


def test_an_unestimated_context_is_none_rather_than_zero():
    """Zero claims an empty context, which is a different and false statement
    from "nobody measured it"."""
    assert _signature().context_length is None
    assert _signature(context_length=8192).context_length == 8192
    for impossible in (0, -1):
        with pytest.raises(ts.UnknownVocabulary):
            _signature(context_length=impossible)


def test_unknown_is_a_member_rather_than_an_absence():
    """§100's choice for `asset_class`, applied to the three fields nobody may
    have estimated. What `unknown` *means for routing* is deliberately not
    decided here - this module says what a task is, TQ-59 and TQ-60 say what to
    do about it."""
    signature = _signature()
    assert signature.novelty == ts.UNKNOWN
    assert signature.ambiguity == ts.UNKNOWN
    assert signature.latency_sensitivity == ts.UNKNOWN
    for vocabulary in (ts.JUDGEMENTS, ts.LATENCY_SENSITIVITIES):
        assert ts.UNKNOWN in vocabulary


def test_a_signature_cannot_be_edited_after_it_is_built():
    """Frozen, like OwnerContext and Holding: it is the description a routing
    decision was made against, and something reassignable between
    classification and selection is not a description of what was routed."""
    signature = _signature()
    with pytest.raises(dataclasses.FrozenInstanceError):
        signature.privacy_level = ts.PRIVACY_EXTERNAL_ALLOWED


# --- nothing here routes anything ---------------------------------------------------


def test_this_module_names_no_model_and_ranks_nothing():
    """TQ-53's scope, asserted rather than trusted. The vocabulary must not
    acquire a routing opinion: a default model, a rank, a score, or a rule about
    what `unknown` means. Those belong to TQ-54, TQ-59 and TQ-60, and a
    vocabulary that quietly decides them would make those increments arguments
    about code that already chose."""
    body = conftest.executable_source(REPO / "app" / "task_signature.py")

    for leaked in ("claude", "llama", "deepseek", "anthropic", "rank", "score",
                   "leaderboard"):
        assert leaked not in body, (
            f"{leaked!r} appears in task_signature's code: this module says what a "
            "task is, not what should run it")
