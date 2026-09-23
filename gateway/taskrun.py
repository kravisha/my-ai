"""A long task done in front of Krish, asking as it goes.

Krish, 2026-09-23, describing the thing he actually wants:

> *"I should say Jarvis prepare my expense statements by looking into my
> business account - ask me questions while you are working on the account so
> that we don't have any confusion about what needs to be done. Also use last
> year's statement as a model and ask me questions when you can't find the data
> that you seek."*

Three instructions in one sentence, and they pull in different directions. Work
without constant interruption. Ask when genuinely stuck. Follow a model. This
module is the shape that satisfies all three, and the shape is mostly refusals.

## The model gives shape, never values

*"Use last year's statement as a model"* is the most dangerous sentence here,
because the obvious implementation is the worst one: copy last year's figures
and change what you can find. A `Model` therefore lists **what a finished thing
has** - the fields, in order, with what each means - and carries no values at
all. There is no path in this module by which last year's number reaches this
year's statement. That is Amendment 3 made structural rather than promised: a
figure with the wrong provenance is a forgery even when nobody notices, and
especially when it happens to be right.

## A need is met by a source or it is not met

Every `Need` is filled by `found(value, source=...)`, and `source` is required.
There is no `assume`, no `default`, no `estimate`. A need that cannot be filled
becomes a `Question`, and a question is the only other way it can leave the
unmet state. An empty statement with three honest questions attached is a better
morning's work than a complete one with a plausible number in it.

## The one who was asked is the one who may answer

A `Question` records who it was put to, and only that person's answer fills the
need. Jarvis answering his own question would be Amendment 1 broken in the place
it is easiest to break it - he is holding the pen, he has a good guess, and the
answer looks identical either way afterwards. So the refusal is in the method
rather than in a rule he is asked to keep.

## Parking a question does not stop the work

Krish's other instruction, from the same day, was not to stall: a blocked need
parks its question and the task carries on with every need that does not depend
on it. `blocked_by` is what makes "does not depend on it" computable rather than
a judgement, and a need whose dependency is unanswered is not attempted - it is
not guessed at either.

## Finishing is a claim, so it is checked

`finish` refuses while any need is unmet and unasked. Reporting a statement as
done with a silent hole in it is the failure this whole arrangement is against,
and it is the one that looks most like success.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from gateway import identity

# --- what can happen to a need --------------------------------------------------

UNMET = "unmet"
FOUND = "found"
ASKED = "asked"
ANSWERED = "answered"
WAIVED = "waived"
STATES = (UNMET, FOUND, ASKED, ANSWERED, WAIVED)

# The states in which a need is settled enough for the task to finish.
SETTLED = (FOUND, ANSWERED, WAIVED)


class NotFound(ValueError):
    """Something tried to fill a need without a source, or to finish with a
    hole in the work."""


class Stuck(RuntimeError):
    """The task cannot go further without Krish."""


class NotYours(RuntimeError):
    """Somebody answered a question that was not put to them.

    Chiefly Jarvis answering his own: Amendment 1 says an agent must never
    supply the permission it is asking for, and a question he may answer is a
    question he did not really ask."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _same(one: str, other: str) -> bool:
    """Two names for the same person. Case and surrounding space are not a
    different person, and treating them as one would make the refusals above
    bypassable by pressing the shift key."""
    return (one or "").strip().lower() == (other or "").strip().lower()


@dataclass(frozen=True)
class Field:
    """One line a finished thing has, from the model. No value."""

    name: str
    means: str

    def __post_init__(self) -> None:
        for label, value in (("name", self.name), ("means", self.means)):
            if not (value or "").strip():
                raise NotFound(f"a model field needs a {label}")


@dataclass(frozen=True)
class Model:
    """What a finished thing looks like. Shape only.

    Built from last year's statement by reading its *headings*, never its
    numbers. A `Model` that could carry a value would make the obvious
    implementation - copy last year and change what you find - reachable, and
    that implementation is a forgery generator with a friendly name."""

    name: str
    fields: tuple[Field, ...]

    def __post_init__(self) -> None:
        if not self.fields:
            raise NotFound(
                f"model {self.name!r} lists no fields, so it says nothing about "
                f"what a finished statement has and cannot be followed")

    def needs(self) -> list["Need"]:
        return [Need(name=one.name, means=one.means) for one in self.fields]


@dataclass
class Question:
    """Something Jarvis could not work out, put to Krish and set aside."""

    about: str
    asked: str
    tried: str
    # Who it was put to. Recorded at the moment of asking rather than at the
    # moment of answering, so that the answer has somebody to be checked
    # against instead of naming itself.
    of: str
    at: datetime = field(default_factory=_now)
    answer: str | None = None
    answered_by: str = ""

    @property
    def open(self) -> bool:
        return self.answer is None


