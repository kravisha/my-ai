"""A world that keeps running, across days.

Every simulation so far has been a bounded run: start the organization, let it
work for ninety seconds or five minutes, stop it, read the result. That shape
cannot exhibit anything whose timescale exceeds one run - and **that turned out
to include most of what the organization was built to do.** Intelligence expiry
needs ten graded reports and a bounded run produces four, so the conditions half
of it has never once engaged outside a unit test.

So this advances a world continuously instead. The generators are the ones the
orchestrator already registers; what is new is that time does not stop, the day
rolls over, and state survives the boundary.

**Two things carry the design.**

*State survives the rollover.* A price level that reset each morning would not be
a price level, and a monthly release that forgot when it last fired would fire
every day. The orchestrator already exposes `state()`/`restore()`; this makes
sure they are used across the one boundary where forgetting looks natural.

*A day is never skipped.* Ticks are driven by wall-clock, and a process that
stalls - a slow model call, a paused laptop - resumes with more simulated time
elapsed than it expected. At one simulated day per wall hour, a stall of an hour
and five minutes crosses a rollover *and part of another*. Detecting "the date
changed" would handle the first and silently lose the second, so rollover
returns every day crossed rather than a boolean.

Nothing here writes to the organization's database. The world produces
observations and announces boundaries; what consumes them is the caller's
business, which keeps this usable by a live run, a replay and a test alike.

Internal rationale: INT-PHIL-0032
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from simulation.clock import SimulationClock
from simulation.generators import Observation, WorldEvent

# Emitted onto the event bus when the simulated date changes, so a generator can
# react to the boundary without having to track the date itself. Named rather
# than left to each generator: three generators tracking their own idea of "a new
# day" is three chances to disagree about when it started.
DAY_ROLLOVER = "day_rollover"


@dataclass
class WorldTick:
    """What one advance of the world produced."""

    at: datetime
    observations: list[Observation] = field(default_factory=list)
    # Every simulated day whose start was crossed by this tick. Usually empty,
    # occasionally one, and more than one when the process was stalled.
    days_rolled: list[date] = field(default_factory=list)

    @property
    def rolled_over(self) -> bool:
        return bool(self.days_rolled)


class ContinuousWorld:
    """The baseline world, advancing under its own clock.

    Deliberately not a thread and not a loop. `advance()` is called by whoever
    owns the cadence - a harness, a test, or a live run - which keeps the world
    testable without waiting for real seconds to pass."""

    def __init__(self, orchestrator, clock: SimulationClock | None = None):
        self.orchestrator = orchestrator
        self.clock = clock or orchestrator.clock
        self._last_seen: date | None = None
        # Where the world actually is. Kept because `advance` is driven by an
        # explicit wall reading, so "now" for this world is the last moment it
        # was advanced to - not the real clock. Reporting the latter made a
        # week-long run claim it had reached 2031.
        self._at: datetime | None = None
        self.days_completed: list[date] = []
        self.ticks = 0

    # -- advancing ------------------------------------------------------------

    def advance(self, wall: datetime | None = None) -> WorldTick:
        """Move the world forward to `wall` and return what happened.

        Rollover is detected *before* the generators run, so the first tick of a
        new day sees the boundary event rather than learning about it a tick
        late. That ordering matters for anything whose behaviour differs on the
        first tick of a session."""
        moment = wall or datetime.now(timezone.utc)
        now = self.clock.now(moment)

        rolled = self._days_crossed(now.date())
        for day in rolled:
            self.orchestrator.emit(WorldEvent(
                kind=DAY_ROLLOVER,
                magnitude=0.0,
                # Stamped at the current moment, not at the day's midnight. The
                # bus ages events out after six simulated hours, so a
                # midnight-stamped rollover would have expired before the equity
                # session opened - present in the code, visible to nobody.
                occurred_at=now,
                source="world",
                detail=f"simulated day {day.isoformat()} began",
            ))

        observations = self.orchestrator.tick(moment)
        self._at = moment
        self.ticks += 1
        return WorldTick(at=now, observations=observations, days_rolled=rolled)

    def _days_crossed(self, today: date) -> list[date]:
        """Every day boundary passed since the last tick.

        Returns a list rather than a flag because a stalled process can cross
        more than one. A world that reported only the latest would skip whatever
        a missed day was supposed to trigger - and would do it silently, on the
        exact occasions when something already went wrong."""
        if self._last_seen is None:
            self._last_seen = today
            return []
        if today <= self._last_seen:
            return []

        crossed = []
        day = self._last_seen
        while day < today:
            # Crossing *into* `day + 1` is the moment `day` finished, so the
            # completed day is the one being left rather than the one entered.
            # The first version recorded `crossed[:-1]`, which meant an ordinary
            # single-day rollover completed nothing at all - a simulated week ran
            # with `days_completed` still reading zero.
            self.days_completed.append(day)
            day += timedelta(days=1)
            crossed.append(day)
        self._last_seen = today
        return crossed

    def run_until(self, deadline: datetime, step_seconds: float = 1.0) -> list[WorldTick]:
        """Advance in fixed wall-clock steps up to `deadline`, without sleeping.

        For replay and tests: real elapsed time is not needed to advance
        simulated time, only a wall-clock reading, so a simulated week can be
        produced in whatever wall time the generators take."""
        ticks = []
        moment = self.clock.started_at
        while moment < deadline:
            ticks.append(self.advance(moment))
            moment += timedelta(seconds=step_seconds)
        return ticks

    # -- surviving a restart --------------------------------------------------

    def state(self) -> dict:
        """Everything needed to resume this world in a fresh process.

        The generators' state is the orchestrator's; what belongs to the world is
        where it had got to."""
        return {
            "generators": self.orchestrator.state(),
            "last_seen_day": self._last_seen.isoformat() if self._last_seen else None,
            "days_completed": [day.isoformat() for day in self.days_completed],
            "ticks": self.ticks,
            "at": self._at.isoformat() if self._at else None,
        }

    def restore(self, state: dict) -> None:
        self.orchestrator.restore(state.get("generators", {}))
        last = state.get("last_seen_day")
        self._last_seen = date.fromisoformat(last) if last else None
        self.days_completed = [date.fromisoformat(d) for d in state.get("days_completed", [])]
        self.ticks = state.get("ticks", 0)
        at = state.get("at")
        self._at = datetime.fromisoformat(at) if at else None

    # -- what the world can say about itself ----------------------------------

    def summary(self) -> dict:
        """Where the world is, read from its own position rather than the real
        clock. A world advanced by explicit wall readings has no reason to agree
        with `datetime.now()`, and asking the clock without a moment gave a
        seven-hour run a simulated date five years out."""
        at = self._at
        return {
            "simulated_now": self.clock.now(at).isoformat(),
            "simulated_day": self.clock.simulated_day(at).isoformat(),
            "days_completed": len(self.days_completed),
            "ticks": self.ticks,
            "open_data_classes": self.clock.open_data_classes(at),
            "wall_seconds_per_simulated_day": self.clock.wall_seconds_per_simulated_day(),
        }
