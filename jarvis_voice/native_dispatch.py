"""Serialized presentation boundary over an injected, exclusively owned CommApi.

No transport, store, speaker, protocol transition or session is constructed here.
A timeout never retries an operation; an already running call may still finish.
"""
from __future__ import annotations

from concurrent.futures import Future, TimeoutError
import itertools
import json
import queue
import threading
import time
import uuid


class SchemaError(ValueError):
    pass


def _json_copy(value):
    def check(item, depth=0):
        if depth > 16:
            raise SchemaError("depth")
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is list:
            for child in item:
                check(child, depth + 1)
            return
        if type(item) is dict and all(type(k) is str for k in item):
            for child in item.values():
                check(child, depth + 1)
            return
        raise SchemaError("non JSON value")
    check(value)
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) > 512_000:
        raise SchemaError("size")
    return json.loads(encoded)


def validate_view(snapshot, transcript):
    snapshot, transcript = _json_copy(snapshot), _json_copy(transcript)
    required = {"status", "pending", "binding", "recovery"}
    if type(snapshot) is not dict or set(snapshot) != required:
        raise SchemaError("snapshot fields")
    recovery = snapshot["recovery"]
    if type(recovery) is not dict or set(recovery) != {"state", "errors", "pending_state"}:
        raise SchemaError("recovery fields")
    if recovery["state"] not in ("not_run", "ok", "unresolved") or type(recovery["errors"]) is not list:
        raise SchemaError("recovery state")
    if any(type(error) is not str for error in recovery["errors"]):
        raise SchemaError("recovery errors")
    if recovery["pending_state"] is not None and type(recovery["pending_state"]) is not str:
        raise SchemaError("pending state")
    binding = snapshot["binding"]
    binding_fields = {"bound", "self_id", "self_session", "self_epoch", "peer_id", "peer_session", "peer_epoch",
                      "my_check_in_id", "peer_check_in_id", "conversation_id", "cancel_generation"}
    if type(binding) is not dict or set(binding) != binding_fields:
        raise SchemaError("binding fields")
    if type(binding["bound"]) is not bool or type(snapshot["status"]) is not dict:
        raise SchemaError("snapshot types")
    for field in ("pending",):
        if snapshot[field] is not None and (type(snapshot[field]) is not str or not snapshot[field]):
            raise SchemaError(field)
    for field in ("self_id", "self_session", "self_epoch"):
        if type(binding[field]) is not str or not binding[field]:
            raise SchemaError(field)
    for field in binding_fields - {"bound", "cancel_generation", "self_id", "self_session", "self_epoch"}:
        if binding[field] is not None and (type(binding[field]) is not str or not binding[field]):
            raise SchemaError(field)
    if type(binding["cancel_generation"]) is not int or binding["cancel_generation"] < 0:
        raise SchemaError("cancel_generation")
    allowed_status = {"request", "busy", "handshake", "transport", "storage", "persisted", "remote_cancel", "recovery", "shutdown"}
    if set(snapshot["status"]) - allowed_status:
        raise SchemaError("status key")
    for status in snapshot["status"].values():
        if type(status) is not dict or set(status) != {"state", "source"}:
            raise SchemaError("status shape")
        if any(type(status[k]) is not str or not status[k] for k in status):
            raise SchemaError("status value")
    if type(transcript) is not list or len(transcript) > 2000:
        raise SchemaError("transcript")
    fields = {"schema_version", "event_id", "conversation_id", "sequence", "epoch", "author", "timestamp",
              "kind", "payload", "responder", "request_id", "restored", "speech", "speech_token", "persisted", "late", "terminal_state", "origin", "origin_echoed", "linked_user_event_id", "turn_id", "user_event_id"}
    for row in transcript:
        if type(row) is not dict or set(row) - fields:
            raise SchemaError("transcript fields")
        if row.get("kind") not in ("user", "assistant_local", "assistant_claude", "system"):
            raise SchemaError("kind")
        for field in ("origin", "origin_echoed"):
            if field in row and row[field] is not None and row[field] not in ("krish-via-jarvis", "jarvis"):
                raise SchemaError(field)
        # The facade's user row has no request/speech/persistence result yet.
        # Null is permitted only for those user fields, not assistant results.
        user_nulls = {"request_id", "speech", "persisted"} if row["kind"] in ("user", "assistant_local") else set()
        if type(row.get("payload")) is not dict or type(row["payload"].get("text")) is not str:
            raise SchemaError("text")
        for flag in ("restored", "late"):
            if flag in row and type(row[flag]) is not bool:
                raise SchemaError(flag)
        if "speech" in row and not ("speech" in user_nulls and row["speech"] is None):
            speech = row["speech"]
            if type(speech) is not str or (speech not in ("spoken", "not_spoken", "unknown", "queued", "started", "no_speech_path", "cancelled_before_completion")
                                           and not (speech.startswith("error(") and speech.endswith(")") and len(speech) <= 72)):
                raise SchemaError("speech")
        if "speech_token" in row and row["speech_token"] is not None and type(row["speech_token"]) is not str:
            raise SchemaError("speech_token")
        for field in ("epoch", "request_id", "event_id", "conversation_id", "author", "timestamp", "schema_version", "terminal_state", "linked_user_event_id", "turn_id", "user_event_id"):
            if field in ("linked_user_event_id", "user_event_id") and row.get(field) is None:
                continue
            if field in user_nulls and row.get(field) is None:
                continue
            if field in row and (type(row[field]) is not str or not row[field]):
                raise SchemaError(field)
        if "responder" in row and row["responder"] is not None and type(row["responder"]) is not str:
            raise SchemaError("responder")
        if "sequence" in row and (type(row["sequence"]) is not int or row["sequence"] < 1):
            raise SchemaError("sequence")
        if "persisted" in row and not ("persisted" in user_nulls and row["persisted"] is None):
            p = row["persisted"]
            if type(p) is not dict or set(p) != {"turn", "checkpoint", "error"}:
                raise SchemaError("persisted")
            if type(p["turn"]) is not bool or type(p["checkpoint"]) is not bool:
                raise SchemaError("persisted flags")
            if p["error"] is not None and type(p["error"]) is not str:
                raise SchemaError("persisted error")
    return {"snapshot": snapshot, "transcript": transcript}


