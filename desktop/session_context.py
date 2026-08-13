"""The desktop app's equivalent of app.main.main()'s per-user setup: given an
authenticated username, build the same three per-user stores the CLI
constructs, plus a running conversation. Bundled into one object so it can
be handed between screens the way vibe-agent hands its APIClient around -
here there's no HTTP token to hold, just the local stores themselves.
"""

from dataclasses import dataclass, field

from app.audit import AuditLog
from app.permissions import PermissionManager
from app.privacy_preferences import PrivacyPreferenceStore
from app.users import ensure_user_data_dir


@dataclass
class AppSession:
    username: str
    permissions: PermissionManager
    preferences: PrivacyPreferenceStore
    audit_log: AuditLog
    messages: list = field(default_factory=list)


def build_session(username: str) -> AppSession:
    user_dir = ensure_user_data_dir(username)
    return AppSession(
        username=username,
        permissions=PermissionManager(path=user_dir / "permissions.json"),
        preferences=PrivacyPreferenceStore(path=user_dir / "privacy_preferences.json"),
        audit_log=AuditLog(path=user_dir / "audit_log.jsonl"),
    )
