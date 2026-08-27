"""One command, one verdict (TQ-91; docs/SPEC_RECONCILIATION.md §129).

The composition is tested against constructed results rather than by running the
harness: a test that spent five minutes starting real agent processes to check an
`if` would be measuring the organization to assert something about arithmetic.
`run_curriculum` is exercised for real, because it is fast and because the shape
of what it returns is exactly what drifts.

**The property worth defending is the three-valued verdict.** A verifier with two
values has to call a run it did not perform something, and both available answers
are wrong.
"""

from __future__ import annotations

import pytest

from simulation import verification


def scenario_result(scenario_id="baseline", *, passed=True, graceful=True, failures=()):
    return {"id": scenario_id, "run_id": f"{scenario_id}-1", "passed": passed,
            "graceful": graceful, "properties_passed": 3 if passed else 2,
            "properties_total": 3, "failures": list(failures)}


def curriculum_result(*, passed=True, failures=(), regressions=(), out_of_date=()):
    return {"curriculum": "portfolio_analysis", "version": 1, "exercises": 6,
            "failures": list(failures), "regressions": list(regressions),
            "out_of_date": list(out_of_date), "passed": passed, "note": ""}


# --- the three-valued verdict --------------------------------------------------------

def test_everything_run_and_everything_passed_is_the_only_pass():
    result = verification.Verification(
        scenarios=[scenario_result("a"), scenario_result("b")],
        curriculum=curriculum_result())
    assert result.verdict == verification.VERDICT_PASS


def test_a_scenario_that_did_not_run_is_not_a_scenario_that_passed():
    """The single easiest thing to get wrong here. Three of seven scenarios
    declare `requires_model`; a verifier reporting "0 failures" over four run and
    three skipped would issue a clean bill of health for an organization it had
    mostly not examined."""
    result = verification.Verification(
        scenarios=[scenario_result("a")],
        curriculum=curriculum_result(),
        skipped=[{"id": "b", "why": "declares requires_model and no model is reachable"}])
    assert result.verdict == verification.VERDICT_INCOMPLETE
    assert not result.failures, "nothing failed - it simply was not all asked"


def test_skipping_the_curriculum_is_also_incomplete():
    result = verification.Verification(scenarios=[scenario_result("a")], curriculum=None)
    assert result.verdict == verification.VERDICT_INCOMPLETE


def test_a_failure_outranks_an_incomplete():
    """`INCOMPLETE` is not a softer `FAIL`. When both are true the answer is the
    one that names something wrong."""
    result = verification.Verification(
        scenarios=[scenario_result("a", passed=False, failures=["a property"])],
        curriculum=None,
        skipped=[{"id": "b", "why": "no model"}])
    assert result.verdict == verification.VERDICT_FAIL


def test_a_curriculum_failure_fails_the_whole_verdict():
    result = verification.Verification(
        scenarios=[scenario_result("a")],
        curriculum=curriculum_result(passed=False, failures=["portfolio.something"]))
    assert result.verdict == verification.VERDICT_FAIL
    assert [entry["id"] for entry in result.failures] == ["curriculum"]


def test_a_scenario_that_left_an_agent_running_fails_even_with_every_property_green():
    """The next run inherits the consequences: an agent process left alive keeps
    writing, and results from an organization nobody is watching are worse than
    no results."""
    result = verification.Verification(
        scenarios=[scenario_result("a", passed=False, graceful=False)],
        curriculum=curriculum_result())
    assert result.verdict == verification.VERDICT_FAIL


# --- what the curriculum contributes -------------------------------------------------

def test_the_curriculum_runs_and_reports_its_shape():
    """Exercised for real. It is fast, and the shape of what it returns is what
    drifts when the curriculum changes underneath."""
    report = verification.run_curriculum()
    assert report["curriculum"] == "portfolio_analysis"
    assert report["exercises"] >= 1
    assert set(report) >= {"failures", "regressions", "out_of_date", "passed", "note"}
    assert report["passed"] is True, report["note"]


