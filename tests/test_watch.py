"""The fault-tolerance network: who watches whom, and what happens when the
watched one goes quiet.

The framework this implements states its rule in two lines - NO CRITICAL FAILURE
GOES UNNOTICED, NO NOTICED FAILURE GOES OWNERLESS - and the tests here are those
two lines asked of the code rather than of the document.
"""

import subprocess
import time
from unittest.mock import MagicMock

import pytest

from agents import coo as coo_module
from backend import controller as controller_module
from backend import fi_db, watch
from backend.controller import CONTROLLER_ROLE, Controller


@pytest.fixture
def controller(tmp_path, monkeypatch):
    """A Controller against a temp database, with spawning stubbed - every test
    here is about the decision to spawn, not about the process that results."""
    spawned = []

    def fake_popen(args, **kwargs):
        spawned.append(args)
        return MagicMock(pid=4242, poll=lambda: None)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    instance = Controller(db_path=str(tmp_path / "fi.db"))
    instance.bootstrap_self()
    instance.spawned = spawned
    yield instance
    instance.close()


# --- The relationships (§3, §5) -----------------------------------------


def test_every_role_that_exists_has_a_watcher():
    """§5: no critical operational entity shall exist without an identified
    watcher. Asked of the roles the system actually has, so adding one without
    giving it a watcher fails here rather than becoming a silent hole."""
    live_roles = set(coo_module.BASELINE_ROLES) | {watch.COO_ROLE, CONTROLLER_ROLE}

    assert watch.unwatched(live_roles) == []


def test_the_controller_watches_the_coo_and_the_coo_watches_the_workforce():
    assert watch.watcher_of(watch.COO_ROLE) == CONTROLLER_ROLE
    for role in coo_module.BASELINE_ROLES:
        assert watch.watcher_of(role) == watch.COO_ROLE


def test_the_top_of_the_hierarchy_is_watched_but_not_recoverable():
    """§5 wants senior roles watched too, and they are - COO's health evaluation
    covers the Controller like anything else. What cannot be pretended is
    recovery: the Controller is the server process, so a dead one cannot restart
    itself and no in-process watcher would outlive it. The owner is named instead
    of invented."""
    assert watch.watcher_of(CONTROLLER_ROLE) == watch.COO_ROLE
    assert "human operator" in watch.recovery_owner(CONTROLLER_ROLE)
    assert watch.recovery_owner(watch.COO_ROLE) is None, "the COO's watcher can recover it itself"


def test_the_watch_loop_is_asymmetric():
    """COO watches the Controller and the Controller watches COO, which is the
    circular relationship the framework's §18 asks about. It is safe only because
    exactly one direction carries recovery authority - two watchers that could
    each restart the other would thrash, each reading the other's restart as a
    failure."""
    assert CONTROLLER_ROLE in watch.WATCHES[watch.COO_ROLE]
    assert watch.COO_ROLE in watch.WATCHES[CONTROLLER_ROLE]
    assert watch.recovery_owner(CONTROLLER_ROLE) is not None, (
        "if the Controller ever becomes recoverable from inside the system, this loop stops "
        "being asymmetric and needs an external arbiter"
    )


def test_the_role_names_agree_with_the_code_that_uses_them():
    """watch.py names the roles itself rather than importing them, because it is
    the lower layer. The duplication is checked here rather than trusted."""
    assert watch.CONTROLLER_ROLE == controller_module.CONTROLLER_ROLE
    assert watch.COO_ROLE == coo_module.ROLE
    assert coo_module.IDENTITY == f"{coo_module.ROLE}-1"


# --- Detection (§8) ------------------------------------------------------


def test_a_silent_coo_is_noticed_and_a_replacement_started(controller):
    """The hole this was built to close. Nothing watched the COO before: it is
    spawned once at startup and is deliberately not in BASELINE_POPULATION, so if
    it died the health evaluation that notices every *other* agent's silence died
    with it."""
    fi_db.register_agent(controller.conn, "coo-1", "coo", 999)
    _age_heartbeat(controller.conn, "coo-1", seconds=120)

    outcome = controller.watch_coo()

    assert outcome["action"] == "respawned"
    assert any("agents.coo" in " ".join(args) for args in controller.spawned)

    [incident] = fi_db.list_incidents(controller.conn)
    assert incident["subject_identity"] == "coo-1"
    assert incident["detected_by"] == "controller-1"
    assert incident["status"] == "open"
    assert "past the" in incident["symptom"]
    assert "crashed" in incident["diagnosis"]


