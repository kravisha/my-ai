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

# The default mixed stream: some posts hint at unusual activity, some are
# noise. Uncorrelated with anything happening on the option surface, which is
# realistic for an ordinary day but makes corroboration untestable on its own -
# see NARRATIVES below.
TEMPLATES = (
    ("{security} vol looking spicy today, someone knows something", 0.6),
    ("just added to my {security} position, feeling good", 0.3),
    ("anyone else seeing weird options activity on {security}?", 0.7),
    ("{security} earnings whisper number is way off consensus", 0.8),
    ("random noise post not really about anything", 0.1),
    ("{security} to the moon lol", 0.2),
    ("large {security} block trade just printed, unusual size", 0.75),
)

# Per-security narratives, so a caller can construct the three cases an
# Explorer<->Speculator cross-check has to tell apart (addendum_12 §14).
#
# Without these the stream is drawn uniformly at random per security, with no
# reference to whether that security's surface is dislocated - so chatter about
# a security with a forced anomaly is statistically identical to chatter about a
# flat one, and "does the social evidence corroborate this dislocation?" is a
# question the fixture cannot answer. Any agreement would be an RNG coincidence.
# Same defect the market provider had before it gained `regime`: a mechanism
# for a phenomenon that cannot occur.
#
# These are ground truth the system is never told. Speculator reads the posts
# and forms its own view; nothing hands it the narrative label.
# Each narrative controls three things independently: what the posts *say*,
# how *many* arrive, and how many distinct *authors* write them. Keeping those
# separate is the whole point - a message board is a verbal medium, so stance
# lives in the text, but volume and authorship are the arithmetic that text
# cannot reveal. A narrative that changed all three together would make the two
# frames redundant and the cross-check untestable.
NARRATIVES = {
    # Chatter consistent with a real dislocation, from a broad crowd.
    "corroborating": {
        "templates": (
            ("unusual {security} options flow all morning, size on the calls", 0.85),
            ("something is going on with {security}, vol bid hard", 0.8),
            ("{security} block trades printing well above average size", 0.9),
            ("hearing chatter about a {security} announcement this week", 0.75),
        ),
        "posts_per_call": (0, 2),  # deliberately *quieter* than 'contradicting'
        "author_pool": 400,
    },
    # Attention pointing the other way: the move is acknowledged and explained
    # away. Distinct from silence - this is evidence *for* the negative. Noisier
    # than the corroborating stream on purpose, so ranking by volume alone
    # promotes exactly the wrong security.
    "contradicting": {
        "templates": (
            ("{security} move is just index rebalancing, nothing stock-specific", 0.8),
            ("that {security} vol spike was one fat-finger print, already gone", 0.75),
            ("no news on {security}, people are reading into noise", 0.7),
            ("{security} desk says flow was a single hedge roll, not directional", 0.85),
        ),
        "posts_per_call": (1, 4),
        "author_pool": 400,
    },
    # Reads as enthusiastic corroboration and is high-volume, but comes from a
    # handful of accounts. This is the case that earns source dispersion its
    # keep: the text says "crowd agrees", the arithmetic says "three people
    # posting repeatedly". Addendum 12 §13's "coordinated noise" and
    # "popularity without substance", made constructible.
    "coordinated": {
        "templates": (
            ("{security} about to rip, load up", 0.9),
            ("massive {security} flow, this is the one", 0.88),
            ("{security} squeeze incoming, they cannot hold it", 0.92),
        ),
        "posts_per_call": (2, 5),
        "author_pool": 3,
    },
    # No chatter at all. "No evidence available" is a legitimate cross-check
    # answer and a different finding from disagreement, so it must be
    # constructible rather than approximated by a low post count.
    "silent": {"templates": (), "posts_per_call": (0, 0), "author_pool": 1},
}

MIN_POSTS_PER_CALL = 0
MAX_POSTS_PER_CALL = 3
POST_INTERVAL_SECONDS = 5
DEFAULT_AUTHOR_POOL = 9000


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
    def __init__(self, seed: int, narratives: dict[str, str] | None = None):
        """narratives: maps security -> a key of NARRATIVES ('corroborating',
        'contradicting', 'coordinated', 'silent'). Securities absent from this
        dict keep the default mixed TEMPLATES stream.

        This is ground truth the provider generates from; the system never sees
        the label. Speculator reads whatever posts arrive and forms its own view -
        what changes is that the stream can now actually agree or disagree with
        the option surface, which is what makes a cross-check verifiable rather
        than decorative.

        The narratives are deliberately constructed so that **no single frame
        gets the right answer**. Ranking by volume promotes 'coordinated' and
        then 'contradicting', which is backwards - 'corroborating' is the
        quietest of the three. Reading stance alone rates 'coordinated' and
        'corroborating' alike. Only stance *and* source dispersion together
        separate them. That is the point of the fixture: if one signal sufficed,
        the cross-check would have nothing to prove."""
        self._rng = random.Random(seed)
        self._cursor = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self._posts: list[SocialPost] = []
        self._narratives = narratives or {}

    def _profile_for(self, security: str) -> dict:
        """The generation profile for one security: templates, post rate, and
        author pool. Returns the default mixed stream for securities with no
        assigned narrative."""
        narrative = self._narratives.get(security)
        if narrative is None:
            return {
                "templates": TEMPLATES,
                "posts_per_call": (MIN_POSTS_PER_CALL, MAX_POSTS_PER_CALL),
                "author_pool": DEFAULT_AUTHOR_POOL,
            }
        if narrative not in NARRATIVES:
            raise ValueError(f"unknown narrative {narrative!r} for {security}; expected one of {sorted(NARRATIVES)}")
        return NARRATIVES[narrative]

    def fetch_recent(self, security: str, since: str | None = None) -> list[SocialPost]:
        profile = self._profile_for(security)
        templates = profile["templates"]
        # A 'silent' security has no templates to draw from. Return early rather
        # than generating zero-length posts, so the timestamp cursor does not
        # advance for a security producing nothing.
        if not templates:
            return []

        low, high = profile["posts_per_call"]
        count = self._rng.randint(low, high)
        for _ in range(count):
            self._cursor += timedelta(seconds=POST_INTERVAL_SECONDS)
            template, engagement_base = self._rng.choice(templates)
            self._posts.append(
                SocialPost(
                    source=self._rng.choice(SOURCES),
                    # Drawn from a pool whose *size* the narrative controls, so a
                    # high-volume stream can still come from very few accounts.
                    author=f"user{1000 + self._rng.randrange(profile['author_pool'])}",
                    posted_at=self._cursor.isoformat(),
                    text=template.format(security=security),
                    security=security,
                    engagement_score=round(engagement_base + self._rng.uniform(-0.1, 0.1), 3),
                )
            )
        if since is None:
            return [p for p in self._posts if p.security == security]
        return [p for p in self._posts if p.security == security and p.posted_at > since]
