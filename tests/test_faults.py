"""Making things fail on purpose.

The lifecycle catalogue has said `injectable: True` about thirty-six events since
it was written, and until now nothing could inject anything. These tests are
about the half that can be checked without a live organization: what a scenario
may declare, what it is refused for, and what each fault does to a database or a
process it can reach. The other half - that a fault fires mid-run and the
organization responds - is a scenario, and lives in simulation/scenarios/.
"""

import sqlite3
import subprocess
import sys
import time

import pytest

from backend import fi_db
from simulation import faults, scenario


# --- What a scenario may declare ----------------------------------------


def test_a_scenario_without_faults_carries_an_empty_schedule():
    """Every ordinary scenario. The feature must cost nothing when unused."""
    parsed = scenario.from_dict(
        {"id": "x", "version": 1, "description": "d", "duration_seconds": 60, "lifecycle": "draft"}
    )

    assert not parsed.faults
    assert parsed.faults.record() == []


def test_faults_are_ordered_by_when_they_fire():
    schedule = faults.parse([
        {"at_seconds": 30, "action": "kill", "target": "coo-1"},
        {"at_seconds": 5, "action": "lock_database", "seconds": 2},
    ])

    assert [fault.at_seconds for fault in schedule.faults] == [5, 30]


def test_only_faults_this_code_can_cause_are_accepted():
    """The catalogue's entry rule, applied to the injector. A scenario naming a
    fault nothing can produce would pass by never running - the single most
    repeated mistake in this project."""
    with pytest.raises(faults.FaultError, match="unknown action"):
        faults.parse([{"at_seconds": 1, "action": "network_partition", "target": "coo-1"}])

    message = str(pytest.raises(
        faults.FaultError, faults.parse, [{"at_seconds": 1, "action": "explode"}]
    ).value)
    for action in faults.ACTIONS:
        assert action in message, "the refusal must name what is possible, not only what is not"


def test_a_fault_that_needs_a_target_is_refused_without_one():
    with pytest.raises(faults.FaultError, match="needs a target"):
        faults.parse([{"at_seconds": 1, "action": "kill"}])

    # A database lock has no target, and must not be made to invent one.
    assert faults.parse([{"at_seconds": 1, "action": "lock_database"}])


def test_malformed_schedules_are_refused_at_load_time(tmp_path):
    """At load rather than at the moment it was meant to fire: a fault that turns
    out to be unspellable at second 40 of a five-minute run has wasted the run."""
    with pytest.raises(faults.FaultError, match="non-numeric"):
        faults.parse([{"at_seconds": "soon", "action": "kill", "target": "coo-1"}])
    with pytest.raises(faults.FaultError, match="before the run starts"):
        faults.parse([{"at_seconds": -1, "action": "kill", "target": "coo-1"}])
    with pytest.raises(faults.FaultError, match="must be a list"):
        faults.parse({"at_seconds": 1})

    with pytest.raises(scenario.ScenarioError, match="unknown action"):
        scenario.from_dict({
            "id": "x", "version": 1, "description": "d", "duration_seconds": 60,
            "lifecycle": "draft", "faults": [{"at_seconds": 1, "action": "nope", "target": "a"}],
        })


def test_only_faults_that_are_due_fire():
    schedule = faults.parse([
        {"at_seconds": 10, "action": "kill", "target": "a-1"},
        {"at_seconds": 30, "action": "kill", "target": "b-1"},
    ])

    assert [f.target for f in schedule.due(15)] == ["a-1"]
    assert [f.target for f in schedule.due(31)] == ["a-1", "b-1"]

    schedule.faults[0].fired_at = "already"
    assert [f.target for f in schedule.due(31)] == ["b-1"], "a fired fault does not fire twice"


# --- What the faults actually do ----------------------------------------


def test_stopping_an_agent_requests_retirement(tmp_path):
    """The control case. A fault suite that only ever kills cannot show that a
    watcher tells a deliberate stop apart from a crash."""
    db_path = tmp_path / "fi.db"
    conn = fi_db.get_connection(db_path)
    fi_db.init_schema(conn)
    fi_db.register_agent(conn, "explorer-1", "explorer", 4242)
    conn.close()

    fault = faults.Fault(at_seconds=0, action="stop", target="explorer-1")
    outcome = faults.fire(fault, db_path)

    assert "requested retirement" in outcome
    conn = fi_db.get_connection(db_path)
    try:
        assert fi_db.get_agent(conn, "explorer-1")["retire_requested"]
    finally:
        conn.close()


def test_a_fault_against_a_missing_target_is_recorded_not_raised(tmp_path):
    """A target that has already died is an ordinary thing to find during a fault
    run. Ending the run on it would lose everything the run had produced."""
    db_path = tmp_path / "fi.db"
    conn = fi_db.get_connection(db_path)
    fi_db.init_schema(conn)
    conn.close()

    for action in ("kill", "stop"):
        fault = faults.Fault(at_seconds=0, action=action, target="nobody-1")
        outcome = faults.fire(fault, db_path)
        assert "nothing to" in outcome
        assert fault.fired_at is not None, "an attempt that found nothing still happened"


def test_killing_reads_the_pid_from_the_registry(tmp_path):
    """Targets are named by identity and resolved through the organization's own
    record, so a fault that cannot find its target says so rather than killing
    something else."""
    db_path = tmp_path / "fi.db"
    conn = fi_db.get_connection(db_path)
    fi_db.init_schema(conn)

    victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        fi_db.register_agent(conn, "dummy-1", "dummy", victim.pid)
        conn.close()

        outcome = faults.fire(faults.Fault(at_seconds=0, action="kill", target="dummy-1"), db_path)

        assert f"killed dummy-1 (pid {victim.pid})" == outcome
        assert victim.wait(timeout=15) != 0, "a killed process did not exit cleanly"
    finally:
        if victim.poll() is None:
            victim.kill()


def test_locking_the_database_blocks_writers(tmp_path):
    """SQLite is the only coordination channel, so this is the closest thing this
    architecture has to a network partition: every agent meets a database that
    will not take a write."""
    db_path = tmp_path / "fi.db"
    conn = fi_db.get_connection(db_path)
    fi_db.init_schema(conn)
    conn.close()

    import threading

    fault = faults.Fault(at_seconds=0, action="lock_database", seconds=1.5)
    holder = threading.Thread(target=faults.fire, args=(fault, db_path))
    holder.start()
    time.sleep(0.3)

    writer = sqlite3.connect(str(db_path), timeout=0.2)
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked|busy"):
            writer.execute("INSERT INTO agent_names (name, reserved) VALUES ('probe', 0)")
            writer.commit()
    finally:
        writer.close()
        holder.join(timeout=10)

    assert "held an exclusive database lock" in fault.outcome

    # And the lock is released, so the run continues rather than the fault being
    # a one-way door.
    after = sqlite3.connect(str(db_path), timeout=5)
    try:
        after.execute("SELECT COUNT(*) FROM agent_registry").fetchone()
    finally:
        after.close()


# --- What the manifest records ------------------------------------------


def test_the_manifest_records_faults_that_did_not_fire():
    """A run whose faults never landed proved nothing, and that has to be visible
    in the record rather than inferred from an absence."""
    schedule = faults.parse([{"at_seconds": 99, "action": "kill", "target": "coo-1"}])

    [record] = schedule.record()

    assert record["fired_at"] is None
    assert record["outcome"] is None
    assert record["action"] == "kill"
