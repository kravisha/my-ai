"""What Alpha means, and the test that keeps it from meaning nothing.

A certification suite composed by looking at what the system currently does will
certify whatever the system currently does. Everything passes on the first run,
the gate reads green forever, and nobody notices it is measuring nothing.

So the central test here is not that criteria pass. It is that **some of them
fail**, and that they fail for reasons naming real work. If this file ever goes
all-green without the underlying capabilities being built, the criteria were
rewritten to the answer.
"""

import pytest

from backend import fi_db
from simulation import certification, properties


PERFECT_RUN = {
    "population": {"respawns": 0, "running_at_end": [], "failed_directives": 0},
    "pipeline": {"unanalysed_completed_reports": 0, "ungraded_analyses": 0, "detector_events": 3},
    "queue": {"drained": True},
    "intelligence": {"regime_bound": ["iv_peak_ratio"]},
}


# -- the criteria must be able to fail ---------------------------------------

def test_alpha_is_not_currently_reached(conn):
    """The load-bearing test. Criteria written from what the system already does
    would all pass immediately and certify nothing."""
    report = certification.report(metrics=None, conn=conn)

    assert not report["entry_met"], "entry criteria all pass; they were written to the answer"
    assert not report["certified"]
    assert len(report["outstanding"]) >= 4


def test_the_unbuilt_capabilities_are_named(conn):
    """Entry failures should say what is missing rather than that something is.

    Updated when A4 landed: the continuously advancing world moved from unmet to
    met, which is the gate doing its job. This test failing on that change is the
    intended behaviour - a criterion silently flipping to green is exactly what
    the suite exists to make impossible."""
    entry = {r["criterion"]: r for r in certification.evaluate_entry()}

    assert entry["the world advances continuously"]["met"], (
        "simulation.world exists; this criterion should now pass"
    )
    assert not entry["history is queryable"]["met"]
    assert "simulation.history" in entry["history is queryable"]["detail"]


def test_the_capabilities_already_built_pass():
    """The other side. Without this, an entry gate that failed everything would
    look identical to one measuring correctly."""
    entry = {r["criterion"]: r for r in certification.evaluate_entry()}

    assert entry["simulated time exists"]["met"]
    assert entry["generators arrive behind a contract"]["met"]
    assert entry["runs are isolated and measured"]["met"]


# -- measured criteria -------------------------------------------------------

def test_a_run_that_meets_everything_certifies_on_the_measured_criteria(conn):
    """Proves the measured criteria can pass, so their failing today is a fact
    about the system rather than about the criteria."""
    results = {
        r["criterion"]: r for r in certification.evaluate_certification(PERFECT_RUN, conn)
    }
    measured = [c.name for c in certification.CERTIFICATION if c.kind == certification.MEASURED]

    assert all(results[name]["met"] for name in measured), (
        "a run meeting every measured criterion still failed one: "
        + str([name for name in measured if not results[name]["met"]])
    )


def test_the_known_bottleneck_is_a_criterion(conn):
    """The queue has never drained in any run. Certification says so rather than
    accommodating it - the scenario property holds a ceiling on known-bad
    behaviour, and this states the target."""
    backlogged = {**PERFECT_RUN, "queue": {"drained": False}}
    results = {r["criterion"]: r for r in certification.evaluate_certification(backlogged, conn)}

    assert not results["the queue drains"]["met"]


def test_a_speculator_only_run_does_not_certify(conn):
    """Every run so far has been Speculator-only: zero detector events, every
    report from one producer. Certifying on those would certify half an
    organization."""
    half = {**PERFECT_RUN, "pipeline": {**PERFECT_RUN["pipeline"], "detector_events": 0}}
    results = {r["criterion"]: r for r in certification.evaluate_certification(half, conn)}

    assert not results["both discovery paths produce work"]["met"]


def test_an_unrun_criterion_is_not_a_passed_one(conn):
    """The same rule `properties.summarise` applies to an empty property set: a
    criterion nobody measured has not been satisfied, it has been unasked."""
    results = certification.evaluate_certification(metrics=None, conn=conn)
    measured = [r for r in results if "could not be measured" in r["detail"]]

    assert measured and not any(r["met"] for r in measured)


# -- declared criteria -------------------------------------------------------

def test_the_pinned_gap_count_blocks_certification(conn):
    """Pinning gaps stops them growing quietly. It does not close them, and Alpha
    means closed."""
    results = {r["criterion"]: r for r in certification.evaluate_certification(PERFECT_RUN, conn)}
    result = results["the declared organization matches the built one"]

    assert not result["met"]
    assert "known_gap_count" in result["detail"]


def test_open_governance_concerns_block_certification(conn):
    """A governance layer with open concerns of its own cannot be relied on to
    report honestly about anything else."""
    results = {r["criterion"]: r for r in certification.evaluate_certification(PERFECT_RUN, conn)}
    assert not results["the governance layer reports no concerns"]["met"]


def test_governance_reads_a_database_that_predates_objections(conn):
    """Regression. Governance is read against run databases of every vintage, and
    two of its metrics assumed the objections table existed - so certifying any
    run recorded before that table crashed instead of reporting."""
    conn.execute("DROP TABLE objections")
    conn.execute("DROP TABLE finding_dispositions")

    results = certification.evaluate_certification(PERFECT_RUN, conn)

    assert any(r["criterion"] == "the governance layer reports no concerns" for r in results)


# -- the shape of the criteria -----------------------------------------------

def test_every_criterion_says_what_its_failure_would_mean():
    """A criterion whose failure has no consequence anyone can state is a
    criterion nobody will act on."""
    for criterion in certification.ENTRY + certification.CERTIFICATION:
        assert len(criterion.guards) > 50, f"{criterion.name!r} does not say what it guards against"
        assert criterion.requires


def test_certification_states_that_it_gates_nothing(conn):
    """There is no production operation to withhold. A gate described as binding
    when nothing is bound would be the first false clause in a system built to
    avoid them."""
    assert "nominal" in certification.report(metrics=None, conn=conn)["authority"]


def test_criteria_reuse_the_scenario_comparators():
    """Not a second comparison language. A certification criterion is exactly a
    scenario property that must hold across the organization."""
    for criterion in certification.CERTIFICATION:
        if criterion.kind == certification.MEASURED:
            assert criterion.prop["assert"] in properties.COMPARATORS


# -- the comparator this needed ----------------------------------------------

def test_is_not_empty_closes_the_asymmetry():
    """Without it a suite can assert that nothing happened but not that something
    did, which is backwards for properties whose main risk is certifying an idle
    system."""
    metrics = {"intelligence": {"regime_bound": ["iv_peak_ratio"]}, "pipeline": {"none": []}}

    assert properties.evaluate(
        {"name": "bound", "metric": "intelligence.regime_bound", "assert": "is_not_empty"}, metrics
    )["passed"]
    assert not properties.evaluate(
        {"name": "none", "metric": "pipeline.none", "assert": "is_not_empty"}, metrics
    )["passed"]


def test_is_not_empty_on_something_without_a_length_is_a_failure_not_an_error():
    result = properties.evaluate(
        {"name": "n", "metric": "a.b", "assert": "is_not_empty"}, {"a": {"b": 3}}
    )
    assert not result["passed"]
    assert "no length" in result["detail"]
