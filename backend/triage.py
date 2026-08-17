"""Which queued lead Analysis should reason about next.

A pure ranking over the pending queue, deliberately kept out of both fi_db and
agents/analysis.py so the ordering decision can be tested on its own - the
ordering is the substance here, and it should not need a database or a model
call to examine.

Ranking inputs, in precedence order:

1. **Waiting time** overrides everything. Any report older than
   STARVATION_SECONDS sorts first, oldest first within that block.
2. **Structural novelty** (see backend/novelty.py). A lead scoring at or above
   novelty.NOVEL_THRESHOLD is promoted ahead of familiar ones.
3. **Evidence completeness** - whether the lead's cross-check returned, and with
   what outcome. `evidence` ranks above `no_evidence`, above `unanswered`, above
   no cross-check at all.
4. **Report id**, i.e. arrival order, breaking all remaining ties. Among equally
   ranked leads the queue is therefore FIFO.

Deliberately *not* inputs: any prediction of how well a lead will grade; the
*direction* of the cross-check finding as opposed to its presence; and scope
(peer versus individual). Changing any of these is a design decision, not a
tuning change - do not add them without consulting the governing rationale.

Internal rationale: INT-PHIL-0001, INT-PHIL-0002, INT-PHIL-0003, INT-PHIL-0005
"""

import os

from backend.novelty import NOVEL_THRESHOLD

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


def prioritise(reports: list[dict], cross_checks: dict, ages: dict, starvation_seconds: float | None = None,
               novelty_scores: dict | None = None) -> list[dict]:
    """Order the pending queue. `ages` maps report id -> seconds waiting, and
    `novelty_scores` maps report id -> structural novelty (see backend/novelty.py).

    Ties break on report id, which is arrival order - so among equally ranked
    leads the queue stays FIFO, and the change is a refinement of the old
    behaviour rather than a replacement for it."""
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
        # Novel first, then best-evidenced, then arrival order. `novelty_scores`
        # holds whole assessments rather than bare numbers, so the reason a lead
        # was promoted is available to explain() from the same structure that
        # promoted it - two representations would let the ranking and its stated
        # reason drift apart.
        assessment = (novelty_scores or {}).get(report["id"]) or {}
        novel = assessment.get("score", 0.0) >= NOVEL_THRESHOLD
        return (1, 0 if novel else 1, _evidence_rank(report, cross_checks), report["id"])

    return sorted(reports, key=key)


def explain(report: dict, cross_checks: dict, ages: dict, starvation_seconds: float | None = None,
            novelty_scores: dict | None = None) -> str:
    """Why this report sits where it does. Recorded alongside the choice so the
    ordering is auditable rather than merely effective - the same reason every
    other decision in this system carries its reason."""
    if starvation_seconds is None:
        starvation_seconds = STARVATION_SECONDS
    age = ages.get(report["id"], 0.0)
    if age >= starvation_seconds:
        return f"waited {age:.0f}s, past the {starvation_seconds:.0f}s starvation guard"
    novel = (novelty_scores or {}).get(report["id"])
    if novel and novel.get("is_novel"):
        return f"unprecedented: {novel['summary']}"
    if report.get("cross_check_id") is None:
        return "no cross-check on this lead"
    outcome = (cross_checks.get(report["cross_check_id"]) or {}).get("outcome")
    return {
        "evidence": "cross-check answered with evidence from the second frame",
        "no_evidence": "cross-check answered: the second frame found nothing",
        "unanswered": "cross-check timed out unanswered",
    }.get(outcome, "cross-check outcome unknown")
