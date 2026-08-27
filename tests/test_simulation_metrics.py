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
    assert queue["net_depth_change"] == 1
    assert queue["drained"] is False


def test_a_fully_drained_queue_reports_drained(empty):
    add_report(empty, 1, at(0), at(5))
    add_report(empty, 2, at(1), at(6))
    queue = metrics.collect_from(empty)["queue"]
    assert queue["net_depth_change"] == 0
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
    assert metrics.lookup({"queue": {"net_depth_change": 7}}, "queue.net_depth_change") == 7


def test_lookup_raises_on_a_missing_path():
    """A typo must not read as absence, which would quietly assert nothing."""
    with pytest.raises(KeyError, match="no metric at"):
        metrics.lookup({"queue": {"net_depth_change": 7}}, "queue.netdepth")


def test_lookup_error_names_what_was_available():
    with pytest.raises(KeyError, match="net_depth_change"):
        metrics.lookup({"queue": {"net_depth_change": 7}}, "queue.nope")


# -- property evaluation -----------------------------------------------------

METRICS = {
    "queue": {"net_depth_change": 10, "drained": False, "pressure_ratio": 3.15},
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
    ("at_least", "queue.net_depth_change", 5, True),
    ("at_least", "queue.net_depth_change", 50, False),
    ("is_empty", "population.running_at_end", None, True),
    ("is_empty", "population.crashed", None, False),
    ("is_false", "queue.drained", None, True),
    ("is_true", "queue.drained", None, False),
])
def test_comparators(comparator, path, value, expected):
    result = check(metric=path, **{"assert": comparator}, value=value)
    assert result["passed"] is expected, result["detail"]


def test_unknown_comparator_fails_rather_than_passing():
    result = check(metric="queue.net_depth_change", **{"assert": "roughly"}, value=10)
    assert result["passed"] is False
    assert "unknown comparator" in result["detail"]


def test_comparator_needing_a_value_fails_without_one():
    result = check(metric="queue.net_depth_change", **{"assert": "at_most"})
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


# -- day two: metrics against an inherited database ---------------------------

def test_a_run_boundary_excludes_inherited_rows(empty):
    """The defect chaining exposed.

    Without a boundary, a run that inherits another run's database reports that
    run's work as its own. Measured on a real chain: the third generation
    reported eight respawns having respawned nothing, because every generation's
    baseline spawn was still being counted."""
    add_report(empty, 1, at(0), at(5))       # inherited
    add_report(empty, 2, at(1), at(6))       # inherited
    add_report(empty, 3, at(30), at(35))     # this run

    unscoped = metrics.collect_from(empty)["pipeline"]
    scoped = metrics.collect_from(empty, since=at(20))["pipeline"]

    assert unscoped["reports_filed"] == 3
    assert scoped["reports_filed"] == 1


def test_work_retired_this_run_counts_even_if_it_arrived_earlier(empty):
    """Completions are scoped by when the work was retired, not filed.

    An inherited report finished during this run is work this run did, and
    counting it by creation would credit it to a run that never touched it."""
    add_report(empty, 1, at(0), at(30))      # arrived before, retired during

    scoped = metrics.collect_from(empty, since=at(20))
    assert scoped["pipeline"]["reports_completed"] == 1
    assert scoped["pipeline"]["reports_filed"] == 0


def test_inherited_backlog_is_reported_separately(empty):
    """A run that starts behind is a different situation from one that falls
    behind, and one depth number cannot tell them apart."""
    add_report(empty, 1, at(0))              # inherited, still pending
    add_report(empty, 2, at(1))              # inherited, still pending
    add_report(empty, 3, at(30))             # filed this run

    queue = metrics.collect_from(empty, since=at(20))["queue"]
    assert queue["inherited_backlog"] == 2
    assert queue["arrivals"] == 1
    assert queue["pending_at_end"] == 3


def test_drained_answers_from_what_is_pending_not_from_the_net_change(empty):
    """It read True over ten waiting reports before these were separated.

    A run that retires exactly as many as it files nets zero while leaving the
    inherited backlog untouched."""
    add_report(empty, 1, at(0))              # inherited, never touched
    add_report(empty, 2, at(30), at(35))     # filed and retired this run

    queue = metrics.collect_from(empty, since=at(20))["queue"]
    assert queue["net_depth_change"] == 0
    assert queue["drained"] is False, "a net change of zero is not an empty queue"
    assert queue["pending_at_end"] == 1