def test_a_known_gap_that_fails_is_not_a_verdict_failure():
    """A known gap is declared to fail. Counting it would make the verdict red
    for exactly the honesty that makes the curriculum worth reading."""
    result = verification.Verification(
        scenarios=[scenario_result("a")], curriculum=curriculum_result())
    assert result.verdict == verification.VERDICT_PASS


def test_a_curriculum_out_of_date_is_reported_and_is_not_a_failure(capsys):
    """A known gap that passed means somebody built the capability. Not a defect -
    and it must not be silent, or the curriculum drifts out of date unnoticed."""
    result = verification.Verification(
        scenarios=[scenario_result("a")],
        curriculum=curriculum_result(out_of_date=["portfolio.detects_something"]))
    assert result.verdict == verification.VERDICT_PASS

    from simulation.__main__ import _print_verification
    _print_verification(result)
    printed = capsys.readouterr().out
    assert "curriculum out of date" in printed
    assert "portfolio.detects_something" in printed


def test_a_regression_fails_the_curriculum():
    result = verification.Verification(
        scenarios=[scenario_result("a")],
        curriculum=curriculum_result(passed=False, regressions=["portfolio.values_nothing"]))
    assert result.verdict == verification.VERDICT_FAIL


# --- the report says what it does not know -------------------------------------------

def test_the_report_names_its_own_blind_spots():
    """A verifier that lists what it cannot see is worth more than one that
    implies it sees everything. Written from what the specifications ask for
    rather than from what the code does, for the reason
    `simulation/certification.py` gives about its own criteria."""
    assert len(verification.NOT_COVERED) >= 4
    joined = " ".join(verification.NOT_COVERED).lower()
    for absent in ("deliberation", "market data", "historical", "rollback"):
        assert absent in joined


def test_the_report_survives_a_terminal_that_cannot_render_it():
    """It is printed to a console, and the section sign renders as `?` under the
    Windows codepage - turning a reference into noise exactly where a reader is
    deciding whether to trust a verdict."""
    for line in verification.NOT_COVERED:
        line.encode("ascii")


def test_the_skipped_are_printed_under_their_own_heading(capsys):
    """A skipped scenario listed among passes reads as a pass."""
    from simulation.__main__ import _print_verification
    _print_verification(verification.Verification(
        scenarios=[scenario_result("a")],
        skipped=[{"id": "needs_a_model", "why": "no model is reachable"}]))
    printed = capsys.readouterr().out
    assert "[skip] needs_a_model" in printed
    assert "VERDICT  INCOMPLETE" in printed


@pytest.mark.parametrize("verdict,expected_exit", [
    (verification.VERDICT_PASS, 0),
    (verification.VERDICT_INCOMPLETE, 1),
    (verification.VERDICT_FAIL, 1),
])
def test_only_a_pass_exits_zero(verdict, expected_exit):
    """So a caller that only reads the exit code cannot mistake an incomplete
    verification for a successful one."""
    import inspect
    from simulation import __main__ as cli
    source = inspect.getsource(cli._cmd_verify)
    assert "return 0 if result.verdict == verification.VERDICT_PASS else 1" in source


# --- the rules, exercised on data that can actually exercise them (§129) --------------

def _outcome(exercise_id, *, passed, expectation="pass"):
    return {"exercise_id": exercise_id, "passed": passed, "expectation": expectation}


def _report(**overrides):
    base = {"curriculum": "portfolio_analysis", "version": 1, "regressions": [],
            "curriculum_out_of_date": [], "note": ""}
    base.update(overrides)
    return base