def test_a_healthy_coo_is_left_alone(controller):
    fi_db.register_agent(controller.conn, "coo-1", "coo", 999)
    fi_db.record_heartbeat(controller.conn, "coo-1")

    outcome = controller.watch_coo()

    assert outcome["action"] == "none"
    assert controller.spawned == []
    assert fi_db.list_incidents(controller.conn) == []


def test_a_dormant_coo_is_a_decision_not_a_fault(controller):
    """§7: intentional inactivity must be told apart from failure before anything
    disruptive happens. Respawning a deliberately retired executive would undo a
    Controller decision, which is the exact bug dormancy was introduced to fix."""
    fi_db.register_agent(controller.conn, "coo-1", "coo", 999)
    fi_db.request_retirement(controller.conn, "coo-1")
    _age_heartbeat(controller.conn, "coo-1", seconds=120)

    outcome = controller.watch_coo()

    assert outcome["action"] == "none"
    assert "dormant" in outcome["reason"]
    assert controller.spawned == []
    assert fi_db.list_incidents(controller.conn) == []


def test_a_coo_that_never_registered_is_noticed_too(controller):
    """With no spawn in flight, an absent row means the COO is genuinely gone."""
    outcome = controller.watch_coo()

    assert outcome["action"] == "respawned"
    [incident] = fi_db.list_incidents(controller.conn)
    assert "no registry row" in incident["symptom"] or "no registry row" in incident["diagnosis"]


def test_a_spawn_still_coming_up_is_not_a_failure(controller):
    """The defect a live run found, and the reason this test exists at all.

    The first version of this watch had no notion of a spawn in flight. The poll
    loop's first tick runs microseconds after bootstrap_coo, found no registry
    row for a process that had existed for less than a millisecond, declared it
    missing and started another - **six COO processes under one permanent
    identity in under two minutes**, which is precisely the duplicate-executive
    hazard the watch was written to prevent.

    Worse, the first version of *this file* asserted that behaviour was correct:
    a test named "a COO that never registered is noticed too" passed throughout,
    because it never distinguished a COO that had never registered from one that
    had not registered *yet*."""
    controller.bootstrap_coo()
    assert controller.spawned, "the bootstrap should have started one"

    outcome = controller.watch_coo(now=time.monotonic() + controller_module.WATCH_INTERVAL_SECONDS + 1)

    assert outcome["action"] == "none"
    assert "coming up" in outcome["reason"]
    assert len(controller.spawned) == 1, "a starting COO must not be started again"
    assert fi_db.list_incidents(controller.conn) == [], "starting up is not an incident"


def test_a_spawn_that_never_lands_is_eventually_a_failure(controller):
    """The grace period is a delay, not an amnesty."""
    controller.bootstrap_coo()

    outcome = controller.watch_coo(
        now=time.monotonic() + controller_module.COO_SPAWN_GRACE_SECONDS + 1
    )

    assert outcome["action"] == "respawned"
    assert len(controller.spawned) == 2


def test_respawn_refuses_while_a_spawn_is_in_flight(controller):
    """The guard lives in respawn_coo rather than in its callers, because a guard
    in the caller is a guard the next caller does not have. The runaway came from
    a path where the incident was deduplicated and the spawn was not."""
    controller.bootstrap_coo()

    with pytest.raises(RuntimeError, match="has not reported yet"):
        controller.respawn_coo()

    assert len(controller.spawned) == 1


def test_a_registry_row_that_never_heartbeats_is_given_time(controller):
    """The cross-process half: a COO some *other* process started is still coming
    up, and this Controller has no memory of having started it."""
    fi_db.register_agent(controller.conn, "coo-1", "coo", 999)

    outcome = controller.watch_coo()

    assert outcome["action"] == "none"
    assert controller.spawned == []


