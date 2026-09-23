"""Saying back what was understood, before doing the thing that cannot be undone.

Krish, 2026-09-23:

> *"Give him all the capabilities and the command that he cannot change is that
> user will decide what help he needs from Jarvis and Jarvis should reiterate his
> understanding back to the user for critical tasks that are important such as
> sending emails as opposed to raising volume on the radio - the later shouldn't
> need a confirmation. When user confirms Jarvis will act and complete execution.
> This is a relationship that has to be cultivated with time and trust."*

Four things, and they are separable:

1. **All the capabilities.** Nothing here is a capability gate. It does not decide
   what Jarvis can do; it decides what he says first.
2. **The user decides what help he needs.** Structurally: Jarvis cannot confirm
   his own understanding. `confirm` refuses a confirmation from the agent itself,
   for the same reason `gateway/charter.py` refuses a key Jarvis writes - a
   permission the asker can issue is not a permission.
3. **Reiterate for the consequential, not for the trivial.** Which is which is
   **not** decided here. `app/initiative.py` already ranks actions by
   reversibility and reach, and it already says that turning up a radio is `act`
   and sending mail to another person is `propose`. A second scale would be a
   second thing to keep in step with the first, and they would drift.
4. **On confirmation, act and complete.** A confirmation produces a `Mandate`
   with a scope, and execution runs inside it without asking again. Re-asking
   halfway is not caution, it is nagging, and it is what makes a person stop
   granting anything.

## A read-back is not a yes/no question

*"Shall I send the email?"* catches nothing. The misunderstanding is never in the
verb, it is in the particulars - which recipient, which quarter, which file. So an
`Understanding` is a list of particulars, and one for a consequential action with
no particulars is refused.

**And every particular says where it came from.** This is the part that does the
work. *"To the Acme accounts team - you said that. Subject 'Late invoice, Q3' -
I wrote that."* A person's ear catches the second one. A read-back that reads
back only what it was told confirms nothing, because the error lives in what was
inferred.

## What an unknown does

An `Understanding` may carry things Jarvis could not determine. `confirm` refuses
while any remain, unless the caller names each one it is accepting - the shape
`gateway/inquiry.py` uses for its objections, and for the same reason: a single
flag that waves away five unknowns costs the same as waving away one.

## Across turns: the register

A read-back is offered on one turn and answered on the next, so something has to
hold the question in between. `Register` does, and three of its properties are
the point:

- **The model never handles a token.** `execute` asks the register for a live
  mandate that covers *this exact call*, rather than being handed an identifier
  it could replay. Authority comes from who answered, recorded when they
  answered; nothing the model writes can reach it.
- **A mandate is spent.** *"Confirmation licenses the exact action"* - singular.
  Yes to sending one email is not yes to sending it four times, and a mandate
  that survived its own use would say otherwise. `proceed` may be called as often
  as an execution needs, because it only reads; spending is a separate act at the
  call site.
- **Both sides lapse.** An unanswered proposal and an unused confirmation both
  go stale, for the reason `gateway/charter.py` keeps grants short: a yes given
  an hour ago to a question nobody remembers is not consent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app import initiative

# Where a particular came from. Closed, because the whole value of the read-back
# is the difference between the first and the rest.
TOLD = "told"            # Krish said it, in these words or plainly enough.
INFERRED = "inferred"    # Jarvis worked it out. This is where errors live.
DEFAULTED = "defaulted"  # Nobody said, and a convention was used.
SOURCES = (TOLD, INFERRED, DEFAULTED)

# How a particular is read aloud, by source. The wording matters more than it
# looks: "I assumed" invites a correction, "the subject is" does not.
SOURCE_PHRASE = {
    TOLD: "you said",
    INFERRED: "I worked that out",
    DEFAULTED: "nobody said, so I used the usual",
}


class NotStated(ValueError):
    """A read-back that would confirm nothing."""


class NotConfirmed(PermissionError):
    """Something tried to act without the user's confirmation, or to confirm
    on the user's behalf."""


