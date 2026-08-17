"""Distributional questions about the personnel rules, answered over many trials.

Some questions cannot be answered by one run however carefully it is set up.
"Does a strong agent qualify" needs a single trial. "How often does a *weak*
agent qualify anyway" is a rate, and a rate needs a population - and it is the
question that decides whether an evidence threshold is high enough.

This is the first thing in this project that has genuinely needed trial volume.
The enterprise-pack disposition deferred Monte Carlo on the grounds that none of
the twelve recorded defects had required it, and that reasoning still holds for
those defects. It does not hold here, and the position is revised rather than
quietly stretched.

**Why these run without a database.** `personnel.sample_grades` is the same
sampler the database path writes rows from, so a trial differs only in whether
the rows were persisted - and thousands of trials at three inserts each is
minutes spent committing to establish something the arithmetic already decides.
The equivalence is asserted directly in the tests rather than assumed.

Nothing here asserts. These functions measure, and the tests decide whether a
measurement is acceptable - so a threshold can be re-derived later without
rewriting the experiment that justified it.

Internal rationale: INT-PHIL-0020
"""

from __future__ import annotations

import random
from collections import Counter

from backend import competency
from simulation import personnel

DEFAULT_TRIALS = 300

# What a qualification for judgment work currently demands. Kept here rather
# than in competency.py because it is a policy, not a rule: the rules say how to
# compare a profile against a requirement, and this is one requirement.
ANALYSIS_REQUIREMENT = {"analytical_quality": 0.5, "evidence_discipline": 0.45}


def _profile_from(grades: list[dict], min_samples: int | None = None) -> dict:
    """Build a profile, optionally overriding the evidence floor for a sweep."""
    if min_samples is None:
        return competency.profile({"grades": grades})

    original = {name: spec["min_samples"] for name, spec in competency.DIMENSIONS.items()}
    try:
        for spec in competency.DIMENSIONS.values():
            spec["min_samples"] = min_samples
        return competency.profile({"grades": grades})
    finally:
        for name, value in original.items():
            competency.DIMENSIONS[name]["min_samples"] = value


def qualification_rate(
    archetype: str,
    evaluate_after: int,
    lifetime_items: int = 60,
    requirement: dict | None = None,
    min_samples: int | None = None,
    trials: int = DEFAULT_TRIALS,
    seed: int = 20260817,
) -> dict:
    """How often this archetype qualifies when judged after `evaluate_after` items.

    For a weak archetype this is the false-promotion rate. For a strong one it is
    the opposite measure - how often a capable agent is held back - and both
    matter, because a threshold high enough to stop every false promotion also
    stops every true one."""
    requirement = requirement or ANALYSIS_REQUIREMENT
    qualified = 0
    blocked_on_evidence = 0

    for trial in range(trials):
        rng = random.Random(seed + trial)
        grades = personnel.sample_grades(archetype, lifetime_items, rng)[:evaluate_after]
        result = competency.evaluate_qualification(_profile_from(grades, min_samples), requirement)
        qualified += result["qualified"]
        blocked_on_evidence += result["blocked_by"] == "evidence"

    return {
        "archetype": archetype,
        "evaluate_after": evaluate_after,
        "min_samples": min_samples,
        "trials": trials,
        "qualified": qualified,
        "rate": round(qualified / trials, 4),
        "blocked_on_evidence_rate": round(blocked_on_evidence / trials, 4),
        "true_competence_at_evaluation": round(
            personnel.true_competence_at(archetype, (evaluate_after - 1) / max(1, lifetime_items - 1)), 4
        ),
    }


def evidence_floor_sweep(
    archetype: str,
    floors: tuple[int, ...] = (5, 10, 20, 30, 40),
    lifetime_items: int = 60,
    trials: int = DEFAULT_TRIALS,
    seed: int = 20260817,
) -> list[dict]:
    """Qualification rate against the evidence floor, judged as soon as it is met.

    The curve that says what `min_samples` should be. Judging at the moment the
    floor is reached is the worst case on purpose: it is what an organization
    eager to promote would do, and a floor that only works if nobody is in a
    hurry is not a floor."""
    return [
        qualification_rate(
            archetype, evaluate_after=floor, lifetime_items=lifetime_items,
            min_samples=floor, trials=trials, seed=seed,
        )
        for floor in floors
    ]


def detection_lag(
    archetype: str = "declining",
    lifetime_items: int = 80,
    window: int | None = None,
    requirement: dict | None = None,
    trials: int = DEFAULT_TRIALS,
    seed: int = 20260817,
) -> dict:
    """How far into a decline the agent stops qualifying.

    Reported as a fraction of the agent's life, so it can be compared across
    window sizes. `window` None means judge on the whole record, which is the
    behaviour a profile with no recency has - and the number it produces is the
    argument for having one."""
    requirement = requirement or ANALYSIS_REQUIREMENT
    lags = []
    never = 0

    for trial in range(trials):
        rng = random.Random(seed + trial)
        grades = personnel.sample_grades(archetype, lifetime_items, rng)
        lost_at = None
        for point in range(competency.DIMENSIONS["analytical_quality"]["min_samples"], lifetime_items + 1):
            considered = grades[:point][-window:] if window else grades[:point]
            if not competency.evaluate_qualification(competency.profile({"grades": considered}), requirement)["qualified"]:
                lost_at = point
                break
        if lost_at is None:
            never += 1
        else:
            lags.append(lost_at / lifetime_items)

    return {
        "archetype": archetype,
        "window": window,
        "trials": trials,
        "never_detected": never,
        "median_lag_fraction": round(_median(lags), 4) if lags else None,
        "worst_lag_fraction": round(max(lags), 4) if lags else None,
    }


def rank_stability(
    archetypes: tuple[str, ...] = ("improving", "declining", "erratic"),
    items: int = 60,
    trials: int = DEFAULT_TRIALS,
    seed: int = 20260817,
) -> dict:
    """How a ranking behaves between agents who are genuinely equal.

    All three archetypes average 0.5 by construction, so there is no true
    ordering to find. Two things are measured: how often each takes the top
    position, which should be roughly uniform because the ordering is noise; and
    how often the ranking claims two of them are *separated*, which is the false
    positive rate of the separation rule and should sit near the tail
    probability the rule was built around."""
    winners = Counter()
    false_separations = 0
    comparisons = 0

    for trial in range(trials):
        rng = random.Random(seed + trial)
        profiles = {
            f"agent_{index}": competency.profile(
                {"grades": personnel.sample_grades(archetype, items, rng)}
            )
            for index, archetype in enumerate(archetypes)
        }
        ranked = [row for row in competency.rank(profiles, "analytical_quality") if row["rank"]]
        if ranked:
            winners[ranked[0]["name"]] += 1
        for row in ranked:
            if row.get("separated") is not None:
                comparisons += 1
                false_separations += bool(row["separated"])

    return {
        "trials": trials,
        "top_position_share": {
            name: round(count / trials, 4) for name, count in sorted(winners.items())
        },
        "comparisons": comparisons,
        "false_separation_rate": round(false_separations / comparisons, 4) if comparisons else None,
    }


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2
