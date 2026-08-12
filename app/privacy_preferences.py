"""Learned, reviewable privacy preferences (Master Spec §7-8 / Addendum 1 §11-12).

Distinct from permissions.py: PermissionManager governs whether MY AI may
touch a resource at all (layer 1). This store governs whether data already
read from that resource may be *forwarded* to an external service (layer 2)
- keyed per resource/field-group/service, e.g. "portfolio_holdings:reasoning_model".

"The AI manages data placement. The user manages trust." - every disposition
here is a trust decision the user made explicitly, always inspectable
(list_all) and reversible (forget), never inferred or silently escalated.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

PREFERENCES_PATH = Path(__file__).resolve().parent.parent / "privacy_preferences.json"

VALID_DISPOSITIONS = ("always", "never")


class PrivacyPreferenceStore:
    def __init__(self, path: Path = PREFERENCES_PATH):
        self.path = path
        self._state = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    def set(self, key: str, disposition: str) -> None:
        if disposition not in VALID_DISPOSITIONS:
            raise ValueError(f"Invalid disposition: {disposition}")
        self._state[key] = {
            "disposition": disposition,
            "set_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save()

    def get(self, key: str) -> str | None:
        entry = self._state.get(key)
        return entry["disposition"] if entry else None

    def forget(self, key: str) -> bool:
        if key in self._state:
            del self._state[key]
            self._save()
            return True
        return False

    def list_all(self) -> dict:
        return {key: dict(entry) for key, entry in self._state.items()}