PERSISTENCE_OPS = {"record_user_turn", "record_local_answer", "conversations", "select_conversation", "new_conversation", "shutdown"}
CONTEXT_OPS = {"select_conversation", "new_conversation", "shutdown"}


def validate_persistence_result(operation, result):
    """Preserve refusal and unknown values; never turn them into saved claims."""
    if operation == "conversations":
        if type(result) is not list:
            raise SchemaError("conversations")
        for item in result:
            if type(item) is not dict or set(item) != {"conversation_id", "last_sequence", "closed_cleanly", "pending", "source"}:
                raise SchemaError("conversation fields")
            if type(item["conversation_id"]) is not str or not item["conversation_id"] or item["source"] not in ("ledger", "checkpoint"):
                raise SchemaError("conversation identity")
            for key in ("last_sequence", "pending"):
                if item[key] is not None and (type(item[key]) is not int or item[key] < 0):
                    raise SchemaError(key)
            if item["closed_cleanly"] is not None and type(item["closed_cleanly"]) is not bool:
                raise SchemaError("closed_cleanly")
        return result
    allowed = {
        "record_user_turn": {"user_event_id", "sequence", "persisted", "duplicate", "conversation_id", "reason", "conflict", "text", "origin"},
        "record_local_answer": {"event_id", "sequence", "persisted", "linked_user_event_id", "duplicate", "conflict", "reason"},
        "select_conversation": {"selected", "conversation_id", "recovery", "reason", "pending", "cancel_outstanding", "unsaved"},
        "new_conversation": {"created", "conversation_id", "reason", "unsaved"},
        "shutdown": {"checkpoint_persisted", "error", "pending", "cancel_outstanding", "unsaved"},
    }[operation]
    if type(result) is not dict or set(result) - allowed:
        raise SchemaError("persistence result fields")
    required = {"record_user_turn": {"user_event_id", "persisted", "duplicate"},
                "record_local_answer": {"event_id", "persisted"}, "select_conversation": {"selected"},
                "new_conversation": {"created"}, "shutdown": allowed}[operation]
    if not required <= set(result):
        raise SchemaError("missing persistence fields")
    for key, value in result.items():
        if key in ("duplicate", "conflict", "selected", "created", "checkpoint_persisted"):
            if type(value) is not bool:
                raise SchemaError(key)
        elif key == "sequence":
            if value is not None and (type(value) is not int or value < 1):
                raise SchemaError(key)
        elif key in ("unsaved", "cancel_outstanding"):
            if type(value) is not list or any(type(v) is not str or not v for v in value):
                raise SchemaError(key)
        elif key == "persisted":
            if type(value) is not dict or not {"turn", "error"} <= set(value) or set(value) - {"turn", "checkpoint", "error"}:
                raise SchemaError(key)
            for flag in ("turn", "checkpoint"):
                if flag in value and value[flag] is not None and type(value[flag]) is not bool:
                    raise SchemaError(flag)
            if value["error"] is not None and type(value["error"]) is not str:
                raise SchemaError("persisted error")
        elif key == "recovery":
            if type(value) is not dict or set(value) != {"state", "errors"} or value["state"] not in ("not_run", "ok", "unresolved") or type(value["errors"]) is not list or any(type(v) is not str for v in value["errors"]):
                raise SchemaError(key)
        elif value is not None and type(value) is not str:
            raise SchemaError(key)
    if (result.get("selected") or result.get("created")) and not result.get("conversation_id"):
        raise SchemaError("selected identity")
    return result


