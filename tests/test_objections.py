"""Declining ordered work on a named ground, and settling it by checking.

The premise G5 was written against turned out to be wrong in a useful way. There
was no free-form refusal to replace, because **there was no refusal at all**:
every directive ended `success` or `failure`, and two paths in the Controller
were objections wearing a failure's clothes. Being ordered to retire an agent
that does not exist is not the executor breaking.

Three things carry these tests. Filing is constrained - closed ground, evidence
and remedy all required. Settling is a *check* against records, not a judgment,
so an objection can be found wrong. And the separation from G7 holds end to end:
the module that decides has no write path, and the function that writes does no
deciding.
"""

import pytest

from backend import compliance, fi_db
from backend.controller import Controller


@pytest.fixture
def controller(tmp_path):
    coord = Controller(db_path=str(tmp_path / "fi_test.db"))
    yield coord
    coord.close()


def pending_directive(conn, directive_type="retire", identity="explorer-9"):
    return fi_db.enqueue_directive(
        conn, directive_type=directive_type, target_role="explorer",
        target_identity=identity, requested_by="coo-1", reason="test",
    )


def file(conn, directive_id, ground="missing dependency", evidence="ev", remedy="rem"):
    return fi_db.file_objection(
        conn, directive_id, filed_by="controller-1", ground=ground,
        evidence=evidence, remedy=remedy,
    )


# -- filing is constrained ----------------------------------------------------

def test_an_objection_must_name_a_ground_from_the_closed_list(conn):
    """An 'other' category would restore free-form refusal under a new name."""
    directive_id = pending_directive(conn)
    with pytest.raises(ValueError, match="unknown objection ground"):
        file(conn, directive_id, ground="i would rather not")


def test_an_objection_must_carry_evidence(conn):
    directive_id = pending_directive(conn)
    with pytest.raises(ValueError, match="evidence"):
        file(conn, directive_id, evidence="   ")


def test_an_objection_must_propose_a_remedy(conn):
    """The manifesto's fifth principle, enforced at the point of refusal: a
    blocked agent owes what would let the work proceed, not only the fact that it
    is blocked."""
    directive_id = pending_directive(conn)
    with pytest.raises(ValueError, match="remedy"):
        file(conn, directive_id, remedy="")


def test_objecting_to_a_directive_that_is_not_pending_is_refused(conn):
    directive_id = pending_directive(conn)
    file(conn, directive_id)
    with pytest.raises(ValueError, match="not pending"):
        file(conn, directive_id)


# -- an objection completes the directive, and does not fail it ---------------

def test_an_objected_directive_leaves_the_pending_queue(conn):
    """The regression that would hurt most. Before the trigger carried
    'objected', an objected directive stayed pending, so the executor would
    re-object every cycle forever."""
    directive_id = pending_directive(conn)
    file(conn, directive_id)

    assert fi_db.fetch_next_pending_directive(conn) is None
    archived = conn.fetchone("SELECT * FROM coo_directives_completed WHERE id = ?", (directive_id,))
    assert archived["outcome"] == "objected"


def test_an_objection_is_not_recorded_as_a_failure(conn):
    """The distinction the whole mechanism exists for. An executor that correctly
    declines an impossible order should not read as unreliable."""
    directive_id = pending_directive(conn)
    file(conn, directive_id)

    archived = conn.fetchone("SELECT outcome FROM coo_directives_completed WHERE id = ?", (directive_id,))
    assert archived["outcome"] != "failure"


# -- settling is checking, not judging ---------------------------------------

def test_a_verifiable_objection_is_upheld_when_the_records_agree(conn):
    directive_id = pending_directive(conn, identity="explorer-404")
    objection_id = file(conn, directive_id)

    settled = fi_db.settle_objection(conn, objection_id, settled_by="test")

    assert settled["status"] == "upheld"
    assert "explorer-404" in settled["settlement_reason"]


def test_a_verifiable_objection_is_rejected_when_the_records_contradict_it(conn):
    """The half that makes settlement real rather than ceremonial. If every
    objection were upheld, filing one would be free and the check would be
    decoration."""
    fi_db.register_agent(conn, "explorer-1", "explorer", 4242)
    directive_id = pending_directive(conn, identity="explorer-1")
    objection_id = file(conn, directive_id)

    settled = fi_db.settle_objection(conn, objection_id, settled_by="test")

    assert settled["status"] == "rejected"
    assert "exists" in settled["settlement_reason"]


