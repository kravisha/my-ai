"""A long task done in front of Krish, asking as it goes.

Krish, 2026-09-23: *"I should say Jarvis prepare my expense statements by
looking into my business account - ask me questions while you are working on the
account so that we don't have any confusion about what needs to be done. Also use
last year's statement as a model and ask me questions when you can't find the
data that you seek."*

Four separable claims, and the tests are grouped by them:

1. The model gives shape and never values, so last year's figure cannot become
   this year's.
2. A need is filled from a source or it is not filled.
3. The one who was asked is the one who may answer.
4. Finishing is a claim, and a hole is not an oversight - it is the failure that
   looks most like success.

The first is the one that needs structural proof rather than a passing example:
a `Model` that gained a `value` field would break no behavioural test at all
until the day a number came through it. So it is asserted over the parsed AST.

Probed by `tests/probes/taskrun_probes.py`.
"""

import ast
import inspect
from pathlib import Path

import pytest

from gateway import identity, taskrun
from gateway.taskrun import (ANSWERED, ASKED, FOUND, UNMET, WAIVED, Field,
                             Model, NotFound, NotYours, Run, Stuck)

LAST_YEAR = "last year's expense statement"


def statement():
    """Krish's own example: the shape of last year's statement, no figures."""
    return Model(name=LAST_YEAR, fields=(
        Field("travel", "flights and hotels charged to the business"),
        Field("software", "subscriptions charged to the business card"),
        Field("acme_invoice", "the Acme invoice, which arrives late")))


def run(goal="prepare the Q3 expense statement", **kwargs):
    return Run(goal, statement(), **kwargs)


# --- 1. the model gives shape, never values ---------------------------------

def test_a_model_is_the_headings_of_last_years_statement():
    made = statement()
    assert [one.name for one in made.fields] == [
        "travel", "software", "acme_invoice"]
    assert [one.means for one in made.fields] == [
        "flights and hotels charged to the business",
        "subscriptions charged to the business card",
        "the Acme invoice, which arrives late"]


def test_a_model_cannot_carry_a_value():
    """The load-bearing one, and it cannot be shown by an example.

    Every behavioural test here would still pass if `Field` grew a `value`, up
    until the morning a figure travelled through it. So this reads the class,
    not a run of it."""
    source = Path(inspect.getfile(taskrun)).read_text()
    tree = ast.parse(source)
    classes = {node.name: node for node in ast.walk(tree)
               if isinstance(node, ast.ClassDef)}

    for name in ("Field", "Model"):
        annotated = [node.target.id for node in classes[name].body
                     if isinstance(node, ast.AnnAssign)]
        assert annotated, f"{name} was expected to be a dataclass with fields"
        for attribute in annotated:
            assert attribute not in ("value", "values", "amount", "figure",
                                     "last_year", "previous"), (
                f"{name}.{attribute} is a way for last year's number to reach "
                f"this year's statement")
    assert [node.target.id for node in classes["Field"].body
            if isinstance(node, ast.AnnAssign)] == ["name", "means"]
    assert [node.target.id for node in classes["Model"].body
            if isinstance(node, ast.AnnAssign)] == ["name", "fields"]


def test_the_needs_a_model_makes_start_empty():
    for one in statement().needs():
        assert one.state == UNMET
        assert one.value is None
        assert one.source == ""


def test_a_model_with_no_fields_says_nothing_about_a_finished_statement():
    with pytest.raises(NotFound) as refusal:
        Model(name=LAST_YEAR, fields=())
    assert "lists no fields" in str(refusal.value)


def test_a_field_without_a_meaning_is_refused():
    with pytest.raises(NotFound):
        Field("travel", "  ")
    with pytest.raises(NotFound):
        Field("", "flights")


def test_a_line_not_in_the_model_is_not_part_of_this_statement():
    with pytest.raises(NotFound) as refusal:
        run().need("bonus")
    assert "different statement" in str(refusal.value)


def test_two_runs_of_the_same_model_do_not_share_their_needs():
    """A `Model` handing out the same `Need` objects would make one run's
    figures appear in the next one's - the copy-last-year failure by another
    road."""
    model = statement()
    first, second = Run("Q3", model), Run("Q4", model)
    first.need("travel").found("4,210.00", source="business account")
    assert second.need("travel").value is None
    assert second.need("travel").state == UNMET


# --- 2. a need is filled from a source or it is not filled ------------------

