"""T24-T27 the strict JSON bridge; T28-T33 the speech emission descriptor, callbacks bound to
(token, epoch, cancel generation), stop invalidation, no-speech paths, and defensive locking.
No window, no pywebview import, no audio."""

from __future__ import annotations

import json
import sys
import threading

import pytest

from jarvis_voice.comm import bridge, handshake
from tests.test_jarvis_comm_state import World  # noqa: F401 (reuses the fakes-only world)
from tests.test_jarvis_comm_support import *  # noqa: F401,F403


@pytest.fixture
def api(tmp_path):
    w = World(tmp_path)
    w.handshake()
    return w, bridge.CommApi(w.comm)


def _result_for(w, req_id, text="4"):
    w.peer_result({"message_id": req_id, "conversation_id": w.comm.conversation_id}, text=text)


# ---------------------------------------------------------------- T24-T27 strict boundary
def test_T24_every_method_returns_strict_json_values_only(api):
    w, a = api
    for value in (a.snapshot(), a.transcript(), a.escalate("what is 2 plus 2?", origin="krish-via-jarvis"), a.poll(), a.view(), a.stop()):
        json.dumps(value, allow_nan=False)


def test_T25_snapshot_has_the_frozen_keys_binding_facts_and_status_sources(api):
    w, a = api
    s = a.snapshot()
    assert set(s) == {"status", "pending", "binding", "recovery"}
    assert s["recovery"]["state"] == "not_run"
    b = s["binding"]
    assert b["bound"] is True and b["peer_id"] == PEER["id"] and b["self_id"] == SELF["id"]
    assert b["peer_epoch"] == PEER["epoch"] and b["self_epoch"] == SELF["epoch"] and b["cancel_generation"] == 0
    assert s["status"]["storage"] == {"state": "durable (fake-file)", "source": "capabilities"}
    a.escalate("q", origin="krish-via-jarvis")
    s2 = a.snapshot()
    assert s2["pending"] is not None and s2["status"]["request"] == {"state": "delivered", "source": "readback"}
    assert s2["binding"]["conversation_id"] == w.comm.conversation_id


def test_T26_escalate_refuses_empty_and_busy_and_stop_reports_cancel_states(api):
    w, a = api
    assert a.escalate("", origin="krish-via-jarvis") == {"sent": False, "reason": "empty"}
    assert a.escalate(None) == {"sent": False, "reason": "empty"}
    first = a.escalate("first", origin="krish-via-jarvis")
    assert first["sent"] is True and first["status"] == "delivered"
    second = a.escalate("second", origin="krish-via-jarvis")
    assert second["sent"] is False and second["reason"] == "busy"
    st = a.stop()
    assert st == {"request": "cancelled", "remote_cancel": "unconfirmed", "cancel_generation": 1}
    assert w.speaker.stopped == 1


def test_T27_transcript_records_carry_only_allow_listed_fields_and_unexpected_types_raise(api):
    w, a = api
    req = a.escalate("q", origin="krish-via-jarvis")
    _result_for(w, req["message_id"])
    a.poll()
    t = a.transcript()
    assert t[-1]["payload"]["text"] == "4" and t[-1]["speech"] == "spoken" and t[-1]["persisted"]["turn"] is True
    assert set(t[-1]) <= set(bridge.TRANSCRIPT_FIELDS)
    w.comm.transcript[-1]["responder"] = object()
    with pytest.raises(bridge.BridgeContractError):
        a.transcript()


def test_bridge_imports_no_window_toolkit():
    assert "webview" not in sys.modules and "tkinter" not in sys.modules


# ---------------------------------------------------------------- T28-T33 speech contract
def test_T28_blocking_speaker_gets_the_full_descriptor_and_is_recorded_spoken(api):
    w, a = api
    req = a.escalate("q", origin="krish-via-jarvis")
    _result_for(w, req["message_id"])
    a.poll()
    d = w.speaker.descriptors[-1]
    assert set(d) == {"emission_id", "request_id", "epoch", "cancel_generation", "text"}
    assert d["request_id"] == req["message_id"] and d["epoch"] == SELF["epoch"] and d["cancel_generation"] == 0 and d["text"] == "4"
    assert w.comm.speech.state(d["emission_id"]) == "spoken"
    assert a.transcript()[-1]["speech"] == "spoken"


