"""Python-to-browser bridge for the interface: a strict JSON facade over ``state.Comm``.

Agreed seams (hub 5825949203, 5825957209, 5825977000, 5825984993, 5825988607):

- The host builds ``Comm`` through ``launch.build`` and wraps it in ``CommApi``; ONE host worker
  serializes every call. The ``RLock`` here is defensive mutual exclusion only, NOT an ordering
  guarantee; the host worker provides ordering.
- Page-facing methods: ``snapshot transcript escalate stop poll`` plus the speech callbacks
  ``speech_started speech_completed speech_error speech_unknown``. Host-only hooks (explicit
  Start/Connect, never automatic on window show): ``start recover check_in``.
- Strict boundary: allow-listed fields with type checks; an unexpected or coercible value raises
  ``BridgeContractError`` rather than being coerced. No ``default=str``.
- Binding facts are reported read-only; the page cannot set epochs.
"""

from __future__ import annotations

import json
import threading
from typing import Any

ATOM = (str, int, bool, type(None), float)
TRANSCRIPT_FIELDS = {
    "kind": str, "payload": dict, "responder": (str, type(None)), "request_id": (str, type(None)),
    "restored": bool, "speech": (str, type(None)), "speech_token": (str, type(None)),
    "persisted": (dict, type(None)), "late": bool, "terminal_state": (str, type(None)),
    "timestamp": (str, type(None)), "sequence": (int, type(None)),
    "origin": (str, type(None)), "origin_echoed": (str, type(None)),
    # identities the host needs for dedup and conversation filtering (UI review, Arya 5826602151)
    "event_id": (str, type(None)), "conversation_id": (str, type(None)), "linked_user_event_id": (str, type(None)),
    "user_event_id": (str, type(None)), "turn_id": (str, type(None)),
}
STATUS_KEYS = {"request", "busy", "handshake", "transport", "storage", "persisted", "remote_cancel", "recovery", "shutdown"}


class BridgeContractError(TypeError):
    pass


def _strict(value: Any, path: str = "$") -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise BridgeContractError(f"non-finite number at {path}")
        return value
    if isinstance(value, list):
        return [_strict(v, f"{path}[{i}]") for i, v in enumerate(value)]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise BridgeContractError(f"non-string key at {path}")
            out[k] = _strict(v, f"{path}.{k}")
        return out
    raise BridgeContractError(f"unexpected type {type(value).__name__} at {path}")


def _transcript_record(rec: dict) -> dict:
    out = {}
    for k, v in rec.items():
        if k not in TRANSCRIPT_FIELDS:
            continue  # internal fields never cross; the allow-list is the contract
        if not isinstance(v, TRANSCRIPT_FIELDS[k]) or (isinstance(v, bool) and TRANSCRIPT_FIELDS[k] is int):
            raise BridgeContractError(f"transcript field {k} has type {type(v).__name__}")
        out[k] = _strict(v, f"transcript.{k}")
    if "kind" not in out or "payload" not in out:
        raise BridgeContractError("transcript record lacks kind/payload")
    return out