def test_a_found_value_records_where_it_came_from():
    task = run()
    task.need("travel").found(
        "4,210.00", source="business account, 12 rows tagged travel")
    assert task.need("travel").state == FOUND
    assert task.need("travel").value == "4,210.00"
    assert task.need("travel").source == "business account, 12 rows tagged travel"


def test_a_value_with_no_source_is_refused():
    with pytest.raises(NotFound) as refusal:
        run().need("travel").found("4,210.00", source="   ")
    assert "a value needs a source" in str(refusal.value)


def test_there_is_no_method_that_fills_a_need_without_saying_where_from():
    """*"There is no `assume`, no `default`, no `estimate`."* Written down in
    the module docstring, which is not a place that can enforce anything."""
    filling = [name for name, _ in inspect.getmembers(
        taskrun.Need, inspect.isfunction) if not name.startswith("_")]
    assert sorted(filling) == ["answered", "ask", "found", "waive"]
    for name in ("assume", "default", "estimate", "guess", "carry_over",
                 "same_as_last_year"):
        assert not hasattr(taskrun.Need, name)
    for name in ("found", "answered"):
        signature = inspect.signature(getattr(taskrun.Need, name))
        provenance = {"found": "source", "answered": "by"}[name]
        parameter = signature.parameters[provenance]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty, (
            f"Need.{name} would accept a value with no {provenance}")


def test_a_question_must_say_what_was_already_tried():
    with pytest.raises(NotFound) as refusal:
        run().ask("software", "are the Figma charges business?", tried="")
    assert "already tried" in str(refusal.value)


def test_a_question_with_nothing_in_it_is_refused():
    with pytest.raises(NotFound):
        run().ask("software", "   ", tried="checked the card statement")


def test_asking_records_the_question_and_the_work_behind_it():
    task = run()
    question = task.ask(
        "software", "are the two Figma charges both business?",
        tried="matched the card against last quarter; both appear once")
    assert task.need("software").state == ASKED
    assert question.about == "software"
    assert question.asked == "are the two Figma charges both business?"
    assert question.tried == (
        "matched the card against last quarter; both appear once")
    assert question.open


# --- 3. the one who was asked is the one who may answer ---------------------

def test_a_question_records_who_it_was_put_to():
    task = run(for_whom="krish")
    question = task.ask("software", "both business?", tried="checked the card")
    assert question.of == "krish"


def test_a_run_for_somebody_else_puts_its_questions_to_them():
    """Who the work is for is who its questions go to. Hard-wiring Krish here
    would mean a task run for anyone else quietly asked the wrong person."""
    task = run(for_whom="the accountant")
    question = task.ask("software", "both business?", tried="checked the card")
    assert question.of == "the accountant"
    task.need("software").answered("yes", by="the accountant")
    assert task.need("software").state == ANSWERED


def test_jarvis_cannot_answer_his_own_question():
    """Amendment 1, in the place it is easiest to break: he has a good guess,
    he is holding the pen, and afterwards the two look identical."""
    task = run()
    task.ask("software", "both business?", tried="checked the card")
    with pytest.raises(NotYours) as refusal:
        task.need("software").answered("yes, both", by=identity.AGENT_ID)
    assert "Only the one who was asked" in str(refusal.value)
    assert task.need("software").state == ASKED
    assert task.need("software").value is None


def test_somebody_the_question_was_never_put_to_cannot_answer_it():
    task = run(for_whom="krish")
    task.ask("software", "both business?", tried="checked the card")
    with pytest.raises(NotYours):
        task.need("software").answered("yes", by="the accountant")


def test_a_question_cannot_be_addressed_to_jarvis_himself():
    task = run()
    with pytest.raises(NotYours):
        task.need("software").ask("both business?", tried="checked the card",
                                  of=identity.AGENT_ID)


def test_a_question_cannot_be_addressed_to_jarvis_in_different_letters():
    """Case is not a different person, and neither is a stray space."""
    task = run()
    with pytest.raises(NotYours):
        task.need("software").ask("both business?", tried="checked",
                                  of=f"  {identity.AGENT_ID.upper()} ")


def test_a_task_cannot_be_for_jarvis():
    with pytest.raises(NotYours) as refusal:
        run(for_whom=identity.AGENT_ID)
    assert "for himself" in str(refusal.value)


