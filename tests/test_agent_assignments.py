"""Assignment spans: which agent occupied which slot, and when.

The owner decision of 2026-08-17 separates the durable agent (`name`) from the
desk it occupies (`identity`). These tests hold the two invariants that make
personnel history reconstructible - one open span per agent, one per desk - and
the boundary rule that decides which span a piece of work belongs to.

The most load-bearing test here is the respawn one. `register_agent` runs on
every spawn and every respawn, and a respawn that opened a second span would
read as a transfer the agent never made, splitting one agent's record in two.
"""

import pytest

from backend import fi_db


def at(second: int) -> str:
    return f"2026-08-17T00:00:{second:02d}.000000+00:00"


def set_span(conn, span_id: int, started_at: str, ended_at: str | None):
    conn.execute(
        "UPDATE agent_assignments SET started_at = ?, ended_at = ? WHERE id = ?",
        (started_at, ended_at, span_id),
    )


def add_detection(conn, identity: str, created_at: str):
    conn.execute(
        "INSERT INTO detector_events (created_at, producer_identity, producer_spawned_at, security, "
        "detector_type, peak_iv, baseline_iv, ratio, threshold, schema_version) "
        "VALUES (?, ?, ?, 'SYN1', 'iv_ratio', 0.5, 0.2, 2.5, 2.0, 1)",
        (created_at, identity, created_at),
    )


@pytest.fixture
def registered(conn):
    fi_db.init_schema(conn)
    fi_db.register_agent(conn, "explorer-1", "explorer", 100)
    return fi_db.get_agent_name(conn, "explorer-1")


# -- opening ------------------------------------------------------------------

def test_registration_opens_an_assignment(conn, registered):
    span = fi_db.current_assignment(conn, name=registered)
    assert span["identity"] == "explorer-1"
    assert span["role"] == "explorer"
    assert span["ended_at"] is None


def test_respawn_does_not_open_a_second_assignment(conn, registered):
    """The regression guard.

    Name assignment is idempotent so a respawn keeps its name; the span must be
    idempotent for the same reason, or one agent's record becomes two."""
    for pid in (101, 102, 103):
        fi_db.register_agent(conn, "explorer-1", "explorer", pid)
    assert len(fi_db.assignment_history(conn, registered)) == 1


def test_a_second_open_span_for_one_agent_is_refused(conn, registered):
    with pytest.raises(ValueError, match="already holds"):
        fi_db.open_assignment(conn, registered, "analysis-1", "analysis")


def test_a_second_open_span_for_one_desk_is_refused(conn, registered):
    fi_db.register_agent(conn, "analysis-1", "analysis", 200)
    other = fi_db.get_agent_name(conn, "analysis-1")
    with pytest.raises(ValueError, match="already occupied"):
        fi_db.reassign_agent_name(conn, other, "explorer-1", "attempted move")


def test_the_database_enforces_one_open_span_per_desk(conn, registered):
    """Enforced by a partial unique index, not only by the function.

    An invariant that lives solely in application code is one raw INSERT away
    from being violated, and attribution is ambiguous the moment it is."""
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO agent_assignments (name, identity, role, started_at, schema_version) "
            "VALUES ('Someone', 'explorer-1', 'explorer', ?, 5)",
            (at(0),),
        )


# -- transfer -----------------------------------------------------------------

def test_transfer_closes_the_old_span_and_opens_a_new_one(conn, registered):
    fi_db.reassign_agent_name(conn, registered, "analysis-1", "transferred to analysis")
    history = fi_db.assignment_history(conn, registered)

    assert [span["identity"] for span in history] == ["explorer-1", "analysis-1"]
    assert history[0]["ended_at"] is not None, "the vacated span must be closed"
    assert history[1]["ended_at"] is None
    assert fi_db.get_agent_name(conn, "analysis-1") == registered


def test_transfer_leaves_the_old_desk_free_for_someone_else(conn, registered):
    fi_db.reassign_agent_name(conn, registered, "analysis-1", "transfer")
    assert fi_db.current_assignment(conn, identity="explorer-1") is None

    fi_db.open_assignment(conn, "Blake", "explorer-1", "explorer", "backfilled the vacancy")
    assert fi_db.current_assignment(conn, identity="explorer-1")["name"] == "Blake"


def test_transferring_to_the_desk_already_held_is_a_no_op(conn, registered):
    before = fi_db.assignment_history(conn, registered)
    fi_db.reassign_agent_name(conn, registered, "explorer-1", "no move")
    assert fi_db.assignment_history(conn, registered) == before


def test_transferring_an_unknown_name_is_refused(conn, registered):
    with pytest.raises(ValueError, match="no agent named"):
        fi_db.reassign_agent_name(conn, "Nobody", "analysis-1")


# -- dormancy (owner decision, 2026-08-17) ------------------------------------

def test_retirement_does_not_vacate_the_desk(conn, registered):
    """A retired agent still holds its assignment.

    It is not working and it has not vacated - lifecycle_state carries that, and
    the assignment does not. Ending the span on retirement would make resuming
    an agent require a fresh assignment, and would break its history into pieces
    at every dormancy."""
    fi_db.request_retirement(conn, "explorer-1")

    span = fi_db.current_assignment(conn, name=registered)
    assert span is not None and span["ended_at"] is None
    assert span["identity"] == "explorer-1"

    record = fi_db.personnel_record(conn, registered)
    assert record["current"]["identity"] == "explorer-1"
    assert record["current"]["lifecycle_state"] == fi_db.LIFECYCLE_DORMANT


