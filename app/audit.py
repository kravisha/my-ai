"""Append-only audit log of every access attempt My AI makes to a local resource."""

import json
from datetime import datetime, timezone
from pathlib import Path

AUDIT_LOG_PATH = Path(__file__).resolve().parent.parent / "audit_log.jsonl"


def record(action: str, resource: str, authorized: bool, result: str) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "resource": resource,
        "authorized": authorized,
        "result": result,
    }
    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
