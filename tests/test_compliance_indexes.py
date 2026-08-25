"""The indexes the compliance check depends on (TQ-29, SPEC_RECONCILIATION §80).

`remediation.corrective_items` took **195.9 seconds to return two rows** on a
real 146MB database, and wedged the console that polled it. The cause was not
the logic: `compliance.unevaluated`'s generated SQL correlates a subquery per
row, and with no index on the linking columns SQLite ran
`SCAN cross_check_requests x SCAN discovery_reports_completed` — roughly 32
million row visits — then sorted every match in a temp B-tree.

A timing assertion would be flaky on shared hardware, so what is pinned here is
the *structural* cause: the indexes exist, and the query plan uses them. A plan
that regresses to SCAN is the defect coming back, and it fails here rather than
in production three months later.
"""

import pytest

from backend import compliance, fi_db, remediation

# Every (table, column) the check's generated SQL correlates, joins or orders
# on for the rule that was slow. Named from the rule definition rather than
# copied, so a rule that changes its linkage makes this list wrong loudly.
REQUIRED_INDEXES = {
    "discovery_reports_completed": "cross_check_id",
    "grades": "report_id",
    "discovery_reports": "cross_check_id",
    "cross_check_requests": "answered_at",
}

SLOW_QUERY = (
    "SELECT w.id FROM cross_check_requests w "
    "WHERE w.answered_at IS NOT NULL AND NOT EXISTS ("
    "  SELECT 1 FROM discovery_reports_completed c JOIN grades e ON e.report_id = c.id "
    "  WHERE c.cross_check_id = w.id) "
    "ORDER BY w.answered_at LIMIT 20"
)


def _indexed_columns(conn, table: str) -> set[str]:
    columns = set()
    for index in conn.fetchall(f"PRAGMA index_list({table})"):
        for entry in conn.fetchall(f"PRAGMA index_info({dict(index)['name']})"):
            columns.add(dict(entry)["name"])
    return columns


@pytest.mark.parametrize("table,column", sorted(REQUIRED_INDEXES.items()))
def test_the_linking_column_is_indexed(conn, table, column):
    assert column in _indexed_columns(conn, table), (
        f"{table}.{column} is not indexed; compliance.unevaluated correlates on it and "
        "without the index the check degrades to a full scan per row (§80)"
    )


def test_the_query_plan_uses_indexes_rather_than_scanning(conn):
    """The assertion that actually catches a regression: SQLite says what it
    will do, so ask it rather than timing it."""
    plan = " | ".join(dict(row)["detail"] for row in conn.fetchall("EXPLAIN QUERY PLAN " + SLOW_QUERY))

    assert "SCAN w" not in plan, f"outer table is being scanned again: {plan}"
    assert "SCAN c" not in plan, f"the correlated subquery is scanning again: {plan}"
    assert "TEMP B-TREE" not in plan.upper(), f"ORDER BY fell back to a sort: {plan}"
    assert plan.count("SEARCH") >= 3, f"expected index searches, got: {plan}"


def test_the_rule_that_was_slow_still_names_those_columns():
    """If the rule's linkage changes, the indexes above stop being the right
    ones - and this test is how that gets noticed rather than silently
    reintroducing the 196 seconds."""
    rule = next(r for r in compliance.EVALUATION_RULES if r.name == "cross-check answer")
    kind, carrier, link, target, key = rule.evaluation
    assert (carrier, link) == ("discovery_reports_completed", "cross_check_id")
    assert (target, key) == ("grades", "report_id")
    assert rule.completed_at == "answered_at"
    assert rule.in_flight == ("discovery_reports", "cross_check_id")


def test_corrective_items_runs_on_an_empty_database(conn):
    """The console polls this every few seconds; it must be cheap and it must
    not raise on a database with no findings at all."""
    assert remediation.corrective_items(conn, limit=200) == []
    assert isinstance(remediation.summarise(conn), str)
