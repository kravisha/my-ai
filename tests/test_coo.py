"""Unit tests for agents/coo.py's decision logic - pure DB logic, no real
process needed here (the real bootstrap->baseline flow is covered as an
integration test in test_coordinator.py alongside the rest of the genuine
subprocess tests)."""

import pytest

from agents.coo import (
    BASELINE_ROLES,
    _coo_work,
    _ensure_baseline_population,
    _evaluate_agent_health,
    _evaluate_past_decisions,
    _role_spawn_in_flight,
)
from backend import fi_db


@pytest.fixture
def conn():
    connection = fi_db.get_connection(":memory:")
    fi_db.init_schema(connection)
    yield connection
    connection.close()


def test_ensure_baseline_population_enqueues_spawn_when_role_missing(conn):
    _ensure_baseline_population(conn)
    pending = fi_db.fetch_next_pending_directive(conn)
    assert pending["directive_type"] == "spawn"
    assert pending["target_role"] in BASELINE_ROLES
    assert pending["requested_by"] == "coo"
    # Gap 2 (project brief): COO's decision must carry a reason, and a first-
    # ever spawn should read differently from a respawn-after-death (see
    # test_ensure_baseline_population_respawns_role_after_it_goes_gone below).
    assert "never been spawned" in pending["reason"]


def test_ensure_baseline_population_does_not_duplicate_when_role_already_active(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    _ensure_baseline_population(conn)
    assert fi_db.fetch_next_pending_directive(conn) is None


def test_ensure_baseline_population_respawns_role_after_it_goes_gone(conn):
    """If the only dummy dies, COO should notice on its next cycle and ask
    for a replacement - a small real instance of maintaining ecosystem
    health, not just a one-time bootstrap check."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.mark_agent_gone(conn, "dummy-1")

    _ensure_baseline_population(conn)

    pending = fi_db.fetch_next_pending_directive(conn)
    assert pending is not None
    assert pending["target_role"] == "dummy"
    assert "zero active agents" in pending["reason"]


def test_ensure_baseline_population_does_not_duplicate_when_spawn_in_flight(conn):
    """Regression test for a race caught during manual end-to-end
    verification: the Coordinator marks a spawn directive completed as
    soon as subprocess.Popen returns, before the child has actually called
    register_agent. COO must not enqueue a second spawn for the same role
    while that gap is still open."""
    directive_id = fi_db.enqueue_directive(conn, "spawn", requested_by="coo", target_role="dummy")
    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-not-yet-registered")

    assert _role_spawn_in_flight(conn, "dummy") is True

    _ensure_baseline_population(conn)

    assert fi_db.fetch_next_pending_directive(conn) is None


def test_ensure_baseline_population_does_not_duplicate_while_directive_still_pending(conn):
    """Regression test for a bug found via manual verification of Gap 3: the
    old _role_spawn_in_flight only checked coo_directives_completed, which
    is blind to a directive the Coordinator hasn't picked up yet. COO's
    ~1s cycle and the Coordinator's ~1s poll are close enough in period
    that this was routine, not rare - simulated here by enqueuing a spawn
    and calling _ensure_baseline_population again before anything completes
    it, exactly as COO's next cycle would if the Coordinator hadn't caught
    up yet."""
    fi_db.enqueue_directive(conn, "spawn", requested_by="coo", target_role="dummy")

    assert _role_spawn_in_flight(conn, "dummy") is True

    _ensure_baseline_population(conn)

    count = conn.execute("SELECT COUNT(*) AS n FROM coo_directives WHERE target_role = 'dummy'").fetchone()["n"]
    assert count == 1


def test_ensure_baseline_population_respawns_once_in_flight_agent_actually_dies(conn):
    """Once the previously in-flight agent shows up in the registry and
    then goes gone, it's no longer "in flight" - COO should treat this as
    a real death and ask for a replacement, same as the existing
    respawn-after-death behavior."""
    directive_id = fi_db.enqueue_directive(conn, "spawn", requested_by="coo", target_role="dummy")
    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-1")
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.mark_agent_gone(conn, "dummy-1")

    assert _role_spawn_in_flight(conn, "dummy") is False

    _ensure_baseline_population(conn)

    pending = fi_db.fetch_next_pending_directive(conn)
    assert pending is not None
    assert pending["target_role"] == "dummy"


def test_evaluate_agent_health_marks_stale_agent_crashed(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.record_heartbeat(conn, "dummy-1")

    _evaluate_agent_health(conn, stale_seconds=0)

    assert fi_db.get_agent(conn, "dummy-1")["status"] == "crashed"


def test_evaluate_agent_health_leaves_fresh_agent_active(conn):
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.record_heartbeat(conn, "dummy-1")

    _evaluate_agent_health(conn, stale_seconds=999)

    assert fi_db.get_agent(conn, "dummy-1")["status"] == "active"


def test_evaluate_agent_health_does_not_touch_gracefully_gone_agents(conn):
    """A clean exit already set status='gone' itself - health evaluation
    should leave that alone rather than overwriting it with 'crashed'."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.mark_agent_gone(conn, "dummy-1")

    _evaluate_agent_health(conn, stale_seconds=0)

    assert fi_db.get_agent(conn, "dummy-1")["status"] == "gone"


def test_coo_work_respawns_crashed_agent_within_same_cycle(conn):
    """Integration of Gap 3 with the existing baseline-population logic:
    a crashed agent (health evaluation runs before baseline population in
    _coo_work) should trigger a respawn in the very same cycle it was
    detected, not one cycle later."""
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.record_heartbeat(conn, "dummy-1")

    _evaluate_agent_health(conn, stale_seconds=0)
    _ensure_baseline_population(conn)

    assert fi_db.get_agent(conn, "dummy-1")["status"] == "crashed"
    pending = fi_db.fetch_next_pending_directive(conn)
    assert pending is not None
    assert pending["target_role"] == "dummy"


def test_evaluate_past_decisions_marks_established_when_agent_active(conn):
    directive_id = fi_db.enqueue_directive(conn, "spawn", requested_by="coo", target_role="dummy")
    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-1")
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)

    _evaluate_past_decisions(conn, grace_seconds=0)

    completed = fi_db.list_completed_directives(conn)
    assert completed[0]["observed_result"] == "established"