def test_a_judged_ground_escalates_rather_than_being_decided(conn):
    """No agent can adjudicate, so nothing pretends to."""
    directive_id = pending_directive(conn)
    objection_id = file(conn, directive_id, ground="integrity or safety concern")

    settled = fi_db.settle_objection(conn, objection_id, settled_by="test")

    assert settled["status"] == "escalated"
    assert "owner" in settled["settlement_reason"]


def test_a_ground_with_no_checker_escalates_and_says_what_is_missing(conn):
    """Not quietly rejected. An unsettled objection treated as unfounded would
    make refusing cost the objector, which is the incentive the framework spends
    a section trying to avoid."""
    directive_id = pending_directive(conn)
    objection_id = file(conn, directive_id, ground="workload harm")

    settled = fi_db.settle_objection(conn, objection_id, settled_by="test")

    assert settled["status"] == "escalated"
    assert "threshold" in settled["settlement_reason"]


def test_an_objection_cannot_be_settled_twice(conn):
    directive_id = pending_directive(conn)
    objection_id = file(conn, directive_id)
    fi_db.settle_objection(conn, objection_id, settled_by="test")

    with pytest.raises(ValueError, match="already"):
        fi_db.settle_objection(conn, objection_id, settled_by="test")


# -- the separation from G7, end to end --------------------------------------

def test_the_checker_reports_but_cannot_settle(conn):
    """Investigation proposes; something else disposes.

    `compliance.check_objection` returns a reading and writes nothing, which is
    checked here by calling it and finding the objection untouched. The read-only
    property is asserted structurally in test_compliance.py; this is the same
    claim from the behavioural side, on the one mechanism most likely to erode
    it."""
    directive_id = pending_directive(conn, identity="explorer-404")
    objection_id = file(conn, directive_id)
    directive = conn.fetchone("SELECT * FROM coo_directives_completed WHERE id = ?", (directive_id,))

    settlement = compliance.check_objection(conn, "missing dependency", dict(directive))

    assert settlement.outcome == compliance.UPHELD
    assert fi_db.get_objection(conn, objection_id)["status"] == "filed", (
        "checking an objection changed it; the checker must have no write path"
    )


def test_the_unchecked_grounds_are_counted(conn):
    """The gap between verifiable in principle and checkable today is a number,
    so it cannot quietly stay where it is."""
    assert len(compliance.UNCHECKED_GROUNDS) == compliance.UNCHECKED_GROUND_COUNT
    total = (compliance.UNCHECKED_GROUND_COUNT + compliance.CHECKED_GROUND_COUNT
             + compliance.JUDGED_GROUND_COUNT)
    assert total == len(compliance.OBJECTION_GROUNDS), "a ground is unaccounted for"
    for ground, reason in compliance.UNCHECKED_GROUNDS.items():
        assert len(reason) > 40, f"{ground} is unchecked without saying what is missing"


# -- the Controller's two real instances -------------------------------------

def test_being_ordered_to_retire_a_missing_agent_is_an_objection(controller):
    """Recorded as a failure before G5. The Controller worked exactly as
    intended; the order named something absent."""
    directive_id = pending_directive(controller.conn, "retire", "explorer-404")
    controller.process_next_directive()

    objection = fi_db.list_objections(controller.conn)[-1]
    assert objection["ground"] == "missing dependency"
    assert objection["directive_id"] == directive_id
    assert "explorer-404" in objection["evidence"]
    assert objection["remedy"]


def test_being_ordered_to_resume_a_missing_agent_is_an_objection(controller):
    pending_directive(controller.conn, "resume", "explorer-404")
    controller.process_next_directive()

    assert fi_db.list_objections(controller.conn)[-1]["ground"] == "missing dependency"


def test_an_unhandled_directive_type_is_a_jurisdiction_objection(controller):
    """Nothing broke - the Controller was asked to do something outside what it
    executes, and the remedy names the real options rather than just declining."""
    pending_directive(controller.conn, "audit_the_books", "explorer-1")
    controller.process_next_directive()

    objection = fi_db.list_objections(controller.conn)[-1]
    assert objection["ground"] == "jurisdiction mismatch"
    assert "audit_the_books" in objection["evidence"]


def test_the_controller_settles_its_own_objection_against_the_registry(controller):
    """End to end: the objection is filed by one mechanism and checked by
    another, and the check re-derives the claim from records rather than
    believing the objector."""
    pending_directive(controller.conn, "retire", "explorer-404")
    controller.process_next_directive()
    objection_id = fi_db.list_objections(controller.conn)[-1]["id"]

    settled = fi_db.settle_objection(controller.conn, objection_id, settled_by="test")
    assert settled["status"] == "upheld"
