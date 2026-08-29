"""The personnel record, joined to the durable agent id (TQ-99;
addendum 51 §3, §5; docs/SPEC_RECONCILIATION.md §140 §4, §148).

TQ-97 introduced `agent_id` **beside** `agent_names` rather than under it, so two
answers to *which is the durable agent* coexisted — the state addendum 47 §5
forbids, and the one §122 spent an increment undoing three cases of. It was taken
knowingly, for one increment, and held for five.

The test that matters is `test_a_renamed_agent_keeps_one_continuous_history`:
before this, a rename split an agent's personnel folder in two, because the
folder was keyed by the display name addendum 51 §3 says the key must be
independent of.
"""

from __future__ import annotations

import pytest

from backend import agent_identity as identity, fi_db

DESK = "explorer-1"
OTHER_DESK = "analysis-1"


def _registered(conn, desk=DESK, role="explorer"):
    """Through `register_agent`, which is the only path that assigns a name in
    production — a fixture that assigned one itself would not exercise the code
    that assigns one (§132)."""
    fi_db.register_agent(conn, desk, role, pid=4242)
    return fi_db.get_agent_name(conn, desk)


# --- the durable key reaches the personnel record ---------------------------------------

def test_registering_an_agent_gives_it_a_durable_id(conn):
    name = _registered(conn)
    agent_id = fi_db.agent_id_for_name(conn, name)

    assert agent_id, "a registered agent has no durable id"
    assert identity.get(conn, agent_id)["first_name"] == name
    assert fi_db.personnel_record(conn, name)["agent_id"] == agent_id


def test_the_span_and_the_name_carry_the_same_id(conn):
    """Half a history keyed by id and half by name is the drift this increment
    exists to end."""
    name = _registered(conn)
    agent_id = fi_db.agent_id_for_name(conn, name)
    spans = fi_db.assignment_history(conn, name)

    assert len(spans) == 1
    assert spans[0]["agent_id"] == agent_id


def test_two_agents_get_two_ids(conn):
    first = _registered(conn)
    second = _registered(conn, OTHER_DESK, "analysis")
    assert first != second
    assert fi_db.agent_id_for_name(conn, first) != fi_db.agent_id_for_name(conn, second)


# --- the property that could not hold before ---------------------------------------------

def test_a_renamed_agent_keeps_one_continuous_history(conn):
    """**The whole point of TQ-99.**

    Before it, `assignment_history` was keyed by the display name, so renaming an
    agent split its personnel folder in two: the spans stayed under the old name
    and nothing under the new one found them. Addendum 51 §3 asks for an
    identifier *independent of display name* precisely so this cannot happen."""
    name = _registered(conn)
    agent_id = fi_db.agent_id_for_name(conn, name)
    before = fi_db.assignment_history(conn, name)
    assert before, "no history to lose"

    new_name = next(n for n in fi_db.AGENT_NAME_POOL if n != name)
    identity.rename(conn, agent_id, first_name=new_name, reason="the owner asked")

    after = fi_db.assignment_history(conn, new_name)
    assert [row["id"] for row in after] == [row["id"] for row in before], (
        "the rename split the personnel history")
    assert fi_db.agent_id_for_name(conn, new_name) == agent_id
    assert fi_db.personnel_record(conn, new_name)["agent_id"] == agent_id


def test_a_released_name_is_not_returned_to_the_pool(conn):
    """A name that changed hands would make every older sentence about it
    ambiguous, so it stays spent — the same rule `create` enforces."""
    name = _registered(conn)
    agent_id = fi_db.agent_id_for_name(conn, name)
    new_name = next(n for n in fi_db.AGENT_NAME_POOL if n != name)
    identity.rename(conn, agent_id, first_name=new_name, reason="r")

    assert fi_db.agent_id_for_name(conn, name) is None
    with pytest.raises(identity.IdentityRefused):
        identity.create(conn, first_name=name)


def test_the_desk_moves_with_the_agent_on_a_rename(conn):
    """A rename changes what an agent is called, not where it sits."""
    name = _registered(conn)
    agent_id = fi_db.agent_id_for_name(conn, name)
    new_name = next(n for n in fi_db.AGENT_NAME_POOL if n != name)
    identity.rename(conn, agent_id, first_name=new_name, reason="r")

    assert fi_db.get_agent_name(conn, DESK) == new_name
    assert fi_db.current_assignment(conn, identity=DESK)["identity"] == DESK


# --- the backfill is backdated, not stamped at now ----------------------------------------

