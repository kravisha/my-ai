"""Krish's side of the loop: seeing what Jarvis noticed, and answering it.

Until this, the sweep wrote guesses that nothing could ever settle, so every one
of them would have aged quietly into a wrong answer. A record that only
accumulates failures is worse than no record, because it looks like evidence.

The thing worth reading these tests for is the separation. This module writes
`guess_verdict`, which only `operator_console` may write - so it authenticates
as Krish and refuses to fall back to Jarvis. The consequence, stated here rather
than discovered later: a "yes" typed at Jarvis settles the *action* and not the
*guess*.

Probed by `tests/probes/console_probes.py`.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import model_calls
from dba import agent as agent_module, main as dba_main, registry, store
from dba import audit, store as dba_store
from gateway import (anticipation, console, dbaclient, identity, noticing,
                     persistence, taskrun, trustbook)
from gateway.anticipation import (FULL_STOP, NOT_NOW, OBSERVE, PERFECT, WANTED,
                                  WRONG, Guess)

TOKEN = "test-token-for-jarvis"
OPERATOR_TOKEN = "test-token-for-the-operator-console"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PATH_ENV, str(tmp_path / "dba.db"))
    monkeypatch.setenv(dba_main.token_env_var("JARVIS"), TOKEN)
    monkeypatch.setenv(dba_main.token_env_var("operator_console"), OPERATOR_TOKEN)
    monkeypatch.setenv(dbaclient.TOKEN_ENV, TOKEN)
    monkeypatch.setenv(identity.VERSION_ENV, "a" * 40)
    monkeypatch.setattr(model_calls, "log_dir", lambda: tmp_path)
    agent_module._AGENT = None
    registry.reset_sync()
    yield tmp_path
    agent_module._AGENT = None
    registry.reset_sync()


@pytest.fixture()
def service():
    with TestClient(dba_main.app) as made:
        yield made


def _transport(service, agent, token):
    def transport(method, path, payload):
        response = service.request(
            method, path, json=payload if method != "GET" else None,
            headers={"X-DBA-Agent": agent, "X-DBA-Token": token})
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {}

    return transport


@pytest.fixture()
def jarvis(service):
    return dbaclient.DBAClient(transport=_transport(service, "JARVIS", TOKEN),
                               requested_by="JARVIS", actor="jarvis")


@pytest.fixture()
def krish(service):
    return console.operator_client(
        transport=_transport(service, "operator_console", OPERATOR_TOKEN))


def a_guess(domain="commitments", what="send the Q3 statement"):
    return Guess(domain=domain, what=what,
                 because="you promised it by Friday",
                 made_at=datetime.now(timezone.utc))


# --- the console is Krish's, and says so -----------------------------------------

def test_a_console_with_no_operator_token_refuses_to_run(monkeypatch):
    """Rather than falling back to Jarvis's identity. A verdict written in the
    name of the agent being judged is not a verdict."""
    monkeypatch.delenv(console.TOKEN_ENV, raising=False)
    with pytest.raises(console.NoToken, match="not Krish's console"):
        console.operator_client()


def test_the_console_speaks_as_the_operator():
    assert console.describe()["speaks_as"] == "operator_console"
    assert console.describe()["writes"] == ["guess_verdict", "agent_state"]


def test_a_conversational_yes_does_not_settle_a_guess():
    """Stated in the data rather than left to be discovered. The conversation
    settles the action - `readback`'s mandate, in-process - and that is enough
    to get the work done. If it could also write verdicts, the Gateway would
    hold the operator's token and there would be no separation at all."""
    assert console.describe()["a_conversational_yes_settles_a_guess"] is False


# --- what Krish is shown ----------------------------------------------------------

def test_only_the_guesses_the_ladder_allowed_are_shown(jarvis, krish):
    """A guess recorded and not said is not missing - it is the bottom rung
    working."""
    trustbook.record(jarvis, a_guess(), to_say=True)
    trustbook.record(jarvis, a_guess(what="something quieter"), to_say=False)

    shown = console.mentions(krish)
    assert [row["what"] for row in shown] == ["send the Q3 statement"]


def test_a_mention_already_shown_is_not_shown_again(jarvis, krish):
    guess_id = trustbook.record(jarvis, a_guess(), to_say=True)
    assert console.mentions(krish)
    trustbook.mark_said(jarvis, guess_id)
    assert console.mentions(krish) == []


