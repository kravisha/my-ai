"""The Routing Decision Record (app/routing_decisions.py; TQ-55,
docs/SPEC_RECONCILIATION.md §106).

Nothing here routes anything. These tests are about whether the *record* is
trustworthy: whether the decision and its outcome can disagree, whether a
signature survives storage intact, and whether a §36 violation that reaches the
log is visible rather than merely present.

The three that carry the increment:

- `test_completing_a_decision_scores_the_leaderboard_in_one_write_path` — §32's
  loop. Two write paths would be two sources of truth for one outcome.
- `test_a_local_only_task_sent_externally_is_flagged` — §41's
  PRIVACY_MISROUTING, found by running the module rather than by reasoning.
- `test_a_stored_decision_is_validated_on_read` — a log nobody can interpret is
  a log of decisions about tasks nobody can describe.
"""

import conftest
import pytest

from app import model_performance as mp
from app import routing_decisions as rd
from app.task_signature import (CATEGORY_CODING, CATEGORY_FINANCIAL,
                                COMPLEXITY_COMPLEX, COMPLEXITY_TRIVIAL,
                                ERROR_COST_HIGH, PRIVACY_EXTERNAL_ALLOWED,
                                PRIVACY_LOCAL_ONLY, TaskSignature,
                                UnknownVocabulary)

MODEL = "some-model"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(mp.PATH_ENV, str(tmp_path / "model_performance.db"))
    mp.seed_leaderboard(CATEGORY_FINANCIAL, [MODEL])
    mp.seed_leaderboard(CATEGORY_CODING, [MODEL])
    yield


def _sig(**over):
    base = dict(task_category=CATEGORY_FINANCIAL, complexity=COMPLEXITY_COMPLEX,
                privacy_level=PRIVACY_EXTERNAL_ALLOWED, error_cost=ERROR_COST_HIGH)
    base.update(over)
    return TaskSignature(**base)


def _decide(**over):
    kwargs = dict(reason="the front-runner on this leaderboard",
                  execution_path=rd.PATH_LOCAL, selected_model=MODEL)
    signature = over.pop("signature", _sig())
    kwargs.update(over)
    return rd.record_decision(signature, **kwargs)


# --- the record itself --------------------------------------------------------------


def test_a_decision_is_recorded_with_its_reason():
    decision = rd.get(_decide())

    assert decision["execution_path"] == rd.PATH_LOCAL
    assert decision["selected_model"] == MODEL
    assert decision["reason_for_selection"]
    assert decision["final_status"] == rd.STATUS_PENDING
    assert decision["routing_decision_id"].startswith("rd-")


def test_a_decision_without_a_reason_is_refused():
    """§26 asks for `reason_for_selection`, and a row saying what was chosen but
    not why is not worth the space when a routing mistake is being diagnosed."""
    for empty in ("", "   "):
        with pytest.raises(rd.DecisionRefused, match="reason"):
            _decide(reason=empty)


def test_a_decision_is_recorded_against_a_signature_not_a_dict():
    """The signature validates the vocabulary (§104); a dict would let an
    uninterpretable task into the log."""
    with pytest.raises(rd.DecisionRefused):
        rd.record_decision({"task_category": CATEGORY_FINANCIAL}, reason="x",
                           execution_path=rd.PATH_LOCAL, selected_model=MODEL)


def test_a_deterministic_path_cannot_name_a_model():
    """§19's whole point: deterministic work uses no model. A row claiming both
    would make `UNNECESSARY_AI` uncountable."""
    with pytest.raises(rd.DecisionRefused, match="deterministic"):
        _decide(execution_path=rd.PATH_DETERMINISTIC, selected_model=MODEL)


def test_a_model_path_must_name_a_model():
    with pytest.raises(rd.DecisionRefused, match="no model was selected"):
        _decide(execution_path=rd.PATH_EXTERNAL, selected_model=None)


