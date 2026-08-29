"""The Software Engineering Department, first increment (TQ-83;
addendum 46 §7-§13; docs/SPEC_RECONCILIATION.md §119, §137).

Addendum 46's terminal claim is *Jarvis develops Jarvis*. Most of what is tested
here is the honesty about how little of that is true yet: the department turns a
directive into governed data or **names the capability the architecture lacks**,
and it never approves its own work.
"""

from __future__ import annotations

import inspect
import json

from datetime import datetime, timedelta, timezone

import pytest

from agents import software_engineer
from backend import (engineering, fi_db, governed_knowledge as governed,
                     operating_context, parliament, portfolios)

OWNER = portfolios.for_superuser("krish")
ROLL = {"broad": ["coo", "analysis"], "representative": ["coo", "analysis"]}


@pytest.fixture
def governed_conn(conn):
    parliament.adopt_genesis_articles(
        conn, owner=OWNER, text="The Articles.", roll=ROLL,
        quorum="1/2", ordinary_threshold="1/2")
    return conn


def _enact(conn, title="A resolution", affects="organization_policy") -> int:
    resolution = parliament.propose(conn, title=title, rationale="r",
                                    proposed_by="coo", affects=affects)
    for voter in ROLL["representative"]:
        parliament.cast_vote(conn, resolution, voter=voter, value="for")
    parliament.close(conn, resolution)
    return resolution


def _directive(conn, *, requirement=None, subject="discovery_reports", title="A directive",
               binds="*"):
    return engineering.receive(
        conn, title=title, intended_outcome="Every discovery report names its source.",
        resolution_id=_enact(conn, title=f"r:{title}"),
        requirement=requirement or {"kind": "required_fields", "fields": ["summary"]},
        subject=subject, binds=binds)


# --- authority requires provenance ----------------------------------------------------

def test_a_directive_needs_the_resolution_that_authorised_it(governed_conn):
    """An engineering directive with no authority is somebody's idea. A
    department that acted on ideas would be §119's bypass arriving through the
    intake rather than through the design."""
    with pytest.raises(engineering.EngineeringRefused) as refusal:
        engineering.receive(governed_conn, title="x", intended_outcome="y",
                            resolution_id=999,
                            requirement={"kind": "required_fields", "fields": ["a"]},
                            subject="s")
    assert "enacted resolution" in str(refusal.value)


def test_an_open_resolution_authorises_nothing(governed_conn):
    resolution = parliament.propose(governed_conn, title="x", rationale="r",
                                    proposed_by="coo", affects="organization_policy")
    with pytest.raises(engineering.EngineeringRefused):
        engineering.receive(governed_conn, title="x", intended_outcome="y",
                            resolution_id=resolution,
                            requirement={"kind": "required_fields", "fields": ["a"]},
                            subject="s")


def test_prose_alone_is_not_a_directive(governed_conn):
    """Code cannot obey prose (§126). A directive that only described what it
    wanted would be a wish nothing could act on, and the department would have
    to invent the requirement - which is the drafting nobody voted for."""
    with pytest.raises(engineering.EngineeringRefused) as refusal:
        engineering.receive(governed_conn, title="x", intended_outcome="be better",
                            resolution_id=_enact(governed_conn), requirement={}, subject="s")
    assert "wish nothing can act on" in str(refusal.value)


def test_the_shortcut_around_evolution_is_named_in_the_row(governed_conn):
    """§119 adjudicated that directives reach this department through Evolution,
    which does not exist. The deviation is declared rather than quiet: a later
    reader must not mistake today's shortcut for the intended architecture."""
    directive = engineering.get_directive(governed_conn, _directive(governed_conn))
    assert directive["arrived_via"] == engineering.VIA_RESOLUTION_DIRECTLY
    assert "no_evolution_relay" in directive["arrived_via"]


# --- the ladder -----------------------------------------------------------------------

def test_an_outcome_the_system_can_obey_is_a_data_change(governed_conn):
    """§8's ladder, answered by the registry that already knows it: an obligation
    kind this system understands can be put in force by adopting an instrument."""
    directive = engineering.get_directive(governed_conn, _directive(governed_conn))
    level, reasoning = engineering.assess(directive)
    assert level == "directive"
    assert "no code is required" in reasoning


def test_an_outcome_nothing_can_obey_is_a_capability_gap(governed_conn):
    """Addendum 46 §40's own example: *"Parliament determines that agents require
    secure real-time video, but the platform contains no video capability.
    Changing instructions cannot create a video transport."*

    An obligation kind nothing understands is exactly that."""
    directive = engineering.get_directive(governed_conn, _directive(
        governed_conn, requirement={"kind": "secure_video_transport"},
        subject="agent_conferences", title="Video"))
    level, reasoning = engineering.assess(directive)
    assert level == engineering.LEVEL_CODE
    assert "capability gap" in reasoning
    assert "secure_video_transport" in reasoning


