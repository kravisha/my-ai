"""A world that keeps running, across days.

Every simulation before this was bounded, and that shape cannot exhibit anything
whose timescale exceeds one run - which turned out to include most of what the
organization was built to do. Intelligence expiry needs ten graded reports and a
bounded run produces four.

Two properties carry these tests, and both are things that look fine until the
day they do not:

**State survives the rollover.** A price level that reset each morning would not
be a price level.

**No day is skipped.** A stalled process resumes with more simulated time elapsed
than it expected, and detecting "the date changed" handles one boundary while
silently losing the rest - on exactly the occasions when something already went
wrong.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from providers.market_data import SyntheticMarketDataProvider
from providers.social_data import SyntheticSocialDataProvider
from simulation import world as world_module
from simulation.clock import SimulationClock
from simulation.generators.builtin import MacroGenerator, MarketGenerator, SocialGenerator
from simulation.generators.orchestrator import Orchestrator
from simulation.world import DAY_ROLLOVER, ContinuousWorld

WALL = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
EPOCH = datetime(2026, 1, 5, 14, 0, tzinfo=timezone.utc)   # Monday, before the open


def build(scale=24, epoch=EPOCH, **kwargs):
    clock = SimulationClock(epoch=epoch, scale=scale, started_at=WALL)
    orchestrator = Orchestrator(
        clock,
        [
            MarketGenerator(SyntheticMarketDataProvider(seed=42)),
            SocialGenerator(SyntheticSocialDataProvider(seed=7)),
            MacroGenerator(seed=1, **kwargs),
        ],
        subjects=("SYN1", "SYN2"),
    )
    return ContinuousWorld(orchestrator, clock)


class Watcher:
    """A generator that records the events it was shown."""

    name = "watcher"
    data_classes = ("cpi",)

    def __init__(self):
        self.seen = []

    def generate(self, request):
        from simulation.generators import GenerationResult

        self.seen.append([event.kind for event in request.events])
        return GenerationResult()


def watching_world(scale=24):
    clock = SimulationClock(epoch=EPOCH, scale=scale, started_at=WALL)
    watcher = Watcher()
    return ContinuousWorld(Orchestrator(clock, [watcher], subjects=("SYN1",)), clock), watcher


# -- the rate ----------------------------------------------------------------

def test_a_simulated_day_takes_a_wall_hour():
    """The owner's decision, asserted where it can be seen. Everything else in
    this module is calibrated against it."""
    world = build()
    assert world.clock.wall_seconds_per_simulated_day() == pytest.approx(3600)


def test_the_world_reports_where_it_has_got_to():
    world = build()
    summary = world.summary()

    assert summary["wall_seconds_per_simulated_day"] == pytest.approx(3600)
    assert summary["days_completed"] == 0
    assert "simulated_day" in summary


# -- day rollover ------------------------------------------------------------

def test_an_ordinary_tick_does_not_roll_the_day():
    world = build()
    world.advance(WALL)
    assert world.advance(WALL + timedelta(seconds=1)).days_rolled == []


def test_crossing_midnight_rolls_the_day():
    world = build()
    world.advance(WALL)

    # 10 wall hours after an epoch of 14:00 is 10 simulated days later.
    tick = world.advance(WALL + timedelta(hours=10))

    assert tick.rolled_over
    assert tick.days_rolled[-1] == date(2026, 1, 15)


def test_a_stalled_process_does_not_lose_the_days_it_slept_through():
    """The failure this module was written around. A world reporting only the
    latest boundary would skip whatever the missed days were meant to trigger,
    and would do it silently."""
    world = build()
    world.advance(WALL)

    tick = world.advance(WALL + timedelta(hours=3))

    assert len(tick.days_rolled) == 3, "a three-day jump reported as fewer boundaries"
    assert tick.days_rolled == [date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8)]


def test_the_first_tick_establishes_the_day_rather_than_rolling_it():
    """Otherwise every world would report a rollover the moment it started, and
    the count of days would be permanently one too high."""
    assert build().advance(WALL).days_rolled == []


def test_time_going_backwards_rolls_nothing():
    """A defensive case with a real cause: two processes reading the same clock
    can disagree by milliseconds, and a backwards step must not be read as a
    rollover to yesterday."""
    world = build()
    world.advance(WALL + timedelta(hours=2))
    assert world.advance(WALL + timedelta(hours=1)).days_rolled == []


# -- the boundary is announced -----------------------------------------------

def test_generators_are_told_the_day_rolled():
    """Announced on the bus rather than left to each generator to notice. Three
    generators tracking their own idea of a new day is three chances to disagree
    about when it started."""
    world, watcher = watching_world()
    world.advance(WALL)
    world.advance(WALL + timedelta(hours=1))

    assert DAY_ROLLOVER in watcher.seen[-1]


def test_the_rollover_is_visible_on_the_tick_that_crosses_it():
    """Not a tick late. Anything whose behaviour differs on the first tick of a
    day needs the boundary before it runs, not after."""
    world, watcher = watching_world()
    world.advance(WALL)
    world.advance(WALL + timedelta(hours=1))

    assert DAY_ROLLOVER in watcher.seen[1], "the boundary arrived after the tick that crossed it"


def test_the_rollover_event_does_not_age_out_before_anyone_sees_it():
    """The bug this catches was in the first draft: stamping the event at the
    day's midnight put it six or more simulated hours in the past, and the bus
    ages events out after six - so the event existed and reached nobody."""
    world, watcher = watching_world()
    world.advance(WALL)
    world.advance(WALL + timedelta(hours=1))

    assert any(DAY_ROLLOVER in seen for seen in watcher.seen)


def test_every_crossed_day_is_announced_not_just_the_last():
    world, watcher = watching_world()
    world.advance(WALL)
    world.advance(WALL + timedelta(hours=3))

    assert watcher.seen[-1].count(DAY_ROLLOVER) == 3


# -- state survives ----------------------------------------------------------

def test_generator_state_survives_a_day_boundary():
    """A monthly release that forgot when it last fired would fire every day."""
    world = build(surprise_probability=1.0)
    world.advance(WALL)
    before = world.orchestrator.state()["macro"]["last_release"]

    world.advance(WALL + timedelta(hours=2))

    assert world.orchestrator.state()["macro"]["last_release"] == before


def test_a_world_resumes_where_it_left_off():
    """What a continuously advancing world needs to survive a restart: a price
    level that reset on every process start would not be a price level."""
    first = build(surprise_probability=1.0)
    first.advance(WALL)
    first.advance(WALL + timedelta(hours=3))
    carried = first.state()

    second = build(surprise_probability=1.0)
    second.restore(carried)

    assert second.state()["last_seen_day"] == carried["last_seen_day"]
    assert second.ticks == first.ticks
    assert second.orchestrator.state()["macro"]["last_release"] == \
        first.orchestrator.state()["macro"]["last_release"]


def test_a_resumed_world_does_not_replay_the_days_it_already_saw():
    """The specific way a restart corrupts a world: resuming and immediately
    reporting every past boundary again."""
    first = build()
    first.advance(WALL)
    first.advance(WALL + timedelta(hours=3))

    second = build()
    second.restore(first.state())

    assert second.advance(WALL + timedelta(hours=3)).days_rolled == []


# -- the world actually produces a world -------------------------------------

def test_the_world_produces_observations_over_a_simulated_day():
    """A world that advanced its clock and generated nothing would pass every
    test above."""
    world = build()
    produced = [obs for tick in world.run_until(WALL + timedelta(hours=1), step_seconds=60)
                for obs in tick.observations]

    assert produced, "a simulated day produced no observations at all"
    assert {o.data_class for o in produced} & {"option_surface", "social_post"}


def test_a_simulated_day_crosses_a_session_boundary():
    """The point of the rate. At one simulated day per wall hour, a world run for
    an hour sees the market open and shut - which is what makes anything
    session-dependent testable at all.

    Asked of a session-bound class specifically. `open_data_classes` is never
    empty - published statistics have no session and chatter has no closing bell -
    so "was anything open" would read True all day and prove nothing."""
    world = build()
    seen = set()
    moment = WALL
    while moment < WALL + timedelta(hours=1):
        seen.add(world.clock.is_open("option_surface", moment))
        moment += timedelta(seconds=60)

    assert seen == {True, False}, "the options market never changed state across a simulated day"


def test_something_is_always_open_even_when_the_markets_are_shut():
    """The other half, and the reason the test above asks about one class: an
    organization with nothing to do overnight would be idle for two thirds of
    every simulated day."""
    world = build()
    # 30 wall minutes past a 14:00 epoch is 02:00 the next simulated day.
    # Measured rather than guessed: the first attempt used 10 minutes, which
    # is 18:00 and squarely mid-session.
    overnight = WALL + timedelta(minutes=30)

    assert not world.clock.is_open("option_surface", overnight)
    assert world.clock.open_data_classes(overnight)


def test_run_until_needs_no_real_elapsed_time():
    """Simulated time advances from a wall-clock reading, not from waiting - so a
    simulated week costs whatever the generators cost and nothing more."""
    world = build()
    ticks = world.run_until(WALL + timedelta(hours=24), step_seconds=3600)

    assert len(ticks) == 24
    assert sum(len(t.days_rolled) for t in ticks) >= 20


# -- two defects found only by running a full simulated week ------------------

def test_an_ordinary_rollover_completes_a_day():
    """The first version recorded all-but-the-last crossed day, so a single-day
    rollover completed nothing. A simulated week ran with `days_completed` still
    reading zero, and every test above passed."""
    world = build()
    world.advance(WALL)
    world.advance(WALL + timedelta(hours=1))

    assert world.days_completed == [date(2026, 1, 5)]


def test_days_completed_counts_a_whole_simulated_week():
    world = build()
    world.run_until(WALL + timedelta(hours=7), step_seconds=600)

    # Measured, not derived: run_until's last step lands at wall +24600s, which
    # is 6.83 simulated days past a 14:00 epoch - so Jan 5 through Jan 11 have
    # finished and Jan 12 is in progress. Guessing "six" here was wrong once
    # already.
    assert len(world.days_completed) == 7
    assert world.days_completed[0] == date(2026, 1, 5)
    assert world.days_completed[-1] == date(2026, 1, 11)


def test_the_world_reports_its_own_position_not_the_real_clock():
    """A world advanced by explicit wall readings has no reason to agree with
    `datetime.now()`. Asking the clock without a moment gave a seven-hour run a
    simulated date five years out - and the summary looked plausible enough that
    only the arithmetic gave it away."""
    world = build()
    world.run_until(WALL + timedelta(hours=7), step_seconds=600)

    assert world.summary()["simulated_day"] == "2026-01-12"


def test_a_restored_world_reports_the_position_it_was_saved_at():
    world = build()
    world.run_until(WALL + timedelta(hours=3), step_seconds=600)

    resumed = build()
    resumed.restore(world.state())

    assert resumed.summary()["simulated_day"] == world.summary()["simulated_day"]
