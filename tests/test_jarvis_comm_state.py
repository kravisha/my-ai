"""The live communication state machine, driven with fakes and counters.

T09 epoch binding, T10 wrong reply, T11 busy, T12 stop, T13 seam order and persisted:false,
T14 status sources, T17 restart, T18 checkpoint failure (spoken once), T19 restart after T18,
T20 counter recovery, T21 no-op adapter. Per Arya 5825662233/5825724716 these exercise the
REAL state machine with fake send and speech counters, including a repeated late reply and a
restart; nothing here touches a network, a process, audio or a UI.
"""

from __future__ import annotations

import uuid

import pytest

from jarvis_voice.comm import entry as entry_mod, handshake, ledger as ledger_mod, outbox as outbox_mod
from jarvis_voice.comm import plane_local, publisher as pub_mod, reader as reader_mod, state as state_mod
from jarvis_voice.comm import status as status_mod, storage
from tests.test_jarvis_comm_support import *  # noqa: F401,F403


class World:
    """One participant (the Jarvis side, the one that escalates and speaks) over a local spool,
    with a fake peer (the existing Claude) that we script by appending entries to the same spool."""

    def __init__(self, tmp_path, store=None, epoch=SELF["epoch"]):
        self.clock = FakeClock()
        self.spool = tmp_path / "spool.md"
        self.root = tmp_path
        self.speaker = FakeSpeaker()
        self.display = FakeDisplay()
        self.store = store if store is not None else FakeStore()
        self.rel = handshake.Relationship(self_id=SELF["id"], self_session=SELF["session"], self_epoch=epoch)
        self.comm = self._build(self.rel)
        self.peer_seq = 0

    def _build(self, rel):
        plane = plane_local.LocalSpoolPlane(self.spool)
        ob = outbox_mod.Outbox(self.root / "outbox")
        lg = ledger_mod.Ledger(self.root / "ledger.json")
        pub = pub_mod.Publisher(plane, ob, lg, sleep=self.clock.sleep, clock=self.clock)
        rd = reader_mod.Reader(plane, lg, self_id=rel.self_id, clock=self.clock)
        return state_mod.Comm(relationship=rel, publisher=pub, reader=rd, store=self.store,
                              speaker=self.speaker, display=self.display, clock=self.clock,
                              owner=OWNER, grant_id=GRANT[0], grant_revision=GRANT[1])

    # -- the scripted peer --------------------------------------------------------------
    def peer_append(self, **kw):
        self.peer_seq += 1
        e = peer_entry(self.clock, sequence=self.peer_seq, **kw)
        with open(self.spool, "a", encoding="utf-8", newline="\n") as f:
            f.write(entry_mod.render(e))
        return e

    def peer_check_in(self, epoch=PEER["epoch"], to_epoch=SELF["epoch"], reply_to=()):
        return self.peer_append(type_="CHECK_IN", body="jarvis check-in", epoch=epoch, reply_to=reply_to,
                                evidence=[{"kind": "peer_epoch", "value": to_epoch}])

    def handshake(self):
        my = self.comm.check_in()                     # we publish CHECK_IN
        theirs = self.peer_check_in(reply_to=[my["message_id"]])
        self.comm.poll()                              # we read theirs and bind
        assert self.comm.relationship.bound
        return my, theirs

    def peer_result(self, request, text="4", epoch=PEER["epoch"], conversation_id=None, to=None, type_="RESULT",
                    to_epoch=None):
        return self.peer_append(type_=type_, body=text, reply_to=[request["message_id"]],
                                conversation_id=conversation_id or request["conversation_id"], epoch=epoch,
                                to=to, evidence=[{"kind": "peer_epoch", "value": to_epoch or self.comm.relationship.self_epoch}])


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


