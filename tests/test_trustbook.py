"""Where the trust ladder's record is kept, and who may write which half.

The record was living in a Python list, so every restart wiped what Jarvis had
earned. That is the same failure as a ladder nothing can climb, wearing a
different hat - and it hid a second one: the grades were somewhere he could have
written them.

So the guess is his and the verdict is not, and the refusal that matters is the
DBA's, in another service, over HTTP.
"""

import pytest
from fastapi.testclient import TestClient

from app import model_calls
from dba import agent as agent_module, main as dba_main, registry, store
from gateway import anticipation, dbaclient, identity, trustbook
from gateway.anticipation import (ACT_AND_REPORT, FAILED, OBSERVE, PERFECT,
                                  WANTED, WRONG, Guess)

TOKEN = "test-token-for-jarvis"
OPERATOR_TOKEN = "test-token-for-the-operator-console"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PATH_ENV, str(tmp_path / "dba.db"))
    monkeypatch.setenv(dba_main.token_env_var("JARVIS"), TOKEN)
    monkeypatch.setenv(dba_main.token_env_var("operator_console"), OPERATOR_TOKEN)
    monkeypatch.setenv(dbaclient.TOKEN_ENV, TOKEN)
    monkeypatch.setenv(identity.VERSION_ENV, "f" * 40)
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


def _as(service, agent, token):
    def transport(method, path, payload):
        response = service.request(
            method, path, json=payload if method != "GET" else None,
            headers={"X-DBA-Agent": agent, "X-DBA-Token": token})
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {}

    return dbaclient.DBAClient(transport=transport, requested_by=agent,
                               actor=agent.lower())


@pytest.fixture()
def client(service):
    return _as(service, "JARVIS", TOKEN)


@pytest.fixture()
def operator(service):
    return _as(service, "operator_console", OPERATOR_TOKEN)


def a_guess(domain="expenses"):
    return Guess(domain=domain, what="the quarterly statement",
                 because="the quarter closed and he asked on the 3rd last year")


# --- the guess is his ------------------------------------------------------------

def test_jarvis_records_his_own_guess(client):
    """An assistant who cannot record a prediction cannot be judged on one."""
    guess_id = trustbook.record(client, a_guess())
    assert guess_id
    stored = client.get(guess_id)
    assert stored["domain"] == "expenses"
    assert stored["because"].startswith("the quarter closed")
    assert stored["status"] == trustbook.OPEN


def test_a_recorded_guess_comes_back_unsettled(client):
    trustbook.record(client, a_guess())
    made, problems = trustbook.load(client)
    assert problems == []
    assert len(made) == 1 and made[0].settled is False


# --- the verdict is not ----------------------------------------------------------

def test_jarvis_cannot_write_his_own_verdict(client):
    """The record that decides how much latitude he gets. A mark an agent can
    award itself is not a mark - and the refusal comes from the DBA rather than
    from code in the process being judged."""
    guess_id = trustbook.record(client, a_guess())
    with pytest.raises(dbaclient.Refused) as raised:
        trustbook.settle(client, guess_id, outcome=WANTED, settled_by="krish")
    assert "administer" in str(raised.value)
    assert trustbook.load(client)[0][0].settled is False


def test_jarvis_cannot_rate_his_own_work_either(client, operator):
    guess_id = trustbook.record(client, a_guess())
    verdict = trustbook.settle(operator, guess_id, outcome=WANTED,
                               settled_by="krish")
    with pytest.raises(dbaclient.Refused):
        trustbook.rate(client, verdict["id"], quality=PERFECT, rated_by="krish")


def test_krish_settles_and_rates_through_the_operator(client, operator):
    guess_id = trustbook.record(client, a_guess())
    verdict = trustbook.settle(operator, guess_id, outcome=WANTED,
                               settled_by="krish")
    trustbook.rate(operator, verdict["id"], quality=PERFECT, rated_by="krish")

    made, problems = trustbook.load(client)
    assert problems == []
    assert made[0].outcome == WANTED and made[0].settled_by == "krish"
    assert made[0].quality == PERFECT and made[0].rated_by == "krish"


def test_a_verdict_must_say_who_gave_it(operator):
    with pytest.raises(ValueError, match="who gave it"):
        trustbook.settle(operator, "guess-1", outcome=WANTED, settled_by="  ")


def test_a_rating_must_say_who_gave_it(client, operator):
    guess_id = trustbook.record(client, a_guess())
    verdict = trustbook.settle(operator, guess_id, outcome=WANTED,
                               settled_by="krish")
    with pytest.raises(ValueError, match="who gave it"):
        trustbook.rate(operator, verdict["id"], quality=PERFECT, rated_by="  ")
    assert trustbook.load(client)[0][0].quality is None