def test_krishs_answer_fills_the_need_and_says_he_said_it():
    task = run(for_whom="krish")
    task.ask("software", "both business?", tried="checked the card")
    task.need("software").answered("yes, both", by="krish")
    filled = task.need("software")
    assert filled.state == ANSWERED
    assert filled.value == "yes, both"
    assert "krish" in filled.source
    assert not filled.question.open
    assert filled.question.answered_by == "krish"
    assert task.open_questions() == []


def test_an_answer_needs_a_name_on_it():
    task = run()
    task.ask("software", "both business?", tried="checked the card")
    with pytest.raises(NotFound):
        task.need("software").answered("yes", by="  ")


def test_answering_something_nobody_asked_is_refused():
    with pytest.raises(NotFound) as refusal:
        run().need("software").answered("yes", by="krish")
    assert "nothing was asked" in str(refusal.value)


def test_jarvis_cannot_leave_a_line_out_himself():
    task = run()
    with pytest.raises(NotYours) as refusal:
        task.need("acme_invoice").waive(
            by=identity.AGENT_ID, because="it never arrived")
    assert "the owner's decision" in str(refusal.value)
    assert task.need("acme_invoice").state == UNMET


def test_krish_may_leave_a_line_out_and_it_is_recorded_as_his():
    task = run()
    task.need("acme_invoice").waive(
        by="krish", because="it goes in Q4 this year")
    left_out = task.need("acme_invoice")
    assert left_out.state == WAIVED
    assert left_out.settled
    assert "krish" in left_out.source
    assert "Q4" in left_out.source


def test_waiving_a_line_needs_a_reason():
    with pytest.raises(NotFound) as refusal:
        run().need("acme_invoice").waive(by="krish", because="")
    assert "needs a name and a reason" in str(refusal.value)


# --- 4. parking a question does not stop the work ---------------------------

def test_the_rest_of_the_work_carries_on_while_a_question_waits():
    task = run()
    task.ask("software", "both business?", tried="checked the card")
    assert [one.name for one in task.workable()] == ["travel", "acme_invoice"]


def test_a_line_waiting_on_an_unanswered_one_is_not_attempted():
    task = run()
    task.depends("acme_invoice", on="software")
    task.ask("software", "both business?", tried="checked the card")
    workable = [one.name for one in task.workable()]
    assert "acme_invoice" not in workable
    assert workable == ["travel"]
    assert task.need("acme_invoice").value is None


def test_answering_the_blocker_releases_the_work_behind_it():
    task = run(for_whom="krish")
    task.depends("acme_invoice", on="software")
    task.ask("software", "both business?", tried="checked the card")
    assert "acme_invoice" not in [one.name for one in task.workable()]
    task.need("software").answered("yes, both", by="krish")
    assert "acme_invoice" in [one.name for one in task.workable()]


def test_a_line_already_filled_is_not_offered_again():
    task = run()
    task.need("travel").found("4,210.00", source="business account")
    assert "travel" not in [one.name for one in task.workable()]


def test_a_line_cannot_wait_on_itself():
    with pytest.raises(NotFound):
        run().depends("travel", on="travel")


def test_a_loop_of_waiting_is_refused_when_it_is_closed():
    """Nothing in a loop is ever workable, and a run that cannot move looks
    exactly like one that is working."""
    task = run()
    task.depends("software", on="travel")
    task.depends("acme_invoice", on="software")
    with pytest.raises(NotFound) as refusal:
        task.depends("travel", on="acme_invoice")
    assert "loop" in str(refusal.value)
    assert task.need("travel").blocked_by is None


def test_a_loop_of_two_is_refused():
    task = run()
    task.depends("software", on="travel")
    with pytest.raises(NotFound):
        task.depends("travel", on="software")


def test_waiting_on_a_line_that_is_not_in_the_model_is_refused():
    with pytest.raises(NotFound):
        run().depends("travel", on="bonus")


# --- 5. finishing is a claim, so it is checked ------------------------------

def fill(task):
    task.need("travel").found("4,210.00", source="business account")
    task.need("software").found("612.00", source="business card, 4 rows")
    task.need("acme_invoice").found("1,900.00", source="Acme invoice 3312")
    return task


def test_a_finished_statement_reports_every_line_and_where_it_came_from():
    done = fill(run()).finish()
    assert [one["name"] for one in done["settled"]] == [
        "travel", "software", "acme_invoice"]
    assert done["holes"] == []
    assert done["questions"] == []
    assert done["goal"] == "prepare the Q3 expense statement"
    assert done["model"] == LAST_YEAR
    assert done["finished_at"]