class OutOfScope(PermissionError):
    """An action the confirmation did not cover."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Particular:
    """One detail that could be misunderstood, and where it came from."""

    label: str
    value: str
    source: str = TOLD

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise NotStated(f"{self.label}: source={self.source!r} is not one "
                            f"of {SOURCES}")
        if not (self.label or "").strip():
            raise NotStated("a particular needs a label; an unlabelled value "
                            "cannot be corrected because nobody knows what it is")

    def spoken(self) -> str:
        return f"{self.label}: {self.value} - {SOURCE_PHRASE[self.source]}"


def needs_readback(action: initiative.Action, *, level: str | None = None
                   ) -> tuple[bool, str]:
    """Whether this action must be said back first, and why.

    Derived from `app/initiative.decide`, not from a list kept here. That module
    already knows that raising the volume is `act` and sending mail to another
    person is `propose`, and it knows it from reversibility and reach rather than
    from anybody remembering to add a verb to a list."""
    verdict = initiative.decide(action, level=level)
    if verdict.disposition == initiative.REFUSE:
        return False, (f"this action is refused outright, so there is nothing to "
                       f"confirm: {verdict.reason}")
    if verdict.disposition == initiative.PROPOSE:
        return True, verdict.reason
    return False, (f"{verdict.disposition}: {verdict.reason}")


@dataclass
class Understanding:
    """What Jarvis believes he was asked to do, in the particulars.

    Not a summary. A summary can be agreed to and still be wrong, because the
    listener supplies their own meaning for the vague parts."""

    action: initiative.Action
    particulars: tuple[Particular, ...] = ()
    unknowns: tuple[str, ...] = ()
    at: str = field(default_factory=_now)

    def inferred(self) -> tuple[Particular, ...]:
        return tuple(item for item in self.particulars if item.source != TOLD)

    def check(self, *, level: str | None = None) -> None:
        """Refuse a read-back that would confirm nothing."""
        required, _ = needs_readback(self.action, level=level)
        if required and not self.particulars:
            raise NotStated(
                f"{self.action.name!r} needs the user's confirmation, and a "
                f"read-back with no particulars is 'shall I?' - which catches "
                f"nothing, because the misunderstanding is never in the verb.")

    def spoken(self, *, level: str | None = None) -> list[str]:
        """The read-back, as lines to say.

        Inferred particulars are not buried at the end. They are the ones worth
        hearing, so they are marked in place and counted at the close."""
        self.check(level=level)
        lines = [f"Before I do this: {self.action.summary or self.action.name}"]
        lines += [f"  - {item.spoken()}" for item in self.particulars]
        for unknown in self.unknowns:
            lines.append(f"  - I could not work out: {unknown}")
        guessed = self.inferred()
        if guessed:
            lines.append(
                f"  ({len(guessed)} of those {'is' if len(guessed) == 1 else 'are'} "
                f"mine rather than yours: "
                f"{', '.join(item.label for item in guessed)}.)")
        lines.append("Have I got that right?")
        return lines

    def corrected(self, label: str, value: str) -> "Understanding":
        """Krish's correction, as a new understanding to be said back again.

        A correction returns to the read-back rather than straight to acting: the
        thing being corrected is the evidence that the understanding was wrong,
        and a wrong understanding corrected once is not obviously right. The
        source becomes `told`, because now it was."""
        found = False
        revised = []
        for item in self.particulars:
            if item.label == label:
                revised.append(Particular(label=label, value=value, source=TOLD))
                found = True
            else:
                revised.append(item)
        if not found:
            revised.append(Particular(label=label, value=value, source=TOLD))
        return Understanding(
            action=self.action, particulars=tuple(revised),
            unknowns=tuple(item for item in self.unknowns if item != label))


@dataclass(frozen=True)
class Mandate:
    """What the user confirmed, and therefore what may now be done without asking.

    The scope is the particulars as confirmed. Execution inside it needs no
    further permission - that is the *"act and complete execution"* half - and
    stepping outside it is a new thing that was never agreed to."""

    understanding: Understanding
    confirmed_by: str
    at: str = field(default_factory=_now)
    accepted_unknowns: tuple[str, ...] = ()

    def scope(self) -> dict[str, str]:
        return {item.label: item.value
                for item in self.understanding.particulars}

    def covers(self, action: initiative.Action,
               particulars: dict[str, str] | None = None) -> tuple[bool, str]:
        """Whether this is **the exact action** that was confirmed.

        Krish, 2026-09-23: *"Confirmation licenses the exact action for which the
        permission was granted in the first place."*

        So the comparison is set equality, not a subset check. A first version
        only looked at the particulars a caller happened to pass, which meant
        passing none matched on the name alone - and the name is identical
        between sending one email and sending three. Every confirmed particular
        must be presented and must match; anything missing is as much "not that
        action" as anything different."""
        if action.name != self.understanding.action.name:
            return False, (
                f"{action.name!r} is not what was confirmed "
                f"({self.understanding.action.name!r}).")
        agreed = self.scope()
        presented = dict(particulars or {})

        for label, value in presented.items():
            if label not in agreed:
                return False, (
                    f"{label!r} was never part of what was confirmed. Adding a "
                    f"particular after the fact is a different action wearing "
                    f"the same name.")
            if agreed[label] != value:
                return False, (
                    f"{label} was confirmed as {agreed[label]!r} and this is "
                    f"{value!r}.")
        missing = sorted(set(agreed) - set(presented))
        if missing:
            return False, (
                f"this call does not state {', '.join(missing)}, which "
                f"{'was' if len(missing) == 1 else 'were'} part of what was "
                f"confirmed. A confirmation licenses the exact action it was "
                f"given for, and an unstated particular is one nobody agreed a "
                f"value for.")
        return True, "confirmed"