def test_the_ladder_is_addendum_46s_and_is_not_restated():
    """Five rungs, in §8's order, in one place."""
    assert engineering.LEVELS == (
        "knowledge", "directive", "configuration", "composition", "code")
    assert engineering.DELIVERABLE_LEVELS == engineering.LEVELS[:-1]


def test_the_assessment_is_deterministic_rather_than_asked_of_a_model():
    """A model asked *"could this be data?"* answers plausibly every time,
    including for the cases where it cannot - and the department would report
    level 2 for problems needing level 5, which is what §119 said to write this
    metric against."""
    source = inspect.getsource(engineering.assess)
    assert "UNDERSTOOD_OBLIGATIONS" in source
    for model_ish in ("call_reasoning_model", "model_gateway", "complete("):
        assert model_ish not in source


def test_an_assessment_without_its_reasoning_is_refused(governed_conn):
    with pytest.raises(engineering.EngineeringRefused):
        engineering.record_assessment(governed_conn, 1, engineer="e1",
                                      level="directive", reasoning="  ")


# --- the producer is not the approver -------------------------------------------------

def test_an_engineer_cannot_approve_its_own_proposal(governed_conn):
    """Addendum 46 §11, enforced structurally rather than left to a convention."""
    directive = engineering.get_directive(governed_conn, _directive(governed_conn))
    result = software_engineer.handle(governed_conn, directive, engineer="engineer-1")

    with pytest.raises(engineering.EngineeringRefused) as refusal:
        engineering.approve(governed_conn, result["work_id"], approver="engineer-1")
    assert "cannot also be its only approval" in str(refusal.value)


def test_the_agent_never_calls_approve():
    """The refusal above is one half. This is the other: an agent that reached
    for `approve` at all would be one rename away from approving itself."""
    import ast
    tree = ast.parse(inspect.getsource(software_engineer))
    called = {
        getattr(node.func, "attr", None)
        for node in ast.walk(tree) if isinstance(node, ast.Call)
    }
    # Parsed rather than string-matched: the module docstring names `approve`
    # while explaining why it is never called, and a substring check cannot tell
    # a mention from a call - which would make this test fail for the one reason
    # it should not.
    assert "approve" not in called


def test_somebody_else_approving_puts_the_instrument_in_force(governed_conn):
    """End to end: a directive becomes a rule the organization actually obeys."""
    directive = engineering.get_directive(governed_conn, _directive(governed_conn))
    result = software_engineer.handle(governed_conn, directive, engineer="engineer-1")

    item = engineering.approve(governed_conn, result["work_id"], approver="coo")
    assert governed.effective(governed_conn, "discovery_reports").startswith("Every discovery")
    assert governed.effective_item(governed_conn, "discovery_reports")["id"] == item

    work = engineering.get_work(governed_conn, result["work_id"])
    assert work["approved_by"] == "coo"
    assert work["outcome"] == engineering.OUTCOME_ACHIEVED


def test_a_proposal_that_was_never_made_cannot_be_approved(governed_conn):
    directive = engineering.get_directive(governed_conn, _directive(
        governed_conn, requirement={"kind": "telepathy"}, title="Telepathy"))
    result = software_engineer.handle(governed_conn, directive, engineer="engineer-1")
    with pytest.raises(engineering.EngineeringRefused):
        engineering.approve(governed_conn, result["work_id"], approver="coo")


# --- the metric §119 said to write against --------------------------------------------

def test_needing_code_is_recorded_as_an_outcome_and_not_as_a_failure(governed_conn):
    """§8 defines level 5 as the architecture lacking the mechanism. A department
    that could never say it would report a data solution for every problem,
    always score well, and never change anything."""
    directive = engineering.get_directive(governed_conn, _directive(
        governed_conn, requirement={"kind": "secure_video_transport"}, title="Video"))
    result = software_engineer.handle(governed_conn, directive, engineer="engineer-1")

    assert result["outcome"] == engineering.OUTCOME_NEEDS_CODE
    assert engineering.get_directive(
        governed_conn, directive["id"])["status"] == engineering.STATUS_NEEDS_CODE
    assert engineering.outcomes(governed_conn)["needs_code"] == 1