def test_intelligence_state_is_never_scoped(empty):
    """A lens that went stale in an earlier generation is still stale now.

    Scoping current state would report a healthy organization by forgetting."""
    empty.execute(
        "INSERT INTO intelligence_artifacts (created_at, artifact_kind, name, version, value, "
        "status, staleness_reason, schema_version) "
        "VALUES (?, 'detection_lens', 'old_lens', 1, '2.0', 'stale', 'failed earlier', 1)",
        (at(0),),
    )
    assert metrics.collect_from(empty, since=at(20))["intelligence"]["stale"] == 1


def test_lifetime_spawns_stays_cumulative_while_respawns_do_not(empty):
    for index, completed in enumerate([at(0), at(5), at(30)], start=1):
        empty.execute(
            "INSERT INTO coo_directives_completed (id, timestamp, directive_type, target_role, "
            "requested_by, completed_at, outcome, schema_version) "
            "VALUES (?, ?, 'spawn', 'analysis', 'coo', ?, 'success', 1)",
            (index, completed, completed),
        )

    scoped = metrics.collect_from(empty, since=at(20))["population"]
    assert scoped["lifetime_spawns"] == 3
    assert scoped["respawns"] == 0, "one baseline spawn this run is not a respawn"


def test_staffing_a_role_with_two_agents_is_not_counted_as_a_respawn(empty):
    """Counted per identity, not per role.

    A role staffed with two agents takes two spawns to establish. Counting
    spawns-beyond-the-first per role reported that as a respawn, and flagged it
    the first time judgment was staffed with two."""
    for index, identity in enumerate(["analysis-1", "analysis-2"], start=1):
        empty.execute(
            "INSERT INTO coo_directives_completed (id, timestamp, directive_type, target_role, "
            "requested_by, completed_at, outcome, detail, schema_version) "
            "VALUES (?, ?, 'spawn', 'analysis', 'coo', ?, 'success', ?, 1)",
            (index, at(index), at(index), identity),
        )
    assert metrics.collect_from(empty)["population"]["respawns"] == 0


def test_the_same_slot_filled_twice_is_a_respawn(empty):
    for index in (1, 2):
        empty.execute(
            "INSERT INTO coo_directives_completed (id, timestamp, directive_type, target_role, "
            "requested_by, completed_at, outcome, detail, schema_version) "
            "VALUES (?, ?, 'spawn', 'analysis', 'coo', ?, 'success', 'analysis-1', 1)",
            (index, at(index), at(index)),
        )
    assert metrics.collect_from(empty)["population"]["respawns"] == 1


# -- governance, and the queue measure that replaced pressure (§128) -----------

def test_retirement_ratio_rises_with_health_where_pressure_ratio_fell(empty):
    """The metric `queue.pressure_ratio` was asserted on until a survey showed it
    anti-correlated with health: the run that left 2 of 10 pending read 34.08,
    worse than the run that left 8 of 10 pending at 22.01 (§128).

    This is the replacement, checked in the direction that mattered — retiring
    more of what arrived must read higher, not lower."""
    def ten_reports_with(retired: int):
        # A separate database per case: deleting completed rows to build the
        # second one would remove the arrivals too, and the ratio would answer a
        # question about four reports instead of ten.
        connection = fi_db.get_connection(":memory:")
        fi_db.init_schema(connection)
        for report_id in range(1, 11):
            add_report(connection, report_id, at(report_id),
                       completed=at(20 + report_id) if report_id <= retired else None)
        return metrics.collect_from(connection)["queue"]["retirement_ratio"]

    healthy = ten_reports_with(8)
    struggling = ten_reports_with(2)

    assert healthy == 0.8 and struggling == 0.2
    assert healthy > struggling


def test_retirement_ratio_is_unknown_rather_than_zero_when_nothing_arrived(empty):
    """Nothing filed is not a failure to retire. Zero would read as one."""
    assert metrics.collect_from(empty)["queue"]["retirement_ratio"] is None


def test_work_filed_under_no_authority_is_counted(empty):
    """The number that separates governed-on-paper from governed-in-fact.

    A run can hold Articles, an instrument and a talkative Speaker while every
    report is filed by a caller that named no filer. Counting the work that
    carried no authority is the only way that shows up."""
    add_report(empty, 1, at(1))
    add_report(empty, 2, at(2))
    empty.execute("UPDATE discovery_reports SET governed_by = '7' WHERE id = 1")

    governance = metrics.collect_from(empty)["governance"]
    assert governance["work_governed"] == 1
    assert governance["work_ungoverned"] == 1


def test_governance_reports_an_ungoverned_organization_without_inventing_one(empty):
    """No Articles is a real state, and every field says so rather than
    defaulting to something that reads like governance."""
    governance = metrics.collect_from(empty)["governance"]
    assert governance["articles_version"] is None
    assert governance["instruments_in_force"] == 0
    assert governance["speaker_reports"] == 0
    assert governance["speaker_last_report_at"] is None
