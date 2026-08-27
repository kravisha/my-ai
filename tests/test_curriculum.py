"""The portfolio-analysis curriculum, and what running it says (TQ-76;
addendum 36, §114, §115).

§60 disposition 3 deferred Education's machinery *"until a real curriculum need
the existing loop cannot express."* §114 checked and it could not. This is what
lifted: the curriculum and the grade, not the Curriculum Architect.

Two tests carry the weight.

`test_the_analyst_detects_a_silently_partial_account` is the one to read first,
and it **used to assert the opposite**. It was a declared `KNOWN_GAP` - an
exercise the system was expected to fail, in the curriculum so the absence was
recorded rather than silent. It failed for a day, said why, and TQ-80 closed it;
when it started passing the runner reported *"the curriculum is out of date"*
rather than absorbing the win, and it was reclassified deliberately.

`test_a_known_gap_is_still_supported_and_still_must_fail` is the other, and it
exists because the first one stopped being a gap. A mechanism with no user rots,
and the KNOWN_GAP machinery has to keep working for the next absence somebody
finds - so it is exercised against a gap declared for the purpose.
"""

import json

import pytest

from agents import portfolio_analyst
from backend import curriculum as curriculum_module
from simulation import training


@pytest.fixture
def analyst():
    return lambda conn: portfolio_analyst._analyst_work(conn, "analyst-1")


def _exercise(exercise_id):
    return curriculum_module.PORTFOLIO_ANALYSIS_V1.by_id(exercise_id)


# --- the curriculum is well formed --------------------------------------------------


def test_every_exercise_declares_a_competency_that_exists():
    """A curriculum whose exercises point at competencies nobody defined is a
    list of tasks rather than a curriculum."""
    curriculum = curriculum_module.PORTFOLIO_ANALYSIS_V1
    for exercise in curriculum.exercises:
        assert exercise.competency in curriculum.competencies, (
            f"{exercise.exercise_id} trains {exercise.competency!r}, which is not defined")


def test_every_competency_is_exercised():
    """The other direction. A competency nothing exercises is a claim about what
    the organization values that nothing tests."""
    curriculum = curriculum_module.PORTFOLIO_ANALYSIS_V1
    exercised = {exercise.competency for exercise in curriculum.exercises}
    assert set(curriculum.competencies) == exercised


def test_every_exercise_says_why_it_exists():
    """An exercise without a stated reason is one nobody can decide to retire -
    and a curriculum that only grows is one that eventually trains against
    problems the system no longer has."""
    for exercise in curriculum_module.PORTFOLIO_ANALYSIS_V1.exercises:
        assert len(exercise.why) > 60


def test_remediation_and_capability_are_both_present_and_distinguished():
    """Addendum 36 §4: *"the curriculum should distinguish remediation from
    capability-building because their goals and measurement differ."* Collapsing
    them would make every hard exercise look like a bug and every regression look
    like an ambition."""
    kinds = {exercise.kind for exercise in curriculum_module.PORTFOLIO_ANALYSIS_V1.exercises}
    assert kinds == {curriculum_module.KIND_REMEDIATION,
                     curriculum_module.KIND_CAPABILITY}


def test_an_exercise_with_no_source_is_refused():
    with pytest.raises(curriculum_module.CurriculumError):
        curriculum_module.Exercise(
            exercise_id="x", competency="consolidation",
            kind=curriculum_module.KIND_CAPABILITY, client="avery", sources=(),
            why="a reason long enough to be a reason and not a shrug at all really")


def test_an_exercise_without_a_stated_reason_is_refused():
    """`test_every_exercise_says_why_it_exists` checks the exercises that exist;
    this checks the guard that keeps a new one from arriving without a reason.

    Found by mutation testing: removing the guard changed nothing observable,
    because every current exercise has a `why`. A test over data does not test
    the rule that produced the data."""
    with pytest.raises(curriculum_module.CurriculumError):
        curriculum_module.Exercise(
            exercise_id="x", competency="consolidation",
            kind=curriculum_module.KIND_CAPABILITY, client="avery", sources=("a",),
            why="")


def test_an_unknown_kind_is_refused():
    with pytest.raises(curriculum_module.CurriculumError):
        curriculum_module.Exercise(
            exercise_id="x", competency="consolidation", kind="vibes",
            client="avery", sources=("a",),
            why="a reason long enough to be a reason and not a shrug at all really")


