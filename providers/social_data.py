"""SocialDataProvider interface (addendum_10 §3) + one synthetic
implementation (addendum_10 §5: "Speculator consumes generated social/
context streams first, then a Reddit provider can be wired when
credentials/mechanism are selected" - a real Reddit provider is explicitly
later, addendum_7 §3).

Unlike providers/market_data.py's static-per-call surface, this genuinely
advances: each fetch_recent call can produce new posts with strictly
increasing posted_at timestamps, simulating an ongoing stream rather than a
fixed snapshot - reproducible from the same seed + call sequence, not
identical every call (addendum_8 §3's reproducibility requirement, without
building the Trainer itself).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

SOURCES = ("reddit",)

TEMPLATES = (
    ("{security} vol looking spicy today, someone knows something", 0.6),
    ("just added to my {security} position, feeling good", 0.3),
    ("anyone else seeing weird options activity on {security}?", 0.7),
    ("{security} earnings whisper number is way off consensus", 0.8),
    ("random noise post not really about anything", 0.1),
    ("{security} to the moon lol", 0.2),
    ("large {security} block trade just printed, unusual size", 0.75),
)

MIN_POSTS_PER_CALL = 0
MAX_POSTS_PER_CALL = 3
POST_INTERVAL_SECONDS = 5


@dataclass(frozen=True)
class SocialPost:
    source: str
    author: str
    posted_at: str
    text: str
    security: str
    engagement_score: float


class SocialDataProvider(Protocol):
    def fetch_recent(self, security: str, since: str | None = None) -> list[SocialPost]: ...


class SyntheticSocialDataProvider:
    def __init__(self, seed: int):
        self._rng = random.Random(seed)
        self._cursor = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self._posts: list[SocialPost] = []

    def fetch_recent(self, security: str, since: str | None = None) -> list[SocialPost]:
        count = self._rng.randint(MIN_POSTS_PER_CALL, MAX_POSTS_PER_CALL)
        for _ in range(count):
            self._cursor += timedelta(seconds=POST_INTERVAL_SECONDS)
            template, engagement_base = self._rng.choice(TEMPLATES)
            self._posts.append(
                SocialPost(
                    source=self._rng.choice(SOURCES),
                    author=f"user{self._rng.randint(1000, 9999)}",
                    posted_at=self._cursor.isoformat(),
                    text=template.format(security=security),
                    security=security,
                    engagement_score=round(engagement_base + self._rng.uniform(-0.1, 0.1), 3),
                )
            )
        if since is None:
            return [p for p in self._posts if p.security == security]
        return [p for p in self._posts if p.security == security and p.posted_at > since]