def test_the_department_is_reported_by_outcome_and_never_by_level(governed_conn):
    """The level says which rung was used; the outcome says whether the thing
    asked for happened. Reporting the first as a score is the failure §119 named
    before this department existed."""
    reported = engineering.outcomes(governed_conn)
    assert set(reported) == {"achieved", "needs_code", "open_directives", "in_flight"}
    assert not any("level" in key for key in reported)


def test_a_proposal_awaiting_approval_counts_as_neither_achieved_nor_refused(governed_conn):
    """`in_flight` exists so a department with proposals nobody has approved
    cannot read as one that delivered them - or as one that refused."""
    directive = engineering.get_directive(governed_conn, _directive(governed_conn))
    software_engineer.handle(governed_conn, directive, engineer="engineer-1")

    reported = engineering.outcomes(governed_conn)
    assert reported["in_flight"] == 1
    assert reported["achieved"] == 0 and reported["needs_code"] == 0


# --- the department cannot exceed itself ----------------------------------------------

def test_a_code_level_assessment_cannot_be_dressed_as_a_proposal(governed_conn):
    """The boundary is honest rather than temporary: nothing here writes code, so
    a work item assessed at level 5 has nothing to propose."""
    work_id = engineering.record_assessment(
        governed_conn, _directive(governed_conn), engineer="e1",
        level=engineering.LEVEL_CODE, reasoning="the mechanism does not exist")
    with pytest.raises(engineering.EngineeringRefused) as refusal:
        engineering.propose_instrument(governed_conn, work_id, instrument={})
    assert "not something this department can deliver" in str(refusal.value)


def test_two_engineers_cannot_take_the_same_directive(governed_conn):
    """Two proposals for one decision is the shape a duplicate claim takes here."""
    _directive(governed_conn)
    first = engineering.claim_next(governed_conn, "engineer-1")
    second = engineering.claim_next(governed_conn, "engineer-2")
    assert first is not None and second is None


def test_an_idle_department_produces_nothing(governed_conn):
    """Addendum 46 §10: work determines staffing. A quiet cycle means the
    organization has asked for nothing, not that the department is broken."""
    software_engineer._engineer_work(governed_conn, "engineer-1")
    assert engineering.outcomes(governed_conn)["in_flight"] == 0


# --- impact analysis, in the only form this architecture supports (§138) ---------------

def test_a_proposal_says_who_it_would_bind(governed_conn):
    """Addendum 30 §4 asks an Evolution Directive to name affected agent classes.
    It is one of the few fields on that list this system can actually fill."""
    for role, identity in (("explorer", "explorer-1"), ("analysis", "analysis-1")):
        fi_db.register_agent(governed_conn, identity, role, 1)
    directive = engineering.get_directive(governed_conn, _directive(governed_conn))
    result = software_engineer.handle(governed_conn, directive, engineer="engineer-1")

    impact = json.loads(engineering.get_work(governed_conn, result["work_id"])["impact"])
    assert impact["roles_affected"] == ["analysis", "explorer"]
    assert impact["binds"] == "*"


def test_a_proposal_that_adoption_would_refuse_says_so_before_an_approval_is_spent(governed_conn):
    """The piece worth having. Without it, a proposal `governed_knowledge.adopt`
    will reject sits in the queue looking deliverable until somebody spends an
    approval finding out.

    **The prediction is checked against the real refusal**, not merely asserted —
    an impact statement that guessed would be worse than none."""
    first = engineering.get_directive(governed_conn, _directive(governed_conn, title="One"))
    approved = software_engineer.handle(governed_conn, first, engineer="engineer-1")
    engineering.approve(governed_conn, approved["work_id"], approver="coo")

    second = engineering.get_directive(governed_conn, _directive(governed_conn, title="Two"))
    result = software_engineer.handle(governed_conn, second, engineer="engineer-1")
    impact = json.loads(engineering.get_work(governed_conn, result["work_id"])["impact"])

    assert impact["would_be_refused"], "the collision was not predicted"
    assert impact["displaces"]["level"] == "organization_policy"

    with pytest.raises(governed.AdoptionRefused):
        engineering.approve(governed_conn, result["work_id"], approver="coo")


def test_a_clean_proposal_predicts_no_refusal(governed_conn):
    """The other direction, so the prediction cannot be right by always saying
    yes."""
    directive = engineering.get_directive(governed_conn, _directive(governed_conn))
    result = software_engineer.handle(governed_conn, directive, engineer="engineer-1")
    impact = json.loads(engineering.get_work(governed_conn, result["work_id"])["impact"])

    assert impact["would_be_refused"] is None
    assert impact["displaces"] is None
    engineering.approve(governed_conn, result["work_id"], approver="coo")