def validate_result(operation, result):
    result = _json_copy(result)
    if operation in PERSISTENCE_OPS:
        return validate_persistence_result(operation, result)
    if operation == "view":
        if result is not None:
            raise SchemaError("view result")
        return None
    if operation == "start":
        if type(result) is not dict or set(result) != {"recovery", "check_in_id", "binding"} or type(result["check_in_id"]) is not str:
            raise SchemaError("start result")
        return result
    if operation.startswith("speech_"):
        if type(result) is not dict or result.get("outcome") not in ("applied", "ignored", "refused") or set(result) - {"outcome", "state", "reason"}:
            raise SchemaError("speech result")
        return result
    fields = {"escalate": {"sent", "reason", "message_id", "user_event_id", "status"},
              "stop": {"request", "remote_cancel", "cancel_generation"}, "poll": {"status", "new", "request", "speech"}}[operation]
    if type(result) is not dict or set(result) - fields:
        raise SchemaError("result fields")
    if operation == "escalate" and type(result.get("sent")) is not bool:
        raise SchemaError("sent")
    if operation == "escalate" and result["sent"] and (
            type(result.get("message_id")) is not str or not result["message_id"]):
        raise SchemaError("message_id")
    if operation == "stop" and set(result) != fields:
        raise SchemaError("stop fields")
    if operation == "stop" and (type(result["cancel_generation"]) is not int or result["cancel_generation"] < 0):
        raise SchemaError("cancel generation")
    if operation == "poll" and (type(result.get("new")) is not int or result["new"] < 0):
        raise SchemaError("new")
    for field, value in result.items():
        if field not in ("sent", "new", "cancel_generation", "speech") and value is not None and type(value) is not str:
            raise SchemaError("result value")
    if operation == "poll":
        if type(result.get("speech")) is not list:
            raise SchemaError("speech descriptors")
        for d in result["speech"]:
            if type(d) is not dict or set(d) != {"token_id", "request_id", "epoch", "cancel_generation", "text", "state"}:
                raise SchemaError("descriptor fields")
            if any(type(d[k]) is not str or not d[k] for k in ("token_id", "request_id", "epoch", "text", "state")):
                raise SchemaError("descriptor strings")
            if type(d["cancel_generation"]) is not int or d["cancel_generation"] < 0:
                raise SchemaError("descriptor generation")
    return result


