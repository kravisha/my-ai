"""How far along a skill is, computed from evidence rather than declared
(Document 1 §22; Document 2 §10, §12.12).

> *"Jarvis must not claim that a skill is learned merely because code was
> generated, documentation was read, a unit test passed, one lucky attempt
> worked, or an external model produced a plausible answer."*

The way to satisfy that is not a rule telling the engine to be careful. It is to
make the claim **underivable**: `state_of()` is a pure function from the recorded
evidence to a state, and nothing anywhere can set a state directly. There is no
`mark_mastered`. An episode is `MASTERED` when the evidence says so and at no
other time, and the same function that reports the state reports what is missing
from the next one.

That also gives Document 2 §11 its answer for free. *"What have you figured out
so far?"* and *"Are you ready to show me?"* are `state_of()` and
`what_is_missing()` rendered into a sentence.

## Why held-out cases are their own gate

Document 1 §16 asks for evaluation on cases not used during development, and the
temptation is to treat that as one more test file. It is a separate **state
transition** here, because the failure it guards against is specific: a recipe
tuned until the development cases pass has been fitted to those cases, and a
suite that mixes the two cannot tell fitting from learning. `TESTING` means the
development cases pass; `VALIDATING` means cases it never saw pass too. Only the
second is evidence of a capability.

## Why mastery needs a person

`AWAITING_FEEDBACK → MASTERED` is the one transition evidence cannot make alone.
Document 2 §7 makes feedback part of completion, and
`app/initiative.HARM_WIDENS_ITS_OWN_AUTHORITY` refuses self-granted authority at
every boldness setting. A skill that promoted itself to operational on its own
test results would be that harm. So the last gate is Krish's, and
`accepted_by_user` is the only field in this module that a human writes.

## Degradation is a real state, not a failure of bookkeeping

A skill that worked and then stopped is different from one that never worked,
and the difference is what tells you whether the environment changed. A
`MASTERED` skill whose later runs fail falls to `DEGRADED`, and repeated failure
to `NEEDS_RETRAINING` — which puts it back in the learning loop rather than
quietly leaving a broken skill registered.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- the ten states, in the order evidence unlocks them -----------------------

IDENTIFIED = "capability_identified"
PLANNED = "learning_planned"
LEARNING = "currently_learning"
PARTIAL = "partially_functional"
TESTING = "testing"
VALIDATING = "real_world_validation"
AWAITING_FEEDBACK = "awaiting_user_feedback"
MASTERED = "learned"
DEGRADED = "degraded"
NEEDS_RETRAINING = "needs_retraining"

# The progression. `DEGRADED` and `NEEDS_RETRAINING` are not on it: they are
# where a mastered skill falls to, not somewhere it climbs through.
PROGRESSION = (IDENTIFIED, PLANNED, LEARNING, PARTIAL, TESTING, VALIDATING,
               AWAITING_FEEDBACK, MASTERED)
STATES = PROGRESSION + (DEGRADED, NEEDS_RETRAINING)

MEANING = {
    IDENTIFIED: "I know what I cannot do, specifically enough to learn it",
    PLANNED: "I have a written plan and know how I will know I succeeded",
    LEARNING: "I am attempting it and recording what happens",
    PARTIAL: "it works on at least one case and not on all of them",
    TESTING: "every case I developed against passes",
    VALIDATING: "cases I never saw pass too, and I am trying it for real",
    AWAITING_FEEDBACK: "it works and I need you to tell me whether it is right",
    MASTERED: "learned, accepted, and usable as an ordinary skill",
    DEGRADED: "it used to work and a later run failed",
    NEEDS_RETRAINING: "it has failed repeatedly since it was learned",
}

# How many consecutive failures after mastery move a skill from DEGRADED to
# NEEDS_RETRAINING. Two rather than one: a single failure can be the
# environment having a bad moment, and demoting a good skill on one bad run
# would make the state noisy enough to ignore. Two in a row is a pattern.
RETRAINING_AFTER_FAILURES = 2


@dataclass(frozen=True)
class Evidence:
    """Everything the state is computed from. Nothing else may influence it.

    A frozen record rather than loose arguments so that the inputs to a mastery
    claim are a single auditable object — the thing a person would want to see
    when asking "on what basis do you say you have learned this"."""

    objective_is_specific: bool = False
    plan_exists: bool = False
    attempts: int = 0
    development_cases: int = 0
    development_passed: int = 0
    heldout_cases: int = 0
    heldout_passed: int = 0
    real_world_trials: int = 0
    real_world_succeeded: int = 0
    # The one field a human writes. See the module docstring.
    accepted_by_user: bool = False
    # Runs after mastery. `post_mastery_failures` counts the current streak, so
    # a success resets it - a skill that fails, works, fails is flaky rather
    # than degraded, and the streak is what tells them apart.
    post_mastery_runs: int = 0
    post_mastery_failures: int = 0

    @property
    def development_all_pass(self) -> bool:
        return self.development_cases > 0 and self.development_passed == self.development_cases

    @property
    def heldout_all_pass(self) -> bool:
        return self.heldout_cases > 0 and self.heldout_passed == self.heldout_cases

    @property
    def trial_succeeded(self) -> bool:
        return self.real_world_trials > 0 and self.real_world_succeeded > 0


@dataclass(frozen=True)
class State:
    """A state and the reason it is not the next one.

    `missing` is never empty except at `MASTERED`, and it is what Document 2
    §11's *"are you ready to show me?"* is answered from."""

    name: str
    meaning: str
    missing: tuple[str, ...] = ()
    next_state: str | None = None

    @property
    def is_mastered(self) -> bool:
        return self.name == MASTERED

    @property
    def may_demonstrate(self) -> bool:
        """Whether there is anything worth showing yet.

        From `PARTIAL` onward: a skill that works on one case is worth
        demonstrating with that stated, and Document 2 §6 asks for evidence
        rather than for perfection. Demonstrating at `LEARNING` would be showing
        somebody a thing that does not run."""
        return self.name in (PARTIAL, TESTING, VALIDATING, AWAITING_FEEDBACK,
                             MASTERED, DEGRADED)


def state_of(evidence: Evidence) -> State:
    """The state this evidence supports, and what the next one needs.

    Read top-down: the degraded branch first, because a mastered skill that
    started failing must not keep reporting `learned` while the checks below
    still find all its old passing evidence intact."""
    if evidence.accepted_by_user and evidence.post_mastery_failures:
        if evidence.post_mastery_failures >= RETRAINING_AFTER_FAILURES:
            return State(NEEDS_RETRAINING, MEANING[NEEDS_RETRAINING],
                         (f"{evidence.post_mastery_failures} consecutive failures "
                          f"since it was learned; it needs to go back through the "
                          f"loop rather than stay registered",),
                         next_state=LEARNING)
        return State(DEGRADED, MEANING[DEGRADED],
                     ("one failure since it was learned; another consecutive one "
                      "moves it to needs_retraining",),
                     next_state=MASTERED)

    if not evidence.objective_is_specific:
        return State(IDENTIFIED, MEANING[IDENTIFIED],
                     ("a learning objective specific enough to test against",),
                     next_state=PLANNED)

    if not evidence.plan_exists:
        return State(IDENTIFIED, MEANING[IDENTIFIED],
                     ("a written learning plan",), next_state=PLANNED)

    if evidence.attempts == 0:
        return State(PLANNED, MEANING[PLANNED],
                     ("at least one attempt, so there is something to diagnose",),
                     next_state=LEARNING)

    if evidence.development_passed == 0:
        return State(LEARNING, MEANING[LEARNING],
                     ("a first case that produces the expected result",),
                     next_state=PARTIAL)

    if not evidence.development_all_pass:
        remaining = evidence.development_cases - evidence.development_passed
        return State(PARTIAL, MEANING[PARTIAL],
                     (f"{remaining} of {evidence.development_cases} development "
                      f"case(s) still failing",), next_state=TESTING)

    if evidence.heldout_cases == 0:
        return State(TESTING, MEANING[TESTING],
                     ("held-out cases. Passing only what I built against shows "
                      "fitting, not learning",), next_state=VALIDATING)

    if not evidence.heldout_all_pass:
        remaining = evidence.heldout_cases - evidence.heldout_passed
        return State(TESTING, MEANING[TESTING],
                     (f"{remaining} of {evidence.heldout_cases} held-out case(s) "
                      f"failing - this is fitting rather than learning, and the "
                      f"recipe needs to change rather than the cases",),
                     next_state=VALIDATING)

    if not evidence.trial_succeeded:
        return State(VALIDATING, MEANING[VALIDATING],
                     ("a controlled real-world trial that succeeded",),
                     next_state=AWAITING_FEEDBACK)

    if not evidence.accepted_by_user:
        return State(AWAITING_FEEDBACK, MEANING[AWAITING_FEEDBACK],
                     ("your judgement. Tests cannot tell me whether this is what "
                      "you actually wanted",), next_state=MASTERED)

    return State(MASTERED, MEANING[MASTERED], (), next_state=None)


def describe(evidence: Evidence) -> dict:
    """The state as data, for a tool result and for the narration."""
    state = state_of(evidence)
    return {
        "state": state.name,
        "means": state.meaning,
        "next_state": state.next_state,
        "missing": list(state.missing),
        "may_demonstrate": state.may_demonstrate,
        "evidence": {
            "attempts": evidence.attempts,
            "development": f"{evidence.development_passed}/{evidence.development_cases}",
            "held_out": f"{evidence.heldout_passed}/{evidence.heldout_cases}",
            "real_world_trials": f"{evidence.real_world_succeeded}/{evidence.real_world_trials}",
            "accepted_by_user": evidence.accepted_by_user,
        },
    }
