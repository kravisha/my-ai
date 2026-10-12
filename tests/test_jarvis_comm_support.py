"""Shared fakes and the mock-only boundary for the JARVIS-COMM-01 suite.

Every ``test_jarvis_comm_*`` module does ``from tests.test_jarvis_comm_support import *``
so the autouse ``_no_escape`` fixture below is collected into that module's namespace.
That is the C1 control from hub 5825647565 section 4, widened per Arya 5825662233:
sockets, ``subprocess`` and ``os.system`` are made to raise for the whole module, so a
test that reaches for a real listener, a real process or a real network call FAILS
instead of quietly passing as "mock-only". The boundary is enforced by mechanism, not
by intention (LESSON-20260924-DEPLOY-TESTED-MY-INTENTION).

Nothing here speaks, listens, launches, or touches GitHub.
"""

from __future__ import annotations

import os
import socket
import subprocess
import uuid
from dataclasses import dataclass, field

import pytest

from jarvis_voice.comm import canon, entry as entry_mod

__all__ = [
    "_no_escape", "FakeClock", "FakeSpeaker", "FakeAsyncSpeaker", "FakeDisplay", "FakeStore",
    "FakeGitHubClient", "peer_entry", "SELF", "PEER", "OWNER", "GRANT",
]

SELF = {"id": "claude-deploy-local", "session": "e2fcbb54", "epoch": "epoch-claude-1"}
PEER = {"id": "jarvis-local", "session": "jarvis-run-1", "epoch": "epoch-jarvis-1"}
OWNER = "Krish"
GRANT = ("5825532363", 1)


class EscapeAttempt(RuntimeError):
    """Raised by the boundary when a test tries to leave the fake world."""


@pytest.fixture(autouse=True)
def _no_escape(monkeypatch):
    def refuse(*_a, **_k):
        raise EscapeAttempt("mock-only boundary: sockets, subprocess and os.system are refused in this suite")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "create_server", refuse, raising=False)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "call", refuse)
    monkeypatch.setattr(subprocess, "check_output", refuse)
    monkeypatch.setattr(os, "system", refuse)
    yield


class FakeClock:
    def __init__(self, start: float = 1_000_000.0):
        self.t = start
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def iso(self) -> str:
        # Fixed offset so the suite is timezone-independent; RFC3339 with offset as R2 requires.
        from datetime import datetime, timedelta, timezone
        tz = timezone(timedelta(hours=-4))
        return datetime.fromtimestamp(self.t, tz).isoformat(timespec="seconds")

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


class FakeSpeaker:
    """A BLOCKING-completion speaker (stands in for System.Speech in a CLI harness): it declares
    the contract explicitly and returns "completed". The number that matters in T12/T18/T19 is
    len(spoken). ``descriptors`` keeps every emission descriptor it was handed."""

    blocking_completion = True
    playback = True

    def __init__(self):
        self.spoken: list[str] = []
        self.descriptors: list[dict] = []
        self.stopped = 0
        self.stop_hook = None

    def speak(self, descriptor: dict) -> str:
        self.descriptors.append(dict(descriptor))
        self.spoken.append(descriptor["text"])
        return "completed"

    def stop(self) -> None:
        self.stopped += 1
        if self.stop_hook:
            self.stop_hook()


class FakeAsyncSpeaker(FakeSpeaker):
    """A browser-like speaker: enqueues and returns "queued"; completion comes through callbacks."""

    blocking_completion = False

    def speak(self, descriptor: dict) -> str:
        self.descriptors.append(dict(descriptor))
        return "queued"


class FakeDisplay:
    def __init__(self):
        self.shown: list[dict] = []

    def show(self, **kw) -> None:
        self.shown.append(dict(kw))


