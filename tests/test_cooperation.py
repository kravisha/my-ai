"""Reading the cooperation the organization already records (TQ-92;
addendum 48 §3, §12, §13; addendum 37 O9; docs/SPEC_RECONCILIATION.md §131, §149).

Nothing here is a new measurement. `cross_check_requests` has recorded one agent
asking another for help and the answer coming back or not since long before
addendum 48 asked for cooperation to be measured — under a *timing* rationale.

So the tests are mostly about what this must **not** become. Addendum 48 §12
forbids *"empty activity, performative work… and actions that create work without
creating value"*, and a cooperation score is the shortest route to all of it: an
agent answering everything with nothing would score perfectly and cooperate not at
all.

`test_there_is_no_score_and_no_ranking` is the one that matters, and
`test_the_outcome_vocabulary_is_not_restated_here` is the one that caught a real
defect — the schema comment beside the `outcome` column named a value the code has
never written, and the first draft of this module trusted it and matched nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from backend import cooperation, fi_db

ROOT = Path(__file__).resolve().parent.parent

ASKER = "speculator-1"
HELPER = "explorer-1"
OTHER = "explorer-2"


def _register(conn, identity, role):
    fi_db.register_agent(conn, identity, role, pid=1000 + len(identity))


@pytest.fixture
def team(conn):
    for identity, role in ((ASKER, "speculator"), (HELPER, "explorer"), (OTHER, "explorer")):
        _register(conn, identity, role)
    return conn


def _ask(conn, *, asker=ASKER, of_role="explorer", security="SYN1") -> int:
    return fi_db.open_cross_check(
        conn, asker, "t0", "speculator", of_role, security,
        question="Is there a dislocation here?",
        requester_finding={"confidence": 0.7}, requester_confidence=0.7)


def _answer(conn, request_id, *, by=HELPER, outcome=None):
    fi_db.answer_cross_check(
        conn, request_id, by, "t0", outcome or fi_db.CROSS_CHECK_EVIDENCE,
        responder_finding={"seen": True}, responder_confidence=0.6)


def _find(rows, identity):
    return next((row for row in rows if row["identity"] == identity), None)


# --- what this must never become ---------------------------------------------------------

def test_there_is_no_score_and_no_ranking():
    """**The property this module exists to hold.**

    A cooperation score is a metric agents will optimize, and addendum 48 §12
    forbids precisely the behaviour that follows. Asserted over the parsed module
    because the property is the *absence* of a capability — prevention by absence,
    the same argument §120 makes about the safest write path."""
    tree = ast.parse((ROOT / "backend" / "cooperation.py").read_text(encoding="utf-8"))
    defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    for forbidden in ("rank", "score", "rate", "grade", "leaderboard", "ranking",
                      "best", "worst", "top"):
        assert forbidden not in defined, (
            f"backend/cooperation.py defines {forbidden}(); a cooperation score is the "
            f"shortest route to addendum 48 §12's empty activity and performative work.")


def test_nothing_ranks_agents_on_cooperation():
    """`backend/competency.py` already ranks, so the machinery is one import
    away. This asserts nobody has reached for it — which is a different claim
    from cooperation having no ranking function of its own."""
    for path in (ROOT / "backend").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "cooperation" in text and "competency.rank" in text:
            pytest.fail(f"{path.name} ranks on cooperation")


def test_the_report_says_it_has_no_ranking_rather_than_leaving_it_to_be_noticed(team):
    """A reader arriving with addendum 48 §3 in mind is looking for a leadership
    criterion. Saying there is none is part of the answer."""
    report = cooperation.report(team)
    assert "no score and no ranking" in report["no_ranking"]
    assert any("threshold" in line for line in report["not_measured"])
    assert any("maturity" in line for line in report["not_measured"])


# --- the vocabulary is taken, not restated -----------------------------------------------

def test_the_outcome_vocabulary_is_not_restated_here():
    """**This caught a real defect.** The schema comment beside `outcome` said
    `'answered'` for a value the code has always written as `'evidence'`, and the
    first draft of this module trusted the comment and matched nothing — a query
    that silently returns zero rows, which is the failure mode a wrong comment
    produces and a wrong constant does not.

    So the vocabulary comes from `fi_db` and this pins that it still does."""
    assert cooperation.ANSWERS == (fi_db.CROSS_CHECK_EVIDENCE, fi_db.CROSS_CHECK_NO_EVIDENCE)

    # String constants in *code*, not in prose - the docstring above quotes the
    # wrong value deliberately, and a substring scan over the file would be
    # defeated by the very explanation of the defect.
    tree = ast.parse((ROOT / "backend" / "cooperation.py").read_text(encoding="utf-8"))
    docstrings = {
        node.body[0].value
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body
        and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)
    }
    literals = {
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and node not in docstrings
    }
    # The outcome VALUES, not field names. `"answered"` is a legitimate key in
    # `by_role`'s output and was never an outcome value at all - which is the
    # defect in miniature: the word reads like a value and is not one.
    for spelled in (fi_db.CROSS_CHECK_EVIDENCE, fi_db.CROSS_CHECK_NO_EVIDENCE,
                    fi_db.CROSS_CHECK_UNANSWERED):
        assert spelled not in literals, (
            f"cooperation.py spells the outcome {spelled!r} literally; it must come from fi_db, "
            f"because a second copy of a vocabulary is one that goes stale without failing")


def test_the_schema_comment_names_the_constants_rather_than_the_values():
    """The fix for the defect above, pinned. A comment listing literal values is
    one that goes stale without failing; a comment naming the constants sends a
    reader to the definition."""
    schema = (ROOT / "backend" / "fi_db.py").read_text(encoding="utf-8")
    assert "CROSS_CHECK_EVIDENCE | CROSS_CHECK_NO_EVIDENCE | CROSS_CHECK_UNANSWERED" in schema


# --- what it reports ----------------------------------------------------------------------

def test_an_answered_request_credits_the_responder_and_costs_the_asker_nothing(team):
    _answer(team, _ask(team))
    rows = cooperation.by_agent(team)

    helper = _find(rows, HELPER)
    assert helper["answered_with_a_finding"] == 1
    assert helper["answered_no_evidence"] == 0

    asker = _find(rows, ASKER)
    assert asker["asked"] == 1 and asker["left_waiting"] == 0


def test_an_honestly_empty_answer_is_an_answer(team):
    """An agent that looked and found nothing has helped. Counting it as a
    non-answer would push agents toward manufacturing findings — addendum 48 §12's
    empty activity, arriving through the measurement meant to discourage it."""
    _answer(team, _ask(team), outcome=fi_db.CROSS_CHECK_NO_EVIDENCE)
    rows = cooperation.by_agent(team)

    assert _find(rows, HELPER)["answered_no_evidence"] == 1
    assert _find(rows, ASKER)["left_waiting"] == 0
    assert cooperation.by_role(team)[0]["left_waiting"] == 0


def test_being_left_waiting_is_counted_against_the_asker_not_the_responder(team):
    """**The only unambiguous failure here, and it has nobody to blame.** A
    cross-check names the role it is addressed to and acquires a responder only
    when somebody answers, so an unanswered request is a fact about the
    organization's staffing rather than about an individual's willingness."""
    _ask(team)
    rows = cooperation.by_agent(team)

    assert _find(rows, ASKER)["left_waiting"] == 1
    assert _find(rows, HELPER) is None, (
        "an unanswered request was attributed to an agent that never saw it")
    assert cooperation.by_role(team) == [
        {"role": "explorer", "asked_of": 1, "answered": 0, "left_waiting": 1}]


def test_answering_everything_emptily_shows_as_composition_not_as_a_good_score(team):
    """The gaming case, and the answer to it is that there is no number to game.
    An agent answering ten requests with nothing is *visible as that* — the two
    counts sit side by side and nothing collapses them."""
    for _ in range(10):
        _answer(team, _ask(team), outcome=fi_db.CROSS_CHECK_NO_EVIDENCE)
    helper = _find(cooperation.by_agent(team), HELPER)

    assert helper["answered_no_evidence"] == 10
    assert helper["answered_with_a_finding"] == 0
    assert helper["answers_used"] == 0
    # And no aggregate exists that would have read as a perfect score.
    assert "score" not in helper and "rate" not in helper


def test_an_answer_a_report_was_built_on_is_recorded_as_used(team):
    """The outcome half: help that went somewhere. Not a quality score — an
    honest *no evidence* is cooperation and will never be used."""
    request = _ask(team)
    _answer(team, request)
    fi_db.enqueue_report(team, ASKER, "t0", "lead", "SYN1", summary="s",
                         evidence_ids=[], cross_check_id=request)

    assert _find(cooperation.by_agent(team), HELPER)["answers_used"] == 1


def test_a_used_answer_stays_used_after_the_report_is_completed(team):
    """A judged report moves to the archive, and the help it was built on does not
    stop having been used — §132's defect, which keeps arriving."""
    request = _ask(team)
    _answer(team, request)
    report = fi_db.enqueue_report(team, ASKER, "t0", "lead", "SYN1", summary="s",
                                  evidence_ids=[], cross_check_id=request)
    fi_db.complete_report(team, report, "analyzed",
                          handled_by_identity="analysis-1", handled_by_spawned_at="t0")

    assert _find(cooperation.by_agent(team), HELPER)["answers_used"] == 1