class NativeDispatcher:
    """Exclusive owner of all calls to the supplied facade, including reads."""
    def __init__(self, api=None, *, timeout=15.0, capacity=16, local=None, speech_available=False):
        self._api = api
        self.epoch = str(uuid.uuid4())
        self._timeout = timeout
        self._queue = queue.PriorityQueue(maxsize=capacity)
        self._order = itertools.count()
        self._lock = threading.Lock()
        self._closed = False
        self._revision = 0
        self._local = local
        self._local_cancel = None
        self._context_pending = False
        self._events = []
        self._comm_events = set()
        self._speech_available = speech_available
        self._worker = threading.Thread(target=self._run, name="jarvis-native-dispatch", daemon=True)
        self._worker.start()

    def _error(self, code, *, unknown=False):
        return {"ok": False, "host_epoch": self.epoch, "error": code, "outcome_unknown": unknown}

    def request(self, operation, host_epoch, text=None, origin=None):
        if host_epoch != self.epoch:
            return self._error("stale_host_epoch")
        if operation not in PERSISTENCE_OPS | {"view", "escalate", "stop", "poll", "start", "speech_started", "speech_completed", "speech_error", "speech_unknown"}:
            return self._error("capability_unavailable")
        if operation in ("record_user_turn", "record_local_answer", "select_conversation"):
            try:
                text = _json_copy(text)
                required = {"record_user_turn": {"original_text", "origin", "submission_id"},
                            "record_local_answer": {"text", "origin", "user_event_id"},
                            "select_conversation": {"conversation_id"}}[operation]
                optional = {"evidence", "completion_id"} if operation == "record_local_answer" else set()
                if type(text) is not dict or not required <= set(text) or set(text) - required - optional:
                    raise SchemaError("arguments")
                if any(type(text[k]) is not str or not text[k] for k in required):
                    raise SchemaError("arguments")
                if "origin" in text and text["origin"] not in ("krish-via-jarvis", "jarvis"):
                    raise SchemaError("origin")
                if len(text.get("original_text", text.get("text", ""))) > 16000:
                    raise SchemaError("text length")
                if "evidence" in text and type(text["evidence"]) is not list:
                    raise SchemaError("evidence")
                if "completion_id" in text and (type(text["completion_id"]) is not str or not text["completion_id"]):
                    raise SchemaError("completion_id")
            except SchemaError:
                return self._error("invalid_arguments")
        if operation.startswith("speech_"):
            if type(text) is not list or len(text) != (4 if operation == "speech_error" else 3):
                return self._error("invalid_callback")
            if any(type(v) is not str or not v for v in text[:2]) or type(text[2]) is not int or text[2] < 0:
                return self._error("invalid_callback")
            if len(text) == 4 and text[3] is not None and (type(text[3]) is not str or len(text[3]) > 64):
                return self._error("invalid_callback")
        named_escalation = operation == "escalate" and type(text) is dict
        if named_escalation:
            try:
                text = _json_copy(text)
                if set(text) - {"text", "origin", "user_event_id", "submission_id", "consultation_text"}:
                    raise SchemaError("escalation arguments")
                if text.get("origin") not in ("krish-via-jarvis", "jarvis"):
                    raise SchemaError("origin")
                if any(type(v) is not str or not v or len(v) > 16000 for v in text.values()):
                    raise SchemaError("escalation value")
                if not text.get("user_event_id") and not (text.get("text") and text.get("submission_id")):
                    raise SchemaError("submission identity")
            except SchemaError:
                return self._error("invalid_arguments")
        if operation == "escalate" and not named_escalation and (type(text) is not str or not text.strip() or len(text) > 16000):
            return self._error("invalid_text")
        if operation == "escalate" and not named_escalation:
            if type(origin) is not str or origin not in ("krish-via-jarvis", "jarvis"):
                return self._error("invalid_origin")
            text = (text, origin)
        future = Future()
        with self._lock:
            if self._closed:
                return self._error("closed")
            if operation in CONTEXT_OPS and (self._local_cancel is not None or self._context_pending):
                return self._error("busy")
            if operation == "stop" and self._local_cancel is not None:
                self._local_cancel.set()
            try:
                self._queue.put_nowait((0 if operation == "stop" else 1, next(self._order), future, operation, text))
                if operation in CONTEXT_OPS:
                    self._context_pending = True
            except queue.Full:
                return self._error("busy")
        try:
            return future.result(timeout=self._timeout)
        except TimeoutError:
            cancelled = future.cancel()
            if cancelled and operation in CONTEXT_OPS:
                with self._lock:
                    self._context_pending = False
            return self._error("queue_timeout" if cancelled else "operation_timeout",
                               unknown=not cancelled and operation != "view")

    def _run(self):
        while True:
            _, _, future, operation, text = self._queue.get()
            if operation is None:
                return
            if not future.set_running_or_notify_cancel():
                continue
            if self._api is None:
                if operation in CONTEXT_OPS:
                    with self._lock:
                        self._context_pending = False
                future.set_result(self._error("comm_unavailable"))
                continue
            try:
                result = None
                if operation == "escalate":
                    result = self._api.escalate(**text) if type(text) is dict else self._api.escalate(text[0], origin=text[1])
                elif operation.startswith("speech_"):
                    result = getattr(self._api, operation)(*text)
                elif operation in ("record_user_turn", "record_local_answer", "select_conversation"):
                    result = getattr(self._api, operation)(**text)
                elif operation != "view":
                    result = getattr(self._api, operation)()
                result = validate_result(operation, result)
                raw = self._api.view()
                view = validate_view(raw["snapshot"], raw["transcript"])
                with self._lock:
                    if not self._closed:
                        if operation in ("select_conversation", "new_conversation") and (result.get("selected") or result.get("created")):
                            self._events.clear()
                            self._comm_events.clear()
                        selected = view["snapshot"]["binding"]["conversation_id"]
                        rows = [row for row in view["transcript"]
                                if (not row.get("conversation_id") or row["conversation_id"] == selected)
                                and (not row.get("restored") or selected is not None)]
                        self._ingest_comm(rows)
                self._revision += 1
                future.set_result({"ok": True, "host_epoch": self.epoch, "revision": self._revision,
                                   "result": result, "view": view, "speech_available": self._speech_available})
            except Exception:
                # An operation may already have published before serialization failed.
                future.set_result(self._error("operation_failed", unknown=operation != "view"))
            finally:
                if operation in CONTEXT_OPS:
                    with self._lock:
                        self._context_pending = False

    def close(self, timeout=0.5):
        """Bounded shutdown; never pretend to terminate an in-flight facade call."""
        with self._lock:
            if not self._closed:
                self._closed = True
                if self._local_cancel is not None:
                    self._local_cancel.set()
                while True:
                    try:
                        item = self._queue.get_nowait()
                        # Atomically prevent timeout cancellation from racing
                        # the shutdown result; cancelled futures need no result.
                        if item[2] is not None and not item[2].done() and item[2].set_running_or_notify_cancel():
                            item[2].set_result(self._error("closed"))
                    except queue.Empty:
                        break
                self._queue.put_nowait((-1, next(self._order), None, None, None))
        self._worker.join(timeout=timeout)
        return {"closed": True, "worker_stopped": not self._worker.is_alive()}

    def local_turn(self, epoch, text):
        if type(text) is not str or not text.strip() or len(text) > 16000:
            return self._error("invalid_text")
        with self._lock:
            if epoch != self.epoch or self._closed:
                return self._error("closed_or_stale")
            if self._local is None:
                return self._error("local_unavailable")
            if self._local_cancel is not None or self._context_pending:
                return self._error("local_busy")
            cancel = self._local_cancel = threading.Event()
            history = self._history
            user_event = {"source": "local", "role": "user", "content": text, "state": "pending"}
            persistent = self._api is not None and callable(getattr(self._api, "record_user_turn", None))
            if not persistent:
                self._events.append(user_event)
        try:
            receipt = None
            if persistent:
                recorded = self.request("record_user_turn", epoch, {"original_text": text, "origin": "krish-via-jarvis",
                    "submission_id": f"{time.time_ns() // 1_000_000}-{uuid.uuid4()}"})
                if not recorded["ok"]:
                    return recorded
                receipt = recorded["result"]
                if not receipt.get("user_event_id"):
                    return {"ok": False, "host_epoch": self.epoch, "error": receipt.get("reason") or "user_turn_refused",
                            "outcome_unknown": False, "user_receipt": receipt}
                if cancel.is_set():
                    return self._error("local_cancelled")
            result = self._local.turn(text, history, cancel=cancel)
            answer_receipt = None
            if persistent and result["status"] == "reply" and not cancel.is_set():
                saved = self.request("record_local_answer", epoch, {"text": result["text"], "origin": "krish-via-jarvis",
                    "user_event_id": receipt["user_event_id"], "completion_id": f"{time.time_ns() // 1_000_000}-{uuid.uuid4()}"})
                answer_receipt = saved.get("result") if saved["ok"] else {"outcome_unknown": saved["outcome_unknown"], "error": saved["error"]}
            with self._lock:
                if self._closed or cancel.is_set():
                    user_event["state"] = "cancelled"
                    return self._error("local_cancelled")
                if result["status"] == "reply":
                    user_event["state"] = "completed"
                    if not persistent:
                        self._events.append({"source": "local", "role": "assistant", "content": result["text"], "state": "completed"})
                else:
                    user_event["state"] = result["status"]
                return {"ok": True, "host_epoch": self.epoch, "local": result,
                        "user_receipt": receipt, "answer_receipt": answer_receipt}
        except Exception:
            with self._lock:
                user_event["state"] = "failed"
            return self._error("local_failed")
        finally:
            with self._lock:
                self._local_cancel = None

    @property
    def _history(self):
        # Only role/content crosses into inference. Attribution stays in assistant
        # content, never a system/tool message or an executable instruction.
        return [{"role": e["role"], "content": e["content"]}
                for e in self._events if e["state"] == "completed"][-24:]

    def _ingest_comm(self, rows):
        """Called with the dispatcher lock after the authoritative facade view."""
        for index, row in enumerate(rows):
            if row.get("late"):
                continue
            restored = row.get("restored", False)
            origin = row.get("origin") or row["payload"].get("origin")
            if restored and row.get("terminal_state") != "completed":
                continue
            if row["kind"] == "assistant_claude":
                if row.get("terminal_state") != "completed" or not row.get("request_id"):
                    continue
                key = ("answer", row["request_id"])
                role = "assistant"
                attribution = "Claude's prior answer" if restored else "Claude's answer"
                provenance = ("; answering Krish via Jarvis" if origin == "krish-via-jarvis" else "; Jarvis asked" if origin == "jarvis" else "; origin unverified") if restored else ""
                content = attribution + " (" + (row.get("responder") or "bound peer") + provenance + "):\n" + (
                    json.dumps(row["payload"]["text"], ensure_ascii=False) if restored else row["payload"]["text"])
            elif row["kind"] == "assistant_local":
                if row.get("terminal_state") != "completed" or not row.get("event_id"):
                    continue
                key = ("local_answer", row["event_id"])
                role = "assistant"
                content = ("Jarvis's prior local answer (" + (row.get("responder") or row["payload"].get("responder") or "local") + "):\n" +
                           json.dumps(row["payload"]["text"], ensure_ascii=False)) if restored else row["payload"]["text"]
            elif row["kind"] == "user" and origin in ("krish-via-jarvis", "jarvis"):
                identity = row.get("event_id") or row.get("request_id")
                if restored and not identity:
                    continue  # Do not invent a cross-session identity from array position.
                key = ("question", identity or index)
                role = "user" if origin == "krish-via-jarvis" else "assistant"
                content = ("Prior conversation turn" if restored else "User turn" if row["payload"].get("submission_id") else "Consultation requested from Claude") + " (" + origin + "):\n" + (
                    json.dumps(row["payload"]["text"], ensure_ascii=False) if restored else row["payload"]["text"])
            else:
                continue
            if key in self._comm_events:
                continue
            self._comm_events.add(key)
            self._events.append({"source": "comm", "role": role, "content": content, "state": "completed",
                                 "request_id": row.get("request_id"), "origin": origin, "restored": restored})


