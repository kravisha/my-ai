"""The producers: what a turn writes down, and what the maintenance loop does.

Everything in `gateway/ledger.py` and `gateway/persistence.py` worked before
this and almost nothing wrote to it - after a restart the ledger held boot
reports and nothing else. These are the tests for the four things that closed
that: turn-level recording, the memory tools, the checkpoint cadence, and the
promotion of detected gaps into the §11 lifecycle.

`test_a_turn_is_remembered_across_a_restart` is the one that matters. It is
TEST A again, except that nothing in it writes state directly - a conversation
does, through the same path a real turn takes.
"""

import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from app import capability_gaps as detector
from app import initiative, model_calls
from app.learning import retention, store as learning_store
from dba import agent as agent_module, main as dba_main, registry, store
from gateway import (checkpoint as checkpoint_module, conversation, dbaclient,
                     gaps, identity, ledger, persistence, recording, rehydrate,
                     roles, tools, upkeep)

TOKEN = "test-token-for-jarvis"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PATH_ENV, str(tmp_path / "dba.db"))
    monkeypatch.setenv(dba_main.token_env_var("JARVIS"), TOKEN)
    monkeypatch.setenv(dbaclient.TOKEN_ENV, TOKEN)
    monkeypatch.setenv(identity.VERSION_ENV, "d" * 40)
    monkeypatch.setattr(model_calls, "log_dir", lambda: tmp_path)
    agent_module._AGENT = None
    registry.reset_sync()
    yield tmp_path
    agent_module._AGENT = None
    registry.reset_sync()


@pytest.fixture()
def service():
    with TestClient(dba_main.app) as running:
        yield running


@pytest.fixture()
def client(service, monkeypatch):
    def transport(method, path, payload):
        response = service.request(
            method, path, json=payload if method != "GET" else None,
            headers={"X-DBA-Agent": "JARVIS", "X-DBA-Token": TOKEN})
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {}

    made = dbaclient.DBAClient(transport=transport)
    # Every module under test constructs its own client; point them all at the
    # real service rather than at a stub, so what is verified is the contract.
    monkeypatch.setattr(dbaclient, "DBAClient", lambda **kwargs: made)
    return made


# =============================================================================
# 1. A turn records what happened
# =============================================================================


def test_a_turn_records_the_request_as_a_summary_not_the_sentence(client):
    """§8's retention answer: a reference and a summary, never the text.

    Asserted against `recording.SUMMARY_CHARS` rather than against a literal
    200. The first version of this test passed a raw 1400-character request and
    still went green, because `ledger.append` truncates to 200 of its own
    accord - so the property was being delivered by a constant in another
    module and the test could not tell the difference. `recording` bounds it
    itself now, and this pins that."""
    recorder = recording.Recorder(role=roles.ROLE_OPERATOR, subject="krish",
                                  conversation_id=7, client=client)
    long_request = "please " + ("reconcile the september statements " * 40)
    recorder.request(long_request)

    tip = ledger.tip(client)
    assert tip["event_type"] == ledger.USER_REQUEST
    assert tip["session_id"] == "conversation:7"
    assert tip["name"] == recording.summarise(long_request)
    assert len(tip["name"]) <= recording.SUMMARY_CHARS
    assert long_request not in json.dumps(tip)


def test_the_summary_bound_is_this_modules_own(client):
    """The probe for the test above. If `recording` stopped bounding the text,
    a ledger that truncated at a larger number would carry the sentence."""
    long_request = "x" * 5000
    assert len(recording.summarise(long_request)) == recording.SUMMARY_CHARS
    assert recording.SUMMARY_CHARS == 200