# ---------------------------------------------------------------- handshake / T09
def test_handshake_binds_both_epochs_and_a_stale_check_in_cannot_rebind(w):
    my, theirs = w.handshake()
    rel = w.comm.relationship
    assert (rel.peer_id, rel.peer_epoch) == (PEER["id"], PEER["epoch"])
    # a CHECK_IN from an old Jarvis epoch, addressed to an old Claude epoch, does not rebind the current peer
    w.peer_check_in(epoch="epoch-jarvis-0", to_epoch="epoch-claude-0", reply_to=[my["message_id"]])
    w.comm.poll()
    assert rel.peer_epoch == PEER["epoch"]
    assert any(d.get("event") == "check_in_refused" for d in w.display.shown)
    # a CHECK_IN for the current Claude epoch but not replying to our current CHECK_IN is refused too
    w.peer_check_in(epoch="epoch-jarvis-2", to_epoch=SELF["epoch"], reply_to=[str(uuid.uuid4())])
    w.comm.poll()
    assert rel.peer_epoch == PEER["epoch"]


def test_T09_old_epoch_reply_is_stale_unresolved_never_spoken(w):
    w.handshake()
    req = w.comm.escalate("what is 2 plus 2?", origin="krish-via-jarvis")
    w.peer_result(req, text="4 from an old session", epoch="epoch-jarvis-0")
    w.comm.poll()
    assert w.speaker.spoken == []
    assert w.comm.status.get("request") == "waiting"
    assert w.comm.pending is not None
    assert w.comm.stale[0]["reason"] == "epoch"


# ---------------------------------------------------------------- T10
def test_T10_wrong_conversation_recipient_or_reply_to_is_refused_and_recorded(w):
    w.handshake()
    req = w.comm.escalate("q", origin="krish-via-jarvis")
    w.peer_result(req, text="wrong conv", conversation_id=str(uuid.uuid4()))
    w.peer_result(req, text="wrong recipient", to=["someone-else"])
    other = w.peer_append(type_="RESULT", body="unrelated reply", reply_to=[str(uuid.uuid4())], conversation_id=req["conversation_id"])
    w.comm.poll()
    assert w.speaker.spoken == []
    reasons = sorted(s["reason"] for s in w.comm.stale)
    assert reasons == ["conversation", "recipient", "reply_to"]
    assert w.comm.pending["message_id"] == req["message_id"]
    # then the right one arrives and is the current answer, spoken once
    w.peer_result(req, text="4")
    w.comm.poll()
    assert w.speaker.spoken == ["4"] and w.comm.pending is None


# ---------------------------------------------------------------- T11
def test_T11_second_escalation_while_pending_is_busy_and_not_sent(w):
    w.handshake()
    r1 = w.comm.escalate("first", origin="krish-via-jarvis")
    r2 = w.comm.escalate("second", origin="krish-via-jarvis")
    assert r1["sent"] is True and r2["sent"] is False and r2["reason"] == "busy"
    assert w.comm.status.get("request") == "delivered"   # the first request's state is untouched by the refusal
    assert w.spool.read_text(encoding="utf-8").count('"type": "QUESTION"') == 1
    assert w.comm.status.get("busy") == "busy"


# ---------------------------------------------------------------- T12
def test_T12_local_stop_suppresses_later_playback_keeps_transcript_and_needs_cancel_ack_for_remote(w):
    w.handshake()
    req = w.comm.escalate("q", origin="krish-via-jarvis")
    seen = {}
    w.speaker.stop_hook = lambda: seen.setdefault("generation_at_stop", w.comm.speech.cancel_generation)
    w.comm.stop()
    assert w.speaker.stopped == 1
    assert seen["generation_at_stop"] == 1                      # tokens invalidated BEFORE speaker.stop
    assert w.comm.status.get("request") == "cancelled"
    assert w.comm.status.source("request") == "local_stop"
    assert w.comm.status.get("remote_cancel") == "unconfirmed"
    assert '"type": "CANCEL_REQUEST"' in w.spool.read_text(encoding="utf-8")
    # Dev 5825971357: the request stays an outstanding cancel_requested item in the checkpoint until CANCEL_ACK,
    # while the live one-consultation slot is free
    assert w.comm.pending is None
    cp = w.store.checkpoints[req["conversation_id"]]
    assert cp["pending"] == [{"request_id": req["message_id"], "epoch": SELF["epoch"], "state": "cancel_requested", "turn_sequence": 2}]  # 1 = the user turn (G1)
    assert w.comm.escalate("another", origin="krish-via-jarvis")["sent"] is True
    # late reply: stored as evidence, displayed as late, never spoken
    w.peer_result(req, text="late 4")
    w.comm.poll()
    assert w.speaker.spoken == []
    assert any(t.get("payload", {}).get("text") == "late 4" and t["payload"].get("late_for_cancelled_request") for t in w.comm.transcript)
    # repeated late reply (same id and content) is a duplicate, still not spoken
    w.comm.poll()
    assert w.speaker.spoken == []
    # remote cancellation only confirmed by CANCEL_ACK; the outstanding item then leaves the checkpoint
    w.peer_result(req, text="stopped", type_="CANCEL_ACK")
    w.comm.poll()
    assert w.comm.status.get("remote_cancel") == "confirmed"
    assert all(p["request_id"] != req["message_id"] for p in w.store.checkpoints[req["conversation_id"]]["pending"])