@dataclass
class Need:
    """One thing the work requires, and where it came from if it is there."""

    name: str
    means: str
    state: str = UNMET
    value: str | None = None
    source: str = ""
    # The name of another need this one cannot be attempted without. What makes
    # "carry on with the independent work" computable rather than a judgement.
    blocked_by: str | None = None
    question: Question | None = None

    def found(self, value: str, *, source: str) -> "Need":
        """Fill it, from somewhere.

        `source` is required and is not decoration: it is the difference between
        a figure and a forgery, and the only reason anybody can check this
        later."""
        if not (source or "").strip():
            raise NotFound(
                f"{self.name}: a value needs a source. Where it came from is "
                f"what makes it a figure rather than a guess with a decimal "
                f"point, and there is no method here that fills a need without "
                f"one.")
        if value is None:
            raise NotFound(f"{self.name}: found what?")
        self.value = value
        self.source = source.strip()
        self.state = FOUND
        return self

    def ask(self, question: str, *, tried: str, of: str) -> Question:
        """Give up on finding it, say what was tried, and say who is being asked.

        `tried` is required so that the question is answerable. *"What is the
        March figure?"* invites *"look it up"*; *"the March statement has two
        entries for Acme and I cannot tell which is the invoice"* does not.

        `of` is required so that the answer can be checked against somebody. A
        question addressed to nobody in particular is one Jarvis can answer
        himself the moment it gets inconvenient."""
        if not (question or "").strip():
            raise NotFound(f"{self.name}: ask what?")
        if not (tried or "").strip():
            raise NotFound(
                f"{self.name}: a question must say what was already tried, or "
                f"it is a request for Krish to do the looking.")
        if not (of or "").strip():
            raise NotFound(f"{self.name}: ask whom?")
        if _same(of, identity.AGENT_ID):
            raise NotYours(
                f"{self.name}: {identity.AGENT_ID!r} cannot be the one asked. A "
                f"question put to yourself is a decision wearing a question "
                f"mark.")
        self.question = Question(about=self.name, asked=question.strip(),
                                 tried=tried.strip(), of=of.strip())
        self.state = ASKED
        return self.question

    def answered(self, value: str, *, by: str) -> "Need":
        """Fill it with what the person who was asked said.

        The refusals here are Amendment 1: the asker may not supply the answer,
        and neither may a third party the question was never put to."""
        if self.question is None:
            raise NotFound(f"{self.name}: nothing was asked about this")
        if not (by or "").strip():
            raise NotFound(f"{self.name}: who answered?")
        if value is None:
            raise NotFound(f"{self.name}: answered what?")
        if not _same(by, self.question.of):
            raise NotYours(
                f"{self.name}: this was put to {self.question.of!r} and "
                f"{by.strip()!r} is answering it. Only the one who was asked "
                f"settles it; anybody else is a guess with a name on it.")
        self.question.answer = value
        self.question.answered_by = by.strip()
        self.value = value
        self.source = f"{by.strip()} said so"
        self.state = ANSWERED
        return self

    def waive(self, *, by: str, because: str) -> "Need":
        """Krish's decision to leave it out. His, and recorded as his."""
        if not (by or "").strip() or not (because or "").strip():
            raise NotFound(
                f"{self.name}: waiving a line needs a name and a reason. A hole "
                f"nobody accounted for is the thing this refuses.")
        if _same(by, identity.AGENT_ID):
            raise NotYours(
                f"{self.name}: {identity.AGENT_ID!r} cannot waive a line of his "
                f"own work. Leaving something out is the owner's decision, and "
                f"an assistant who may take it has no holes to report.")
        self.state = WAIVED
        self.source = f"{by.strip()} left it out: {because.strip()}"
        return self

    @property
    def settled(self) -> bool:
        return self.state in SETTLED


