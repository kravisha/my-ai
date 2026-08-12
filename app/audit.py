"""Append-only audit log of every access attempt My AI makes to a local resource.

A class rather than a bare module function so that per-user isolation is
representable: two users' audit logs need to be two simultaneously-live
destinations (two AuditLog instances with different paths), not one global
path swapped in and out.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

AUDIT_LOG_PATH = Path(__file__).resolve().parent.parent / "audit_log.jsonl"


class AuditLog:
    def __init__(self, path: Path = AUDIT_LOG_PATH):
        self.path = path

    def record(self, action: str, resource: str, authorized: bool, result: str) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "resource": resource,
            "authorized": authorized,
            "result": result,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
