"""A task run survives a restart, and its questions reach Krish.

TQ-119's two missing halves. `gateway/taskrun.py` decided everything and kept
nothing: a morning's work on the expense statement died with the process, and
the questions it parked were put to nobody, because nothing showed them to him.

The claim worth reading these tests for is that a stored run is **replayed**,
not trusted. The store can be edited without going through `taskrun`, so a run
restored by assignment would be the easiest road around every refusal in it: a
figure with its source deleted, an answer in a name the question was never put
to, a waiver in Jarvis's. Each of those is written into the store directly here
and must come back as `Corrupt`, never as a run.

Probed by `tests/probes/taskrun_store_probes.py`.
"""

import copy

import pytest
from fastapi.testclient import TestClient

from app import model_calls
from dba import agent as agent_module, main as dba_main, registry, store
from gateway import console, dbaclient, identity, persistence, taskrun
from gateway.taskrun import (ANSWERED, ASKED, FOUND, UNMET, WAIVED, Corrupt,
                             Field, Model, NotFound, NotYours, Run)

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


def statement():
    return Model(name="last year's expense statement", fields=(
        Field("travel", "flights and hotels charged to the business"),
        Field("software", "subscriptions charged to the business card"),
        Field("acme_invoice", "the Acme invoice, which arrives late"),
        Field("donations", "gifts made in the business's name")))


def a_morning():
    """One of every state, and a dependency: what a real run looks like at
    eleven o'clock."""
    task = Run("prepare the Q3 expense statement", statement())
    task.depends("acme_invoice", on="software")
    task.need("travel").found("4,210.00", source="business account, 12 rows")
    task.ask("software", "are the two Figma charges both business?",
             tried="matched the card against last quarter")
    task.need("donations").waive(by="krish", because="none this year")
    return task


def _plant(client, name, stored):
    """Write straight into the store, as anything that is not `taskrun` could."""
    persistence.put(client, persistence.TASK, taskrun.key(name), stored)


# --- the stored form --------------------------------------------------------------

def test_the_storage_names_are_what_they_are():
    """Literals, not the constants: a changed prefix orphans every stored run,
    and a test written as `taskrun.PREFIX + name` would follow it silently."""
    assert taskrun.key("q3") == "taskrun/q3"
    assert taskrun.to_dict(a_morning())["format"] == 1


def test_a_stored_run_needs_a_name():
    with pytest.raises(NotFound, match="needs a name"):
        taskrun.key("  ")


def test_a_run_comes_back_as_it_was():
    before = a_morning()
    after = taskrun.restore(taskrun.to_dict(before))

    assert after.goal == "prepare the Q3 expense statement"
    assert after.for_whom == "krish"
    assert after.started == before.started
    assert [one.state for one in after.needs] == [FOUND, ASKED, UNMET, WAIVED]
    assert after.need("travel").value == "4,210.00"
    assert after.need("travel").source == "business account, 12 rows"
    assert after.need("acme_invoice").blocked_by == "software"
    assert after.need("donations").waived_by == "krish"
    assert after.need("donations").waived_because == "none this year"
    asked = after.need("software").question
    assert asked.asked == "are the two Figma charges both business?"
    assert asked.tried == "matched the card against last quarter"
    assert asked.of == "krish"
    assert asked.at == before.need("software").question.at
    assert taskrun.to_dict(after) == taskrun.to_dict(before)


def test_a_restored_run_knows_its_next_action():
    """Requirement 1 in its own words: a task resumed after a restart knows what
    to do next - and what it must not do yet."""
    after = taskrun.restore(taskrun.to_dict(a_morning()))
    assert [one.name for one in after.workable()] == []
    assert [one.about for one in after.open_questions()] == ["software"]
    assert after.report()["blocked"] == [{"name": "acme_invoice",
                                          "on": "software"}]


def test_an_answered_question_comes_back_answered_by_whoever_answered_it():
    before = a_morning()
    before.need("software").answered("both are", by="Krish ")
    after = taskrun.restore(taskrun.to_dict(before))
    assert after.need("software").state == ANSWERED
    assert after.need("software").question.answered_by == "Krish"
    assert after.need("software").value == "both are"
    assert [one.name for one in after.workable()] == ["acme_invoice"]


