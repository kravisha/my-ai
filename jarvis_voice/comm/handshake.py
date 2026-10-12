"""Session-bound relationship: both epochs bound through CHECK_IN, so a stale handshake
cannot rebind a current peer and an entry from a superseded epoch is never current.

Sender epoch is the R2 ``epoch`` field. Recipient epoch travels as
``evidence: [{"kind": "peer_epoch", "value": <the epoch the sender is addressing>}]``.

Two shapes of CHECK_IN exist. The INITIAL one (no ``reply_to``) comes from the side that
starts the handshake and cannot yet know the other side's epoch; it may only bind an
UNBOUND relationship. The ANSWERING one replies to the peer's current CHECK_IN and names
the epoch it is addressing; it is the only shape that may (re)bind once a relationship is
bound, and only from the same peer.
"""

from __future__ import annotations

from dataclasses import dataclass


def peer_epoch_of(entry: dict) -> str | None:
    for ev in entry.get("evidence", []):
        if isinstance(ev, dict) and ev.get("kind") == "peer_epoch":
            return ev.get("value")
    return None


@dataclass
class Relationship:
    self_id: str
    self_session: str
    self_epoch: str
    peer_id: str | None = None
    peer_session: str | None = None
    peer_epoch: str | None = None
    bound: bool = False
    my_check_in_id: str | None = None
    peer_check_in_id: str | None = None

    def bind(self, entry: dict) -> tuple[bool, str]:
        if entry.get("type") != "CHECK_IN":
            return False, "not a CHECK_IN"
        if self.self_id not in entry.get("to", []):
            return False, "not addressed to me"
        addressed = peer_epoch_of(entry)
        initial = not entry.get("reply_to")
        if self.bound:
            if entry["from"] != self.peer_id:
                return False, f"already bound to {self.peer_id}"
            if addressed != self.self_epoch:
                return False, f"addressed to epoch {addressed!r}, mine is {self.self_epoch!r}"
            if not self.my_check_in_id or self.my_check_in_id not in entry.get("reply_to", []):
                return False, "does not reply to my current CHECK_IN"
        elif initial:
            if addressed is not None and addressed != self.self_epoch:
                return False, f"addressed to epoch {addressed!r}, mine is {self.self_epoch!r}"
            if self.peer_id is not None and entry["from"] != self.peer_id:
                return False, f"expected peer {self.peer_id}, got {entry['from']}"
        else:
            if addressed != self.self_epoch:
                return False, f"addressed to epoch {addressed!r}, mine is {self.self_epoch!r}"
            if not self.my_check_in_id or self.my_check_in_id not in entry.get("reply_to", []):
                return False, "does not reply to my current CHECK_IN"
            if self.peer_id is not None and entry["from"] != self.peer_id:
                return False, f"expected peer {self.peer_id}, got {entry['from']}"
        self.peer_id = entry["from"]
        self.peer_session = entry["session_id"]
        self.peer_epoch = entry["epoch"]
        self.peer_check_in_id = entry["message_id"]
        self.bound = True
        return True, "bound"

    def is_current(self, entry: dict) -> tuple[bool, str]:
        if not self.bound:
            return False, "unbound"
        if entry.get("from") != self.peer_id:
            return False, "sender"
        if entry.get("epoch") != self.peer_epoch:
            return False, "epoch"
        if self.self_id not in entry.get("to", []):
            return False, "recipient"
        addressed = peer_epoch_of(entry)
        if addressed is not None and addressed != self.self_epoch:
            return False, "epoch"
        return True, "current"
