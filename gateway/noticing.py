"""Noticing that Krish will want something, before he asks.

Krish, 2026-09-23: *"the anticipating ability or predictive abilities are what is
characterized as being preemptive in being helpful like humans holding the door
and being thoughtful like a caring parent."*

`gateway/anticipation.py` scores guesses and `gateway/readback.py` offers them.
Neither makes one. Until this, nothing did: the trust ladder had no input, and a
ladder with nothing on it is the same failure as a ladder nothing can climb.

## Noticing is reading what is already recorded

Nothing here observes the world. It reads rows this system already keeps -
commitments with a due date, requests that keep coming back - and turns them into
things worth saying. That is deliberate and it is the whole difference between
anticipation and invention: every prompting carries the record it came from, so
*"why did you think that?"* has an answer that is not a feeling.

## Saying it is a separate decision from noticing it

`notice` finds everything. `worth_saying` decides which of it Krish actually
hears, and it asks the trust ladder. At `observe` the noticing is **recorded and
not spoken** - which is what that rung means, and the first place in the system
where the rung changes behaviour rather than describing it.

That split matters more than it looks. An assistant that only records what it is
allowed to say can never demonstrate that it was right, so it can never climb.
Recording everything and speaking little is what makes the bottom rung a starting
point rather than a trap.

## Holding forty doors is not helpfulness

`MOST_PER_SWEEP` caps what goes out at once. A person who points out six things
you might want is helping; a person who points out sixty is a cost. The cap is on
what is **said**, never on what is noticed, for the reason above.

## Not now means not now

A prompting whose guess was recently settled `not_now` is held back for
`QUIET_DAYS`. He answered - the answer was *not at the moment* - and asking again
that afternoon is how a person learns to stop reading what they are asked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from gateway import anticipation

# Where a noticing came from. Closed, because `worth_saying` groups on it and a
# free-form source is one nothing can weigh.
COMMITMENT_DUE = "commitment_due"
COMMITMENT_OVERDUE = "commitment_overdue"
REPEATED_REQUEST = "repeated_request"
SOURCES = (COMMITMENT_DUE, COMMITMENT_OVERDUE, REPEATED_REQUEST)

# How long before a due date a commitment is worth raising. Two days: long
# enough to do something about it, short enough that it is not noise about a
# thing three weeks away.
DUE_WITHIN_DAYS = 2

# How many times a thing must have been asked for before its recurrence is a
# pattern rather than a coincidence.
TIMES_BEFORE_A_PATTERN = 3

# The most that is said in one sweep. Noticing is unbounded; saying is not.
MOST_PER_SWEEP = 3

# After a `not_now`, how long before the same ground is raised again.
QUIET_DAYS = 7


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day(when: datetime) -> str:
    """A date as Krish would say it: "3 October", no leading zero.

    Built rather than formatted. `%-d` is a glibc extension - it is not in the C
    standard and Windows raises `ValueError: Invalid format string` on it, which
    took out every noticing on the only machine this is for while passing on
    every machine it was written on. `%#d` is the Windows spelling and is just as
    unportable in the other direction, so neither is used."""
    return f"{when.day} {when:%B}"


def _parse(stamp) -> datetime | None:
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Prompting:
    """Something Krish will probably want, and the record that says so."""

    domain: str
    what: str
    because: str
    source: str
    by_when: datetime | None = None
    # How pressing, for ordering when more is noticed than may be said. Not a
    # probability and not called one - nothing here has measured how often these
    # are right, and `gateway/anticipation.py` is where that is found out.
    urgency: int = 0

    def as_guess(self, *, now: datetime | None = None) -> anticipation.Guess:
        return anticipation.Guess(
            domain=self.domain, what=self.what, because=self.because,
            made_at=now or _now(), by_when=self.by_when)


def from_commitments(commitments, *, now: datetime | None = None
                     ) -> list[Prompting]:
    """Promises coming due, and promises already missed.

    §4.1 keeps these so that *"what did I promise and not deliver"* survives a
    restart. Reading them back before the date is what turns a record into
    help."""
    when = now or _now()
    found = []
    for row in commitments:
        if (row.get("status") or "open") != "open":
            continue
        due = _parse(row.get("due_on"))
        promise = (row.get("promise") or row.get("name") or "").strip()
        if not promise:
            continue
        if due is None:
            continue
        days = (due - when).total_seconds() / 86400.0
        if days < 0:
            found.append(Prompting(
                domain="commitments", what=promise,
                because=(f"you were promised this by {_day(due)} and it has "
                         f"not been settled"),
                source=COMMITMENT_OVERDUE, by_when=due,
                urgency=100 + min(30, int(-days))))
        elif days <= DUE_WITHIN_DAYS:
            found.append(Prompting(
                domain="commitments", what=promise,
                because=f"this is due on {_day(due)}",
                source=COMMITMENT_DUE, by_when=due,
                urgency=50 + int(DUE_WITHIN_DAYS - days)))
    return found


def from_repeated_requests(entries, *, now: datetime | None = None
                           ) -> list[Prompting]:
    """Things Krish has asked for often enough that asking again is predictable.

    Fed from `app/capability_gaps.py`'s ranked rows, which already count how
    often something was wanted and could not be done."""
    when = now or _now()
    found = []
    for row in entries:
        count = int(row.get("count") or 0)
        if count < TIMES_BEFORE_A_PATTERN:
            continue
        wanted = (row.get("what_was_needed") or "").strip()
        if not wanted:
            continue
        last = _parse(row.get("last_seen"))
        found.append(Prompting(
            domain=row.get("gap_type") or "requests",
            what=wanted,
            because=(f"you have asked for this {count} times"
                     + (f", most recently on {_day(last)}" if last else "")),
            source=REPEATED_REQUEST,
            by_when=(when + timedelta(days=DUE_WITHIN_DAYS)),
            urgency=min(40, count)))
    return found


def notice(*, commitments=(), requests=(), now: datetime | None = None
           ) -> list[Prompting]:
    """Everything worth noticing, most pressing first. Says nothing."""
    found = list(from_commitments(commitments, now=now))
    found += list(from_repeated_requests(requests, now=now))
    return sorted(found, key=lambda one: (-one.urgency, one.domain, one.what))


def recently_declined(domain: str, guesses, *, now: datetime | None = None
                      ) -> bool:
    """Whether Krish said *not at the moment* about this ground lately.

    He answered. Asking again that afternoon is how a person learns to stop
    reading what they are asked."""
    when = now or _now()
    for guess in guesses:
        if guess.domain != domain or guess.outcome != anticipation.NOT_NOW:
            continue
        if guess.settled_at and (when - guess.settled_at) <= timedelta(
                days=QUIET_DAYS):
            return True
    return False


def worth_saying(promptings, guesses, *, now: datetime | None = None,
                 most: int = MOST_PER_SWEEP) -> tuple[list, list]:
    """Split what was noticed into what is said and what is only recorded.

    Returns `(say, record_only)`. Everything noticed is recorded either way -
    an assistant that only writes down what it is allowed to say can never
    demonstrate it was right, so it can never climb."""
    say, quiet = [], []
    for one in promptings:
        allowed, _ = anticipation.may(one.domain, guesses,
                                      at_least=anticipation.MENTION, now=now)
        if not allowed:
            quiet.append(one)
        elif recently_declined(one.domain, guesses, now=now):
            quiet.append(one)
        elif len(say) >= most:
            quiet.append(one)
        else:
            say.append(one)
    return say, quiet


def describe() -> dict:
    return {
        "sources": list(SOURCES),
        "due_within_days": DUE_WITHIN_DAYS,
        "times_before_a_pattern": TIMES_BEFORE_A_PATTERN,
        "most_per_sweep": MOST_PER_SWEEP,
        "quiet_days_after_a_not_now": QUIET_DAYS,
        "records_everything_it_notices": True,
        "observes_the_world": False,
    }
