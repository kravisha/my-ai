"""Which queued lead Analysis should reason about next.

A pure ranking over the pending queue, deliberately kept out of both fi_db and
agents/analysis.py so the ordering decision can be tested on its own - the
ordering is the substance here, and it should not need a database or a model
call to examine.

**What this deliberately does not do: predict value.** The obvious design is to
rank by how good a lead looks, but the system has no validated way to predict
which lead will grade well, and a ranking built on an unvalidated predictor is
the same trap as scoring stance against templates written alongside the scorer -
it looks principled and measures nothing. Learned prioritisation is Trainer
work, behind validation (addendum 13 §14).

So the ranking uses only what can be *observed* about a report, and only where
the observation supports the inference:

- **Evidence completeness.** A lead whose cross-check came back has two
  independent findings for Analysis to weigh; one whose partner never answered
  has one. That is a statement about how much evidence exists, not about which
  way it points - and the direction is explicitly not consulted here. Ranking on
  whether Speculator's stance *supported* the lead would settle in a queue the
  question addendum 12 §14 reserves for Analysis.
- **Waiting time, which overrides everything.** Without it, a security whose
  cross-checks keep timing out would sit at the back of the queue forever, and
  prioritisation would quietly become permanent suppression. Any report older
  than STARVATION_SECONDS jumps ahead of the ranking entirely.

Scope (peer versus individual) is deliberately *not* a ranking input. Addendum 7
§5 treats the two as different findings, not better and worse ones, and
preferring either would assert a strategic judgment that belongs to Bob rather
than to a queue.
"""

import os

# How long a report may wait before it outranks everything regardless of how
# well-evidenced it is. Starvation is the failure mode prioritisation invents,
# so the guard against it ships in the same file.
#
# **The value has to exceed the queue's drain time, or the guard fires for
# everything and prioritisation silently degenerates to FIFO.** Measured against
# a real ten-security backend: Analysis completes 0.05 reports/sec - one per
# ~20s, since each costs a deep-reasoning call - and the pending queue runs
# 13-20 deep, so a full drain takes 260-400s. A 120s guard (the first value
# tried) was *below* that, meaning every report would have starved before being
# reached and the ranking would never have applied to anything. That is the
# unconsumed-table failure mode in a new shape: a feature that runs, passes its
# tests, and never actually operates.
#
# 900s sits comfortably above the worst measured drain, so the guard catches
# genuinely stuck leads rather than routine queueing. It is a measured constant,
# not a derived one - deriving it from observed throughput would be better, and
# is future work rather than something to guess at now.
STARVATION_SECONDS = float(os.environ.get("FI_TRIAGE_STARVATION_SECONDS", "900"))

# Cross-check outcomes, best-evidenced first. 'evidence' and 'no_evidence' are
# both genuine answers from the second frame; 'unanswered' means nobody replied,
# and None means the lead was never cross-checked at all.
_OUTCOME_RANK = {"evidence": 0, "no_evidence": 1, "unanswered": 2}
_NO_CROSS_CHECK_RANK = 3


def _evidence_rank(report: dict, cross_checks: dict) -> int:
    if report.get("cross_check_id") is None:
        return _NO_CROSS_CHECK_RANK
    outcome = (cross_checks.get(report["cross_check_id"]) or {}).get("outcome")
    return _OUTCOME_RANK.get(outcome, _NO_CROSS_CHECK_RANK)


def prioritise(reports: list[dict], cross_checks: dict, ages: dict, starvation_seconds: float | None = None) -> list[dict]:
    """Order the pending queue. `ages` maps report id -> seconds waiting.

    Ties break on report id, which is arrival order - so among equally
    well-evidenced leads the queue stays FIFO, and the change is a refinement
    of the old behaviour rather than a replacement for it."""
    if starvation_seconds is None:
        starvation_seconds = STARVATION_SECONDS

    def key(report):
        starving = ages.get(report["id"], 0.0) >= starvation_seconds
        # Starving reports sort first as a block, oldest first within it. A
        # starving lead is not promoted *above* other starving leads by being
        # better evidenced - once something has waited too long, waiting longer
        # is the only thing that matters.
        if starving:
            return (0, -ages.get(report["id"], 0.0), report["id"])
        return (1, _evidence_rank(report, cross_checks), report["id"])

    return sorted(reports, key=key)


def explain(report: dict, cross_checks: dict, ages: dict, starvation_seconds: float | None = None) -> str:
    """Why this report sits where it does. Recorded alongside the choice so the
    ordering is auditable rather than merely effective - the same reason every
    other decision in this system carries its reason."""
    if starvation_seconds is None:
        starvation_seconds = STARVATION_SECONDS
    age = ages.get(report["id"], 0.0)
    if age >= starvation_seconds:
        return f"waited {age:.0f}s, past the {starvation_seconds:.0f}s starvation guard"
    if report.get("cross_check_id") is None:
        return "no cross-check on this lead"
    outcome = (cross_checks.get(report["cross_check_id"]) or {}).get("outcome")
    return {
        "evidence": "cross-check answered with evidence from the second frame",
        "no_evidence": "cross-check answered: the second frame found nothing",
        "unanswered": "cross-check timed out unanswered",
    }.get(outcome, "cross-check outcome unknown")