def test_a_mention_already_answered_is_not_shown_again(jarvis, krish):
    guess_id = trustbook.record(jarvis, a_guess(), to_say=True)
    console.answer(krish, guess_id, outcome=WANTED)
    assert console.mentions(krish) == []


def test_a_mention_carries_the_record_it_came_from(jarvis, krish):
    trustbook.record(jarvis, a_guess(), to_say=True)
    assert console.mentions(krish)[0]["because"] == "you promised it by Friday"


# --- answering --------------------------------------------------------------------

def test_krish_settles_a_guess_from_his_console(jarvis, krish):
    guess_id = trustbook.record(jarvis, a_guess(), to_say=True)
    verdict = console.answer(krish, guess_id, outcome=WANTED)

    made, problems = trustbook.load(jarvis)
    assert problems == []
    assert made[0].outcome == WANTED and made[0].settled_by == "krish"
    assert verdict["id"]


def test_jarvis_cannot_use_the_console_to_settle_his_own_guess(jarvis):
    """The refusal comes from the DBA, not from this module."""
    guess_id = trustbook.record(jarvis, a_guess(), to_say=True)
    with pytest.raises(dbaclient.Refused) as raised:
        console.answer(jarvis, guess_id, outcome=WANTED)
    assert "administer" in str(raised.value)


def test_the_three_answers_are_all_available(jarvis, krish):
    """Two would hide the interesting one."""
    for outcome in (WANTED, NOT_NOW, WRONG):
        guess_id = trustbook.record(jarvis, a_guess(what=outcome), to_say=True)
        console.answer(krish, guess_id, outcome=outcome)
    made, _ = trustbook.load(jarvis)
    assert {one.outcome for one in made} == {WANTED, NOT_NOW, WRONG}


def test_an_answer_nobody_declared_is_refused(jarvis, krish):
    guess_id = trustbook.record(jarvis, a_guess(), to_say=True)
    with pytest.raises(ValueError, match="outcome must be one of"):
        console.answer(krish, guess_id, outcome="maybe")


def test_the_refusal_explains_why_not_now_is_worth_having(jarvis, krish):
    guess_id = trustbook.record(jarvis, a_guess(), to_say=True)
    with pytest.raises(ValueError) as raised:
        console.answer(krish, guess_id, outcome="maybe")
    assert "stop noticing" in str(raised.value)


def test_krish_rates_the_work_afterwards(jarvis, krish):
    guess_id = trustbook.record(jarvis, a_guess(), to_say=True)
    verdict = console.answer(krish, guess_id, outcome=WANTED)
    console.rate(krish, verdict["id"], quality=PERFECT)

    made, _ = trustbook.load(jarvis)
    assert made[0].quality == PERFECT and made[0].rated_by == "krish"


# --- silence is an answer, and it is not "wrong" ------------------------------------

def test_a_mention_krish_never_answered_lapses_to_not_now(jarvis, krish):
    """He may well have needed the thing and not wanted it raised then.
    Recording silence as a bad guess teaches Jarvis to stop noticing, when the
    lesson available is to wait."""
    trustbook.record(jarvis, a_guess(), to_say=True)
    later = datetime.now(timezone.utc) + timedelta(days=noticing.QUIET_DAYS + 1)

    lapsed = console.lapse(krish, now=later)
    assert len(lapsed) == 1

    made, _ = trustbook.load(jarvis)
    assert made[0].outcome == NOT_NOW
    assert made[0].settled_by == "no answer"


def test_a_mention_inside_the_window_is_left_alone(jarvis, krish):
    trustbook.record(jarvis, a_guess(), to_say=True)
    assert console.lapse(krish, now=datetime.now(timezone.utc)) == []
    assert console.mentions(krish)


def test_lapsing_is_the_operators_write_too(jarvis):
    """"No answer" is still a judgement, and Jarvis does not write the records
    that judge him."""
    trustbook.record(jarvis, a_guess(), to_say=True)
    later = datetime.now(timezone.utc) + timedelta(days=noticing.QUIET_DAYS + 1)
    with pytest.raises(dbaclient.Refused):
        console.lapse(jarvis, now=later)


