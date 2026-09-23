"""What is worth remembering, and what gets collected (§25/§26, and the owner).

Krish, 2026-09-23, asked whether *"the March invoice from Acme always arrives
late"* is a lesson or a context, and answered his own question:

> *"It's a fact that Claude may choose to remember and this cost may or may not
> be rewarded by a cost saving use in the future - that's how Jarvis learns how
> to guess correctly what to remember and what to discard - all deadweight
> unreferenced information should be eventually garbage collected as well"*

That is a different data model from the one `app/learning/memory.py` had. A
lesson there is *counted* - `times_seen` says how often the pattern recurred -
and nothing at all recorded whether the lesson was ever **read back and used**.
Those are the two halves of a bet and only one of them was being kept.

## A remembered fact is a bet, not a record

Three numbers, and they are not the same number:

| | what it means |
|---|---|
| `times_seen` | how often the world produced this pattern. Acquisition. |
| `times_referenced` | how often the fact was handed to a decision. Use. |
| `times_paid_off` | how often the thing it was handed to then went well. Return. |

A fact with a high `times_seen` and no references is deadweight that keeps
re-announcing itself. A fact referenced once that paid off has already earned
its cost. Nothing in this module asks how *interesting* a fact is, because that
is the judgement this project distrusts everywhere else - it asks only what the
fact has done.

## Acme is the case that kills a naive collector

*"The March invoice from Acme always arrives late"* is relevant for about one
week a year. A collector that discards facts unreferenced for ninety days
deletes it every June, re-learns it every March at full cost, and reports a tidy
database. So a bet carries `expected_interval_days`, and a fact is cold only
when it has gone unreferenced for several of **its own** cycles rather than
several of the collector's.

That alone is not enough, and the first version of this module was wrong about
it. Running the two cases side by side: Acme survived, and so did a fact that
cost twelve model calls and had never been referenced once in five hundred days,
because an unstated cycle defaults to a year and a year buys eight hundred days
of protection. That is the deadweight he asked to have collected, sitting there
wearing Acme's coat.

The distinction is not time. It is whether anything ever **asked a question this
fact could have answered**:

- `times_offered` - how often the fact was a candidate, because something read
  its kind while deciding.
- `times_referenced` - how often it was then actually handed over.

A fact offered two hundred times and never once chosen is dead, and no cycle
excuses it. A fact offered two hundred times and chosen each March is Acme. A
fact **never offered** cannot be judged at all, and is kept - not out of
generosity, but because its silence is evidence about the thing that never asked,
and collecting it would destroy the only record of a question nobody puts. When
that happens the kind is what should be questioned, and `KindHistory` is where
that argument gets its numbers.

## Discarding is itself the lesson, so the tombstone is an aggregate

The content goes - that is what he asked for - but *"facts of this kind cost us
this much and were never once used"* is exactly the training signal for guessing
better next time, and it must outlive the rows it describes. So a discard
increments a per-kind tally and the row is deleted. One row per kind means the
record of what was thrown away is bounded by the number of kinds and can never
itself become the deadweight it exists to prevent.

## A kind judged worthless keeps a door ajar

`worth_recording` stops recording a kind that has produced enough facts and
never a payoff. It does **not** stop for ever: it records every
`REPRIEVE_EVERY`-th one anyway. A policy that closed a kind permanently could
never find out the kind had become useful, and would be indistinguishable from
a bug that lost those facts. The reprieve is counter-driven rather than random
so that a test can state exactly which one gets through.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- verdicts -----------------------------------------------------------------

KEEP = "keep"
PROBATION = "probation"
DISCARD = "discard"
VERDICTS = (KEEP, PROBATION, DISCARD)

# --- the policy, as named numbers ---------------------------------------------

# Nothing is collected before this, whatever its cycle says. A fact acquired
# yesterday has not failed to be useful; it has not had the chance.
GRACE_DAYS = 30.0

# How many of a fact's own cycles must pass unreferenced before it is cold.
# Two plus a margin: one missed cycle is an ordinary quiet year, two is a
# pattern.
CYCLES_BEFORE_COLD = 2.25

# The cycle assumed for a fact that does not state one. A year, because the
# expensive mistake is collecting a seasonal fact and the cheap mistake is
# keeping a dead one slightly too long.
DEFAULT_INTERVAL_DAYS = 365.0

# A fact that paid off has earned its cost, so it is given this multiple of the
# cold period before it is retired. It is retired eventually: a fact that was
# useful in 2024 and never since is history, not memory.
EARNED_MULTIPLE = 2.0

# How often a fact must have been a candidate before being passed over counts
# against it. Twelve, so that a monthly planning read gives a yearly fact a full
# year of chances before anything is concluded from its silence.
MIN_OFFERS_TO_JUDGE = 12

# Probation is a window, not somewhere to live. A fact that spends this multiple
# of its cold period on probation is collected: it was offered, taken, never
# followed by anything good, and then went quiet twice over.
PROBATION_MULTIPLE = 2.0

# How many facts of one kind must exist before their payoff rate means anything.
# §26's own floor, for the same reason: fewer is one anecdote with a percentage
# sign on it.
MIN_SAMPLE_FOR_KIND = 8

# One in this many facts of a discredited kind is recorded anyway, so the kind
# can be found out to have become useful.
REPRIEVE_EVERY = 10


@dataclass(frozen=True)
class Bet:
    """One remembered fact, as the numbers that decide its fate.

    Frozen and free of any store, so every rule below is testable without a
    database, a clock or a network - and so that nothing can decide a fact's
    fate from anything but these fields."""

    kind: str
    cost: float = 0.0
    age_days: float = 0.0
    times_referenced: int = 0
    # How often this fact was a candidate - something read its kind while
    # deciding - whether or not it was chosen. Without it, "unused" and "never
    # asked about" are the same number, and they call for opposite actions.
    times_offered: int = 0
    # None means never referenced. Deliberately not 0, which would read as
    # "referenced today" and is the more dangerous of the two mistakes.
    days_since_reference: float | None = None
    times_paid_off: int = 0
    expected_interval_days: float | None = None

    def cycle(self) -> float:
        """The fact's own period, or the conservative default."""
        stated = self.expected_interval_days
        if stated is None or stated <= 0:
            return DEFAULT_INTERVAL_DAYS
        return float(stated)

    def cold_after_days(self) -> float:
        """How long unreferenced before this fact counts as cold."""
        cold = max(GRACE_DAYS, CYCLES_BEFORE_COLD * self.cycle())
        if self.times_paid_off:
            cold *= EARNED_MULTIPLE
        return cold

    def quiet_days(self) -> float:
        """How long it has gone unused.

        For a fact never referenced this is its whole age, which is the point:
        an unreferenced fact's silence starts the day it was acquired, not the
        day somebody first went looking."""
        if self.days_since_reference is None:
            return self.age_days
        return float(self.days_since_reference)

    def is_cold(self) -> bool:
        return self.quiet_days() > self.cold_after_days()