def test_a_failed_tool_is_recorded_and_a_read_only_one_is_not(client):
    """§5: meaningful transactions, not a dump. A read that succeeded changed
    nothing and is not part of a history of what happened."""
    recorder = recording.Recorder(role=roles.ROLE_OPERATOR, subject="krish",
                                  client=client)

    recorder.tool_succeeded("list_scoreboard_items")   # read-only
    assert ledger.length(client) == 0

    recorder.tool_succeeded("file_scoreboard_item")    # changed something
    recorder.tool_failed("remote_diagnose", "host unreachable")

    kinds = [row["event_type"] for row in ledger.events(client, limit=10)]
    assert kinds == [ledger.ACTION_SUCCEEDED, ledger.ACTION_FAILED]


def test_which_tools_count_as_changing_something_comes_from_their_own_risk():
    """Derived from TOOL_RISK rather than a second list here, so a new tool is
    classified by the statement that already decides whether it needs
    confirming."""
    assert recording._changed_something("file_scoreboard_item") is True
    assert recording._changed_something("publish_document") is True
    assert recording._changed_something("list_scoreboard_items") is False
    assert recording._changed_something("recall") is False
    # A tool with no risk entry cannot be classified, and is not guessed at.
    assert recording._changed_something("a_tool_nobody_declared") is False


def test_a_client_turn_is_not_written_into_jarvis_memory(client):
    """Every record is keyed agent="jarvis". A client's request summary landing
    there would be a privacy regression arriving through a continuity feature."""
    for role in (roles.ROLE_CLIENT, roles.ROLE_INTERNAL):
        recorder = recording.Recorder(role=role, subject="a-client",
                                      client=client)
        recorder.request("what are my holdings worth")
        recorder.tool_failed("anything", "x")
        assert recorder.enabled is False
    assert ledger.length(client) == 0


def test_an_unreachable_dba_costs_the_diary_and_not_the_turn(monkeypatch):
    """The failure is counted, logged, and filed as a capability gap - which
    puts it in the ranked monthly report rather than a log nobody opens."""
    def dead(method, path, payload):
        raise dbaclient.Unavailable("connection refused")

    recorder = recording.Recorder(role=roles.ROLE_OPERATOR, subject="krish",
                                  client=dbaclient.DBAClient(transport=dead))
    recorder.request("hello")          # does not raise

    assert recorder.written == 0
    assert recorder.problems and "life ledger" in recorder.problems[0]
    filed = detector.entries()
    assert filed and filed[-1]["gap_type"] == detector.GAP_MISSING_INTEGRATION


def test_a_turn_writes_its_request_through_the_real_run_turn(client):
    """The wiring, not the recorder: a turn with no tool calls still records."""

    class OneShot:
        def stream(self, system, messages, offered, max_tokens):
            yield {"type": "text", "text": "noted."}
            yield {"type": "final", "content": [{"type": "text", "text": "noted."}],
                   "stop_reason": "end_turn"}

    recorder = recording.Recorder(role=roles.ROLE_OPERATOR, subject="krish",
                                  conversation_id=3, client=client)
    events = list(conversation.run_turn(
        ":memory:", [{"role": "user", "text": "remember the boiler service"}],
        OneShot(), role=roles.ROLE_OPERATOR, subject="krish", recorder=recorder))

    assert events[-1]["type"] == "reply"
    assert ledger.tip(client)["event_type"] == ledger.USER_REQUEST
    assert "boiler" in ledger.tip(client)["name"]


# =============================================================================
# 2. The memory tools
# =============================================================================


def _call(name, arguments):
    return tools.execute(None, name, arguments, role=roles.ROLE_OPERATOR,
                         subject="krish")


def test_remember_survives_a_restart(client):
    result = _call("remember", {"kind": "preference", "name": "tone",
                                "value": "plain, no flattery"})
    assert result["survives_restart"] is True

    restoration = rehydrate.bootstrap(client)
    assert restoration.assert_fact(
        persistence.PREFERENCE, "tone")["value"] == "plain, no flattery"


def test_a_correction_is_recorded_as_a_correction_in_the_ledger(client):
    _call("remember", {"kind": "correction", "name": "krish-timezone",
                       "value": "Asia/Kolkata, not UTC"})

    assert persistence.get(client, persistence.CORRECTION,
                           "krish-timezone")["value"].startswith("Asia/Kolkata")
    assert ledger.tip(client)["event_type"] == ledger.USER_CORRECTION