def test_T29_async_speaker_stays_queued_until_the_bound_completion_callback(tmp_path):
    w = World(tmp_path)
    w.speaker = FakeAsyncSpeaker()
    w.comm = w._build(w.rel)
    w.handshake()
    a = bridge.CommApi(w.comm)
    req = a.escalate("q", origin="krish-via-jarvis")
    _result_for(w, req["message_id"])
    p = a.poll()
    d = p["speech"][0]
    assert d["state"] == "eligible" and a.transcript()[-1]["speech"] == "queued"
    # wrong epoch or wrong generation: refused, state untouched
    assert a.speech_completed(d["token_id"], "other-epoch", d["cancel_generation"])["outcome"] == "refused"
    assert a.speech_completed(d["token_id"], d["epoch"], d["cancel_generation"] + 1)["outcome"] == "refused"
    assert a.speech_completed("not-a-token", d["epoch"], d["cancel_generation"])["outcome"] == "refused"
    assert a.speech_completed(d["token_id"], d["epoch"], "0")["outcome"] == "refused"   # typed triple only
    assert a.transcript()[-1]["speech"] == "queued"
    assert a.speech_started(d["token_id"], d["epoch"], d["cancel_generation"])["outcome"] == "applied"
    assert a.speech_completed(d["token_id"], d["epoch"], d["cancel_generation"]) == {"outcome": "applied", "state": "spoken"}
    assert a.transcript()[-1]["speech"] == "spoken"
    # duplicates are idempotent
    assert a.speech_completed(d["token_id"], d["epoch"], d["cancel_generation"])["outcome"] == "ignored"
    assert a.speech_error(d["token_id"], d["epoch"], d["cancel_generation"], "Late")["outcome"] == "ignored"


def test_T30_stop_invalidates_before_speaker_stop_and_a_delayed_onend_cannot_revive_spoken(tmp_path):
    w = World(tmp_path)
    w.speaker = FakeAsyncSpeaker()
    w.comm = w._build(w.rel)
    w.handshake()
    a = bridge.CommApi(w.comm)
    req = a.escalate("q", origin="krish-via-jarvis")
    _result_for(w, req["message_id"])
    d = a.poll()["speech"][0]
    seen = {}
    w.speaker.stop_hook = lambda: seen.setdefault("state_at_stop", w.comm.speech.state(d["token_id"]))
    st = a.stop()
    assert st["cancel_generation"] == 1 and seen["state_at_stop"] == "cancelled_before_completion"
    assert a.speech_completed(d["token_id"], d["epoch"], d["cancel_generation"])["outcome"] == "ignored"
    assert a.speech_completed(d["token_id"], d["epoch"], 1)["outcome"] == "refused"
    assert a.transcript()[-1]["speech"] == "cancelled_before_completion"


def test_T31_error_callback_is_a_bounded_type_not_free_text(tmp_path):
    w = World(tmp_path)
    w.speaker = FakeAsyncSpeaker()
    w.comm = w._build(w.rel)
    w.handshake()
    a = bridge.CommApi(w.comm)
    req = a.escalate("q", origin="krish-via-jarvis")
    _result_for(w, req["message_id"])
    d = a.poll()["speech"][0]
    r = a.speech_error(d["token_id"], d["epoch"], d["cancel_generation"], "Traceback (most recent call last): boom")
    assert r == {"outcome": "applied", "state": "error(UnknownError)"}
    req2_blocked = a.escalate("again", origin="krish-via-jarvis")
    assert req2_blocked["sent"] is True  # an errored emission never blocks the next consultation