def test_finishing_with_a_silent_hole_is_refused():
    task = run()
    task.need("travel").found("4,210.00", source="business account")
    with pytest.raises(NotFound) as refusal:
        task.finish()
    message = str(refusal.value)
    assert "software" in message and "acme_invoice" in message
    assert "the Acme invoice, which arrives late" in message


def test_finishing_while_a_question_is_open_says_it_is_waiting():
    task = run()
    task.need("travel").found("4,210.00", source="business account")
    task.need("software").found("612.00", source="business card")
    task.ask("acme_invoice", "which Acme line is the invoice?",
             tried="both March rows say ACME; one is a refund")
    with pytest.raises(Stuck) as refusal:
        task.finish()
    assert "which Acme line is the invoice?" in str(refusal.value)


def test_a_statement_finished_on_krishs_answers_is_finished():
    task = run(for_whom="krish")
    task.need("travel").found("4,210.00", source="business account")
    task.need("software").found("612.00", source="business card")
    task.ask("acme_invoice", "which Acme line is the invoice?",
             tried="both March rows say ACME; one is a refund")
    task.need("acme_invoice").answered("the 1,900 one", by="krish")
    done = task.finish()
    assert done["holes"] == []
    assert [one["value"] for one in done["settled"]][-1] == "the 1,900 one"


def test_a_waived_line_lets_the_statement_finish():
    task = run()
    task.need("travel").found("4,210.00", source="business account")
    task.need("software").found("612.00", source="business card")
    task.need("acme_invoice").waive(by="krish", because="it goes in Q4")
    assert task.finish()["holes"] == []


def test_a_task_needs_a_goal():
    with pytest.raises(NotFound):
        Run("   ", statement())


# --- 6. what a person and a caller see --------------------------------------

def test_the_report_separates_what_is_done_from_what_is_asked_and_missing():
    task = run()
    task.need("travel").found("4,210.00", source="business account")
    task.ask("software", "both business?", tried="checked the card")
    task.depends("acme_invoice", on="software")
    report = task.report()
    assert report["settled"] == [
        {"name": "travel", "value": "4,210.00", "source": "business account"}]
    assert report["questions"] == [{
        "about": "software", "asked": "both business?",
        "tried": "checked the card", "of": "krish"}]
    assert report["holes"] == ["acme_invoice"]
    assert report["blocked"] == [{"name": "acme_invoice", "on": "software"}]


def test_a_blocked_line_stops_being_blocked_once_its_blocker_settles():
    task = run()
    task.depends("acme_invoice", on="software")
    task.need("software").found("612.00", source="business card")
    assert task.report()["blocked"] == []


def test_the_narration_shows_the_question_and_the_work_behind_it():
    task = run()
    task.need("travel").found(
        "4,210.00", source="business account, 12 rows tagged travel")
    task.ask("software", "are the two Figma charges both business?",
             tried="matched the card against last quarter")
    task.depends("acme_invoice", on="software")
    lines = task.narrate()
    assert lines[0] == f"prepare the Q3 expense statement (following {LAST_YEAR})"
    assert "[x] travel: 4,210.00" in lines[1]
    assert "12 rows tagged travel" in lines[1]
    assert "[?] software: are the two Figma charges both business?" in lines[2]
    assert "already tried: matched the card against last quarter" in lines[3]
    assert "[ ] acme_invoice: waiting on software" in lines[4]


def test_the_narration_says_not_yet_for_work_nobody_has_reached():
    assert "[ ] travel: not yet" in run().narrate()[1]


def test_describe_says_what_this_module_refuses():
    said = taskrun.describe()
    assert said["model_carries_values"] is False
    assert said["a_value_needs_a_source"] is True
    assert said["answers_its_own_questions"] is False
    assert said["finishes_with_a_hole"] is False
    assert said["blocked_work_parks_a_question"] is True
    assert said["dependency_loops"] == "refused"
    assert said["states"] == ["unmet", "found", "asked", "answered", "waived"]


def test_every_state_a_need_can_be_in_is_either_settled_or_not():
    assert set(taskrun.SETTLED) <= set(taskrun.STATES)
    assert set(taskrun.STATES) - set(taskrun.SETTLED) == {UNMET, ASKED}