def test_outcomes_and_qualities_stay_closed(client, operator):
    guess_id = trustbook.record(client, a_guess())
    with pytest.raises(ValueError, match="outcome must be one of"):
        trustbook.settle(operator, guess_id, outcome="probably",
                         settled_by="krish")
    verdict = trustbook.settle(operator, guess_id, outcome=WANTED,
                               settled_by="krish")
    with pytest.raises(ValueError, match="quality must be one of"):
        trustbook.rate(operator, verdict["id"], quality="fine", rated_by="krish")


# --- it survives a restart -------------------------------------------------------

def test_the_record_outlives_the_process(client, operator):
    """The whole point. Before this it lived in a Python list."""
    for _ in range(12):
        guess_id = trustbook.record(client, a_guess())
        verdict = trustbook.settle(operator, guess_id, outcome=WANTED,
                                   settled_by="krish")
        trustbook.rate(operator, verdict["id"], quality=PERFECT,
                       rated_by="krish")

    earned = trustbook.standing(client, "expenses")
    assert earned.rung == anticipation.FULL_STOP
    assert earned.settled == 12 and earned.perfect_run == 12


def test_a_domain_nobody_has_guessed_in_starts_at_the_bottom(client):
    assert trustbook.standing(client, "email").rung == OBSERVE


def test_domains_are_kept_apart_in_the_store(client, operator):
    for _ in range(12):
        guess_id = trustbook.record(client, a_guess("expenses"))
        verdict = trustbook.settle(operator, guess_id, outcome=WANTED,
                                   settled_by="krish")
        trustbook.rate(operator, verdict["id"], quality=PERFECT,
                       rated_by="krish")
    for _ in range(5):
        guess_id = trustbook.record(client, a_guess("email"))
        trustbook.settle(operator, guess_id, outcome=WRONG, settled_by="krish")

    assert trustbook.standing(client, "expenses").rung == anticipation.FULL_STOP
    assert trustbook.standing(client, "email").rung == OBSERVE


def test_one_botched_execution_still_drops_the_rung_after_a_reload(
        client, operator):
    for _ in range(12):
        guess_id = trustbook.record(client, a_guess())
        verdict = trustbook.settle(operator, guess_id, outcome=WANTED,
                                   settled_by="krish")
        trustbook.rate(operator, verdict["id"], quality=PERFECT,
                       rated_by="krish")
    assert trustbook.standing(client, "expenses").rung == anticipation.FULL_STOP

    guess_id = trustbook.record(client, a_guess())
    verdict = trustbook.settle(operator, guess_id, outcome=WANTED,
                               settled_by="krish")
    trustbook.rate(operator, verdict["id"], quality=FAILED, rated_by="krish")

    assert trustbook.standing(client, "expenses").rung == anticipation.MENTION


# --- loading is hostile ----------------------------------------------------------

def test_a_verdict_naming_a_guess_that_is_not_there_is_reported(client, operator):
    """The interesting failure is not a missing row - it is an extra one. Jarvis
    cannot write a verdict, so one pointing at nothing wants explaining."""
    trustbook.settle(operator, "guess-deadbeefdeadbeef", outcome=WANTED,
                     settled_by="krish")
    made, problems = trustbook.load(client)
    assert made == []
    assert any("is not in the record" in problem for problem in problems)


def test_two_verdicts_on_one_guess_are_reported(client, operator):
    """A guess is settled once; a second verdict would let a bad week be
    revised."""
    guess_id = trustbook.record(client, a_guess())
    trustbook.settle(operator, guess_id, outcome=WRONG, settled_by="krish")
    trustbook.settle(operator, guess_id, outcome=WANTED, settled_by="krish")

    made, problems = trustbook.load(client)
    assert any("more than one verdict" in problem for problem in problems)
    # And the first one stands: the record is not quietly improved.
    assert made[0].outcome == WRONG


@pytest.mark.parametrize("stamp", ["not a timestamp", "", None, 17, []])
def test_an_unparseable_timestamp_returns_none_rather_than_raising(stamp):
    """Unreachable through the client - the DBA validates timestamps and refuses
    the write - so it is tested where it can be reached. It is defence against a
    hand-edited database, and a loader that raised on one bad row would lose
    every good one behind it."""
    assert trustbook._parse(stamp) is None


def test_a_naive_timestamp_is_read_as_utc():
    """Rather than as local time, which would make a guess look hours older or
    younger than it is and quietly move the ladder."""
    from datetime import timezone as _tz
    parsed = trustbook._parse("2026-09-23T12:00:00")
    assert parsed.tzinfo == _tz.utc


def test_describe_says_who_writes_which_half():
    described = trustbook.describe()
    assert described["verdict_written_by"] == "the operator console only"
    assert described["survives_a_restart"] is True