# --- the store is not trusted -----------------------------------------------------

def _tampered(edit):
    stored = taskrun.to_dict(a_morning())
    edit(stored)
    return stored


def _line(stored, name):
    return next(one for one in stored["needs"] if one["name"] == name)


def test_a_figure_whose_source_was_removed_does_not_come_back():
    def edit(stored):
        _line(stored, "travel")["source"] = ""
    with pytest.raises(Corrupt, match="needs a source"):
        taskrun.restore(_tampered(edit))


def test_an_unmet_line_carrying_a_value_does_not_come_back():
    """Last year's number, parked on an unmet line, waiting for somebody to flip
    the state."""
    def edit(stored):
        _line(stored, "acme_invoice")["value"] = "9,000.00"
    with pytest.raises(Corrupt, match="unmet, and yet"):
        taskrun.restore(_tampered(edit))


def test_an_unmet_line_carrying_a_question_does_not_come_back():
    def edit(stored):
        _line(stored, "acme_invoice")["question"] = copy.deepcopy(
            _line(stored, "software")["question"])
    with pytest.raises(Corrupt, match="unmet, and yet"):
        taskrun.restore(_tampered(edit))


def test_an_answer_in_jarvis_s_name_does_not_come_back():
    def edit(stored):
        line = _line(stored, "software")
        line["state"] = ANSWERED
        line["question"]["answer"] = "both are"
        line["question"]["answered_by"] = identity.AGENT_ID
    with pytest.raises(Corrupt, match="Only the one who was asked"):
        taskrun.restore(_tampered(edit))


def test_a_question_readdressed_to_jarvis_does_not_come_back():
    """Changing `of` is the other way to make his own answer legitimate."""
    def edit(stored):
        _line(stored, "software")["question"]["of"] = identity.AGENT_ID
    with pytest.raises(Corrupt, match="cannot be the one asked"):
        taskrun.restore(_tampered(edit))


def test_an_open_question_carrying_an_answer_does_not_come_back():
    def edit(stored):
        _line(stored, "software")["question"]["answer"] = "both are"
    with pytest.raises(Corrupt, match="asked, and yet carries an answer"):
        taskrun.restore(_tampered(edit))


def test_an_asked_line_with_no_question_does_not_come_back():
    def edit(stored):
        _line(stored, "software")["question"] = None
    with pytest.raises(Corrupt, match="with no question"):
        taskrun.restore(_tampered(edit))


def test_a_waiver_in_jarvis_s_name_does_not_come_back():
    def edit(stored):
        _line(stored, "donations")["waived_by"] = identity.AGENT_ID
    with pytest.raises(Corrupt, match="cannot waive"):
        taskrun.restore(_tampered(edit))


def test_a_waiver_with_no_reason_does_not_come_back():
    def edit(stored):
        _line(stored, "donations")["waived_because"] = ""
    with pytest.raises(Corrupt, match="needs a name and a reason"):
        taskrun.restore(_tampered(edit))


def test_a_line_the_model_does_not_have_does_not_come_back():
    def edit(stored):
        stored["needs"].append({**_line(stored, "travel"), "name": "bonus"})
    with pytest.raises(Corrupt, match="not the model's lines"):
        taskrun.restore(_tampered(edit))


def test_a_line_dropped_from_the_run_does_not_come_back():
    def edit(stored):
        stored["needs"] = [one for one in stored["needs"]
                           if one["name"] != "acme_invoice"]
    with pytest.raises(Corrupt, match="not the model's lines"):
        taskrun.restore(_tampered(edit))


def test_a_dependency_loop_planted_in_the_store_does_not_come_back():
    def edit(stored):
        _line(stored, "software")["blocked_by"] = "acme_invoice"
    with pytest.raises(Corrupt, match="closes a loop"):
        taskrun.restore(_tampered(edit))


def test_an_unknown_state_does_not_come_back():
    def edit(stored):
        _line(stored, "travel")["state"] = "estimated"
    with pytest.raises(Corrupt, match="unknown state 'estimated'"):
        taskrun.restore(_tampered(edit))


