"""Evaluating a scenario's declared properties against a run's metrics.

A property is a claim that must hold across repeats of a scenario - never a
claim about what the run produced. See `simulation/scenario.py`.

Deliberately a handful of comparators over a dotted metric path, rather than an
expression language. A property has to be readable by whoever is deciding
whether a failure is a real regression, at the moment they are deciding it, and
an expression they have to interpret is one more thing that can be misread.

**A property that cannot be evaluated fails.** A misspelled metric path, an
unknown comparator, a missing comparand: each reports failure with the reason,
rather than being skipped. A skipped property still counts as coverage in
everyone's head, which makes it worse than a property nobody wrote.

Internal rationale: INT-PHIL-0018
"""

from __future__ import annotations

from simulation.metrics import lookup

# `is_not_empty` closes an asymmetry that mattered: without it a suite can
# assert that nothing happened but not that something did, which is backwards
# for a set of properties whose main risk is certifying an idle system.
COMPARATORS = (
    "equals", "at_most", "at_least", "is_empty", "is_not_empty", "is_true", "is_false",
)
NEEDS_VALUE = ("equals", "at_most", "at_least")


def evaluate_all(properties: list[dict], metrics: dict) -> list[dict]:
    return [evaluate(prop, metrics) for prop in properties]


def evaluate(prop: dict, metrics: dict) -> dict:
    name = prop.get("name", "<unnamed>")
    path = prop.get("metric", "")
    comparator = prop.get("assert", "is_true")
    expected = prop.get("value")

    result = {
        "name": name,
        "metric": path,
        "assert": comparator,
        "expected": expected,
        "observed": None,
        "passed": False,
        "detail": "",
    }

    if comparator not in COMPARATORS:
        result["detail"] = f"unknown comparator {comparator!r}; known: {list(COMPARATORS)}"
        return result
    if comparator in NEEDS_VALUE and expected is None:
        result["detail"] = f"comparator {comparator!r} needs a value and none was given"
        return result

    try:
        observed = lookup(metrics, path)
    except KeyError as exc:
        result["detail"] = str(exc)
        return result

    result["observed"] = observed

    try:
        passed, detail = _compare(comparator, observed, expected)
    except TypeError as exc:
        # A comparison between incomparable types is a defect in the scenario,
        # not an inconclusive result, so it fails rather than erroring out of the
        # whole summary.
        result["detail"] = f"cannot compare {observed!r} with {expected!r}: {exc}"
        return result

    result["passed"] = passed
    result["detail"] = detail
    return result


def _compare(comparator: str, observed, expected) -> tuple[bool, str]:
    if comparator == "equals":
        return observed == expected, f"{observed!r} == {expected!r}"
    if comparator == "at_most":
        return observed <= expected, f"{observed!r} <= {expected!r}"
    if comparator == "at_least":
        return observed >= expected, f"{observed!r} >= {expected!r}"
    if comparator == "is_empty":
        try:
            return len(observed) == 0, f"len({observed!r}) == 0"
        except TypeError:
            return False, f"{observed!r} has no length, so 'is_empty' cannot be judged"
    if comparator == "is_not_empty":
        try:
            return len(observed) > 0, f"len({observed!r}) > 0"
        except TypeError:
            return False, f"{observed!r} has no length, so 'is_not_empty' cannot be judged"
    if comparator == "is_true":
        return observed is True, f"{observed!r} is True"
    return observed is False, f"{observed!r} is False"


def summarise(results: list[dict]) -> dict:
    failed = [r for r in results if not r["passed"]]
    return {
        "total": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "failures": [r["name"] for r in failed],
        # An empty property set is reported as such rather than as a pass. A
        # scenario asserting nothing has not been satisfied; it has been unasked.
        "asserted": bool(results),
    }