def test_a_time_sensitive_memory_comes_back_flagged(client):
    _call("remember", {"kind": "knowledge", "name": "tunnel-url",
                       "value": "https://x.trycloudflare.com",
                       "time_sensitive": True})

    restoration = rehydrate.bootstrap(client)
    assert "knowledge/tunnel-url" in restoration.needs_reverification


def test_a_commitment_and_a_task_survive_a_restart(client):
    _call("record_commitment", {"name": "weekly-summary",
                                "promise": "send it every Sunday",
                                "owed_to": "krish"})
    _call("record_task_state", {"name": "september", "doing": "reconcile",
                                "step": "2 of 4",
                                "next_action": "fetch the card statement"})

    restoration = rehydrate.bootstrap(client)
    assert restoration.assert_fact(
        persistence.COMMITMENT, "weekly-summary")["promise"] == "send it every Sunday"
    assert restoration.assert_fact(
        persistence.TASK, "september")["next"] == "fetch the card statement"


def test_recall_finds_what_was_remembered_and_how(client):
    _call("remember", {"kind": "knowledge", "name": "boiler-service",
                       "value": "due every March"})
    found = _call("recall", {"subject": "boiler"})

    assert found["nothing_found"] is False
    assert found["remembered"][0]["name"] == "boiler-service"
    assert found["events"]


def test_recall_says_nothing_found_rather_than_reconstructing(client):
    found = _call("recall", {"subject": "something never mentioned"})
    assert found["nothing_found"] is True
    assert found["remembered"] == [] and found["events"] == []


def test_reconsider_adds_a_layer_and_keeps_the_original(client):
    original = ledger.append(client, event_type=ledger.LESSON,
                             summary="local models are always slower")
    result = _call("reconsider", {
        "event_id": original["id"],
        "new_understanding": "slower only above 8k context",
        "what_changed_it": "measured it on short prompts"})

    assert result["original_kept"] is True
    assert client.get(original["id"])["name"] == "local models are always slower"
    assert ledger.replay(client)["intact"] is True


def test_an_unreachable_dba_is_said_out_loud_not_swallowed(monkeypatch):
    """The failure to avoid is an assistant that believes it remembered
    something and did not."""
    def dead(**kwargs):
        raise dbaclient.Unavailable("connection refused")

    monkeypatch.setattr(dbaclient, "DBAClient", dead)
    result = _call("remember", {"kind": "knowledge", "name": "x", "value": "y"})
    assert "error" in result
    assert "Nothing was remembered" in result["error"]


def test_the_memory_tools_are_operator_only():
    for name in ("remember", "record_commitment", "record_task_state",
                 "recall", "reconsider"):
        assert tools.permitted(roles.ROLE_OPERATOR, name) is True
        for role in (roles.ROLE_CLIENT, roles.ROLE_INTERNAL):
            assert tools.permitted(role, name) is False


def test_remembering_is_something_jarvis_may_simply_do():
    """An assistant that had to ask permission to remember a correction is one
    that will not remember it."""
    for name in ("remember", "record_commitment", "record_task_state"):
        declared = tools.TOOL_RISK[name]
        verdict = initiative.decide(initiative.Action(
            name=name, reversibility=declared["reversibility"],
            reach=declared["reach"], summary=declared["summary"]))
        assert verdict.may_act, name


# =============================================================================
# 3. The checkpoint cadence
# =============================================================================


def test_the_first_sweep_takes_a_checkpoint_because_there_is_none(client):
    persistence.put(client, persistence.GOAL, "ship", "phase 3")
    result = upkeep.run_once(client)
    assert result["checkpoint"]["name"] == "checkpoint_000001"
    assert "no valid checkpoint" in result["checkpoint"]["why"]