def test_a_deterministic_decision_needs_no_model():
    decision = rd.get(_decide(execution_path=rd.PATH_DETERMINISTIC,
                              selected_model=None,
                              reason="arithmetic - §19, AI is not used merely because "
                                     "it is available"))
    assert decision["selected_model"] is None
    assert decision["execution_path"] == rd.PATH_DETERMINISTIC


@pytest.mark.parametrize("field,value", [
    ("execution_path", "magic"),
])
def test_an_unknown_vocabulary_value_is_refused_on_write(field, value):
    with pytest.raises(UnknownVocabulary):
        _decide(**{field: value})


# --- the signature is stored once (§26's four duplicates) ---------------------------


def test_the_duplicated_fields_are_derived_rather_than_stored():
    """§26 lists `task_signature` and also `task_category`, `complexity`,
    `risk_level` and `privacy_level`. Storing them beside it would be four more
    places to disagree, so three of the four are read off the signature."""
    signature = _sig(complexity=COMPLEXITY_TRIVIAL, privacy_level=PRIVACY_LOCAL_ONLY)
    decision = rd.get(_decide(signature=signature))

    assert decision["complexity"] == COMPLEXITY_TRIVIAL
    assert decision["privacy_level"] == PRIVACY_LOCAL_ONLY
    assert decision["risk_level"] == signature.error_cost


def test_risk_level_is_the_third_name_for_one_fact():
    """`criticality` in model_registry.yaml, `error_cost` on the signature,
    `risk_level` in §26. §104 tied the first two; this reads the third off the
    signature rather than adding a column."""
    signature = _sig(error_cost="low")
    assert rd.get(_decide(signature=signature))["risk_level"] == "low"


def test_the_category_column_cannot_disagree_with_the_signature():
    """It is denormalised for indexing and the caller never supplies it - but a
    hand-edited row could still diverge, and that is refused rather than
    guessed at."""
    decision_id = _decide()
    conn = rd._connect()
    try:
        conn.execute("UPDATE routing_decisions SET task_category = ? "
                     "WHERE routing_decision_id = ?", (CATEGORY_CODING, decision_id))
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(UnknownVocabulary, match="Refusing to guess"):
        rd.get(decision_id)


def test_a_signature_survives_storage_intact():
    signature = _sig(agent_role="analysis", context_length=4096, coding_required=True)
    assert rd.get(_decide(signature=signature))["signature"] == signature


def test_a_stored_decision_is_validated_on_read():
    """A log nobody can interpret is a log of decisions about tasks nobody can
    describe. Fail closed, like every other vocabulary here."""
    decision_id = _decide()
    conn = rd._connect()
    try:
        conn.execute("UPDATE routing_decisions SET execution_path = 'telepathy' "
                     "WHERE routing_decision_id = ?", (decision_id,))
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(UnknownVocabulary):
        rd.get(decision_id)


# --- the loop closes in one write path (§32) ----------------------------------------


def test_completing_a_decision_scores_the_leaderboard_in_one_write_path():
    """§32's loop: record the route, record the result, score it, update the
    registry. One call does the last three, so the log and the tally cannot
    disagree about what happened."""
    before = mp.entry(MODEL, CATEGORY_FINANCIAL)["sample_count"]
    decision_id = _decide()

    rd.complete(decision_id, final_status=rd.STATUS_COMPLETED,
                validation_result=rd.VALIDATION_PASSED, quality_score=0.9)

    after = mp.entry(MODEL, CATEGORY_FINANCIAL)
    assert after["sample_count"] == before + 1
    assert after["quality_score"] == pytest.approx(0.9)
    assert rd.get(decision_id)["final_status"] == rd.STATUS_COMPLETED


def test_a_failure_reaches_the_leaderboard_as_a_failure():
    decision_id = _decide()
    rd.complete(decision_id, final_status=rd.STATUS_FAILED,
                validation_result=rd.VALIDATION_FAILED, failure_type="wrong_answer")

    entry = mp.entry(MODEL, CATEGORY_FINANCIAL)
    assert entry["failure_rate"] == 1.0
    assert entry["penalty_score"] > 0


