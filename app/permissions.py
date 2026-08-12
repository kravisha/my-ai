"""Permission Manager: tracks which local resources My AI is allowed to access.

Grants/revocations are explicit user actions (CLI commands), never inferred
from conversation. State persists to permissions.json so it survives restarts.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

PERMISSIONS_PATH = Path(__file__).resolve().parent.parent / "permissions.json"

RESOURCE_PATHS = {
    "portfolio": Path(__file__).resolve().parent.parent / "data" / "portfolio.xlsx",
}


class PermissionManager:
    def __init__(self, path: Path = PERMISSIONS_PATH):
        self.path = path
        self._state = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    def grant(self, resource: str) -> None:
        if resource not in RESOURCE_PATHS:
            raise ValueError(f"Unknown resource: {resource}")
        self._state[resource] = {
            "status": "granted",
            "granted_at": datetime.now(timezone.utc).isoformat(),
            "resource_path": str(RESOURCE_PATHS[resource]),
        }
        self._save()

    def revoke(self, resource: str) -> None:
        if resource not in RESOURCE_PATHS:
            raise ValueError(f"Unknown resource: {resource}")
        entry = self._state.get(resource, {"resource_path": str(RESOURCE_PATHS[resource])})
        entry["status"] = "revoked"
        self._state[resource] = entry
        self._save()

    def is_granted(self, resource: str) -> bool:
        entry = self._state.get(resource)
        return bool(entry and entry.get("status") == "granted")
