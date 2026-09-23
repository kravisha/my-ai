"""Investigating something, and being auditable about how.

Owner instruction, 2026-09-23: *"please at least build as much of inquisitive and
deep reasoning abilities without biases as you possibly can."*

`gateway/gaps.py` has an `investigating` state and nothing investigates. §12 of
the Persistence specification lists how a suspicion should be confirmed -
deterministic tests, held-out tests, repeated failures, code inspection,
comparison against requirements - and none of it was implemented. A suspicion
went from `suspected` to `confirmed` because somebody called `confirm`. This is
the part in between.

## "Without biases" is a claim nothing can honestly make

So this does not make it. What it does instead is keep a record of the reasoning
whose **shape** can be checked, and refuse to conclude when the shape is bad.
The difference matters: an agent asserting it reasoned without bias has produced
a number wearing authority nothing earned, which is the thing this repository
refuses everywhere else. An agent that cannot conclude until it has tried to
refute its own answer has been made to do something.

Five biases are computable from an inquiry's own record, and they are the five
checked here:

| | What is computed |
|---|---|
| `one_hypothesis` | only one explanation was ever entertained |
| `no_refutation_attempted` | nothing was recorded that would have refuted the answer, or nothing went looking for it |
| `only_confirming` | every observation supports something; nothing refutes anything and nothing reports finding nothing |
| `single_source` | every observation came from one place |
| `anchored` | the answer is the first hypothesis written down, and no alternative was ever refuted |

Three of those **block** a conclusion rather than warning about it. That is the
whole design: `conclude()` raises unless the shape is sound, and a caller who
disagrees must name each objection it is overriding, which is then recorded on
the conclusion for ever. There is deliberately no `force=True` - a boolean that
waves away every objection at once is the hole through which this kind of
machinery always fails.

## Finding nothing is a result

`observe(..., finding=NOTHING)` exists because an absence is evidence and the
commonest way to fake an investigation is to record only the hits. §12's
`unsupported` state is what an inquiry that looked properly and found nothing
concludes to, and it is not a failure - but it is also not available for free:
`conclude(outcome=UNSUPPORTED)` requires the record to hold an absence or an
elimination, because otherwise nothing separates "I looked and there was
nothing there" from "I did not look", which is `inconclusive`.

## A conclusion is withdrawn, never overwritten

`conclude()` refuses on an inquiry that has already concluded; `reopen()` moves
the old conclusion to `superseded` with the reason it stopped being believed.
An inquiry that changed its mind is the most informative record in the system
and an assignment that erased the previous answer would throw away exactly that.

## Confidence is derived, never asserted

`confidence()` is computed from how many independent sources agreed, whether a
refutation was attempted and survived, and how many alternatives were
eliminated. Nothing may set it. A model's own estimate of its certainty is the
least reliable number in the system and it is not collected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

# --- what an observation can be -----------------------------------------------

SUPPORTS = "supports"
REFUTES = "refutes"
NOTHING = "found_nothing"
NEUTRAL = "neutral"
FINDINGS = (SUPPORTS, REFUTES, NOTHING, NEUTRAL)

# --- how a hypothesis ends ----------------------------------------------------

OPEN = "open"
ELIMINATED = "eliminated"
SURVIVED = "survived"
HYPOTHESIS_STATES = (OPEN, ELIMINATED, SURVIVED)

# --- how an inquiry ends ------------------------------------------------------

CONFIRMED = "confirmed"
UNSUPPORTED = "unsupported"
INCONCLUSIVE = "inconclusive"
OUTCOMES = (CONFIRMED, UNSUPPORTED, INCONCLUSIVE)

# --- the shape checks ---------------------------------------------------------

ONE_HYPOTHESIS = "one_hypothesis"
NO_REFUTATION_ATTEMPTED = "no_refutation_attempted"
ONLY_CONFIRMING = "only_confirming"
SINGLE_SOURCE = "single_source"
ANCHORED = "anchored"
NO_OBSERVATIONS = "no_observations"

# Which objections stop a conclusion, and which are said out loud beside one.
#
# The blocking three are the ones where proceeding would mean the conclusion
# carries no more information than the guess that started it. The other two are
# real and sometimes unavoidable - everything genuinely does point one way
# occasionally, and sometimes there is only one place to look.
BLOCKING = (NO_OBSERVATIONS, ONE_HYPOTHESIS, NO_REFUTATION_ATTEMPTED)
ADVISORY = (ONLY_CONFIRMING, SINGLE_SOURCE, ANCHORED)

OBJECTIONS = {
    NO_OBSERVATIONS: "nothing was observed, so this is the opening guess with a "
                     "record attached rather than a finding",
    ONE_HYPOTHESIS: "only one explanation was ever entertained, so nothing was "
                    "compared and the answer could not have come out differently",
    NO_REFUTATION_ATTEMPTED: "nothing was recorded that would have refuted this "
                             "answer, or nothing went looking for it - so the "
                             "answer has not survived anything",
    ONLY_CONFIRMING: "every observation supports something and none refutes "
                     "anything or reports finding nothing, which is what a "
                     "search for agreement looks like",
    SINGLE_SOURCE: "every observation came from one place, so an error in that "
                   "place is indistinguishable from a fact about the world",
    ANCHORED: "the answer is the first hypothesis written down and no "
              "alternative was ever eliminated",
}


class ShapeRefused(RuntimeError):
    """The inquiry will not conclude, and says which objections stand.

    Raised rather than returned, because a caller that wanted to ignore this
    should have to say so in words - `accepting=[...]` - rather than by not
    reading a return value."""

    def __init__(self, objections: list[str]) -> None:
        self.objections = list(objections)
        super().__init__(
            "this inquiry's shape does not support a conclusion:\n"
            + "\n".join(f"  - {name}: {OBJECTIONS[name]}" for name in objections)
            + "\n\nEither observe more, or conclude(accepting=[...]) naming each "
              "objection you are overriding. It will be recorded on the "
              "conclusion.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Observation:
    """One thing that was looked at, and what it did to which hypothesis."""

    what: str
    source: str
    finding: str
    about: str | None = None        # the hypothesis key it bears on
    at: str = field(default_factory=_now)
    detail: str = ""

    def to_dict(self) -> dict:
        return {"what": self.what, "source": self.source, "finding": self.finding,
                "about": self.about, "at": self.at, "detail": self.detail}


@dataclass
class Hypothesis:
    """One candidate explanation, and what would kill it.

    `refuted_by` is required at the moment the hypothesis is proposed, not
    afterwards. Asking for it later means asking somebody who already believes
    the answer what would change their mind, which is the question they are
    worst at."""

    key: str
    statement: str
    refuted_by: str
    state: str = OPEN
    because: str = ""

    def to_dict(self) -> dict:
        return {"key": self.key, "statement": self.statement,
                "refuted_by": self.refuted_by, "state": self.state,
                "because": self.because}


@dataclass
class Conclusion:
    outcome: str
    answer: str | None
    confidence: float
    reasoning: str
    objections_overridden: tuple[str, ...] = ()
    advisories: tuple[str, ...] = ()
    at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {"outcome": self.outcome, "answer": self.answer,
                "confidence": self.confidence, "reasoning": self.reasoning,
                "objections_overridden": list(self.objections_overridden),
                "advisories": list(self.advisories), "at": self.at}


class Inquiry:
    """One question, its candidate answers, and what was looked at.

    Deliberately holds no reference to the DBA, the ledger or a gap. It is pure
    reasoning state, which is what makes every check on it testable without a
    store, a network or a machine. `gateway/gaps.py` is where an inquiry's result
    turns into a lifecycle transition."""

    def __init__(self, question: str, *, opened_by: str = "jarvis") -> None:
        if not (question or "").strip():
            raise ValueError("an inquiry needs a question; without one there is "
                             "nothing for an observation to be relevant to")
        self.question = question.strip()
        self.opened_by = opened_by
        self.opened_at = _now()
        self.hypotheses: list[Hypothesis] = []
        self.observations: list[Observation] = []
        self.conclusion: Conclusion | None = None
        # Withdrawn conclusions, in the order they were withdrawn. An inquiry
        # that changed its mind and left no trace of having done so is the one
        # shape from which nobody can ever learn anything.
        self.superseded: list[dict] = []

    # --- building it ----------------------------------------------------------

    def hypothesise(self, key: str, statement: str, *, refuted_by: str) -> Hypothesis:
        """Add a candidate answer and what would rule it out.

        `refuted_by` is not optional. A hypothesis nobody said how to kill is
        one that cannot be eliminated, and an inquiry full of those concludes
        whatever it started believing."""
        if not (refuted_by or "").strip():
            raise ValueError(
                f"hypothesis {key!r} must say what would refute it. Asking that "
                f"later means asking somebody who already believes the answer "
                f"what would change their mind, which is the question they are "
                f"worst at.")
        if any(existing.key == key for existing in self.hypotheses):
            raise ValueError(f"hypothesis {key!r} is already in this inquiry")
        hypothesis = Hypothesis(key=key, statement=statement,
                                refuted_by=refuted_by.strip())
        self.hypotheses.append(hypothesis)
        return hypothesis

    def observe(self, what: str, *, source: str, finding: str,
                about: str | None = None, detail: str = "") -> Observation:
        """Record something that was looked at.

        `source` is required so `single_source` can be computed, and `finding`
        is closed so that "I looked and found nothing" is expressible - it is
        evidence, and recording only the hits is the commonest way an
        investigation is faked."""
        if finding not in FINDINGS:
            raise ValueError(f"finding must be one of {FINDINGS}")
        if about is not None and not self._get(about):
            raise ValueError(
                f"observation is about {about!r}, which is not a hypothesis in "
                f"this inquiry. Add it first, or leave `about` empty.")
        if not (source or "").strip():
            raise ValueError("an observation must say where it came from")
        observation = Observation(what=what, source=source.strip(),
                                  finding=finding, about=about, detail=detail)
        self.observations.append(observation)
        if finding == REFUTES and about:
            self._get(about).state = ELIMINATED
            self._get(about).because = what
        return observation

    def _get(self, key: str) -> Hypothesis | None:
        return next((item for item in self.hypotheses if item.key == key), None)

    # --- auditing the shape ---------------------------------------------------

    def audit(self, *, answer: str | None = None) -> list[str]:
        """Which objections stand, for a conclusion naming `answer`.

        Computed from the record and nothing else. No judgement is involved,
        which is the point - a bias check that required a judgement about
        whether one is biased would be the same instrument measuring itself."""
        found: list[str] = []

        if not self.observations:
            found.append(NO_OBSERVATIONS)
        if len(self.hypotheses) < 2:
            found.append(ONE_HYPOTHESIS)

        if answer is not None:
            addressed = any(
                observation.about == answer
                and observation.finding in (REFUTES, NOTHING)
                for observation in self.observations)
            candidate = self._get(answer)
            if candidate is None or not candidate.refuted_by or not addressed:
                found.append(NO_REFUTATION_ATTEMPTED)
        elif not any(observation.finding in (REFUTES, NOTHING)
                     for observation in self.observations):
            found.append(NO_REFUTATION_ATTEMPTED)

        if self.observations and all(observation.finding == SUPPORTS
                                     for observation in self.observations):
            found.append(ONLY_CONFIRMING)

        sources = {observation.source for observation in self.observations}
        if len(self.observations) > 1 and len(sources) == 1:
            found.append(SINGLE_SOURCE)

        if (answer is not None and self.hypotheses
                and self.hypotheses[0].key == answer
                and not any(item.state == ELIMINATED for item in self.hypotheses)):
            found.append(ANCHORED)

        return found

    def blocking(self, *, answer: str | None = None) -> list[str]:
        return [name for name in self.audit(answer=answer) if name in BLOCKING]

    def advisories(self, *, answer: str | None = None) -> list[str]:
        return [name for name in self.audit(answer=answer) if name in ADVISORY]

    # --- confidence, derived ---------------------------------------------------

    def confidence(self, answer: str | None = None) -> float:
        """Earned, never asserted. Nothing may set this.

        Four things move it, each of which is a fact about the record: how many
        independent sources agreed, whether a refutation was attempted and
        survived, how many alternatives were eliminated, and whether anything
        refuted the answer anyway. A model's own estimate of its certainty is
        the least reliable number available and is not collected."""
        if not self.observations:
            return 0.0

        supporting = [observation for observation in self.observations
                      if observation.finding == SUPPORTS
                      and (answer is None or observation.about == answer)]
        against = [observation for observation in self.observations
                   if observation.finding == REFUTES
                   and (answer is None or observation.about == answer)]
        if against:
            return 0.0

        score = 0.0
        # Independent agreement, not volume: three observations from one source
        # are one observation.
        score += min(0.4, 0.2 * len({item.source for item in supporting}))
        # A refutation attempted and survived is worth more than agreement.
        if answer is not None and any(
                observation.about == answer and observation.finding == NOTHING
                for observation in self.observations):
            score += 0.3
        # Alternatives actually eliminated.
        eliminated = sum(1 for item in self.hypotheses if item.state == ELIMINATED)
        score += min(0.2, 0.1 * eliminated)
        # A clean shape.
        if not self.audit(answer=answer):
            score += 0.1
        return round(min(1.0, score), 2)

    # --- concluding -----------------------------------------------------------

    def conclude(self, *, outcome: str, answer: str | None = None,
                 reasoning: str = "", accepting: list[str] | None = None
                 ) -> Conclusion:
        """Close the inquiry, or refuse to.

        `accepting` names each blocking objection being overridden, and every
        name given is recorded on the conclusion permanently. There is no
        `force=True`: a single boolean that waves away every objection at once
        is the hole this kind of machinery always fails through, because it
        costs the same to override one objection as five."""
        if self.conclusion is not None:
            raise ValueError(
                "this inquiry has already concluded. Call reopen(because=...) "
                "first - silently replacing a conclusion loses the fact that it "
                "changed, which is the most informative thing that happened.")
        if outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of {OUTCOMES}")
        if outcome == CONFIRMED and not answer:
            raise ValueError("a confirmed inquiry must say which hypothesis it "
                             "confirmed")
        if answer is not None and not self._get(answer):
            raise ValueError(f"{answer!r} is not a hypothesis in this inquiry")
        if answer is not None and self._get(answer).state == ELIMINATED:
            raise ValueError(
                f"{answer!r} was eliminated by {self._get(answer).because!r}. "
                f"This is not a bias to be weighed and overridden - it is a "
                f"contradiction with the inquiry's own record, so `accepting` "
                f"does not apply. Reopen it with an observation if the "
                f"elimination was wrong.")

        accepted = set(accepting or [])
        unknown = accepted - set(OBJECTIONS)
        if unknown:
            raise ValueError(
                f"unknown objection(s) {sorted(unknown)}. Accepting an objection "
                f"nobody raised would let a typo stand in for an override.")

        standing = [name for name in self.blocking(answer=answer)
                    if name not in accepted]
        if standing:
            raise ShapeRefused(standing)

        # After the shape gate, deliberately: "you observed nothing" is a more
        # basic complaint than "your observations do not support this particular
        # outcome", and hearing the second one first would send a caller looking
        # in the wrong place.
        if outcome == UNSUPPORTED and not (
                any(item.finding == NOTHING for item in self.observations)
                or any(item.state == ELIMINATED for item in self.hypotheses)):
            raise ValueError(
                "`unsupported` is the outcome of having looked and found "
                "nothing, so the record must hold either an observation that "
                "found nothing or a hypothesis something eliminated. With "
                "neither, nothing distinguishes this from not having looked, "
                "which is `inconclusive`. The usual cause is a refuting "
                "observation recorded without `about`, which eliminates "
                "nothing.")

        if answer is not None:
            candidate = self._get(answer)
            if candidate.state == OPEN:
                candidate.state = SURVIVED

        self.conclusion = Conclusion(
            outcome=outcome, answer=answer,
            confidence=self.confidence(answer),
            reasoning=reasoning,
            objections_overridden=tuple(sorted(accepted & set(self.blocking(answer=answer)))),
            advisories=tuple(self.advisories(answer=answer)))
        return self.conclusion

    def reopen(self, *, because: str) -> Conclusion:
        """Withdraw the conclusion, keeping it on the record.

        `because` is required. An inquiry that reversed itself is more
        informative than one that never wavered, and the reason it reversed is
        the whole of that information - so it is not optional and the old
        conclusion is not deleted."""
        if self.conclusion is None:
            raise ValueError("this inquiry has not concluded, so there is "
                             "nothing to withdraw")
        if not (because or "").strip():
            raise ValueError("withdrawing a conclusion must say why")
        withdrawn = self.conclusion
        self.superseded.append({"conclusion": withdrawn.to_dict(),
                                "because": because.strip(), "at": _now()})
        self.conclusion = None
        return withdrawn

    # --- what it hands on ------------------------------------------------------

    def evidence(self) -> dict:
        """The whole record, for `gaps.confirm(evidence=...)`.

        Everything, including what was eliminated and what found nothing. §12
        asks that the evidence which caused a classification be preserved, and
        an evidence bundle holding only the winning line is a story rather than
        a record."""
        return {
            "question": self.question,
            "opened_by": self.opened_by,
            "opened_at": self.opened_at,
            "hypotheses": [item.to_dict() for item in self.hypotheses],
            "observations": [item.to_dict() for item in self.observations],
            "conclusion": self.conclusion.to_dict() if self.conclusion else None,
            "superseded": list(self.superseded),
            "audit": self.audit(answer=self.conclusion.answer if self.conclusion else None),
        }

    def narrate(self) -> list[str]:
        """The reasoning in the order it happened, for a person to read.

        Eliminated hypotheses are included. An account that mentions only the
        surviving answer is the shape of a conclusion looking for support."""
        lines = [f"Question: {self.question}"]
        for item in self.hypotheses:
            mark = {OPEN: "?", ELIMINATED: "x", SURVIVED: "+"}[item.state]
            lines.append(f"  [{mark}] {item.key}: {item.statement}")
            lines.append(f"        would be refuted by: {item.refuted_by}")
            if item.state == ELIMINATED:
                lines.append(f"        eliminated by: {item.because}")
        for observation in self.observations:
            lines.append(f"  - {observation.finding} ({observation.source}): "
                         f"{observation.what}")
        for withdrawn in self.superseded:
            lines.append(f"  WITHDRAWN: {withdrawn['conclusion']['outcome']}"
                         f" -> {withdrawn['conclusion']['answer']}"
                         f" ({withdrawn['because']})")
        if self.conclusion is not None:
            lines.append(f"Conclusion: {self.conclusion.outcome}"
                         f"{f' -> {self.conclusion.answer}' if self.conclusion.answer else ''}"
                         f" (confidence {self.conclusion.confidence})")
            for name in self.conclusion.objections_overridden:
                lines.append(f"  OVERRODE: {name} - {OBJECTIONS[name]}")
            for name in self.conclusion.advisories:
                lines.append(f"  note: {name} - {OBJECTIONS[name]}")
        return lines


def describe() -> dict:
    return {
        "findings": list(FINDINGS),
        "outcomes": list(OUTCOMES),
        "blocking_objections": list(BLOCKING),
        "advisory_objections": list(ADVISORY),
        "objections": dict(OBJECTIONS),
        "confidence_is_derived": True,
        "no_force_flag": True,
        "conclusions_are_withdrawn_not_overwritten": True,
    }