@dataclass
class FakeStore:
    """Dev's five functions with the shapes from hub 5825713366 / 5825719873.

    ``fail`` holds the next call names that must raise; ``bad_shape`` makes a save
    return something that is not the agreed dict (T13/T21 contract-error path).
    Everything is in memory; ``durable`` is what capabilities() reports.
    """

    durable: bool = True
    storage: str = "fake-file"
    fail: list[str] = field(default_factory=list)
    bad_shape: list[str] = field(default_factory=list)
    turns: dict[str, list[dict]] = field(default_factory=dict)
    checkpoints: dict[str, dict] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    seq: int = 0

    def _maybe_fail(self, name: str):
        self.calls.append(name)
        if name in self.fail:
            self.fail.remove(name)
            raise OSError(f"injected failure in {name}")

    def capabilities(self) -> dict:
        return {"durable": self.durable, "storage": self.storage}

    def save_completed_turn(self, turn: dict) -> dict:
        self._maybe_fail("save_completed_turn")
        if "save_completed_turn" in self.bad_shape:
            return 42  # not a dict: the consumer must treat this as a contract error
        events = self.turns.setdefault(turn["conversation_id"], [])
        for e in events:
            if e["event_id"] == turn["event_id"]:
                if canon.fingerprint(e) == canon.fingerprint(turn):
                    return {"event_id": turn["event_id"], "duplicate": True, "persisted": True, "storage": self.storage}
                raise ValueError("ConflictError: same event_id, different content")
        events.append(dict(turn))
        return {"event_id": turn["event_id"], "duplicate": False, "persisted": True, "storage": self.storage}

    def save_checkpoint(self, conversation_id: str, cp: dict) -> dict:
        self._maybe_fail("save_checkpoint")
        if "save_checkpoint" in self.bad_shape:
            return 7  # the FileStore-int shape Arya flagged in 5825710656; must be refused
        self.seq += 1
        self.checkpoints[conversation_id] = dict(cp, checkpoint_seq=self.seq)
        return {"checkpoint_seq": self.seq, "persisted": True, "storage": self.storage}

    def load_history(self, conversation_id: str, since_sequence: int = 0) -> dict:
        events = [dict(e, restored=True) for e in self.turns.get(conversation_id, []) if e["sequence"] > since_sequence]
        seqs = sorted(e["sequence"] for e in events)
        gaps = [s for s in range(1, (seqs[-1] if seqs else 0) + 1) if s not in seqs]
        return {"events": events, "gaps": gaps, "corruption_detected": None, "version_refused": False}

    def load_checkpoint(self, conversation_id: str) -> dict:
        cp = self.checkpoints.get(conversation_id)
        if cp is None:
            return {"checkpoint_available": False}
        return {"checkpoint_available": True, "checkpoint": dict(cp)}

    def recover(self, current_epoch: str) -> dict:
        stale, still = [], []
        for cid, cp in self.checkpoints.items():
            for p in cp.get("pending", []):
                item = {"request_id": p["request_id"], "epoch": p["epoch"], "conversation_id": cid,
                        "turn_sequence": p.get("turn_sequence")}
                if p["epoch"] != current_epoch:
                    stale.append(dict(item, state="stale_unresolved"))
                else:
                    still.append(dict(item, state=p.get("state", "awaiting_reply")))
        prev = None
        for cp in self.checkpoints.values():
            prev = cp.get("epoch", prev)
        return {"previous_epoch": prev, "stale_unresolved": stale, "still_pending": still,
                "stray_tmp_quarantined": [], "history_repaired": [], "history_frozen_unsupported_major": [],
                "checkpoint_current_missing_prev_used": [], "warnings": []}


class FakeGitHubClient:
    """An in-memory stand-in for the two Contents API calls the GitHub plane makes.

    ``conflicts_before_ok`` makes that many PUTs return a 409 first (T03/T04);
    ``lose_next_response`` makes one PUT apply the write and then raise (T02: server
    accepted, client never saw it).
    """

    def __init__(self, text: str = ""):
        self._text = text
        self.blob = "blob0"
        self.etag = '"etag0"'
        self.version = 0
        self.conflicts_before_ok = 0
        self.lose_next_response = False
        self.get_calls = 0
        self.put_calls = 0
        self.peer_appends: list[str] = []  # text a "peer" appends between our GET and PUT

    @property
    def text(self) -> str:
        return self._text

    @text.setter
    def text(self, value: str) -> None:
        # Any change to the file is a new revision: new blob SHA, new ETag. A fake that let
        # the bytes change under an unchanged ETag would make a 304 lie.
        if value != self._text:
            self._text = value
            self._bump()

    def _bump(self):
        self.version += 1
        self.blob = f"blob{self.version}"
        self.etag = f'"etag{self.version}"'

    def get(self, etag: str | None):
        self.get_calls += 1
        if etag == self.etag:
            return 304, self.etag, self.blob, None
        return 200, self.etag, self.blob, self.text

    def put(self, sha: str, text: str, message: str):
        self.put_calls += 1
        if self.peer_appends:
            self.text = self.text + self.peer_appends.pop(0)
        if self.conflicts_before_ok > 0:
            self.conflicts_before_ok -= 1
            return 409, None, None
        if sha != self.blob:
            return 409, None, None
        self.text = text
        if self.lose_next_response:
            self.lose_next_response = False
            raise TimeoutError("response lost after the server applied the write")
        return 200, f"commit{self.version}", self.blob


def peer_entry(clock: FakeClock, *, type_: str, body: str, to=None, reply_to=(), conversation_id=None,
               sequence=1, epoch=None, from_=None, evidence=None, message_id=None) -> dict:
    return entry_mod.make_entry(
        message_id=message_id or str(uuid.uuid4()),
        conversation_id=conversation_id or str(uuid.uuid4()),
        sequence=sequence, created_at=clock.iso(),
        from_=from_ or PEER["id"], session_id=PEER["session"], epoch=epoch or PEER["epoch"],
        to=list(to or [SELF["id"]]), owner=OWNER, grant_id=GRANT[0], grant_revision=GRANT[1],
        type_=type_, reply_to=list(reply_to), task_id=None, body=body, evidence=list(evidence or []),
    )


def test_control_C1_socket_is_refused():
    with pytest.raises(EscapeAttempt):
        socket.socket()


def test_control_C1_subprocess_and_os_system_are_refused():
    with pytest.raises(EscapeAttempt):
        subprocess.run(["python", "-c", "pass"])
    with pytest.raises(EscapeAttempt):
        os.system("echo escaped")
