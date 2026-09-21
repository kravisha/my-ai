"""Attempt, observe, diagnose, revise — and record all four
(Document 1 §14-§17).

## Expectations are properties, not expected values

A skill that reads live machine state has no fixed right answer: the listening
ports differ between runs, between machines, and between Krish's laptop and this
container. An expected-value test would pass only where it was written, which is
the opposite of evidence.

So a `Case`'s `expect` is a **checkable property** — `rows>=1`,
`field_between:local_port=1..65535`, `unique:pid` — evaluated by `check()` below.
That is what lets the same case run on Linux here and Windows there and mean the
same thing.

## Diagnosis is deterministic, and that is the point

§17: *"When a test fails, Jarvis must not immediately request help from an
expensive external model."* The way to guarantee that is for the first diagnosis
to need no model at all. `diagnose()` reads the recipe's own trace and classifies
the failure by rule — and the rule that earns its place is this one:

> **A step whose `rows_in` was positive and `rows_out` was zero is the failure,
> even when the recipe reported success.**

That is the bug this loop will hit most: a filter comparing against the wrong
literal, or a `derive` that skipped every row because a field name was wrong. The
final answer is merely empty, which looks like "nothing to report" rather than
"step 8 is broken", and a model asked to explain an empty list will invent a
plausible reason. The trace knows.

## The escalation ladder is recorded, not just followed

§19 wants to know *why* an external model was needed. `RESOLUTIONS` is the ladder
in order, and `diagnose()` returns the cheapest rung that could plausibly fix the
failure. When the answer is `external_model`, the reason is part of the record,
so `memory.py` can later report "debugging this class of failure keeps costing
model calls" — which is §26's whole point.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.learning import recipe as recipe_module
from app.learning import sandbox as sandbox_module
from app.learning import store

# --- §17's failure classes -----------------------------------------------------

MISSING_KNOWLEDGE = "missing_knowledge"
INCORRECT_ASSUMPTION = "incorrect_assumption"
IMPLEMENTATION_BUG = "implementation_bug"
ENVIRONMENT_DIFFERENCE = "environment_difference"
DEPENDENCY_ISSUE = "dependency_issue"
PERMISSION_ISSUE = "permission_issue"
MALFORMED_INPUT = "malformed_input"
INCORRECT_TEST_EXPECTATION = "incorrect_test_expectation"
INSUFFICIENT_DECOMPOSITION = "insufficient_skill_decomposition"
INTEGRATION_FAILURE = "integration_failure"
CLASSES = (MISSING_KNOWLEDGE, INCORRECT_ASSUMPTION, IMPLEMENTATION_BUG,
           ENVIRONMENT_DIFFERENCE, DEPENDENCY_ISSUE, PERMISSION_ISSUE,
           MALFORMED_INPUT, INCORRECT_TEST_EXPECTATION,
           INSUFFICIENT_DECOMPOSITION, INTEGRATION_FAILURE)

# §17's resolution ladder, cheapest first. The last rung is the one whose use
# must be justified in the record.
DETERMINISTIC_REASONING = "deterministic_reasoning"
EXISTING_KNOWLEDGE = "existing_knowledge"
EXISTING_SKILLS = "existing_skills"
LOCAL_DOCUMENTATION = "local_documentation"
TARGETED_RESEARCH = "targeted_research"
EXTERNAL_MODEL = "external_model"
RESOLUTIONS = (DETERMINISTIC_REASONING, EXISTING_KNOWLEDGE, EXISTING_SKILLS,
               LOCAL_DOCUMENTATION, TARGETED_RESEARCH, EXTERNAL_MODEL)


@dataclass(frozen=True)
class Diagnosis:
    """Why it failed, how to fix it, and how much that fix should cost."""

    failure_class: str
    resolution: str
    because: str
    at_step: int | None = None
    suggestion: str = ""

    def to_dict(self) -> dict:
        return {"failure_class": self.failure_class, "resolution": self.resolution,
                "because": self.because, "at_step": self.at_step,
                "suggestion": self.suggestion}


@dataclass
class Outcome:
    """One attempt against one case."""

    case_name: str
    passed: bool
    observed: str
    expected: str
    diagnosis: Diagnosis | None = None
    trace: list = field(default_factory=list)
    answer: object = None


# --- checking a property ------------------------------------------------------

_EXPECTATIONS = (
    "no_error", "rows>=N", "rows<=N", "rows==N", "has_field:NAME",
    "field_nonempty:NAME", "field_matches:NAME=REGEX", "field_is_int:NAME",
    "field_between:NAME=LO..HI", "unique:NAME", "sorted_by:NAME",
    "answer_is_int", "contains_field_value:NAME=VALUE",
)


class ExpectationError(ValueError):
    """The case is not checkable, which is a defect in the case, not the skill."""


def check(expectation: str, result) -> tuple[bool, str]:
    """Evaluate one property against a recipe result. Returns (passed, observed).

    `observed` is a sentence rather than a boolean because it goes straight into
    the learning record and into the demonstration: "4 rows, ports 41533-43797"
    is evidence and "False" is not."""
    text = (expectation or "").strip()
    if not text:
        raise ExpectationError("a case with no expectation cannot be checked")

    if not result.ok and text != "no_error":
        return False, f"the recipe failed before this could be checked: {result.error}"

    answer = result.answer
    rows = answer if isinstance(answer, list) else None

    if text == "no_error":
        return result.ok, ("ran without error" if result.ok
                           else f"failed at step {result.failed_step}: {result.error}")

    if text == "answer_is_int":
        return isinstance(answer, int) and not isinstance(answer, bool), \
            f"answer is {type(answer).__name__}"

    match = re.fullmatch(r"rows(>=|<=|==)(\d+)", text)
    if match:
        if rows is None:
            return False, f"answer is {type(answer).__name__}, not rows"
        wanted = int(match.group(2))
        actual = len(rows)
        passed = {">=": actual >= wanted, "<=": actual <= wanted,
                  "==": actual == wanted}[match.group(1)]
        return passed, f"{actual} row(s)"

    if ":" not in text:
        raise ExpectationError(
            f"{text!r} is not a checkable property. The vocabulary is "
            f"{', '.join(_EXPECTATIONS)}.")
    kind, argument = text.split(":", 1)
    kind, argument = kind.strip(), argument.strip()

    if rows is None:
        return False, f"answer is {type(answer).__name__}, not rows"
    if not rows:
        return False, "no rows, so the property cannot hold"

    if kind == "has_field":
        missing = [index for index, row in enumerate(rows) if argument not in row]
        return not missing, (f"all {len(rows)} row(s) have {argument}" if not missing
                             else f"{len(missing)} row(s) missing {argument}")

    if kind == "field_nonempty":
        empty = [row for row in rows if not str(row.get(argument, "")).strip()]
        return not empty, (f"{argument} populated in all {len(rows)} row(s)"
                           if not empty else f"{len(empty)} row(s) have an empty {argument}")

    if kind == "field_is_int":
        bad = [row.get(argument) for row in rows
               if not isinstance(row.get(argument), int) or isinstance(row.get(argument), bool)]
        return not bad, (f"{argument} is an integer in all {len(rows)} row(s)"
                         if not bad else f"{argument} is not an integer: {bad[:3]}")

    if kind == "unique":
        values = [str(row.get(argument)) for row in rows]
        return len(values) == len(set(values)), \
            f"{len(set(values))} distinct {argument} across {len(values)} row(s)"

    if kind == "sorted_by":
        field_name = argument.replace(" desc", "").strip()
        descending = argument.endswith("desc")
        values = [row.get(field_name) for row in rows]
        keyed = [recipe_module._sortable(value) for value in values]
        ordered = keyed == sorted(keyed, reverse=descending)
        return ordered, f"{field_name} {'is' if ordered else 'is not'} in order"

    if kind == "field_matches":
        if "=" not in argument:
            raise ExpectationError("field_matches needs NAME=REGEX")
        name, pattern = argument.split("=", 1)
        compiled = re.compile(pattern)
        bad = [row.get(name.strip()) for row in rows
               if compiled.search(str(row.get(name.strip(), ""))) is None]
        return not bad, (f"{name.strip()} matches {pattern} in all {len(rows)} row(s)"
                         if not bad else f"{len(bad)} row(s) do not match: {bad[:3]}")

    if kind == "field_between":
        if "=" not in argument or ".." not in argument:
            raise ExpectationError("field_between needs NAME=LO..HI")
        name, span = argument.split("=", 1)
        low, high = (float(part) for part in span.split("..", 1))
        outside = []
        for row in rows:
            try:
                value = float(row.get(name.strip()))
            except (TypeError, ValueError):
                outside.append(row.get(name.strip()))
                continue
            if not low <= value <= high:
                outside.append(value)
        return not outside, (
            f"{name.strip()} within {low:g}-{high:g} in all {len(rows)} row(s)"
            if not outside else f"{len(outside)} outside the range: {outside[:3]}")

    if kind == "contains_field_value":
        if "=" not in argument:
            raise ExpectationError("contains_field_value needs NAME=VALUE")
        name, wanted = argument.split("=", 1)
        found = any(str(row.get(name.strip())) == wanted.strip() for row in rows)
        return found, f"{name.strip()}={wanted.strip()} {'found' if found else 'absent'}"

    raise ExpectationError(
        f"{kind!r} is not a checkable property. The vocabulary is "
        f"{', '.join(_EXPECTATIONS)}.")


# --- one attempt ---------------------------------------------------------------


def attempt(episode_id: int, recipe, case, *, kind: str = store.KIND_PRACTICE,
            inputs: dict | None = None, record: bool = True) -> Outcome:
    """Run the recipe against one case, diagnose it if it fails, and record it.

    The sandbox is opened per attempt and destroyed with it, which is what makes
    a practice run reversible in the sense `app/initiative.py` means."""
    with sandbox_module.Sandbox(allow_commands=recipe.needs_commands) as box:
        result = recipe_module.run(recipe, box, inputs)

    try:
        passed, observed = check(case.expect, result)
    except ExpectationError as bad:
        # A case that cannot be checked is a defect in the case. Recorded as
        # such rather than as a failure of the skill, because blaming the recipe
        # for an unparseable expectation sends the next attempt after the wrong
        # thing entirely.
        outcome = Outcome(case.name, False, f"the case is not checkable: {bad}",
                          case.expect,
                          Diagnosis(INCORRECT_TEST_EXPECTATION,
                                    DETERMINISTIC_REASONING, str(bad),
                                    suggestion="fix the expectation, not the recipe"),
                          result.trace, result.answer)
        if record:
            _store(episode_id, recipe, kind, outcome)
        return outcome

    diagnosis = None if passed else diagnose(result, case, observed)
    outcome = Outcome(case.name, passed, observed, case.expect, diagnosis,
                      result.trace, result.answer)
    if record:
        _store(episode_id, recipe, kind, outcome)
    return outcome


def _store(episode_id: int, recipe, kind: str, outcome: Outcome) -> None:
    store.record_attempt(
        episode_id, kind=kind, passed=outcome.passed, case_name=outcome.case_name,
        recipe_version=recipe.version, expected=outcome.expected,
        observed=outcome.observed,
        diagnosis=outcome.diagnosis.to_dict() if outcome.diagnosis else None,
        trace=outcome.trace,
        # Zero model calls, recorded rather than assumed: this is the claim the
        # whole deterministic-skill argument rests on, and a number in the record
        # is what makes it checkable.
        cost={"model_calls": 0, "tokens": 0,
              "steps_run": len([t for t in outcome.trace if t.get("ok")])})


# --- §17's diagnosis -----------------------------------------------------------

# Message fragments that identify a failure class without a model call. Ordered:
# the first match wins, so more specific patterns come first.
_SIGNATURES = (
    # FIRST, and the order is the fix. This message also contains "is not
    # there", and the permission signature below would otherwise claim it -
    # sending the learner to propose an allow-list change for a file that does
    # not exist. Windows CI found that; it is why the two have separate classes.
    ("it is not there", ENVIRONMENT_DIFFERENCE, DETERMINISTIC_REASONING,
     "this path belongs to a platform this machine is not. Do not propose a "
     "boundary - the refusal names the route this platform uses instead, and "
     "the skill needs a second recipe version for it"),
    ("is not permitted", PERMISSION_ISSUE, DETERMINISTIC_REASONING,
     "the sandbox refused a path. Either the skill needs a path it should not "
     "have, or it is reading the wrong one - check the path before proposing a "
     "boundary"),
    ("refused by the deny-list", PERMISSION_ISSUE, DETERMINISTIC_REASONING,
     "this path is never readable; the skill needs a different source"),
    ("is not installed on this machine", DEPENDENCY_ISSUE, DETERMINISTIC_REASONING,
     "the program is allowed but absent here. Either find a file-based route or "
     "record that this skill needs that dependency"),
    ("not one of the", INSUFFICIENT_DECOMPOSITION, DETERMINISTIC_REASONING,
     "the recipe reached for a primitive that does not exist, which means the "
     "decomposition assumed a step the vocabulary cannot express. Either compose "
     "it from what exists or propose the primitive as a boundary"),
    ("did not finish within", ENVIRONMENT_DIFFERENCE, DETERMINISTIC_REASONING,
     "it timed out here. Reduce what the step reads, or the environment is "
     "slower than the skill assumes"),
    ("is not hexadecimal", INCORRECT_ASSUMPTION, DETERMINISTIC_REASONING,
     "a field is not the format the recipe assumed"),
    ("is not four hex bytes", INCORRECT_ASSUMPTION, DETERMINISTIC_REASONING,
     "this is an IPv6 row reaching an IPv4 transform, or the column is wrong"),
    ("needs a field the row does not have", IMPLEMENTATION_BUG, DETERMINISTIC_REASONING,
     "a field name is wrong or a derive step did not run; the trace names which"),
    ("not rows", IMPLEMENTATION_BUG, DETERMINISTIC_REASONING,
     "a step was handed text where it expected rows, or a parse step is missing"),
    ("is not JSON", MALFORMED_INPUT, DETERMINISTIC_REASONING,
     "the source is not the format the recipe assumed"),
    ("nothing before it produced", IMPLEMENTATION_BUG, DETERMINISTIC_REASONING,
     "the steps are out of order"),
    ("could not be read", ENVIRONMENT_DIFFERENCE, DETERMINISTIC_REASONING,
     "the file exists in the design and not on this machine"),
)


def diagnose(result, case, observed: str = "") -> Diagnosis:
    """Classify a failure from the trace alone. No model call.

    Order matters. The collapse check comes **before** the message signatures,
    because a recipe that ran cleanly to an empty answer has no error message to
    match and is the most common real failure - and reporting it as
    "incorrect_test_expectation" because the expectation was the thing that
    failed would send the next attempt after the case instead of the bug."""
    collapsed = _collapse(result.trace)
    if collapsed is not None:
        step = result.trace[collapsed]
        return Diagnosis(
            INCORRECT_ASSUMPTION, DETERMINISTIC_REASONING,
            f"step {collapsed} ({step['op']}) received {step.get('rows_in')} row(s) "
            f"and produced 0. Everything after it worked on nothing, so the empty "
            f"answer is that step rather than the data.",
            at_step=collapsed,
            suggestion=(f"check the {step['op']} step's literal - a filter comparing "
                        f"against the wrong value, or a derive naming a field that "
                        f"is not there, both look exactly like this"))

    message = (result.error or "").lower()
    if message:
        for fragment, failure_class, resolution, suggestion in _SIGNATURES:
            if fragment in message:
                return Diagnosis(failure_class, resolution,
                                 f"the failure message says {fragment!r}",
                                 at_step=result.failed_step, suggestion=suggestion)
        return Diagnosis(
            MISSING_KNOWLEDGE, LOCAL_DOCUMENTATION,
            f"the failure is not one of the {len(_SIGNATURES)} shapes this system "
            f"recognises: {result.error}",
            at_step=result.failed_step,
            suggestion="read the step's own source before escalating; an "
                       "unrecognised failure is a gap in this diagnosis table too")

    # It ran, and the property did not hold.
    return Diagnosis(
        INCORRECT_ASSUMPTION, DETERMINISTIC_REASONING,
        f"the recipe ran and the expected property did not hold: {observed}",
        suggestion=(f"the recipe produced something, so this is a wrong assumption "
                    f"about shape or value rather than a broken step. If the "
                    f"output looks right and the property is wrong, the case is "
                    f"the thing to fix - say so rather than bending the recipe"))


def _collapse(trace: list) -> int | None:
    """The first step that turned rows into nothing. See `diagnose`."""
    for entry in trace:
        if not entry.get("ok"):
            return None
        rows_in, rows_out = entry.get("rows_in"), entry.get("rows_out")
        if isinstance(rows_in, int) and isinstance(rows_out, int) \
                and rows_in > 0 and rows_out == 0:
            return int(entry["step"])
    return None


def run_cases(episode_id: int, recipe, cases, *, kind: str) -> list[Outcome]:
    return [attempt(episode_id, recipe, case, kind=kind) for case in cases]


def evidence_for(episode_id: int, objective) -> dict:
    """Counts `mastery.Evidence` is built from, read back from the store."""
    development = store.latest_case_results(episode_id, store.KIND_DEVELOPMENT)
    heldout = store.latest_case_results(episode_id, store.KIND_HELDOUT)
    trials = store.attempts(episode_id, store.KIND_TRIAL)
    operational = store.attempts(episode_id, store.KIND_OPERATIONAL)
    failures = 0
    for record in reversed(operational):
        if record["passed"]:
            break
        failures += 1
    return {
        "attempts": len(store.attempts(episode_id)),
        "development_cases": len(objective.development_cases),
        "development_passed": len([name for name, passed in development.items()
                                   if passed]),
        "heldout_cases": len(objective.held_out_cases),
        "heldout_passed": len([name for name, passed in heldout.items() if passed]),
        "real_world_trials": len(trials),
        "real_world_succeeded": len([t for t in trials if t["passed"]]),
        "post_mastery_runs": len(operational),
        "post_mastery_failures": failures,
    }
