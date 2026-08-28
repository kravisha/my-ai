"""One command, one report: does the organization work?
(TASK_QUEUE TQ-91; docs/SPEC_RECONCILIATION.md §129).

Two simulation systems exist and until now neither knew the other did.
`simulation/harness.py` runs the real organization in its own database under a
scenario; `simulation/training.py` runs the Department of Education's curriculum
against simulated exchanges and clients. **"Everything works end to end" meant two
different things depending on which had been run**, and nothing put the two
answers in one place.

They are not merged, and that is deliberate. A scenario measures the organization
*operating* — processes, queues, timing constants, whether the workforce survives
its own failures. A curriculum measures an agent *learning* — whether it detects
what it should and refuses what it cannot do. Forcing one into the other for
symmetry would cost more than it returns, and the seam between them is real
rather than an accident of history.

What was missing was not a merge. It was a verdict.

## The rule this file exists to hold

**A scenario that did not run is not a scenario that passed.**

That sounds obvious and is the single easiest thing to get wrong here. Three of
the seven scenarios declare `requires_model`, and in an environment with no key
they are skipped. A verifier that reported "0 failures" over four scenarios run
and three skipped would be issuing a clean bill of health for an organization it
had mostly not examined — the vacuity this project has now been bitten by at
§117, §118, §127 and §128, arriving one level higher where it would do the most
damage.

So the verdict has three values, not two. `INCOMPLETE` is not a softer `FAIL`; it
is the honest answer when nothing failed and not everything was asked.

## What it still does not cover

Named in the report itself rather than left for a reader to assume from a green
line. A verifier that lists its own blind spots is worth more than one that
implies it has none.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agents import portfolio_analyst
from backend import curriculum as curriculum_module, fi_db
from simulation import harness, scenario as scenario_module, training

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_INCOMPLETE = "INCOMPLETE"

# What running every scenario and the whole curriculum still does not tell you.
# Written from what the specifications ask for rather than from what the code
# happens to do, for the reason `simulation/certification.py` gives about its own
# criteria: a list composed by looking at what the system currently does will
# always report that the system currently does everything.
# ASCII on purpose. This list is printed to a terminal, and the section sign
# renders as `?` under the Windows console codepage - turning a reference into
# noise exactly where a reader is deciding whether to trust a verdict.
NOT_COVERED = (
    "Deliberation. No agent proposes or votes, so a governed run seeds its "
    "Articles and its resolution (SPEC_RECONCILIATION 128).",
    "Real market data. Every price in every run is synthetic "
    "(SPEC_RECONCILIATION 113), so nothing here exercises valuation.",
    "A real broker, a real client, and the credential path to reach one (TQ-73).",
    "Historical-data operation, which addendum 46 section 27 requires and "
    "nothing implements.",
    # RE-AIMED rather than removed (SPEC_RECONCILIATION 105, 139 section 6). TQ-96
    # built a release over governed data and `release_and_rollback` exercises it,
    # so the old entry is no longer true - but the half of "release" this
    # organization may not perform is still uncovered, and deleting the line would
    # read as though it were.
    "Code release. This organization observes its code version and cannot choose "
    "it (SPEC_RECONCILIATION 139 section 3), so nothing here deploys, restarts, "
    "canaries or coexists versions. Governed-data release and rollback IS covered.",
    "Release acceptance criteria. Health is a judgement somebody records with "
    "evidence, not a threshold anything computes (addendum 30 section 16).",
)


def model_can_be_called() -> bool:
    """Whether a model would actually answer, not whether a key exists.

    `harness.model_is_available()` answers the first question, and the first
    verification run showed that is not enough: the key was reachable, the daily
    token budget was exhausted, and every model call was refused. The
    model-dependent scenarios ran, every report failed instantly with a spending
    message, and the summary reported failures **about the budget while looking
    exactly like failures about the organization** (§132).

    That is precisely what `INCOMPLETE` exists for. A run that could not use a
    model did not test the thing the scenario is about, and reporting it as a
    failure is as wrong as reporting it as a pass."""
    if not harness.model_is_available():
        return False
    try:
        from app import model_budget
        model_budget.check_budget()
    except ImportError:  # pragma: no cover - the budget module is always present
        return True
    except Exception:  # noqa: BLE001 - any refusal means a call would not land
        return False
    return True


def _why_no_model() -> str:
    if not harness.model_is_available():
        return "declares requires_model and no model is reachable"
    return ("declares requires_model and the model budget is exhausted, so every "
            "call would be refused and the run would measure the budget")


@dataclass
class Verification:
    scenarios: list = field(default_factory=list)
    curriculum: dict | None = None
    skipped: list = field(default_factory=list)

    @property
    def failures(self) -> list:
        failed = [entry for entry in self.scenarios if not entry["passed"]]
        if self.curriculum and not self.curriculum["passed"]:
            failed.append({"id": "curriculum", "failures": self.curriculum["failures"]})
        return failed

    @property
    def verdict(self) -> str:
        """`INCOMPLETE` is not a softer `FAIL`.

        A failure means something was asked and answered wrongly. Incomplete
        means it was not asked. Reporting the second as a pass is how a suite
        comes to certify an organization it did not examine."""
        if self.failures:
            return VERDICT_FAIL
        if self.skipped or self.curriculum is None:
            return VERDICT_INCOMPLETE
        return VERDICT_PASS


def verify(*, scenario_ids: list | None = None, include_curriculum: bool = True,
           on_progress=None) -> Verification:
    """Run the scenarios and the curriculum, and compose one answer."""
    result = Verification()
    available = scenario_module.load_all()
    chosen = scenario_ids or sorted(
        sid for sid, scenario in available.items() if scenario.is_runnable)

    for scenario_id in chosen:
        scenario = available.get(scenario_id)
        if scenario is None:
            result.skipped.append({"id": scenario_id, "why": "no such scenario"})
            continue
        if scenario.requires_model and not model_can_be_called():
            # Skipped, and skipped loudly. The alternative - running it anyway -
            # produces a summary describing a different organization than the
            # scenario intends, which the harness already refuses to do.
            result.skipped.append({
                "id": scenario_id,
                "why": _why_no_model()})
            continue
        if on_progress:
            on_progress("scenario", scenario_id, scenario.duration_seconds)
        run = harness.execute(scenario)
        summary = run.summary or {}
        properties = summary.get("properties") or {}
        result.scenarios.append({
            "id": scenario_id,
            "run_id": run.run_id,
            # A run that left an agent process behind fails even if every
            # property passed: the next run inherits the consequences, and
            # results from an organization nobody is watching are worse than no
            # results.
            "passed": bool(run.graceful and run.properties_passed),
            "graceful": run.graceful,
            "properties_passed": properties.get("passed", 0),
            "properties_total": properties.get("total", 0),
            # `properties["failures"]` is a list of NAMES. Reading it as records
            # crashed the first verification run that had a failure to render -
            # and every test of this file constructed the entry by hand rather
            # than from a real summary, so the seam between them was untested by
            # construction (§132).
            "failures": list(properties.get("failures") or []),
        })

    if include_curriculum:
        if on_progress:
            on_progress("curriculum", curriculum_module.PORTFOLIO_ANALYSIS_V1.name, 0)
        result.curriculum = run_curriculum()
    return result


def run_curriculum() -> dict:
    """Every exercise, against a fresh in-memory database.

    Through the real analyst: it claims from the ordinary queue, fetches through
    the ordinary provider lookup, and delivers to the ordinary transport. Only
    the world is simulated (§115)."""
    conn = fi_db.get_connection(":memory:")
    try:
        fi_db.init_schema(conn)
        outcome = training.run_curriculum(
            conn, lambda c: portfolio_analyst._analyst_work(c, "analyst-1"),
            trained_agent="analyst-1")
        return summarise_curriculum(outcome["outcomes"], outcome["report"])
    finally:
        conn.close()


def summarise_curriculum(outcomes: list, report: dict) -> dict:
    """Turn a curriculum run into the verifier's view of it.

    **Separated from the run on purpose.** The rules below - a known gap that
    fails is not a failure, a regression is - cannot be tested against a live
    curriculum that currently contains neither. Mutation testing found exactly
    that: removing the known-gap exclusion changed nothing, because there is no
    known gap left to exclude (§129).

    A test over data does not test the rule that produced the data unless the
    data can exercise the rule. This project has now been bitten by that at §117,
    §118, §123 and here."""
    failures = [
        result["exercise_id"]
        for result in outcomes
        # A known gap is DECLARED to fail. Counting it would make the verdict red
        # for exactly the honesty that makes the curriculum worth reading.
        if not result["passed"]
        and result["expectation"] != curriculum_module.EXPECT_KNOWN_GAP
    ]
    return {
        "curriculum": report["curriculum"],
        "version": report["version"],
        "exercises": len(outcomes),
        "failures": failures,
        # A remediation failure is a defect: the failure it was written after has
        # recurred. It fails the verdict even though the exercise itself was
        # expected to pass and simply did not.
        "regressions": report["regressions"],
        # Not a failure. A known gap that passed means somebody built the
        # capability and the curriculum owes an update - but it must not be
        # silent, or the curriculum drifts out of date unnoticed (§117).
        "out_of_date": report["curriculum_out_of_date"],
        "passed": not failures and not report["regressions"],
        "note": report["note"],
    }
