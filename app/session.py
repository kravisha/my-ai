"""Server-side session store: many concurrently-valid tokens (one per logged
-in client), matching vibe-agent's DB-backed Session table shape but as a
JSON file, consistent with the rest of this project's storage. Every
protected backend route resolves the caller via validate(token), the way
vibe-agent's get_current_business() resolves a request via
validate_session(db, token).
"""

import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

SESSION_PATH = Path(__file__).resolve().parent.parent / "sessions.json"
SESSION_LIFETIME = timedelta(days=7)


class SessionStore:
    def __init__(self, path: Path = SESSION_PATH, lifetime: timedelta = SESSION_LIFETIME):
        self.path = path
        self.lifetime = lifetime

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _save(self, state: dict) -> None:
        self.path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def create(self, username: str) -> str:
        state = self._load()
        token = secrets.token_urlsafe(32)
        state[token] = {
            "username": username,
            "expires_at": (datetime.now(timezone.utc) + self.lifetime).isoformat(),
        }
        self._save(state)
        return token

    def validate(self, token: str) -> str | None:
        state = self._load()
        record = state.get(token)
        if record is None:
            return None
        try:
            expires_at = datetime.fromisoformat(record["expires_at"])
            username = record["username"]
        except (KeyError, ValueError):
            return None
        if expires_at < datetime.now(timezone.utc):
            return None
        return username

    def revoke(self, token: str) -> None:
        state = self._load()
        if token in state:
            del state[token]
            self._save(state)