@dataclass(frozen=True)
class Verdict:
    outcome: str
    because: str
    # What the decision was made from, so a surprising verdict can be argued
    # with rather than merely overridden.
    quiet_days: float = 0.0
    cold_after_days: float = 0.0


def verdict(bet: Bet) -> Verdict:
    """Keep, stop offering, or collect. Ordered, and every branch says why.

    The order is the argument of the module. Age first, because nothing young is
    deadweight. Then the never-referenced facts, judged on whether they were ever
    passed over rather than on how long they were quiet - which is where the
    first version of this got Acme's protection and a dead fact's protection
    confused. Only then the facts that were used, on a clock their own payoff
    stretches."""
    quiet, cold_after = bet.quiet_days(), bet.cold_after_days()
    detail = {"quiet_days": round(quiet, 1),
              "cold_after_days": round(cold_after, 1)}

    if bet.age_days < GRACE_DAYS:
        return Verdict(KEEP, f"acquired {bet.age_days:.0f} day(s) ago; nothing is "
                             f"collected inside the {GRACE_DAYS:.0f}-day grace "
                             f"period", **detail)

    if not bet.times_referenced:
        if bet.times_offered < MIN_OFFERS_TO_JUDGE:
            return Verdict(KEEP, f"offered {bet.times_offered} time(s), below the "
                                 f"{MIN_OFFERS_TO_JUDGE} at which being passed "
                                 f"over means anything. Nothing has really asked "
                                 f"a question this could answer, and that is a "
                                 f"fact about the asking, not about this",
                           **detail)
        if bet.age_days <= bet.cycle():
            return Verdict(KEEP, f"offered {bet.times_offered} time(s) and never "
                                 f"chosen, but only {bet.age_days:.0f} day(s) old "
                                 f"against a {bet.cycle():.0f}-day cycle - its "
                                 f"season may simply not have come round yet",
                           **detail)
        return Verdict(DISCARD, f"cost {bet.cost:g} to acquire, was a candidate "
                                f"{bet.times_offered} time(s) across "
                                f"{bet.age_days:.0f} day(s) - more than a full "
                                f"{bet.cycle():.0f}-day cycle - and was never once "
                                f"chosen. Deadweight", **detail)

    if not bet.is_cold():
        return Verdict(KEEP, f"used {bet.times_referenced} time(s), last "
                             f"{quiet:.0f} day(s) ago, inside the {cold_after:.0f} "
                             f"this fact's {bet.cycle():.0f}-day cycle allows",
                       **detail)
    if bet.times_paid_off:
        return Verdict(DISCARD, f"paid off {bet.times_paid_off} time(s) and earned "
                                f"its keep, but has been unused for "
                                f"{quiet:.0f} day(s) against the {cold_after:.0f} "
                                f"an earned fact is given. This is history, not "
                                f"memory", **detail)
    if quiet > PROBATION_MULTIPLE * cold_after:
        return Verdict(DISCARD, f"referenced {bet.times_referenced} time(s), never "
                                f"once followed by a good outcome, and quiet for "
                                f"{quiet:.0f} day(s) - past the "
                                f"{PROBATION_MULTIPLE:g}x cold period probation "
                                f"lasts", **detail)
    return Verdict(PROBATION, f"referenced {bet.times_referenced} time(s) and never "
                              f"once followed by a good outcome, and cold for "
                              f"{quiet:.0f} day(s). Stop offering it before "
                              f"collecting it, so a wrong call here costs a missed "
                              f"hint rather than the fact", **detail)