def test_the_watch_rate_limits_itself(controller):
    """The poll loop ticks about once a second and silence is measured in tens of
    seconds. A registry read per tick would be work for nothing."""
    fi_db.register_agent(controller.conn, "coo-1", "coo", 999)
    fi_db.record_heartbeat(controller.conn, "coo-1")

    first = controller.watch_coo(now=1000.0)
    immediately_after = controller.watch_coo(now=1001.0)
    later = controller.watch_coo(now=1000.0 + controller_module.WATCH_INTERVAL_SECONDS + 1)

    assert first is not None
    assert immediately_after is None, "a tick later is not a new question"
    assert later is not None


# --- Recovery and its limits (§8, §11, §13) ------------------------------


def test_an_incident_closes_when_the_capability_returns(controller):
    """The other half of the lifecycle. A watcher that only ever files leaves a
    board of failures that all look permanent."""
    fi_db.register_agent(controller.conn, "coo-1", "coo", 999)
    _age_heartbeat(controller.conn, "coo-1", seconds=120)
    controller.watch_coo()

    fi_db.record_heartbeat(controller.conn, "coo-1")
    outcome = controller.watch_coo(now=time.monotonic() + 1000)

    assert outcome["action"] == "recovered"
    [incident] = fi_db.list_incidents(controller.conn)
    assert incident["status"] == "recovered"
    assert incident["resolved_at"] is not None
    assert "heartbeat resumed" in incident["action"]


def test_a_crash_loop_escalates_instead_of_respawning_forever(controller):
    """§11 and §13 together: when the watcher runs out of attempts the failure
    does not disappear, it acquires an owner and the lost capability is stated.

    Counted from the durable record rather than from memory, so a loop that
    survives a restart is still caught."""
    fi_db.register_agent(controller.conn, "coo-1", "coo", 999)

    for _ in range(controller_module.MAX_RECOVERIES + 1):
        _age_heartbeat(controller.conn, "coo-1", seconds=120)
        controller.watch_coo(now=time.monotonic() + _ * 1000)
        # Each attempt is a fresh failure: close the incident so the next pass
        # opens another, which is what a crash loop looks like.
        incident = fi_db.open_incident_for(controller.conn, "coo-1")
        if incident:
            fi_db.record_recovery(controller.conn, incident["id"])

    _age_heartbeat(controller.conn, "coo-1", seconds=120)
    outcome = controller.watch_coo(now=time.monotonic() + 99000)

    assert outcome["action"] == "escalated"
    escalated = [i for i in fi_db.list_incidents(controller.conn) if i["status"] == "escalated"]
    assert escalated, "the failure must still have an owner"
    assert escalated[0]["escalated_to"] == "human operator"
    assert "without an executive" in escalated[0]["action"]


def test_a_failed_respawn_escalates_rather_than_disappearing(controller, monkeypatch):
    fi_db.register_agent(controller.conn, "coo-1", "coo", 999)
    _age_heartbeat(controller.conn, "coo-1", seconds=120)

    def refuse(*args, **kwargs):
        raise OSError("no process for you")

    monkeypatch.setattr(subprocess, "Popen", refuse)
    outcome = controller.watch_coo()

    assert outcome["action"] == "escalated"
    [incident] = fi_db.list_incidents(controller.conn)
    assert incident["status"] == "escalated"
    assert "no process for you" in incident["action"]


# --- Split brain (§10, §17) ----------------------------------------------


def test_a_live_coo_is_never_duplicated(controller):
    """The hazard that had to be fixed before recovery could be built at all.

    `bootstrap_coo` used to spawn unconditionally. An unclean server death leaves
    the COO subprocess alive - children outlive their parent - so a restart
    produced two live processes under one permanent identity, both evaluating
    health and both filing directives, with the registry showing one pid."""
    fi_db.register_agent(controller.conn, "coo-1", "coo", 999)
    fi_db.record_heartbeat(controller.conn, "coo-1")

    with pytest.raises(RuntimeError, match="refusing to spawn a second"):
        controller.respawn_coo()

    assert controller.spawned == []


def test_bootstrap_adopts_a_surviving_coo_rather_than_failing(controller):
    """Startup must not crash because the previous COO outlived its server, and
    must not start a second one either. Adoption is the correct outcome: the
    organization has the executive it needs."""
    fi_db.register_agent(controller.conn, "coo-1", "coo", 999)
    fi_db.record_heartbeat(controller.conn, "coo-1")

    identity = controller.bootstrap_coo()

    assert identity == "coo-1"
    assert controller.spawned == [], "a live COO must not be duplicated at startup"