def confirm(understanding: Understanding, *, confirmed_by: str,
            agent: str, accepting_unknowns: list[str] | None = None,
            level: str | None = None) -> Mandate:
    """Record the user's yes. Refuses a yes Jarvis gave himself.

    *"The user will decide what help he needs from Jarvis"* - so the one thing
    this function will not do is let the asker answer. That is structural here
    and not a rule Jarvis is asked to follow, because a rule he is asked to
    follow is exactly what stops holding in the case it is for."""
    understanding.check(level=level)
    if not (confirmed_by or "").strip():
        raise NotConfirmed("a confirmation must say who gave it")
    if confirmed_by.strip().lower() == (agent or "").strip().lower():
        raise NotConfirmed(
            f"{agent!r} cannot confirm its own understanding. The user decides "
            f"what help he needs; an assistant that may answer for him has "
            f"replaced the decision with a formality.")

    accepted = set(accepting_unknowns or ())
    unknown = accepted - set(understanding.unknowns)
    if unknown:
        raise NotStated(
            f"accepted unknown(s) nobody raised: {sorted(unknown)}. A typo "
            f"standing in for an acceptance is how an unresolved detail becomes "
            f"an agreed one.")
    standing = [item for item in understanding.unknowns if item not in accepted]
    if standing:
        raise NotStated(
            "these were not resolved and were not accepted: "
            + "; ".join(standing)
            + ". Name each one you are proceeding without, or ask.")
    return Mandate(understanding=understanding, confirmed_by=confirmed_by.strip(),
                   accepted_unknowns=tuple(sorted(accepted)))


def proceed(mandate: Mandate | None, action: initiative.Action,
            particulars: dict[str, str] | None = None, *,
            level: str | None = None) -> None:
    """Raise unless this action is covered. Silent when it is.

    An action that needs no read-back at all passes with no mandate: that is the
    radio volume, and requiring a confirmation for it would train the user to say
    yes without listening, which costs the confirmations that matter."""
    required, why = needs_readback(action, level=level)
    if not required:
        return
    if mandate is None:
        raise NotConfirmed(
            f"{action.name!r} needs the user's confirmation first. {why}")
    covered, reason = mandate.covers(action, particulars)
    if not covered:
        raise OutOfScope(f"{reason} Confirming one thing is not confirming the "
                         f"next one.")


# How long a read-back waits for an answer, and how long an answer stays good.
# Short. A question nobody has answered in ten minutes has been overtaken by the
# conversation, and a yes still lying around an hour later is not consent to
# something happening now.
OFFER_MINUTES = 10
MANDATE_MINUTES = 10


@dataclass
class _Held:
    understanding: Understanding
    at: datetime
    mandate: Mandate | None = None
    spent_at: datetime | None = None


