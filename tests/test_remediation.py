"""Corrective work: one item per cause, routed by who could have complied.

Two measurements shaped this before anything was built.

**Ten findings were one design gap.** A real run had every analysis result graded
by its own producer - 10 of 10. Generating a task per finding would have produced
nine duplicates and one misdirected task.

**Whether an agent could have complied is measurable.** If every opportunity
failed, the compliant path was not available and no agent can be faulted. That
case is conclusive without a threshold, which matters because the alternative was
inventing a cutoff for "mostly".

The third finding came from trying to dispatch the work: **there is no general
task queue.** `coo_directives` carries lifecycle actions, and the Controller
objects to anything else on jurisdiction grounds - so the blocker is
demonstrable rather than asserted, by the mechanism G5 built.
"""

import pytest

from backend import compliance, fi_db, remediation
from backend.controller import Controller

RULE = "discovery report (analysed)"


@pytest.fixture
def controller(tmp_path):
    coord = Controller(db_path=str(tmp_path / "fi_test.db"))
    yield coord
    coord.close()


_ids = iter(range(3000, 4000))


def report(conn, graded: bool):
    """A completed, analysed report - graded or not."""
    report_id = next(_ids)
    conn.execute(
        "INSERT INTO discovery_reports_completed (id, created_at, producer_identity, "
        "producer_spawned_at, report_type, security, summary, completed_at, outcome, "
        "schema_version) VALUES (?, '2026-08-17T00:00:00+00:00', 'speculator-1', "
        "'2026-08-17T00:00:00+00:00', 'social', 'SYN1', 's', '2026-08-17T00:01:00+00:00', "
        "'analyzed', 1)",
        (report_id,),
    )
    if graded:
        conn.execute(
            "INSERT INTO analysis_results (id, created_at, producer_identity, producer_spawned_at, "
            "report_id, security, thesis, evidence_summary, confidence, schema_version) VALUES "
            "(?, '2026-08-17T00:00:30+00:00', 'analysis-1', '2026-08-17T00:00:00+00:00', ?, "
            "'SYN1', 't', 'e', 0.5, 1)",
            (report_id, report_id),
        )
        conn.execute(
            "INSERT INTO grades (created_at, grader_identity, grader_spawned_at, report_id, "
            "analysis_result_id, relevance_score, novelty_score, evidence_quality_score, "
            "worth_the_compute, overall_score, schema_version) VALUES "
            "('2026-08-17T00:01:00+00:00', 'coo-1', '2026-08-17T00:00:00+00:00', ?, ?, "
            "0.5, 0.5, 0.5, 1, 0.5, 1)",
            (report_id, report_id),
        )
        # Risk-assessed too, or "graded" would stop meaning "fully processed" -
        # the risk-assessed rule joined EVALUATION_RULES alongside grading, and
        # an ungraded-in-every-other-sense report must not also read as an
        # unassessed one, which would inflate these counts with a second,
        # unrelated cause.
        conn.execute(
            "INSERT INTO risk_assessments (analysis_result_id, security, overall, factors, "
            "assessed_by, created_at, schema_version) VALUES "
            "(?, 'SYN1', 'low', '{\"factors\": [], \"measured\": false}', 'coo-1', "
            "'2026-08-17T00:01:00+00:00', 1)",
            (report_id,),
        )
    return report_id


# -- the classification, which needs no invented threshold --------------------

def test_total_failure_is_systemic():
    """Conclusive without a cutoff: if nothing ever complied, complying was not
    among the options."""
    assert remediation.classify(findings=10, opportunities=10) == remediation.SYSTEMIC


def test_partial_failure_is_attributable():
    """Some completions did carry an evaluation, which proves it was available."""
    assert remediation.classify(findings=3, opportunities=10) == remediation.ATTRIBUTABLE


def test_a_single_case_is_undetermined():
    """One case cannot distinguish an agent that failed from a design that made
    compliance impossible. Stated rather than guessed."""
    assert remediation.classify(findings=1, opportunities=1) == remediation.UNDETERMINED
    assert remediation.classify(findings=0, opportunities=0) == remediation.UNDETERMINED


# -- one item per cause -------------------------------------------------------

def test_many_findings_of_one_cause_produce_one_item(conn):
    """The measurement that shaped this. Ten findings, one design gap - ten
    tasks would have been nine duplicates and one misdirected."""
    for _ in range(10):
        report(conn, graded=False)

    items = remediation.corrective_items(conn)

    assert len(items) == 1
    assert items[0].findings == 10
    assert items[0].opportunities == 10


def test_a_systemic_item_goes_to_the_owner_and_says_why(conn):
    for _ in range(6):
        report(conn, graded=False)

    item = remediation.corrective_items(conn)[0]

    assert item.classification == remediation.SYSTEMIC
    assert item.assigned_to == remediation.OWNER
    assert "could have chosen otherwise" in item.rationale
    assert "design" in item.statement


def test_an_attributable_item_names_the_producer_and_its_blocker(conn):
    """Compliance was available - most completions carried an evaluation - so
    this is work for the agent. And there is nowhere to send it."""
    for _ in range(9):
        report(conn, graded=True)
    report(conn, graded=False)

    item = remediation.corrective_items(conn)[0]

    assert item.classification == remediation.ATTRIBUTABLE
    assert item.assigned_to == "speculator-1"
    assert "no queue carries corrective work" in item.blocked