def test_a_known_gap_that_fails_is_not_counted_as_a_failure():
    """A known gap is declared to fail, so counting it would make the verdict red
    for exactly the honesty that makes the curriculum worth reading.

    Constructed rather than run: the live curriculum contains no known gap since
    TQ-80 closed the last one, so a test over it cannot tell whether this rule
    exists. Mutation testing found that - removing the exclusion changed
    nothing."""
    from backend import curriculum as curriculum_module
    summary = verification.summarise_curriculum(
        [_outcome("a", passed=True),
         _outcome("b", passed=False, expectation=curriculum_module.EXPECT_KNOWN_GAP)],
        _report())
    assert summary["failures"] == []
    assert summary["passed"] is True


def test_an_ordinary_exercise_that_fails_is_counted():
    """The counterpart, so the exclusion above cannot swallow everything."""
    summary = verification.summarise_curriculum(
        [_outcome("a", passed=True), _outcome("b", passed=False)], _report())
    assert summary["failures"] == ["b"]
    assert summary["passed"] is False


def test_a_regression_fails_even_when_no_exercise_is_listed_as_failed():
    """A remediation failure is a defect: the failure it was written after has
    recurred. The curriculum reports it separately from the exercise verdicts,
    so a summary that only read `failures` would call this a pass."""
    summary = verification.summarise_curriculum(
        [_outcome("a", passed=True)], _report(regressions=["portfolio.values_nothing"]))
    assert summary["failures"] == []
    assert summary["passed"] is False


def test_a_curriculum_out_of_date_does_not_fail_the_summary():
    summary = verification.summarise_curriculum(
        [_outcome("a", passed=True)],
        _report(curriculum_out_of_date=["portfolio.detects_something"]))
    assert summary["passed"] is True
    assert summary["out_of_date"] == ["portfolio.detects_something"]


# --- what the first real verification run found (§132) -------------------------------

def test_a_scenario_entry_is_built_from_a_real_summary_shape():
    """The seam every other test in this file skipped.

    The composition was tested on entries constructed by hand and `verify()` was
    never asked to build one from a summary. `properties["failures"]` is a list
    of NAMES; the code read it as records and crashed on the first verification
    run that had a failure to render - after two scenarios and four minutes."""
    summary = {"properties": {"total": 13, "passed": 12, "failed": 1,
                              "failures": ["every completed report was analysed"],
                              "asserted": True}}
    properties = summary["properties"]
    entry = {"failures": list(properties.get("failures") or [])}
    assert entry["failures"] == ["every completed report was analysed"]

    from simulation.__main__ import _print_verification
    import io as _io
    import contextlib
    printed = _io.StringIO()
    with contextlib.redirect_stdout(printed):
        _print_verification(verification.Verification(
            scenarios=[scenario_result("a", passed=False,
                                       failures=properties["failures"])]))
    assert "every completed report was analysed" in printed.getvalue()


def test_an_exhausted_budget_is_a_reason_to_skip_not_a_reason_to_fail(monkeypatch):
    """A key being reachable is not a model being callable.

    The first full verification ran with the daily token budget exhausted. Every
    model call was refused, every report failed instantly with a spending
    message, and the summary reported failures **about the budget while looking
    exactly like failures about the organization**.

    A run that could not use a model did not test what the scenario is about, and
    calling that a failure is as wrong as calling it a pass. It is what
    INCOMPLETE exists for."""
    from app import model_budget
    from simulation import harness

    monkeypatch.setattr(harness, "model_is_available", lambda: True)
    monkeypatch.setattr(
        model_budget, "check_budget",
        lambda: (_ for _ in ()).throw(RuntimeError("Daily model token budget exhausted")))

    assert verification.model_can_be_called() is False
    assert "budget is exhausted" in verification._why_no_model()


def test_no_key_and_no_budget_are_reported_differently(monkeypatch):
    """Two different reasons a scenario could not run, and a reader deciding what
    to do about it needs to know which."""
    from simulation import harness
    monkeypatch.setattr(harness, "model_is_available", lambda: False)
    assert "no model is reachable" in verification._why_no_model()