def test_an_immediate_tier_write_forces_the_next_checkpoint(client):
    """What gives persistence.TIER something hanging on it."""
    checkpoint_module.take(client)
    due, why = upkeep.checkpoint_due(client)
    assert due is False

    persistence.put(client, persistence.TASK, "invoice", {"step": 2})
    due, why = upkeep.checkpoint_due(client)
    assert due is False, why      # periodic tier: written, but not urgent

    persistence.put(client, persistence.COMMITMENT, "sunday", "the summary")
    due, why = upkeep.checkpoint_due(client)
    assert due is True
    assert "immediate tier" in why


def test_the_interval_forces_one_even_with_nothing_important(client):
    from datetime import timedelta

    checkpoint_module.take(client)
    later = upkeep._now() + timedelta(hours=upkeep.CHECKPOINT_EVERY_HOURS + 1)
    due, why = upkeep.checkpoint_due(client, now=later)
    assert due is True
    assert "interval" in why


def test_a_sweep_that_cannot_reach_the_dba_reports_it_and_does_not_raise(monkeypatch):
    def dead(**kwargs):
        raise dbaclient.Unavailable("connection refused")

    monkeypatch.setattr(dbaclient, "DBAClient", dead)
    result = upkeep.run_once()
    assert result["problems"]
    assert result["checkpoint"] is None


def test_the_shutdown_checkpoint_is_taken_and_says_why(client):
    persistence.put(client, persistence.IDENTITY, "name", "Jarvis")
    record = upkeep.checkpoint_before_shutdown(client)
    assert record["reason"] == checkpoint_module.BEFORE_SHUTDOWN
    assert record["status"] == checkpoint_module.VALID


def test_shutdown_never_raises_when_the_store_is_gone(monkeypatch):
    def dead(**kwargs):
        raise dbaclient.Unavailable("connection refused")

    monkeypatch.setattr(dbaclient, "DBAClient", dead)
    assert upkeep.checkpoint_before_shutdown() is None


# =============================================================================
# 4. Detected gaps reach the lifecycle
# =============================================================================


def test_the_sweep_promotes_what_the_detector_recorded(client):
    """`app/capability_gaps.py` had been writing these to JSONL all along and
    nothing read them, so no gap Krish's own usage produced ever reached him."""
    for _ in range(3):
        detector.record(gap_type=detector.GAP_MISSING_TOOL,
                        what_was_needed="read a PDF",
                        user_visible_outcome="apologised")

    result = upkeep.run_once(client)

    assert result["promoted"] == ["missing_tool: read a PDF"]
    raised = gaps.all_gaps(client, status=gaps.SUSPECTED)
    assert raised[0]["frequency"] == 3
    # and suspected is all it is - nothing was confirmed and nothing proposed
    assert client.count("change_proposal", {}) == 0


def test_promotion_does_not_run_again_the_same_day(client):
    detector.record(gap_type=detector.GAP_MISSING_TOOL, what_was_needed="x",
                    user_visible_outcome="y")
    detector.record(gap_type=detector.GAP_MISSING_TOOL, what_was_needed="x",
                    user_visible_outcome="y")

    upkeep.run_once(client)
    assert upkeep.promotion_due(client) is False
    second = upkeep.run_once(client)
    assert second["promoted"] is None


def test_a_once_only_gap_is_not_promoted(client):
    """The detector's own threshold is kept rather than second-guessed."""
    detector.record(gap_type=detector.GAP_MISSING_KNOWLEDGE,
                    what_was_needed="the 2026 tax bands",
                    user_visible_outcome="guessed and said so")
    result = upkeep.run_once(client)
    assert result["promoted"] == []


# =============================================================================
# The whole point
# =============================================================================