def test_an_outcome_lands_only_on_the_category_it_was_decided_for():
    """§11 holds through this layer too."""
    rd.complete(_decide(), final_status=rd.STATUS_FAILED, failure_type="wrong_answer")

    assert mp.entry(MODEL, CATEGORY_FINANCIAL)["sample_count"] == 1
    assert mp.entry(MODEL, CATEGORY_CODING)["sample_count"] == 0


def test_a_decision_is_closed_once():
    """Re-closing would rewrite history and double-count the outcome against
    the leaderboard."""
    decision_id = _decide()
    rd.complete(decision_id, final_status=rd.STATUS_COMPLETED)

    with pytest.raises(rd.DecisionRefused, match="already"):
        rd.complete(decision_id, final_status=rd.STATUS_COMPLETED)
    assert mp.entry(MODEL, CATEGORY_FINANCIAL)["sample_count"] == 1


def test_a_deterministic_decision_scores_no_model():
    """Nothing ran, so nothing is ranked. `UNNECESSARY_AI` is about the path
    taken, not about a model that was never asked."""
    decision_id = _decide(execution_path=rd.PATH_DETERMINISTIC, selected_model=None,
                          reason="a parser does this")
    rd.complete(decision_id, final_status=rd.STATUS_COMPLETED)

    assert mp.entry(MODEL, CATEGORY_FINANCIAL)["sample_count"] == 0


def test_completing_an_unknown_decision_raises():
    with pytest.raises(LookupError):
        rd.complete("rd-nope", final_status=rd.STATUS_COMPLETED)


def test_an_unvalidated_result_never_reads_as_passed():
    """§38: "Before penalizing a model, validate where possible." So "nobody
    checked" is its own answer."""
    decision_id = _decide()
    rd.complete(decision_id, final_status=rd.STATUS_COMPLETED)

    assert rd.get(decision_id)["validation_result"] == rd.VALIDATION_NOT_VALIDATED


def test_a_quality_score_outside_zero_to_one_is_refused():
    decision_id = _decide()
    with pytest.raises(rd.DecisionRefused):
        rd.complete(decision_id, final_status=rd.STATUS_COMPLETED, quality_score=1.5)


# --- §36 detection (§41's PRIVACY_MISROUTING) ---------------------------------------


def test_a_local_only_task_sent_externally_is_flagged():
    """Found by running the module, not by reasoning about it (§106): the first
    end-to-end exercise routed a LOCAL_ONLY step to an external model and
    nothing said a word."""
    decision_id = _decide(signature=_sig(privacy_level=PRIVACY_LOCAL_ONLY),
                          execution_path=rd.PATH_EXTERNAL, reason="escalated")

    assert rd.get(decision_id)["privacy_violation"] is True
    assert rd.summary()["privacy_violations"] == 1
    assert "not prevented" in rd.summary()["privacy_note"]


def test_a_local_only_task_kept_local_is_not_flagged():
    decision_id = _decide(signature=_sig(privacy_level=PRIVACY_LOCAL_ONLY),
                          execution_path=rd.PATH_LOCAL)
    assert rd.get(decision_id)["privacy_violation"] is False


def test_a_shareable_task_sent_externally_is_not_flagged():
    decision_id = _decide(signature=_sig(privacy_level=PRIVACY_EXTERNAL_ALLOWED),
                          execution_path=rd.PATH_EXTERNAL)
    assert rd.get(decision_id)["privacy_violation"] is False


def test_a_violation_is_recorded_rather_than_refused():
    """**Detection, never refusal.** Once TQ-60 enforces privacy, a violation
    can only reach this table through a bug or a bypass - and a log that refused
    to record those would hide precisely what it exists to reveal."""
    decision_id = _decide(signature=_sig(privacy_level=PRIVACY_LOCAL_ONLY),
                          execution_path=rd.PATH_EXTERNAL, reason="a bug put it here")

    assert rd.get(decision_id) is not None, "the log records reality, violations included"