class NativeApi:
    """Only this narrow surface is exposed to pywebview, never the dispatcher."""
    def __init__(self, dispatcher, microphone=None):
        self._dispatcher = dispatcher
        self._microphone = microphone
        self._close_handler = None

    def close_app(self, epoch, force=False):
        if type(force) is not bool or epoch != self._dispatcher.epoch:
            return self._dispatcher._error("invalid_close")
        if self._close_handler is None:
            return self._dispatcher._error("close_unavailable")
        return self._close_handler(epoch, force)

    def voice_start(self, epoch):
        if self._dispatcher._api is not None:
            state = self._dispatcher.request("view", epoch)
            if not state.get("ok"):
                return state
            snapshot = state["view"]["snapshot"]
            if not snapshot["binding"]["conversation_id"] or snapshot["recovery"]["state"] == "unresolved":
                return {"ok": False, "host_epoch": epoch, "error": "conversation_setup_required"}
        return self._microphone.start(epoch) if self._microphone is not None else {"ok": False, "error": "microphone_unavailable"}

    def voice_events(self, epoch):
        return self._microphone.drain(epoch) if self._microphone is not None else {"ok": False, "error": "microphone_unavailable", "events": []}

    def voice_diagnostic_start(self, epoch):
        # Explicit transcription-only page mode; no conversation or inference.
        return self._microphone.start(epoch) if self._microphone is not None else {"ok": False, "error": "microphone_unavailable"}

    def voice_stop(self, epoch):
        if epoch != self._dispatcher.epoch:
            return self._dispatcher._error("stale_host_epoch")
        result = self._microphone.close() if self._microphone is not None else {"closed": True, "worker_stopped": True}
        return {"ok": True, "host_epoch": epoch, **result}

    def view(self, epoch):
        return self._dispatcher.request("view", epoch)

    def submission_id(self, epoch):
        if epoch != self._dispatcher.epoch:
            return self._dispatcher._error("stale_host_epoch")
        return {"ok": True, "host_epoch": epoch, "submission_id": f"{time.time_ns() // 1_000_000}-{uuid.uuid4()}"}

    def record_user_turn(self, epoch, original_text, origin, submission_id):
        return self._dispatcher.request("record_user_turn", epoch, {
            "original_text": original_text, "origin": origin, "submission_id": submission_id})

    def record_local_answer(self, epoch, text, origin, user_event_id, completion_id):
        return self._dispatcher.request("record_local_answer", epoch, {
            "text": text, "origin": origin, "user_event_id": user_event_id, "completion_id": completion_id})

    def conversations(self, epoch):
        return self._dispatcher.request("conversations", epoch)

    def select_conversation(self, epoch, conversation_id):
        return self._dispatcher.request("select_conversation", epoch, {"conversation_id": conversation_id})

    def new_conversation(self, epoch):
        return self._dispatcher.request("new_conversation", epoch)

    def shutdown(self, epoch):
        return self._dispatcher.request("shutdown", epoch)

    def escalate(self, epoch, text, origin=None):
        return self._dispatcher.request("escalate", epoch, text, origin)

    def consult(self, epoch, user_event_id, origin, consultation_text):
        return self._dispatcher.request("escalate", epoch, {
            "user_event_id": user_event_id, "origin": origin, "consultation_text": consultation_text})

    def stop(self, epoch):
        return self._dispatcher.request("stop", epoch)

    def poll(self, epoch):
        return self._dispatcher.request("poll", epoch)

    def start(self, epoch):
        return self._dispatcher.request("start", epoch)

    def local_turn(self, epoch, text):
        return self._dispatcher.local_turn(epoch, text)

    def speech_started(self, host_epoch, token, epoch, generation):
        return self._dispatcher.request("speech_started", host_epoch, [token, epoch, generation])

    def speech_completed(self, host_epoch, token, epoch, generation):
        return self._dispatcher.request("speech_completed", host_epoch, [token, epoch, generation])

    def speech_error(self, host_epoch, token, epoch, generation, error=None):
        return self._dispatcher.request("speech_error", host_epoch, [token, epoch, generation, error])

    def speech_unknown(self, host_epoch, token, epoch, generation):
        return self._dispatcher.request("speech_unknown", host_epoch, [token, epoch, generation])