def test_an_agent_that_has_neither_asked_nor_answered_is_absent(team):
    """Absent rather than present with zeroes. It has not been in a position to
    cooperate or fail to, and a row of zeroes reads as a finding (§100, §104)."""
    _answer(team, _ask(team))
    assert _find(cooperation.by_agent(team), OTHER) is None


# --- the second signal: questions left for whoever comes next -----------------------------

def test_answering_another_agents_open_question_counts(team):
    """The other kind of asking: a cross-check is addressed to somebody, an open
    question is left for whoever comes next."""
    question = fi_db.record_knowledge(
        team, record_kind="open_question", subject="SYN1",
        statement="Why did the surface move?", recorded_by=ASKER)
    report = fi_db.enqueue_report(team, ASKER, "t0", "lead", "SYN1",
                                  summary="s", evidence_ids=[])
    result = fi_db.record_analysis_result(
        team, HELPER, "t0", report, "SYN1", "thesis", "e", 0.5, "some")
    fi_db.resolve_knowledge(team, question, resolved_by_ref=f"analysis_results:{result}")

    assert _find(cooperation.by_agent(team), HELPER)["questions_answered_for_others"] == 1


def test_answering_your_own_question_is_not_cooperation(team):
    """That is the organization thinking, not one agent helping another — and
    counting it would be §147's self-evaluation in a new place."""
    question = fi_db.record_knowledge(
        team, record_kind="open_question", subject="SYN1",
        statement="Why did the surface move?", recorded_by=HELPER)
    report = fi_db.enqueue_report(team, ASKER, "t0", "lead", "SYN1",
                                  summary="s", evidence_ids=[])
    result = fi_db.record_analysis_result(
        team, HELPER, "t0", report, "SYN1", "thesis", "e", 0.5, "some")
    fi_db.resolve_knowledge(team, question, resolved_by_ref=f"analysis_results:{result}")

    helper = _find(cooperation.by_agent(team), HELPER)
    assert helper is None or helper["questions_answered_for_others"] == 0


# --- it agrees with the measurement that was already there --------------------------------

def test_it_agrees_with_the_metric_that_has_been_running_all_along(team):
    """`cross_check.unanswered_rate` has measured this for months under a timing
    rationale. Two readings of one fact that could disagree would mean one of them
    was measuring something else — which is exactly what §149 found about the
    schema comment."""
    from simulation import metrics

    for _ in range(3):
        _answer(team, _ask(team))
    _ask(team)

    left = sum(row["left_waiting"] for row in cooperation.by_role(team))
    collected = metrics._cross_check(team)
    assert collected["total"] == 4

    # **The two readings differ by design, and the difference is the point.**
    # `unanswered_rate` counts only requests that timed out and were marked
    # `unanswered`; a request still sitting open is `open_at_end`. From the
    # asker's side both are the same experience - nobody has answered - so
    # `left_waiting` merges them, and this pins the relationship rather than
    # asserting an equality that would quietly stop being true.
    timed_out = collected["outcomes"].get(fi_db.CROSS_CHECK_UNANSWERED, 0)
    assert left == timed_out + collected["open_at_end"] == 1
