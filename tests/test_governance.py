"""Metrics about the governance layer, not about the agents.

The test that matters most here is not that a number is computed - it is that
each number can actually go bad. A governance metric that reads healthy under
every condition is decoration, and decoration is worse than nothing because it
also supplies reassurance.

So every metric is exercised in both directions: healthy, and then broken on
purpose in the specific way it exists to detect.
"""

from datetime import datetime, timedelta, timezone

import pytest

from backend import compliance, fi_db, governance


def objection(conn, ground="missing dependency", identity="explorer-404", status=None, filed_at=None):
    directive_id = fi_db.enqueue_directive(
        conn, directive_type="retire", requested_by="coo-1", target_identity=identity,
    )
    objection_id = fi_db.file_objection(
        conn, directive_id, filed_by="controller-1", ground=ground,
        evidence="evidence", remedy="remedy",
    )
    if status:
        conn.execute("UPDATE objections SET status = ? WHERE id = ?", (status, objection_id))
    if filed_at:
        conn.execute("UPDATE objections SET filed_at = ? WHERE id = ?", (filed_at, objection_id))
    return objection_id


# -- path coverage: the check quietly stops covering things -------------------

def test_every_completion_path_is_currently_covered(conn):
    coverage = governance.path_coverage(conn)
    assert coverage["uncovered"] == []
    assert coverage["completion_paths"] > 0, "found no completion tables at all; the query is wrong"


def test_a_new_completion_path_with_no_rule_is_reported(conn):
    """The failure this exists for. Adding a kind of completed work is ordinary;
    remembering to add a rule for it is the step that gets missed - and the check
    keeps passing because it never looks."""
    conn.execute("CREATE TABLE forecasts_completed (id INTEGER PRIMARY KEY, completed_at TEXT)")

    coverage = governance.path_coverage(conn)

    assert "forecasts_completed" in coverage["uncovered"]
    assert any("forecasts_completed" in c for c in governance.concerns(conn))


def test_coverage_reads_the_live_database_not_the_declared_schema(conn):
    """Deliberate. The question is whether the check covers work this system
    actually completes, and a table in a running database is work being completed
    whether or not anything declared it."""
    conn.execute("CREATE TABLE adhoc_completed (id INTEGER PRIMARY KEY)")
    assert "adhoc_completed" in governance.path_coverage(conn)["uncovered"]


# -- escalation: the dead letter box ------------------------------------------

def test_no_escalation_backlog_when_nothing_is_waiting(conn):
    backlog = governance.escalation_backlog(conn)
    assert backlog == {"waiting": 0, "oldest_seconds": None, "grounds": {}}


def test_an_escalated_objection_shows_as_waiting_with_its_age(conn):
    """Escalation is the settlement design's release valve. If nothing drains it,
    the design has quietly become refusal with extra steps."""
    filed = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    objection(conn, ground="integrity or safety concern", status="escalated", filed_at=filed)

    backlog = governance.escalation_backlog(conn)

    assert backlog["waiting"] == 1
    assert backlog["oldest_seconds"] > 10_000
    assert backlog["grounds"] == {"integrity or safety concern": 1}


def test_the_escalation_concern_names_the_wait(conn):
    objection(conn, ground="integrity or safety concern", status="escalated")
    assert any("escalated and unresolved" in c for c in governance.concerns(conn))


def test_escalation_backlog_states_no_threshold(conn):
    """There is no honest number yet for how long is too long, and the
    measurement that would produce one - the owner's observed turnaround - has
    not happened. Reporting the age without judging it is the correct output."""
    objection(conn, status="escalated")
    assert "threshold" not in str(governance.escalation_backlog(conn))


# -- settlement mix: filing free, or filing punished --------------------------

def test_the_settlement_mix_is_not_stated_below_the_evidence_floor(conn):
    """'100% upheld' over two cases invites exactly the over-reading the floor
    exists to prevent. Absent is not zero applies to the governors too."""
    objection(conn, status="upheld")
    objection(conn, status="upheld")

    mix = governance.settlement_mix(conn)

    assert mix["upheld_rate"] is None
    assert governance.UNSTATED in mix["reason"]


def test_a_mix_of_all_upheld_is_flagged_once_there_is_enough_evidence(conn):
    """If every objection is upheld, filing one costs nothing and an executor
    could decline any work it disliked."""
    for _ in range(governance.MIN_SETTLEMENTS_TO_CHARACTERISE):
        objection(conn, status="upheld")

    assert governance.settlement_mix(conn)["upheld_rate"] == 1.0
    assert any("costs nothing" in c for c in governance.concerns(conn))


def test_a_mix_of_none_upheld_is_flagged_too(conn):
    """The opposite failure, and the worse one: agents that learn objecting never
    works will fail silently instead, and a silent failure carries no ground, no
    evidence and no remedy."""
    for _ in range(governance.MIN_SETTLEMENTS_TO_CHARACTERISE):
        objection(conn, status="rejected")

    assert governance.settlement_mix(conn)["upheld_rate"] == 0.0
    assert any("fail silently" in c for c in governance.concerns(conn))


def test_a_healthy_mix_raises_no_settlement_concern(conn):
    """The control. Without this, the two tests above would pass on a function
    that complained about every possible mix."""
    for _ in range(6):
        objection(conn, status="upheld")
    for _ in range(6):
        objection(conn, status="rejected")

    concerns = governance.concerns(conn)
    assert not any("costs nothing" in c or "fail silently" in c for c in concerns)


# -- attribution: blaming agents for the specification ------------------------

def test_structural_findings_are_counted_apart_from_agent_findings():
    """The first real compliance run produced three findings and none was an
    agent failing to do something it could have done. A governance layer that
    could not tell the difference would have punished three agents for the
    specification's mistakes."""
    attribution = governance.finding_attribution()

    assert attribution["structural"] == compliance.EXEMPT_COUNT + compliance.BLOCKED_COUNT
    assert attribution["attributable_to_agents"] < attribution["rules"]
    assert attribution["attributable_to_agents"] > 0


# -- checker coverage ---------------------------------------------------------

def test_unbuilt_checkers_are_reported_as_missing_machinery(conn):
    """Not as a caseload demanding a judge. Four of five verifiable grounds
    escalate for want of a checker, which from the outside looks exactly like
    needing an adjudicator - and the answer is to build the checkers."""
    coverage = governance.checker_coverage()

    assert coverage["without_checker"] == compliance.UNCHECKED_GROUND_COUNT
    assert coverage["with_checker"] + coverage["without_checker"] == coverage["verifiable_grounds"]
    assert any("want of machinery" in c for c in governance.concerns(conn))


# -- the shape of the thing ---------------------------------------------------

def test_there_is_no_single_governance_score(conn):
    """A single health number would be the first thing optimised and the last
    thing understood - the same reasoning that keeps competency per-dimension."""
    data = governance.report(conn)
    assert not any(key in data for key in ("score", "health", "grade", "rating"))


def test_the_governance_module_cannot_change_anything():
    """Same construction as the compliance module, for the same reason: something
    that measures the governors must not also be able to act on them."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(governance))
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "execute" not in calls, "governance.py writes; it must only read"


def test_summarise_runs_on_an_empty_organization(conn):
    """The state every governance layer starts in, and the one most likely to
    divide by zero."""
    assert "objections filed: 0" in governance.summarise(conn)
