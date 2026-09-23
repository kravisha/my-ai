"""Guessing what Krish wants before he asks, and being scored on it.

Krish, 2026-09-23, on what trust is and how it is earned:

> *"trust means anticipating correctly what i need and correctly executing it to
> perfection. Thats what is earned and at some point i know that he would execute
> to perfection and would give him a free hand to complete things as per his
> discretion and just present me the final result which is the point called the
> full stop."*

and on what being helpful looks like:

> *"the anticipating ability or predictive abilities are what is characterized as
> being preemptive in being helpful like humans holding the door and being
> thoughtful like a caring parent"*

Those were two separate objectives until it became clear they are one capability
seen twice. Being preemptively helpful **is** anticipating; anticipating
correctly is what earns the free hand. So there is one record here, and the
ladder moves on it.

## A guess is only a guess if it was written down first

A `Guess` is made before the outcome is known, says what the trigger was, and
carries a deadline. Recorded afterwards it is hindsight, and a hindsight record
grades a hundred per cent for ever. This is the same discipline as
`gateway/inquiry.py` requiring `refuted_by` at the moment a hypothesis is
proposed: the honest version of a claim is the one made while it could still be
wrong.

## Three outcomes, because two would hide the interesting one

| | meaning |
|---|---|
| `wanted` | right, and he wanted it done |
| `not_now` | right about the need, wrong to act - timing, mood, privacy |
| `wrong` | the need never existed |

Holding a door for somebody who wanted to walk past is not the same mistake as
holding a door that is not there. Collapsing `not_now` into `wrong` teaches the
wrong lesson: stop noticing, rather than notice and wait.

## Two rates, because knowing and doing fail differently

Anticipating that Krish needs the quarterly statement and then producing a wrong
one are different failures with different fixes, so `accuracy` and `execution`
are counted separately and both gate the ladder.

**And they are recorded at different moments**, which the first version of this
module got wrong. `settle` took the outcome *and* the quality together, so the
quality had to be known when Krish said yes - before the work had been done. It
never was, so every guess was rated `None`, `perfect_run` was permanently zero,
and the ladder could not climb past `mention` no matter how well anything went.
A ladder nothing can climb is decoration.

So: `settle` closes the anticipation when Krish answers, and `rate` records how
the work turned out afterwards, once. Both refuse a verdict from the agent.

## Nothing here grades itself

A prediction the predictor scores is worth nothing, and this module cannot score
anything: `settle` takes the outcome as an argument and the callers hand it
something Jarvis did not author - Krish answering a read-back, asking for the
thing himself, or a deadline passing with neither. The same shape as
`gateway/charter.py`'s owner-written grant, for the same reason.

## The ladder is per domain, and slow up, fast down

Per domain because a free hand with expense statements is not a free hand with
email, and one mistake in the second must not cost the first. Slow up because
trust is, and fast down because that is how it works with people: a single
execution failure drops the rung immediately, and climbing back needs the same
run of good outcomes as the first time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# --- how a guess turns out ------------------------------------------------------

WANTED = "wanted"
NOT_NOW = "not_now"
WRONG = "wrong"
OUTCOMES = (WANTED, NOT_NOW, WRONG)

OUTCOME_MEANING = {
    WANTED: "right, and he wanted it done",
    NOT_NOW: ("right about the need and wrong to act - a door held for somebody "
              "who wanted to walk past"),
    WRONG: "the need never existed",
}

# --- how well it was then done --------------------------------------------------

PERFECT = "perfect"
FLAWED = "flawed"
FAILED = "failed"
QUALITIES = (PERFECT, FLAWED, FAILED)

# --- the ladder -----------------------------------------------------------------

OBSERVE = "observe"
MENTION = "mention"
PREPARE = "prepare"
ACT_AND_REPORT = "act_and_report"
FULL_STOP = "full_stop"
RUNGS = (OBSERVE, MENTION, PREPARE, ACT_AND_REPORT, FULL_STOP)

RUNG_MEANING = {
    OBSERVE: "notices and records, says nothing",
    MENTION: "says he noticed, and asks",
    PREPARE: "does the part that can be undone, shows it, waits",
    ACT_AND_REPORT: "does it, and tells Krish straight away",
    FULL_STOP: ("does it and presents the result - the free hand, and the point "
                "Krish called the full stop"),
}

# How many settled guesses a domain needs before its rates mean anything. Small,
# because the ladder's lowest rungs cost little to be wrong about, and the
# execution gate below is what actually guards the top.
MIN_SETTLED = 5

# The share of guesses that must have been wanted to climb. Not a hundred per
# cent: an assistant that never guesses wrong is one that never guesses.
ACCURACY_TO_CLIMB = 0.8

# How many consecutive perfect executions each rung above `mention` needs. It is
# a run rather than a rate on purpose - a rate lets an old failure be diluted by
# volume, and *"executing to perfection"* is not an average.
RUN_TO_CLIMB = {PREPARE: 3, ACT_AND_REPORT: 5, FULL_STOP: 10}


class NotYet(ValueError):
    """A guess settled before it was made, or graded by its own author."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Guess:
    """One thing Jarvis thinks Krish will want, written down before he knows.

    `because` is required: a guess with no stated trigger cannot be argued with,
    and cannot teach anything when it turns out wrong."""

    domain: str
    what: str
    because: str
    made_at: datetime = field(default_factory=_now)
    by_when: datetime | None = None
    outcome: str | None = None
    settled_at: datetime | None = None
    settled_by: str = ""
    # How the work went, recorded after it was done rather than when Krish said
    # yes. Separate from `outcome` because they are known at different moments.
    quality: str | None = None
    rated_at: datetime | None = None
    rated_by: str = ""

    def __post_init__(self) -> None:
        for name, value in (("domain", self.domain), ("what", self.what),
                            ("because", self.because)):
            if not (value or "").strip():
                raise NotYet(
                    f"a guess needs a {name}. Without it this is a feeling, and "
                    f"a feeling cannot be scored, argued with, or learned from.")

    @property
    def settled(self) -> bool:
        return self.outcome is not None

    @property
    def rated(self) -> bool:
        return self.quality is not None

    def overdue(self, *, now: datetime | None = None) -> bool:
        """Past its deadline and still unsettled.

        An overdue guess is a finding, not a gap in the data: Krish neither asked
        for the thing nor confirmed it, and silence about a deadline that has
        passed is an answer."""
        if self.settled or self.by_when is None:
            return False
        return (now or _now()) > self.by_when