class CommApi:
    def __init__(self, comm):
        self._comm = comm
        self._lock = threading.RLock()

    # ---------------------------------------------------------------- host-only hooks
    def _recovery(self) -> dict:
        """Typed, always present: state not_run | ok | unresolved, with the store contract errors."""
        return {"state": self._comm.recovery_state, "errors": list(self._comm.recovery_errors),
                "pending_state": self._comm.recovery.get("pending_state") if self._comm.recovery else None}

    def start(self) -> dict:
        """Explicit Start/Connect: recover, then check_in. Nothing runs before the host calls this.
        An unresolved recovery is returned as such (state, errors) and still performs the CHECK_IN, so the
        relationship can bind, but every escalation is refused until a clean recover()."""
        with self._lock:
            rep = self._comm.recover()
            ci = self._comm.check_in()
            return _strict({"recovery": dict(self._recovery(),
                                             stale_unresolved=len(rep.get("stale_unresolved", [])),
                                             still_pending=len(rep.get("still_pending", [])),
                                             previous_epoch=rep.get("previous_epoch")),
                            "check_in_id": ci["message_id"], "binding": self._binding()})

    def recover(self) -> dict:
        with self._lock:
            rep = self._comm.recover()
            return _strict(dict(self._recovery(), previous_epoch=rep.get("previous_epoch"),
                                stale_unresolved=[p.get("request_id") for p in rep.get("stale_unresolved", [])],
                                still_pending=[p.get("request_id") for p in rep.get("still_pending", [])]))

    def check_in(self) -> dict:
        with self._lock:
            ci = self._comm.check_in()
            return _strict({"check_in_id": ci["message_id"], "binding": self._binding()})

    # ---------------------------------------------------------------- page-facing
    def _binding(self) -> dict:
        rel = self._comm.relationship
        return {"bound": rel.bound, "self_id": rel.self_id, "self_session": rel.self_session, "self_epoch": rel.self_epoch,
                "peer_id": rel.peer_id, "peer_session": rel.peer_session, "peer_epoch": rel.peer_epoch,
                "my_check_in_id": rel.my_check_in_id, "peer_check_in_id": rel.peer_check_in_id,
                "conversation_id": self._comm.conversation_id,
                "cancel_generation": self._comm.speech.cancel_generation}

    def snapshot(self) -> dict:
        with self._lock:
            status = self._comm.status.snapshot()
            if set(status) - STATUS_KEYS:
                raise BridgeContractError(f"unexpected status keys {sorted(set(status) - STATUS_KEYS)}")
            return _strict({"status": status, "pending": self._comm.pending["message_id"] if self._comm.pending else None,
                            "binding": self._binding(), "recovery": self._recovery()})

    def transcript(self) -> list:
        with self._lock:
            return [_transcript_record(r) for r in self._comm.transcript]

    def view(self) -> dict:
        """snapshot + transcript captured atomically under one lock acquisition."""
        with self._lock:
            return {"snapshot": self.snapshot(), "transcript": self.transcript()}

    def escalate(self, text: Any = None, origin: Any = None, user_event_id: Any = None, submission_id: Any = None,
                 consultation_text: Any = None) -> dict:
        """origin is mandatory and typed: "krish-via-jarvis" | "jarvis" (Krish 5826141255). Pass user_event_id from
        record_user_turn to reuse the stored user turn, or text (+ submission_id) to record and escalate once."""
        if user_event_id is None and (not isinstance(text, str) or not text.strip()):
            return {"sent": False, "reason": "empty"}
        if not isinstance(origin, str):
            return {"sent": False, "reason": "contract_error: origin must be a string"}
        if user_event_id is not None and not isinstance(user_event_id, str):
            return {"sent": False, "reason": "contract_error: user_event_id must be a string"}
        with self._lock:
            if consultation_text is not None and not isinstance(consultation_text, str):
                return {"sent": False, "reason": "contract_error: consultation_text must be a string"}
            r = self._comm.escalate(text, origin=origin, user_event_id=user_event_id,
                                    submission_id=submission_id if isinstance(submission_id, str) else None,
                                    consultation_text=consultation_text)
            return _strict({"sent": bool(r.get("sent", False)), "reason": r.get("reason"), "message_id": r.get("message_id"),
                            "user_event_id": r.get("user_event_id"), "status": self._comm.status.get("request")})

    # ---------------------------------------------------------------- persistence-host API (Arya 5826453952)
    def record_user_turn(self, original_text: Any, origin: Any, submission_id: Any) -> dict:
        if not isinstance(original_text, str) or not isinstance(origin, str) or not isinstance(submission_id, str):
            return {"user_event_id": None, "duplicate": False, "persisted": {"turn": False, "error": "contract_error"},
                    "reason": "typed arguments required"}
        with self._lock:
            return _strict(self._comm.record_user_turn(original_text, origin, submission_id))

    def record_local_answer(self, text: Any, origin: Any, user_event_id: Any, evidence: Any = None, completion_id: Any = None) -> dict:
        if not isinstance(text, str) or not isinstance(origin, str) or not isinstance(user_event_id, str):
            return {"event_id": None, "persisted": {"turn": False, "error": "contract_error"}, "reason": "typed arguments required"}
        if completion_id is not None and not isinstance(completion_id, str):
            return {"event_id": None, "persisted": {"turn": False, "error": "contract_error"}, "reason": "completion_id must be a string"}
        with self._lock:
            r = self._comm.record_local_answer(text, origin=origin, user_event_id=user_event_id,
                                               evidence=evidence if isinstance(evidence, list) else [], completion_id=completion_id)
            return _strict({"event_id": r.get("event_id"), "sequence": r.get("sequence"), "persisted": r.get("persisted"),
                            "linked_user_event_id": r.get("linked_user_event_id"), "duplicate": r.get("duplicate", False),
                            "conflict": r.get("conflict", False), "reason": r.get("reason")})

    def new_conversation(self) -> dict:
        with self._lock:
            return _strict(self._comm.new_conversation())

    def conversations(self) -> list:
        with self._lock:
            return _strict(self._comm.conversations())

    def select_conversation(self, conversation_id: Any) -> dict:
        if not isinstance(conversation_id, str):
            return {"selected": False, "reason": "contract_error"}
        with self._lock:
            return _strict(self._comm.select_conversation(conversation_id))

    def shutdown(self) -> dict:
        """Serialized through the facade; consumes the final checkpoint result; never calls stop()."""
        with self._lock:
            return _strict(self._comm.shutdown())

    def stop(self) -> dict:
        with self._lock:
            self._comm.stop()
            return _strict({"request": self._comm.status.get("request"), "remote_cancel": self._comm.status.get("remote_cancel"),
                            "cancel_generation": self._comm.speech.cancel_generation})

    def poll(self) -> dict:
        with self._lock:
            r = self._comm.poll()
            return _strict({"status": r.get("status"), "new": len(r.get("new_entries", [])),
                            "request": self._comm.status.get("request"), "speech": self._speech_descriptors()})

    def _speech_descriptors(self) -> list:
        return [self._comm.speech.descriptor(t.get("speech_token")) for t in self._comm.transcript
                if t.get("speech_token") and self._comm.speech.state(t["speech_token"]) in ("eligible", "queued", "started")]

    # ---------------------------------------------------------------- speech callbacks (host -> comm)
    def _cb(self, kind: str, token_id: Any, epoch: Any, cancel_generation: Any, error_type: Any = None) -> dict:
        if not isinstance(token_id, str) or not isinstance(epoch, str) or isinstance(cancel_generation, bool) or not isinstance(cancel_generation, int):
            return {"outcome": "refused", "reason": "typed triple required: token_id str, epoch str, cancel_generation int"}
        with self._lock:
            outcome = self._comm.speech_callback(kind, token_id, epoch=epoch, cancel_generation=cancel_generation, error_type=error_type)
            return _strict({"outcome": outcome, "state": self._comm.speech.state(token_id)})

    def speech_started(self, token_id, epoch, cancel_generation) -> dict:
        return self._cb("started", token_id, epoch, cancel_generation)

    def speech_completed(self, token_id, epoch, cancel_generation) -> dict:
        return self._cb("completed", token_id, epoch, cancel_generation)

    def speech_error(self, token_id, epoch, cancel_generation, error_type=None) -> dict:
        return self._cb("error", token_id, epoch, cancel_generation, error_type)

    def speech_unknown(self, token_id, epoch, cancel_generation) -> dict:
        return self._cb("unknown", token_id, epoch, cancel_generation)


def to_json(value: Any) -> str:
    """The only serializer: strict first, then json without any default coercion."""
    return json.dumps(_strict(value), ensure_ascii=False, allow_nan=False)
