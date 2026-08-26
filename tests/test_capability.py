"""The capability and escalation decision (app/capability.py; TQ-59,
docs/SPEC_RECONCILIATION.md §108).

§3's *first* decision — can this be done without a model, and if not, is local
enough — kept separate from §3's second, which is TQ-60's. Nothing here names a
model, and a source scan asserts it.

The three that carry the increment:

- `test_a_local_only_task_with_no_local_model_is_refused_not_escalated` — the
  case that is live right now, and the one where "helpful" and "correct"
  disagree.
- `test_the_deterministic_check_runs_before_anything_else` — §19 is not a
  formality, and a check reachable only after some other condition passed would
  be one.
- `test_every_declared_capability_points_at_code_that_exists` — a registry
  claiming a deterministic solution that is not there would route work to
  nothing.
"""

from pathlib import Path

import conftest
import pytest

from app import capability as cap
from app import local_ai
from app.task_signature import (CATEGORY_FINANCIAL, COMPLEXITY_COMPLEX,
                                COMPLEXITY_HIGH_STAKES, COMPLEXITY_MODERATE,
                                COMPLEXITY_SPECIALIZED, COMPLEXITY_TRIVIAL,
                                ERROR_COST_HIGH, ERROR_COST_LOW,
                                ERROR_COST_MEDIUM, JUDGEMENT_HIGH,
                                PRIVACY_EXTERNAL_ALLOWED,
                                PRIVACY_EXTERNAL_REQUIRED, PRIVACY_LOCAL_ONLY,
                                PRIVACY_LOCAL_PREFERRED, TaskSignature)

REPO = Path(__file__).resolve().parent.parent


def _sig(**over):
    base = dict(task_category=CATEGORY_FINANCIAL, complexity=COMPLEXITY_MODERATE,
                privacy_level=PRIVACY_EXTERNAL_ALLOWED, error_cost=ERROR_COST_MEDIUM)
    base.update(over)
    return TaskSignature(**base)


# --- §19: deterministic first, and not as a formality --------------------------------


def test_the_deterministic_check_runs_before_anything_else():
    """§19: "AI should not be used merely because AI is available."

    A check reachable only after some other condition passed would be a
    formality. This one runs first for every signature, including the ones that
    would otherwise be refused outright."""
    for privacy in (PRIVACY_LOCAL_ONLY, PRIVACY_EXTERNAL_REQUIRED,
                    PRIVACY_EXTERNAL_ALLOWED, PRIVACY_LOCAL_PREFERRED):
        for available in (True, False):
            decision = cap.decide(_sig(privacy_level=privacy),
                                  operation="portfolio_concentration",
                                  local_available=available)
            assert decision.path == cap.PATH_DETERMINISTIC
            assert decision.deterministic_possible is True


def test_a_deterministic_solution_is_privacy_safe_by_construction():
    """Deterministic-before-privacy is only safe because a deterministic
    solution is *our code on this machine* - it sends nothing anywhere. Worth
    asserting rather than assuming, because the ordering would be a hole if a
    "deterministic" answer could ever mean an external call."""
    decision = cap.decide(_sig(privacy_level=PRIVACY_LOCAL_ONLY),
                          operation="portfolio_concentration", local_available=False)

    assert decision.path == cap.PATH_DETERMINISTIC
    assert decision.path != cap.PATH_EXTERNAL


def test_an_unregistered_operation_is_unknown_rather_than_needing_a_model():
    """§19 asks a question a person answers at design time. Silence means nobody
    has asked yet, and treating silence as "use AI" would be the reflex §19
    exists to interrupt."""
    assert cap.deterministic_capability_for("something_nobody_considered") is None
    assert cap.deterministic_capability_for(None) is None

    decision = cap.decide(_sig(), operation="something_nobody_considered",
                          local_available=True)
    assert decision.deterministic_possible is False
    assert "deterministic" not in decision.reason.lower()


def test_every_declared_capability_points_at_code_that_exists():
    """The `model_registry.yaml` discipline applied here: a registry that drifts
    is worse than none, because a router would believe it. A capability claiming
    a deterministic solution that is not there would route work to nothing."""
    for capability in cap.DETERMINISTIC_CAPABILITIES:
        module, _, symbol = capability.code_ref.partition("::")
        path = REPO / module
        assert path.exists(), f"{capability.operation}: {module} does not exist"
        if symbol:
            source = path.read_text(encoding="utf-8")
            assert f"def {symbol}" in source, (
                f"{capability.operation}: {module} has no {symbol}()")


def test_every_capability_says_why_it_is_reliable():
    """A registry entry that only says "this is deterministic" is an assertion.
    Saying why is what lets somebody later disagree with it."""
    for capability in cap.DETERMINISTIC_CAPABILITIES:
        assert capability.why_reliable.strip()
        assert capability.summary.strip()
        assert len(capability.why_reliable) > 40, (
            f"{capability.operation}: give a real reason, not a label")


def test_capability_operations_are_unique():
    operations = [c.operation for c in cap.DETERMINISTIC_CAPABILITIES]
    assert len(set(operations)) == len(operations)