def test_a_clean_log_reports_no_privacy_note():
    _decide()
    assert rd.summary()["privacy_violations"] == 0
    assert rd.summary()["privacy_note"] is None


# --- task-step routing (§25) --------------------------------------------------------


def test_one_task_can_be_routed_step_by_step():
    """§25's own example: parse deterministically, interpret locally, resolve
    the hard part externally."""
    steps = [
        ("parse", rd.PATH_DETERMINISTIC, None),
        ("interpret", rd.PATH_LOCAL, MODEL),
        ("resolve", rd.PATH_EXTERNAL, MODEL),
    ]
    for name, path, model in steps:
        _decide(task_id="task-1", task_step_id=name, execution_path=path,
                selected_model=model, reason=f"step {name}")

    recorded = rd.for_task("task-1")
    assert [d["task_step_id"] for d in recorded] == ["parse", "interpret", "resolve"]
    assert [d["execution_path"] for d in recorded] == [
        rd.PATH_DETERMINISTIC, rd.PATH_LOCAL, rd.PATH_EXTERNAL]


def test_a_whole_task_decision_needs_no_step():
    _decide(task_id="task-2")
    assert rd.for_task("task-2")[0]["task_step_id"] is None


def test_recent_can_be_filtered_by_category():
    _decide()
    _decide(signature=_sig(task_category=CATEGORY_CODING), reason="coding work")

    assert len(rd.recent()) == 2
    assert len(rd.recent(task_category=CATEGORY_CODING)) == 1


# --- what is deliberately unanswerable ----------------------------------------------


def test_escalation_worth_defaults_to_unknown_rather_than_false():
    """The field this whole lineage exists to answer, and nothing can answer it
    yet - it needs a counterfactual, and TQ-63's challenger mode is the first
    thing that produces one. A boolean defaulting to false would have quietly
    asserted that every escalation was wasted."""
    decision_id = _decide()
    assert rd.get(decision_id)["was_escalation_worthwhile"] == rd.WORTH_UNKNOWN

    rd.complete(decision_id, final_status=rd.STATUS_COMPLETED)
    assert rd.get(decision_id)["was_escalation_worthwhile"] == rd.WORTH_UNKNOWN
    assert rd.summary()["escalation_worth_unknown"] == 1


def test_cost_and_resource_fields_exist_and_are_empty():
    """Nullable rather than absent, unlike §105's score columns: a score
    participates in arithmetic that changes shape when a dimension arrives,
    whereas a log field is inert - and a log is the one artifact that must not
    need migrating, because migrating a log means rewriting history."""
    decision_id = _decide()
    decision = rd.get(decision_id)

    for field in ("estimated_cost", "actual_cost", "resource_usage"):
        assert field in decision
        assert decision[field] is None


def test_resource_usage_round_trips_when_something_supplies_it():
    """Nothing does yet - TQ-57's hardware monitoring is the first - but the
    column must hold it correctly the day it does."""
    decision_id = _decide()
    rd.complete(decision_id, final_status=rd.STATUS_COMPLETED,
                resource_usage={"vram_mb": 4200, "seconds_held": 3.1})

    assert rd.get(decision_id)["resource_usage"] == {"vram_mb": 4200,
                                                     "seconds_held": 3.1}


def test_nothing_here_selects_a_model():
    """TQ-55's scope, asserted rather than trusted. This module records what was
    decided; deciding is TQ-59's and TQ-60's."""
    body = conftest.executable_source(rd.__file__)

    for leaked in ("front_runner", "ranking(", "select_model", "choose"):
        assert leaked not in body, (
            f"{leaked!r} appears in routing_decisions' code: this module records "
            "decisions, it does not make them")
