"""The live communication state machine. Single writer of transport state and the only
caller of the persistence seam.

One pending consultation at a time. Reply acceptance requires reply_to = our request,
same conversation, bound epochs both ways, recipient = us, sender = the bound peer.
Terminal order, one thread, no queue: terminal check -> save_completed_turn -> live state
-> save_checkpoint -> display -> speech (at most one emission; never for a cancelled
request; never on restore). Persistence results are consumed explicitly: a missing or
non-boolean ``persisted`` is a contract error, never success. A raise is an error type in
the status line, no retry.
"""

from __future__ import annotations

import uuid

from . import canon, entry as entry_mod, handshake as hs, plane as P, speech as speech_mod, status as status_mod, storage

def recovery_category(reason: str) -> str:
    """One vocabulary for the status line, derived from the unresolved reason text (shared with tests)."""
    if "contract_error" in reason or reason.split(":")[0] in ("recover", "load_history", "load_checkpoint"):
        return "store contract error"
    if "frozen_unsupported_major" in reason:
        return "frozen unsupported major"
    if reason.startswith("pending_state"):
        return "checkpoint unavailable"
    if reason.startswith("still_pending"):
        return "still pending"
    if reason.startswith("pending "):
        return "pending unknown"
    return "unknown"


REPLY_TYPES = {"RESULT", "ERROR", "CANCEL_ACK", "ACK", "PROGRESS", "BLOCKER", "ACCEPT", "OBJECTION"}
INBOUND_WORK = {"QUESTION", "TASK_ASSIGN", "TASK_REQUEST"}


