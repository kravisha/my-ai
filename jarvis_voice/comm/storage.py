"""The persistence seam as consumed by communication (Dev 5825761562 confirmed shapes):

    save_completed_turn(turn)            -> {event_id, duplicate, persisted, storage}
    save_checkpoint(conversation_id, cp) -> {checkpoint_seq, persisted, storage}
    capabilities()                       -> {durable: bool, storage: str}
    load_history / load_checkpoint / recover(current_epoch)

``NoopStore`` is the in-memory/no-op adapter for the first demonstration. It reports
non-durable on every call; ``persisted`` is never true. ``consume`` is the consumer rule:
a missing or non-boolean ``persisted`` is a contract error, never success.
"""

from __future__ import annotations


class NoopStore:
    storage = "noop-demo"

    def capabilities(self) -> dict:
        return {"durable": False, "storage": self.storage}

    def save_completed_turn(self, turn: dict) -> dict:
        return {"event_id": turn.get("event_id"), "duplicate": False, "persisted": False, "storage": self.storage}

    def save_checkpoint(self, conversation_id: str, cp: dict) -> dict:
        return {"checkpoint_seq": None, "persisted": False, "storage": self.storage}

    def load_history(self, conversation_id: str, since_sequence: int = 0) -> dict:
        return {"events": [], "gaps": [], "corruption_detected": None, "version_refused": False}

    def load_checkpoint(self, conversation_id: str) -> dict:
        return {"checkpoint_available": False}

    def recover(self, current_epoch: str) -> dict:
        return {"previous_epoch": None, "stale_unresolved": [], "still_pending": [], "stray_tmp_quarantined": [],
                "history_repaired": [], "history_frozen_unsupported_major": [],
                "checkpoint_current_missing_prev_used": [], "warnings": []}


def consume(result: object) -> tuple[bool, str | None]:
    """(persisted, error). Explicit `persisted` bool or it is a contract error."""
    if not isinstance(result, dict):
        return False, "contract_error"
    p = result.get("persisted")
    if not isinstance(p, bool):
        return False, "contract_error"
    return p, None
