"""Simulated time, and the fact that different market data runs on different clocks.

The organization has been driven entirely by wall-clock time: one-second poll
loops, and providers advancing a private cursor nothing else can read. Market
hours, day rollover, event calendars, a continuously advancing world and a
recommendation's declared horizon all need a clock the whole organization shares,
and building any of them against wall-clock time guarantees rework.

**There is no single clock.** An options surface moves tick by tick while the
session is open; a mutual fund NAV is struck once, at the close, and not at all
otherwise; a corporate bond may not trade for a week; CPI arrives monthly and is
weeks stale when it does; GDP arrives quarterly and is then revised twice. A
simulation that ticked all of them uniformly would be modelling a market that
does not exist, and an organization tested against it would be learning the wrong
reflexes.

So one clock advances, and each data class consults its own cadence to decide
whether this tick produces anything.

## The part that matters most: two timestamps, not one

Every datum carries **effective_at** - the moment it describes - and
**knowable_at** - the moment the organization could first have known it. For a
live quote they are the same. For CPI they are weeks apart. For a GDP revision
the effective date is a quarter that ended months ago.

An agent may only ever see data whose `knowable_at` has passed. That is not a
nicety: using a value before it was knowable is lookahead bias, it inflates every
result it touches, and it is invisible in the output - a backtest built on it
looks excellent and means nothing. Enforcing it in the clock rather than in each
consumer is the only version that holds, because the consumers are agents written
independently and one of them will forget.

## Choosing the scale

`FI_SIM_TIME_SCALE` is how many simulated seconds pass per wall-clock second.
The choice trades simulated coverage against intraday resolution, and both
directions have a real cost:

- **Too slow** and a run never reaches a day rollover, let alone a monthly
  release. At 24x - one simulated day per wall hour - a five-minute run covers
  two simulated hours, so nothing periodic is ever exercised.
- **Too fast** and agents sample too coarsely to see anything intraday. At
  10,000x a one-second poll skips three simulated hours, and an agent watching
  for a dislocation would step straight over it.

The default of 288 puts one simulated day in five wall minutes, chosen so that:

- a 300-second run covers exactly one simulated day, making rollover reachable in
  an ordinary run rather than only in a soak;
- a ten-generation chain covers ten simulated days;
- an overnight run covers a quarter, so quarterly releases and revisions are
  exercisable;
- an agent's one-second poll advances about five simulated minutes, which is a
  plausible analyst cadence rather than a tick-by-tick one.

**This is a starting value chosen for testability, not a derived one**, and it is
per-scenario config precisely so the simulation can be used to find out what it
should be. A scenario studying intraday behaviour should slow it down; one
studying multi-quarter memory should speed it up.

Internal rationale: INT-PHIL-0022
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

# Simulated seconds per wall-clock second. See the module docstring for why 288.
DEFAULT_SCALE = float(os.environ.get("FI_SIM_TIME_SCALE", "288"))

# Where simulated time starts. A Monday, so the first simulated day is a trading
# day and a run does not open on a weekend with every market shut.
DEFAULT_EPOCH = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)


# --- sessions ---------------------------------------------------------------
#
# When a market is open at all. Deliberately not one calendar: an equity session
# is a third of the day, futures run nearly around the clock, and a mutual fund
# has no session because it does not trade continuously in the first place.
#
# Times are UTC and holidays are absent. Both are simplifications, and they are
# the honest kind: a holiday calendar is a lookup table that changes nothing
# structurally, whereas pretending every asset shares one session would change
# what the organization learns.
@dataclass(frozen=True)
class Session:
    name: str
    opens: time | None      # None means it never closes
    closes: time | None
    weekdays: tuple[int, ...]   # 0 = Monday

    def is_open(self, moment: datetime) -> bool:
        if moment.weekday() not in self.weekdays:
            return False
        if self.opens is None or self.closes is None:
            return True

        clock_time = moment.timetz().replace(tzinfo=None)
        if self.opens <= self.closes:
            return self.opens <= clock_time < self.closes
        # A session that wraps midnight - futures open in the evening and run
        # through to the following evening. Comparing it as a single interval
        # makes `opens <= t < closes` unsatisfiable, so the session reads as
        # permanently shut, which is how it was first written.
        return clock_time >= self.opens or clock_time < self.closes


WEEKDAYS = (0, 1, 2, 3, 4)
EVERY_DAY = (0, 1, 2, 3, 4, 5, 6)

SESSIONS = {
    # US cash equities, 09:30-16:00 ET, expressed in UTC without daylight saving.
    "equity": Session("equity", time(14, 30), time(21, 0), WEEKDAYS),
    "bond": Session("bond", time(13, 0), time(22, 0), WEEKDAYS),
    # Futures trade nearly around the clock with a short daily break.
    "futures": Session("futures", time(23, 0), time(22, 0), EVERY_DAY),
    "fx": Session("fx", None, None, WEEKDAYS),
    "always": Session("always", None, None, EVERY_DAY),
    # For data that is published rather than traded. It has no session, and
    # saying so is better than borrowing one that misdescribes it.
    "none": Session("none", None, None, EVERY_DAY),
}


# --- cadences ---------------------------------------------------------------

CONTINUOUS = "continuous"       # updates whenever its session is open
DAILY_CLOSE = "daily_close"     # one value, struck at the session close
SPORADIC = "sporadic"           # trades irregularly; absence is not an error
PERIODIC = "periodic"           # released on a calendar: monthly, quarterly
SCHEDULED = "scheduled"         # a known list of dates, e.g. policy meetings


@dataclass(frozen=True)
class Cadence:
    """How one class of market data arrives.

    `publication_lag` is the gap between what a datum describes and when the
    world could know it. It is zero for anything traded and substantial for
    anything measured: a home price index describes a month that ended two months
    ago. Modelling it is the difference between a simulation that can teach the
    organization to wait for confirmation and one that quietly hands it the
    future.

    `revisions` is how many times a figure is restated afterwards. GDP is
    published, revised, and revised again, and a decision made on the first print
    was made without the other two - which is a thing worth being able to test."""

    name: str
    kind: str
    session: str
    interval: timedelta | None = None
    publication_lag: timedelta = timedelta(0)
    revisions: int = 0

    def session_spec(self) -> Session:
        return SESSIONS[self.session]


# Chosen from how these instruments actually behave, not from convenience. The
# groupings that matter are traded-vs-published and continuous-vs-struck: an ETF
# and a mutual fund hold nearly the same assets and keep completely different
# clocks, because one trades all day and the other is priced once.
CADENCES = {
    "equity_price": Cadence("equity_price", CONTINUOUS, "equity"),
    "option_surface": Cadence("option_surface", CONTINUOUS, "equity"),
    "etf_price": Cadence("etf_price", CONTINUOUS, "equity"),
    "index_price": Cadence("index_price", CONTINUOUS, "equity"),
    # Priced once a day from the closing marks. No intraday value exists, and a
    # simulation that produced one would be inventing a quote nobody could trade.
    "mutual_fund_nav": Cadence("mutual_fund_nav", DAILY_CLOSE, "equity"),
    "index_fund_nav": Cadence("index_fund_nav", DAILY_CLOSE, "equity"),
    # Government paper trades continuously; a given corporate bond may not trade
    # for days, and its last price going stale is information rather than a gap.
    "government_yield": Cadence("government_yield", CONTINUOUS, "bond"),
    "corporate_bond_price": Cadence("corporate_bond_price", SPORADIC, "bond"),
    "credit_spread": Cadence("credit_spread", DAILY_CLOSE, "bond"),
    "commodity_price": Cadence("commodity_price", CONTINUOUS, "futures"),
    "fx_rate": Cadence("fx_rate", CONTINUOUS, "fx"),
    # Policy decisions land on a published schedule, roughly eight times a year.
    "policy_rate": Cadence("policy_rate", SCHEDULED, "none", interval=timedelta(days=45)),
    # Published statistics. The lags are what make them different from prices:
    # by the time the organization sees them they describe a period that closed
    # weeks or months earlier.
    "employment": Cadence("employment", PERIODIC, "none",
                          interval=timedelta(days=30), publication_lag=timedelta(days=7)),
    "cpi": Cadence("cpi", PERIODIC, "none",
                   interval=timedelta(days=30), publication_lag=timedelta(days=14)),
    "gdp": Cadence("gdp", PERIODIC, "none",
                   interval=timedelta(days=91), publication_lag=timedelta(days=28), revisions=2),
    "home_price_index": Cadence("home_price_index", PERIODIC, "none",
                                interval=timedelta(days=30), publication_lag=timedelta(days=60)),
    "earnings": Cadence("earnings", PERIODIC, "none",
                        interval=timedelta(days=91), publication_lag=timedelta(days=21)),
}


class SimulationClock:
    """Simulated time, advancing at a fixed multiple of wall-clock time.

    Deliberately derived from wall-clock rather than stepped by a caller. The
    organization is a set of independent OS processes with no shared scheduler,
    so any clock they must each advance would drift apart between them; a clock
    computed from a shared epoch and rate gives every process the same answer
    without coordinating."""

    def __init__(self, epoch: datetime | None = None, scale: float | None = None,
                 started_at: datetime | None = None):
        self.epoch = epoch or DEFAULT_EPOCH
        self.scale = DEFAULT_SCALE if scale is None else float(scale)
        self.started_at = started_at or datetime.now(timezone.utc)

    def now(self, wall: datetime | None = None) -> datetime:
        elapsed = ((wall or datetime.now(timezone.utc)) - self.started_at).total_seconds()
        return self.epoch + timedelta(seconds=elapsed * self.scale)

    def wall_seconds_per_simulated_day(self) -> float:
        return 86400 / self.scale

    def simulated_day(self, wall: datetime | None = None) -> date:
        return self.now(wall).date()

    def is_open(self, data_class: str, wall: datetime | None = None) -> bool:
        return CADENCES[data_class].session_spec().is_open(self.now(wall))

    def open_data_classes(self, wall: datetime | None = None) -> list[str]:
        """Which data classes could produce something right now.

        The basis for turning outward during market hours and inward outside
        them - and it is a list rather than a boolean because the markets do not
        all close together."""
        return sorted(name for name in CADENCES if self.is_open(name, wall))


def knowable_at(cadence: Cadence, effective_at: datetime) -> datetime:
    """When the organization could first have known a datum describing this moment."""
    return effective_at + cadence.publication_lag


def is_knowable(cadence: Cadence, effective_at: datetime, now: datetime) -> bool:
    """Whether this datum may be shown yet.

    The guard against lookahead bias, kept in the clock rather than in each
    consumer. Consumers are independently written agents, and one of them will
    forget; a result built on a figure published after the decision that used it
    looks excellent and means nothing, and nothing in the output reveals it."""
    return knowable_at(cadence, effective_at) <= now


def visible(data_class: str, records: list[dict], now: datetime) -> list[dict]:
    """Filter records to those the organization is allowed to have seen.

    Each record needs an `effective_at`. Records without one are dropped rather
    than assumed current: a datum whose date is unknown cannot be shown to be
    knowable, and guessing in the permissive direction is exactly the error this
    exists to prevent."""
    cadence = CADENCES[data_class]
    allowed = []
    for record in records:
        effective = record.get("effective_at")
        if effective is None:
            continue
        if isinstance(effective, str):
            effective = datetime.fromisoformat(effective)
        if is_knowable(cadence, effective, now):
            allowed.append(record)
    return allowed