# ---------------------------------------------------------------- T13
def test_T13_seam_call_order_and_persisted_false_on_raise(w):
    w.handshake()
    req = w.comm.escalate("q", origin="krish-via-jarvis")
    w.store.fail.append("save_completed_turn")
    w.peer_result(req, text="4")
    w.comm.poll()
    assert w.store.calls[-1] == "save_completed_turn"          # checkpoint NOT called after the raise
    assert w.comm.status.get("persisted") == "turn=no checkpoint=no (OSError)"
    assert w.speaker.spoken == ["4"]                            # the answer arrived; that is a fact
    assert w.store.calls.count("save_completed_turn") == 2      # the user turn (G1) and the failed Claude turn; no retry
    last = w.comm.transcript[-1]
    assert last["persisted"] == {"turn": False, "checkpoint": False, "error": "OSError"}


def test_T13_order_is_terminal_save_turn_state_checkpoint_display_speech(w):
    w.handshake()
    req = w.comm.escalate("q", origin="krish-via-jarvis")
    w.peer_result(req, text="4")
    w.comm.poll()
    order = [x for x in w.comm.trace if x in ("terminal_check", "save_completed_turn", "live_state", "save_checkpoint", "display", "speech")]
    assert order == ["terminal_check", "save_completed_turn", "live_state", "save_checkpoint", "display", "speech"]


def test_T13_wrong_return_shape_is_a_contract_error_not_success(w):
    w.handshake()
    w.store.bad_shape.append("save_checkpoint")
    req = w.comm.escalate("q", origin="krish-via-jarvis")
    w.peer_result(req, text="4")
    w.comm.poll()
    assert w.comm.status.get("persisted") == "turn=yes checkpoint=no (contract_error)"
    assert w.comm.transcript[-1]["persisted"]["checkpoint"] is False


# ---------------------------------------------------------------- T14
def test_T14_each_status_comes_only_from_its_source_and_silence_is_waiting(w):
    w.handshake()
    st = w.comm.status
    req = w.comm.escalate("q", origin="krish-via-jarvis")
    assert st.get("request") == "delivered" and st.source("request") == "readback"
    for _ in range(3):
        w.comm.poll()
    assert st.get("request") == "waiting" and st.source("request") == "silence"
    w.peer_append(type_="ACK", body="read", reply_to=[req["message_id"]], conversation_id=req["conversation_id"])
    w.comm.poll()
    assert st.get("request") == "read" and st.source("request") == "peer_ack"
    w.peer_append(type_="PROGRESS", body="approval-needed: tool use", reply_to=[req["message_id"]], conversation_id=req["conversation_id"],
                  evidence=[{"kind": "client_state", "value": "approval-needed"}])
    w.comm.poll()
    assert st.get("request") == "approval-needed" and st.source("request") == "peer_report"
    with pytest.raises(status_mod.StatusError):
        st.set("request", "limit", source="guess")   # a limit state without a participant/client report is refused
    assert st.snapshot()["storage"] == {"state": "durable (fake-file)", "source": "capabilities"}