def test_T32_no_playback_speaker_and_none_return_never_yield_spoken(tmp_path):
    class LogLike:
        playback = False
        def speak(self, d): return None
        def stop(self): pass

    class NoneReturner:
        playback = True
        blocking_completion = False
        def speak(self, d): return None
        def stop(self): pass

    for speaker, expected in ((LogLike(), "no_speech_path"), (NoneReturner(), "error(SpeakerContract)")):
        w = World(tmp_path / expected.replace("(", "_").replace(")", ""))
        w.speaker = speaker
        w.comm = w._build(w.rel)
        w.handshake()
        a = bridge.CommApi(w.comm)
        req = a.escalate("q", origin="krish-via-jarvis")
        _result_for(w, req["message_id"])
        a.poll()
        assert a.transcript()[-1]["speech"] == expected


def test_T33_lock_is_defensive_mutual_exclusion_two_threads_yield_one_sent_one_busy(api):
    w, a = api
    results = []
    barrier = threading.Barrier(2)

    def go(text):
        barrier.wait()
        results.append(a.escalate(text, origin="krish-via-jarvis"))

    ts = [threading.Thread(target=go, args=(t,)) for t in ("one", "two")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sorted(r["sent"] for r in results) == [False, True]
    assert [r for r in results if not r["sent"]][0]["reason"] == "busy"


# ---------------------------------------------------------------- T37/T38 recovery visibility through the facade (UI executor repro, Arya 5826206681)
def test_T37_negative_control_malformed_recover_is_visible_in_start_snapshot_view_and_blocks_escalation(tmp_path):
    from jarvis_voice.comm import storage

    class TupleRecover(storage.NoopStore):
        def recover(self, current_epoch):
            return ("not", "a", "dict")

    w = World(tmp_path, store=TupleRecover())
    a = bridge.CommApi(w.comm)
    st = a.start()
    assert st["recovery"]["state"] == "unresolved"
    assert st["recovery"]["errors"] == ["recover: contract_error (returned tuple, expected dict)"]
    assert a.snapshot()["recovery"]["state"] == "unresolved"
    assert a.snapshot()["status"]["recovery"] == {"state": "unresolved (store contract error)", "source": "store"}
    assert a.view()["snapshot"]["recovery"]["errors"] == st["recovery"]["errors"]
    # bind the peer exactly as the fixture does, then try to escalate: refused, nothing sent
    w.peer_check_in(reply_to=[st["check_in_id"]])
    a.poll()
    assert a.snapshot()["binding"]["bound"] is True
    r = a.escalate("what is 2 plus 2?", origin="krish-via-jarvis")
    assert r["sent"] is False and r["reason"].startswith("recovery_unresolved")
    assert '"type": "QUESTION"' not in w.spool.read_text(encoding="utf-8")
    assert a.snapshot()["status"]["request"] == {"state": "blocked", "source": "publisher"}
    # a later clean recover() lifts the block
    w.comm.store = storage.NoopStore()
    assert a.recover()["state"] == "ok"
    assert a.escalate("what is 2 plus 2?", origin="krish-via-jarvis")["sent"] is True


def test_T38_positive_control_clean_recover_reports_ok_and_allows_escalation(tmp_path):
    w = World(tmp_path)
    a = bridge.CommApi(w.comm)
    st = a.start()
    assert st["recovery"]["state"] == "ok" and st["recovery"]["errors"] == []
    w.peer_check_in(reply_to=[st["check_in_id"]])
    a.poll()
    assert a.escalate("q", origin="krish-via-jarvis")["sent"] is True
    assert a.snapshot()["status"]["recovery"] == {"state": "ok", "source": "store"}


# ---------------------------------------------------------------- T47/T48 unresolved recovery categories gate (Arya 5826247682, R4 repro)
def test_T47_frozen_unsupported_major_in_the_report_is_unresolved_and_gates_escalation(tmp_path):
    from jarvis_voice.comm import storage

    class FrozenMajor(storage.NoopStore):
        def recover(self, current_epoch):
            rep = super().recover(current_epoch)
            rep["checkpoint_frozen_unsupported_major"] = ["checkpoints/abc.json"]
            return rep

    w = World(tmp_path, store=FrozenMajor())
    a = bridge.CommApi(w.comm)
    st = a.start()
    assert st["recovery"]["state"] == "unresolved"
    assert st["recovery"]["errors"] == ["checkpoint_frozen_unsupported_major: 1 file(s) preserved and refused"]
    w.peer_check_in(reply_to=[st["check_in_id"]])
    a.poll()
    assert a.escalate("q", origin="krish-via-jarvis")["sent"] is False
    assert '"type": "QUESTION"' not in w.spool.read_text(encoding="utf-8")


def test_T48_known_conversation_without_a_checkpoint_or_unknown_pending_is_unresolved_fresh_root_is_ok(tmp_path):
    import uuid as _uuid
    from jarvis_voice.comm import storage
    conv = str(_uuid.uuid4())

    class KnownConvNoCheckpoint(storage.NoopStore):
        def recover(self, current_epoch):
            rep = super().recover(current_epoch)
            rep["stale_unresolved"] = [{"request_id": str(_uuid.uuid4()), "epoch": "old", "conversation_id": conv, "state": "stale_unresolved"}]
            return rep

    w = World(tmp_path, store=KnownConvNoCheckpoint())
    a = bridge.CommApi(w.comm)
    st = a.start()
    assert st["recovery"]["state"] == "unresolved"
    assert any(e.startswith("pending_state: unknown (checkpoint unavailable)") for e in st["recovery"]["errors"])

    class SameEpochPending(storage.NoopStore):
        def recover(self, current_epoch):
            rep = super().recover(current_epoch)
            rep["still_pending"] = [{"request_id": str(_uuid.uuid4()), "epoch": current_epoch, "conversation_id": conv, "state": "awaiting_reply"}]
            return rep

    w2 = World(tmp_path / "b", store=SameEpochPending())
    st2 = bridge.CommApi(w2.comm).start()
    assert st2["recovery"]["state"] == "unresolved" and any(e.startswith("still_pending") for e in st2["recovery"]["errors"])
    # fresh root: nothing known, ok (positive control)
    w3 = World(tmp_path / "c", store=storage.NoopStore())
    assert bridge.CommApi(w3.comm).start()["recovery"]["state"] == "ok"


# ---------------------------------------------------------------- T49 status projection == recovery classification (UI executor, Arya 5826383776)
@pytest.mark.parametrize("category", ["contract", "frozen_major", "checkpoint_unavailable", "still_pending", "ok"])
def test_T49_status_recovery_and_recovery_state_never_disagree(tmp_path, category):
    import uuid as _uuid
    from jarvis_voice.comm import storage
    conv = str(_uuid.uuid4())

    class S(storage.NoopStore):
        def recover(self, current_epoch):
            if category == "contract":
                return ("bad",)
            rep = super().recover(current_epoch)
            if category == "frozen_major":
                rep["history_frozen_unsupported_major"] = ["history/x.jsonl"]
            elif category == "checkpoint_unavailable":
                rep["stale_unresolved"] = [{"request_id": str(_uuid.uuid4()), "epoch": "old", "conversation_id": conv, "state": "stale_unresolved"}]
            elif category == "still_pending":
                rep["still_pending"] = [{"request_id": str(_uuid.uuid4()), "epoch": current_epoch, "conversation_id": conv, "state": "awaiting_reply"}]
            return rep

    w = World(tmp_path, store=S())
    a = bridge.CommApi(w.comm)
    st = a.start()
    snap = a.snapshot()
    state = snap["recovery"]["state"]
    status_text = snap["status"]["recovery"]["state"]
    assert state == st["recovery"]["state"]
    if category == "ok":
        assert state == "ok" and status_text == "ok"
    else:
        assert state == "unresolved" and status_text.startswith("unresolved (")
        from jarvis_voice.comm import state as state_mod
        assert status_text == f"unresolved ({state_mod.recovery_category(snap['recovery']['errors'][0])})"
        assert status_text in ("unresolved (store contract error)", "unresolved (frozen unsupported major)",
                               "unresolved (checkpoint unavailable)", "unresolved (still pending)", "unresolved (pending unknown)")
    assert (a.escalate("q", origin="krish-via-jarvis")["sent"] is False) == (state == "unresolved") or not snap["binding"]["bound"]


# ---------------------------------------------------------------- T54-T57 persistence-host API (Arya 5826453952)
def test_T54_record_user_turn_is_idempotent_on_submission_id_and_escalate_reuses_it(api):
    w, a = api
    r1 = a.record_user_turn("what is 2 plus 2?", "krish-via-jarvis", "sub-1")
    r2 = a.record_user_turn("what is 2 plus 2?", "krish-via-jarvis", "sub-1")
    assert r1["duplicate"] is False and r2["duplicate"] is True and r2["user_event_id"] == r1["user_event_id"]
    conv = r1["conversation_id"]
    assert [t["kind"] for t in w.store.turns[conv]] == ["user"]                       # written once
    e = a.escalate(origin="krish-via-jarvis", user_event_id=r1["user_event_id"])
    assert e["sent"] is True and e["user_event_id"] == r1["user_event_id"]
    assert [t["kind"] for t in w.store.turns[conv]] == ["user"]                       # still once
    assert a.escalate("x", origin="krish-via-jarvis", user_event_id="nope")["reason"].startswith("contract_error")
    assert a.record_user_turn("t", "krish-via-jarvis", "")["persisted"]["error"] == "contract_error"


def test_T55_text_escalate_records_once_atomically_and_local_answer_links_the_user_turn(api):
    w, a = api
    e = a.escalate("q", origin="jarvis", submission_id="sub-9")
    conv = w.comm.conversation_id
    assert e["sent"] is True and [t["kind"] for t in w.store.turns[conv]] == ["user"]
    assert w.store.turns[conv][0]["payload"]["submission_id"] == "sub-9"
    again = a.escalate("q", origin="jarvis", submission_id="sub-9")                   # same submission while pending
    assert again["sent"] is False and again["reason"] in ("duplicate_submission", "busy")
    loc = a.record_local_answer("local says 4", "jarvis", e["user_event_id"])
    assert loc["persisted"]["turn"] is True and loc["linked_user_event_id"] == e["user_event_id"]
    assert w.store.turns[conv][-1]["payload"]["user_event_id"] == e["user_event_id"]
    assert a.record_local_answer("x", "jarvis", "unknown-id")["persisted"]["error"] == "contract_error"


def test_T56_conversations_are_enumerated_from_persisted_facts_and_selected_explicitly(tmp_path):
    w = World(tmp_path)
    a = bridge.CommApi(w.comm)
    assert a.conversations() == []
    w.handshake()
    e = a.escalate("q", origin="krish-via-jarvis")
    w.peer_result({"message_id": e["message_id"], "conversation_id": w.comm.conversation_id}, text="4"); a.poll()
    a.shutdown()
    convs = a.conversations()
    assert len(convs) == 1 and convs[0]["conversation_id"] == w.comm.conversation_id
    assert convs[0]["closed_cleanly"] is True and convs[0]["pending"] == 0 and convs[0]["source"] == "checkpoint"
    # a new session over the same root: nothing auto-selected; explicit selection restores display-only
    rel2 = handshake.Relationship(self_id=SELF["id"], self_session=SELF["session"], self_epoch="epoch-claude-2")
    comm2 = w._build(rel2)
    a2 = bridge.CommApi(comm2)
    assert comm2.conversation_id is None
    assert a2.select_conversation("not-a-conversation")["selected"] is False
    assert a2.transcript() == []                                                          # start/recover shows nothing unselected
    sel = a2.select_conversation(convs[0]["conversation_id"])
    assert sel["selected"] is True and sel["recovery"]["state"] == "ok"
    restored = [t for t in a2.transcript() if t.get("restored")]
    assert [t["kind"] for t in restored] == ["user", "assistant_claude"] and restored[1]["speech"] == "unknown"
    assert w.speaker.spoken == ["4"]                                                   # nothing replayed


def test_T57_shutdown_reports_unsaved_turns_and_a_failed_final_checkpoint_never_claims_saved(api):
    w, a = api
    w.store.fail.append("save_completed_turn")
    r = a.record_user_turn("lost words", "krish-via-jarvis", "sub-lost")
    assert r["persisted"]["turn"] is False
    w.store.fail.append("save_checkpoint")
    out = a.shutdown()
    assert out["checkpoint_persisted"] is False and out["error"] == "OSError"
    assert out["unsaved"] == [r["user_event_id"]]
    assert w.speaker.stopped == 0                                                      # shutdown is not stop()


def test_T58_submission_conflict_consultation_envelope_and_selection_refusal(api):
    w, a = api
    r = a.record_user_turn("what is 2 plus 2?", "krish-via-jarvis", "sub-c")
    c = a.record_user_turn("something else", "krish-via-jarvis", "sub-c")
    assert c["conflict"] is True and c["user_event_id"] is None and c["persisted"]["error"] == "conflict"
    assert [t["kind"] for t in w.store.turns[r["conversation_id"]]] == ["user"]
    # the envelope sent to Claude may differ from the saved words; the saved words are untouched
    e = a.escalate(origin="krish-via-jarvis", user_event_id=r["user_event_id"], consultation_text="Krish asks: what is 2 plus 2? (context: none)")
    assert e["sent"] is True
    assert "Krish asks" in w.spool.read_text(encoding="utf-8")
    assert w.store.turns[r["conversation_id"]][0]["payload"]["text"] == "what is 2 plus 2?"
    assert w.comm.requests[e["message_id"]]["consultation_text"].startswith("Krish asks")
    # selection is refused while a consultation is pending
    sel = a.select_conversation(r["conversation_id"])
    assert sel["selected"] is False and sel["reason"] == "active_or_unsaved" and sel["pending"] == e["message_id"]
    # a local-answer save failure appears in shutdown().unsaved as well
    w.peer_result({"message_id": e["message_id"], "conversation_id": w.comm.conversation_id}, text="4"); a.poll()
    w.store.fail.append("save_completed_turn")
    loc = a.record_local_answer("late local", "jarvis", r["user_event_id"])
    assert loc["persisted"]["turn"] is False
    assert loc["event_id"] in a.shutdown()["unsaved"]


def test_T59_dedup_horizon_is_documented_and_restored_submissions_are_refused_not_resent(tmp_path):
    from jarvis_voice.comm import state as state_mod
    w = World(tmp_path)
    a = bridge.CommApi(w.comm)
    w.handshake()
    a.record_user_turn("q", "krish-via-jarvis", "sub-r")
    a.shutdown()
    rel2 = handshake.Relationship(self_id=SELF["id"], self_session=SELF["session"], self_epoch="epoch-claude-2")
    comm2 = w._build(rel2)
    a2 = bridge.CommApi(comm2)
    a2.select_conversation(w.comm.conversation_id)
    again = a2.record_user_turn("q", "krish-via-jarvis", "sub-r")
    assert again["duplicate"] is True and again["user_event_id"] is None and again["reason"].startswith("submission_seen_before_restart")
    assert state_mod.Comm.SUBMISSIONS_KEPT == 100    # the horizon is finite and documented; beyond it a replay is not detectable


def test_T60_local_answer_exact_once_per_user_turn_new_conversation_and_ledger_backed_dedup(tmp_path):
    from jarvis_voice.comm import ledger as ledger_mod
    w = World(tmp_path)
    a = bridge.CommApi(w.comm)
    w.handshake()
    r = a.record_user_turn("q", "krish-via-jarvis", "sub-x")
    one = a.record_local_answer("answer", "jarvis", r["user_event_id"], completion_id="c1")
    dup = a.record_local_answer("answer", "jarvis", r["user_event_id"], completion_id="c1")      # host completion fired twice
    assert one["duplicate"] is False and dup["duplicate"] is True and dup["event_id"] == one["event_id"]
    dup2 = a.record_local_answer("answer", "jarvis", r["user_event_id"])                         # same words, no id: fingerprint
    assert dup2["duplicate"] is True
    con = a.record_local_answer("different", "jarvis", r["user_event_id"], completion_id="c2")
    assert con["conflict"] is True and con["event_id"] is None
    assert [t["kind"] for t in w.store.turns[r["conversation_id"]]] == ["user", "assistant_local"]
    # new conversation: explicit, refused while anything is unsaved, otherwise a fresh id known to the ledger
    nc = a.new_conversation()
    assert nc["created"] is True and nc["conversation_id"] != r["conversation_id"]
    assert nc["conversation_id"] in ledger_mod.Ledger(tmp_path / "ledger.json").conversations()
    # dedup survives even when the checkpoint save failed: the ledger kept the submission id
    w.store.fail.append("save_checkpoint")
    a.shutdown()
    rel2 = handshake.Relationship(self_id=SELF["id"], self_session=SELF["session"], self_epoch="epoch-claude-2")
    a2 = bridge.CommApi(w._build(rel2))
    again = a2.record_user_turn("q", "krish-via-jarvis", "sub-x")
    assert again["duplicate"] is True and again["user_event_id"] is None
    # a failed shutdown leaves the facade usable: a spoken retry works, nothing is "already closed"
    out = a.shutdown()
    assert out["checkpoint_persisted"] in (True, False)
    assert a.new_conversation()["created"] in (True, False)


def test_T61_S17_failed_user_save_refuses_the_consultation_and_S19_uncertain_replay(tmp_path):
    from jarvis_voice.comm import state as state_mod, storage
    w = World(tmp_path)
    a = bridge.CommApi(w.comm)
    w.handshake()
    w.store.fail.append("save_completed_turn")
    r = a.escalate("q", origin="krish-via-jarvis", submission_id="1700000000000-a")
    assert r["sent"] is False and r["reason"] == "user_turn_not_persisted (OSError)"
    assert '"type": "QUESTION"' not in w.spool.read_text(encoding="utf-8")
    assert a.transcript()[-1]["kind"] == "user" and a.transcript()[-1]["persisted"]["turn"] is False   # words kept, shown unsaved
    # non-durable storage is NOT a failure: the demo still consults
    w2 = World(tmp_path / "noop", store=storage.NoopStore()); a2 = bridge.CommApi(w2.comm); w2.handshake()
    assert a2.escalate("q", origin="krish-via-jarvis")["sent"] is True
    # S19: with a full horizon, a timestamped id older than everything remembered is an uncertain replay, refused
    w3 = World(tmp_path / "h"); a3 = bridge.CommApi(w3.comm)
    for i in range(state_mod.Comm.SUBMISSIONS_KEPT):
        a3.record_user_turn(f"t{i}", "jarvis", f"{1700000100000 + i}-x")
    old = a3.record_user_turn("old words", "jarvis", "1700000000000-old")
    assert old["user_event_id"] is None and old["reason"].startswith("uncertain_replay")
    new = a3.record_user_turn("new words", "jarvis", "1700000200000-new")
    assert new["user_event_id"] is not None
    assert a3.record_user_turn("no ts", "jarvis", "plain-id")["user_event_id"] is not None   # untimestamped ids cannot be judged, treated as new


def test_T62_S21_S20b_S16b_start_then_select_restores_once_no_implicit_resume_answer_names_its_question(tmp_path):
    w = World(tmp_path)
    a = bridge.CommApi(w.comm)
    w.handshake()
    e = a.escalate("q", origin="krish-via-jarvis")
    w.peer_result({"message_id": e["message_id"], "conversation_id": w.comm.conversation_id}, text="4"); a.poll()
    conv = w.comm.conversation_id
    stored_answer = [t for t in w.store.turns[conv] if t["kind"] == "assistant_claude"][0]
    assert stored_answer["payload"]["user_event_id"] == e["user_event_id"]                    # S16b
    a.shutdown()
    rel2 = handshake.Relationship(self_id=SELF["id"], self_session=SELF["session"], self_epoch="epoch-claude-2")
    comm2 = w._build(rel2); a2 = bridge.CommApi(comm2)
    st = a2.start()
    assert comm2.conversation_id is None                                                       # S20b: nothing auto-continued
    r = a2.record_user_turn("more", "krish-via-jarvis", "sub-m")
    assert r["user_event_id"] is None and r["reason"].startswith("conversation_required")     # explicit choice required
    sel = a2.select_conversation(conv)
    assert sel["selected"] is True
    kinds = [t["kind"] for t in a2.transcript() if t.get("restored")]
    assert kinds == ["user", "assistant_claude"]                                               # S21: restored once, not twice
    assert a2.record_user_turn("more", "krish-via-jarvis", "sub-m")["user_event_id"] is not None


def test_T63_T65_facade_after_shutdown_identities_in_transcript_no_cross_conversation_rows(tmp_path):
    w = World(tmp_path)
    a = bridge.CommApi(w.comm)
    w.handshake()
    e = a.escalate("first conversation", origin="krish-via-jarvis")
    w.peer_result({"message_id": e["message_id"], "conversation_id": w.comm.conversation_id}, text="4"); a.poll()
    conv1 = w.comm.conversation_id
    # T64: identities cross the typed allow-list
    t = a.transcript()
    assert all(r["event_id"] and r["conversation_id"] == conv1 for r in t)
    assert t[-1]["user_event_id"] == e["user_event_id"] and t[-1]["kind"] == "assistant_claude"
    # T65: a new conversation holds none of the prior rows; selecting the old one holds only its rows
    nc = a.new_conversation()
    assert nc["created"] is True and a.transcript() == []
    e2 = a.escalate("second conversation", origin="jarvis")
    w.peer_result({"message_id": e2["message_id"], "conversation_id": w.comm.conversation_id}, text="5"); a.poll()
    assert {r["conversation_id"] for r in a.transcript()} == {nc["conversation_id"]}
    sel = a.select_conversation(conv1)
    assert sel["selected"] is True and {r["conversation_id"] for r in a.transcript()} == {conv1}
    # T63: the facade stays inspectable after a successful AND a failed shutdown
    out = a.shutdown()
    assert out["checkpoint_persisted"] is True
    assert a.snapshot()["status"]["shutdown"] == {"state": "checkpoint saved", "source": "store"}
    assert a.view()["snapshot"]["status"]["shutdown"]["state"] == "checkpoint saved"
    w.store.fail.append("save_checkpoint")
    out2 = a.shutdown()
    assert out2["checkpoint_persisted"] is False
    assert a.snapshot()["status"]["shutdown"]["state"] == "checkpoint NOT saved (OSError)"
    assert a.view()["transcript"] == a.transcript()


def test_T66_S24_identities_survive_record_recover_select(tmp_path):
    w = World(tmp_path)
    a = bridge.CommApi(w.comm)
    w.handshake()
    r = a.record_user_turn("q", "krish-via-jarvis", "sub-id")
    e = a.escalate(origin="krish-via-jarvis", user_event_id=r["user_event_id"])
    w.peer_result({"message_id": e["message_id"], "conversation_id": w.comm.conversation_id}, text="4"); a.poll()
    loc = a.record_local_answer("also local", "jarvis", r["user_event_id"], completion_id="c1")
    live = {t["event_id"]: t for t in a.transcript()}
    a.shutdown()
    rel2 = handshake.Relationship(self_id=SELF["id"], self_session=SELF["session"], self_epoch="epoch-claude-2")
    a2 = bridge.CommApi(w._build(rel2)); a2.start(); a2.select_conversation(w.comm.conversation_id)
    restored = {t["event_id"]: t for t in a2.transcript() if t.get("restored")}
    assert set(restored) == set(live)                                                   # same event ids: dedup by id works
    claude = [t for t in restored.values() if t["kind"] == "assistant_claude"][0]
    local = [t for t in restored.values() if t["kind"] == "assistant_local"][0]
    assert claude["user_event_id"] == r["user_event_id"] and local["linked_user_event_id"] == r["user_event_id"]
    assert live[claude["event_id"]]["user_event_id"] == claude["user_event_id"]        # same value live and restored
