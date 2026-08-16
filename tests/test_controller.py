"""Regression tests for backend/controller.py.

Two kinds of test here, deliberately - see the plan's explicit note that
this is the one place in the project where a real subprocess in a test is
the correct call, not a shortcut:

1. Directive-processing *logic* - mocked subprocess.Popen, fast and
   hermetic, covers the branching (spawn/retire/unknown directive type,
   unknown identity) without needing a real process.
2. A genuine end-to-end integration test that spawns a real `agents.dummy`
   subprocess through the real Controller, confirms it actually registers
   and heartbeats, then retires it for real and confirms clean exit. This
   is the test that actually proves the control plane works - the mocked
   tests above would pass even if process spawning were subtly broken.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from backend import fi_db
from backend.controller import Controller


@pytest.fixture
def controller(tmp_path):
    db_path = str(tmp_path / "fi_test.db")
    coord = Controller(db_path=db_path)
    yield coord
    coord.close()


def test_bootstrap_coo_launches_subprocess_directly_bypassing_directive_queue(controller):
    fake_process = MagicMock()
    with patch("backend.controller.subprocess.Popen", return_value=fake_process) as popen_mock:
        identity = controller.bootstrap_coo()

    assert identity.startswith("coo-")
    args, kwargs = popen_mock.call_args
    assert args[0][1:3] == ["-m", "agents.coo"]
    assert args[0][3] == identity
    assert kwargs["env"]["FI_DB_PATH"] == controller.db_path
    assert identity in controller.known_process_identities()
    # bootstrap never touches the directive queue - nothing to process
    assert fi_db.fetch_next_pending_directive(controller.conn) is None


def test_process_next_directive_returns_false_when_queue_empty(controller):
    assert controller.process_next_directive() is False


def test_spawn_directive_launches_subprocess_and_completes_successfully(controller):
    fake_process = MagicMock()
    with patch("backend.controller.subprocess.Popen", return_value=fake_process) as popen_mock:
        directive_id = fi_db.enqueue_directive(controller.conn, "spawn", "coo", target_role="dummy")
        processed = controller.process_next_directive()

    assert processed is True
    popen_mock.assert_called_once()
    args, kwargs = popen_mock.call_args
    assert args[0][:3] == [args[0][0], "-m", "agents.dummy"]
    assert kwargs["env"]["FI_DB_PATH"] == controller.db_path

    completed = fi_db.list_completed_directives(controller.conn)
    assert completed[0]["id"] == directive_id
    assert completed[0]["outcome"] == "success"
    assert completed[0]["detail"].startswith("dummy-")
    assert completed[0]["detail"] in controller.known_process_identities()


def test_spawn_directive_failure_is_recorded(controller):
    with patch("backend.controller.subprocess.Popen", side_effect=OSError("boom")):
        fi_db.enqueue_directive(controller.conn, "spawn", "coo", target_role="dummy")
        controller.process_next_directive()

    completed = fi_db.list_completed_directives(controller.conn)
    assert completed[0]["outcome"] == "failure"
    assert "boom" in completed[0]["detail"]


def test_retire_directive_sets_flag_and_completes_successfully(controller):
    fi_db.register_agent(controller.conn, "dummy-abc123", "dummy", 999)
    directive_id = fi_db.enqueue_directive(controller.conn, "retire", "coo", target_identity="dummy-abc123")

    controller.process_next_directive()

    assert fi_db.is_retirement_requested(controller.conn, "dummy-abc123") is True
    completed = fi_db.list_completed_directives(controller.conn)
    assert completed[0]["id"] == directive_id
    assert completed[0]["outcome"] == "success"


def test_retire_directive_for_unknown_identity_fails(controller):
    fi_db.enqueue_directive(controller.conn, "retire", "coo", target_identity="does-not-exist")
    controller.process_next_directive()

    completed = fi_db.list_completed_directives(controller.conn)
    assert completed[0]["outcome"] == "failure"
    assert "does-not-exist" in completed[0]["detail"]


def test_unknown_directive_type_fails(controller):
    fi_db.enqueue_directive(controller.conn, "self_destruct", "coo")
    controller.process_next_directive()

    completed = fi_db.list_completed_directives(controller.conn)
    assert completed[0]["outcome"] == "failure"
    assert "self_destruct" in completed[0]["detail"]


def test_multiple_directives_processed_one_per_call(controller):
    with patch("backend.controller.subprocess.Popen", return_value=MagicMock()):
        fi_db.enqueue_directive(controller.conn, "spawn", "coo", target_role="dummy")
        fi_db.enqueue_directive(controller.conn, "spawn", "coo", target_role="dummy")

        assert controller.process_next_directive() is True
        assert len(fi_db.list_completed_directives(controller.conn)) == 1

        assert controller.process_next_directive() is True
        assert len(fi_db.list_completed_directives(controller.conn)) == 2

        assert controller.process_next_directive() is False


# --- Real end-to-end integration test: a genuine subprocess, not a mock ---


def test_real_dummy_agent_spawn_and_graceful_retire(controller):
    """Spawns a real agents.dummy subprocess through the real Controller,
    confirms it actually registers and heartbeats (proving process spawning
    and FI_DB_PATH wiring both really work), then retires it and confirms
    it exits on its own within a timeout - not killed, not hung."""
    directive_id = fi_db.enqueue_directive(controller.conn, "spawn", "coo", target_role="dummy")
    controller.process_next_directive()

    completed = fi_db.list_completed_directives(controller.conn)
    spawn_result = next(d for d in completed if d["id"] == directive_id)
    assert spawn_result["outcome"] == "success"
    identity = spawn_result["detail"]

    deadline = time.time() + 10
    agent = None
    while time.time() < deadline:
        agent = fi_db.get_agent(controller.conn, identity)
        if agent is not None and agent["last_heartbeat_at"] is not None:
            break
        time.sleep(0.2)
    assert agent is not None, "dummy agent never registered itself"
    assert agent["status"] == "active"
    first_heartbeat = agent["last_heartbeat_at"]

    # the performance_card view (objective fields only, per the plan's
    # confirmed Executive Performance Card scope) should already reflect
    # this real running agent, not just the raw registry row
    card = {row["identity"]: row for row in fi_db.get_performance_card(controller.conn)}
    assert identity in card
    assert card[identity]["role"] == "dummy"
    assert card[identity]["status"] == "active"
    assert card[identity]["heartbeat_count"] >= 1

    # confirm heartbeats actually advance, not just a one-time registration write
    deadline = time.time() + 5
    advanced = False
    while time.time() < deadline:
        agent = fi_db.get_agent(controller.conn, identity)
        if agent["last_heartbeat_at"] != first_heartbeat:
            advanced = True
            break
        time.sleep(0.2)
    assert advanced, "dummy agent never sent a second heartbeat"

    retire_id = fi_db.enqueue_directive(controller.conn, "retire", "coo", target_identity=identity)
    controller.process_next_directive()
    retire_result = next(d for d in fi_db.list_completed_directives(controller.conn) if d["id"] == retire_id)
    assert retire_result["outcome"] == "success"

    deadline = time.time() + 10
    retired = False
    while time.time() < deadline:
        agent = fi_db.get_agent(controller.conn, identity)
        if agent["process_state"] == fi_db.PROCESS_STOPPED:
            retired = True
            break
        time.sleep(0.2)
    assert retired, "dummy agent never stopped its process after retirement was requested"

    # retirement is non-destructive: the agent is dormant, not deleted, and
    # its identity and name are preserved for a later resume
    agent = fi_db.get_agent(controller.conn, identity)
    assert agent["lifecycle_state"] == fi_db.LIFECYCLE_DORMANT
    assert fi_db.get_agent_name(controller.conn, identity) is not None

    process = controller._processes[identity]
    process.wait(timeout=5)
    assert process.returncode == 0


def test_real_coo_bootstrap_establishes_baseline_population(controller, monkeypatch):
    """The full startup story, end to end with real processes: Controller
    bootstraps a real COO (bypassing the directive queue), the running COO
    notices no dummy exists and enqueues a spawn directive for one, and a
    polling loop (standing in for what backend/main.py will run
    continuously) picks that directive up and actually spawns a real dummy
    agent - proving addendum 6 §2's whole startup sequence works, not just
    each piece in isolation.

    COO's BASELINE_ROLES now also includes explorer/speculator/analysis
    (Phase C) - this test only asserts on dummy specifically (unchanged,
    representative proof baseline population works), but bootstrapping COO
    for real now also spawns those three as a side effect. Speculator's
    synthetic stream can cross its confidence threshold within a few
    cycles regardless of any forced anomaly, which would hand Analysis a
    real report to reason about - a fake API key here (not this machine's
    real one, which conftest.py's setdefault only supplies if none exists)
    keeps this Phase A/B-era test keyless: any such call fails fast and
    cleanly (caught by explorer.py's/analysis.py's own try/except), rather
    than silently making a real, paid network call as an unintended side
    effect of a later increment's larger BASELINE_ROLES."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    coo_identity = controller.bootstrap_coo()

    deadline = time.time() + 15
    dummy_identity = None
    while time.time() < deadline and dummy_identity is None:
        controller.process_next_directive()
        agents = fi_db.list_agents(controller.conn)
        dummy = next((a for a in agents if a["role"] == "dummy" and a["status"] == "active"), None)
        if dummy is not None:
            dummy_identity = dummy["identity"]
        time.sleep(0.2)

    assert dummy_identity is not None, "COO never established the baseline dummy population"

    coo_agent = fi_db.get_agent(controller.conn, coo_identity)
    assert coo_agent is not None
    assert coo_agent["status"] == "active"

    # cleanup: retire every real process this test spawned. BASELINE_ROLES
    # now has 4 roles, not just dummy, so the wait loop above may have left
    # some of their spawn directives still pending when it exited (it only
    # waits for dummy). Drain those FIRST, before deciding what to retire -
    # otherwise a spawn directive processed *during* cleanup could hand out
    # a real subprocess identity that never makes it into the retire list.
    while controller.process_next_directive():
        pass

    # known_process_identities() (populated the instant subprocess.Popen
    # returns) is the source of truth for what's actually running now that
    # the queue above is fully drained - not agent_registry, which could
    # still be missing a just-spawned identity's registration write for a
    # brief window (real registration takes well under 1s in practice).
    # Wait for all of them to actually register before deciding who to
    # retire - an identity Popen'd but not yet registered would fail
    # _handle_retire's unknown-identity check and leak instead.
    registration_deadline = time.time() + 5
    while time.time() < registration_deadline:
        if all(fi_db.get_agent(controller.conn, identity) is not None for identity in controller.known_process_identities()):
            break
        time.sleep(0.2)
    to_retire = list(controller.known_process_identities())
    for identity in to_retire:
        fi_db.enqueue_directive(controller.conn, "retire", "coo", target_identity=identity)
    while controller.process_next_directive():
        pass

    deadline = time.time() + 10
    while time.time() < deadline:
        agents = {a["identity"]: a for a in fi_db.list_agents(controller.conn)}
        if all(agents[identity]["process_state"] == fi_db.PROCESS_STOPPED for identity in to_retire):
            break
        time.sleep(0.2)
    else:
        pytest.fail("not all spawned agents retired cleanly within timeout")

    for identity in to_retire:
        controller._processes[identity].wait(timeout=5)


# --- Controller as an agent in its own right (Pre-Alpha step 2) ---


def test_controller_is_never_in_baseline_roles():
    """THE critical invariant of Controller-as-agent: the Controller *is*
    the running server, not a spawned subprocess. If "controller" ever
    appeared in BASELINE_ROLES, COO would notice it "missing" and ask the
    Controller to Popen an agents/controller.py that deliberately does not
    exist - failing every cycle forever."""
    from agents.coo import BASELINE_ROLES
    from backend.controller import CONTROLLER_ROLE

    assert CONTROLLER_ROLE not in BASELINE_ROLES


def test_bootstrap_self_registers_controller_as_an_agent(controller):
    identity = controller.bootstrap_self()

    assert identity == "controller-1"
    agent = fi_db.get_agent(controller.conn, identity)
    assert agent is not None
    assert agent["role"] == "controller"
    assert agent["status"] == "active"
    # heartbeat recorded immediately, so a COO health check running between
    # registration and the first poll tick never sees it as stale
    assert agent["last_heartbeat_at"] is not None


def test_bootstrap_self_gets_a_name_like_any_other_agent(controller):
    identity = controller.bootstrap_self()
    assert fi_db.get_agent_name(controller.conn, identity) is not None


def test_bootstrap_self_is_idempotent_across_a_server_restart(controller):
    """A server restart re-registers the same permanent identity under a new
    pid - the same ON CONFLICT path a subprocess agent's respawn takes."""
    identity = controller.bootstrap_self()
    name_before = fi_db.get_agent_name(controller.conn, identity)

    controller.bootstrap_self()

    agents = [a for a in fi_db.list_agents(controller.conn) if a["role"] == "controller"]
    assert len(agents) == 1
    assert fi_db.get_agent_name(controller.conn, identity) == name_before


def test_shutdown_self_stops_process_without_retiring_the_controller(controller):
    """A clean server shutdown must read as a clean process stop, not a
    crash - and crucially not as a retirement. The Controller stays
    organizationally in service so restarting the server brings it straight
    back rather than needing an explicit resume."""
    identity = controller.bootstrap_self()
    controller.shutdown_self()

    agent = fi_db.get_agent(controller.conn, identity)
    assert agent["process_state"] == fi_db.PROCESS_STOPPED
    assert agent["lifecycle_state"] == fi_db.LIFECYCLE_ACTIVE


def test_record_self_heartbeat_advances_the_heartbeat(controller):
    identity = controller.bootstrap_self()
    before = fi_db.get_agent(controller.conn, identity)["last_heartbeat_at"]

    time.sleep(0.01)
    controller.record_self_heartbeat()

    assert fi_db.get_agent(controller.conn, identity)["last_heartbeat_at"] > before


def test_controller_appears_on_the_performance_card(controller):
    """Controller is a first-class agent, so it should show up in the same
    organizational view as everyone else - not be invisible infrastructure."""
    identity = controller.bootstrap_self()
    card = {row["identity"]: row for row in fi_db.get_performance_card(controller.conn)}
    assert identity in card
    assert card[identity]["role"] == "controller"