def settle(guess: Guess, *, outcome: str, by: str, agent: str,
           now: datetime | None = None) -> Guess:
    """Record whether the guess was right, on somebody else's word.

    `by` is who or what decided, and it may not be the agent. Nothing in this
    module can work out an outcome for itself - the callers hand it an event
    Jarvis did not author.

    How the work then went is `rate`, and deliberately not a parameter here: at
    the moment Krish says yes, the work has not been done."""
    if outcome not in OUTCOMES:
        raise NotYet(f"outcome must be one of {OUTCOMES}")
    if not (by or "").strip():
        raise NotYet("a settled guess must say who settled it")
    if by.strip().lower() == (agent or "").strip().lower():
        raise NotYet(
            f"{agent!r} cannot score its own guess. A prediction graded by the "
            f"predictor reads a hundred per cent for ever, which is the one "
            f"number this whole record exists to avoid.")
    if guess.settled:
        raise NotYet(
            f"this guess was already settled as {guess.outcome!r}. Re-scoring it "
            f"would let a bad week be tidied up later.")
    when = now or _now()
    if when < guess.made_at:
        raise NotYet(
            "a guess cannot be settled before it was made. Recorded afterwards "
            "it is hindsight, and hindsight scores perfectly.")
    guess.outcome = outcome
    guess.settled_at = when
    guess.settled_by = by.strip()
    return guess


def rate(guess: Guess, *, quality: str, by: str, agent: str,
         now: datetime | None = None) -> Guess:
    """Record how the work turned out, once, on somebody else's word.

    Only a settled guess can be rated: until Krish has said he wanted the thing,
    there is nothing whose execution could be judged. And only once - a second
    rating would let a bad Tuesday be revised on Wednesday, which is the shape
    `settle` already refuses for outcomes."""
    if quality not in QUALITIES:
        raise NotYet(f"quality must be one of {QUALITIES}")
    if not (by or "").strip():
        raise NotYet("a rating must say who gave it")
    if by.strip().lower() == (agent or "").strip().lower():
        raise NotYet(
            f"{agent!r} cannot rate its own work. Executing to perfection is "
            f"Krish's judgement about the result, and an assistant grading "
            f"its own output has the one number that means nothing.")
    if not guess.settled:
        raise NotYet(
            "this guess has not been settled, so there is nothing whose "
            "execution could be judged yet. Krish says whether he wanted it "
            "before anybody says how well it was done.")
    if guess.rated:
        raise NotYet(
            f"this was already rated {guess.quality!r}. A second rating would "
            f"let a bad Tuesday be revised on Wednesday.")
    guess.quality = quality
    guess.rated_at = now or _now()
    guess.rated_by = by.strip()
    return guess


