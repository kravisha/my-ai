"""Unit tests for agents/speculator.py - normalization, confidence-
threshold gating, and cursor-based dedup. No LLM call in this agent
(addendum_7 §3), so no mocking needed here - just a fake provider with
canned posts for deterministic control over what "recent" returns. The one
real-subprocess test at the bottom needs no @pytest.mark.real_llm marker
for the same reason - it makes no network call, just proves the process/
provider/DB mechanics actually work, matching test_controller.py's
real-subprocess-proves-the-mechanics pattern."""

import os
import subprocess
import sys
import time

from agents.speculator import _speculator_work
from backend import fi_db
from backend.controller import PROJECT_ROOT
from providers.social_data import SocialPost


class FakeProvider:
    """security_batches maps security -> its own list of batches, popped
    independently per security - _speculator_work now loops over every
    security in the peer group each cycle, so a provider that ignored which
    security was being asked about would hand out the wrong security's
    batch once more than one security is in play."""

    def __init__(self, security_batches: dict[str, list[list[SocialPost]]]):
        self._security_batches = {sec: list(batches) for sec, batches in security_batches.items()}

    def fetch_recent(self, security, since=None):
        batches = self._security_batches.get(security)
        if not batches:
            return []
        return batches.pop(0)


def post(text, confidence, posted_at="2026-01-01T00:00:05+00:00", security="SYN1"):
    return SocialPost(source="reddit", author="u1", posted_at=posted_at, text=text, security=security, engagement_score=confidence)


def test_speculator_work_records_evidence_for_every_new_post(conn):
    provider = FakeProvider({"SYN1": [[post("low signal chatter", 0.2), post("another low one", 0.3)]]})
    cursor_state = {}

    _speculator_work(conn, "speculator-1", "2026-01-01T00:00:00+00:00", provider, cursor_state)

    items = fi_db.list_evidence_items(conn, [1, 2])
    assert len(items) == 2
    assert items[0]["producer_identity"] == "speculator-1"
    assert items[0]["evidence_type"] == "social"


def test_speculator_work_no_report_below_threshold(conn):
    provider = FakeProvider({"SYN1": [[post("mild chatter", 0.3)]]})
    _speculator_work(conn, "speculator-1", "2026-01-01T00:00:00+00:00", provider, {})
    assert fi_db.fetch_next_pending_report(conn) is None


def test_speculator_work_files_report_when_confidence_clears_threshold(conn):
    provider = FakeProvider({"SYN1": [[post("large block trade just printed", 0.75)]]})
    _speculator_work(conn, "speculator-1", "2026-01-01T00:00:00+00:00", provider, {})

    report = fi_db.fetch_next_pending_report(conn)
    assert report is not None
    assert report["report_type"] == "speculator"
    assert report["detector_event_id"] is None
    import json
    assert json.loads(report["evidence_ids"]) == [1]


def test_speculator_work_no_posts_is_a_noop(conn):
    provider = FakeProvider({"SYN1": [[]]})
    _speculator_work(conn, "speculator-1", "2026-01-01T00:00:00+00:00", provider, {})
    assert fi_db.list_evidence_items(conn, [1]) == []
    assert fi_db.fetch_next_pending_report(conn) is None


def test_speculator_work_cursor_advances_across_calls(conn):
    provider = FakeProvider({"SYN1": [
        [post("first", 0.2, posted_at="2026-01-01T00:00:05+00:00")],
        [post("second", 0.2, posted_at="2026-01-01T00:00:10+00:00")],
    ]})
    cursor_state = {}

    _speculator_work(conn, "speculator-1", "2026-01-01T00:00:00+00:00", provider, cursor_state)
    assert cursor_state["SYN1"] == "2026-01-01T00:00:05+00:00"

    _speculator_work(conn, "speculator-1", "2026-01-01T00:00:00+00:00", provider, cursor_state)
    assert cursor_state["SYN1"] == "2026-01-01T00:00:10+00:00"


def test_speculator_work_skips_new_report_while_one_still_pending(conn):
    """Dedup guard, same shape as Explorer's - a report from this producer+
    security still unconsumed should block filing another one."""
    provider = FakeProvider({"SYN1": [
        [post("first big signal", 0.8)],
        [post("second big signal", 0.9)],
    ]})
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


def test_speculator_work_loops_over_peer_group_without_cross_contamination(conn, monkeypatch):
    """Each security in the peer group gets its own evidence from its own
    batch - a security with no configured batch (SYN3 here) contributes
    nothing, and SYN1's posts never leak into SYN2's evidence or vice
    versa."""
    monkeypatch.setattr("agents.discovery_config.PEER_GROUP_SECURITIES", ["SYN1", "SYN2", "SYN3"])
    provider = FakeProvider({
        "SYN1": [[post("SYN1 chatter", 0.3, security="SYN1")]],
        "SYN2": [[post("SYN2 chatter", 0.4, security="SYN2")]],
    })

    _speculator_work(conn, "speculator-1", "2026-01-01T00:00:00+00:00", provider, {})

    items = {item["security"]: item["content"] for item in fi_db.list_evidence_items(conn, [1, 2])}
    assert items == {"SYN1": "SYN1 chatter", "SYN2": "SYN2 chatter"}


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

    env = {**os.environ, "FI_DB_PATH": db_path, "FI_PEER_GROUP_SECURITIES": "SYN1"}
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