def test_the_curriculum_is_versioned():
    """§2.1 asks for versions, and §11 asks the curriculum to adapt from results.
    A curriculum edited in place would make every past grade
    uninterpretable."""
    assert curriculum_module.PORTFOLIO_ANALYSIS_V1.version == 1
    assert curriculum_module.PORTFOLIO_ANALYSIS_V1.name in curriculum_module.CURRICULA


# --- running it ---------------------------------------------------------------------


def test_the_analyst_passes_every_exercise_it_should(conn, analyst):
    """The real analyst, the real transport, the real provider lookup. Only the
    world is simulated."""
    outcome = training.run_curriculum(conn, analyst)

    should_pass = [result for result in outcome["outcomes"]
                   if result["expectation"] == curriculum_module.EXPECT_PASS]
    failed = [result["exercise_id"] for result in should_pass if not result["passed"]]

    assert should_pass, "the curriculum has no exercises that should pass"
    assert not failed, (
        f"the analyst failed {failed}. Complaints: "
        f"{[r['complaints'] for r in should_pass if not r['passed']]}")


def test_the_analyst_detects_a_silently_partial_account(conn, analyst):
    """**The one to read first**, and it used to assert the opposite.

    This was a declared `KNOWN_GAP`: a broker returning two of four positions
    sends a well-formed answer, and the analyst had no way to know it was short.
    The exercise failed on purpose, said why in the report, and TQ-80 closed it -
    the account is asked how much it holds, and the two disagreeing is the
    signal.

    When it began passing, the runner reported *"the curriculum is out of date"*
    rather than absorbing the win quietly, and the exercise was reclassified
    deliberately. That is the whole loop working: declare the absence, fail
    loudly, close it, be told."""
    result = training.run_exercise(
        conn, _exercise("portfolio.detects_a_silently_partial_account"), analyst)

    assert result["passed"] is True
    assert result["verdict"] == "satisfied", (
        f"the client is still unhappy: {result['complaints']}")
    assert result["curriculum_out_of_date"] is False


def test_an_unreachable_source_is_reported_rather_than_hidden(conn, analyst):
    result = training.run_exercise(
        conn, _exercise("portfolio.says_when_a_source_was_unreachable"), analyst)

    assert result["passed"] is True
    codes = {complaint["code"] for complaint in result["complaints"]}
    assert "partial_presented_as_complete" not in codes
    assert "account_vanished" not in codes


def test_one_source_down_does_not_cost_the_client_the_answer(conn, analyst):
    """The failure easier to reach by being careful: refusing the whole analysis
    because one source was down."""
    result = training.run_exercise(
        conn, _exercise("portfolio.still_answers_when_one_source_is_down"), analyst)

    assert result["passed"] is True
    codes = {complaint["code"] for complaint in result["complaints"]}
    assert "no_answer" not in codes and "refused" not in codes


def test_two_exercises_do_not_share_a_world(conn, analyst):
    """A fault declared in one exercise must not leak into the next. Two
    exercises with different worlds run in one process, and neither can reach
    into the other's."""
    training.run_exercise(
        conn, _exercise("portfolio.says_when_a_source_was_unreachable"), analyst)
    clean = training.run_exercise(
        conn, _exercise("portfolio.consolidates_two_sources"), analyst)

    assert clean["passed"] is True


def test_an_exercise_puts_the_world_back_when_it_finishes(conn, analyst):
    """The half the test above does not reach, found by mutation testing:
    disabling the restore changed nothing, because each exercise installs its own
    world on the way in and never reads the previous one.

    What a leak actually costs is everything *outside* an exercise - a later
    fetch, a test, a live run - silently served by a broken exchange somebody
    declared for one exercise. So the assertion is about the registry, not about
    the next exercise's grade."""
    from backend import portfolio_providers
    from simulation import exchange

    before = portfolio_providers._PROVIDERS[exchange.PROVIDER_TYPE]

    training.run_exercise(
        conn, _exercise("portfolio.says_when_a_source_was_unreachable"), analyst)

    assert portfolio_providers._PROVIDERS[exchange.PROVIDER_TYPE] is before, (
        "an exercise left its faulty exchange registered; everything after it would be "
        "served by a world somebody declared for one exercise")