def test_a_run_for_jarvis_does_not_come_back():
    def edit(stored):
        stored["for_whom"] = identity.AGENT_ID
    with pytest.raises(Corrupt, match="cannot be for"):
        taskrun.restore(_tampered(edit))


@pytest.mark.parametrize("stored", [None, "a run", {}, {"format": 2}])
def test_something_that_is_not_a_stored_run_does_not_come_back(stored):
    with pytest.raises(Corrupt, match="not a stored run in format 1"):
        taskrun.restore(stored)


def test_a_stored_run_missing_a_part_does_not_come_back():
    stored = taskrun.to_dict(a_morning())
    del stored["needs"]
    with pytest.raises(Corrupt, match="does not replay"):
        taskrun.restore(stored)


# --- through the store ------------------------------------------------------------

def test_a_run_saved_is_a_run_loaded(jarvis):
    before = a_morning()
    taskrun.save(jarvis, "q3", before)
    assert taskrun.to_dict(taskrun.load(jarvis, "q3")) == \
        taskrun.to_dict(before)


def test_the_newest_save_is_the_one_loaded(jarvis):
    task = a_morning()
    taskrun.save(jarvis, "q3", task)
    task.need("acme_invoice")  # still blocked
    task.need("software").answered("both are", by="krish")
    taskrun.save(jarvis, "q3", task)
    assert taskrun.load(jarvis, "q3").need("software").state == ANSWERED


def test_a_run_never_saved_loads_as_nothing(jarvis):
    assert taskrun.load(jarvis, "q4") is None


def test_loading_a_tampered_run_raises_rather_than_returning_it(jarvis):
    _plant(jarvis, "q3", _tampered(
        lambda stored: _line(stored, "travel").update(source="")))
    with pytest.raises(Corrupt):
        taskrun.load(jarvis, "q3")


def test_every_stored_run_is_listed_and_a_corrupt_one_is_named(jarvis):
    """Named, not dropped. A run that silently fell out of the list would take
    its open questions with it, and an absent question is not an answered
    one."""
    taskrun.save(jarvis, "q3", a_morning())
    _plant(jarvis, "q2", _tampered(
        lambda stored: _line(stored, "travel").update(source="")))
    persistence.put(jarvis, persistence.TASK, "september",
                    {"doing": "reconcile"})

    runs, corrupt = taskrun.stored_runs(jarvis)
    assert sorted(runs) == ["q3"]
    assert sorted(corrupt) == ["q2"]
    assert "needs a source" in corrupt["q2"]


# --- Krish's side -----------------------------------------------------------------

def test_krish_sees_every_open_question_across_his_runs(jarvis, krish):
    taskrun.save(jarvis, "q3", a_morning())
    other = Run("prepare the Q2 expense statement", statement())
    other.ask("travel", "was the Denver trip business?",
              tried="found a hotel with no matching invoice")
    taskrun.save(jarvis, "q2", other)

    waiting, corrupt = console.questions(krish)
    assert corrupt == {}
    assert [(one["run"], one["line"]) for one in waiting] == [
        ("q2", "travel"), ("q3", "software")]
    assert waiting[1] == {
        "run": "q3", "goal": "prepare the Q3 expense statement",
        "line": "software", "asked": "are the two Figma charges both business?",
        "tried": "matched the card against last quarter", "of": "krish"}


def test_an_answered_question_is_not_shown_again(jarvis, krish):
    taskrun.save(jarvis, "q3", a_morning())
    console.reply(krish, "q3", "software", "both are")
    assert console.questions(krish) == ([], {})


def test_krish_s_answer_is_saved_and_releases_the_work_behind_it(jarvis, krish):
    """Saved before `reply` returns: an answer that lived only in the console's
    process would be gone the moment he closed it."""
    taskrun.save(jarvis, "q3", a_morning())
    console.reply(krish, "q3", "software", "both are")

    resumed = taskrun.load(jarvis, "q3")
    assert resumed.need("software").state == ANSWERED
    assert resumed.need("software").source == "krish said so"
    assert [one.name for one in resumed.workable()] == ["acme_invoice"]


def test_the_console_cannot_answer_in_somebody_else_s_name(jarvis, krish):
    taskrun.save(jarvis, "q3", a_morning())
    with pytest.raises(NotYours):
        console.reply(krish, "q3", "software", "both are", by="bookkeeper")
    with pytest.raises(NotYours):
        console.reply(krish, "q3", "software", "both are",
                      by=identity.AGENT_ID)
    assert taskrun.load(jarvis, "q3").need("software").state == ASKED


