"""Whether completed work carries the evaluation the rules require.

The organization's own rule is that grading is part of task completion. This
checks it, and the check is deliberately a query over records that already
exist - an organization considering an enforcement division should first find out
whether it has anything to enforce.

Two failure shapes, and the second is the one worth building carefully for. A
missing evaluation is an absence and looks like one. A *self*-evaluation is
present, makes the record look complete, and carries no independent information
at all.
"""

import pytest

from backend import compliance, fi_db


@pytest.fixture
def db(conn):
    fi_db.init_schema(conn)
    return conn


def complete_report(conn, report_id, graded=True, producer="speculator-1"):
    conn.execute(
        "INSERT INTO discovery_reports_completed (id, created_at, producer_identity, "
        "producer_spawned_at, report_type, security, summary, completed_at, outcome, schema_version) "
        "VALUES (?, '2026-08-17T00:00:00+00:00', ?, '2026-08-17T00:00:00+00:00', 'social', 'SYN1', "
        "'s', '2026-08-17T00:01:00+00:00', 'analyzed', 1)",
        (report_id, producer),
    )
    if graded:
        # A grade needs an analysis result, because grades.analysis_result_id is
        # NOT NULL. That constraint is why the failed-analysis path cannot comply
        # with the grading rule even in principle - see
        # test_a_failed_analysis_cannot_be_graded_because_the_schema_forbids_it.
        conn.execute(
            "INSERT INTO analysis_results (id, created_at, producer_identity, producer_spawned_at, "
            "report_id, security, thesis, evidence_summary, confidence, schema_version) "
            "VALUES (?, '2026-08-17T00:00:30+00:00', 'analysis-1', '2026-08-17T00:00:00+00:00', "
            "?, 'SYN1', 't', 'e', 0.5, 1)",
            (report_id, report_id),
        )
        conn.execute(
            "INSERT INTO grades (created_at, grader_identity, grader_spawned_at, report_id, "
            "analysis_result_id, relevance_score, novelty_score, evidence_quality_score, "
            "worth_the_compute, overall_score, schema_version) "
            "VALUES ('2026-08-17T00:01:00+00:00', 'analysis-1', '2026-08-17T00:00:00+00:00', ?, ?, "
            "0.5, 0.5, 0.5, 1, 0.5, 1)",
            (report_id, report_id),
        )


def analysis_with_grader(conn, analysis_id, producer, grader):
    conn.execute(
        "INSERT INTO analysis_results (id, created_at, producer_identity, producer_spawned_at, "
        "report_id, security, thesis, evidence_summary, confidence, schema_version) "
        "VALUES (?, '2026-08-17T00:00:00+00:00', ?, '2026-08-17T00:00:00+00:00', 1, 'SYN1', "
        "'t', 'e', 0.5, 1)",
        (analysis_id, producer),
    )
    conn.execute(
        "INSERT INTO grades (created_at, grader_identity, grader_spawned_at, report_id, "
        "analysis_result_id, relevance_score, novelty_score, evidence_quality_score, "
        "worth_the_compute, overall_score, schema_version) "
        "VALUES ('2026-08-17T00:01:00+00:00', ?, '2026-08-17T00:00:00+00:00', 1, ?, "
        "0.5, 0.5, 0.5, 1, 0.5, 1)",
        (grader, analysis_id),
    )


# -- unevaluated work ---------------------------------------------------------

def test_a_graded_report_raises_no_finding(db):
    complete_report(db, 1, graded=True)
    assert compliance.check(db)["unevaluated"] == []


def test_an_ungraded_report_is_found(db):
    """The failed-analysis path: complete_report(..., 'failed', ...) writes no
    grade, so a report that broke analysis completes unevaluated - which is
    exactly the case whose grade would have carried why it broke."""
    complete_report(db, 1, graded=False)
    findings = compliance.check(db)["unevaluated"]

    assert len(findings) == 1
    assert findings[0]["rule"] == "discovery report"
    assert findings[0]["producer"] == "speculator-1"


def test_a_finding_says_what_was_expected_and_who_should_have_written_it(db):
    """A finding nobody can act on is an alarm, not a check."""
    complete_report(db, 1, graded=False)
    finding = compliance.check(db)["unevaluated"][0]

    assert "grades" in finding["expected"]
    assert finding["consumer"]
    assert finding["completed_at"]


def test_work_still_in_flight_is_not_a_finding(db):
    """Only completed work is subject to the rule."""
    db.execute(
        "INSERT INTO discovery_reports (id, created_at, producer_identity, producer_spawned_at, "
        "report_type, security, summary, status, schema_version) "
        "VALUES (1, '2026-08-17T00:00:00+00:00', 'speculator-1', '2026-08-17T00:00:00+00:00', "
        "'social', 'SYN1', 's', 'pending', 1)"
    )
    assert compliance.check(db)["unevaluated"] == []


def test_a_directive_with_an_observed_result_counts_as_evaluated(db):
    """Satisfies the rule under another name, and the check has to know that or
    it would report a compliant path as a violation."""
    db.execute(
        "INSERT INTO coo_directives_completed (id, timestamp, directive_type, target_role, "
        "requested_by, completed_at, outcome, observed_result, schema_version) "
        "VALUES (1, '2026-08-17T00:00:00+00:00', 'spawn', 'analysis', 'coo', "
        "'2026-08-17T00:01:00+00:00', 'success', 'agent registered and heartbeat', 1)"
    )
    assert not [f for f in compliance.check(db)["unevaluated"] if f["rule"] == "COO directive"]


