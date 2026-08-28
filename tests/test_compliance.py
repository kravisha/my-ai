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


def complete_report(conn, report_id, graded=True, producer="speculator-1", outcome="analyzed"):
    conn.execute(
        "INSERT INTO discovery_reports_completed (id, created_at, producer_identity, "
        "producer_spawned_at, report_type, security, summary, completed_at, outcome, schema_version) "
        "VALUES (?, '2026-08-17T00:00:00+00:00', ?, '2026-08-17T00:00:00+00:00', 'social', 'SYN1', "
        "'s', '2026-08-17T00:01:00+00:00', ?, 1)",
        (report_id, producer, outcome),
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
        # Risk-assessed too, or "a graded report raises no finding" would stop
        # being true the moment the risk-assessed rule joined EVALUATION_RULES -
        # graded here means fully processed, and COO's cycle now includes
        # assessing risk as part of that.
        conn.execute(
            "INSERT INTO risk_assessments (analysis_result_id, security, overall, factors, "
            "assessed_by, created_at, schema_version) "
            "VALUES (?, 'SYN1', 'low', '{\"factors\": [], \"measured\": false}', 'coo-1', "
            "'2026-08-17T00:01:00+00:00', 1)",
            (report_id,),
        )


def report_with_grader(conn, report_id, filer, grader):
    """A report and the grade written about it.

    **The grade is of the upstream report** (`agents/analysis.py`: *"a grade of
    the upstream report"*), so the party whose work was judged is whoever filed
    it. This fixture used to vary the *analysis result's* producer, which is the
    agent that writes the grade - so the two were equal by construction and the
    check under test could never come back empty (§147)."""
    conn.execute(
        "INSERT INTO discovery_reports (id, created_at, producer_identity, "
        "producer_spawned_at, report_type, security, status, schema_version) "
        "VALUES (?, '2026-08-17T00:00:00+00:00', ?, '2026-08-17T00:00:00+00:00', "
        "'lead', 'SYN1', 'pending', 1)",
        (report_id, filer),
    )
    conn.execute(
        "INSERT INTO analysis_results (id, created_at, producer_identity, producer_spawned_at, "
        "report_id, security, thesis, evidence_summary, confidence, schema_version) "
        "VALUES (?, '2026-08-17T00:00:00+00:00', 'analysis-1', '2026-08-17T00:00:00+00:00', ?, "
        "'SYN1', 't', 'e', 0.5, 1)",
        (report_id, report_id),
    )
    conn.execute(
        "INSERT INTO grades (created_at, grader_identity, grader_spawned_at, report_id, "
        "analysis_result_id, relevance_score, novelty_score, evidence_quality_score, "
        "worth_the_compute, overall_score, rationale, schema_version) "
        "VALUES ('2026-08-17T00:01:00+00:00', ?, '2026-08-17T00:00:00+00:00', ?, ?, "
        "0.5, 0.5, 0.5, 1, 0.5, 'because', 1)",
        (grader, report_id, report_id),
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
    assert findings[0]["rule"] == "discovery report (analysed)"
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
    report_with_grader(db, 1, filer="explorer-1", grader="explorer-1")
    findings = compliance.check(db)["self_evaluated"]

    assert len(findings) == 1
    assert findings[0]["producer"] == findings[0]["grader"] == "explorer-1"


def test_work_graded_by_someone_else_is_not_flagged(db):
    """Otherwise every grade would be a finding and the check would say nothing.

    **This is what the check could not do until §147.** It compared the grader to
    the *analysis result's* producer, and `agents/analysis.py` writes both under
    one identity - so the comparison was true by construction, every grade came
    back as a violation, and a genuinely independent pipeline was reported as a
    total failure of the duty. A tripwire that always fires carries exactly as
    much information as one that never does."""
    report_with_grader(db, 1, filer="explorer-1", grader="analysis-1")
    assert compliance.check(db)["self_evaluated"] == []


def test_the_real_pipeline_does_not_trip_the_check(db):
    """Written against the shape the organization actually produces: Explorer
    files, Analysis grades. The version of this check that shipped for months
    would have failed here, which is why the case is pinned rather than left to
    the two tests above."""
    for report_id, filer in ((1, "explorer-1"), (2, "speculator-1"), (3, "explorer-1")):
        report_with_grader(db, report_id, filer=filer, grader="analysis-1")
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

        kind = rule.evaluation[0]
        if kind == compliance.COLUMN:
            assert rule.evaluation[1] in columns, (
                f"{rule.name} expects evaluation in {rule.table}.{rule.evaluation[1]}, which does not exist"
            )
        elif kind == compliance.VIA:
            _, carrier, link, target, key = rule.evaluation
            carrier_cols = {row["name"] for row in db.fetchall(f"PRAGMA table_info({carrier})")}
            target_cols = {row["name"] for row in db.fetchall(f"PRAGMA table_info({target})")}
            assert link in carrier_cols, f"{rule.name} follows {carrier}.{link}, which does not exist"
            assert key in target_cols, f"{rule.name} expects {target}.{key}, which does not exist"
        else:
            _, table, column = rule.evaluation
            target_cols = {row["name"] for row in db.fetchall(f"PRAGMA table_info({table})")}
            assert column in target_cols, f"{rule.name} expects a row in {table}.{column}, which does not exist"


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

    assert "VIOLATION" in text
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

    complete_report(db, 1, graded=False, outcome="failed")   # as the failed path leaves it

    with pytest.raises(sqlite3.IntegrityError, match="analysis_result_id"):
        db.execute(
            "INSERT INTO grades (created_at, grader_identity, grader_spawned_at, report_id, "
            "relevance_score, novelty_score, evidence_quality_score, worth_the_compute, "
            "overall_score, schema_version) "
            "VALUES ('2026-08-17T00:01:00+00:00', 'analysis-1', '2026-08-17T00:00:00+00:00', 1, "
            "0.5, 0.5, 0.5, 1, 0.5, 1)"
        )

    report = compliance.check(db)
    assert report["unevaluated"] == [], "not a violation - nobody could have graded it"
    assert len(report["blocked"]) == 1, "it should still be reported, as blocked"
    assert "NOT NULL" in report["blocked"][0]["note"]


# -- classification: violation, in flight, or blocked -------------------------

def carry_cross_check(conn, cross_check_id, report_id, report_completed, graded):
    """A cross-check answered, then carried by a report that may or may not have
    completed - which is the difference between judged, awaiting judgment, and
    neglected."""
    conn.execute(
        "INSERT INTO cross_check_requests (id, created_at, requester_identity, requester_spawned_at, "
        "requester_role, responder_role, security, question, requester_finding, status, outcome, responder_identity, "
        "answered_at, schema_version) "
        "VALUES (?, '2026-08-17T00:00:00+00:00', 'explorer-1', '2026-08-17T00:00:00+00:00', "
        "'explorer', 'speculator', 'SYN1', 'q', 'f', 'consumed', 'evidence', 'speculator-1', "
        "'2026-08-17T00:00:30+00:00', 1)",
        (cross_check_id,),
    )
    table = "discovery_reports_completed" if report_completed else "discovery_reports"
    if report_completed:
        conn.execute(
            f"INSERT INTO {table} (id, created_at, producer_identity, producer_spawned_at, "
            "report_type, security, summary, completed_at, outcome, cross_check_id, schema_version) "
            "VALUES (?, '2026-08-17T00:00:00+00:00', 'explorer-1', '2026-08-17T00:00:00+00:00', "
            "'iv', 'SYN1', 's', '2026-08-17T00:01:00+00:00', 'analyzed', ?, 1)",
            (report_id, cross_check_id),
        )
    else:
        conn.execute(
            f"INSERT INTO {table} (id, created_at, producer_identity, producer_spawned_at, "
            "report_type, security, summary, status, cross_check_id, schema_version) "
            "VALUES (?, '2026-08-17T00:00:00+00:00', 'explorer-1', '2026-08-17T00:00:00+00:00', "
            "'iv', 'SYN1', 's', 'pending', ?, 1)",
            (report_id, cross_check_id),
        )
    if graded:
        conn.execute(
            "INSERT INTO analysis_results (id, created_at, producer_identity, producer_spawned_at, "
            "report_id, security, thesis, evidence_summary, confidence, schema_version) "
            "VALUES (?, '2026-08-17T00:00:40+00:00', 'analysis-1', '2026-08-17T00:00:00+00:00', "
            "?, 'SYN1', 't', 'e', 0.5, 1)",
            (900 + report_id, report_id),
        )
        conn.execute(
            "INSERT INTO grades (created_at, grader_identity, grader_spawned_at, report_id, "
            "analysis_result_id, relevance_score, novelty_score, evidence_quality_score, "
            "worth_the_compute, overall_score, schema_version) "
            "VALUES ('2026-08-17T00:01:00+00:00', 'analysis-1', '2026-08-17T00:00:00+00:00', ?, ?, "
            "0.5, 0.5, 0.5, 1, 0.5, 1)",
            (report_id, 900 + report_id),
        )


def test_a_cross_check_judged_through_its_carrying_report_is_compliant(db):
    """The false positive that G2 existed to check.

    A cross-check answer is never graded in its own right - it is carried into a
    report and evaluated as part of it. The first rule looked for a grade keyed
    directly to the cross-check, which nothing ever writes, so it reported twenty
    answers as neglected when every one had been carried."""
    carry_cross_check(db, cross_check_id=1, report_id=1, report_completed=True, graded=True)
    report = compliance.check(db)

    assert [f for f in report["unevaluated"] if f["rule"] == "cross-check answer"] == []


def test_a_cross_check_awaiting_its_report_is_in_flight_not_a_violation(db):
    """Reporting work still being judged as neglect would make an organization
    keeping up look exactly like one falling behind."""
    carry_cross_check(db, cross_check_id=1, report_id=1, report_completed=False, graded=False)
    report = compliance.check(db)

    assert report["unevaluated"] == []
    assert len(report["in_flight"]) == 1
    assert "has not completed" in report["in_flight"][0]["note"]


def test_a_cross_check_carried_by_nothing_is_a_real_violation(db):
    """The other side. If the carrier route were treated as always-compliant,
    the rule would excuse everything and check nothing."""
    db.execute(
        "INSERT INTO cross_check_requests (id, created_at, requester_identity, requester_spawned_at, "
        "requester_role, responder_role, security, question, requester_finding, status, outcome, responder_identity, "
        "answered_at, schema_version) "
        "VALUES (1, '2026-08-17T00:00:00+00:00', 'explorer-1', '2026-08-17T00:00:00+00:00', "
        "'explorer', 'speculator', 'SYN1', 'q', 'f', 'consumed', 'evidence', 'speculator-1', "
        "'2026-08-17T00:00:30+00:00', 1)"
    )
    violations = [f for f in compliance.check(db)["unevaluated"] if f["rule"] == "cross-check answer"]
    assert len(violations) == 1


def test_blocked_work_is_not_counted_as_a_violation(db):
    """A schema constraint and somebody's neglect have nothing in common as
    remedies, so counting them together would make the total meaningless."""
    complete_report(db, 1, graded=False, outcome="failed")
    report = compliance.check(db)

    assert report["total_findings"] == 0
    assert len(report["blocked"]) == 1


def test_the_blocked_count_is_pinned():
    """Same ratchet as exemption. A path quietly marked blocked stops being
    checked while the suite stays green."""
    blocked = [rule for rule in compliance.EVALUATION_RULES if rule.blocked]
    assert len(blocked) == compliance.BLOCKED_COUNT
    for rule in blocked:
        assert "Remedy" in rule.blocked or "remedy" in rule.blocked, (
            f"{rule.name} is blocked without naming who can unblock it"
        )


# -- separation of powers, at the only scale that currently exists ------------

def test_the_detection_layer_cannot_change_anything():
    """Investigation cannot punish, because investigation cannot write.

    The governing framework asks for investigation, prosecution, adjudication and
    retirement authority to be separated. With six roles and no adjudicator, the
    one separation that can be made real today is this one - and it is made real
    by construction rather than by policy, since a module containing no write
    statement cannot sanction anyone whatever it concludes.

    Parsed rather than trusted, because the natural next change to a compliance
    module is to have it record what it found, and that is the change that would
    quietly merge the investigator with the enforcer."""
    import ast
    import inspect

    from backend import compliance as module

    source = inspect.getsource(module)
    for statement in ("INSERT ", "UPDATE ", "DELETE "):
        assert statement not in source.upper().replace("INSERT/UPDATE/DELETE", ""), (
            f"the compliance module contains {statement.strip()}. Detection must not be able to "
            "change what it inspects; recording a finding belongs to a separate step with its own "
            "authority."
        )

    tree = ast.parse(source)
    writers = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "execute" not in writers, "the compliance module calls execute(); it should only read"


def test_no_role_charter_grants_adjudication():
    """There is no adjudicator, and appointing one silently is how a court gets
    built before there is a dispute.

    The Controller executes and does not decide. Explorer and Speculator are
    barred from judging by the axiom separating observation from judgment.
    Analysis is the only role that reasons and is itself the subject of the one
    live finding. COO already manages the workforce and acts for the vacant CEO;
    adding adjudication would concentrate manager, investigator, reputation
    assessor and retirement authority in one agent."""
    for role, charter in fi_db.ROLE_CHARTERS.items():
        granted = " ".join(charter["allowed"]).lower()
        for word in ("adjudicat", "sanction", "punish", "convict"):
            assert word not in granted, f"{role}'s charter grants {word!r}"


def test_most_objection_grounds_need_a_checker_rather_than_a_judge():
    """Why the absence of an adjudicator does not block the objection mechanism.

    Whether work falls outside a role's charter, whether a dependency exists,
    whether a resource is reachable, whether two instructions contradict, whether
    an agent is measurably overloaded - all decidable from records. Only a
    subjective safety concern needs weighing."""
    verifiable = compliance.objection_grounds(compliance.VERIFIABLE)
    judged = compliance.objection_grounds(compliance.JUDGED)

    assert len(verifiable) >= 4
    assert len(judged) == compliance.JUDGED_GROUND_COUNT
    assert all(ground.evidence for ground in compliance.OBJECTION_GROUNDS)


def test_the_judged_ground_count_is_pinned():
    """The cheapest way to acquire a judiciary is to keep reclassifying checkable
    things as matters of opinion."""
    judged = [g for g in compliance.OBJECTION_GROUNDS if g.kind == compliance.JUDGED]
    assert len(judged) == compliance.JUDGED_GROUND_COUNT
    assert "owner" in judged[0].decided_by


def test_the_grounds_list_is_closed(db):
    """An open "other" category would make refusal discretionary, which is the
    thing a structured objection exists to replace."""
    names = {ground.name for ground in compliance.OBJECTION_GROUNDS}
    assert not any(name in ("other", "misc", "general") for name in names)


def test_every_objection_ground_proposes_a_way_forward():
    """A blocked agent owes a proposal, not just a report of being blocked.

    The manifesto's fifth principle: when progress stops because something does
    not exist, the answer is what would have to be built and at what cost - not
    that it is absent. An objection mechanism that only recorded refusals would
    institutionalise the opposite, since "I cannot" would become a complete and
    accepted answer."""
    for ground in compliance.OBJECTION_GROUNDS:
        assert ground.remedy, f"{ground.name} says no without saying what would let it proceed"
        assert len(ground.remedy) > 40, f"{ground.name}'s remedy is too thin to act on"


def test_the_safety_ground_may_answer_that_nothing_would_help():
    """The bound on the principle above. Constructive initiative is a default,
    not an obligation to find a way to do everything - and the one ground that
    turns on judgment is exactly where "no remedy exists" must stay sayable."""
    judged = compliance.objection_grounds(compliance.JUDGED)[0]
    assert "nothing would" in judged.remedy