# ---------------------------------------------------------------- T17
def test_T17_restart_recovers_pending_without_replay_and_lost_cursor_rereads_with_dedup(w):
    w.handshake()
    req = w.comm.escalate("q", origin="krish-via-jarvis")
    # simulate process death: a brand-new Comm on the same root, new epoch
    rel2 = handshake.Relationship(self_id=SELF["id"], self_session=SELF["session"], self_epoch="epoch-claude-2")
    comm2 = w._build(rel2)
    rep = comm2.recover()
    assert rep["previous_epoch"] == SELF["epoch"]
    assert [p["request_id"] for p in rep["stale_unresolved"]] == [req["message_id"]]
    assert comm2.pending is None                                  # never re-sent
    assert w.spool.read_text(encoding="utf-8").count('"type": "QUESTION"') == 1
    assert w.speaker.spoken == []
    # lost cursor: full reread finds every entry once
    comm2.reader.ledger.forget_cursor()
    r = comm2.poll()
    assert r["reread"] is True
    assert sorted(comm2.reader.ledger.accounted_ids()) == sorted(comm2.reader.ledger.accounted_ids())  # stable
    assert len(comm2.reader.ledger.accounted_ids()) == len(set(comm2.reader.ledger.accounted_ids()))


# ---------------------------------------------------------------- T18 / T19
def test_T18_checkpoint_failure_displays_and_speaks_once_with_split_persisted_status(w):
    w.handshake()
    req = w.comm.escalate("q", origin="krish-via-jarvis")
    w.store.fail.append("save_checkpoint")
    w.peer_result(req, text="4")
    w.comm.poll()
    assert w.speaker.spoken == ["4"]
    assert w.comm.status.get("persisted") == "turn=yes checkpoint=no (OSError)"
    assert w.comm.pending is None                                      # cleared in memory
    assert w.store.checkpoints[req["conversation_id"]]["pending"][0]["request_id"] == req["message_id"]  # on disk still pending
    # repeated late reply after the terminal: duplicate, still exactly one emission
    w.peer_result(req, text="4")
    w.comm.poll()
    w.comm.poll()
    assert w.speaker.spoken == ["4"]


def test_T19_restart_after_T18_resolves_by_history_no_resend_no_speech_speech_unknown(w):
    w.handshake()
    req = w.comm.escalate("q", origin="krish-via-jarvis")
    w.store.fail.append("save_checkpoint")
    w.peer_result(req, text="4")
    w.comm.poll()
    spoken_before = list(w.speaker.spoken)
    rel2 = handshake.Relationship(self_id=SELF["id"], self_session=SELF["session"], self_epoch="epoch-claude-2")
    comm2 = w._build(rel2)
    rep = comm2.recover()
    resolved = [p for p in comm2.recovery["pending"] if p["request_id"] == req["message_id"]]
    assert resolved and resolved[0]["state"] == "resolved_by_history"
    assert [t for t in comm2.transcript if t.get("restored")] == []          # nothing shown until selected
    assert comm2.select_conversation(req["conversation_id"])["selected"] is True
    restored = [t for t in comm2.transcript if t.get("restored") and t["kind"] == "assistant_claude"]
    assert restored and restored[-1]["payload"]["text"] == "4" and restored[-1]["speech"] == "unknown"
    assert w.speaker.spoken == spoken_before                         # nothing replayed
    assert w.spool.read_text(encoding="utf-8").count('"type": "QUESTION"') == 1   # nothing re-sent
    # a late reply for the old request after restart is evidence only
    w.peer_result(req, text="4 again", epoch=PEER["epoch"], to_epoch=SELF["epoch"])
    comm2.poll()
    assert w.speaker.spoken == spoken_before


