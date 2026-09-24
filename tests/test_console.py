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
from gateway import (anticipation, console, dbaclient, identity, noticing,
                     trustbook)
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
    assert console.describe()["writes"] == [
        "guess_verdict", "answers to parked task questions"]


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
