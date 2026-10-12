"""Status, each state from its own source only. Silence is waiting, never a diagnosis.

Sources are explicit strings so the UI can show where a state came from. A state whose
source cannot supply it (a "limit" without a participant/client report) is refused.
"""

from __future__ import annotations


class StatusError(ValueError):
    pass


REQUEST_STATES = {
    "local": {"local"},
    "queued": {"outbox"},
    "publication-unknown": {"publisher"},
    "delivered": {"readback"},
    "read": {"peer_ack"},
    "accepted": {"peer_report"},
    "processing": {"peer_report"},
    "waiting": {"silence"},
    "result-received": {"reader"},
    "completed": {"terminal"},
    "approval-needed": {"peer_report"},
    "limit": {"peer_report"},
    "error": {"terminal", "publisher", "peer_report"},
    "cancelled": {"local_stop", "terminal"},
    "conflict": {"publisher"},
    "blocked": {"publisher"},
}


class Status:
    def __init__(self):
        self._s: dict[str, dict] = {}

    def set(self, key: str, state: str, *, source: str) -> None:
        if key == "request":
            allowed = REQUEST_STATES.get(state)
            if allowed is None:
                raise StatusError(f"unknown request state {state!r}")
            if source not in allowed:
                raise StatusError(f"request state {state!r} cannot come from source {source!r}; allowed {sorted(allowed)}")
        self._s[key] = {"state": state, "source": source}

    def get(self, key: str) -> str | None:
        v = self._s.get(key)
        return v["state"] if v else None

    def source(self, key: str) -> str | None:
        v = self._s.get(key)
        return v["source"] if v else None

    def clear(self, key: str) -> None:
        self._s.pop(key, None)

    def snapshot(self) -> dict:
        return {k: dict(v) for k, v in self._s.items()}
