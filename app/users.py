"""User accounts: registration and authentication, backed by users.json.

Same DI shape as permissions.py/privacy_preferences.py - storage lives behind
a constructor `path`, so callers never touch the file format directly and a
future swap to a real DB wouldn't change any call site.

Usernames are normalized to lowercase and restricted to a small charset
because a username becomes a filesystem directory name (user_data/<username>/)
- unrestricted input would be a path-traversal risk, and Windows' NTFS is
case-insensitive so "Alice" and "alice" must not be treated as different
accounts.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import bcrypt

USERS_PATH = Path(__file__).resolve().parent.parent / "users.json"
USER_DATA_ROOT = Path(__file__).resolve().parent.parent / "user_data"

USERNAME_RE = re.compile(r"^[a-z0-9_-]{1,32}$")


class UserStore:
    def __init__(self, path: Path = USERS_PATH):
        self.path = path
        self._state = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    def register(self, username: str, password: str) -> str:
        normalized = normalize_username(username)
        if not USERNAME_RE.match(normalized):
            raise ValueError(
                "Username must be 1-32 characters, lowercase letters/digits/underscore/hyphen only."
            )
        if normalized in self._state:
            raise ValueError(f"Username already exists: {normalized}")
        self._state[normalized] = {
            "password_hash": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save()
        return normalized

    def authenticate(self, username: str, password: str) -> bool:
        entry = self._state.get(normalize_username(username))
        if entry is None:
            return False
        return bcrypt.checkpw(password.encode(), entry["password_hash"].encode())

    def exists(self, username: str) -> bool:
        return normalize_username(username) in self._state


def normalize_username(username: str) -> str:
    return username.strip().lower()


def ensure_user_data_dir(username: str, root: Path = USER_DATA_ROOT) -> Path:
    user_dir = root / normalize_username(username)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir
