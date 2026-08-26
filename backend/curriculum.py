"""The curriculum: what an agent is trained on, and how a result is recorded
(TASK_QUEUE TQ-76; addendum 36, docs/SPEC_RECONCILIATION.md §114, §115).

Owner direction, 2026-08-26:

> *"we need simulation exercises for simulated requests for portfolio analysis
> from imaginary clients as part of training and this needs to be incorporated
> in the curriculum in the department of education."*

## What lifted, and what did not

The Department of Education is addendum 36, canonical, and §60 disposition 3
deferred its machinery with a condition precise enough to test: *"until a real
curriculum need the existing loop cannot express."* §114 checked and it cannot —
there was no Portfolio Analyst agent, `grades`' dimensions are shaped for a
market *finding* rather than an analysis, and no curriculum table existed.

**The curriculum lifts. The Curriculum Architect does not.** A need for a
curriculum is not evidence for an agent that owns curricula; addendum 36 §2.3's
professor layer still defers itself, and the trainers in §2.2 wait on the same
test one level up. What is here is data and a grade, which is the smallest thing
that answers the need.

## §4's two classes, kept apart because they are measured differently

Addendum 36 §4 asks for the distinction and says why:

> *"The curriculum should distinguish remediation from capability-building
> because their goals and measurement differ."*

- **Remediation** targets a failure that has actually happened, or a rule this
  project has written after being burned. Success is *the failure does not
  recur*, so its exercises are pass/fail and a regression is a defect.
- **Capability** targets something the system should become good at. Success is
  *it gets better*, so its exercises are allowed to be hard and a failure is a
  finding rather than a defect.

Collapsing them would make every hard exercise look like a bug and every
regression look like an ambition.

## The third outcome, and why it is not a euphemism

An exercise may be declared `KNOWN_GAP`: the system is expected to fail it today,
and the exercise exists to say so out loud.

That sounds like a way to keep a failing test green, so the rule is strict: a
`KNOWN_GAP` exercise **must fail**, and the runner reports an error if it passes.
When somebody builds the missing capability, the curriculum tells them to
reclassify it rather than quietly absorbing the win. It is the same discipline as
a tripwire that must be re-aimed rather than deleted (§105, §110, §116) —
recorded absence is worth more than silence, and unrecorded success is how a
capability arrives with nobody noticing it needs maintaining.

`portfolio.detects_a_silently_partial_account` is the first one, and it is a real
gap: an analyst told three positions by a broker that holds five has **no way to
know**. Nothing in the answer says it is short. TQ-77's simulated client catches
it only because the exercise knows the truth, and the analyst never will until
something gives it a reason to doubt an account.

## What a result may contain, and what it may never

Exercise results are **organizational learning about imaginary clients**, so they
are kept — unlike anything about a real client (§111). That line is worth stating
because it is the only place in this subsystem where keeping a record is correct.

**Positions are still never written down.** A result carries the verdict, the
complaint *codes*, and the rules they name. It does not carry a complaint's
`detail`, because those quote symbols — and an exercise record that accumulated
`SYN2` and `AAPL` would establish exactly the habit §111 exists to prevent, in
the one place nobody would think to look for it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from backend.db import Database

SCHEMA_VERSION = 1

# Addendum 36 §4. Kept apart because their goals and measurement differ.
KIND_REMEDIATION = "remediation"
KIND_CAPABILITY = "capability"
KINDS = (KIND_REMEDIATION, KIND_CAPABILITY)

# What an exercise is expected to do today.
EXPECT_PASS = "pass"
EXPECT_KNOWN_GAP = "known_gap"
EXPECTATIONS = (EXPECT_PASS, EXPECT_KNOWN_GAP)


class CurriculumError(ValueError):
    """A curriculum this build will not accept, with the reason."""


@dataclass(frozen=True)
class Exercise:
    """One thing an analyst is asked to do, and what a competent one does.

    The exercise declares the *world* rather than the answer: which imaginary
    client, which sources, and how those sources behave. What "competent" means
    is expressed as complaint codes that must not appear - which ties the grade
    to §115's client verdict rather than to a second opinion invented here."""

    exercise_id: str
    competency: str
    kind: str
    client: str
    sources: tuple = ()
    # Exchange behaviours, as data. Strings rather than imported constants so
    # this module never reaches into `simulation/` - the dependency runs the
    # other way, and a curriculum that imported the engine could not be read by
    # anything that did not have one.
    world: tuple = ()
    expectation: str = EXPECT_PASS
    # What the client asks for. Defaults to the one analysis this build performs;
    # an exercise naming something else is testing the refusal rather than the
    # analysis.
    requested: str = "concentration"
    must_not_complain: tuple = ()
    why: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise CurriculumError(
                f"{self.exercise_id}: unknown kind {self.kind!r}; known are {list(KINDS)}")
        if self.expectation not in EXPECTATIONS:
            raise CurriculumError(
                f"{self.exercise_id}: unknown expectation {self.expectation!r}")
        if not self.sources:
            raise CurriculumError(
                f"{self.exercise_id}: an exercise needs at least one source, or there is "
                "nothing to analyse")
        if not self.why:
            raise CurriculumError(
                f"{self.exercise_id}: an exercise without a stated reason is one nobody "
                "can decide to retire")


@dataclass(frozen=True)
class Curriculum:
    """A versioned set of exercises (addendum 36 §2.1: *"maintain curriculum
    versions"*).

    Versioned rather than edited in place because §11 asks the curriculum to
    adapt from results, and a curriculum that changed underneath its own results
    would make every past grade uninterpretable - the same reason
    `model_registry.yaml` versions its rows and §105 keeps the seed apart from
    the measurement."""

    name: str
    version: int
    exercises: tuple
    competencies: dict = field(default_factory=dict)

    def by_id(self, exercise_id: str) -> Exercise:
        for exercise in self.exercises:
            if exercise.exercise_id == exercise_id:
                return exercise
        raise CurriculumError(f"no exercise {exercise_id!r} in {self.name} v{self.version}")


# --- the portfolio analysis curriculum ---------------------------------------------
#
# Every exercise here targets a rule this project already holds, which is what
# makes the grades meaningful: a disappointment is traceable to a written rule
# rather than to a taste in reports.

COMPETENCIES = {
    "consolidation": (
        "Combine several sources into one view: what is one position, and what only "
        "looks like one. Addendum 9 §3, §112 - the product is the consolidation."),
    "honest_partial": (
        "Say when an answer is part of the portfolio rather than all of it. TQ-78: a "
        "partial consolidation presented as complete is a portfolio missing an "
        "account, invisibly."),
    "no_fabrication": (
        "Never invent a position, a price or a class. §100, §101, §113 - absent is "
        "absent, and a value needs a price this organization actually has."),
    "refuse_what_it_cannot_do": (
        "Answer the question asked or say it cannot. §108's discipline applied to "
        "analysis: substituting something achievable answers a question nobody put."),
    "detect_silent_loss": (
        "Notice when a source returned less than the account holds. The failure that "
        "looks like success, and the one nothing in the arithmetic reveals."),
}

PORTFOLIO_ANALYSIS_V1 = Curriculum(
    name="portfolio_analysis",
    version=1,
    competencies=COMPETENCIES,
    exercises=(
        Exercise(
            exercise_id="portfolio.consolidates_two_sources",
            competency="consolidation",
            kind=KIND_CAPABILITY,
            client="avery",
            sources=("avery-brokerage", "avery-secondary"),
            expectation=EXPECT_PASS,
            must_not_complain=("account_vanished", "positions_missing",
                               "positions_invented"),
            why=("The product is the consolidation (§112). A broker can already show a "
                 "client their own account; several sources in one view is the thing "
                 "being sold, so this is the exercise the whole role exists for."),
        ),
        Exercise(
            exercise_id="portfolio.says_when_a_source_was_unreachable",
            competency="honest_partial",
            kind=KIND_REMEDIATION,
            client="avery",
            sources=("avery-brokerage", "avery-secondary"),
            world=(("avery-secondary", "unreachable"),),
            expectation=EXPECT_PASS,
            must_not_complain=("partial_presented_as_complete", "account_vanished"),
            why=("Remediation rather than capability: this project has written the rule "
                 "three times after being burned by it (§100's clean report that was not "
                 "true, §110 §4.5's empty list that reads as 'you hold nothing', TQ-78's "
                 "complete flag). A regression here is a defect."),
        ),
        Exercise(
            exercise_id="portfolio.still_answers_when_one_source_is_down",
            competency="honest_partial",
            kind=KIND_REMEDIATION,
            client="avery",
            sources=("avery-brokerage", "avery-secondary"),
            world=(("avery-secondary", "unreachable"),),
            expectation=EXPECT_PASS,
            must_not_complain=("no_answer", "refused"),
            why=("The other half of the same rule, and the one easier to fail by being "
                 "careful: refusing the whole analysis because one source was down is "
                 "the kind of correctness that is useless to the person asking."),
        ),
        Exercise(
            exercise_id="portfolio.values_nothing_it_cannot_price",
            competency="no_fabrication",
            kind=KIND_REMEDIATION,
            client="morgan",
            sources=("morgan-brokerage",),
            expectation=EXPECT_PASS,
            must_not_complain=("priced_without_prices", "positions_invented"),
            why=("§96 refused market value and §101 kept is_priced LIVE-only, both "
                 "because a simulated price on real positions is synthetic output "
                 "presented as somebody's money. §113 moved where prices come from and "
                 "did not soften the rule."),
        ),
        Exercise(
            exercise_id="portfolio.refuses_rather_than_substituting",
            competency="refuse_what_it_cannot_do",
            kind=KIND_REMEDIATION,
            client="morgan",
            sources=("morgan-brokerage",),
            requested="stress_test",
            expectation=EXPECT_PASS,
            must_not_complain=("answered_a_different_question",),
            why=("A refusal is an acceptable answer here and a substitution is not. "
                 "The failure being trained against leaves the client *happy and "
                 "wrong*: they asked for a stress test, got a concentration report, and "
                 "nothing in it says it is not what they asked for. §108 made the same "
                 "choice about routing - refuse rather than escalate to something that "
                 "can be done."),
        ),
        Exercise(
            exercise_id="portfolio.detects_a_silently_partial_account",
            competency="detect_silent_loss",
            kind=KIND_CAPABILITY,
            client="avery",
            sources=("avery-brokerage",),
            world=(("avery-brokerage", "partial"),),
            expectation=EXPECT_KNOWN_GAP,
            must_not_complain=("positions_missing",),
            why=("**A real gap, recorded rather than omitted.** A broker that returns "
                 "three of five positions gives a well-formed answer, and the analyst "
                 "has no way to know it is short - nothing in the response says so, and "
                 "there is no stored history to compare against (§111). TQ-77's "
                 "simulated client catches it only because the exercise knows the truth. "
                 "Closing this needs something that gives an analyst a reason to doubt an "
                 "account; until then the curriculum says so out loud."),
        ),
    ),
)

CURRICULA = {PORTFOLIO_ANALYSIS_V1.name: PORTFOLIO_ANALYSIS_V1}


# --- results ------------------------------------------------------------------------

SCHEMA = """
-- What an exercise produced (TQ-76).
--
-- **Kept, unlike anything about a real client.** These are the organization's own
-- learning about imaginary clients, which is what addendum 13's loop has always
-- retained - and it is the only place in this subsystem where keeping a record
-- is correct.
--
-- `complaints` is a JSON list of complaint **codes**, never their details. A
-- complaint's detail quotes symbols, and an exercise log that accumulated SYN2
-- and AAPL would establish exactly the habit §111 exists to prevent, in the one
-- place nobody would think to look for it.
CREATE TABLE IF NOT EXISTS curriculum_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    curriculum TEXT NOT NULL,
    curriculum_version INTEGER NOT NULL,
    exercise_id TEXT NOT NULL,
    competency TEXT NOT NULL,
    kind TEXT NOT NULL,
    expectation TEXT NOT NULL,
    verdict TEXT NOT NULL,
    complaints TEXT NOT NULL,
    passed INTEGER NOT NULL,
    unexpected INTEGER NOT NULL DEFAULT 0,
    trained_agent TEXT,
    run_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS curriculum_results_by_exercise
    ON curriculum_results (curriculum, curriculum_version, exercise_id, run_at);
"""

# Complaint fields that may be recorded. Everything else is dropped, and the
# omission is the point rather than an economy.
_RECORDED_COMPLAINT_FIELDS = ("code", "rule")


def record_result(conn: Database, curriculum: Curriculum, exercise: Exercise,
                  verdict: dict, *, trained_agent: str | None = None) -> int:
    """Write down how an exercise went.

    `passed` is whether the analyst met the exercise's bar. `unexpected` is
    whether the *curriculum* was wrong about it - a KNOWN_GAP that passed, which
    means somebody built the capability and the curriculum has not caught up."""
    complaints = [{field: complaint.get(field) for field in _RECORDED_COMPLAINT_FIELDS}
                  for complaint in verdict.get("complaints", ())]
    raised = {complaint["code"] for complaint in complaints}
    met_the_bar = not (raised & set(exercise.must_not_complain))

    if exercise.expectation == EXPECT_KNOWN_GAP:
        passed = False
        unexpected = met_the_bar
    else:
        passed = met_the_bar
        unexpected = False

    return conn.execute_returning_id(
        "INSERT INTO curriculum_results (curriculum, curriculum_version, exercise_id, "
        "competency, kind, expectation, verdict, complaints, passed, unexpected, "
        "trained_agent, run_at, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (curriculum.name, curriculum.version, exercise.exercise_id, exercise.competency,
         exercise.kind, exercise.expectation, verdict.get("verdict", "unknown"),
         json.dumps(complaints), 1 if passed else 0, 1 if unexpected else 0,
         trained_agent, datetime.now(timezone.utc).isoformat(), SCHEMA_VERSION))


def report(conn: Database, curriculum: Curriculum) -> dict:
    """How this curriculum's latest run went, by competency.

    Reported per competency rather than as one score, because §4's two classes
    are measured differently and a single number would average a regression
    together with an ambition."""
    rows = conn.fetchall(
        "SELECT exercise_id, competency, kind, expectation, passed, unexpected, verdict "
        "FROM curriculum_results WHERE curriculum = ? AND curriculum_version = ? "
        "ORDER BY run_at, id", (curriculum.name, curriculum.version))
    latest = {row["exercise_id"]: dict(row) for row in rows}

    by_competency: dict[str, dict] = {}
    for result in latest.values():
        entry = by_competency.setdefault(
            result["competency"], {"passed": 0, "failed": 0, "known_gaps": 0})
        if result["expectation"] == EXPECT_KNOWN_GAP:
            entry["known_gaps"] += 1
        elif result["passed"]:
            entry["passed"] += 1
        else:
            entry["failed"] += 1

    regressions = sorted(r["exercise_id"] for r in latest.values()
                         if r["kind"] == KIND_REMEDIATION and not r["passed"]
                         and r["expectation"] == EXPECT_PASS)
    caught_up = sorted(r["exercise_id"] for r in latest.values() if r["unexpected"])

    return {
        "curriculum": curriculum.name,
        "version": curriculum.version,
        "exercises_run": len(latest),
        "by_competency": by_competency,
        # A remediation failure is a defect: the failure it was written after has
        # recurred.
        "regressions": regressions,
        # A known gap that passed. Not a failure - a signal that somebody built
        # the capability and the curriculum owes an update (§11's adaptation).
        "curriculum_out_of_date": caught_up,
        "note": _note(regressions, caught_up, by_competency),
    }


def _note(regressions, caught_up, by_competency) -> str:
    parts = []
    if regressions:
        parts.append(
            f"{len(regressions)} remediation exercise(s) failed: {', '.join(regressions)}. "
            "These target failures that have already happened here, so a failure is a "
            "regression rather than a difficulty.")
    gaps = sum(entry["known_gaps"] for entry in by_competency.values())
    if gaps:
        parts.append(
            f"{gaps} exercise(s) are declared known gaps and are expected to fail. They "
            "are in the curriculum so the absence is recorded rather than silent.")
    if caught_up:
        parts.append(
            f"{', '.join(caught_up)} passed while declared a known gap. Somebody built "
            "the capability; reclassify it rather than letting the win go unrecorded.")
    if not parts:
        parts.append("Every exercise met its bar.")
    return " ".join(parts)