# --- §36: privacy is a constraint, not a tiebreaker ---------------------------------


def test_a_local_only_task_with_no_local_model_is_refused_not_escalated():
    """**The case that is live right now**, and the one where "helpful" and
    "correct" disagree.

    A LOCAL_ONLY task needing intelligence, on a machine with no local model,
    cannot be done. Sending it externally is not a fallback - it is the thing
    LOCAL_ONLY forbids. §36: sensitive data does not leave because the external
    model ranks higher, and it does not leave because the local one is missing
    either."""
    decision = cap.decide(_sig(privacy_level=PRIVACY_LOCAL_ONLY),
                          local_available=False)

    assert decision.path == cap.PATH_REFUSED
    assert decision.path != cap.PATH_EXTERNAL
    assert decision.forced is True
    assert "cannot be done" in decision.reason


def test_a_local_only_task_stays_local_when_local_exists():
    decision = cap.decide(_sig(privacy_level=PRIVACY_LOCAL_ONLY), local_available=True)

    assert decision.path == cap.PATH_LOCAL
    assert decision.forced is True
    assert decision.local_sufficient is True


@pytest.mark.parametrize("complexity", [COMPLEXITY_HIGH_STAKES, COMPLEXITY_SPECIALIZED])
@pytest.mark.parametrize("error_cost", [ERROR_COST_HIGH])
def test_no_amount_of_difficulty_sends_local_only_work_outside(complexity, error_cost):
    """The rules that escalate everything else must not touch this one. Privacy
    is a constraint; the rest are heuristics."""
    decision = cap.decide(
        _sig(privacy_level=PRIVACY_LOCAL_ONLY, complexity=complexity,
             error_cost=error_cost, ambiguity=JUDGEMENT_HIGH, tool_use_required=True),
        local_available=True)

    assert decision.path == cap.PATH_LOCAL
    assert decision.forced is True


def test_external_required_work_goes_external_even_when_local_would_do():
    decision = cap.decide(
        _sig(privacy_level=PRIVACY_EXTERNAL_REQUIRED, complexity=COMPLEXITY_TRIVIAL,
             error_cost=ERROR_COST_LOW),
        local_available=True)

    assert decision.path == cap.PATH_EXTERNAL
    assert decision.forced is True


def test_a_forced_decision_is_marked_as_forced():
    """`forced` separates a constraint from a heuristic, so a leaderboard never
    treats "privacy required it" as evidence about capability."""
    heuristic = cap.decide(_sig(complexity=COMPLEXITY_HIGH_STAKES), local_available=True)
    constraint = cap.decide(_sig(privacy_level=PRIVACY_LOCAL_ONLY), local_available=True)

    assert heuristic.forced is False
    assert constraint.forced is True


# --- availability is a fact, not a judgement ----------------------------------------


def test_no_local_model_is_reported_as_availability_not_capability():
    """It changes the day TQ-57 lands, and a ranking gathered under it must not
    be read as evidence about what local intelligence could have handled."""
    decision = cap.decide(_sig(), local_available=False)

    assert decision.path == cap.PATH_EXTERNAL
    assert decision.local_sufficient is False
    assert "availability fact" in decision.reason
    assert "not a judgement" in decision.reason


def test_the_live_default_matches_the_machine():
    """With no `local_available` supplied, the answer is the truth about this
    machine - which today is False, from `local_ai.available()`."""
    assert local_ai.available() is False
    assert cap.decide(_sig()).path == cap.PATH_EXTERNAL
    assert cap.decide(_sig(privacy_level=PRIVACY_LOCAL_ONLY)).path == cap.PATH_REFUSED


# --- §16's self-assessment, as seeded rules ------------------------------------------


def test_ordinary_work_stays_local_when_local_exists():
    decision = cap.decide(_sig(complexity=COMPLEXITY_MODERATE,
                               error_cost=ERROR_COST_MEDIUM), local_available=True)

    assert decision.path == cap.PATH_LOCAL
    assert decision.local_sufficient is True


def test_high_stakes_work_escalates():
    decision = cap.decide(_sig(complexity=COMPLEXITY_HIGH_STAKES), local_available=True)

    assert decision.path == cap.PATH_EXTERNAL
    assert "HIGH_STAKES" in decision.reason


def test_complex_work_with_a_high_error_cost_escalates():
    assert cap.decide(_sig(complexity=COMPLEXITY_COMPLEX, error_cost=ERROR_COST_HIGH),
                      local_available=True).path == cap.PATH_EXTERNAL
    # ...and the same complexity with a low error cost does not.
    assert cap.decide(_sig(complexity=COMPLEXITY_COMPLEX, error_cost=ERROR_COST_LOW),
                      local_available=True).path == cap.PATH_LOCAL


def test_high_error_cost_with_high_ambiguity_escalates():
    assert cap.decide(_sig(error_cost=ERROR_COST_HIGH, ambiguity=JUDGEMENT_HIGH),
                      local_available=True).path == cap.PATH_EXTERNAL