def test_the_client_notices_being_answered_a_different_question(conn):
    """The check the refusal exercise depends on, tested directly.

    Mutation testing found that disabling it changed nothing: the analyst
    *refuses* a stress test rather than substituting, so the complaint never
    fires either way and the exercise passes regardless. The exercise is still
    right — it would catch a substitution — but it does not exercise the
    detection, so this does."""
    from simulation import client_sessions

    client = client_sessions.SimulatedClient(
        client_id="morgan", session_id="s", sources=[{"name": "morgan-brokerage"}],
        truth={"morgan-brokerage": []})
    client.asked_for = "stress_test"

    verdict = client.judge({"status": "ready", "result": {
        "requested": "concentration", "sources": ["morgan-brokerage"],
        "failed_sources": [], "complete": True, "positions": [],
        "analysis": {"priced": False}}})

    codes = {complaint["code"] for complaint in verdict["complaints"]}
    assert "answered_a_different_question" in codes


# --- what a run leaves behind -------------------------------------------------------


def test_a_run_leaves_no_client_data(conn, analyst):
    """§111 applies to training too. The exercise is the production workflow with
    invented inputs, and the workflow discards on disconnect."""
    from backend import analysis_requests

    training.run_curriculum(conn, analyst)

    assert analysis_requests.outstanding(conn)["clean"] is True
    assert conn.fetchone(
        "SELECT COUNT(*) AS n FROM portfolio_analysis_requests")["n"] == 0


def test_an_exercise_that_falls_over_still_leaves_nothing(conn):
    """**The case the test above passes without exercising**, found by mutation
    testing: on the happy path the row is already gone, because `collect` deletes
    on read. So that test proves delete-on-read works, not that the disconnect
    does.

    The disconnect is what covers the path where nothing was ever collected —
    which is the path an exercise takes when it fails, and the one where a
    client's report would otherwise sit on disk."""
    from backend import analysis_requests

    def explode(_conn):
        raise RuntimeError("the analyst fell over mid-exercise")

    with pytest.raises(RuntimeError):
        training.run_exercise(
            conn, _exercise("portfolio.consolidates_two_sources"), explode)

    assert conn.fetchone(
        "SELECT COUNT(*) AS n FROM portfolio_analysis_requests")["n"] == 0


def test_a_result_records_the_grade_and_never_a_position(conn, analyst):
    """**The line this subsystem turns on.** Exercise results are kept - they are
    the organization's own learning about imaginary clients. Positions are still
    never written down, because a log that accumulated SYN2 and AAPL would
    establish exactly the habit §111 exists to prevent, in the one place nobody
    would think to look."""
    training.run_curriculum(conn, analyst)

    rows = conn.fetchall("SELECT * FROM curriculum_results")
    assert rows, "nothing was recorded"
    dumped = json.dumps([dict(row) for row in rows])
    for symbol in ("SYN1", "SYN2", "SYN5", "SYN2C350", "SYN4", "SYN6"):
        assert symbol not in dumped, f"an exercise result recorded {symbol}"
    # And what it does record is usable.
    assert all(row["competency"] for row in rows)
    assert all(row["verdict"] for row in rows)


def test_a_result_keeps_the_rule_a_complaint_named(conn, analyst):
    """*"Disappointed"* is a mood. A complaint that names its rule is something a
    curriculum can act on."""
    training.run_exercise(
        conn, _exercise("portfolio.refuses_rather_than_substituting"), analyst)

    row = conn.fetchone("SELECT complaints FROM curriculum_results ORDER BY id DESC")
    complaints = json.loads(row["complaints"])
    assert complaints
    assert all(complaint["rule"] for complaint in complaints)
    assert all("detail" not in complaint for complaint in complaints), (
        "a complaint's detail quotes symbols and must not be recorded")


# --- the report Education reads -----------------------------------------------------


def test_the_report_separates_a_regression_from_a_difficulty(conn, analyst):
    """A remediation failure is a defect - the failure it was written after has
    recurred. A capability failure is a finding. One number would average them
    together."""
    outcome = training.run_curriculum(conn, analyst)
    report = outcome["report"]

    assert report["regressions"] == [], (
        f"a remediation exercise regressed: {report['regressions']}")
    assert report["by_competency"]["detect_silent_loss"]["passed"] == 1
    assert report["by_competency"]["honest_partial"]["passed"] == 2