# --- learning which kinds are worth the cost ----------------------------------


@dataclass(frozen=True)
class KindHistory:
    """What a kind of fact has cost and returned, across everything ever kept.

    This is the aggregate that survives collection. It is the whole reason a
    discard is not simply a delete."""

    kind: str
    recorded: int = 0
    referenced: int = 0
    paid_off: int = 0
    discarded_unreferenced: int = 0
    cost_sunk: float = 0.0

    def payoff_rate(self) -> float | None:
        """Fraction of this kind's facts that were ever followed by a good
        outcome, or `None` while the sample is too small to mean anything."""
        if self.recorded < MIN_SAMPLE_FOR_KIND:
            return None
        return self.paid_off / self.recorded

    def reference_rate(self) -> float | None:
        if self.recorded < MIN_SAMPLE_FOR_KIND:
            return None
        return self.referenced / self.recorded


def worth_recording(history: KindHistory) -> tuple[bool, str]:
    """Whether a new fact of this kind should be written down at all.

    Returns the decision and the reason for it. Fails **open**: an unknown kind
    and a small sample are both recorded, because "we have never tried" and "we
    tried and it never helped" are different findings and only the second one
    justifies stopping."""
    rate = history.payoff_rate()
    if rate is None:
        return True, (f"{history.recorded} of this kind recorded so far, below "
                      f"the {MIN_SAMPLE_FOR_KIND} a claim about its value would "
                      f"need. Recorded, because not knowing is not a reason to "
                      f"stop")
    if rate > 0:
        return True, (f"{history.paid_off} of {history.recorded} of this kind were "
                      f"followed by a good outcome")
    # Nothing of this kind has ever paid off. Record one in REPRIEVE_EVERY so the
    # door stays ajar, counting from what has already been recorded so that the
    # choice is a fact about the store rather than a coin.
    if history.recorded % REPRIEVE_EVERY == 0:
        return True, (f"none of {history.recorded} of this kind ever paid off, so "
                      f"this kind is not recorded - except every "
                      f"{REPRIEVE_EVERY}th, which this is, so that the kind can "
                      f"be found out to have become useful")
    return False, (f"none of {history.recorded} of this kind ever paid off and "
                   f"{history.cost_sunk:g} was spent acquiring them. Not "
                   f"recorded; the next reprieve is at "
                   f"{(history.recorded // REPRIEVE_EVERY + 1) * REPRIEVE_EVERY}")


def describe() -> dict:
    return {
        "verdicts": list(VERDICTS),
        "grace_days": GRACE_DAYS,
        "cycles_before_cold": CYCLES_BEFORE_COLD,
        "default_interval_days": DEFAULT_INTERVAL_DAYS,
        "earned_multiple": EARNED_MULTIPLE,
        "min_offers_to_judge": MIN_OFFERS_TO_JUDGE,
        "probation_multiple": PROBATION_MULTIPLE,
        "min_sample_for_kind": MIN_SAMPLE_FOR_KIND,
        "reprieve_every": REPRIEVE_EVERY,
        "a_fact_is_a_bet": True,
        "discards_leave_an_aggregate": True,
    }