def test_answering_a_run_that_does_not_exist_is_refused(krish):
    with pytest.raises(NotFound, match="no stored run called 'q9'"):
        console.reply(krish, "q9", "software", "both are")


def test_krish_can_leave_a_line_out_and_it_stays_out(jarvis, krish):
    taskrun.save(jarvis, "q3", a_morning())
    console.leave_out(krish, "q3", "acme_invoice",
                      because="Acme invoices go in Q4")
    resumed = taskrun.load(jarvis, "q3")
    assert resumed.need("acme_invoice").state == WAIVED
    assert resumed.need("acme_invoice").waived_by == "krish"


def test_the_console_cannot_leave_a_line_out_in_jarvis_s_name(jarvis, krish):
    taskrun.save(jarvis, "q3", a_morning())
    with pytest.raises(NotYours):
        console.leave_out(krish, "q3", "acme_invoice", because="later",
                          by=identity.AGENT_ID)
    assert taskrun.load(jarvis, "q3").need("acme_invoice").state == UNMET


def test_the_console_shows_a_run_it_cannot_load(jarvis, krish):
    _plant(jarvis, "q3", _tampered(
        lambda stored: _line(stored, "travel").update(source="")))
    waiting, corrupt = console.questions(krish)
    assert waiting == []
    assert list(corrupt) == ["q3"]


# --- from a terminal --------------------------------------------------------------

@pytest.fixture()
def terminal(krish, monkeypatch):
    monkeypatch.setattr(console, "operator_client", lambda: krish)


def test_the_questions_command_prints_them(jarvis, terminal, capsys):
    taskrun.save(jarvis, "q3", a_morning())
    assert console.main(["questions"]) == 0
    printed = capsys.readouterr().out.splitlines()
    assert printed == [
        "q3 / software: are the two Figma charges both business?",
        "    already tried: matched the card against last quarter"]


def test_the_questions_command_says_when_nothing_is_waiting(terminal, capsys):
    assert console.main(["questions"]) == 0
    assert capsys.readouterr().out.strip() == "Nothing waiting."


def test_the_questions_command_fails_loudly_on_a_run_it_cannot_load(
        jarvis, terminal, capsys):
    """Non-zero, and first. A console that exits 0 while a run is unreadable
    reports a clean slate it cannot see."""
    taskrun.save(jarvis, "q2", a_morning())
    _plant(jarvis, "q3", _tampered(
        lambda stored: _line(stored, "travel").update(source="")))
    assert console.main(["questions"]) == 1
    printed = capsys.readouterr().out.splitlines()
    assert printed[0].startswith("CANNOT LOAD q3: ")
    assert "Nothing waiting." not in printed


def test_the_reply_command_records_the_answer(jarvis, terminal, capsys):
    taskrun.save(jarvis, "q3", a_morning())
    assert console.main(["reply", "q3", "software", "both are"]) == 0
    assert capsys.readouterr().out.strip() == "recorded"
    assert taskrun.load(jarvis, "q3").need("software").value == "both are"


def test_the_reply_command_refuses_somebody_else_and_says_why(
        jarvis, terminal, capsys):
    taskrun.save(jarvis, "q3", a_morning())
    assert console.main(["reply", "q3", "software", "both are",
                         "--by", identity.AGENT_ID]) == 2
    assert "Only the one who was asked" in capsys.readouterr().err
    assert taskrun.load(jarvis, "q3").need("software").state == ASKED


def test_the_leave_out_command_records_the_waiver(jarvis, terminal, capsys):
    taskrun.save(jarvis, "q3", a_morning())
    assert console.main(["leave-out", "q3", "acme_invoice",
                         "--because", "goes in Q4"]) == 0
    assert taskrun.load(jarvis, "q3").need("acme_invoice").waived_because == \
        "goes in Q4"


def test_describe_says_a_run_survives_and_how():
    said = taskrun.describe()
    assert said["survives_a_restart"] is True
    assert said["restored_by"] == "replay through the same refusals"
