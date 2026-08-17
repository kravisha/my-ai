"""Metric derivation and property evaluation.

These are pure functions over rows, which is the one part of the simulation
subsystem a unit test can check honestly: the arithmetic does not depend on the
fixture being realistic, only on it being well-formed.

What is checked hardest is the ability to FAIL. A property framework that cannot
report a failure is a suite that reports coverage it does not have, and this
project has already shipped one feature that was inert for exactly that reason.
"""

import pytest

from backend import fi_db
from simulation import metrics, properties


@pytest.fixture
def empty(conn):
    fi_db.init_schema(conn)
    return conn


def add_report(conn, report_id: int, created: str, completed: str | None = None):
    """One report, pending or completed, with only the columns the metrics read."""
    if completed is None:
        conn.execute(
            "INSERT INTO discovery_reports (id, created_at, producer_identity, producer_spawned_at, "
            "report_type, security, summary, status, schema_version) "
            "VALUES (?, ?, 'speculator-1', ?, 'social', 'SYN1', 's', 'pending', 1)",
            (report_id, created, created),
        )
    else:
        conn.execute(
            "INSERT INTO discovery_reports_completed (id, created_at, producer_identity, "
            "producer_spawned_at, report_type, security, summary, completed_at, outcome, schema_version) "
            "VALUES (?, ?, 'speculator-1', ?, 'social', 'SYN1', 's', ?, 'handled', 1)",
            (report_id, created, created, completed),
        )


def at(second: int) -> str:
    return f"2026-08-17T00:00:{second:02d}.000000+00:00"


# -- metrics on an empty database --------------------------------------------

def test_metrics_on_an_empty_database_do_not_crash(empty):
    """A run that produced nothing must still summarise.

    Every rate here divides by a count that can be zero, and a summariser that
    raised on an empty run would hide exactly the runs most worth looking at."""
    collected = metrics.collect_from(empty)
    assert set(collected) == set(metrics.FAMILIES)
    assert collected["queue"]["arrivals"] == 0
    assert collected["queue"]["drained"] is True
    assert collected["cross_check"]["unanswered_rate"] is None
    assert collected["pipeline"]["handling_latency_seconds"]["p50"] is None


# -- queue reconstruction ----------------------------------------------------

def test_queue_depth_is_reconstructed_from_timestamps(empty):
    """Depth at any instant is arrivals-so-far minus completions-so-far.

    Three arrive before the first completes, so the peak is 3 even though only
    one is pending at the end."""
    add_report(empty, 1, at(0), at(10))
    add_report(empty, 2, at(1), at(11))
    add_report(empty, 3, at(2), at(12))
    add_report(empty, 4, at(20))

    queue = metrics.collect_from(empty)["queue"]
    assert queue["arrivals"] == 4
    assert queue["completions"] == 3
    assert queue["max_depth"] == 3
    assert queue["final_depth"] == 1
    assert queue["drained"] is False


def test_a_fully_drained_queue_reports_drained(empty):
    add_report(empty, 1, at(0), at(5))
    add_report(empty, 2, at(1), at(6))
    queue = metrics.collect_from(empty)["queue"]
    assert queue["final_depth"] == 0
    assert queue["drained"] is True


def test_completion_sorts_before_arrival_at_the_same_instant(empty):
    """Otherwise a tie invents a depth of one that never existed."""
    add_report(empty, 1, at(0), at(5))
    add_report(empty, 2, at(5), at(9))
    assert metrics.collect_from(empty)["queue"]["max_depth"] == 1


def test_pressure_ratio_exceeds_one_when_arrival_outpaces_drain(empty):
    # Six reports arrive at 2s intervals; three are retired at 6s intervals.
    for index, (created, completed) in enumerate([(0, 20), (2, 26), (4, 32)], start=1):
        add_report(empty, index, at(created), at(completed))
    for index, created in enumerate([6, 8, 10], start=10):
        add_report(empty, index, at(created))

    queue = metrics.collect_from(empty)["queue"]
    assert queue["arrival_interval_seconds"] == 2.0
    assert queue["drain_interval_seconds"] == 6.0
    assert queue["pressure_ratio"] == 3.0, "drain three times slower than arrival must read 3.0"


def test_handling_latency_is_measured_from_creation_not_pickup(empty):
    """What matters organizationally is how long the work waited, not how long
    the agent held it."""
    add_report(empty, 1, at(0), at(30))
    latency = metrics.collect_from(empty)["pipeline"]["handling_latency_seconds"]
    assert latency["max"] == 30.0


# -- unjudged work -----------------------------------------------------------

