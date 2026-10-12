"""Read loop, R2 README section "Read loop, recovery and wake boundary".

A 304 is no new bytes, not no obligations. A 200 is parsed, compared with the accounted
set, unseen ids consumed once, conflicts and malformed blocks retained, sequence gaps kept.
The read cursor never advances from one's own publication. Detection and actual reading
have separate timestamps; ``ack`` is the actual read.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import entry as entry_mod, plane as P


@dataclass
class ReadResult:
    status: str
    new_entries: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    malformed: list[dict] = field(default_factory=list)
    gaps: list[dict] = field(default_factory=list)
    reread: bool = False
    detail: str = ""


class Reader:
    def __init__(self, plane, ledger, *, self_id: str, clock):
        self.plane = plane
        self.ledger = ledger
        self.self_id = self_id
        self.clock = clock

    def read(self) -> ReadResult:
        cursor = self.ledger.cursor()
        reread = cursor is None
        f = self.plane.fetch(cursor)
        if f.status == P.FAILED:
            return ReadResult("failed", detail=f.detail)
        if f.status == P.UNCHANGED:
            return ReadResult("unchanged")
        parsed = entry_mod.parse(f.text or "")
        res = ReadResult("changed", reread=reread)
        for m in parsed.malformed:
            self.ledger.record_malformed(m.heading_id, m.reason)
            res.malformed.append({"heading_id": m.heading_id, "reason": m.reason})
        for p in parsed.entries:
            e = p.entry
            if e["from"] == self.self_id:
                self.ledger.record_own(e["message_id"], p.sha256)
                continue
            outcome = self.ledger.record_seen(e["message_id"], p.sha256)
            if outcome == "new":
                self.ledger.note_sequence((e["from"], e["session_id"], e["conversation_id"]), e["sequence"])
                res.new_entries.append(e)
            elif outcome == "conflict":
                res.conflicts.append({"message_id": e["message_id"], "sha256": p.sha256})
        res.gaps = self.ledger.gaps()
        self.ledger.set_cursor(f.cursor)
        return res

    def ack(self, message_ids: list[str]) -> None:
        now = self.clock.iso()
        for mid in message_ids:
            self.ledger.ack(mid, now)
        self.ledger.save()