def test_evaluate_past_decisions_marks_never_registered_when_agent_absent(conn):
    """Grace period elapsed and the identity never showed up in
    agent_registry at all - the spawn succeeded at the OS level but the
    child never got as far as registering itself."""
    directive_id = fi_db.enqueue_directive(conn, "spawn", requested_by="coo", target_role="dummy")
    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-1")

    _evaluate_past_decisions(conn, grace_seconds=0)

    completed = fi_db.list_completed_directives(conn)
    assert completed[0]["observed_result"] == "never_registered"


def test_evaluate_past_decisions_marks_died_before_establishing(conn):
    directive_id = fi_db.enqueue_directive(conn, "spawn", requested_by="coo", target_role="dummy")
    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-1")
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)
    fi_db.mark_agent_gone(conn, "dummy-1")

    _evaluate_past_decisions(conn, grace_seconds=0)

    completed = fi_db.list_completed_directives(conn)
    assert completed[0]["observed_result"] == "died_before_establishing"


def test_evaluate_past_decisions_is_idempotent(conn):
    """Once a directive has an observed_result, later calls should not
    re-evaluate or overwrite it (e.g. an agent that was 'established' at
    observation time but later dies shouldn't retroactively rewrite the
    original decision's grade)."""
    directive_id = fi_db.enqueue_directive(conn, "spawn", requested_by="coo", target_role="dummy")
    fi_db.complete_directive(conn, directive_id, "success", detail="dummy-1")
    fi_db.register_agent(conn, "dummy-1", "dummy", 111)

    _evaluate_past_decisions(conn, grace_seconds=0)
    fi_db.mark_agent_gone(conn, "dummy-1")
    _evaluate_past_decisions(conn, grace_seconds=0)

    completed = fi_db.list_completed_directives(conn)
    assert completed[0]["observed_result"] == "established"


def test_coo_work_does_not_raise_and_prints_status(conn, capsys):
    _coo_work(conn)
    out = capsys.readouterr().out
    assert "[COO]" in out
    # also has the real side effect of ensuring baseline population
    assert fi_db.fetch_next_pending_directive(conn) is not None