class Register:
    """The read-backs waiting for an answer, and the answers not yet used.

    Deliberately in memory and per-process. A confirmation that survived a
    restart would be a yes given to a Jarvis that no longer exists, and asking
    again after a crash costs one question."""

    def __init__(self, *, now=None) -> None:
        # The clock is injectable so every expiry rule is testable at a chosen
        # time, the same split `app/learning/retention.py` uses.
        self._clock = now or (lambda: datetime.now(timezone.utc))
        self._held: list[_Held] = []

    # --- offering -------------------------------------------------------------

    def offer(self, understanding: Understanding, *,
              level: str | None = None) -> Understanding:
        """Hold a read-back open for an answer. Returns what to say."""
        understanding.check(level=level)
        self._sweep()
        # One live question per action: re-proposing the same thing replaces the
        # earlier ask rather than stacking, so an answer cannot land on a
        # question the user has stopped looking at.
        name = understanding.action.name
        self._held = [held for held in self._held
                      if held.understanding.action.name != name
                      or held.mandate is not None]
        self._held.append(_Held(understanding=understanding, at=self._clock()))
        return understanding

    def outstanding(self) -> list[Understanding]:
        self._sweep()
        return [held.understanding for held in self._held
                if held.mandate is None]

    # --- answering ------------------------------------------------------------

    def answer(self, *, confirmed_by: str, agent: str,
               action_name: str | None = None,
               accepting_unknowns: list[str] | None = None) -> Mandate:
        """Krish's yes, against the question it answers.

        Names the action when there is more than one question open, because
        answering "yes" into a room with two questions in it is how the wrong
        thing gets done."""
        self._sweep()
        waiting = [held for held in self._held if held.mandate is None
                   and (action_name is None
                        or held.understanding.action.name == action_name)]
        if not waiting:
            raise NotConfirmed(
                f"there is no read-back waiting to be answered"
                + (f" for {action_name!r}" if action_name else "")
                + ". It may have lapsed, or already been answered - either way "
                  "the thing to do is propose it again rather than assume.")
        if action_name is None and len({held.understanding.action.name
                                        for held in waiting}) > 1:
            raise NotConfirmed(
                "more than one read-back is waiting ("
                + ", ".join(sorted({held.understanding.action.name
                                    for held in waiting}))
                + "). Name which one is being answered: a yes into a room with "
                  "two questions in it is how the wrong thing gets done.")
        held = waiting[-1]
        held.mandate = confirm(held.understanding, confirmed_by=confirmed_by,
                               agent=agent, accepting_unknowns=accepting_unknowns)
        held.at = self._clock()
        return held.mandate

    # --- using ----------------------------------------------------------------

    def mandate_for(self, action: initiative.Action,
                    particulars: dict[str, str] | None = None) -> Mandate | None:
        """A live, unspent confirmation that covers this exact call.

        Looked up by what the call *is*, never by an identifier the caller hands
        in. There is no token for a model to replay, and a call whose arguments
        drifted between the proposal and the attempt simply finds nothing."""
        self._sweep()
        for held in self._held:
            if held.mandate is None or held.spent_at is not None:
                continue
            if held.mandate.covers(action, particulars)[0]:
                return held.mandate
        return None

    def spend(self, mandate: Mandate) -> None:
        """Mark a confirmation used. Yes to one email is not yes to four."""
        for held in self._held:
            if held.mandate is not mandate:
                continue
            if held.spent_at is not None:
                raise NotConfirmed(
                    f"that confirmation was already used at {held.spent_at:%H:%M}. "
                    f"A confirmation licenses the exact action once; doing it "
                    f"again is a new thing to ask about.")
            held.spent_at = self._clock()
            return
        raise NotConfirmed(
            "that confirmation is not live here - it lapsed, or it was never in "
            "this register.")

    # --- housekeeping ---------------------------------------------------------

    def _sweep(self) -> None:
        """Drop what has lapsed. **Spent confirmations are kept** until they
        lapse too.

        Deleting them on use looked tidier and made two things untrue at once:
        `mandate_for`'s check for a spent mandate became dead code carried by the
        sweep, and `spend` could no longer tell "already used" from "never here",
        which are different mistakes with different answers."""
        now = self._clock()
        kept = []
        for held in self._held:
            minutes = MANDATE_MINUTES if held.mandate else OFFER_MINUTES
            if (now - held.at) > timedelta(minutes=minutes):
                continue
            kept.append(held)
        self._held = kept


def describe() -> dict:
    return {
        "sources": list(SOURCES),
        "decided_by": "app/initiative.py",
        "self_confirmation": "refused",
        "trivial_actions_need_confirmation": False,
        "a_confirmation_licenses": ("the exact action, once, with every "
                                   "confirmed particular stated and matching"),
        "offer_minutes": OFFER_MINUTES,
        "mandate_minutes": MANDATE_MINUTES,
        "the_model_handles_no_token": True,
    }
