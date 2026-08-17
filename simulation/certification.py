"""What Alpha means, stated so it can fail.

Two gates, and the distinction matters. **Entry** asks whether Alpha can begin -
whether the machinery to run it exists at all. **Certification** asks whether the
organization performed well enough to be trusted with real work. Building the
second without the first produces a suite that certifies against an environment
incapable of exercising it.

**The trap this is written against:** criteria composed by looking at what the
system currently does will certify whatever the system currently does. Everything
passes on the first run, the gate reads green forever, and nobody notices it is
measuring nothing. So the criteria are written from what Alpha *requires*, and
several of them **fail today on purpose**. A test asserts that they do. If this
file ever goes all-green without the underlying work being done, the criteria
were rewritten to the answer.

Criteria reuse `properties.evaluate` rather than introducing a second comparison
language. A certification criterion is exactly a scenario property that must hold
across the organization rather than within one run.

**Authority, recorded rather than implied:** certification currently gates
nothing. There is no production operation to withhold, so passing confers no
permission and failing withholds none. It is the definition of readiness and a
measurement of distance from it, which is worth having on its own - but a gate
described as binding when nothing is bound would be the first false clause in a
system built to avoid them.

Internal rationale: INT-PHIL-0031
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field

from simulation import properties

# A capability that must exist before Alpha can be run at all.
CAPABILITY = "capability"
# A measured property of a run.
MEASURED = "measured"
# A property of the organization's own declarations, independent of any run.
DECLARED = "declared"


@dataclass(frozen=True)
class Criterion:
    """One thing that must be true, and what its being false would mean."""

    name: str
    kind: str
    requires: str
    # The defect or risk admitting this criterion guards against. A criterion
    # whose failure has no consequence anyone can state is a criterion nobody
    # will act on.
    guards: str
    # CAPABILITY: dotted module paths that must import.
    # MEASURED: a property dict for properties.evaluate.
    # DECLARED: the name of a check in _DECLARED_CHECKS.
    target: tuple = ()
    prop: dict = field(default_factory=dict)
    check: str = ""


ENTRY = (
    Criterion(
        "simulated time exists",
        CAPABILITY,
        "A clock the organization reads instead of wall-clock, with sessions and day rollover.",
        "Without it every timing constant is calibrated against the wrong clock, and anything built "
        "before it gets rebuilt.",
        target=("simulation.clock", "simulation.cadences"),
    ),
    Criterion(
        "generators arrive behind a contract",
        CAPABILITY,
        "New data classes join through a registered generator rather than by editing the engine.",
        "Otherwise each new asset class is an engine change, and the engine becomes the thing "
        "nobody can safely modify.",
        target=("simulation.generators", "simulation.generators.orchestrator"),
    ),
    Criterion(
        "runs are isolated and measured",
        CAPABILITY,
        "A scenario runs against its own database and its outcome is read back as metrics.",
        "A run measured by hand is a run whose result cannot be compared to the next one.",
        target=("simulation.harness", "simulation.metrics", "simulation.properties"),
    ),
    Criterion(
        "the world advances continuously",
        CAPABILITY,
        "A baseline world that keeps running across days rather than a sequence of bounded runs.",
        "Bounded runs cannot exhibit anything that takes longer than one run - which currently "
        "includes every intelligence-expiry behaviour the system has.",
        target=("simulation.world",),
    ),
    Criterion(
        "history is queryable",
        CAPABILITY,
        "Past observations are retained and readable as of a point in time.",
        "Without it nothing can be evaluated against what was knowable when a decision was made, "
        "which is the whole guard against lookahead.",
        target=("simulation.history",),
    ),
)


CERTIFICATION = (
    # --- the organization stays intact --------------------------------------
    Criterion(
        "no agent is respawned",
        MEASURED,
        "A run completes without the workforce being rebuilt under it.",
        "A health threshold below real model latency once produced three concurrent processes "
        "under one identity.",
        prop={"name": "no agent was respawned", "metric": "population.respawns",
              "assert": "equals", "value": 0},
    ),
    Criterion(
        "no agent outlives the run",
        MEASURED,
        "Every process stops when the run stops.",
        "Twelve orphaned agent processes once accumulated unnoticed, found only by chasing a result "
        "one of them was still producing.",
        prop={"name": "no agent survived the run", "metric": "population.running_at_end",
              "assert": "is_empty"},
    ),
    Criterion(
        "no directive fails",
        MEASURED,
        "Lifecycle instructions are executed or declined, never broken.",
        "A failed directive is the executor breaking; declining is now a separate outcome, so this "
        "number means what it says.",
        prop={"name": "no directive failed", "metric": "population.failed_directives",
              "assert": "equals", "value": 0},
    ),

    # --- nothing is consumed unjudged ---------------------------------------
    Criterion(
        "every completed report is analysed",
        MEASURED,
        "Work that leaves the queue was actually consumed.",
        "The alternative is a queue that drains by discarding.",
        prop={"name": "every completed report was analysed",
              "metric": "pipeline.unanalysed_completed_reports", "assert": "equals", "value": 0},
    ),
    Criterion(
        "every analysis is graded",
        MEASURED,
        "Evaluation is part of completion, not optional metadata.",
        "The organization's own rule, and the one the compliance layer exists to check.",
        prop={"name": "every analysis was graded", "metric": "pipeline.ungraded_analyses",
              "assert": "equals", "value": 0},
    ),

    # --- currently unmet, and that is the point -----------------------------
    Criterion(
        "the queue drains",
        MEASURED,
        "Analysis retires reports at least as fast as they arrive, so no report waits longer than "
        "the one before it.",
        "The known bottleneck. Measured at a pressure ratio of 1.89 on a real run and 3.15 on "
        "another: the backlog grows for the whole run. An organization that cannot keep up under "
        "its own synthetic load will not keep up under a market's.",
        prop={"name": "the queue drained", "metric": "queue.drained", "assert": "is_true"},
    ),
    Criterion(
        "intelligence expiry engages",
        MEASURED,
        "At least one detection lens binds a regime baseline during the run.",
        "The conditions half of intelligence expiry is built, unit-tested and verified by hand, and "
        "has never once engaged in a run - binding needs ten graded reports and runs produce four. "
        "A capability that cannot occur in the environment it ships into is not a capability yet.",
        prop={"name": "a lens bound a regime baseline", "metric": "intelligence.regime_bound",
              "assert": "is_not_empty"},
    ),
    Criterion(
        "both discovery paths produce work",
        MEASURED,
        "Explorer and Speculator each file reports, so the quantitative path is exercised rather "
        "than assumed.",
        "Every run so far has been Speculator-only: zero detector events, every report from one "
        "producer. Certifying on those runs would certify half an organization.",
        prop={"name": "the quantitative path produced work", "metric": "pipeline.detector_events",
              "assert": "at_least", "value": 1},
    ),

    # --- the organization's own declarations --------------------------------
    Criterion(
        "the declared organization matches the built one",
        DECLARED,
        "No open gaps between what the organization model declares and what exists.",
        "The gap count is pinned so holes cannot grow quietly, but pinning is not closing. Alpha "
        "means closed.",
        check="no_known_gaps",
    ),
    Criterion(
        "the governance layer reports no concerns",
        DECLARED,
        "The metrics that measure the governance machinery find nothing outstanding.",
        "A governance layer with open concerns of its own cannot be relied on to report honestly "
        "about anything else.",
        check="no_governance_concerns",
    ),
)


# Deliberately NOT criteria, recorded so their absence is a decision:
#
#   the charter's unenforced protections - all three need a consequence path, an
#   adjudicator or an agent-facing channel, and requiring them would force
#   building punitive machinery the evidence does not justify. Alpha readiness
#   must not be the reason a sanctions system gets built.
#
#   deferred capabilities that are not due - a deferral holding correctly is not
#   a deficiency, and counting it as one would convert every deliberate omission
#   into a blocker.
EXCLUDED_BY_DECISION = 2


def _no_known_gaps(conn=None) -> tuple[bool, str]:
    import yaml
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "docs" / "organization.yaml"
    declared = yaml.safe_load(path.read_text(encoding="utf-8")).get("known_gap_count")
    return declared == 0, f"known_gap_count is {declared}"


def _no_governance_concerns(conn=None) -> tuple[bool, str]:
    if conn is None:
        return False, "no database given, so governance concerns could not be read"
    from backend import governance

    found = governance.concerns(conn)
    return not found, (f"{len(found)} concern(s): " + "; ".join(found)) if found else "none"


_DECLARED_CHECKS = {
    "no_known_gaps": _no_known_gaps,
    "no_governance_concerns": _no_governance_concerns,
}


def _capability_present(paths: tuple) -> tuple[bool, str]:
    missing = []
    for path in paths:
        try:
            importlib.import_module(path)
        except ImportError:
            missing.append(path)
    return not missing, ("missing: " + ", ".join(missing)) if missing else "present"


def evaluate_entry() -> list[dict]:
    """Whether Alpha can be run at all. Needs no database - it asks what exists."""
    results = []
    for criterion in ENTRY:
        met, detail = _capability_present(criterion.target)
        results.append({"criterion": criterion.name, "gate": "entry", "met": met, "detail": detail})
    return results


def evaluate_certification(metrics: dict | None = None, conn=None) -> list[dict]:
    """Whether the organization performed well enough to be trusted with real work.

    `metrics` comes from a completed run. Omitted, the measured criteria report
    as unmet with the reason - an unrun criterion is not a passed one, the same
    rule `properties.summarise` applies to an empty property set."""
    results = []
    for criterion in CERTIFICATION:
        if criterion.kind == MEASURED:
            if metrics is None:
                met, detail = False, "no run supplied, so this could not be measured"
            else:
                outcome = properties.evaluate(criterion.prop, metrics)
                met = outcome["passed"]
                detail = outcome["detail"] or f"observed {outcome['observed']!r}"
        else:
            met, detail = _DECLARED_CHECKS[criterion.check](conn)
        results.append({
            "criterion": criterion.name, "gate": "certification", "met": met, "detail": detail,
        })
    return results


def report(metrics: dict | None = None, conn=None) -> dict:
    entry = evaluate_entry()
    certification = evaluate_certification(metrics, conn)
    return {
        "entry": entry,
        "certification": certification,
        "entry_met": all(r["met"] for r in entry),
        "certified": all(r["met"] for r in certification),
        "outstanding": [r["criterion"] for r in entry + certification if not r["met"]],
        # Stated on every report so it cannot be inferred away.
        "authority": (
            "nominal: there is no production operation to gate, so passing confers no permission "
            "and failing withholds none"
        ),
    }


def summarise(metrics: dict | None = None, conn=None) -> str:
    data = report(metrics, conn)
    lines = []
    for gate in ("entry", "certification"):
        met = sum(1 for r in data[gate] if r["met"])
        lines.append(f"{gate}: {met}/{len(data[gate])}")
        for result in data[gate]:
            lines.append(f"  {'ok ' if result['met'] else 'NO '} {result['criterion']} - {result['detail']}")
    lines.append(f"authority: {data['authority']}")
    return "\n".join(lines)


if __name__ == "__main__":
    # Owner-run, like the governance report and for the same reason: a gate no
    # agent can invoke cannot be gamed by one, and certification is a statement
    # about the organization rather than work inside it.
    import sys

    from backend import fi_db
    from simulation import metrics as metrics_module

    run_db = sys.argv[1] if len(sys.argv) > 1 else None
    collected = metrics_module.collect(run_db) if run_db else None
    connection = fi_db.get_connection(run_db)
    try:
        print(summarise(collected, connection))
    finally:
        connection.close()
