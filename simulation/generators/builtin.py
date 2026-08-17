"""The generators that exist today, on the contract.

Two are adapters over the providers already in use, so the existing pipeline is
unchanged and the contract is proved against real producers rather than against
something written to fit it. The third exists for a different reason.

**A coherence mechanism with nothing exercising it is unfalsifiable.** An event
bus that no generator emits into and none reads from will pass every test and
work never. So `MacroGenerator` emits shocks and `MarketGenerator` responds to
them, which is the smallest arrangement that can demonstrate - or fail to
demonstrate - that an event in one generator reaches another. The macro
generator here is deliberately thin; the real one is later work.

Internal rationale: INT-PHIL-0023
"""

from __future__ import annotations

import random
from datetime import timedelta

from providers.market_data import SyntheticMarketDataProvider
from providers.social_data import SyntheticSocialDataProvider
from simulation.generators import GenerationRequest, GenerationResult, WorldEvent

# How far a unit of shock widens the observed surface. Small on purpose: the
# point of the first coherence wiring is that the effect is present and
# directional, not that it is calibrated. Calibrating it against nothing would
# be inventing a number.
SHOCK_TO_IV = 0.05


class MarketGenerator:
    """Option surfaces, and the first consumer of world events.

    Responds to whatever shock is in flight rather than to particular event
    kinds, so a macro release it has never heard of still moves it. A generator
    that only reacted to events it recognised would silently ignore every new
    event type added after it was written, which is the failure that makes a
    coherence layer look like it works."""

    name = "market"
    data_classes = ("option_surface",)

    def __init__(self, provider: SyntheticMarketDataProvider):
        self.provider = provider

    def generate(self, request: GenerationRequest) -> GenerationResult:
        shock = request.shock()
        result = GenerationResult()

        for security in request.subjects:
            surface = self.provider.get_option_surface(security)
            # `iv`, not `implied_volatility`. The first version of this adapter
            # guessed the longer name, found nothing, and would have emitted no
            # observations at all while looking like it worked - an adapter's
            # whole job is to match a shape it does not own, so the shape is
            # worth reading rather than assuming.
            ivs = [point.iv for point in surface.points]
            if not ivs:
                continue

            widened = abs(shock) * SHOCK_TO_IV
            result.observations.append({
                "data_class": "option_surface",
                "subject": security,
                "effective_at": request.now,
                "value": {
                    "mean_iv": round(sum(ivs) / len(ivs) + widened, 4),
                    "max_iv": round(max(ivs) + widened, 4),
                    "points": len(ivs),
                    # Recorded so a consumer can tell a moved surface from a
                    # quiet one without re-deriving the shock.
                    "shock_applied": round(widened, 4),
                },
            })
        return result


class SocialGenerator:
    """Message-board chatter. Emits nothing and consumes nothing, for now.

    Kept deliberately inert on the event bus: chatter reacting to a macro shock
    is plausible and would be invented, and the fixture already has arcs for
    making a stream develop on purpose. Reacting here would make it impossible
    to tell an arc from a coherence effect."""

    name = "social"
    data_classes = ("social_post",)

    def __init__(self, provider: SyntheticSocialDataProvider):
        self.provider = provider
        self._cursors: dict[str, str] = {}

    def generate(self, request: GenerationRequest) -> GenerationResult:
        result = GenerationResult()
        for security in request.subjects:
            posts = self.provider.fetch_recent(security, since=self._cursors.get(security))
            if not posts:
                continue
            self._cursors[security] = posts[-1].posted_at
            result.observations.append({
                "data_class": "social_post",
                "subject": security,
                "effective_at": request.now,
                "value": {
                    "posts": len(posts),
                    "max_engagement": round(max(p.engagement_score for p in posts), 3),
                    "sources": sorted({p.source for p in posts}),
                },
            })
        return result


class MacroGenerator:
    """A thin source of scheduled releases and the shocks they cause.

    Exists to prove the event path works end to end, not to model an economy.
    Two behaviours only: it publishes a figure on its cadence, and when that
    figure surprises it emits an event other generators can feel.

    The publication lag is applied by the orchestrator, which is the point worth
    testing here - CPI describing today is not knowable today, and no generator
    should have to remember that."""

    name = "macro"
    data_classes = ("cpi",)

    def __init__(self, seed: int = 42, surprise_probability: float = 0.35):
        self._rng = random.Random(seed)
        self.surprise_probability = surprise_probability

    def generate(self, request: GenerationRequest) -> GenerationResult:
        result = GenerationResult()
        last = request.state.get("last_release")
        if last is not None and request.now - _parse(last) < timedelta(days=30):
            return result

        request.state["last_release"] = request.now.isoformat()
        surprised = self._rng.random() < self.surprise_probability
        magnitude = round(self._rng.uniform(-1.0, 1.0), 3) if surprised else 0.0

        result.observations.append({
            "data_class": "cpi",
            "subject": "US",
            "effective_at": request.now,
            "value": {"surprise": magnitude, "released": True},
        })
        if surprised:
            result.events.append(WorldEvent(
                kind="inflation_surprise",
                magnitude=magnitude,
                occurred_at=request.now,
                source=self.name,
                detail=f"CPI surprised by {magnitude:+.2f} of a normalised unit",
            ))
        return result


def _parse(value):
    from datetime import datetime
    return datetime.fromisoformat(value)