def test_the_impact_statement_names_what_it_does_not_assess(governed_conn):
    """Addendum 30 §4 asks for training requirements, evaluation and
    certification criteria, and a rollout and rollback plan. This system has none
    of those, and an impact statement silent about that would imply a completeness
    it does not have."""
    directive = engineering.get_directive(governed_conn, _directive(governed_conn))
    result = software_engineer.handle(governed_conn, directive, engineer="engineer-1")
    impact = json.loads(engineering.get_work(governed_conn, result["work_id"])["impact"])

    unassessed = " ".join(impact["not_assessed"]).lower()
    for absent in ("training", "certification", "rollback"):
        assert absent in unassessed


def test_a_directive_that_binds_one_role_affects_only_that_role(governed_conn):
    """The other side of the conditional. Every other impact test binds `*`, so
    a version that reported every role regardless of `binds` passed all of them —
    mutation testing said so.

    **A one-sided conditional is tested on one side**, which is the same shape as
    a rule tested against data that cannot exercise it (§129)."""
    for role, identity in (("explorer", "explorer-1"), ("analysis", "analysis-1")):
        fi_db.register_agent(governed_conn, identity, role, 1)
    directive = engineering.get_directive(
        governed_conn, _directive(governed_conn, binds="analysis"))
    result = software_engineer.handle(governed_conn, directive, engineer="engineer-1")

    impact = json.loads(engineering.get_work(governed_conn, result["work_id"])["impact"])
    assert impact["roles_affected"] == ["analysis"]
    assert "explorer" not in impact["roles_affected"]


# -- abandoned claims ---------------------------------------------------------
#
# `claim_next` is a guarded UPDATE, which is what makes two engineers safe. It
# also introduced a way to lose a directive that did not exist before it: an
# engineer that dies between claiming and delivering leaves the row in_progress
# with claimed_by naming a process that is gone, and `open_directives` stops seeing it.
# The organization's own authorized directive then stops being worked, silently.


def _age_claim(conn, directive_id: int, seconds: float) -> None:
    stale = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    conn.execute("UPDATE engineering_directives SET claimed_at = ? WHERE id = ?",
                 (stale, directive_id))


def test_an_abandoned_directive_returns_to_the_open_queue(governed_conn):
    directive_id = _directive(governed_conn)
    engineering.claim_next(governed_conn, "engineer-1")
    _age_claim(governed_conn, directive_id, engineering.CLAIM_TIMEOUT_SECONDS + 30)

    assert engineering.release_stale_claims(governed_conn) == 1
    assert [d["id"] for d in engineering.open_directives(governed_conn)] == [directive_id]
    assert engineering.get_directive(governed_conn, directive_id)["claimed_by"] is None


def test_a_directive_still_within_the_timeout_is_left_alone(governed_conn):
    """Taking a working engineer's directive would produce two proposals for one
    decision - the exact duplication the guarded claim exists to prevent."""
    directive_id = _directive(governed_conn)
    engineering.claim_next(governed_conn, "engineer-1")
    _age_claim(governed_conn, directive_id, engineering.CLAIM_TIMEOUT_SECONDS / 2)

    assert engineering.release_stale_claims(governed_conn) == 0
    assert engineering.open_directives(governed_conn) == []


def test_a_released_directive_can_be_claimed_by_another_engineer(governed_conn):
    directive_id = _directive(governed_conn)
    engineering.claim_next(governed_conn, "engineer-1")
    _age_claim(governed_conn, directive_id, engineering.CLAIM_TIMEOUT_SECONDS + 30)
    engineering.release_stale_claims(governed_conn)

    reclaimed = engineering.claim_next(governed_conn, "engineer-2")
    assert reclaimed is not None and reclaimed["claimed_by"] == "engineer-2"


def test_claiming_records_when_the_claim_was_taken(governed_conn):
    """claimed_by without claimed_at is a claim nothing can age out. The column
    existed alone until §155, which is why the stranding was invisible."""
    directive_id = _directive(governed_conn)
    engineering.claim_next(governed_conn, "engineer-1")

    assert engineering.get_directive(governed_conn, directive_id)["claimed_at"] is not None


def test_the_engineering_timeout_is_not_the_judgment_timeout(governed_conn):
    """Sized against database work, because `handle` makes no model call.

    fi_db's 180s is justified against a measured 42s model call; copying it here
    would inherit a justification that does not apply. Asserted so the two cannot
    quietly converge on one number that fits neither."""
    assert engineering.CLAIM_TIMEOUT_SECONDS < fi_db.CLAIM_TIMEOUT_SECONDS
    # Well above `Database`'s 5s busy_timeout, the only unbounded wait in the path.
    assert engineering.CLAIM_TIMEOUT_SECONDS > 5 * 5
