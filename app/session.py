"""Persisted local session, matching vibe-agent's login pattern (bcrypt auth +
a token with an expiry) but adapted to a single local CLI process instead of
a multi-request server: there is exactly one active session on this machine
at a time, so the store holds one record, not a keyed table.

Re-running `python -m app.main` with a still-valid session skips the login
prompt entirely, the way `gh`/`aws`/`docker`/`gcloud` persist a local
credential instead of re-authenticating on every invocation.
"""

import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

SESSION_PATH = Path(__file__).resolve().parent.parent / "session.json"
SESSION_LIFETIME = timedelta(days=7)


class SessionStore:
    def __init__(self, path: Path = SESSION_PATH, lifetime: timedelta = SESSION_LIFETIME):
        self.path = path
        self.lifetime = lifetime

    def create(self, username: str) -> str:
        token = secrets.token_urlsafe(32)
        record = {
            "username": username,
            "token": token,
            "expires_at": (datetime.now(timezone.utc) + self.lifetime).isoformat(),
        }
        self.path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return token

    def validate(self) -> str | None:
        if not self.path.exists():
            return None
        try:
            record = json.loads(self.path.read_text(encoding="utf-8"))
            expires_at = datetime.fromisoformat(record["expires_at"])
            username = record["username"]
        except (json.JSONDecodeError, KeyError, ValueError):
            return None
        if expires_at < datetime.now(timezone.utc):
            return None
        return username

    def revoke(self) -> None:
        self.path.unlink(missing_ok=True)
