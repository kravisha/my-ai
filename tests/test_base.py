"""Unit tests for agents/base.py's shared AgentProcess contract - just the
work_fn exception-containment behavior added for Phase C (see agents/
base.py's run_agent docstring). The rest of run_agent (register -> heartbeat
-> retire) is already exercised indirectly by test_controller.py's real-
subprocess tests and test_coo.py."""

import agents.base
from agents.base import run_agent
from backend import fi_db


def test_work_fn_exception_does_not_crash_the_loop(tmp_path, monkeypatch):
    """Before Phase C, no agent made a real network call, so a work_fn
    exception propagating and killing the process (mislabeled 'gone'
    instead of 'crashed') never mattered in practice. Explorer/Speculator/
    Analysis are the first to make real calls - this is the regression
    test for the fix."""
    monkeypatch.setattr(agents.base.time, "sleep", lambda seconds: None)
    db_path = str(tmp_path / "fi_test.db")
    conn = fi_db.get_connection(db_path)
    fi_db.init_schema(conn)

    calls = []

    def flaky_work_fn(work_conn):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("boom")
        fi_db.request_retirement(work_conn, "flaky-1")

    run_agent(identity="flaky-1", role="dummy", work_fn=flaky_work_fn, db_path=db_path)

    # the exception on cycle 1 didn't kill the loop - cycle 2 ran and
    # requested its own retirement, which is why run_agent returned at all
    assert len(calls) == 2

    agent = fi_db.get_agent(conn, "flaky-1")
    # the loop was ended by a retirement request, so the agent is dormant
    # (the Controller's decision) with a stopped process (its own report)
    assert agent["lifecycle_state"] == fi_db.LIFECYCLE_DORMANT
    assert agent["process_state"] == fi_db.PROCESS_STOPPED
    assert agent["last_heartbeat_at"] is not None
    conn.close()
