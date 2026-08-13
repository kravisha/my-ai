"""In-memory, process-lifetime conversation log for the server monitor
(monitor/app.py). Deliberately not persisted to disk - this is a live
"what's happening right now" view, not a permanent record (the existing
per-user audit_log.jsonl already serves as the permanent record, but only
for tool *access* attempts, not full chat text). Restarting the backend
clears it.

Keyed by username, not session/token - two clients logged in as the same
account show up as one entry with merged messages, matching how
permissions/preferences are already scoped per-user rather than per-session.
"""

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class TranscriptEntry:
    role: str  # "user" | "assistant"
    text: str
    timestamp: str


class TranscriptStore:
    def __init__(self):
        self._entries: dict[str, list[TranscriptEntry]] = {}

    def record(self, username: str, role: str, text: str) -> None:
        self._entries.setdefault(username, []).append(
            TranscriptEntry(role=role, text=text, timestamp=datetime.now(timezone.utc).isoformat())
        )

    def list_clients(self) -> list[str]:
        return sorted(self._entries.keys())

    def get_transcript(self, username: str) -> list[dict]:
        return [
            {"role": entry.role, "text": entry.text, "timestamp": entry.timestamp}
            for entry in self._entries.get(username, [])
        ]