# ---------------------------------------------------------------- T20
def test_T20_counter_recovery_takes_the_larger_and_displays_disagreement_gap_reason_unknown(tmp_path):
    store = FakeStore()
    conv = str(uuid.uuid4())
    store.turns[conv] = [{"event_id": str(uuid.uuid4()), "conversation_id": conv, "turn_id": str(uuid.uuid4()),
                          "request_id": None, "sequence": 5, "epoch": "epoch-claude-1", "author": SELF["id"],
                          "timestamp": "2026-09-24T22:00:00-04:00", "kind": "user", "terminal_state": "completed",
                          "payload": {"text": "hello"}, "schema_version": "1.0"}]
    store.checkpoints[conv] = {"schema_version": "1.0", "conversation_id": conv, "checkpoint_seq": 1,
                               "epoch": "epoch-claude-1", "last_sequence": 3,
                               "pending": [{"request_id": str(uuid.uuid4()), "epoch": "epoch-claude-1",
                                            "state": "awaiting_reply", "turn_sequence": 7}]}
    w = World(tmp_path, store=store, epoch="epoch-claude-2")
    w.comm.recover(conversation_id=conv)
    assert w.comm.turn_sequence(conv) == 7
    rec = w.comm.recovery
    assert rec["counter"] == {"history_high_water": 5, "checkpoint_last_sequence": 3, "pending_max_turn_sequence": 7,
                              "resumed_from": 7, "disagreement": True}
    assert rec["gaps"] == [{"conversation_id": conv, "missing": [1, 2, 3, 4], "reason": "unknown"}]
    assert any(d.get("event") == "counter_disagreement" for d in w.display.shown)
    # missing checkpoint: history alone, pending unknown
    del store.checkpoints[conv]
    w2 = World(tmp_path / "again", store=store, epoch="epoch-claude-3")
    w2.comm.recover(conversation_id=conv)
    assert w2.comm.turn_sequence(conv) == 5
    assert w2.comm.recovery["pending_state"] == "unknown (checkpoint unavailable)"


# ---------------------------------------------------------------- T21
def test_T21_noop_adapter_reports_non_durable_and_persisted_is_never_true(tmp_path):
    w = World(tmp_path, store=storage.NoopStore())
    w.handshake()
    assert w.comm.status.get("storage") == "non-durable (noop-demo)"
    req = w.comm.escalate("q", origin="krish-via-jarvis")
    w.peer_result(req, text="4")
    w.comm.poll()
    assert w.speaker.spoken == ["4"]
    assert w.comm.status.get("persisted") == "turn=no checkpoint=no (non-durable)"
    assert w.comm.transcript[-1]["persisted"] == {"turn": False, "checkpoint": False, "error": None}


def test_T21_no_store_at_all_is_the_same_non_durable_status(tmp_path):
    w = World(tmp_path, store=storage.NoopStore())
    w.comm.store = None
    w.handshake()
    assert w.comm.status.get("storage") == "non-durable (absent)"
    req = w.comm.escalate("q", origin="krish-via-jarvis")
    w.peer_result(req, text="4")
    w.comm.poll()
    assert w.speaker.spoken == ["4"] and w.comm.status.get("persisted") == "turn=no checkpoint=no (non-durable)"


# ---------------------------------------------------------------- the demo route (Arya 5825724716)
def test_spool_route_request_id_and_text_are_read_and_the_matching_reply_is_asserted(tmp_path):
    """Jarvis side escalates through the spool; the 'existing Claude' side is a second Comm over the SAME file
    that reads the request id and text and replies. Watcher exit is not used as proof here: the assertion is on
    the id, the text and the matching reply."""
    jarvis = World(tmp_path / "j")
    claude_rel = handshake.Relationship(self_id="claude-deploy-local-2", self_session="s2", self_epoch="ec")
    # both sides share ONE spool file
    jarvis.spool = tmp_path / "shared-spool.md"
    jarvis.comm = jarvis._build(jarvis.rel)
    claude = World(tmp_path / "c")
    claude.spool = jarvis.spool
    claude.rel = claude_rel
    claude.comm = claude._build(claude_rel)
    # handshake: Jarvis CHECK_IN, Claude CHECK_IN reply
    j_ci = jarvis.comm.check_in(peer_id="claude-deploy-local-2")
    claude.comm.poll()
    c_ci = claude.comm.check_in(peer_id=SELF["id"], reply_to=[j_ci["message_id"]])
    jarvis.comm.poll()
    assert jarvis.comm.relationship.bound and claude.comm.relationship.bound
    req = jarvis.comm.escalate("what is 2 plus 2?", origin="krish-via-jarvis")
    got = claude.comm.poll()
    q = [e for e in got["new_entries"] if e["type"] == "QUESTION"]
    assert len(q) == 1 and q[0]["message_id"] == req["message_id"] and q[0]["body"] == "what is 2 plus 2?"
    claude.comm.reply(q[0], "4")
    jarvis.comm.poll()
    assert jarvis.speaker.spoken == ["4"]
    assert jarvis.comm.transcript[-1]["request_id"] == req["message_id"]
    assert jarvis.comm.transcript[-1]["responder"] == "claude-deploy-local-2"