def test_a_turn_is_remembered_across_a_restart(client):
    """TEST A again, except a conversation writes the state rather than a test.

    This is the difference between "Jarvis can persist" and "Jarvis does"."""
    recorder = recording.Recorder(role=roles.ROLE_OPERATOR, subject="krish",
                                  conversation_id=1, client=client)
    recorder.request("the boiler is serviced every March, not every September")
    _call("remember", {"kind": "correction", "name": "boiler-service",
                       "value": "every March"})
    _call("record_commitment", {"name": "book-boiler",
                                "promise": "book the March service"})
    _call("record_task_state", {"name": "september-summary", "doing": "reconcile",
                                "step": "2 of 4", "next_action": "fetch the card"})
    upkeep.run_once(client)          # a checkpoint, because a commitment landed

    # Stop completely. A new runtime, holding nothing.
    restoration = rehydrate.bootstrap(client)

    assert restoration.status == rehydrate.RESTORED_OK
    assert restoration.assert_fact(
        persistence.CORRECTION, "boiler-service")["value"] == "every March"
    assert restoration.assert_fact(
        persistence.COMMITMENT, "book-boiler")["promise"] == "book the March service"
    assert restoration.assert_fact(
        persistence.TASK, "september-summary")["next"] == "fetch the card"
    assert restoration.checkpoint is not None

    # And the ledger says how he came to know it, in order.
    kinds = [row["event_type"] for row in ledger.events(client, limit=20)]
    assert ledger.USER_REQUEST in kinds
    assert ledger.USER_CORRECTION in kinds
    assert ledger.DECISION in kinds
    assert ledger.replay(client)["intact"] is True


# =============================================================================
# Collecting deadweight memory
# =============================================================================
#
# Krish, 2026-09-23: *"all deadweight unreferenced information should be
# eventually garbage collected as well"*. `app/learning/retention.py` decides and
# `app/learning/memory.collect_garbage` acts, and this is the only thing in the
# system that ever calls it. A sweep nothing calls is this repository's
# commonest failure, so it gets a test rather than a comment.


def _deadweight(monkeypatch, tmp_path):
    """Four lessons of one kind, offered together often, three always preferred.

    The fourth is ranked below the cut every single time, which is what makes it
    deadweight rather than a fact nothing ever asked about."""
    monkeypatch.setenv(learning_store.PATH_ENV, str(tmp_path / "learning.db"))
    from app.learning import memory
    doomed = learning_store.record_lesson(kind=memory.SOURCE_VALUE,
                                          pattern="never_chosen", lesson="x",
                                          cost=12.0)
    for index in range(3):
        learning_store.record_lesson(kind=memory.SOURCE_VALUE,
                                     pattern=f"better-{index}", lesson="y",
                                     cost=1.0)
    for _ in range(retention.MIN_OFFERS_TO_JUDGE + 2):
        memory.advice_for(None)
    # Age it past a full cycle, which is the other half of the licence to collect.
    with learning_store.connect() as db:
        db.execute("UPDATE lessons SET at = '2019-01-01T00:00:00+00:00'")
    return doomed


def test_the_maintenance_loop_collects_deadweight_memory(client, monkeypatch,
                                                         tmp_path):
    doomed = _deadweight(monkeypatch, tmp_path)
    assert upkeep.collection_due(client) is True

    result = upkeep.run_once(client)
    assert result["collection"] is not None
    assert "never_chosen" in result["collection"]["discarded"]
    assert doomed not in [row["id"] for row in learning_store.lessons()]


def test_collecting_is_not_repeated_every_sweep(client, monkeypatch, tmp_path):
    """Every rule in `retention` is measured in months. A sweep four times a day
    would read every lesson three hundred times a week to reach the same
    answer."""
    _deadweight(monkeypatch, tmp_path)
    upkeep.run_once(client)
    assert upkeep.collection_due(client) is False
    assert upkeep.run_once(client)["collection"] is None


def test_the_sweep_can_report_without_deleting(client, monkeypatch, tmp_path):
    doomed = _deadweight(monkeypatch, tmp_path)
    monkeypatch.setenv(upkeep.COLLECTION_DRY_RUN_ENV, "1")

    result = upkeep.run_once(client)
    assert result["collection"]["dry_run"] is True
    assert result["collection"]["discarded"] == ["never_chosen"]
    assert doomed in [row["id"] for row in learning_store.lessons()]


