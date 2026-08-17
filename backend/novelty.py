"""Does this observation fit what the system has seen before? (Constitution §8,
Axiom 8.)

A pure function over history, deliberately kept free of semantics. The tempting
design asks a model "is this novel?", and that produces an assessment nothing
can contradict - the unfalsifiable-judgment failure mode this project has had to
refuse repeatedly. Novelty here is instead *structural*: measured against what
the system has actually recorded, so every verdict can be checked against the
rows that produced it.

What "the current conceptual structure" means concretely, given what this system
holds: the securities it has observed, the detector ratios it has seen for each,
the peer combinations that have co-triggered, and the cross-check outcomes it
has encountered. An observation that lands outside all of those is one the
system has no precedent for.

**This is not the same thing as `novelty_score`, and the two must not be
confused.** That score is Analysis's judgment, formed after reasoning, about
whether a report told the organization anything new. This is a structural fact
computed before reasoning, about whether anything like it has been seen. One is
an input to the other: Analysis is told "no precedent exists" and forms its own
view. Collapsing them would replace a judgment with a count.

The limits are worth stating plainly. Structural novelty cannot notice that two
differently-shaped observations mean the same thing, nor that a familiar-looking
one arrives for an unfamiliar reason. It detects *unprecedented*, which is a
proper subset of *novel*. Semantic novelty needs a conceptual model the system
does not yet have, and asserting one now would be the empty-schema mistake in a
new place.
"""

# Novelty is capped at 1.0 and reasons stack, so a first-ever security carrying
# an unprecedented ratio ranks above one that is merely unfamiliar.
FIRST_OBSERVATION = 1.0
UNPRECEDENTED_RATIO = 0.6
NEW_PEER_COMBINATION = 0.4
NEW_CROSS_CHECK_OUTCOME = 0.3

# Below this, a lead is "expected" - a variation on something already seen.
# Deliberately generous: calling a routine observation novel wastes the scarce
# deep-reasoning call, which is the cost this feature exists to spend well.
NOVEL_THRESHOLD = 0.4


def assess(candidate: dict, history: dict) -> dict:
    """Score how far this observation sits outside recorded experience.

    `candidate` describes one lead: security, ratio, co_triggering, outcome.
    `history` is what the system has seen: securities_seen, ratio_range per
    security, peer_combinations, cross_check_outcomes.

    Returns the score, whether it clears the threshold, and the reasons - the
    reasons matter as much as the number, because a novelty verdict nobody can
    interrogate is the assessment this module exists to avoid producing."""
    security = candidate.get("security")
    reasons = []
    score = 0.0

    if security and security not in history.get("securities_seen", set()):
        score += FIRST_OBSERVATION
        reasons.append(f"first observation ever recorded for {security}")

    ratio = candidate.get("ratio")
    seen_range = (history.get("ratio_range") or {}).get(security)
    if ratio is not None and seen_range:
        low, high = seen_range
        if ratio > high:
            score += UNPRECEDENTED_RATIO
            reasons.append(f"ratio {ratio:.2f} exceeds anything previously seen for {security} (max {high:.2f})")
        elif ratio < low:
            score += UNPRECEDENTED_RATIO
            reasons.append(f"ratio {ratio:.2f} is below anything previously seen for {security} (min {low:.2f})")

    # Sorted, so the same set of co-triggering securities is one combination
    # however it happened to be ordered when recorded.
    co_triggering = candidate.get("co_triggering")
    if co_triggering:
        combination = ",".join(sorted(co_triggering))
        if combination not in history.get("peer_combinations", set()):
            score += NEW_PEER_COMBINATION
            reasons.append(f"peer group has not co-triggered as [{combination}] before")

    outcome = candidate.get("cross_check_outcome")
    if outcome and outcome not in history.get("cross_check_outcomes", set()):
        score += NEW_CROSS_CHECK_OUTCOME
        reasons.append(f"first time a lead has come back '{outcome}'")

    score = min(1.0, score)
    return {
        "score": round(score, 3),
        "is_novel": score >= NOVEL_THRESHOLD,
        "reasons": reasons,
        # Said explicitly rather than left as an empty list. "Nothing about this
        # is unprecedented" is a finding, and a blank field reads as an absent
        # check rather than a completed one.
        "summary": "; ".join(reasons) if reasons else "fits existing experience - nothing unprecedented",
    }