def test_completed_reports_without_analyses_are_counted(empty):
    """Work consumed without being judged - invisible to any single-stage test."""
    add_report(empty, 1, at(0), at(5))
    add_report(empty, 2, at(1), at(6))
    assert metrics.collect_from(empty)["pipeline"]["unanalysed_completed_reports"] == 2


# -- metric lookup -----------------------------------------------------------

def test_lookup_resolves_a_dotted_path():
    assert metrics.lookup({"queue": {"final_depth": 7}}, "queue.final_depth") == 7


def test_lookup_raises_on_a_missing_path():
    """A typo must not read as absence, which would quietly assert nothing."""
    with pytest.raises(KeyError, match="no metric at"):
        metrics.lookup({"queue": {"final_depth": 7}}, "queue.finaldepth")


def test_lookup_error_names_what_was_available():
    with pytest.raises(KeyError, match="final_depth"):
        metrics.lookup({"queue": {"final_depth": 7}}, "queue.nope")


# -- property evaluation -----------------------------------------------------

METRICS = {
    "queue": {"final_depth": 10, "drained": False, "pressure_ratio": 3.15},
    "population": {"respawns": 0, "running_at_end": [], "crashed": ["analysis-1"]},
    "cross_check": {"unanswered_rate": None},
}


def check(**prop):
    return properties.evaluate({"name": "p", **prop}, METRICS)


@pytest.mark.parametrize("comparator,path,value,expected", [
    ("equals", "population.respawns", 0, True),
    ("equals", "population.respawns", 1, False),
    ("at_most", "queue.pressure_ratio", 5.0, True),
    ("at_most", "queue.pressure_ratio", 2.0, False),
    ("at_least", "queue.final_depth", 5, True),
    ("at_least", "queue.final_depth", 50, False),
    ("is_empty", "population.running_at_end", None, True),
    ("is_empty", "population.crashed", None, False),
    ("is_false", "queue.drained", None, True),
    ("is_true", "queue.drained", None, False),
])
def test_comparators(comparator, path, value, expected):
    result = check(metric=path, **{"assert": comparator}, value=value)
    assert result["passed"] is expected, result["detail"]


def test_unknown_comparator_fails_rather_than_passing():
    result = check(metric="queue.final_depth", **{"assert": "roughly"}, value=10)
    assert result["passed"] is False
    assert "unknown comparator" in result["detail"]


def test_comparator_needing_a_value_fails_without_one():
    result = check(metric="queue.final_depth", **{"assert": "at_most"})
    assert result["passed"] is False
    assert "needs a value" in result["detail"]


def test_misspelled_metric_path_fails_loudly():
    """The important one.

    A property naming a metric that does not exist must fail. Skipping it would
    leave a scenario reporting coverage for a claim it never checked."""
    result = check(metric="queue.pressur_ratio", **{"assert": "at_most"}, value=5.0)
    assert result["passed"] is False
    assert "no metric at" in result["detail"]


def test_incomparable_values_fail_without_killing_the_summary():
    """`unanswered_rate` is None when no cross-check ran at all. Comparing that
    with a number is a failed run, not an inconclusive one."""
    result = check(metric="cross_check.unanswered_rate", **{"assert": "at_most"}, value=0.0)
    assert result["passed"] is False
    assert "cannot compare" in result["detail"]


# -- property summary --------------------------------------------------------

def test_summary_counts_failures_by_name():
    results = [
        {"name": "a", "passed": True},
        {"name": "b", "passed": False},
        {"name": "c", "passed": False},
    ]
    summary = properties.summarise(results)
    assert summary == {"total": 3, "passed": 1, "failed": 2, "failures": ["b", "c"], "asserted": True}


def test_a_scenario_asserting_nothing_is_not_reported_as_passing():
    """`asserted` exists so an empty property set is never mistaken for success."""
    summary = properties.summarise([])
    assert summary["asserted"] is False
    assert summary["failed"] == 0


# -- the shipped scenario's properties ---------------------------------------

def test_baseline_properties_all_resolve_against_the_metric_shape(empty):
    """Every property in the library must name a metric that exists.

    Checked against a real (empty) collection rather than a hand-written dict, so
    renaming a metric key breaks this immediately instead of at the end of the
    next 90-second run."""
    from simulation import scenario as scenario_module

    collected = metrics.collect_from(empty)
    for scenario in scenario_module.load_all().values():
        for prop in scenario.expected_properties:
            result = properties.evaluate(prop, collected)
            assert "no metric at" not in result["detail"], (
                f"scenario {scenario.id!r} property {prop['name']!r}: {result['detail']}"
            )
