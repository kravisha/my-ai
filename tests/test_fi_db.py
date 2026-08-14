"""Unit tests for backend/fi_db.py - the SQLite coordination substrate for
the Financial Intelligence system. Pure DB logic, fully hermetic (in-memory
SQLite, no real processes) - the real-subprocess integration test lives
separately in tests/test_coordinator.py, per the plan's deliberate testing
split.
"""

import json

import pytest

from backend import fi_db


@pytest.fixture
def conn():
    connection = fi_db.get_connection(":memory:")
    fi_db.init_schema(connection)
    yield connection
    connection.close()


def test_init_schema_is_idempotent(conn):
    fi_db.init_schema(conn)  # calling again should not raise
    fi_db.init_schema(conn)


def test_register_agent_appears_in_list(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    agents = fi_db.list_agents(conn)
    assert len(agents) == 1
    assert agents[0]["identity"] == "dummy-1"
    assert agents[0]["role"] == "dummy"
    assert agents[0]["pid"] == 111
    assert agents[0]["status"] == "active"


def test_register_agent_upserts_rather_than_duplicating(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.register_agent(conn, "dummy-1", "dummy", 222)  # re-spawned with a new pid
    agents = fi_db.list_agents(conn)
    assert len(agents) == 1
    assert agents[0]["pid"] == 222
    assert agents[0]["status"] == "active"


def test_get_agent_returns_none_for_unknown_identity(conn):
    assert fi_db.get_agent(conn, "nobody") is None


def test_get_agent_returns_registered_agent(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    agent = fi_db.get_agent(conn, "dummy-1")
    assert agent["identity"] == "dummy-1"


def test_record_heartbeat_updates_last_heartbeat_and_logs_metric(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    before = fi_db.get_agent(conn, "dummy-1")["last_heartbeat_at"]
    fi_db.record_heartbeat(conn, "dummy-1")
    after = fi_db.get_agent(conn, "dummy-1")["last_heartbeat_at"]
    assert after >= before

    card = fi_db.get_performance_card(conn)
    assert card[0]["heartbeat_count"] == 1


def test_is_retirement_requested_false_by_default(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    assert fi_db.is_retirement_requested(conn, "dummy-1") is False


def test_request_retirement_sets_flag_agent_can_poll(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.request_retirement(conn, "dummy-1")
    assert fi_db.is_retirement_requested(conn, "dummy-1") is True


def test_is_retirement_requested_false_for_unknown_identity(conn):
    assert fi_db.is_retirement_requested(conn, "nobody") is False


def test_reregistering_agent_resets_retire_flag(conn):
    """A fresh spawn under the same identity should not inherit a stale
    retire request from a previous incarnation."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.request_retirement(conn, "dummy-1")
    fi_db.register_agent(conn, "dummy-1", "dummy", 222)
    assert fi_db.is_retirement_requested(conn, "dummy-1") is False


def test_mark_agent_gone_updates_status(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.mark_agent_gone(conn, "dummy-1")
    assert fi_db.get_agent(conn, "dummy-1")["status"] == "gone"


def test_enqueue_and_fetch_next_pending_directive(conn):
    directive_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    pending = fi_db.fetch_next_pending_directive(conn)
    assert pending["id"] == directive_id
    assert pending["directive_type"] == "spawn"
    assert pending["target_role"] == "dummy"
    assert pending["status"] == "pending"
    assert json.loads(pending["params"]) == {}


def test_fetch_next_pending_directive_returns_none_when_empty(conn):
    assert fi_db.fetch_next_pending_directive(conn) is None


def test_directives_are_fetched_fifo_by_timestamp(conn):
    first_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    second_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")

    first_pending = fi_db.fetch_next_pending_directive(conn)
    assert first_pending["id"] == first_id

    fi_db.complete_directive(conn, first_id, "success")
    second_pending = fi_db.fetch_next_pending_directive(conn)
    assert second_pending["id"] == second_id


def test_complete_directive_moves_row_to_completed_table(conn):
    directive_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")

    fi_db.complete_directive(conn, directive_id, "success", detail="spawned dummy-1")

    assert fi_db.fetch_next_pending_directive(conn) is None
    completed = fi_db.list_completed_directives(conn)
    assert len(completed) == 1
    assert completed[0]["id"] == directive_id
    assert completed[0]["outcome"] == "success"
    assert completed[0]["detail"] == "spawned dummy-1"


def test_complete_directive_with_failure_outcome(conn):
    directive_id = fi_db.enqueue_directive(conn, "retire", "coo", target_identity="dummy-1")
    fi_db.complete_directive(conn, directive_id, "failure", detail="process not found")

    completed = fi_db.list_completed_directives(conn)
    assert completed[0]["outcome"] == "failure"
    assert completed[0]["detail"] == "process not found"


def test_performance_card_reflects_multiple_agents(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.register_agent(conn, "coo-1", "coo", 222)
    fi_db.record_heartbeat(conn, "dummy-1")
    fi_db.record_heartbeat(conn, "dummy-1")

    card = fi_db.get_performance_card(conn)
    by_identity = {row["identity"]: row for row in card}
    assert by_identity["dummy-1"]["heartbeat_count"] == 2
    assert by_identity["coo-1"]["heartbeat_count"] == 0


def test_performance_card_empty_when_no_agents(conn):
    assert fi_db.get_performance_card(conn) == []