def test_a_directive_with_no_observed_result_is_found(db):
    db.execute(
        "INSERT INTO coo_directives_completed (id, timestamp, directive_type, target_role, "
        "requested_by, completed_at, outcome, schema_version) "
        "VALUES (1, '2026-08-17T00:00:00+00:00', 'spawn', 'analysis', 'coo', "
        "'2026-08-17T00:01:00+00:00', 'success', 1)"
    )
    assert [f for f in compliance.check(db)["unevaluated"] if f["rule"] == "COO directive"]


# -- self-evaluation ----------------------------------------------------------

def test_work_graded_by_its_own_producer_is_found(db):
    """The subtle one. A grade exists and the record looks complete; what is
    missing is that the evaluation is independent."""
    analysis_with_grader(db, 1, producer="analysis-1", grader="analysis-1")
    findings = compliance.check(db)["self_evaluated"]

    assert len(findings) == 1
    assert findings[0]["producer"] == findings[0]["grader"] == "analysis-1"


def test_work_graded_by_someone_else_is_not_flagged(db):
    """Otherwise every grade would be a finding and the check would say nothing."""
    analysis_with_grader(db, 1, producer="analysis-1", grader="evaluator-1")
    assert compliance.check(db)["self_evaluated"] == []


# -- exemptions ---------------------------------------------------------------

def test_an_exempt_path_is_reported_rather_than_omitted(db):
    """Listing it keeps it visible. Dropping it would make the absence
    indistinguishable from an oversight."""
    report = compliance.check(db)
    assert len(report["exempt"]) == compliance.EXEMPT_COUNT
    assert all(entry["reason"] for entry in report["exempt"])


def test_the_exempt_count_is_pinned():
    """The ratchet, applied to the rules about rules.

    A fifth path quietly marked exempt is how a compliance check stops covering
    anything while still passing."""
    exempt = [rule for rule in compliance.EVALUATION_RULES if rule.exempt]
    assert len(exempt) == compliance.EXEMPT_COUNT
    for rule in exempt:
        assert len(rule.reason.split()) >= 8, f"{rule.name} is exempt without a stated reason"


# -- the check must not silently check nothing --------------------------------

def test_an_empty_database_reports_no_findings_but_says_it_looked(db):
    """"Nothing was found" and "nothing was checked" are different results, and a
    summary that conflated them would let an empty database read as a compliant
    organization."""
    report = compliance.check(db)

    assert report["total_findings"] == 0
    assert report["rules_applied"] >= 3


def test_every_rule_points_at_columns_that_exist(db):
    """A rule naming a column that does not exist would return nothing forever
    and look like compliance.

    This is the same drift the organization model guards: a check is only worth
    having if it is checking the thing it claims to."""
    for rule in compliance.EVALUATION_RULES:
        columns = {row["name"] for row in db.fetchall(f"PRAGMA table_info({rule.table})")}
        assert columns, f"{rule.name} names table {rule.table!r}, which does not exist"

        for column in (rule.key, rule.completed_at, rule.producer):
            assert column in columns, f"{rule.name} names {rule.table}.{column}, which does not exist"

        if rule.evaluation[0] == compliance.COLUMN:
            assert rule.evaluation[1] in columns, (
                f"{rule.name} expects evaluation in {rule.table}.{rule.evaluation[1]}, which does not exist"
            )
        else:
            _, table, column = rule.evaluation
            target = {row["name"] for row in db.fetchall(f"PRAGMA table_info({table})")}
            assert column in target, f"{rule.name} expects a row in {table}.{column}, which does not exist"


def test_a_missing_table_does_not_crash_the_check(db):
    """An older database may predate a table a rule names. The check must report
    what it can rather than failing entirely, or one stale database makes every
    other finding unavailable."""
    db.execute("DROP TABLE cross_check_requests")
    report = compliance.check(db)
    assert report["rules_applied"] >= 3


def test_the_summary_names_both_findings_and_compliance(db):
    complete_report(db, 1, graded=False)
    complete_report(db, 2, graded=True)
    text = compliance.summarise(compliance.check(db))

    assert "UNEVALUATED" in text
    assert "exempt:" in text


# -- why one path cannot comply ----------------------------------------------

def test_a_failed_analysis_cannot_be_graded_because_the_schema_forbids_it(db):
    """The first compliance finding turned out to be architectural, not
    behavioural.

    `grades.analysis_result_id` is NOT NULL, so a grade cannot exist without an
    analysis result - and a report that broke analysis produces none. The
    ungraded failed path is therefore enforced by the schema rather than caused
    by a forgotten call, which matters enormously for what to do about it: the
    governing framework's own question is whether a failure is an agent problem,
    a process problem or an architectural one, and enforcing against an agent
    here would be punishing it for a constraint it cannot satisfy."""
    import sqlite3

    complete_report(db, 1, graded=False)   # as the failed path leaves it

    with pytest.raises(sqlite3.IntegrityError, match="analysis_result_id"):
        db.execute(
            "INSERT INTO grades (created_at, grader_identity, grader_spawned_at, report_id, "
            "relevance_score, novelty_score, evidence_quality_score, worth_the_compute, "
            "overall_score, schema_version) "
            "VALUES ('2026-08-17T00:01:00+00:00', 'analysis-1', '2026-08-17T00:00:00+00:00', 1, "
            "0.5, 0.5, 0.5, 1, 0.5, 1)"
        )

    assert compliance.check(db)["unevaluated"], "the check should still report it"
