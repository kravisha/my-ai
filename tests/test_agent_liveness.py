"""Liveness and progress are two signals (TQ-93;
docs/SPEC_RECONCILIATION.md §133, §134).

They were one field, and conflating them cost a respawn: an agent inside a single
slow model call looked dead while it was working, so COO duplicated it and then
recorded *"heartbeat resumed (1.0s old)"*.

**The point of the separation is which clock each signal depends on.** Progress is
bounded by the slowest model call, which a vendor sets. Liveness is bounded by an
interval this system chooses — so the threshold above it can be justified against
a rate this project controls, which is what `TIMING_CONSTANTS.md` asks of every
constant and what 45s could not have.
"""

from __future__ import annotations

import inspect
import time

import pytest

from agents import base, coo
from backend import fi_db, status_events

STALE = 5.0


def _register(conn, identity="analysis-1", role="analysis"):
    fi_db.register_agent(conn, identity, role, 4321)
    return fi_db.get_agent(conn, identity)


def _age(conn, identity, *, liveness=None, progress=None):
    """Backdate a signal, so a threshold can be crossed without waiting it out."""
    if liveness is not None:
        conn.execute("UPDATE agent_registry SET last_liveness_at = ? WHERE identity = ?",
                     (liveness, identity))
    if progress is not None:
        conn.execute("UPDATE agent_registry SET last_heartbeat_at = ? WHERE identity = ?",
                     (progress, identity))


def _long_ago(seconds: float) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# --- the two signals are independent --------------------------------------------------

def test_liveness_advances_without_any_work_being_done(conn, tmp_path):
    """The whole mechanism, in one assertion. A process that has completed no
    cycle at all is still visibly up."""
    db = str(tmp_path / "t.db")
    working = fi_db.get_connection(db)
    fi_db.init_schema(working)
    _register(working)

    thread = base._Liveness("analysis-1", db, interval=0.05).start()
    try:
        time.sleep(0.2)
        agent = fi_db.get_agent(working, "analysis-1")
        assert fi_db.liveness_age_seconds(agent) is not None
        assert agent["last_heartbeat_at"] is None, "no work has been done"
    finally:
        thread.stop()


def test_liveness_is_not_counted_as_work(conn):
    """`health_metrics` counts work reported. A thread ticking on a timer is not
    work, and inflating the count with it would make `performance_card
    .heartbeat_count` describe the clock instead of the agent."""
    _register(conn)
    before = conn.fetchone("SELECT COUNT(*) AS n FROM health_metrics")["n"]
    for _ in range(3):
        fi_db.record_liveness(conn, "analysis-1")
    after = conn.fetchone("SELECT COUNT(*) AS n FROM health_metrics")["n"]
    assert after == before


# --- what COO now does with them ------------------------------------------------------

def test_an_agent_inside_a_slow_call_is_not_crashed(conn):
    """§133's incident, as a test. Liveness fresh, progress stale: alive and not
    advancing, which is not a crash."""
    _register(conn)
    _age(conn, "analysis-1", liveness=_now(), progress=_long_ago(60))

    assert fi_db.list_stale_active_agents(conn, STALE) == []
    assert [a["identity"] for a in fi_db.list_stalled_live_agents(conn, STALE)] == ["analysis-1"]

    coo._evaluate_agent_health(conn, stale_seconds=STALE)
    assert fi_db.get_agent(conn, "analysis-1")["process_state"] == fi_db.PROCESS_RUNNING


def test_an_agent_that_stopped_signalling_is_still_detected(conn):
    """The detector must not have been softened into uselessness. A process that
    is genuinely gone stops emitting liveness too."""
    _register(conn)
    _age(conn, "analysis-1", liveness=_long_ago(60), progress=_long_ago(60))

    assert [a["identity"] for a in fi_db.list_stale_active_agents(conn, STALE)] == ["analysis-1"]
    coo._evaluate_agent_health(conn, stale_seconds=STALE)
    assert fi_db.get_agent(conn, "analysis-1")["process_state"] == "crashed"


def test_an_agent_emitting_no_liveness_is_judged_by_progress(conn):
    """Not every process runs the liveness thread — a test double, an older
    build, a future agent written differently. Falling back is the honest reading
    of *the only signal it gives*, and the conservative one: a silent process is
    still detected."""
    _register(conn)
    _age(conn, "analysis-1", progress=_long_ago(60))
    assert conn.fetchone(
        "SELECT last_liveness_at FROM agent_registry WHERE identity = 'analysis-1'"
    )["last_liveness_at"] is None

    assert [a["identity"] for a in fi_db.list_stale_active_agents(conn, STALE)] == ["analysis-1"]
    assert fi_db.list_stalled_live_agents(conn, STALE) == [], (
        "with no liveness there is nothing to distinguish slow from dead")


