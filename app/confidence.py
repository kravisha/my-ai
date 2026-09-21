"""Is the local model's answer good enough? Nothing answers that yet, and this
says so rather than inventing a number (Task 01 §4.3).

## The finding, stated in code as well as in docs/CONFIDENCE.md

The task asked for the confidence mechanism to be documented, and added:

> *"If no real mechanism exists and the score is a placeholder, say so
> explicitly rather than inventing one - that finding is more useful than a
> fabricated fix."*

It does not exist. The word "confidence" appeared nowhere in
`app/model_routing.py` before this task; `LocalFirstRouter` escalated on
availability and on exceptions and on nothing else. There is no scorer, no
placeholder that was going to become one, and no threshold that was ever
compared against anything.

So this module is the *seam* rather than the mechanism. `assess()` returns an
`Assessment` whose `score` is `None`, which is a recorded fact - "nobody
measured this" - and never `0.0`, which would read as "measured, and terrible"
and would escalate every request under any threshold above zero.

`app/local_ai.py` sets the precedent this follows exactly: `infer()` is
declared, refuses, and names the increment that will implement it. A refusal
carrying a sentence somebody can act on beats a method that quietly returns a
plausible constant.

## Why it is wired into the router anyway

Because the alternative is that the day a scorer arrives, somebody has to
change the router's decision path, and that is the path this task was called in
to repair. With the seam in place a scorer is `register()`ed and the routing
rule does not move.

It also makes the low-confidence branch testable today, which matters: §7 asks
for a unit test of exactly that decision, and a branch with no test is a branch
that will be wrong when it first runs.

## The rule, so it is not rediscovered from the code

- `score is None` -> **sufficient**. An answer is not rejected on the strength
  of a measurement nobody took. This is why installing a local model does not
  silently escalate everything.
- `score < threshold` and `router.escalate_on_low_confidence` -> insufficient,
  escalate with `low_confidence`.
- otherwise -> sufficient.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app import router_config

# What produces the score today. A string rather than a boolean so the status
# surface and the nightly report can name it, and so the day it changes the
# reports change with it.
MECHANISM_NONE = "none"

NO_MECHANISM = (
    "No confidence mechanism exists in this system. Nothing scores a local "
    "answer, so no answer is ever judged insufficient on quality - see "
    "docs/CONFIDENCE.md. The threshold in config/router.yaml is configured and "
    "unused, which is a finding rather than a bug to be worked around."
)


@dataclass(frozen=True)
class Assessment:
    """What was concluded about one local answer, and on what basis.

    `detail` is not decoration. It is what the call log's `escalation_reason`
    and the nightly report's "why it looks avoidable" column are written from,
    and a verdict with no stated basis is a verdict nobody can argue with."""

    sufficient: bool
    score: float | None
    threshold: float
    mechanism: str
    detail: str


Assessor = Callable[..., "float | None"]

_ASSESSOR: Assessor | None = None
_MECHANISM: str = MECHANISM_NONE


def register(assessor: Assessor | None, mechanism: str = MECHANISM_NONE) -> None:
    """Install the thing that produces a score, or clear it with None.

    Process-wide, like the provider singleton, and for the same reason: how
    this system judges its own answers is a deployment decision, not a
    caller's. Passing None restores the honest state, which is what the suite
    does between tests."""
    global _ASSESSOR, _MECHANISM
    _ASSESSOR = assessor
    _MECHANISM = mechanism if assessor is not None else MECHANISM_NONE


def mechanism() -> str:
    return _MECHANISM


def assess(answer=None, *, request=None, threshold: float | None = None) -> Assessment:
    """Judge one local answer.

    `answer` and `request` are accepted and ignored by the default assessor.
    They are in the signature because a real scorer needs both - the reply and
    what was asked for - and adding a parameter later would mean changing every
    call site, which is the router.

    An assessor that raises is treated as no assessment rather than as a low
    score. A broken scorer must not become an escalation policy: that is the
    same reasoning `LocalFirstRouter.local_is_usable` applies to a broken
    availability check, inverted, because here the safe direction is to keep
    the answer that already exists."""
    limit = router_config.confidence_threshold() if threshold is None else threshold

    score = None
    detail = NO_MECHANISM
    if _ASSESSOR is not None:
        try:
            score = _ASSESSOR(answer=answer, request=request)
        except Exception as bad:  # noqa: BLE001 - a broken scorer is not a verdict
            return Assessment(
                sufficient=True, score=None, threshold=limit, mechanism=_MECHANISM,
                detail=f"the confidence assessor failed ({bad}), so the local answer "
                       f"stands rather than being escalated on a measurement that "
                       f"did not happen")
        detail = f"scored by {_MECHANISM}"

    if score is None:
        return Assessment(sufficient=True, score=None, threshold=limit,
                          mechanism=_MECHANISM, detail=detail)

    score = float(score)
    if score < limit and router_config.escalate_on_low_confidence():
        return Assessment(
            sufficient=False, score=score, threshold=limit, mechanism=_MECHANISM,
            detail=f"confidence {score:.2f} is below the configured threshold "
                   f"{limit:.2f} ({_MECHANISM})")
    if score < limit:
        return Assessment(
            sufficient=True, score=score, threshold=limit, mechanism=_MECHANISM,
            detail=f"confidence {score:.2f} is below the threshold {limit:.2f} but "
                   f"router.escalate_on_low_confidence is off, so the local answer "
                   f"stands and the score is recorded")
    return Assessment(sufficient=True, score=score, threshold=limit,
                      mechanism=_MECHANISM,
                      detail=f"confidence {score:.2f} meets the threshold {limit:.2f}")


def describe() -> dict:
    """For the status surface and the nightly report: what judges answers here."""
    return {
        "mechanism": _MECHANISM,
        "implemented": _ASSESSOR is not None,
        "threshold": router_config.confidence_threshold(),
        "escalate_on_low_confidence": router_config.escalate_on_low_confidence(),
        "note": NO_MECHANISM if _ASSESSOR is None else f"scored by {_MECHANISM}",
        "documented_in": "docs/CONFIDENCE.md",
    }