# ---------------------------------------------------------------- T34 store read containers are dicts (Dev 5826088544)
def test_T34_non_dict_read_results_are_a_typed_store_contract_error_not_a_crash(tmp_path):
    import dataclasses

    @dataclasses.dataclass
    class RecoveryReport:
        previous_epoch: str | None = None
        stale_unresolved: list = dataclasses.field(default_factory=list)
        still_pending: list = dataclasses.field(default_factory=list)

    class DataclassStore(storage.NoopStore):
        def recover(self, current_epoch):
            return RecoveryReport()

    w = World(tmp_path, store=DataclassStore())
    rep = w.comm.recover()
    assert w.comm.recovery["pending_state"] == "unknown (store contract error)"
    assert w.comm.recovery["store_contract_errors"] == ["recover: contract_error (returned RecoveryReport, expected dict)"]
    assert any(d.get("event") == "store_contract_error" for d in w.display.shown)
    assert rep["warnings"] == w.comm.recovery["store_contract_errors"]

    class RaisingLoads(storage.NoopStore):
        def recover(self, current_epoch):
            return {"previous_epoch": None, "stale_unresolved": [{"request_id": "r", "epoch": "old", "conversation_id": "c"}],
                    "still_pending": [], "warnings": []}
        def load_history(self, conversation_id, since_sequence=0):
            raise RuntimeError("disk gone")
        def load_checkpoint(self, conversation_id):
            return ("not", "a", "dict")

    w2 = World(tmp_path / "b", store=RaisingLoads())
    w2.comm.recover()
    assert w2.comm.recovery["store_contract_errors"] == ["load_history: RuntimeError", "load_checkpoint: contract_error (returned tuple, expected dict)"]
    assert w2.comm.recovery["pending_state"] == "unknown (store contract error)"


# ---------------------------------------------------------------- T35/T36 provenance on the wire (Krish 5826141255)
def test_T35_origin_is_mandatory_and_never_defaulted_to_krish(w):
    w.handshake()
    r = w.comm.escalate("what time is it?")
    assert r["sent"] is False and r["reason"].startswith("contract_error")
    assert '"type": "QUESTION"' not in w.spool.read_text(encoding="utf-8")
    r2 = w.comm.escalate("what time is it?", origin="not-a-known-origin")
    assert r2["sent"] is False
    req = w.comm.escalate("what time is it?", origin="jarvis")
    assert req["sent"] is True
    assert {"kind": "origin", "value": "jarvis"} in req["evidence"]
    assert w.comm.transcript[-1]["origin"] == "jarvis"   # the user record carries who asked


def test_T36_reply_echoes_the_origin_it_answered_and_the_transcript_shows_both(tmp_path):
    jarvis = World(tmp_path / "j")
    claude_rel = handshake.Relationship(self_id="claude-deploy-local-2", self_session="s2", self_epoch="ec")
    jarvis.spool = tmp_path / "shared.md"
    jarvis.comm = jarvis._build(jarvis.rel)
    claude = World(tmp_path / "c")
    claude.spool = jarvis.spool
    claude.rel = claude_rel
    claude.comm = claude._build(claude_rel)
    j_ci = jarvis.comm.check_in(peer_id="claude-deploy-local-2")
    claude.comm.poll()
    claude.comm.check_in(peer_id=SELF["id"], reply_to=[j_ci["message_id"]])
    jarvis.comm.poll()
    req = jarvis.comm.escalate("Krish says: what is 2 plus 2?", origin="krish-via-jarvis")
    got = claude.comm.poll()
    q = [e for e in got["new_entries"] if e["type"] == "QUESTION"][0]
    assert state_mod.Comm.origin_of(q) == "krish-via-jarvis"
    out = claude.comm.reply(q, "4")
    assert {"kind": "origin", "value": "krish-via-jarvis"} in out["evidence"]
    jarvis.comm.poll()
    rec = jarvis.comm.transcript[-1]
    assert rec["origin"] == "krish-via-jarvis" and rec["origin_echoed"] == "krish-via-jarvis" and rec["payload"]["text"] == "4"


