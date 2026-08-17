"""The contract every world generator implements, and the shapes it exchanges.

The simulated world is produced by specialised generators - market prices, macro
releases, corporate events, news - under one orchestrator that keeps them
coherent. This module is the contract between them, and it is deliberately the
first thing built: it decides whether the generators that follow are additive or
a rewrite, which is the whole of Foundation First applied here.

Three decisions carry the design.

**The clock decides when a generator runs, not the generator.** Each declares
which data classes it produces; the orchestrator consults those cadences and
calls it only when something could arrive. Without that, every generator
reimplements "is the market open", and they drift.

**Lookahead is impossible by construction.** A generator says only when an
observation *describes*; the orchestrator computes when it becomes *knowable*
from the cadence's publication lag. A generator therefore cannot publish the
future even by mistake, which matters because generators are the part most likely
to be written quickly and by someone else.

**Coherence travels as events, not as calls between generators.** A generator
that reached into another would need an ordering, and an ordering between ten
generators is a dependency graph nobody can hold in their head. Instead a
generator emits a WorldEvent, and the orchestrator offers it to every generator
on subsequent ticks. Delayed and secondary effects are then the default rather
than a special case - which is what §17 of the directive actually asks for.

Internal rationale: INT-PHIL-0023
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class WorldEvent:
    """Something that happened in the simulated world and may move other things.

    `magnitude` is signed and roughly normalised to [-1, 1] so a consumer that
    does not recognise `kind` can still respond proportionately rather than
    ignoring it - an unknown shock of 0.9 should widen something even if the
    generator has never heard of that particular event."""

    kind: str
    magnitude: float
    occurred_at: datetime
    source: str
    subject: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class Observation:
    """One datum, with both of its timestamps.

    `knowable_at` is stamped by the orchestrator rather than the generator. A
    generator knows what it is describing; only the cadence knows when the world
    would have found out."""

    data_class: str
    subject: str
    effective_at: datetime
    knowable_at: datetime
    value: dict
    generator: str


@dataclass
class GenerationRequest:
    """What a generator is told when asked to produce.

    `state` is the generator's own, handed back on every call and never
    inspected by the orchestrator. Mutable and expected to be JSON-serialisable,
    because a continuously advancing world has to carry generator state across a
    day rollover - a price level that reset each morning would not be a price
    level."""

    now: datetime
    since: datetime | None
    subjects: tuple[str, ...]
    events: tuple[WorldEvent, ...]
    state: dict = field(default_factory=dict)

    def events_of(self, *kinds: str) -> tuple[WorldEvent, ...]:
        return tuple(event for event in self.events if event.kind in kinds)

    def shock(self) -> float:
        """Net signed magnitude of everything currently in flight.

        The lowest-effort way for a generator to respond to a world it does not
        model in detail. A generator that only consults this is still coherent
        with the rest, which is the point - coherence should not require every
        generator to understand every event."""
        return sum(event.magnitude for event in self.events)


@dataclass
class GenerationResult:
    """What a generator produces: observations, and anything it wants others to know.

    Observations are raw here - `data_class`, `subject`, `effective_at`, `value` -
    and the orchestrator turns them into Observations with a knowable_at."""

    observations: list[dict] = field(default_factory=list)
    events: list[WorldEvent] = field(default_factory=list)


@runtime_checkable
class Generator(Protocol):
    """A source of one or more data classes.

    `data_classes` must name entries in the cadence registry, so the orchestrator
    can tell when to call it and how long its output takes to become knowable. A
    generator naming a class the taxonomy does not carry is a generator whose
    clock nobody has thought about."""

    name: str
    data_classes: tuple[str, ...]

    def generate(self, request: GenerationRequest) -> GenerationResult: ...