def test_tool_use_escalates_until_a_local_model_has_shown_it_can():
    assert cap.decide(_sig(tool_use_required=True),
                      local_available=True).path == cap.PATH_EXTERNAL


def test_every_escalation_explains_itself():
    """§17 gives this decision its own leaderboard, which only works if a
    decision can later be judged to have been wrong - and one that cannot
    explain itself cannot be."""
    for signature in (_sig(complexity=COMPLEXITY_HIGH_STAKES),
                      _sig(error_cost=ERROR_COST_HIGH, ambiguity=JUDGEMENT_HIGH),
                      _sig(tool_use_required=True)):
        decision = cap.decide(signature, local_available=True)
        assert decision.path == cap.PATH_EXTERNAL
        assert len(decision.reason) > 30
        assert "provisional" in decision.reason


def test_the_ruleset_is_versioned():
    """So a routing record can say which rules produced a decision, and evidence
    gathered under one set is not silently compared against another."""
    assert cap.decide(_sig(), local_available=True).rule_version == cap.RULE_VERSION
    assert cap.RULE_VERSION >= 1


def test_a_decision_without_a_reason_cannot_be_built():
    with pytest.raises(ValueError):
        cap.CapabilityDecision(path=cap.PATH_LOCAL, reason="  ",
                               deterministic_possible=False, local_sufficient=True)


def test_an_unknown_path_cannot_be_built():
    with pytest.raises(ValueError):
        cap.CapabilityDecision(path="vibes", reason="x",
                               deterministic_possible=False, local_sufficient=True)


# --- it flows into the log without translation --------------------------------------


def test_a_decision_flows_straight_into_the_routing_record(tmp_path, monkeypatch):
    """§24's flow, joined up: the fields this module returns are the fields
    `routing_decisions.record_decision` takes. Anything needing re-derivation
    between them would be a place for the two to disagree about what was
    decided."""
    from app import model_performance as mp
    from app import routing_decisions as rd

    monkeypatch.setenv(mp.PATH_ENV, str(tmp_path / "perf.db"))
    signature = _sig()
    decision = cap.decide(signature, local_available=False)

    decision_id = rd.record_decision(
        signature, reason=decision.reason, execution_path=decision.path,
        selected_model="claude-sonnet-5", selected_provider="anthropic",
        deterministic_possible=decision.deterministic_possible,
        local_sufficient=decision.local_sufficient)

    logged = rd.get(decision_id)
    assert logged["execution_path"] == decision.path
    assert logged["deterministic_possible"] is False
    assert logged["local_sufficient"] is False
    assert logged["privacy_violation"] is False


def test_a_deterministic_decision_flows_in_without_a_model(tmp_path, monkeypatch):
    """`record_decision` refuses a deterministic path that names a model (§106),
    so these two modules have to agree - and they do, because a deterministic
    decision carries no model to name."""
    from app import model_performance as mp
    from app import routing_decisions as rd

    monkeypatch.setenv(mp.PATH_ENV, str(tmp_path / "perf.db"))
    signature = _sig()
    decision = cap.decide(signature, operation="portfolio_concentration")

    decision_id = rd.record_decision(
        signature, reason=decision.reason, execution_path=decision.path,
        selected_model=None,
        deterministic_possible=decision.deterministic_possible,
        local_sufficient=decision.local_sufficient)

    assert rd.get(decision_id)["execution_path"] == rd.PATH_DETERMINISTIC


def test_this_module_makes_privacy_misrouting_impossible(tmp_path, monkeypatch):
    """§106 detected a LOCAL_ONLY task that went external and could only report
    it after the fact. Routed through this module, that decision is never made -
    the refusal happens before anything reaches the log."""
    from app import model_performance as mp
    from app import routing_decisions as rd

    monkeypatch.setenv(mp.PATH_ENV, str(tmp_path / "perf.db"))
    signature = _sig(privacy_level=PRIVACY_LOCAL_ONLY)
    decision = cap.decide(signature, local_available=False)

    assert decision.path == cap.PATH_REFUSED
    assert decision.path not in rd.EXECUTION_PATHS, (
        "a refusal is not an execution path - there is nothing to log because "
        "nothing ran")


# --- scope --------------------------------------------------------------------------


def test_this_module_names_no_model_and_reads_no_leaderboard():
    """§3: the two decisions must not be conflated. This one answers *which
    path*; TQ-60 answers *which model*, weighing hardware load, availability and
    budget as well as the rankings."""
    body = conftest.executable_source(REPO / "app" / "capability.py")

    for leaked in ("leaderboard", "front_runner", "ranking", "model_performance",
                   "claude", "llama", "select_model"):
        assert leaked not in body, (
            f"{leaked!r} appears in capability's code: this module chooses a path, "
            "not a model")


def test_the_summary_is_honest_about_there_being_no_local_path():
    report = cap.summary()

    assert report["local_available"] is False
    assert "cannot be done at all" in report["note"]
    assert set(report["deterministic_operations"]) == {
        c.operation for c in cap.DETERMINISTIC_CAPABILITIES}