def test_resume_leaves_the_single_span_intact(conn, registered):
    fi_db.request_retirement(conn, "explorer-1")
    fi_db.resume_agent(conn, "explorer-1")
    assert len(fi_db.assignment_history(conn, registered)) == 1


# -- attribution --------------------------------------------------------------

def test_work_is_attributed_to_the_span_that_contained_it(conn, registered):
    """The whole point: no work row names an agent, yet the agent's record is exact."""
    first = fi_db.current_assignment(conn, name=registered)["id"]
    set_span(conn, first, at(0), at(10))
    fi_db.open_assignment(conn, registered, "analysis-1", "analysis", "transfer")
    second = fi_db.current_assignment(conn, name=registered)["id"]
    set_span(conn, second, at(10), None)

    add_detection(conn, "explorer-1", at(5))    # theirs, first span
    add_detection(conn, "analysis-1", at(20))   # theirs, second span

    assert fi_db.attributed_work(conn, registered)["detector_events"] == 2


def test_work_done_by_a_successor_is_not_attributed_to_the_agent_who_left(conn, registered):
    """The failure a denormalised name column would have produced silently."""
    first = fi_db.current_assignment(conn, name=registered)["id"]
    set_span(conn, first, at(0), at(10))
    fi_db.open_assignment(conn, registered, "analysis-1", "analysis", "transfer")

    add_detection(conn, "explorer-1", at(5))    # theirs
    add_detection(conn, "explorer-1", at(50))   # the successor at that desk

    assert fi_db.attributed_work(conn, registered)["detector_events"] == 1


def test_a_row_at_the_exact_instant_of_transfer_belongs_to_one_span_only(conn, registered):
    """Half-open spans: started_at <= t < ended_at.

    A closed interval on both ends would count a row written at the transfer
    instant twice, and an open one would lose it. Both are wrong in a way that
    only shows up on a boundary nobody tests by accident."""
    first = fi_db.current_assignment(conn, name=registered)["id"]
    set_span(conn, first, at(0), at(10))
    fi_db.open_assignment(conn, registered, "analysis-1", "analysis", "transfer")
    set_span(conn, fi_db.current_assignment(conn, name=registered)["id"], at(10), None)

    add_detection(conn, "explorer-1", at(10))   # exactly at the boundary, old desk

    assert fi_db.attributed_work(conn, registered)["detector_events"] == 0, (
        "a row at the boundary belongs to the span that starts there, not the one that ends"
    )


def test_attribution_counts_pending_reports_as_well_as_completed(conn, registered):
    """An agent's record must not shrink and grow as the queue drains."""
    tables = {table for table, _ in fi_db.WORK_PROVENANCE}
    assert {"discovery_reports", "discovery_reports_completed"} <= tables


# -- personnel record ---------------------------------------------------------

def test_personnel_record_separates_current_from_history(conn, registered):
    fi_db.reassign_agent_name(conn, registered, "analysis-1", "transfer")
    record = fi_db.personnel_record(conn, registered)

    assert record["name"] == registered
    assert record["current"]["identity"] == "analysis-1"
    assert len(record["history"]) == 2, "the earlier assignment is still a historical fact"
    assert record["history"][0]["identity"] == "explorer-1"


def test_personnel_record_for_an_unknown_name_is_none(conn, registered):
    assert fi_db.personnel_record(conn, "Nobody") is None


def test_list_personnel_covers_every_assigned_name(conn, registered):
    fi_db.register_agent(conn, "analysis-1", "analysis", 200)
    names = {record["name"] for record in fi_db.list_personnel(conn)}
    assert names == {registered, fi_db.get_agent_name(conn, "analysis-1")}


# -- migration ----------------------------------------------------------------

def test_a_pre_existing_binding_acquires_a_span_on_next_registration(conn):
    """Databases created before this table have bindings and no spans.

    They pick one up on the next registration rather than through a migration
    step, because every agent registers on every start."""
    fi_db.init_schema(conn)
    conn.execute(
        "UPDATE agent_names SET assigned_to_identity = 'explorer-1', assigned_at = ? "
        "WHERE name = (SELECT name FROM agent_names WHERE reserved = 0 ORDER BY name LIMIT 1)",
        (at(0),),
    )
    name = fi_db.get_agent_name(conn, "explorer-1")
    assert fi_db.current_assignment(conn, name=name) is None

    fi_db.register_agent(conn, "explorer-1", "explorer", 100)

    span = fi_db.current_assignment(conn, name=name)
    assert span is not None and span["identity"] == "explorer-1"


def test_a_backfilled_span_is_backdated_to_the_original_binding(conn):
    """Regression: a span starting at backfill time orphans every prior hour of work.

    Found against the real database, which held 188 detector events, 361 evidence
    items, four completed reports and four grades - all produced before this
    table existed, and all attributed to nobody until the span was backdated to
    `agent_names.assigned_at`. A table whose entire purpose is that history
    survives had been discarding the history it was migrating."""
    fi_db.init_schema(conn)
    conn.execute(
        "UPDATE agent_names SET assigned_to_identity = 'explorer-1', assigned_at = ? "
        "WHERE name = (SELECT name FROM agent_names WHERE reserved = 0 ORDER BY name LIMIT 1)",
        (at(0),),
    )
    name = fi_db.get_agent_name(conn, "explorer-1")
    add_detection(conn, "explorer-1", at(5))   # work done before the table existed

    fi_db.register_agent(conn, "explorer-1", "explorer", 100)

    assert fi_db.current_assignment(conn, name=name)["started_at"] == at(0)
    assert fi_db.attributed_work(conn, name)["detector_events"] == 1, (
        "work predating the backfill must still be attributed"
    )
