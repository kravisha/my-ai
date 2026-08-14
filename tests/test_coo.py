"""Unit tests for agents/coo.py's decision logic - pure DB logic, no real
process needed here (the real bootstrap->baseline flow is covered as an
integration test in test_coordinator.py alongside the rest of the genuine
subprocess tests)."""

import pytest

from agents.coo import BASELINE_ROLES, _coo_work, _ensure_baseline_population, _role_spawn_in_flight
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


def test_coo_work_does_not_raise_and_prints_status(conn, capsys):
    _coo_work(conn)
    out = capsys.readouterr().out
    assert "[COO]" in out
    # also has the real side effect of ensuring baseline population
    assert fi_db.fetch_next_pending_directive(conn) is not None