# --- what a domain has earned ----------------------------------------------------


@dataclass(frozen=True)
class Standing:
    """What one domain's record says, and which rung it supports."""

    domain: str
    settled: int
    wanted: int
    not_now: int
    wrong: int
    perfect_run: int
    rung: str
    because: str

    @property
    def accuracy(self) -> float | None:
        if self.settled < MIN_SETTLED:
            return None
        return self.wanted / self.settled


def standing(domain: str, guesses, *, now: datetime | None = None) -> Standing:
    """Read a domain's record. Computes; decides nothing it cannot show.

    `not_now` counts against climbing but is **not** counted as wrong: it is the
    record saying *notice, and wait*, which is a different instruction from
    *stop noticing*."""
    settled = [guess for guess in guesses
               if guess.domain == domain and guess.settled]
    overdue = [guess for guess in guesses
               if guess.domain == domain and guess.overdue(now=now)]
    # A deadline that passed with no answer is a `wrong` that nobody had to
    # record. Leaving it out would let an assistant climb by guessing often and
    # only ever settling the hits.
    wanted = sum(1 for guess in settled if guess.outcome == WANTED)
    not_now = sum(1 for guess in settled if guess.outcome == NOT_NOW)
    wrong = sum(1 for guess in settled if guess.outcome == WRONG) + len(overdue)
    total = len(settled) + len(overdue)

    run = 0
    for guess in sorted((guess for guess in settled if guess.rated),
                        key=lambda guess: guess.rated_at, reverse=True):
        if guess.quality == PERFECT:
            run += 1
        else:
            break

    rung, because = _rung_for(total, wanted, not_now, run)
    return Standing(domain=domain, settled=total, wanted=wanted, not_now=not_now,
                    wrong=wrong, perfect_run=run, rung=rung, because=because)


def _rung_for(settled: int, wanted: int, not_now: int, run: int
              ) -> tuple[str, str]:
    """The highest rung this record supports, and the sentence for it.

    Ordered from the bottom and returns at the first gate it cannot pass, so the
    reason always names the thing that is actually missing rather than the last
    thing checked."""
    if settled < MIN_SETTLED:
        return OBSERVE, (
            f"{settled} guess(es) have been settled, below the {MIN_SETTLED} "
            f"this needs before its rate means anything. Watching, and saying "
            f"nothing.")
    accuracy = wanted / settled
    if accuracy < ACCURACY_TO_CLIMB:
        return OBSERVE, (
            f"{wanted} of {settled} guesses were wanted ({accuracy:.0%}), below "
            f"the {ACCURACY_TO_CLIMB:.0%} needed to start offering. More "
            f"noticing, less suggesting.")
    if not_now:
        return MENTION, (
            f"{accuracy:.0%} of guesses were right, and {not_now} were right at "
            f"the wrong moment. Say what you noticed and let Krish choose the "
            f"moment.")
    for rung in (PREPARE, ACT_AND_REPORT, FULL_STOP):
        if run < RUN_TO_CLIMB[rung]:
            below = RUNGS[RUNGS.index(rung) - 1]
            return below, (
                f"{accuracy:.0%} of guesses were wanted and the last {run} "
                f"execution(s) were faultless - {RUN_TO_CLIMB[rung]} in a row "
                f"are needed for {rung!r}.")
    return FULL_STOP, (
        f"{accuracy:.0%} of guesses were wanted and the last {run} executions "
        f"were faultless. This is the free hand: do it, and show him the "
        f"result.")


def may(domain: str, guesses, *, at_least: str,
        now: datetime | None = None) -> tuple[bool, str]:
    """Whether this domain has earned at least `at_least`."""
    if at_least not in RUNGS:
        raise NotYet(f"rung must be one of {RUNGS}")
    earned = standing(domain, guesses, now=now)
    allowed = RUNGS.index(earned.rung) >= RUNGS.index(at_least)
    return allowed, earned.because


def describe() -> dict:
    return {
        "outcomes": list(OUTCOMES),
        "qualities": list(QUALITIES),
        "rungs": list(RUNGS),
        "rung_meaning": dict(RUNG_MEANING),
        "min_settled": MIN_SETTLED,
        "accuracy_to_climb": ACCURACY_TO_CLIMB,
        "run_to_climb": dict(RUN_TO_CLIMB),
        "grades_itself": False,
        "per_domain": True,
        "outcome_and_quality_are_recorded_separately": True,
    }
