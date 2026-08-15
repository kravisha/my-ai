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


def test_register_agent_resets_last_heartbeat_on_reregistration(conn):
    """Identity is now a permanent role-slot, so re-registration (a real
    respawn wearing the same identity, not a rare edge case) must not let a
    fresh life inherit its previous life's last_heartbeat_at - that stale
    timestamp could already be past agents/coo.py's staleness threshold and
    get the freshly-registered agent marked 'crashed' immediately."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.record_heartbeat(conn, "dummy-1")
    assert fi_db.get_agent(conn, "dummy-1")["last_heartbeat_at"] is not None

    fi_db.register_agent(conn, "dummy-1", "dummy", 222)  # respawned under the same permanent identity
    assert fi_db.get_agent(conn, "dummy-1")["last_heartbeat_at"] is None


def test_get_agent_returns_none_for_unknown_identity(conn):
    assert fi_db.get_agent(conn, "nobody") is None


def test_get_agent_returns_registered_agent(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    agent = fi_db.get_agent(conn, "dummy-1")
    assert agent["identity"] == "dummy-1"


def test_record_heartbeat_updates_last_heartbeat_and_logs_metric(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    assert fi_db.get_agent(conn, "dummy-1")["last_heartbeat_at"] is None

    fi_db.record_heartbeat(conn, "dummy-1")
    assert fi_db.get_agent(conn, "dummy-1")["last_heartbeat_at"] is not None

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


def test_enqueue_directive_reason_is_optional(conn):
    """Backward compatibility: existing callers that don't pass reason keep
    working, and get a null reason rather than an error."""
    directive_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    pending = fi_db.fetch_next_pending_directive(conn)
    assert pending["id"] == directive_id
    assert pending["reason"] is None


def test_schema_version_is_stamped_on_agent_registry_and_health_metrics(conn):
    """Gap 1 (project brief): every message/record carries a schema
    version, addressed alongside (not instead of) the additive-only-
    columns rule - see the module docstring in fi_db.py for why both."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    agent = fi_db.get_agent(conn, "dummy-1")
    assert agent["schema_version"] == fi_db.SCHEMA_VERSION

    fi_db.record_heartbeat(conn, "dummy-1")
    metric_row = conn.execute("SELECT schema_version FROM health_metrics WHERE identity = 'dummy-1'").fetchone()
    assert metric_row["schema_version"] == fi_db.SCHEMA_VERSION


def test_schema_version_is_stamped_on_directives_and_survives_archival(conn):
    directive_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    pending = fi_db.fetch_next_pending_directive(conn)
    assert pending["schema_version"] == fi_db.SCHEMA_VERSION

    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-1")
    completed = fi_db.list_completed_directives(conn)
    assert completed[0]["schema_version"] == fi_db.SCHEMA_VERSION


def test_enqueue_directive_reason_is_captured_and_survives_archival(conn):
    """Gap 2 (project brief): COO decisions should be logged with a reason.
    This checks the reason is stored on the pending row and carried through
    to the completed table by the archive trigger, not dropped along the way."""
    directive_id = fi_db.enqueue_directive(
        conn, "spawn", "coo", target_role="dummy",
        reason="baseline role 'dummy' has zero active agents - respawning to maintain baseline",
    )
    pending = fi_db.fetch_next_pending_directive(conn)
    assert pending["reason"] == "baseline role 'dummy' has zero active agents - respawning to maintain baseline"

    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-1")
    completed = fi_db.list_completed_directives(conn)
    assert completed[0]["reason"] == "baseline role 'dummy' has zero active agents - respawning to maintain baseline"


def test_directives_needing_observation_excludes_non_spawn_and_failures(conn):
    spawn_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    fi_db.complete_directive(conn, spawn_id, "success", detail="dummy-1")

    failed_spawn_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    fi_db.complete_directive(conn, failed_spawn_id, "failure", detail="boom")

    retire_id = fi_db.enqueue_directive(conn, "retire", "coo", target_identity="dummy-1")
    fi_db.complete_directive(conn, retire_id, "success", detail="retirement requested for dummy-1")

    ready = fi_db.list_directives_needing_observation(conn, grace_seconds=0)
    assert [r["id"] for r in ready] == [spawn_id]


def test_directives_needing_observation_respects_grace_period(conn):
    directive_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-1")

    assert fi_db.list_directives_needing_observation(conn, grace_seconds=999) == []
    assert [r["id"] for r in fi_db.list_directives_needing_observation(conn, grace_seconds=0)] == [directive_id]


def test_directives_needing_observation_excludes_already_observed(conn):
    directive_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-1")
    fi_db.record_observed_result(conn, directive_id, "established")

    assert fi_db.list_directives_needing_observation(conn, grace_seconds=0) == []


def test_record_observed_result_is_visible_on_completed_directive(conn):
    directive_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-1")

    fi_db.record_observed_result(conn, directive_id, "established")

    completed = fi_db.list_completed_directives(conn)
    assert completed[0]["observed_result"] == "established"
    assert completed[0]["observed_at"] is not None


def test_has_pending_spawn_directive_true_while_unprocessed(conn):
    fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    assert fi_db.has_pending_spawn_directive(conn, "dummy") is True


def test_has_pending_spawn_directive_false_once_completed(conn):
    directive_id = fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-1")
    assert fi_db.has_pending_spawn_directive(conn, "dummy") is False


def test_has_pending_spawn_directive_false_for_different_role(conn):
    fi_db.enqueue_directive(conn, "spawn", "coo", target_role="dummy")
    assert fi_db.has_pending_spawn_directive(conn, "explorer") is False


def test_mark_agent_crashed_is_distinct_from_gone(conn):
    """Gap 3 (project brief): restart-vs-crash distinction - 'crashed'
    (detected by COO's health evaluation) must be a different status from
    'gone' (the agent's own clean exit), not collapsed into the same value."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.mark_agent_crashed(conn, "dummy-1")
    assert fi_db.get_agent(conn, "dummy-1")["status"] == "crashed"


def test_list_stale_active_agents_excludes_fresh_heartbeat(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.record_heartbeat(conn, "dummy-1")
    assert fi_db.list_stale_active_agents(conn, stale_seconds=999) == []


def test_list_stale_active_agents_includes_agent_past_threshold(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.record_heartbeat(conn, "dummy-1")
    stale = fi_db.list_stale_active_agents(conn, stale_seconds=0)
    assert [a["identity"] for a in stale] == ["dummy-1"]


def test_list_stale_active_agents_uses_spawn_time_when_no_heartbeat_yet(conn):
    """An agent that registered but crashed before its first heartbeat has
    no last_heartbeat_at to check - fall back to spawned_at rather than
    treating a null heartbeat as 'never stale'."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    stale = fi_db.list_stale_active_agents(conn, stale_seconds=0)
    assert [a["identity"] for a in stale] == ["dummy-1"]


def test_list_stale_active_agents_excludes_non_active_status(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.mark_agent_gone(conn, "dummy-1")
    assert fi_db.list_stale_active_agents(conn, stale_seconds=0) == []


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
