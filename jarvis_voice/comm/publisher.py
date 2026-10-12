"""Safe concurrent publication, R2 README section "Safe concurrent file publication", steps 1-7.

Outbox first. GET and verify. Reconcile by id+hash. Append preserving every byte. PUT as a
compare-and-swap. Read back and locate the id+hash before calling it delivered. Three PUT
attempts, 1 s then 2 s backoff. A lost response is delivery UNKNOWN and is reconciled by a
later GET with the same bytes, never re-executed. 750 KiB pauses for an owner decision.
"""

from __future__ import annotations

from . import canon, entry as entry_mod, plane as P

MAX_FILE_BYTES = 750 * 1024
MAX_ATTEMPTS = 3
BACKOFF = (1, 2)


class Publisher:
    def __init__(self, plane, outbox, ledger, *, sleep, clock, max_file_bytes: int = MAX_FILE_BYTES):
        self.plane = plane
        self.outbox = outbox
        self.ledger = ledger
        self.sleep = sleep
        self.clock = clock
        self.max_file_bytes = max_file_bytes

    def _locate(self, text: str, message_id: str, sha256: str):
        parsed = entry_mod.parse(text)
        hits = [p for p in parsed.entries if p.entry["message_id"] == message_id]
        return parsed, hits, [h for h in hits if h.sha256 == sha256]

    def publish(self, entry: dict) -> P.PublishResult:
        mid = entry.get("message_id", "?")
        errs = entry_mod.validate(entry)
        if errs:
            return P.PublishResult(P.BLOCKED, mid, detail="invalid entry: " + "; ".join(errs))
        sha = canon.fingerprint(entry)
        now = self.clock.iso()
        rec = self.outbox.get(mid)
        if rec is None:
            self.outbox.stage(entry, destination=self.plane.name, base_cursor=None, staged_at=now)  # step 1
        elif rec["sha256"] != sha:
            return P.PublishResult(P.BLOCKED, mid, sha, detail="outbox holds the same message_id with different bytes")
        attempts = 0
        rendered = entry_mod.render(entry)
        while True:
            f = self.plane.fetch(None)  # step 2: full current bytes and the revision to swap against
            if f.status == P.FAILED:
                self.outbox.mark(mid, "unknown", at=self.clock.iso(), detail=f"read failed: {f.detail}")
                return P.PublishResult(P.DELIVERY_UNKNOWN, mid, sha, attempts, detail=f"read failed: {f.detail}")
            text = f.text or ""
            parsed, hits, exact = self._locate(text, mid, sha)
            if len(exact) == 1 and len(hits) == 1:  # step 3: already delivered
                self.outbox.mark(mid, "delivered", at=self.clock.iso(), detail="reconciled by id+hash")
                self.ledger.record_own(mid, sha)
                return P.PublishResult(P.DELIVERED_VERIFIED, mid, sha, attempts, detail="reconciled by id+hash")
            if hits:
                self.outbox.mark(mid, "id_conflict", at=self.clock.iso(), detail="same message_id with different content")
                return P.PublishResult(P.CONFLICT, mid, sha, attempts, detail="same message_id already present with different content")
            if parsed.malformed:
                self.outbox.mark(mid, "blocked", at=self.clock.iso(), detail="malformed history")
                return P.PublishResult(P.BLOCKED, mid, sha, attempts, detail=f"malformed R2 history ({len(parsed.malformed)} block(s)) blocks the write")
            sep = "" if (text == "" or text.endswith("\n")) else "\n"
            new_text = text + sep + rendered
            if len(new_text.encode("utf-8")) > self.max_file_bytes:
                self.outbox.mark(mid, "blocked", at=self.clock.iso(), detail="750 KiB retention decision")
                return P.PublishResult(P.BLOCKED, mid, sha, attempts, detail="file at 750 KiB: owner retention decision required, no rotation")
            attempts += 1
            put = self.plane.put(f.cursor, new_text, message=f"R2 {entry['type']} {mid}")  # step 4
            if put.status == P.PUT_OK:
                rb = self.plane.fetch(None)  # step 5: readback
                if rb.status == P.CHANGED:
                    _, hits2, exact2 = self._locate(rb.text or "", mid, sha)
                    if len(exact2) == 1 and len(hits2) == 1:
                        self.outbox.mark(mid, "delivered", at=self.clock.iso(), detail="readback located id+hash", commit=put.commit)
                        self.ledger.record_own(mid, sha)
                        return P.PublishResult(P.DELIVERED_VERIFIED, mid, sha, attempts, commit=put.commit,
                                               detail="readback located id+hash")
                self.outbox.mark(mid, "unknown", at=self.clock.iso(), detail="put ok but readback did not locate id+hash")
                return P.PublishResult(P.DELIVERY_UNKNOWN, mid, sha, attempts, commit=put.commit,
                                       detail="put ok but readback did not locate id+hash")
            if put.status == P.PUT_UNKNOWN:  # step 7
                self.outbox.mark(mid, "unknown", at=self.clock.iso(), detail=f"lost response: {put.detail}")
                return P.PublishResult(P.DELIVERY_UNKNOWN, mid, sha, attempts, detail=f"lost response ({put.detail}); reconcile by GET before any retry")
            if put.status == P.PUT_FAILED:
                self.outbox.mark(mid, "blocked", at=self.clock.iso(), detail=put.detail)
                return P.PublishResult(P.BLOCKED, mid, sha, attempts, detail=put.detail)
            # PUT_CONFLICT: step 6
            if attempts >= MAX_ATTEMPTS:
                self.outbox.mark(mid, "pending_conflict", at=self.clock.iso(), detail="3 attempts exhausted")
                return P.PublishResult(P.CONFLICT, mid, sha, attempts, detail="concurrent-write conflict: 3 attempts exhausted, pending conflict visible")
            self.sleep(BACKOFF[min(attempts - 1, len(BACKOFF) - 1)])