def test_a_guess_that_was_never_meant_to_be_said_does_not_lapse(jarvis, krish):
    """It was recorded because the ladder says notice everything. Lapsing it
    would punish Jarvis for a silence that was his own."""
    trustbook.record(jarvis, a_guess(), to_say=False)
    later = datetime.now(timezone.utc) + timedelta(days=noticing.QUIET_DAYS + 1)
    assert console.lapse(krish, now=later) == []


# --- the loop closes ----------------------------------------------------------------

def test_a_domain_climbs_once_krish_starts_answering(jarvis, krish):
    """The whole point. Before this the sweep wrote guesses nothing could
    settle, so the record could only ever get worse."""
    assert console.standing(krish, "commitments").rung == OBSERVE

    for index in range(12):
        guess_id = trustbook.record(jarvis, a_guess(what=f"thing {index}"),
                                    to_say=True)
        verdict = console.answer(krish, guess_id, outcome=WANTED)
        console.rate(krish, verdict["id"], quality=PERFECT)

    assert console.standing(krish, "commitments").rung == FULL_STOP


# --- the questions a task parked ---------------------------------------------------

def a_run(goal="prepare the Q3 expense statement"):
    """A run with one line found, one asked about, one untouched."""
    made = taskrun.Run(goal, taskrun.Model(
        name="last year's expense statement", fields=(
            taskrun.Field("travel", "flights and hotels charged to the business"),
            taskrun.Field("software", "subscriptions charged to the business card"),
            taskrun.Field("mileage", "car mileage at the standard rate"))))
    made.need("travel").found("1,240.00", source="business account, Jul-Sep")
    made.ask("software", "is the Figma seat business or personal?",
             tried="both cards show it")
    return made


def test_the_question_a_run_parked_reaches_krish(jarvis, krish):
    """Until this nothing put the question in front of him, so a run that
    asked could only stall. The run is named on each so that the answer can
    find its way back."""
    made = a_run()
    taskrun.save(jarvis, made)

    waiting = console.questions(krish)

    assert [(one["run"], one["about"]) for one in waiting] == \
        [("run:prepare-the-q3-expense-statement", "software")]
    assert waiting[0]["asked"] == "is the Figma seat business or personal?"
    assert waiting[0]["tried"] == "both cards show it"
    assert waiting[0]["of"] == "krish"
    assert waiting[0]["goal"] == "prepare the Q3 expense statement"


def test_questions_from_every_run_are_listed_oldest_first(jarvis, krish):
    later = a_run("prepare the Q2 VAT return")
    later.need("software").question.at += timedelta(minutes=5)
    taskrun.save(jarvis, later)
    taskrun.save(jarvis, a_run())
    assert [one["run"] for one in console.questions(krish)] == [
        "run:prepare-the-q3-expense-statement",
        "run:prepare-the-q2-vat-return"]


def test_nothing_is_waiting_when_no_run_asked_anything(jarvis, krish):
    made = a_run()
    made.need("software").answered("business", by="krish")
    taskrun.save(jarvis, made)
    assert console.questions(krish) == []


def test_krish_answers_a_task_question_from_his_console(jarvis, krish):
    taskrun.save(jarvis, a_run())

    console.reply(krish, "run:prepare-the-q3-expense-statement", "software",
                  "business")

    after = taskrun.load(jarvis, "run:prepare-the-q3-expense-statement")
    software = after.need("software")
    assert software.state == taskrun.ANSWERED
    assert software.value == "business"
    assert software.source == "krish said so"
    assert software.question.answered_by == "krish"
    assert console.questions(krish) == []
    # The rest of the run came back untouched.
    assert after.need("travel").value == "1,240.00"
    assert after.need("mileage").state == taskrun.UNMET


def test_the_answer_is_written_by_the_operator_not_by_jarvis(jarvis, krish):
    """The provenance the docstring claims: the revision carrying Krish's
    answer was created by the operator console, so the DBA's own audit says he
    wrote it. A field saying `answered_by: krish` inside a row Jarvis wrote
    would be Jarvis's word for it."""
    taskrun.save(jarvis, a_run())
    console.reply(krish, "run:prepare-the-q3-expense-statement", "software",
                  "business")
    rows = persistence.current(jarvis, kind=persistence.TASK,
                               name="run:prepare-the-q3-expense-statement")
    assert len(rows) == 1 and rows[0]["revision"] == 2
    conn = dba_store.connect()
    try:
        trail = audit.for_entity(conn, rows[0]["id"])
    finally:
        conn.close()
    created = [one for one in trail if one["action"] == "create"]
    assert [one["requesting_agent"] for one in created] == ["operator_console"]