# ---------------------------------------------------------------- T50-T53 G1-G3 (Dev 5826392645) + shutdown/reopen
def test_T50_G1_user_turn_and_local_answer_are_saved_with_provenance_and_show_persisted_truthfully(w):
    w.handshake()
    req = w.comm.escalate("what is 2 plus 2?", origin="krish-via-jarvis")
    conv = req["conversation_id"]
    kinds = [t["kind"] for t in w.store.turns[conv]]
    pl = w.store.turns[conv][0]["payload"]
    assert kinds == ["user"] and pl["text"] == "what is 2 plus 2?" and pl["origin"] == "krish-via-jarvis" and pl["submission_id"].startswith("auto-")
    assert w.comm.transcript[0]["persisted"]["turn"] is True
    w.peer_result(req, text="4"); w.comm.poll()
    loc = w.comm.record_local_answer("it is late", origin="jarvis")
    assert [t["kind"] for t in w.store.turns[conv]] == ["user", "assistant_claude", "assistant_local"]
    assert loc["persisted"]["turn"] is True and loc["sequence"] == 3
    # save failure on a user turn is visible on that record, never claimed saved
    w.store.fail.append("save_completed_turn")
    w.comm.escalate("again", origin="jarvis")
    assert w.comm.transcript[-1]["kind"] == "user" and w.comm.transcript[-1]["persisted"] == {"turn": False, "checkpoint": False, "error": "OSError"}


def test_T51_G2_stored_claude_turn_carries_origin_and_origin_echoed_inside_the_payload(w):
    w.handshake()
    req = w.comm.escalate("q", origin="jarvis")
    w.peer_result(req, text="4", ); w.comm.poll()
    stored = [t for t in w.store.turns[req["conversation_id"]] if t["kind"] == "assistant_claude"][0]
    assert stored["payload"]["origin"] == "jarvis"
    assert "origin_echoed" in stored["payload"]        # echoed value is whatever the peer sent (None here: scripted peer)


def test_T52_G3_late_reply_after_restart_is_persisted_as_late_for_stale_request_never_spoken(w):
    w.handshake()
    req = w.comm.escalate("q", origin="krish-via-jarvis")
    w.peer_result(req, text="4"); w.comm.poll()
    spoken = list(w.speaker.spoken)
    rel2 = handshake.Relationship(self_id=SELF["id"], self_session=SELF["session"], self_epoch="epoch-claude-2")
    comm2 = w._build(rel2)
    comm2.recover()
    assert req["message_id"] in comm2.requests and comm2.requests[req["message_id"]]["restored"] is True
    # bind the peer again in the new epoch, then a late reply for the old request arrives
    my = comm2.check_in(); w.peer_check_in(reply_to=[my["message_id"]], to_epoch="epoch-claude-2"); comm2.poll()
    w.peer_result(req, text="4 again", to_epoch="epoch-claude-2"); comm2.poll()
    late = [t for t in w.store.turns[req["conversation_id"]] if (t.get("payload") or {}).get("late_for_stale_request")]
    assert len(late) == 1 and late[0]["request_id"] == req["message_id"] and late[0]["payload"]["text"] == "4 again"
    assert w.speaker.spoken == spoken


def test_T53_shutdown_saves_a_final_checkpoint_or_reports_it_was_not_saved(w):
    w.handshake()
    w.comm.escalate("q", origin="krish-via-jarvis")
    out = w.comm.shutdown()
    conv = w.comm.conversation_id
    assert out["checkpoint_persisted"] is True and w.store.checkpoints[conv]["closed_cleanly"] is True
    assert w.comm.status.get("shutdown") == "checkpoint saved"
    w.store.fail.append("save_checkpoint")
    out2 = w.comm.shutdown()
    assert out2["checkpoint_persisted"] is False and out2["error"] == "OSError"
    assert w.comm.status.get("shutdown") == "checkpoint NOT saved (OSError)"