def test_an_identity_backfilled_onto_an_older_binding_is_backdated(conn):
    """`_ensure_assignment`'s lesson, one layer along: an identity created at
    backfill time reports every agent as having come into existence the moment
    somebody restarted the system — and the creation date is exactly the fact a
    persistent identity exists to carry (addendum 51 §5).

    The pre-TQ-97 state is built directly, because the production API cannot
    produce a name binding without an identity any more. That is what the
    backfill path is *for*."""
    # The pool row already exists - `init_schema` seeds all forty names. What a
    # pre-TQ-97 database has is a *binding* with no identity behind it.
    conn.execute(
        "UPDATE agent_names SET assigned_to_identity = ?,"
        " assigned_at = '2026-01-01T00:00:00+00:00' WHERE name = 'Amara'", (DESK,))
    conn.execute(
        "INSERT INTO agent_assignments (name, identity, role, started_at, schema_version)"
        " VALUES ('Amara', ?, 'explorer', '2026-01-01T00:00:00+00:00', 1)", (DESK,))
    assert fi_db.agent_id_for_name(conn, "Amara") is None

    fi_db.register_agent(conn, DESK, "explorer", pid=1)

    agent_id = fi_db.agent_id_for_name(conn, "Amara")
    assert agent_id, "the binding did not acquire an id on registration"
    assert identity.get(conn, agent_id)["created_at"] == "2026-01-01T00:00:00+00:00", (
        "the identity was dated to the backfill rather than to when the name was bound")


def test_the_backfill_stamps_spans_and_events_that_predate_it(conn):
    """A history half keyed by id and half by name would answer differently
    depending on which half a caller happened to read."""
    # The pool row already exists - `init_schema` seeds all forty names. What a
    # pre-TQ-97 database has is a *binding* with no identity behind it.
    conn.execute(
        "UPDATE agent_names SET assigned_to_identity = ?,"
        " assigned_at = '2026-01-01T00:00:00+00:00' WHERE name = 'Amara'", (DESK,))
    conn.execute(
        "INSERT INTO agent_assignments (name, identity, role, started_at, schema_version)"
        " VALUES ('Amara', ?, 'explorer', '2026-01-01T00:00:00+00:00', 1)", (DESK,))
    fi_db.record_personnel_event(
        conn, "Amara", "commendation", subject="a lead nobody else saw", recorded_by="coo-1")

    fi_db.register_agent(conn, DESK, "explorer", pid=1)
    agent_id = fi_db.agent_id_for_name(conn, "Amara")

    unstamped = conn.fetchall(
        "SELECT 'span' AS k FROM agent_assignments WHERE name = 'Amara' AND agent_id IS NULL"
        " UNION ALL"
        " SELECT 'event' FROM personnel_events WHERE name = 'Amara' AND agent_id IS NULL")
    assert unstamped == [], f"rows left unkeyed after backfill: {unstamped}"
    assert fi_db.assignment_history(conn, "Amara")[0]["agent_id"] == agent_id


def test_the_backfill_is_idempotent_across_respawns(conn):
    """It runs on every registration and every respawn. A second identity would
    read as the agent having been replaced (§88's rule about the COO)."""
    _registered(conn)
    first = fi_db.agent_id_for_name(conn, fi_db.get_agent_name(conn, DESK))
    for _ in range(3):
        fi_db.register_agent(conn, DESK, "explorer", pid=9)
    assert fi_db.agent_id_for_name(conn, fi_db.get_agent_name(conn, DESK)) == first
    assert len(identity.roster(conn)) == 1


# --- the two views of a name agree ---------------------------------------------------------

def test_the_name_pool_and_the_identity_never_disagree(conn):
    """The tripwire on the denormalisation. `agent_names.agent_id` and
    `agent_identities.first_name` are two views of one fact, which is the
    arrangement 47 §5 warns about — so the invariant is asserted rather than
    assumed.

    Exercised across a registration, a rename, and a second agent, because a
    check over one row cannot show the two staying in step."""
    _registered(conn)
    _registered(conn, OTHER_DESK, "analysis")
    held = fi_db.get_agent_name(conn, DESK)
    identity.rename(conn, fi_db.agent_id_for_name(conn, held),
                    first_name=next(n for n in fi_db.AGENT_NAME_POOL
                                    if fi_db.agent_id_for_name(conn, n) is None),
                    reason="r")

    disagreements = conn.fetchall(
        "SELECT n.name, n.agent_id, i.first_name FROM agent_names n"
        " JOIN agent_identities i ON i.agent_id = n.agent_id"
        " WHERE n.agent_id IS NOT NULL AND i.first_name <> n.name")
    assert disagreements == [], (
        f"the pool and the identity disagree about a name: {disagreements}")


def test_work_stays_attributed_across_a_rename(conn):
    """Personnel history is *derived* by intersecting work timestamps with the
    span that contained them, and no work row is denormalised against a name. So
    a rename must not move work — and must not lose it either."""
    name = _registered(conn)
    fi_db.enqueue_report(conn, DESK, fi_db.get_agent(conn, DESK)["spawned_at"],
                         "lead", "SYN1", summary="s", evidence_ids=[])
    before = fi_db.attributed_work(conn, name)
    assert before["total"] >= 1, "no work to attribute"

    agent_id = fi_db.agent_id_for_name(conn, name)
    new_name = next(n for n in fi_db.AGENT_NAME_POOL if fi_db.agent_id_for_name(conn, n) is None)
    identity.rename(conn, agent_id, first_name=new_name, reason="r")

    assert fi_db.attributed_work(conn, new_name) == before