def test_the_report_says_when_the_curriculum_is_out_of_date(conn):
    """A known gap that passes is not a failure - it is a signal that somebody
    built the capability and the curriculum owes an update (§11)."""
    # A gap declared over something the system handles fine. It used to be a real
    # exercise; TQ-80 closed the last one, so the mechanism is exercised against
    # a declared gap rather than a remembered one.
    exercise = curriculum_module.Exercise(
        exercise_id="portfolio.a_gap_that_is_not_one",
        competency="consolidation", kind=curriculum_module.KIND_CAPABILITY,
        client="avery", sources=("avery-brokerage",),
        expectation=curriculum_module.EXPECT_KNOWN_GAP,
        must_not_complain=("positions_missing",),
        why="Exercises the out-of-date report, which no real gap does now.")
    curriculum_module.record_result(
        conn, curriculum_module.PORTFOLIO_ANALYSIS_V1, exercise,
        {"verdict": "satisfied", "complaints": []})

    report = curriculum_module.report(conn, curriculum_module.PORTFOLIO_ANALYSIS_V1)

    assert report["curriculum_out_of_date"] == [exercise.exercise_id]
    assert "reclassify" in report["note"]


def test_the_report_names_a_regression_loudly(conn):
    exercise = _exercise("portfolio.says_when_a_source_was_unreachable")
    curriculum_module.record_result(
        conn, curriculum_module.PORTFOLIO_ANALYSIS_V1, exercise,
        {"verdict": "disappointed",
         "complaints": [{"code": "partial_presented_as_complete", "rule": "TQ-78"}]})

    report = curriculum_module.report(conn, curriculum_module.PORTFOLIO_ANALYSIS_V1)

    assert exercise.exercise_id in report["regressions"]
    assert "regression rather than a difficulty" in report["note"]


def test_a_clean_report_says_so_plainly(conn, analyst):
    """With the last known gap closed, the honest report is a clean one - and it
    says so in one sentence rather than listing what did not go wrong."""
    outcome = training.run_curriculum(conn, analyst)

    assert outcome["report"]["note"] == "Every exercise met its bar."
    assert outcome["report"]["exercises_run"] == len(
        curriculum_module.PORTFOLIO_ANALYSIS_V1.exercises)


def test_a_known_gap_is_still_supported_and_still_must_fail(conn, analyst):
    """The mechanism outlives the gap that motivated it.

    With every declared gap now closed, nothing in the curriculum exercises
    `EXPECT_KNOWN_GAP` - and an unexercised mechanism is one that rots. This
    declares a gap the system genuinely does not have (an analysis it cannot
    perform, asked of a source that is fine) and asserts the two properties that
    matter: a known gap that fails is *not* a failure, and one that passes is
    reported as the curriculum being out of date."""
    gap = curriculum_module.Exercise(
        exercise_id="portfolio.known_gap_probe",
        competency="consolidation", kind=curriculum_module.KIND_CAPABILITY,
        client="avery", sources=("avery-brokerage",),
        expectation=curriculum_module.EXPECT_KNOWN_GAP,
        must_not_complain=("positions_missing",),
        why="Exercises the KNOWN_GAP mechanism itself, which no real gap does today.")

    result = training.run_exercise(conn, gap, analyst)

    # The analyst handles this fine, so the declared gap does not exist.
    assert result["passed"] is False, "a KNOWN_GAP exercise must never count as passed"
    assert result["curriculum_out_of_date"] is True, (
        "a known gap the system does not actually have must be reported as the "
        "curriculum being out of date")


# --- what deliberately did not lift --------------------------------------------------


def test_no_curriculum_architect_agent_was_built():
    """§114: the curriculum lifts, the role-holding agent does not. A need for a
    curriculum is not evidence for an agent that owns curricula, and addendum 36
    §2.3's professor layer defers itself."""
    from pathlib import Path

    agents_dir = Path(__file__).resolve().parent.parent / "agents"
    built = {path.stem for path in agents_dir.glob("*.py")}

    assert "curriculum_architect" not in built
    assert "trainer" not in built