def test_jarvis_cannot_use_the_console_to_answer_his_own_question(jarvis, krish):
    """The refusal is `Need.answered`'s, reached through the console rather
    than around it. And nothing is saved on the way to refusing."""
    taskrun.save(jarvis, a_run())
    with pytest.raises(taskrun.NotYours):
        console.reply(krish, "run:prepare-the-q3-expense-statement", "software",
                      "business", by=identity.AGENT_ID)
    with pytest.raises(taskrun.NotYours):
        console.reply(krish, "run:prepare-the-q3-expense-statement", "software",
                      "business", by="somebody else")
    after = taskrun.load(jarvis, "run:prepare-the-q3-expense-statement")
    assert after.need("software").state == taskrun.ASKED
    assert len(persistence.history(
        jarvis, persistence.TASK, "run:prepare-the-q3-expense-statement")) == 1


def test_a_reply_about_a_line_nobody_asked_about_is_refused(jarvis, krish):
    taskrun.save(jarvis, a_run())
    with pytest.raises(taskrun.NotFound, match="nothing was asked"):
        console.reply(krish, "run:prepare-the-q3-expense-statement", "mileage",
                      "none")
    with pytest.raises(taskrun.NotFound, match="not part of"):
        console.reply(krish, "run:prepare-the-q3-expense-statement", "rent",
                      "none")


def test_a_reply_to_a_run_that_was_never_saved_is_refused(jarvis, krish):
    with pytest.raises(taskrun.NotFound, match="not a saved run"):
        console.reply(krish, "run:never", "software", "business")


def test_krish_leaves_a_line_out_from_his_console(jarvis, krish):
    taskrun.save(jarvis, a_run())
    console.leave_out(krish, "run:prepare-the-q3-expense-statement", "mileage",
                      because="none this quarter")
    after = taskrun.load(jarvis, "run:prepare-the-q3-expense-statement")
    assert after.need("mileage").state == taskrun.WAIVED
    assert after.need("mileage").source == "krish left it out: none this quarter"


def test_jarvis_cannot_leave_a_line_out_through_the_console(jarvis, krish):
    taskrun.save(jarvis, a_run())
    with pytest.raises(taskrun.NotYours):
        console.leave_out(krish, "run:prepare-the-q3-expense-statement",
                          "mileage", because="probably none", by=identity.AGENT_ID)
    after = taskrun.load(jarvis, "run:prepare-the-q3-expense-statement")
    assert after.need("mileage").state == taskrun.UNMET


def test_an_answered_run_can_be_finished_by_jarvis(jarvis, krish):
    """The loop, closed: Jarvis asks, Krish answers here, Jarvis carries on."""
    taskrun.save(jarvis, a_run())
    console.reply(krish, "run:prepare-the-q3-expense-statement", "software",
                  "business")
    console.leave_out(krish, "run:prepare-the-q3-expense-statement", "mileage",
                      because="none this quarter")
    done = taskrun.load(jarvis, "run:prepare-the-q3-expense-statement").finish()
    assert done["holes"] == [] and done["questions"] == []


def test_the_terminal_lists_and_answers_questions(jarvis, krish, monkeypatch, capsys):
    monkeypatch.setattr(console, "operator_client", lambda: krish)
    taskrun.save(jarvis, a_run())

    assert console.main(["questions"]) == 0
    shown = capsys.readouterr().out
    assert "run:prepare-the-q3-expense-statement  software: is the Figma seat" in shown
    assert "already tried: both cards show it" in shown

    assert console.main(["reply", "run:prepare-the-q3-expense-statement",
                         "software", "--answer", "business"]) == 0
    assert "0 question(s) still open" in capsys.readouterr().out
    assert console.main(["questions"]) == 0
    assert "Nothing waiting." in capsys.readouterr().out

    assert console.main(["leave-out", "run:prepare-the-q3-expense-statement",
                         "mileage", "--because", "none this quarter"]) == 0
    assert taskrun.load(jarvis, "run:prepare-the-q3-expense-statement") \
        .need("mileage").state == taskrun.WAIVED
