"""Runs the generators, keeps them coherent, and stamps what is knowable.

The engine is not a monolith and must not become one: specialised generators do
the producing, and this coordinates them. Its whole job is the three things a
generator must not do for itself - decide when it runs, decide when its output
becomes visible, and carry what one generator did to the others.

Internal rationale: INT-PHIL-0023
"""

from __future__ import annotations

from datetime import datetime, timedelta

from simulation.cadences import CADENCES
from simulation.clock import SESSIONS, SimulationClock
from simulation.generators import (
    GenerationRequest,
    GenerationResult,
    Generator,
    Observation,
    WorldEvent,
)

# How long a world event stays available to other generators.
#
# An inflation surprise does not finish moving things in the instant it lands:
# rates go first, equities and volatility follow, sentiment and commentary later
# still. A window is the cheapest way to make delayed and secondary effects the
# default rather than something each generator schedules for itself.
#
# Measured in simulated time, so it means the same thing at any scale - a window
# expressed in ticks would silently shorten every time the scale rose.
DEFAULT_EVENT_WINDOW = timedelta(hours=6)


class Orchestrator:
    """Drives a set of generators against one clock.

    Events emitted on a tick are offered from the *next* tick onward, never the
    same one. That is deliberate: making them visible immediately would require
    an ordering among generators, and an ordering among ten generators is a
    dependency graph nobody can keep in their head. The cost is that the fastest
    possible reaction is one tick, which at the default scale is about five
    simulated minutes - slower than a real market and far more honest than a
    hidden execution order."""

    def __init__(
        self,
        clock: SimulationClock,
        generators: list[Generator] | None = None,
        subjects: tuple[str, ...] = (),
        event_window: timedelta = DEFAULT_EVENT_WINDOW,
    ):
        self.clock = clock
        self.generators: list[Generator] = []
        self.subjects = subjects
        self.event_window = event_window
        self._state: dict[str, dict] = {}
        self._events: list[WorldEvent] = []
        self._pending: list[WorldEvent] = []
        self._last_run: dict[str, datetime] = {}
        for generator in generators or []:
            self.register(generator)

    # -- registration --------------------------------------------------------

    def register(self, generator: Generator) -> None:
        """Add a generator, refusing one whose clock nobody has thought about.

        A data class absent from the cadence registry has no session and no
        publication lag, so the orchestrator could neither decide when to call
        the generator nor when its output becomes knowable. Failing here is far
        better than silently defaulting both, which would produce a generator
        that runs constantly and publishes instantly."""
        unknown = [c for c in generator.data_classes if c not in CADENCES]
        if unknown:
            raise ValueError(
                f"generator {generator.name!r} produces {unknown}, which the cadence registry does "
                "not carry. Add them to simulation/cadences.py with their archetype, session and "
                "publication lag first - a data class with no clock cannot be scheduled."
            )
        if any(existing.name == generator.name for existing in self.generators):
            raise ValueError(f"a generator named {generator.name!r} is already registered")
        self.generators.append(generator)
        self._state.setdefault(generator.name, {})

    # -- state ---------------------------------------------------------------

    def state(self) -> dict:
        """Every generator's state, for a world that has to survive a rollover.

        Returned by reference rather than copied: a generator mutating its own
        state between ticks is the normal case, and copying would quietly
        discard it."""
        return self._state

    def restore(self, state: dict) -> None:
        for name, generator_state in state.items():
            self._state[name] = dict(generator_state)

    # -- the tick ------------------------------------------------------------

    def open_data_classes(self, now: datetime) -> set[str]:
        return {name for name, cadence in CADENCES.items() if SESSIONS[cadence.session].is_open(now)}

    def emit(self, event: WorldEvent) -> None:
        """Put an event on the bus from outside any generator.

        The world uses this to announce a day boundary. Queued the same way a
        generator's event is, so it obeys the same visibility rule and there is
        no second path with different timing - except that an event emitted
        *before* `tick` is visible during that tick, which is what lets the first
        tick of a new day see the rollover rather than learn of it a tick late."""
        self._pending.append(event)

    def tick(self, wall: datetime | None = None) -> list[Observation]:
        """Advance the world once.

        Calls every generator that could produce something now, stamps what it
        produced with a knowable date, and collects any events for the next
        tick."""
        now = self.clock.now(wall)
        open_classes = self.open_data_classes(now)

        # Events emitted last tick become visible now; anything past the window
        # ages out. Done before generating, so this tick sees the previous one.
        self._events = [
            event for event in self._events + self._pending
            if now - event.occurred_at <= self.event_window
        ]
        self._pending = []

        produced: list[Observation] = []
        for generator in self.generators:
            if not any(data_class in open_classes for data_class in generator.data_classes):
                continue

            request = GenerationRequest(
                now=now,
                since=self._last_run.get(generator.name),
                subjects=self.subjects,
                events=tuple(self._events),
                state=self._state[generator.name],
            )
            result = generator.generate(request) or GenerationResult()
            self._last_run[generator.name] = now

            produced.extend(self._stamp(generator, result, now, open_classes))
            self._pending.extend(result.events)

        return produced

    def _stamp(
        self,
        generator: Generator,
        result: GenerationResult,
        now: datetime,
        open_classes: set[str],
    ) -> list[Observation]:
        """Turn raw output into observations, computing when each becomes knowable.

        Two things the generator does not get to decide. **Knowability** comes
        from the cadence, so a generator cannot publish the future even by
        mistake - the failure mode this guards against is a plausible-looking
        macro generator that emits a figure on the day it describes, which
        inflates every result downstream and shows up nowhere.

        And a **closed data class is dropped**, even if the generator produced
        it. A generator may produce several classes on different sessions; that
        it was called because one was open does not make the others open."""
        stamped = []
        for raw in result.observations:
            data_class = raw["data_class"]
            cadence = CADENCES.get(data_class)
            if cadence is None or data_class not in open_classes:
                continue
            effective_at = raw.get("effective_at") or now
            stamped.append(
                Observation(
                    data_class=data_class,
                    subject=raw.get("subject", ""),
                    effective_at=effective_at,
                    knowable_at=effective_at + cadence.publication_lag,
                    value=raw.get("value", {}),
                    generator=generator.name,
                )
            )
        return stamped

    # -- reading back --------------------------------------------------------

    def visible(self, observations: list[Observation], now: datetime | None = None) -> list[Observation]:
        """Only what the organization is allowed to have seen.

        The consumer-side half of the guard. Generators cannot publish early;
        this stops a consumer reading early, which is the same error made from
        the other end."""
        moment = now or self.clock.now()
        return [obs for obs in observations if obs.knowable_at <= moment]

    def events_in_flight(self) -> tuple[WorldEvent, ...]:
        return tuple(self._events)
