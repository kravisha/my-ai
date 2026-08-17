"""Machinery deliberately not built, and the triggers that would change that.

Adjudication, precedent, appeal, rehabilitation and a sanctions ladder are all
absent, and the reason is the same in every case: the conditions justifying them
have never occurred. Building a court before there is a dispute is the failure
this whole series avoided.

**A deferral nobody can detect becoming due is an omission with better wording.**
So the point of these tests is not that the deferrals are listed - it is that the
existence triggers actually fire when their condition arrives. A trigger that
cannot fire is the same as no trigger, and it is the more comfortable of the two
because it never interrupts anyone.
"""

import pytest

from backend import compliance, fi_db, governance

RULE = "discovery report (analysed)"
_ids = iter(range(5000, 6000))


def report(conn, graded: bool):
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
    return report_id


def objection(conn, ground):
    directive_id = fi_db.enqueue_directive(
        conn, directive_type="retire", requested_by="coo-1", target_identity="explorer-404",
    )
    return fi_db.file_objection(
        conn, directive_id, filed_by="controller-1", ground=ground,
        evidence="evidence for the objection", remedy="a remedy for the objection",
    )


# -- the shape of the deferral list -------------------------------------------

def test_every_deferral_is_counted():
    """Deferral is the cheapest decision available and the easiest to make
    permanently."""
    assert len(governance.DEFERRED) == governance.DEFERRED_COUNT


def test_every_deferral_states_a_trigger():
    for capability in governance.DEFERRED:
        assert capability.trigger, f"{capability.name!r} is deferred with no trigger"
        assert len(capability.trigger) > 30, f"{capability.name!r} names no concrete trigger"


def test_a_trigger_that_cannot_be_evaluated_says_what_is_missing():
    """The alternative was giving an unformulable trigger a plausible number, and
    every invented threshold in this project has been wrong."""
    for capability in governance.DEFERRED:
        if capability.kind == governance.EXISTENCE:
            assert not capability.needs
        else:
            assert capability.needs, f"{capability.name!r} cannot fire and does not say why"


def test_only_one_trigger_is_unformulable():
    """Pinned, because reclassifying a checkable condition as unformulable is the
    cheapest way to defer something forever."""
    unformulable = [d for d in governance.DEFERRED if d.kind == governance.UNFORMULABLE]
    assert len(unformulable) == governance.UNFORMULABLE_COUNT
    assert unformulable[0].name == "an adjudicator"


def test_every_existence_trigger_has_a_check():
    """A listed trigger with no evaluator would never fire, which is the more
    comfortable failure because it never interrupts anyone."""
    for capability in governance.DEFERRED:
        if capability.kind == governance.EXISTENCE:
            assert capability.name in governance._DUE_CHECKS, (
                f"{capability.name!r} claims an existence trigger and nothing evaluates it"
            )


# -- nothing is due on a clean system -----------------------------------------

def test_nothing_is_due_on_an_untroubled_organization(conn):
    """The control. Without it, every test below would pass on a function that
    always reported everything as due."""
    for _ in range(5):
        report(conn, graded=True)

    assert governance.due(conn) == []
    assert not any("come due" in c for c in governance.concerns(conn))


# -- each existence trigger, fired on purpose ---------------------------------

def test_the_task_queue_becomes_due_when_work_is_attributable(conn):
    """The trigger that matters most. Every finding so far has been systemic, so
    no corrective work has ever needed a queue - and the moment one does, the
    absence stops being a reasoned deferral and becomes a blockage."""
    for _ in range(9):
        report(conn, graded=True)
    report(conn, graded=False)

    fired = {item["capability"] for item in governance.due(conn)}

    assert "general task queue" in fired
    assert any("nowhere to be sent" in c for c in governance.concerns(conn))


def test_a_systemic_finding_does_not_make_the_task_queue_due(conn):
    """The discrimination that makes the trigger worth having. Ten findings that
    are one design gap need no queue - they need a design change."""
    for _ in range(10):
        report(conn, graded=False)

    assert "general task queue" not in {i["capability"] for i in governance.due(conn)}


def test_checkers_become_due_when_objections_arrive_on_unchecked_grounds(conn):
    """The distinction G6 exists to preserve: escalation for want of machinery is
    not a caseload demanding a judge."""
    objection(conn, "workload harm")

    fired = {item["capability"]: item for item in governance.due(conn)}

    assert "checkers for the remaining verifiable grounds" in fired
    assert "workload harm" in fired["checkers for the remaining verifiable grounds"]["evidence"]


def test_an_objection_on_a_checked_ground_does_not_make_checkers_due(conn):
    objection(conn, "missing dependency")
    assert "checkers for the remaining verifiable grounds" not in {
        i["capability"] for i in governance.due(conn)
    }


def test_precedent_becomes_due_when_like_cases_are_treated_unlike(conn):
    """The first moment consistency becomes a question anyone could answer
    wrongly: the same rule, two different dispositions, and nothing recording
    why."""
    first, second = report(conn, graded=False), report(conn, graded=False)
    fi_db.record_disposition(
        conn, rule=RULE, item=first, disposition=fi_db.FALSE_POSITIVE,
        rationale="the grade was written against a superseded report id", decided_by="owner",
    )
    fi_db.record_disposition(
        conn, rule=RULE, item=second, disposition=fi_db.WONT_FIX,
        rationale="the producing agent is retired and this will not be redone", decided_by="owner",
    )

    fired = {item["capability"] for item in governance.due(conn)}

    assert "precedent" in fired
    assert any("treated unlike" in c for c in governance.concerns(conn))


def test_consistent_dispositions_do_not_make_precedent_due(conn):
    first, second = report(conn, graded=False), report(conn, graded=False)
    for item in (first, second):
        fi_db.record_disposition(
            conn, rule=RULE, item=item, disposition=fi_db.FALSE_POSITIVE,
            rationale="both were graded against a superseded report id", decided_by="owner",
        )

    assert "precedent" not in {i["capability"] for i in governance.due(conn)}


# -- prerequisite triggers are not watched ------------------------------------

def test_prerequisite_triggers_are_never_reported_as_due(conn):
    """Watching for a phenomenon the system cannot produce is the mistake this
    project has made before - a detector for something that cannot happen passes
    every test and works never.

    Rehabilitation cannot become due while nothing reduces an agent's standing,
    and appeal cannot while there is nobody to appeal to."""
    for _ in range(9):
        report(conn, graded=True)
    report(conn, graded=False)
    objection(conn, "workload harm")

    fired = {item["capability"] for item in governance.due(conn)}
    prerequisites = {d.name for d in governance.DEFERRED if d.kind != governance.EXISTENCE}

    assert not (fired & prerequisites)


def test_the_adjudicator_trigger_names_what_would_formulate_it():
    """The one that could most easily have been given a plausible number. It
    needs the owner's observed turnaround on escalated objections, and no
    objection has yet escalated."""
    adjudicator = next(d for d in governance.DEFERRED if d.name == "an adjudicator")

    assert adjudicator.kind == governance.UNFORMULABLE
    assert "turnaround" in adjudicator.needs
    assert "invented" in adjudicator.needs


def test_a_due_deferral_reaches_the_governance_summary(conn):
    """A trigger that fires into a function nobody calls is the same as no
    trigger."""
    objection(conn, "contradictory instructions")
    assert "come due" in governance.summarise(conn)