def test_bootstrap_starts_a_coo_when_the_previous_one_is_stale(controller):
    fi_db.register_agent(controller.conn, "coo-1", "coo", 999)
    _age_heartbeat(controller.conn, "coo-1", seconds=120)

    controller.bootstrap_coo()

    assert any("agents.coo" in " ".join(args) for args in controller.spawned)
    assert fi_db.get_agent(controller.conn, "coo-1")["process_state"] == fi_db.PROCESS_CRASHED


def test_reconciliation_reports_what_it_found(controller):
    """§10: recovery is not "restart the executable", it is restoring a coherent
    view of what is already true."""
    assert controller.reconcile_on_start() == {"coo": "absent"}

    fi_db.register_agent(controller.conn, "coo-1", "coo", 999)
    fi_db.record_heartbeat(controller.conn, "coo-1")
    assert controller.reconcile_on_start()["coo"] == "adopted"

    _age_heartbeat(controller.conn, "coo-1", seconds=120)
    assert controller.reconcile_on_start()["coo"] == "stale"

    fi_db.request_retirement(controller.conn, "coo-1")
    assert controller.reconcile_on_start()["coo"] == "dormant"


def _age_heartbeat(conn, identity, seconds):
    """Push a heartbeat into the past. Writing the column directly is the only way
    to simulate silence without waiting out the real threshold."""
    from datetime import datetime, timedelta, timezone

    stale = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    conn.execute(
        "UPDATE agent_registry SET last_heartbeat_at = ?, spawned_at = ? WHERE identity = ?",
        (stale, stale, identity),
    )


# --- The COO's half of the network ---------------------------------------


def test_the_coo_files_an_incident_when_an_agent_goes_silent(conn):
    """COO's health evaluation is the oldest fault-tolerance mechanism here. What
    is new is that a detection becomes a record, not only a state change on a
    registry row: 'crashed' says what is true now, the incident says what
    happened, who noticed, and whether it came back."""
    fi_db.register_agent(conn, "explorer-1", "explorer", 111)
    _age_heartbeat(conn, "explorer-1", seconds=120)

    coo_module._evaluate_agent_health(conn)

    assert fi_db.get_agent(conn, "explorer-1")["process_state"] == fi_db.PROCESS_CRASHED
    [incident] = fi_db.list_incidents(conn)
    assert incident["subject_identity"] == "explorer-1"
    assert incident["detected_by"] == "coo-1"
    assert incident["status"] == "open"


def test_the_coo_closes_its_incident_when_the_agent_returns(conn):
    fi_db.register_agent(conn, "explorer-1", "explorer", 111)
    _age_heartbeat(conn, "explorer-1", seconds=120)
    coo_module._evaluate_agent_health(conn)

    # The respawn lands and the agent starts signalling again.
    fi_db.record_heartbeat(conn, "explorer-1")
    coo_module._evaluate_agent_health(conn)

    [incident] = fi_db.list_incidents(conn)
    assert incident["status"] == "recovered"
    assert "heartbeat resumed" in incident["action"]


def test_a_silence_files_one_incident_not_one_per_cycle(conn):
    """A watcher polls, and the failure it is watching does not go away between
    ticks. Without the guard a single silence becomes a hundred rows and buries
    the one that mattered."""
    fi_db.register_agent(conn, "explorer-1", "explorer", 111)
    _age_heartbeat(conn, "explorer-1", seconds=120)

    for _ in range(5):
        coo_module._evaluate_agent_health(conn)

    assert len(fi_db.list_incidents(conn)) == 1


def test_watchers_do_not_close_each_others_incidents(conn):
    """§16: monitoring follows assigned responsibility. Closing another watcher's
    record would be claiming an observation this agent never made."""
    fi_db.register_agent(conn, "coo-1", "coo", 999)
    fi_db.record_heartbeat(conn, "coo-1")
    fi_db.open_incident(
        conn,
        subject_identity="coo-1",
        subject_role="coo",
        detected_by="controller-1",
        symptom="silence",
    )

    coo_module._evaluate_agent_health(conn)

    [incident] = fi_db.list_incidents(conn)
    assert incident["status"] == "open", "the Controller's incident is the Controller's to close"