class Comm:
    def __init__(self, *, relationship: hs.Relationship, publisher, reader, store, speaker, display, clock,
                 owner: str, grant_id: str, grant_revision: int):
        self.relationship = relationship
        self.publisher = publisher
        self.reader = reader
        self.store = store
        self.speaker = speaker
        self.display = display
        self.clock = clock
        self.owner = owner
        self.grant_id = grant_id
        self.grant_revision = grant_revision
        self.status = status_mod.Status()
        self.pending: dict | None = None
        self.requests: dict[str, dict] = {}
        self.stale: list[dict] = []
        self.transcript: list[dict] = []
        self.inbox: list[dict] = []
        self.trace: list[str] = []
        self.recovery: dict = {}
        self.conversation_id: str | None = None
        self._turn_seq: dict[str, int] = {}
        self._msg_seq = 0
        self.speech = speech_mod.SpeechLedger(clock)
        # Recovery visibility (UI executor repro, Arya 5826206681): not_run | ok | unresolved. A store
        # contract error during recover() blocks new escalations until a clean recover() happens.
        self.recovery_state = "not_run"
        self.recovery_errors: list[str] = []
        self.submissions: dict[str, dict] = {}      # submission_id -> record_user_turn result (idempotency)
        self.user_events: dict[str, dict] = {}      # user_event_id -> transcript record
        self.local_answers: dict[str, dict] = {}    # user_event_id -> the one stored local answer
        # Dedup survives a checkpoint failure too: my transport ledger keeps the last submission ids (Arya 5826487015).
        for sid in self.reader.ledger.submissions():
            self.submissions.setdefault(sid, {"user_event_id": None, "sequence": None, "persisted": {"turn": None, "error": None},
                                              "duplicate": True, "conversation_id": None, "restored": True})
        # Local Stop keeps the request as an outstanding remote cancel until CANCEL_ACK (Dev 5825971357);
        # it lives here, not in the one-consultation slot, so a new escalation is not blocked forever.
        self.cancel_outstanding: dict[str, dict] = {}
        self._store_status()

    # ------------------------------------------------------------------ helpers
    def _store_status(self) -> None:
        if self.store is None:
            self.status.set("storage", "non-durable (absent)", source="capabilities")
            return
        caps = self.store.capabilities()
        durable = isinstance(caps, dict) and caps.get("durable") is True
        name = caps.get("storage", "?") if isinstance(caps, dict) else "?"
        self.status.set("storage", f"{'durable' if durable else 'non-durable'} ({name})", source="capabilities")

    def _durable(self) -> bool:
        return self.status.get("storage", ).startswith("durable")

    def _recovery_status_text(self) -> str:
        """The status-line projection of recovery_state/recovery_errors; the only place it is computed."""
        if self.recovery_state == "unresolved":
            return f"unresolved ({recovery_category(self.recovery_errors[0]) if self.recovery_errors else 'unknown'})"
        return self.recovery_state

    def turn_sequence(self, conversation_id: str) -> int:
        return self._turn_seq.get(conversation_id, 0)

    def _next_turn(self, conversation_id: str) -> int:
        self._turn_seq[conversation_id] = self._turn_seq.get(conversation_id, 0) + 1
        return self._turn_seq[conversation_id]

    def _entry(self, type_: str, body: str, *, to: list[str], reply_to=(), conversation_id: str | None = None,
               evidence=None) -> dict:
        self._msg_seq += 1
        rel = self.relationship
        ev = list(evidence or [])
        if rel.peer_epoch and not any(isinstance(x, dict) and x.get("kind") == "peer_epoch" for x in ev):
            ev.append({"kind": "peer_epoch", "value": rel.peer_epoch})
        return entry_mod.make_entry(
            conversation_id=conversation_id or self.conversation_id or str(uuid.uuid4()), sequence=self._msg_seq,
            created_at=self.clock.iso(), from_=rel.self_id, session_id=rel.self_session, epoch=rel.self_epoch,
            to=to, owner=self.owner, grant_id=self.grant_id, grant_revision=self.grant_revision, type_=type_,
            body=body, reply_to=list(reply_to), evidence=ev)

    def _checkpoint(self, *, closed_cleanly: bool = False) -> tuple[bool, str | None]:
        """Pending-state transition or completed turn: save the checkpoint, consume the result."""
        if self.store is None or self.conversation_id is None:
            return False, None
        cp = {"schema_version": "1.0", "conversation_id": self.conversation_id, "epoch": self.relationship.self_epoch,
              "written_at": self.clock.iso(), "last_sequence": self.turn_sequence(self.conversation_id),
              "closed_cleanly": closed_cleanly,
              "submissions": list(self.submissions)[-self.SUBMISSIONS_KEPT:],   # idempotency survives a restart
              "pending": ([{"request_id": self.pending["message_id"], "epoch": self.pending["epoch"],
                            "state": self.pending["state"], "turn_sequence": self.pending["turn_sequence"]}]
                          if self.pending else []) +
                         [{"request_id": r["message_id"], "epoch": r["epoch"], "state": "cancel_requested",
                           "turn_sequence": r["turn_sequence"]} for r in self.cancel_outstanding.values()],
              "important_state": {"peer_id": self.relationship.peer_id, "peer_epoch": self.relationship.peer_epoch}}
        try:
            return storage.consume(self.store.save_checkpoint(self.conversation_id, cp))
        except Exception as e:  # noqa: BLE001 - the error TYPE goes to the status line, never its text
            return False, type(e).__name__

    # ------------------------------------------------------------------ handshake
    def check_in(self, *, peer_id: str | None = None, reply_to=()) -> dict:
        self._store_status()
        rel = self.relationship
        to = [peer_id or rel.peer_id or "unknown-peer"]
        e = self._entry("CHECK_IN", f"{rel.self_id} check-in; session {rel.self_session}; epoch {rel.self_epoch}",
                        to=to, reply_to=reply_to)
        r = self.publisher.publish(e)
        rel.my_check_in_id = e["message_id"]
        self.status.set("handshake", "check_in_published" if r.status == P.DELIVERED_VERIFIED else r.status, source="publisher")
        return e

    # ------------------------------------------------------------------ escalation
    ORIGINS = ("krish-via-jarvis", "jarvis")

    def escalate(self, text: str | None = None, *, origin: str | None = None, user_event_id: str | None = None,
                 submission_id: str | None = None, consultation_text: str | None = None) -> dict:
        """Provenance is mandatory (Krish 5826141255): the host states whether the utterance is
        Krish's, relayed by Jarvis, or Jarvis's own question. A missing or unknown origin is a
        contract error; nothing is ever attributed to Krish by default.
        The user's words are stored ONCE: pass `user_event_id` from record_user_turn to reuse it, or `text`
        (+ optional submission_id) to record-and-escalate atomically (Arya 5826453952)."""
        self._store_status()
        rel = self.relationship
        if origin not in self.ORIGINS:
            self.status.set("request", "error", source="publisher")
            self.display.show(event="origin_refused", origin=origin)
            return {"sent": False, "reason": "contract_error: origin must be one of " + "|".join(self.ORIGINS)}
        if self.recovery_state == "unresolved":
            self.status.set("request", "blocked", source="publisher")
            self.display.show(event="escalate_refused", reason="recovery_unresolved", errors=list(self.recovery_errors))
            return {"sent": False, "reason": "recovery_unresolved: " + "; ".join(self.recovery_errors)}
        # G1 (Dev 5826392645) + exact-once (Arya 5826453952): the user's turn is a completed turn of its own, stored once.
        if user_event_id is not None:
            user_rec = self.user_events.get(user_event_id)
            if user_rec is None:
                return {"sent": False, "reason": "contract_error: unknown user_event_id"}
            text = user_rec["payload"]["text"]
            if consultation_text is not None:
                if not isinstance(consultation_text, str) or not consultation_text.strip():
                    return {"sent": False, "reason": "contract_error: consultation_text must be a non-empty string"}
                text = consultation_text        # the envelope sent to Claude; the user's saved words stay untouched
        else:
            if not isinstance(text, str) or not text.strip():
                return {"sent": False, "reason": "contract_error: text or user_event_id required"}
            res = self.record_user_turn(text, origin, submission_id or f"auto-{uuid.uuid4()}")
            user_event_id = res.get("user_event_id")
            if res["duplicate"] and any(r.get("user_event_id") == user_event_id for r in self.requests.values()):
                return {"sent": False, "reason": "duplicate_submission", "user_event_id": user_event_id}
            if user_event_id is None:
                return {"sent": False, "reason": "contract_error: user turn not recorded", "persisted": res["persisted"]}
            if res["persisted"].get("error"):
                # Atomic record-then-publish (Dev S17): a user turn whose save FAILED is not consulted on; the
                # words are in the transcript as unsaved and the host shows that; non-durable storage is not a failure.
                self.status.set("request", "error", source="publisher")
                return {"sent": False, "reason": f"user_turn_not_persisted ({res['persisted']['error']})",
                        "user_event_id": user_event_id, "persisted": res["persisted"]}
        if not rel.bound:
            self.status.set("request", "error", source="publisher")
            return {"sent": False, "reason": "unbound"}
        if self.pending is not None:
            self.status.set("busy", "busy", source="local")
            self.display.show(event="busy", pending=self.pending["message_id"])
            return {"sent": False, "reason": "busy"}
        self.status.clear("busy")
        if self.conversation_id is None:
            self.conversation_id = str(uuid.uuid4())
        seq = self._next_turn(self.conversation_id)
        self.status.set("request", "local", source="local")
        e = self._entry("QUESTION", text, to=[rel.peer_id], conversation_id=self.conversation_id,
                        evidence=[{"kind": "origin", "value": origin}])
        self.status.set("request", "queued", source="outbox")
        r = self.publisher.publish(e)
        self.requests[e["message_id"]] = {"message_id": e["message_id"], "conversation_id": self.conversation_id,
                                          "turn_sequence": seq, "text": text, "epoch": rel.self_epoch,
                                          "state": "awaiting_reply", "cancelled": False, "origin": origin,
                                          "user_event_id": user_event_id,
                                          "consultation_text": text if consultation_text is not None else None}
        if r.status == P.DELIVERED_VERIFIED:
            self.status.set("request", "delivered", source="readback")
        elif r.status == P.DELIVERY_UNKNOWN:
            self.status.set("request", "publication-unknown", source="publisher")
        elif r.status == P.CONFLICT:
            self.status.set("request", "conflict", source="publisher")
        else:
            self.status.set("request", "blocked", source="publisher")
        self.pending = self.requests[e["message_id"]]
        self._checkpoint()
        self.display.show(event="escalated", message_id=e["message_id"], state=self.status.get("request"))
        return dict(e, sent=True, user_event_id=user_event_id)

    # ------------------------------------------------------------------ reading
    def poll(self) -> dict:
        r = self.reader.read()
        if r.status == "failed":
            self.status.set("transport", "error", source="reader")
            return {"status": "failed", "new_entries": [], "reread": r.reread}
        self.status.set("transport", "ok", source="reader")
        touched = False
        for e in r.new_entries:
            touched |= self._handle(e)
        if r.new_entries:
            self.reader.ack([e["message_id"] for e in r.new_entries])  # the actual read, with its own time
        if self.pending is not None and not touched and self.status.get("request") in ("delivered", "read", "accepted", "processing", "waiting"):
            self.status.set("request", "waiting", source="silence")
        return {"status": r.status, "new_entries": list(r.new_entries), "reread": r.reread,
                "conflicts": r.conflicts, "malformed": r.malformed}

    def _handle(self, e: dict) -> bool:
        """Returns True when the entry concerned the pending request."""
        rel = self.relationship
        if e["type"] == "CHECK_IN":
            ok, why = rel.bind(e)
            self.display.show(event="check_in_bound" if ok else "check_in_refused", message_id=e["message_id"], reason=why)
            if ok:
                self.status.set("handshake", "bound", source="reader")
            return False
        if not rel.bound:
            self.display.show(event="unbound_entry_ignored", message_id=e["message_id"])
            return False
        ok, why = rel.is_current(e)
        if not ok:
            self.stale.append({"message_id": e["message_id"], "reason": why, "type": e["type"]})
            self.display.show(event="stale_entry", message_id=e["message_id"], reason=why)
            return False
        if e["type"] in INBOUND_WORK:
            self.inbox.append(e)
            self.display.show(event="inbound", message_id=e["message_id"], type=e["type"])
            return False
        if e["type"] not in REPLY_TYPES:
            self.display.show(event="ignored_type", message_id=e["message_id"], type=e["type"])
            return False
        targets = [rid for rid in e.get("reply_to", []) if rid in self.requests]
        if not targets:
            self.stale.append({"message_id": e["message_id"], "reason": "reply_to", "type": e["type"]})
            return False
        if self.requests[targets[0]].get("restored"):
            # G3: a reply for a request that predates this epoch is persisted as late evidence, never current.
            self._late_reply(self.requests[targets[0]], e, flag="late_for_stale_request")
            return True
        req = self.requests[targets[0]]
        if e["conversation_id"] != req["conversation_id"]:
            self.stale.append({"message_id": e["message_id"], "reason": "conversation", "type": e["type"]})
            return False
        is_pending = self.pending is not None and self.pending["message_id"] == req["message_id"]
        if e["type"] == "CANCEL_ACK":
            self.status.set("remote_cancel", "confirmed", source="peer_ack")
            req["remote_cancel"] = "confirmed"
            if req["message_id"] in self.cancel_outstanding:
                del self.cancel_outstanding[req["message_id"]]
                self._checkpoint()
            return True
        if req["state"] != "awaiting_reply" or not is_pending:
            self._late_reply(req, e)
            return True
        if e["type"] == "ACK":
            self.status.set("request", "read", source="peer_ack")
            return True
        if e["type"] in ("PROGRESS", "BLOCKER", "ACCEPT", "OBJECTION"):
            client_state = None
            for ev in e.get("evidence", []):
                if isinstance(ev, dict) and ev.get("kind") == "client_state":
                    client_state = ev.get("value")
            if client_state in ("approval-needed", "limit"):
                self.status.set("request", client_state, source="peer_report")
            elif e["type"] == "ACCEPT":
                self.status.set("request", "accepted", source="peer_report")
            else:
                self.status.set("request", "processing", source="peer_report")
            return True
        # RESULT or ERROR for the pending request
        self.status.set("request", "result-received", source="reader")
        self._terminal(req, e, "completed" if e["type"] == "RESULT" else "error")
        return True

    # ------------------------------------------------------------------ user and local turns (G1)
    def conversation_required(self) -> bool:
        """True when persisted conversations exist and none is selected: the host must select or create one
        explicitly (Arya 5826453952, Dev S20b); a fresh root may start its first conversation implicitly."""
        return self.conversation_id is None and bool(self.reader.ledger.conversations())

    def _ensure_conversation(self) -> str:
        if self.conversation_id is None:
            self.conversation_id = str(uuid.uuid4())
        self.reader.ledger.note_conversation(self.conversation_id)   # G3: findable after a restart
        return self.conversation_id

    SUBMISSIONS_KEPT = 100

    @staticmethod
    def _submission_ts(submission_id: str) -> int | None:
        head = submission_id.split("-", 1)[0]
        return int(head) if head.isdigit() and len(head) >= 12 else None   # UTC milliseconds prefix convention

    def _older_than_horizon(self, submission_id: str) -> bool:
        ts = self._submission_ts(submission_id)
        if ts is None or len(self.submissions) < self.SUBMISSIONS_KEPT:
            return False
        known = [t for t in (self._submission_ts(s) for s in self.submissions) if t is not None]
        return bool(known) and ts < min(known)

    def record_user_turn(self, original_text: str, origin: str, submission_id: str) -> dict:
        """Public (Arya 5826453952): the user's original words, stored once per submission_id.
        A repeat of the same submission_id returns the same user_event_id with duplicate=true and writes nothing."""
        if origin not in self.ORIGINS:
            return {"user_event_id": None, "sequence": None, "persisted": {"turn": False, "error": "contract_error"},
                    "duplicate": False, "conversation_id": self.conversation_id, "reason": "origin"}
        if not isinstance(submission_id, str) or not submission_id:
            return {"user_event_id": None, "sequence": None, "persisted": {"turn": False, "error": "contract_error"},
                    "duplicate": False, "conversation_id": self.conversation_id, "reason": "submission_id"}
        prior = self.submissions.get(submission_id)
        if prior is None and self.conversation_required():   # a known duplicate is refused as such even before selection
            return {"user_event_id": None, "sequence": None, "persisted": {"turn": False, "error": None},
                    "duplicate": False, "conversation_id": None,
                    "reason": "conversation_required: select_conversation() or new_conversation() first"}
        if prior is None and self._older_than_horizon(submission_id):
            # Dev S19: a replay older than everything the horizon still remembers cannot be proven new -> refused,
            # never silently accepted. Detectable only when the host uses ids that start with a UTC-ms timestamp.
            return {"user_event_id": None, "sequence": None, "persisted": {"turn": False, "error": None},
                    "duplicate": False, "conversation_id": self.conversation_id,
                    "reason": "uncertain_replay: submission older than the dedup horizon; reconcile from history"}
        if prior is not None:
            # Same submission_id with different words or origin is a CONFLICT, never a silent old event (Arya 5826475943).
            if prior.get("restored"):
                return {"user_event_id": None, "sequence": None, "persisted": {"turn": False, "error": None},
                        "duplicate": True, "conversation_id": prior.get("conversation_id"),
                        "reason": "submission_seen_before_restart: reconcile from history, not resent"}
            if prior.get("text") != original_text or prior.get("origin") != origin:
                return {"user_event_id": None, "sequence": None, "persisted": {"turn": False, "error": "conflict"},
                        "duplicate": False, "conflict": True, "conversation_id": prior.get("conversation_id"),
                        "reason": "submission_conflict: same submission_id, different text or origin"}
            return dict(prior, duplicate=True)
        self._ensure_conversation()
        seq = self._next_turn(self.conversation_id)
        turn = {"schema_version": "1.0", "event_id": str(uuid.uuid4()), "conversation_id": self.conversation_id,
                "turn_id": str(uuid.uuid4()), "request_id": None, "sequence": seq, "epoch": self.relationship.self_epoch,
                "author": self.relationship.self_id, "timestamp": self.clock.iso(), "kind": "user",
                "terminal_state": "completed",
                "payload": {"text": original_text, "origin": origin, "submission_id": submission_id, "evidence": []}}
        ok, err, _raised = self._save_turn(turn)
        record = dict(turn, persisted={"turn": ok, "checkpoint": False, "error": err}, origin=origin, responder=None,
                      request_id=None, speech="not_spoken")
        self.transcript.append(record)
        result = {"user_event_id": turn["event_id"], "sequence": seq, "persisted": {"turn": ok, "error": err},
                  "duplicate": False, "conversation_id": self.conversation_id}
        self.submissions[submission_id] = dict(result, text=original_text, origin=origin)
        self.reader.ledger.note_submission(submission_id, keep=self.SUBMISSIONS_KEPT)
        if len(self.submissions) > self.SUBMISSIONS_KEPT:
            oldest = next(iter(self.submissions))
            del self.submissions[oldest]
        self.user_events[turn["event_id"]] = record
        return result

    def _save_user_turn(self, text: str, origin: str) -> dict:
        """Internal: escalate() with text and no user_event_id records once through the public path."""
        res = self.record_user_turn(text, origin, submission_id=f"auto-{uuid.uuid4()}")
        return self.user_events.get(res.get("user_event_id")) or {"persisted": res["persisted"]}

    def record_local_answer(self, text: str, *, origin: str, user_event_id: str | None = None, evidence: list | None = None,
                            completion_id: str | None = None) -> dict:
        """A local Jarvis answer (no Claude consultation): saved as an assistant_local turn linked to the user turn.
        Exactly one local answer per user_event_id: a repeat with the same completion_id (or same text fingerprint)
        returns the stored answer with duplicate=true; a different answer for the same user turn is a conflict."""
        if user_event_id is not None and user_event_id not in self.user_events:
            return {"event_id": None, "sequence": None, "persisted": {"turn": False, "error": "contract_error"},
                    "linked_user_event_id": user_event_id, "reason": "unknown user_event_id"}
        if user_event_id is not None:
            prior = self.local_answers.get(user_event_id)
            if prior is not None:
                same = (completion_id is not None and prior.get("completion_id") == completion_id) or prior.get("fingerprint") == canon.fingerprint({"t": text, "o": origin})
                if same:
                    return dict(prior["result"], duplicate=True)
                return {"event_id": None, "sequence": None, "persisted": {"turn": False, "error": "conflict"},
                        "linked_user_event_id": user_event_id, "conflict": True,
                        "reason": "local_answer_conflict: a different answer is already stored for this user turn"}
        self._ensure_conversation()
        seq = self._next_turn(self.conversation_id)
        turn = {"schema_version": "1.0", "event_id": str(uuid.uuid4()), "conversation_id": self.conversation_id,
                "turn_id": str(uuid.uuid4()), "request_id": None, "sequence": seq, "epoch": self.relationship.self_epoch,
                "author": self.relationship.self_id, "timestamp": self.clock.iso(), "kind": "assistant_local",
                "terminal_state": "completed",
                "payload": {"text": text, "responder": self.relationship.self_id, "origin": origin,
                            "user_event_id": user_event_id, "evidence": list(evidence or [])}}
        ok, err, raised = self._save_turn(turn)
        cp_ok, cp_err = (False, None) if raised else self._checkpoint()
        record = dict(turn, persisted={"turn": ok, "checkpoint": cp_ok, "error": err or cp_err}, origin=origin,
                      responder=self.relationship.self_id, request_id=None, speech="not_spoken",
                      linked_user_event_id=user_event_id)
        self.transcript.append(record)
        result = {"event_id": turn["event_id"], "sequence": seq, "persisted": record["persisted"],
                  "linked_user_event_id": user_event_id, "duplicate": False}
        if user_event_id is not None:
            self.local_answers[user_event_id] = {"completion_id": completion_id, "fingerprint": canon.fingerprint({"t": text, "o": origin}),
                                                 "result": result}
        return dict(record, **result)

    def new_conversation(self) -> dict:
        """Explicit new conversation (Arya 5826487015): refused while anything is live or unsaved, like selection."""
        unsaved = [t.get("event_id") for t in self.transcript if not t.get("restored")
                   and isinstance(t.get("persisted"), dict) and t["persisted"].get("turn") is False]
        if self.pending is not None or self.cancel_outstanding or unsaved:
            return {"created": False, "reason": "active_or_unsaved", "unsaved": unsaved}
        self.conversation_id = str(uuid.uuid4())
        self.reader.ledger.note_conversation(self.conversation_id)
        self.transcript = []            # a new conversation starts empty; prior rows are all saved (refused otherwise)
        return {"created": True, "conversation_id": self.conversation_id}

    def conversations(self) -> list[dict]:
        """Authoritative persisted enumeration: my ledger's list cross-checked with the store's checkpoint. No guessing."""
        out = []
        for cid in self.reader.ledger.conversations():
            item = {"conversation_id": cid, "last_sequence": None, "closed_cleanly": None, "pending": None, "source": "ledger"}
            if self.store is not None:
                try:
                    cp = self.store.load_checkpoint(cid)
                except Exception:  # noqa: BLE001
                    cp = None
                if isinstance(cp, dict) and cp.get("checkpoint_available"):
                    c = cp.get("checkpoint") or {}
                    item.update(last_sequence=c.get("last_sequence"), closed_cleanly=c.get("closed_cleanly"),
                                pending=len(c.get("pending") or []), source="checkpoint")
            out.append(item)
        return out

    def select_conversation(self, conversation_id: str) -> dict:
        """Explicit selection by the user through the host; restores that conversation display-only."""
        known = {c["conversation_id"] for c in self.conversations()}
        if conversation_id not in known:
            return {"selected": False, "reason": "unknown conversation_id"}
        # Never mix contexts or abandon unsaved work (Arya 5826475943): refuse while anything is live or unsaved.
        unsaved = [t.get("event_id") for t in self.transcript if not t.get("restored")
                   and isinstance(t.get("persisted"), dict) and t["persisted"].get("turn") is False]
        if self.pending is not None or self.cancel_outstanding or unsaved:
            return {"selected": False, "reason": "active_or_unsaved", "pending": self.pending["message_id"] if self.pending else None,
                    "cancel_outstanding": list(self.cancel_outstanding), "unsaved": unsaved}
        # No cross-conversation contamination (UI review, Arya 5826602151): only the selected conversation's rows
        # remain; safe because selection is refused while anything is unsaved (checked above).
        self.transcript = [t for t in self.transcript if t.get("conversation_id") == conversation_id]
        self.pending = None
        self.conversation_id = conversation_id
        self.recover(conversation_id=conversation_id)
        return {"selected": True, "conversation_id": conversation_id, "recovery": {"state": self.recovery_state, "errors": list(self.recovery_errors)}}

    def shutdown(self) -> dict:
        """Save the final checkpoint before app exit; report the consumed result, never a 'saved' claim."""
        for tid in self.speech.invalidate_all():
            for rec in self.transcript:
                if rec.get("speech_token") == tid:
                    rec["speech"] = "cancelled_before_completion"
        cp_ok, cp_err = self._checkpoint(closed_cleanly=True)
        self.status.set("shutdown", "checkpoint saved" if cp_ok else f"checkpoint NOT saved ({cp_err or 'non-durable'})", source="store")
        unsaved = [t.get("event_id") for t in self.transcript
                   if t.get("event_id") and not t.get("restored") and isinstance(t.get("persisted"), dict) and t["persisted"].get("turn") is False]
        return {"checkpoint_persisted": cp_ok, "error": cp_err, "pending": self.pending["message_id"] if self.pending else None,
                "cancel_outstanding": list(self.cancel_outstanding), "unsaved": unsaved}

    # ------------------------------------------------------------------ terminal
    def _turn(self, req: dict, e: dict, state: str, *, seq: int, extra_payload: dict | None = None) -> dict:
        # G2: provenance lives INSIDE the stored payload, not only on the in-memory record.
        payload = {"text": e["body"], "responder": e["from"], "evidence": [],
                   "origin": req.get("origin"), "origin_echoed": self.origin_of(e),
                   "user_event_id": req.get("user_event_id")}     # Dev S16b: the answer names its question on disk
        payload.update(extra_payload or {})
        return {"schema_version": "1.0", "event_id": str(uuid.uuid4()), "conversation_id": req["conversation_id"],
                "turn_id": str(uuid.uuid4()), "request_id": req["message_id"], "sequence": seq,
                "epoch": self.relationship.self_epoch, "author": e["from"], "timestamp": self.clock.iso(),
                "kind": "assistant_claude", "terminal_state": state, "payload": payload}

    def _save_turn(self, turn: dict) -> tuple[bool, str | None, bool]:
        """(persisted, error, raised)"""
        if self.store is None:
            return False, None, False
        try:
            p, err = storage.consume(self.store.save_completed_turn(turn))
            return p, err, False
        except Exception as ex:  # noqa: BLE001
            return False, type(ex).__name__, True

    def _persisted_line(self, turn_ok: bool, cp_ok: bool, err: str | None) -> str:
        line = f"turn={'yes' if turn_ok else 'no'} checkpoint={'yes' if cp_ok else 'no'}"
        if err:
            return f"{line} ({err})"
        if not self._durable():
            return f"{line} (non-durable)"
        return line

    def _terminal(self, req: dict, e: dict, state: str) -> None:
        self.trace.append("terminal_check")
        turn = self._turn(req, e, state, seq=req["turn_sequence"])
        turn_ok, err, raised = self._save_turn(turn)
        self.trace.append("save_completed_turn")
        self.pending = None
        req["state"] = state
        self.trace.append("live_state")
        cp_ok, cp_err = (False, None) if raised else self._checkpoint()
        self.trace.append("save_checkpoint")
        error = err or cp_err
        persisted = {"turn": turn_ok, "checkpoint": cp_ok, "error": error}
        self.status.set("persisted", self._persisted_line(turn_ok, cp_ok, error), source="store")
        record = dict(turn, persisted=persisted, request_id=req["message_id"], responder=e["from"], speech="not_spoken",
                      origin=req.get("origin"), origin_echoed=self.origin_of(e), user_event_id=req.get("user_event_id"))
        self.transcript.append(record)
        self.trace.append("display")
        self.display.show(event="answer", request_id=req["message_id"], text=e["body"], state=state,
                          persisted=self.status.get("persisted"))
        self.status.set("request", "completed" if state == "completed" else "error", source="terminal")
        self.trace.append("speech")
        if state == "completed" and not req["cancelled"]:
            self._emit(record, req, e["body"])

    def _emit(self, record: dict, req: dict, text: str) -> None:
        """Issue the one eligibility token and hand the text to the host's speaker.
        A synchronous speaker returns None: started+completed are recorded here. An asynchronous
        host returns "queued" and reports through speech_callback; the record stays truthful."""
        tok = self.speech.issue(request_id=req["message_id"], epoch=self.relationship.self_epoch, text=text)
        record["speech"] = "eligible"
        record["speech_token"] = tok["token_id"]
        # A speaker that is not playback at all (None, or declares playback = False, e.g. a log) is a
        # truthful no-speech path; it never yields spoken.
        if self.speaker is None or getattr(self.speaker, "playback", True) is False:
            record["speech"] = "no_speech_path"
            return
        descriptor = {"emission_id": tok["token_id"], "request_id": req["message_id"], "epoch": tok["epoch"],
                      "cancel_generation": tok["cancel_generation"], "text": text}
        try:
            outcome = self.speaker.speak(descriptor)
        except Exception as ex:  # noqa: BLE001
            self.speech.error(tok["token_id"], type(ex).__name__)
            record["speech"] = self.speech.state(tok["token_id"])
            return
        if outcome == "queued":
            record["speech"] = "queued"          # stays queued until an authoritative completion callback
        elif outcome == "refused":
            self.speech.error(tok["token_id"], "SpeakerRefused")
            record["speech"] = self.speech.state(tok["token_id"])
        elif outcome == "completed" and getattr(self.speaker, "blocking_completion", False) is True:
            self.speech.started(tok["token_id"])   # only an explicit blocking-completion contract may do this
            self.speech.completed(tok["token_id"])
            record["speech"] = self.speech.state(tok["token_id"])
        else:
            self.speech.error(tok["token_id"], "SpeakerContract")   # None or an unknown value proves nothing
            record["speech"] = self.speech.state(tok["token_id"])

    def speech_callback(self, kind: str, token_id: str, *, epoch: str | None = None, cancel_generation: int | None = None,
                        error_type: str | None = None) -> str:
        """Host callbacks: started | completed | error | unknown, bound to the (token, epoch, cancel generation)
        triple. Idempotent; refused for unknown, stale or mismatched tokens; never touches other state."""
        kw = {"epoch": epoch, "cancel_generation": cancel_generation}
        if kind == "started":
            outcome = self.speech.started(token_id, **kw)
        elif kind == "completed":
            outcome = self.speech.completed(token_id, **kw)
        elif kind == "error":
            outcome = self.speech.error(token_id, error_type or "", **kw)
        elif kind == "unknown":
            outcome = self.speech.unknown(token_id, **kw)
        else:
            return "refused"
        if outcome == "applied":
            for rec in self.transcript:
                if rec.get("speech_token") == token_id:
                    rec["speech"] = self.speech.state(token_id)
        return outcome

    def _late_reply(self, req: dict, e: dict, *, flag: str | None = None) -> None:
        if flag is None:
            flag = "late_for_cancelled_request" if req.get("cancelled") else "late_for_terminal_request"
        extra = {flag: True}
        seq = self._next_turn(req["conversation_id"])
        turn = self._turn(req, e, "completed", seq=seq, extra_payload=extra)
        turn_ok, err, _ = self._save_turn(turn)
        record = dict(turn, persisted={"turn": turn_ok, "checkpoint": False, "error": err}, request_id=req["message_id"],
                      responder=e["from"], speech="not_spoken", late=True)
        self.transcript.append(record)
        self.display.show(event="late_reply", request_id=req["message_id"], text=e["body"], cancelled=req["cancelled"])

    # ------------------------------------------------------------------ stop / cancel
    def stop(self) -> None:
        # Comm allocates the cancellation generation and invalidates tokens BEFORE the speaker is told
        # to stop, so a completion racing with the stop is already stale when it arrives.
        for tid in self.speech.invalidate_all():
            for rec in self.transcript:
                if rec.get("speech_token") == tid:
                    rec["speech"] = "cancelled_before_completion"
        if self.speaker is not None:
            self.speaker.stop()
        if self.pending is None:
            return
        req = self.pending
        req["cancelled"] = True
        req["state"] = "cancelled"
        self.pending = None
        self.cancel_outstanding[req["message_id"]] = req
        self.status.set("request", "cancelled", source="local_stop")
        self.status.set("remote_cancel", "unconfirmed", source="local")
        turn = {"schema_version": "1.0", "event_id": str(uuid.uuid4()), "conversation_id": req["conversation_id"],
                "turn_id": str(uuid.uuid4()), "request_id": req["message_id"], "sequence": req["turn_sequence"],
                "epoch": self.relationship.self_epoch, "author": self.relationship.self_id, "timestamp": self.clock.iso(),
                "kind": "system", "terminal_state": "cancelled", "payload": {"text": "", "evidence": []}}
        turn_ok, err, raised = self._save_turn(turn)
        cp_ok, cp_err = (False, None) if raised else self._checkpoint()
        self.transcript.append(dict(turn, persisted={"turn": turn_ok, "checkpoint": cp_ok, "error": err or cp_err},
                                    request_id=req["message_id"], responder=None, speech="not_spoken"))
        e = self._entry("CANCEL_REQUEST", "stop", to=[self.relationship.peer_id], reply_to=[req["message_id"]],
                        conversation_id=req["conversation_id"])
        r = self.publisher.publish(e)
        self.display.show(event="cancel_requested", request_id=req["message_id"], publish=r.status)

    # ------------------------------------------------------------------ the other side: reply to inbound work
    @staticmethod
    def origin_of(entry: dict) -> str | None:
        for ev in entry.get("evidence", []):
            if isinstance(ev, dict) and ev.get("kind") == "origin":
                return ev.get("value")
        return None

    def reply(self, inbound: dict, text: str, *, type_: str = "RESULT") -> dict:
        origin = self.origin_of(inbound)
        e = self._entry(type_, text, to=[inbound["from"]], reply_to=[inbound["message_id"]],
                        conversation_id=inbound["conversation_id"],
                        evidence=([{"kind": "origin", "value": origin}] if origin else []))  # echo what was answered
        r = self.publisher.publish(e)
        self.display.show(event="replied", to=inbound["message_id"], publish=r.status)
        return dict(e, publish=r.status)

    # ------------------------------------------------------------------ restart
    def recover(self, *, conversation_id: str | None = None) -> dict:
        rel = self.relationship
        empty = {"previous_epoch": None, "stale_unresolved": [], "still_pending": [], "stray_tmp_quarantined": [],
                 "history_repaired": [], "history_frozen_unsupported_major": [],
                 "checkpoint_current_missing_prev_used": [], "warnings": []}
        contract_errors: list[str] = []

        def _read(name: str, call):
            """All six store functions return plain dicts (COMM-01.md D6, Dev 5826088544). Anything
            else is a typed store contract error, never an AttributeError escaping into the host."""
            try:
                out = call()
            except Exception as ex:  # noqa: BLE001
                contract_errors.append(f"{name}: {type(ex).__name__}")
                return None
            if not isinstance(out, dict):
                contract_errors.append(f"{name}: contract_error (returned {type(out).__name__}, expected dict)")
                return None
            return out

        rep = _read("recover", lambda: self.store.recover(rel.self_epoch)) if self.store is not None else dict(empty)
        if rep is None:
            rep = dict(empty)
            rep["warnings"] = list(contract_errors)
            self.pending = None
            self.recovery = {"report": rep, "pending": [], "gaps": [], "counter": {}, "conversations": [],
                             "pending_state": "unknown (store contract error)", "store_contract_errors": list(contract_errors)}
            self.recovery_state = "unresolved"
            self.recovery_errors = list(contract_errors)
            self.status.set("recovery", self._recovery_status_text(), source="store")
            self.display.show(event="store_contract_error", errors=list(contract_errors))
            return rep
        convs: list[str] = []
        if conversation_id:
            convs.append(conversation_id)
        for item in list(rep.get("stale_unresolved", [])) + list(rep.get("still_pending", [])):
            if item.get("conversation_id") and item["conversation_id"] not in convs:
                convs.append(item["conversation_id"])
        for cid in self.reader.ledger.conversations():        # G3: conversations known from my own ledger
            if cid not in convs:
                convs.append(cid)
        restored_records: dict[str, dict] = {}
        pending_out: list[dict] = []
        gaps_out: list[dict] = []
        counter: dict = {}
        pending_state = "recovered"
        for conv in convs:
            hist = _read("load_history", lambda: self.store.load_history(conv)) if self.store is not None else {"events": [], "gaps": []}
            if hist is None:
                hist = {"events": [], "gaps": []}
            events = hist.get("events", [])
            high = max((ev["sequence"] for ev in events), default=0)
            cp = _read("load_checkpoint", lambda: self.store.load_checkpoint(conv)) if self.store is not None else {"checkpoint_available": False}
            if cp is None:
                cp = {"checkpoint_available": False}
            cp_last = None
            pend_max = None
            cp_pending = []
            if cp.get("checkpoint_available"):
                cp_last = cp["checkpoint"].get("last_sequence")
                cp_pending = cp["checkpoint"].get("pending", [])
                for sid in cp["checkpoint"].get("submissions", []) or []:   # duplicates after restart stay refused
                    self.submissions.setdefault(sid, {"user_event_id": None, "sequence": None,
                                                      "persisted": {"turn": None, "error": None}, "duplicate": True,
                                                      "conversation_id": conv, "restored": True})
                tseqs = [p["turn_sequence"] for p in cp_pending if isinstance(p.get("turn_sequence"), int)]
                pend_max = max(tseqs) if tseqs else None
            else:
                pending_state = "unknown (checkpoint unavailable)"
            present = [x for x in (high, cp_last, pend_max) if x is not None]
            resumed = max(present) if present else 0
            disagreement = len(set(present)) > 1
            self._turn_seq[conv] = resumed
            counter = {"history_high_water": high, "checkpoint_last_sequence": cp_last,
                       "pending_max_turn_sequence": pend_max, "resumed_from": resumed, "disagreement": disagreement}
            if disagreement:
                self.display.show(event="counter_disagreement", conversation_id=conv, **counter)
            for missing in ([hist.get("gaps", [])] if hist.get("gaps") else []):
                gaps_out.append({"conversation_id": conv, "missing": list(missing), "reason": "unknown"})
            by_req = {ev.get("request_id"): ev for ev in events if ev.get("request_id")}
            # G3: rebuild the request map from the store so a late reply after restart maps to a known request.
            for rid, ev in by_req.items():
                self.requests.setdefault(rid, {"message_id": rid, "conversation_id": conv, "turn_sequence": ev.get("sequence"),
                                               "text": None, "epoch": ev.get("epoch"), "state": ev.get("terminal_state", "completed"),
                                               "cancelled": ev.get("terminal_state") == "cancelled", "restored": True,
                                               "origin": (ev.get("payload") or {}).get("origin")})
            for p in cp_pending:
                self.requests.setdefault(p["request_id"], {"message_id": p["request_id"], "conversation_id": conv,
                                                           "turn_sequence": p.get("turn_sequence"), "text": None, "epoch": p.get("epoch"),
                                                           "state": p.get("prior_state") or p.get("state"), "cancelled": False,
                                                           "restored": True, "origin": None})
            if self.conversation_id is None and conversation_id == conv:
                self.conversation_id = conv          # only an EXPLICIT selection makes a conversation current (Dev S20b)
            for p in cp_pending:
                item = {"request_id": p["request_id"], "epoch": p.get("epoch"), "conversation_id": conv,
                        "turn_sequence": p.get("turn_sequence"), "prior_state": p.get("prior_state") or p.get("state")}
                ev = by_req.get(p["request_id"])
                if ev is not None and ev.get("terminal_state") in ("completed", "error", "cancelled"):
                    item["state"] = "resolved_by_history"
                elif p.get("epoch") != rel.self_epoch:
                    item["state"] = "stale_unresolved"
                else:
                    item["state"] = "unknown"
                pending_out.append(item)
            for ev in events:   # every stored turn is restored once, display-only, in sequence order (below)
                pl = ev.get("payload") or {}
                rec = dict(ev, restored=True, request_id=ev.get("request_id"),
                           responder=pl.get("responder"), speech="unknown",
                           origin=pl.get("origin"), origin_echoed=pl.get("origin_echoed"))
                # Dev S24: identities are lifted from the stored payload exactly as origin is, so pairing and dedup
                # work the same before and after a reopen.
                if ev.get("kind") == "assistant_claude":
                    rec["user_event_id"] = pl.get("user_event_id")
                elif ev.get("kind") == "assistant_local":
                    rec["linked_user_event_id"] = pl.get("user_event_id")
                restored_records[ev["event_id"]] = rec
        # Rows are restored into the transcript ONLY for an explicitly selected conversation (UI review via Arya
        # 5826602151, Dev S20b): start() reconciles every known conversation but shows none, so contexts never mix.
        already = {t.get("event_id") for t in self.transcript if t.get("event_id")}
        for rec in sorted(restored_records.values(), key=lambda r: (r.get("conversation_id") or "", r.get("sequence") or 0)):
            if conversation_id is not None and rec.get("conversation_id") == conversation_id and rec["event_id"] not in already:
                self.transcript.append(rec)         # Dev S21: never twice
        self.pending = None
        if contract_errors:
            pending_state = "unknown (store contract error)"
        # Anything the store could not resolve is PUBLIC and GATING (Arya 5826247682, UI executor's R4 repro):
        # frozen unsupported-major files, an unavailable checkpoint for a KNOWN conversation, and pending items
        # whose state is unknown all make recovery `unresolved`; no silent reset, no escalation until resolved.
        unresolved: list[str] = list(contract_errors)
        for key in ("history_frozen_unsupported_major", "checkpoint_frozen_unsupported_major"):
            frozen = rep.get(key) or []
            if frozen:
                unresolved.append(f"{key}: {len(frozen)} file(s) preserved and refused")
        if convs and pending_state.startswith("unknown"):
            unresolved.append(f"pending_state: {pending_state}")
        for item in pending_out:
            if item["state"] == "unknown":
                unresolved.append(f"pending {item['request_id']}: state unknown")
        if rep.get("still_pending"):
            unresolved.append(f"still_pending: {len(rep['still_pending'])} same-epoch item(s) not reconciled")
        self.recovery = {"report": rep, "pending": pending_out, "gaps": gaps_out, "counter": counter,
                         "pending_state": pending_state, "conversations": convs,
                         "store_contract_errors": list(contract_errors), "unresolved": unresolved}
        self.recovery_state = "unresolved" if unresolved else "ok"
        self.recovery_errors = list(unresolved)
        # ONE classification feeds both fields (UI executor's finding, Arya 5826383776): the status key and
        # recovery_state can never disagree because they are derived from the same list here.
        self.status.set("recovery", self._recovery_status_text(), source="store")
        if contract_errors:
            self.display.show(event="store_contract_error", errors=list(contract_errors))
        self.display.show(event="recovered", pending=len(pending_out), stale=len(rep.get("stale_unresolved", [])),
                          pending_state=pending_state)
        return rep
