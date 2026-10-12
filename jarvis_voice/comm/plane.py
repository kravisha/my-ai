"""The message-plane interface. Two implementations: the R2 GitHub file (authoritative
design) and a same-machine spool (compatible adapter for the first demo and for fakes).

A plane moves bytes and reports exactly what it observed. It never decides what an
entry means. Cursors are opaque dicts owned by the plane.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

# publish outcomes (Publisher)
DELIVERED_VERIFIED = "delivered_verified"
DELIVERY_UNKNOWN = "delivery_unknown"
CONFLICT = "conflict"
BLOCKED = "blocked"

# put outcomes (plane level)
PUT_OK = "ok"
PUT_CONFLICT = "put_conflict"
PUT_UNKNOWN = "put_unknown"
PUT_FAILED = "put_failed"

# fetch outcomes
UNCHANGED = "unchanged"
CHANGED = "changed"
FAILED = "failed"


@dataclass
class FetchResult:
    status: str
    cursor: dict | None = None
    text: str | None = None
    detail: str = ""


@dataclass
class PutResult:
    status: str
    cursor: dict | None = None
    commit: str | None = None
    detail: str = ""


@dataclass
class PublishResult:
    status: str
    message_id: str
    sha256: str | None = None
    attempts: int = 0
    detail: str = ""
    commit: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class Plane(Protocol):
    name: str

    def fetch(self, cursor: dict | None) -> FetchResult: ...

    def put(self, expected_cursor: dict | None, new_text: str, message: str = "") -> PutResult: ...