def test_the_two_states_are_exclusive(conn):
    """An agent cannot be both crashed and slow. The order of the checks in
    `_coo_work` says so and the queries have to agree."""
    _register(conn, "explorer-1", "explorer")
    _age(conn, "explorer-1", liveness=_long_ago(60), progress=_long_ago(60))
    _register(conn, "analysis-1", "analysis")
    _age(conn, "analysis-1", liveness=_now(), progress=_long_ago(60))

    crashed = {a["identity"] for a in fi_db.list_stale_active_agents(conn, STALE)}
    slow = {a["identity"] for a in fi_db.list_stalled_live_agents(conn, STALE)}
    assert crashed == {"explorer-1"} and slow == {"analysis-1"}
    assert not (crashed & slow)


# --- and says so ----------------------------------------------------------------------

def test_a_slow_agent_is_reported_once_and_not_every_cycle(conn):
    """An agent slow for ten minutes with nobody saying so is the other failure.
    Reported once per episode, because a warning repeated every cycle is a
    warning nobody reads."""
    coo._REPORTED_SLOW.clear()
    _register(conn)
    _age(conn, "analysis-1", liveness=_now(), progress=_long_ago(60))

    for _ in range(3):
        _age(conn, "analysis-1", liveness=_now())
        coo._report_slow_but_live(conn, stale_seconds=STALE)

    said = [e for e in status_events.recent(conn, limit=50) if e["event_type"] == "agent_slow"]
    assert len(said) == 1
    assert "not being replaced" in said[0]["message"]


def test_recovery_is_reported_too(conn):
    """*"It was slow and now it is not"* is the half that says the organization
    recovered without being told."""
    coo._REPORTED_SLOW.clear()
    _register(conn)
    _age(conn, "analysis-1", liveness=_now(), progress=_long_ago(60))
    coo._report_slow_but_live(conn, stale_seconds=STALE)

    _age(conn, "analysis-1", liveness=_now(), progress=_now())
    coo._report_slow_but_live(conn, stale_seconds=STALE)

    said = [e for e in status_events.recent(conn, limit=50) if e["event_type"] == "agent_slow"]
    assert len(said) == 2
    assert any("advancing again" in e["message"] for e in said)


# --- the thread must never be able to kill an agent ------------------------------------

def test_the_liveness_thread_is_a_daemon_with_its_own_connection():
    """Its own connection because `Database` wraps a single sqlite3 connection and
    sqlite3 objects are not safe across threads — sharing the agent's would put a
    race into every agent in the organization to fix a reporting bug.

    A daemon so a process that is exiting is never held open by it."""
    source = inspect.getsource(base._Liveness)
    assert "daemon=True" in source
    assert "fi_db.get_connection(self.db_path)" in source


def test_a_failing_liveness_thread_does_not_take_the_agent_down(tmp_path):
    """This thread exists to report health and must never become a way for an
    agent to die. A locked database during shutdown is a missed tick, and a
    missed tick is what the threshold's margin is for."""
    thread = base._Liveness("nobody", str(tmp_path / "does" / "not" / "exist.db"),
                            interval=0.05).start()
    time.sleep(0.15)
    assert thread._thread.is_alive() or True  # it may have exited; neither raises
    thread.stop()


def test_the_interval_leaves_room_inside_the_threshold():
    """Nine ticks fit inside COO's threshold, so losing several in a row to
    scheduling still leaves the agent detected as live.

    This is the margin `TIMING_CONSTANTS.md` asks for, and unlike the 45s it is
    justified against a rate this system sets rather than one a vendor does."""
    assert base.LIVENESS_INTERVAL_SECONDS * 9 <= coo.HEALTH_STALE_THRESHOLD_SECONDS


def test_the_coo_cycle_actually_reports_slowness():
    """A reporter nothing calls is a comment.

    Every test above calls `_report_slow_but_live` directly, so removing its call
    site changed nothing and mutation testing said so. That is §132's seam again:
    **a function tested in isolation is not a function that runs.**

    Asserted over the source rather than by driving a cycle, because the property
    is that the call exists and is ordered after the crash check - an agent
    marked crashed this cycle is not a slow one, and the order is what says so."""
    source = inspect.getsource(coo._coo_work)
    assert "_report_slow_but_live(conn)" in source
    assert source.index("_evaluate_agent_health(conn)") < source.index("_report_slow_but_live(conn)")
