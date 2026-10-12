"""Durable outbox: the exact intended entry, its id and hash, persisted BEFORE any network
write. Staging is not delivery. Records survive a crash and are what reconciliation
reads after a lost response."""

from __future__ import annotations

import json
from pathlib import Path

from . import canon, fsatomic


def _atomic_write(path: Path, obj: dict) -> None:
    fsatomic.write_atomic(path, json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=False).encode("utf-8"))


class Outbox:
    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _p(self, message_id: str) -> Path:
        return self.dir / f"{message_id}.json"

    def stage(self, entry: dict, *, destination: str, base_cursor: dict | None, staged_at: str) -> dict:
        rec = {"message_id": entry["message_id"], "sha256": canon.fingerprint(entry), "entry": entry,
               "destination": destination, "base_cursor": base_cursor, "status": "staged",
               "staged_at": staged_at, "history": [{"at": staged_at, "status": "staged"}]}
        _atomic_write(self._p(entry["message_id"]), rec)
        return rec

    def mark(self, message_id: str, status: str, *, at: str, detail: str = "", commit: str | None = None) -> dict:
        rec = self.get(message_id)
        if rec is None:
            raise KeyError(message_id)
        rec["status"] = status
        rec["history"].append({"at": at, "status": status, "detail": detail, "commit": commit})
        if commit:
            rec["commit"] = commit
        _atomic_write(self._p(message_id), rec)
        return rec

    def get(self, message_id: str) -> dict | None:
        p = self._p(message_id)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def pending(self) -> list[dict]:
        out = []
        for p in sorted(self.dir.glob("*.json")):
            rec = json.loads(p.read_text(encoding="utf-8"))
            if rec["status"] not in ("delivered", "blocked"):
                out.append(rec)
        return out
