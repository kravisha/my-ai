"""Unit tests for agents/speculator.py - normalization, confidence-
threshold gating, and cursor-based dedup. No LLM call in this agent
(addendum_7 §3), so no mocking needed here - just a fake provider with
canned posts for deterministic control over what "recent" returns. The one
real-subprocess test at the bottom needs no @pytest.mark.real_llm marker
for the same reason - it makes no network call, just proves the process/
provider/DB mechanics actually work, matching test_coordinator.py's
real-subprocess-proves-the-mechanics pattern."""

import os
import subprocess
import sys
import time

import pytest

from agents.speculator import _speculator_work
from backend import fi_db
from backend.coordinator import PROJECT_ROOT
from providers.social_data import SocialPost


class FakeProvider:
    def __init__(self, batches: list[list[SocialPost]]):
        self._batches = list(batches)

    def fetch_recent(self, security, since=None):
        if not self._batches:
            return []
        return self._batches.pop(0)


def post(text, confidence, posted_at="2026-01-01T00:00:05+00:00", security="SYN1"):
    return SocialPost(source="reddit", author="u1", posted_at=posted_at, text=text, security=security, engagement_score=confidence)


@pytest.fixture
def conn():
    connection = fi_db.get_connection(":memory:")
    fi_db.init_schema(connection)
    yield connection
    connection.close()


def test_speculator_work_records_evidence_for_every_new_post(conn):
    provider = FakeProvider([[post("low signal chatter", 0.2), post("another low one", 0.3)]])
    cursor_state = {}

    _speculator_work(conn, "speculator-1", "2026-01-01T00:00:00+00:00", provider, cursor_state)

    items = fi_db.list_evidence_items(conn, [1, 2])
    assert len(items) == 2
    assert items[0]["producer_identity"] == "speculator-1"
    assert items[0]["evidence_type"] == "social"


def test_speculator_work_no_report_below_threshold(conn):
    provider = FakeProvider([[post("mild chatter", 0.3)]])
    _speculator_work(conn, "speculator-1", "2026-01-01T00:00:00+00:00", provider, {})
    assert fi_db.fetch_next_pending_report(conn) is None


def test_speculator_work_files_report_when_confidence_clears_threshold(conn):
    provider = FakeProvider([[post("large block trade just printed", 0.75)]])
    _speculator_work(conn, "speculator-1", "2026-01-01T00:00:00+00:00", provider, {})

    report = fi_db.fetch_next_pending_report(conn)
    assert report is not None
    assert report["report_type"] == "speculator"
    assert report["detector_event_id"] is None
    import json
    assert json.loads(report["evidence_ids"]) == [1]


def test_speculator_work_no_posts_is_a_noop(conn):
    provider = FakeProvider([[]])
    _speculator_work(conn, "speculator-1", "2026-01-01T00:00:00+00:00", provider, {})
    assert fi_db.list_evidence_items(conn, [1]) == []
    assert fi_db.fetch_next_pending_report(conn) is None


def test_speculator_work_cursor_advances_across_calls(conn):
    provider = FakeProvider([
        [post("first", 0.2, posted_at="2026-01-01T00:00:05+00:00")],
        [post("second", 0.2, posted_at="2026-01-01T00:00:10+00:00")],
    ])
    cursor_state = {}

    _speculator_work(conn, "speculator-1", "2026-01-01T00:00:00+00:00", provider, cursor_state)
    assert cursor_state["since"] == "2026-01-01T00:00:05+00:00"

    _speculator_work(conn, "speculator-1", "2026-01-01T00:00:00+00:00", provider, cursor_state)
    assert cursor_state["since"] == "2026-01-01T00:00:10+00:00"


def test_speculator_work_skips_new_report_while_one_still_pending(conn):
    """Dedup guard, same shape as Explorer's - a report from this producer+
    security still unconsumed should block filing another one."""
    provider = FakeProvider([
        [post("first big signal", 0.8)],
        [post("second big signal", 0.9)],
    ])
    cursor_state = {}

    _speculator_work(conn, "speculator-1", "2026-01-01T00:00:00+00:00", provider, cursor_state)
    first_report = fi_db.fetch_next_pending_report(conn)
    assert first_report is not None

    _speculator_work(conn, "speculator-1", "2026-01-01T00:00:00+00:00", provider, cursor_state)
    # still only the first report pending - no duplicate filed
    still_pending = fi_db.fetch_next_pending_report(conn)
    assert still_pending["id"] == first_report["id"]

    # but the second batch's evidence was still recorded
    assert fi_db.list_evidence_items(conn, [1, 2])[1]["content"] == "second big signal"


# --- real-subprocess integration test (no LLM involved, no marker needed) ---


def test_real_speculator_agent_spawns_and_stays_healthy(tmp_path):
    """Spawns a real agents.speculator subprocess and confirms it
    registers, stays active across multiple heartbeats, and doesn't crash -
    proving subprocess+provider+DB mechanics work end to end. Doesn't
    assert a report gets filed: the synthetic stream's post generation is
    randomized (see providers/social_data.py), so a real run could
    legitimately produce zero qualifying posts in a short window - that's
    already covered deterministically by the mocked unit tests above."""
    db_path = str(tmp_path / "fi_test.db")
    conn = fi_db.get_connection(db_path)
    fi_db.init_schema(conn)

    env = {**os.environ, "FI_DB_PATH": db_path, "FI_DISCOVERY_SECURITY": "SYN1"}
    process = subprocess.Popen([sys.executable, "-m", "agents.speculator", "speculator-1"], cwd=PROJECT_ROOT, env=env)
    try:
        deadline = time.time() + 15
        agent = None
        while time.time() < deadline:
            agent = fi_db.get_agent(conn, "speculator-1")
            if agent is not None and agent["last_heartbeat_at"] is not None:
                break
            time.sleep(0.3)
        assert agent is not None and agent["status"] == "active", "speculator never registered and heartbeat"

        time.sleep(3)  # a few more cycles - give the random stream a chance to produce something

        agent = fi_db.get_agent(conn, "speculator-1")
        assert agent["status"] == "active", "speculator crashed or exited unexpectedly"
    finally:
        fi_db.request_retirement(conn, "speculator-1")
        process.wait(timeout=10)
        conn.close()
