"""Regression tests for backend/coordinator.py.

Two kinds of test here, deliberately - see the plan's explicit note that
this is the one place in the project where a real subprocess in a test is
the correct call, not a shortcut:

1. Directive-processing *logic* - mocked subprocess.Popen, fast and
   hermetic, covers the branching (spawn/retire/unknown directive type,
   unknown identity) without needing a real process.
2. A genuine end-to-end integration test that spawns a real `agents.dummy`
   subprocess through the real Coordinator, confirms it actually registers
   and heartbeats, then retires it for real and confirms clean exit. This
   is the test that actually proves the control plane works - the mocked
   tests above would pass even if process spawning were subtly broken.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from backend import fi_db
from backend.coordinator import Coordinator


@pytest.fixture
def coordinator(tmp_path):
    db_path = str(tmp_path / "fi_test.db")
    coord = Coordinator(db_path=db_path)
    yield coord
    coord.close()


def test_bootstrap_coo_launches_subprocess_directly_bypassing_directive_queue(coordinator):
    fake_process = MagicMock()
    with patch("backend.coordinator.subprocess.Popen", return_value=fake_process) as popen_mock:
        identity = coordinator.bootstrap_coo()

    assert identity.startswith("coo-")
    args, kwargs = popen_mock.call_args
    assert args[0][1:3] == ["-m", "agents.coo"]
    assert args[0][3] == identity
    assert kwargs["env"]["FI_DB_PATH"] == coordinator.db_path
    assert identity in coordinator.known_process_identities()
    # bootstrap never touches the directive queue - nothing to process
    assert fi_db.fetch_next_pending_directive(coordinator.conn) is None


def test_process_next_directive_returns_false_when_queue_empty(coordinator):
    assert coordinator.process_next_directive() is False


def test_spawn_directive_launches_subprocess_and_completes_successfully(coordinator):
    fake_process = MagicMock()
    with patch("backend.coordinator.subprocess.Popen", return_value=fake_process) as popen_mock:
        directive_id = fi_db.enqueue_directive(coordinator.conn, "spawn", "coo", target_role="dummy")
        processed = coordinator.process_next_directive()

    assert processed is True
    popen_mock.assert_called_once()
    args, kwargs = popen_mock.call_args
    assert args[0][:3] == [args[0][0], "-m", "agents.dummy"]
    assert kwargs["env"]["FI_DB_PATH"] == coordinator.db_path

    completed = fi_db.list_completed_directives(coordinator.conn)
    assert completed[0]["id"] == directive_id
    assert completed[0]["outcome"] == "success"
    assert completed[0]["detail"].startswith("dummy-")
    assert completed[0]["detail"] in coordinator.known_process_identities()


def test_spawn_directive_failure_is_recorded(coordinator):
    with patch("backend.coordinator.subprocess.Popen", side_effect=OSError("boom")):
        fi_db.enqueue_directive(coordinator.conn, "spawn", "coo", target_role="dummy")
        coordinator.process_next_directive()

    completed = fi_db.list_completed_directives(coordinator.conn)
    assert completed[0]["outcome"] == "failure"
    assert "boom" in completed[0]["detail"]


def test_retire_directive_sets_flag_and_completes_successfully(coordinator):
    fi_db.register_agent(coordinator.conn, "dummy-abc123", "dummy", 999)
    directive_id = fi_db.enqueue_directive(coordinator.conn, "retire", "coo", target_identity="dummy-abc123")

    coordinator.process_next_directive()

    assert fi_db.is_retirement_requested(coordinator.conn, "dummy-abc123") is True
    completed = fi_db.list_completed_directives(coordinator.conn)
    assert completed[0]["id"] == directive_id
    assert completed[0]["outcome"] == "success"


def test_retire_directive_for_unknown_identity_fails(coordinator):
    fi_db.enqueue_directive(coordinator.conn, "retire", "coo", target_identity="does-not-exist")
    coordinator.process_next_directive()

    completed = fi_db.list_completed_directives(coordinator.conn)
    assert completed[0]["outcome"] == "failure"
    assert "does-not-exist" in completed[0]["detail"]


def test_unknown_directive_type_fails(coordinator):
    fi_db.enqueue_directive(coordinator.conn, "self_destruct", "coo")
    coordinator.process_next_directive()

    completed = fi_db.list_completed_directives(coordinator.conn)
    assert completed[0]["outcome"] == "failure"
    assert "self_destruct" in completed[0]["detail"]


def test_multiple_directives_processed_one_per_call(coordinator):
    with patch("backend.coordinator.subprocess.Popen", return_value=MagicMock()):
        fi_db.enqueue_directive(coordinator.conn, "spawn", "coo", target_role="dummy")
        fi_db.enqueue_directive(coordinator.conn, "spawn", "coo", target_role="dummy")

        assert coordinator.process_next_directive() is True
        assert len(fi_db.list_completed_directives(coordinator.conn)) == 1

        assert coordinator.process_next_directive() is True
        assert len(fi_db.list_completed_directives(coordinator.conn)) == 2

        assert coordinator.process_next_directive() is False


# --- Real end-to-end integration test: a genuine subprocess, not a mock ---


def test_real_dummy_agent_spawn_and_graceful_retire(coordinator):
    """Spawns a real agents.dummy subprocess through the real Coordinator,
    confirms it actually registers and heartbeats (proving process spawning
    and FI_DB_PATH wiring both really work), then retires it and confirms
    it exits on its own within a timeout - not killed, not hung."""
    directive_id = fi_db.enqueue_directive(coordinator.conn, "spawn", "coo", target_role="dummy")
    coordinator.process_next_directive()

    completed = fi_db.list_completed_directives(coordinator.conn)
    spawn_result = next(d for d in completed if d["id"] == directive_id)
    assert spawn_result["outcome"] == "success"
    identity = spawn_result["detail"]

    deadline = time.time() + 10
    agent = None
    while time.time() < deadline:
        agent = fi_db.get_agent(coordinator.conn, identity)
        if agent is not None and agent["last_heartbeat_at"] is not None:
            break
        time.sleep(0.2)
    assert agent is not None, "dummy agent never registered itself"
    assert agent["status"] == "active"
    first_heartbeat = agent["last_heartbeat_at"]

    # the performance_card view (objective fields only, per the plan's
    # confirmed Executive Performance Card scope) should already reflect
    # this real running agent, not just the raw registry row
    card = {row["identity"]: row for row in fi_db.get_performance_card(coordinator.conn)}
    assert identity in card
    assert card[identity]["role"] == "dummy"
    assert card[identity]["status"] == "active"
    assert card[identity]["heartbeat_count"] >= 1

    # confirm heartbeats actually advance, not just a one-time registration write
    deadline = time.time() + 5
    advanced = False
    while time.time() < deadline:
        agent = fi_db.get_agent(coordinator.conn, identity)
        if agent["last_heartbeat_at"] != first_heartbeat:
            advanced = True
            break
        time.sleep(0.2)
    assert advanced, "dummy agent never sent a second heartbeat"

    retire_id = fi_db.enqueue_directive(coordinator.conn, "retire", "coo", target_identity=identity)
    coordinator.process_next_directive()
    retire_result = next(d for d in fi_db.list_completed_directives(coordinator.conn) if d["id"] == retire_id)
    assert retire_result["outcome"] == "success"

    deadline = time.time() + 10
    gone = False
    while time.time() < deadline:
        agent = fi_db.get_agent(coordinator.conn, identity)
        if agent["status"] == "gone":
            gone = True
            break
        time.sleep(0.2)
    assert gone, "dummy agent never marked itself gone after retirement was requested"

    process = coordinator._processes[identity]
    process.wait(timeout=5)
    assert process.returncode == 0


def test_real_coo_bootstrap_establishes_baseline_population(coordinator):
    """The full startup story, end to end with real processes: Coordinator
    bootstraps a real COO (bypassing the directive queue), the running COO
    notices no dummy exists and enqueues a spawn directive for one, and a
    polling loop (standing in for what backend/main.py will run
    continuously) picks that directive up and actually spawns a real dummy
    agent - proving addendum 6 §2's whole startup sequence works, not just
    each piece in isolation."""
    coo_identity = coordinator.bootstrap_coo()

    deadline = time.time() + 15
    dummy_identity = None
    while time.time() < deadline and dummy_identity is None:
        coordinator.process_next_directive()
        agents = fi_db.list_agents(coordinator.conn)
        dummy = next((a for a in agents if a["role"] == "dummy" and a["status"] == "active"), None)
        if dummy is not None:
            dummy_identity = dummy["identity"]
        time.sleep(0.2)

    assert dummy_identity is not None, "COO never established the baseline dummy population"

    coo_agent = fi_db.get_agent(coordinator.conn, coo_identity)
    assert coo_agent is not None
    assert coo_agent["status"] == "active"

    # cleanup: retire both real processes so the test doesn't leak them
    for identity in (dummy_identity, coo_identity):
        fi_db.enqueue_directive(coordinator.conn, "retire", "coo", target_identity=identity)
        coordinator.process_next_directive()

    deadline = time.time() + 10
    while time.time() < deadline:
        agents = {a["identity"]: a for a in fi_db.list_agents(coordinator.conn)}
        if agents[dummy_identity]["status"] == "gone" and agents[coo_identity]["status"] == "gone":
            break
        time.sleep(0.2)
    else:
        pytest.fail("dummy and/or coo did not retire cleanly within timeout")

    for identity in (dummy_identity, coo_identity):
        coordinator._processes[identity].wait(timeout=5)
