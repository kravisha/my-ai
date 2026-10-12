"""Read/task ledger: transport cursor, accounted ids with hashes, own publications, pending
unread ids, actual read receipts, conflicts, malformed blocks and sequence gaps.
Persisted atomically; a lost cursor means a full reread with dedup, never a replay."""

from __future__ import annotations

import json
from pathlib import Path

from . import fsatomic


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = {
            "cursor": None, "seen": {}, "own": [], "pending_unread": [], "receipts": {},
            "conflicts": [], "malformed": [], "gaps": [], "last_sequence": {},
        }
        if self.path.exists():
            self.state.update(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self) -> None:
        fsatomic.write_atomic(self.path, json.dumps(self.state, sort_keys=True, indent=1, ensure_ascii=False).encode("utf-8"))

    # -- cursor --------------------------------------------------------------------
    def cursor(self):
        return self.state["cursor"]

    def set_cursor(self, cursor) -> None:
        self.state["cursor"] = cursor
        self.save()

    def forget_cursor(self) -> None:
        self.state["cursor"] = None
        self.save()

    # -- ids ------------------------------------------------------------------------
    def record_seen(self, message_id: str, sha256: str) -> str:
        prev = self.state["seen"].get(message_id)
        if prev is None:
            self.state["seen"][message_id] = sha256
            if message_id not in self.state["own"]:
                self.state["pending_unread"].append(message_id)
            return "new"
        if prev == sha256:
            return "dup"
        self.state["conflicts"].append({"message_id": message_id, "sha256_seen": prev, "sha256_now": sha256})
        return "conflict"

    def record_own(self, message_id: str, sha256: str) -> None:
        if message_id not in self.state["own"]:
            self.state["own"].append(message_id)
        self.state["seen"].setdefault(message_id, sha256)
        if message_id in self.state["pending_unread"]:
            self.state["pending_unread"].remove(message_id)
        self.save()

    def accounted_ids(self) -> list[str]:
        return list(self.state["seen"])

    def own_ids(self) -> list[str]:
        return list(self.state["own"])

    def pending_unread(self) -> list[str]:
        return list(self.state["pending_unread"])

    def ack(self, message_id: str, read_at: str) -> None:
        if message_id not in self.state["seen"]:
            raise KeyError(f"cannot ACK an id never read: {message_id}")
        self.state["receipts"][message_id] = {"read_at": read_at, "sha256": self.state["seen"][message_id]}
        if message_id in self.state["pending_unread"]:
            self.state["pending_unread"].remove(message_id)

    def receipts(self) -> dict:
        return dict(self.state["receipts"])

    def conflicts(self) -> list[dict]:
        return list(self.state["conflicts"])

    def record_malformed(self, heading_id: str, reason: str) -> None:
        if not any(m["heading_id"] == heading_id and m["reason"] == reason for m in self.state["malformed"]):
            self.state["malformed"].append({"heading_id": heading_id, "reason": reason})

    def malformed(self) -> list[dict]:
        return list(self.state["malformed"])

    def note_sequence(self, key: tuple[str, str, str], sequence: int) -> None:
        k = "|".join(key)
        seqs = self.state["last_sequence"].setdefault(k, [])
        if sequence not in seqs:
            seqs.append(sequence)
            seqs.sort()
        missing = [s for s in range(1, seqs[-1] + 1) if s not in seqs]
        self.state["gaps"] = [g for g in self.state["gaps"] if g["key"] != k]
        if missing:
            self.state["gaps"].append({"key": k, "from": key[0], "session_id": key[1], "conversation_id": key[2], "missing": missing})

    def gaps(self) -> list[dict]:
        return [{k: v for k, v in g.items() if k != "key"} for g in self.state["gaps"]]

    # -- conversations this participant took part in (so recover() can find them after a restart) --
    def note_conversation(self, conversation_id: str) -> None:
        convs = self.state.setdefault("conversations", [])
        if conversation_id not in convs:
            convs.append(conversation_id)
            self.save()

    def conversations(self) -> list[str]:
        return list(self.state.get("conversations", []))

    # -- submission ids (exact-once horizon that does not depend on the store's checkpoint) --
    def note_submission(self, submission_id: str, *, keep: int = 100) -> None:
        subs = self.state.setdefault("submissions", [])
        if submission_id not in subs:
            subs.append(submission_id)
            del subs[:-keep]
            self.save()

    def submissions(self) -> list[str]:
        return list(self.state.get("submissions", []))