class Run:
    """One task, in progress, with its questions and its holes visible."""

    def __init__(self, goal: str, model: Model, *, for_whom: str = "krish"):
        if not (goal or "").strip():
            raise NotFound("a task needs a goal")
        if _same(for_whom, identity.AGENT_ID):
            raise NotYours(
                f"a task cannot be for {identity.AGENT_ID!r}. Whoever the work "
                f"is for is who its questions go to, and work done for himself "
                f"is work he can answer for himself.")
        self.goal = goal.strip()
        self.model = model
        self.for_whom = for_whom
        self.needs: list[Need] = model.needs()
        self.started = _now()

    def need(self, name: str) -> Need:
        for one in self.needs:
            if one.name == name:
                return one
        raise NotFound(
            f"{name!r} is not part of {self.model.name!r}. The model is what a "
            f"finished statement has; adding a line to it mid-task is a "
            f"different statement.")

    def depends(self, name: str, *, on: str) -> Need:
        """Say that one line cannot be attempted before another.

        A cycle is refused here rather than discovered later, because a cycle
        does not crash: every need in it is quietly unworkable forever, the
        narration says *waiting on* about each of them, and the run looks busy
        while nothing can move. `finish` would catch it eventually - but only
        at the end of a morning nobody got anything out of."""
        one, other = self.need(name), self.need(on)
        if one is other:
            raise NotFound(f"{name!r} cannot depend on itself")
        seen = [one.name]
        walk = other
        while walk.blocked_by is not None:
            seen.append(walk.name)
            if walk.blocked_by == one.name:
                raise NotFound(
                    f"{name!r} waiting on {on!r} closes a loop: "
                    + " -> ".join(seen + [one.name])
                    + ". Nothing in a loop is ever workable, and a run that "
                      "cannot move looks exactly like one that is working.")
            walk = self.need(walk.blocked_by)
        one.blocked_by = other.name
        return one

    def ask(self, name: str, question: str, *, tried: str) -> Question:
        """Put a question about one line to whoever the work is for."""
        return self.need(name).ask(question, tried=tried, of=self.for_whom)

    # --- what can be worked on now ------------------------------------------

    def workable(self) -> list[Need]:
        """The needs that can be attempted right now.

        Krish, 2026-09-23, on not stalling: a blocked need parks its question
        and the rest of the work carries on. What it never does is attempt the
        blocked one anyway with a value nobody confirmed."""
        ready = []
        for one in self.needs:
            if one.settled or one.state == ASKED:
                continue
            if one.blocked_by is not None and not self.need(one.blocked_by).settled:
                continue
            ready.append(one)
        return ready

    def open_questions(self) -> list[Question]:
        return [one.question for one in self.needs
                if one.question is not None and one.question.open]

    def holes(self) -> list[Need]:
        """Needs that are neither filled nor asked about. The dangerous set."""
        return [one for one in self.needs
                if not one.settled and one.state != ASKED]

    # --- reporting ------------------------------------------------------------

    def report(self) -> dict:
        return {
            "goal": self.goal,
            "model": self.model.name,
            "settled": [{"name": one.name, "value": one.value,
                         "source": one.source}
                        for one in self.needs if one.settled],
            "questions": [{"about": one.about, "asked": one.asked,
                           "tried": one.tried, "of": one.of}
                          for one in self.open_questions()],
            "holes": [one.name for one in self.holes()],
            "blocked": [{"name": one.name, "on": one.blocked_by}
                        for one in self.needs
                        if one.blocked_by is not None
                        and not self.need(one.blocked_by).settled],
        }

    def narrate(self) -> list[str]:
        """For a person to read while it is happening."""
        lines = [f"{self.goal} (following {self.model.name})"]
        for one in self.needs:
            if one.settled:
                lines.append(f"  [x] {one.name}: {one.value}  - {one.source}")
            elif one.state == ASKED:
                lines.append(f"  [?] {one.name}: {one.question.asked}")
                lines.append(f"        already tried: {one.question.tried}")
            elif one.blocked_by:
                lines.append(f"  [ ] {one.name}: waiting on {one.blocked_by}")
            else:
                lines.append(f"  [ ] {one.name}: not yet")
        return lines

    def finish(self) -> dict:
        """Call it done, or refuse and say what is missing.

        Reporting a statement as finished with a silent hole in it is the
        failure this whole arrangement is against, and the one that looks most
        like success."""
        missing = self.holes()
        if missing:
            raise NotFound(
                "this is not finished: "
                + ", ".join(f"{one.name} ({one.means})" for one in missing)
                + ". Fill them from a source, or ask about them. There is no "
                  "third option, because the third option is a number nobody "
                  "can account for.")
        waiting = self.open_questions()
        if waiting:
            raise Stuck(
                "waiting on Krish: "
                + "; ".join(one.asked for one in waiting))
        return {**self.report(), "finished_at": _now().isoformat(
            timespec="seconds")}


def describe() -> dict:
    return {
        "states": list(STATES),
        "model_carries_values": False,
        "a_value_needs_a_source": True,
        "blocked_work_parks_a_question": True,
        "finishes_with_a_hole": False,
        "answers_its_own_questions": False,
        "dependency_loops": "refused",
    }