def test_a_broken_learning_store_does_not_stop_the_rest_of_the_sweep(
        client, monkeypatch, tmp_path):
    """The loop never raises. A maintenance job that ends on an exception is one
    that stops running and tells nobody."""
    from app.learning import memory
    monkeypatch.setattr(memory, "collect_garbage",
                        lambda **kwargs: (_ for _ in ()).throw(OSError("disk")))
    result = upkeep.run_once(client)
    assert any("memory collection" in problem for problem in result["problems"])
    assert result["checkpoint"] is not None


def test_the_maintenance_cadences_are_what_they_are():
    """Asserted as literals, with the reason each one has its value.

    A test written in terms of a constant cannot detect a wrong constant, which
    `tests/probes/` found the hard way: setting the collection interval from a
    week to six hours broke nothing, because every test asked "is it due?" twice
    in the same second. These four numbers are policy about how often Jarvis
    disturbs his own record, and changing one should mean changing this test."""
    # How much of a day's work may have no validated recovery point.
    assert upkeep.CHECKPOINT_EVERY_HOURS == 6
    # A fault recurring right now is the thing most worth noticing early, and the
    # scan reads a bounded window of one file.
    assert upkeep.SCAN_LOGS_EVERY_HOURS == 6
    # The detector's threshold is about recurrence; asking more often than the
    # thing recurs produces no new information.
    assert upkeep.PROMOTE_GAPS_EVERY_HOURS == 24
    # Every rule in app/learning/retention.py is measured in months, and the
    # answer cannot change faster than its thirty-day grace period.
    assert upkeep.COLLECT_MEMORY_EVERY_HOURS == 24 * 7


# =============================================================================
# Noticing something before Krish asks
# =============================================================================
#
# Krish, 2026-09-23: *"being preemptive in being helpful like humans holding the
# door."* The trust ladder had nothing on it until the sweep started producing
# guesses, and a ladder with nothing on it is the same failure as one nothing
# can climb.


def _a_promise(client, days=1, promise="send Krish the Q3 statement"):
    from datetime import datetime, timedelta, timezone
    due = datetime.now(timezone.utc) + timedelta(days=days)
    return client.create("commitment", {
        "name": promise[:200], "agent": "jarvis", "promise": promise,
        "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "due_on": due.date().isoformat(), "status": "open"},
        reason="test promise")


def test_the_sweep_notices_a_promise_coming_due(client):
    from gateway import trustbook

    _a_promise(client)
    assert upkeep.noticing_due(client) is True

    result = upkeep.run_once(client)
    assert result["noticed"] is not None

    # Recorded as a guess whatever the rung allows saying.
    made, problems = trustbook.load(client)
    assert problems == []
    assert [one.domain for one in made] == ["commitments"]
    assert "due on" in made[0].because


def test_a_new_domain_records_and_says_nothing(client):
    """The bottom rung, doing what it says. Nothing has been earned yet, so the
    noticing is written down and not spoken."""
    _a_promise(client)
    result = upkeep.run_once(client)
    assert result["noticed"]["say"] == []
    assert result["noticed"]["recorded_only"] == 1


def test_noticing_is_not_repeated_every_sweep(client):
    _a_promise(client)
    upkeep.run_once(client)
    assert upkeep.noticing_due(client) is False
    assert upkeep.run_once(client)["noticed"] is None


def test_a_broken_trust_record_does_not_stop_the_rest_of_the_sweep(
        client, monkeypatch):
    from gateway import trustbook

    monkeypatch.setattr(trustbook, "load",
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            ValueError("the record will not load")))
    result = upkeep.run_once(client)
    assert any("noticing" in problem for problem in result["problems"])
    assert result["checkpoint"] is not None


def test_the_noticing_cadence_is_what_it_is():
    """Four hours: a promise due tomorrow is worth raising today and not worth
    raising six times today."""
    assert upkeep.NOTICE_EVERY_HOURS == 4
    assert "notice_every_hours" in upkeep.describe()