def test_a_clean_organization_raises_nothing(conn):
    """The control. Without it, every test above would pass on a function that
    always produced work."""
    for _ in range(5):
        report(conn, graded=True)

    assert remediation.corrective_items(conn) == []
    assert remediation.summarise(conn) == "no corrective work outstanding"


# -- dispositions feed in -----------------------------------------------------

def test_a_finding_ruled_a_false_positive_generates_no_work(conn):
    report_id = report(conn, graded=False)
    fi_db.record_disposition(
        conn, rule=RULE, item=report_id, disposition=fi_db.FALSE_POSITIVE,
        rationale="the grade was written against a superseded report id", decided_by="owner",
    )

    assert remediation.corrective_items(conn) == []


def test_an_accepted_finding_still_generates_work(conn):
    """Accepting a finding means it is real and correction is expected, so it
    belongs in the work rather than out of it. Only false_positive and wont_fix
    remove it."""
    report_id = report(conn, graded=False)
    fi_db.record_disposition(
        conn, rule=RULE, item=report_id, disposition=fi_db.ACCEPTED,
        rationale="real, and the corrective work is queued", decided_by="owner",
    )

    assert len(remediation.corrective_items(conn)) == 1


def test_wont_fix_removes_the_work(conn):
    report_id = report(conn, graded=False)
    fi_db.record_disposition(
        conn, rule=RULE, item=report_id, disposition=fi_db.WONT_FIX,
        rationale="the producing agent is retired and the work will not be redone",
        decided_by="owner",
    )

    assert remediation.corrective_items(conn) == []


# -- corrective work becomes an ordinary record -------------------------------

def test_corrective_items_are_raised_as_ordinary_records(conn):
    """Not a parallel enforcement track. knowledge_records already carries a
    statement, its evidence, who raised it, and closure with a trace."""
    for _ in range(4):
        report(conn, graded=False)

    raised = fi_db.raise_corrective_actions(conn, remediation.corrective_items(conn))

    assert len(raised) == 1
    action = fi_db.list_corrective_actions(conn)[0]
    assert action["record_kind"] == fi_db.KNOWLEDGE_CORRECTIVE
    assert action["subject"] == remediation.OWNER
    assert action["evidence_ref"] == f"{RULE}: 4 of 4"


def test_raising_the_same_work_twice_records_it_once(conn):
    """Load-bearing rather than tidy. The check recomputes the same findings from
    the same records every run, so without the guard one design gap would raise
    an identical item every cycle until the store was noise."""
    for _ in range(3):
        report(conn, graded=False)

    fi_db.raise_corrective_actions(conn, remediation.corrective_items(conn))
    second = fi_db.raise_corrective_actions(conn, remediation.corrective_items(conn))

    assert second == []
    assert len(fi_db.list_corrective_actions(conn)) == 1


def test_a_blocked_item_carries_its_blocker_into_the_record(conn):
    """Corrective work with nowhere to go looks exactly like corrective work
    nobody raised, and the difference is the point of raising it."""
    for _ in range(9):
        report(conn, graded=True)
    report(conn, graded=False)

    fi_db.raise_corrective_actions(conn, remediation.corrective_items(conn))

    assert "BLOCKED" in fi_db.list_corrective_actions(conn)[0]["rationale"]


def test_corrective_work_can_be_closed_with_a_trace(conn):
    """The existing resolution path, which is why this reuses the shape rather
    than inventing one: a question retired with no trace of what answered it is
    worse than one left open."""
    for _ in range(3):
        report(conn, graded=False)
    action_id = fi_db.raise_corrective_actions(conn, remediation.corrective_items(conn))[0]

    fi_db.resolve_knowledge(conn, action_id, resolved_by_ref="schema migration #7")

    assert fi_db.list_corrective_actions(conn) == []
    resolved = fi_db.list_corrective_actions(conn, status="resolved")[0]
    assert resolved["resolved_by_ref"] == "schema migration #7"


# -- the blocker is demonstrable, not asserted --------------------------------

def test_the_directive_queue_refuses_corrective_work(controller):
    """G5's mechanism proving G4's constraint.

    The claim that there is nowhere to send attributable corrective work is
    exactly the kind that rots into a stale comment. Here the system says it:
    enqueue corrective work and the Controller objects on jurisdiction grounds,
    because it executes spawn, retire and resume and nothing else."""
    fi_db.enqueue_directive(
        controller.conn, directive_type="corrective_action", requested_by="compliance",
        target_identity="speculator-1", reason="regrade report 42",
    )
    controller.process_next_directive()

    objection = fi_db.list_objections(controller.conn)[-1]
    assert objection["ground"] == "jurisdiction mismatch"
    assert "corrective_action" in objection["evidence"]


# -- the module writes nothing ------------------------------------------------

def test_remediation_cannot_change_anything():
    """Deciding what work is needed and creating it are separate acts with
    separate authority - the same split as checking and settling an objection."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(remediation))
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "execute" not in calls, "remediation.py writes; it must only read"
