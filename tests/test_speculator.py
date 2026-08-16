"""Unit tests for agents/speculator.py - normalization, confidence-
threshold gating, cursor-based dedup, and the cross-check answer path. The
only LLM call is `_read_stance`, reached solely when answering a
cross-check, so most tests here still need no mocking - just a fake provider
with
canned posts for deterministic control over what "recent" returns. The one
real-subprocess test at the bottom needs no @pytest.mark.real_llm marker
for the same reason - it makes no network call, just proves the process/
provider/DB mechanics actually work, matching test_controller.py's
real-subprocess-proves-the-mechanics pattern."""

import json
import os
import subprocess
import sys
import time
from unittest.mock import MagicMock

import pytest

from agents.speculator import _answer_pending_cross_checks, _source_dispersion, _speculator_work
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


def post(text, confidence, posted_at="2026-01-01T00:00:05+00:00", security="SYN1", author="u1"):
    return SocialPost(source="reddit", author=author, posted_at=posted_at, text=text, security=security, engagement_score=confidence)


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
    """Two cycles now: clearing the confidence bar opens a cross-check asking
    Explorer for quantitative corroboration (addendum 12 section 14), and the
    report is filed once that resolves."""
    provider = FakeProvider({"SYN1": [[post("large block trade just printed", 0.75)]]})
    seen = {}
    _speculator_work(conn, "speculator-1", "2026-01-01T00:00:00+00:00", provider, {}, seen)
    assert fi_db.fetch_next_pending_report(conn) is None

    fi_db.answer_cross_check(conn, 1, "explorer-1", "2026-01-01T00:00:00+00:00",
                             fi_db.CROSS_CHECK_EVIDENCE, {"ratio": 2.2, "cleared_threshold": True})
    _speculator_work(conn, "speculator-1", "2026-01-01T00:00:00+00:00", provider, {}, seen)

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
    fi_db.answer_cross_check(conn, 1, "explorer-1", "2026-01-01T00:00:00+00:00",
                             fi_db.CROSS_CHECK_EVIDENCE, {"ratio": 2.2})
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


# --- cross-check: dispersion, stance, and answering ---


class _Block:
    def __init__(self, text):
        self.type, self.text = "text", text


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]


def stance_response(stance, strength=0.8, summary="s"):
    return _Resp(json.dumps({"stance": stance, "summary": summary, "strength": strength}))


def _ask(conn, security="SYN1"):
    return fi_db.open_cross_check(
        conn, "explorer-1", "T0", "explorer", "speculator", security,
        question=f"Is there contextual evidence on {security}?",
        requester_finding={"ratio": 2.21},
    )


def test_source_dispersion_separates_a_crowd_from_three_accounts():
    """Identical text, opposite meaning. This is the frame language cannot
    supply - telling a crowd from coordinated noise is counting, not reading."""
    crowd = [post("x", 0.9, author=f"u{i}") for i in range(9)]
    coordinated = [post("x", 0.9, author=f"u{i % 3}") for i in range(9)]
    assert _source_dispersion(crowd)["posts_per_author"] == 1.0
    assert _source_dispersion(coordinated)["posts_per_author"] == 3.0
    # volume alone cannot tell them apart
    assert _source_dispersion(crowd)["posts"] == _source_dispersion(coordinated)["posts"]


def test_source_dispersion_of_nothing_is_not_a_division_by_zero():
    assert _source_dispersion([])["posts_per_author"] == 0.0


def test_answering_reports_both_dispersion_and_stance(conn, monkeypatch):
    monkeypatch.setattr("agents.speculator.call_reasoning_model",
                        MagicMock(return_value=stance_response("undercuts", 0.9, "explains it away")))
    request_id = _ask(conn)
    seen = {"SYN1": [post("just a hedge roll", 0.8, author=f"u{i}") for i in range(6)]}

    _answer_pending_cross_checks(conn, "speculator-1", "T1", seen)

    finding = json.loads(fi_db.get_cross_check(conn, request_id)["responder_finding"])
    assert finding["stance"] == "undercuts"
    assert finding["distinct_authors"] == 6
    assert finding["posts_per_author"] == 1.0


def test_answering_with_nothing_observed_is_no_evidence_not_silence(conn):
    request_id = _ask(conn)
    _answer_pending_cross_checks(conn, "speculator-1", "T1", {})
    row = fi_db.get_cross_check(conn, request_id)
    assert row["outcome"] == fi_db.CROSS_CHECK_NO_EVIDENCE
    assert row["status"] == fi_db.CROSS_CHECK_RESOLVED


def test_speculator_never_declares_whether_the_findings_agree(conn, monkeypatch):
    """Speculator reports what the crowd said and how broadly. Whether that
    corroborates a quantitative dislocation is Analysis's judgment."""
    monkeypatch.setattr("agents.speculator.call_reasoning_model",
                        MagicMock(return_value=stance_response("supports")))
    request_id = _ask(conn)
    _answer_pending_cross_checks(conn, "speculator-1", "T1", {"SYN1": [post("unusual flow", 0.9)]})

    row = fi_db.get_cross_check(conn, request_id)
    assert row["outcome"] == fi_db.CROSS_CHECK_EVIDENCE
    assert row["outcome"] not in ("corroborated", "contradicted")


def test_unreadable_stance_still_answers_rather_than_stalling(conn, monkeypatch):
    """An unavailable or malformed stance read must degrade to 'unclear' and
    let the deterministic signals through - never leave the requester waiting."""
    monkeypatch.setattr("agents.speculator.call_reasoning_model",
                        MagicMock(side_effect=RuntimeError("model unavailable")))
    request_id = _ask(conn)
    _answer_pending_cross_checks(conn, "speculator-1", "T1", {"SYN1": [post("chatter", 0.9)]})

    row = fi_db.get_cross_check(conn, request_id)
    assert row["status"] == fi_db.CROSS_CHECK_RESOLVED
    finding = json.loads(row["responder_finding"])
    assert finding["stance"] == "unclear"
    assert finding["distinct_authors"] == 1  # deterministic signals survived


def test_stance_outside_the_allowed_set_is_treated_as_unclear(conn, monkeypatch):
    monkeypatch.setattr("agents.speculator.call_reasoning_model",
                        MagicMock(return_value=_Resp('{"stance": "very bullish", "strength": 0.9}')))
    request_id = _ask(conn)
    _answer_pending_cross_checks(conn, "speculator-1", "T1", {"SYN1": [post("chatter", 0.9)]})
    assert json.loads(fi_db.get_cross_check(conn, request_id)["responder_finding"])["stance"] == "unclear"


def test_answering_ignores_requests_addressed_to_other_roles(conn, monkeypatch):
    call_model = MagicMock(return_value=stance_response("supports"))
    monkeypatch.setattr("agents.speculator.call_reasoning_model", call_model)
    fi_db.open_cross_check(conn, "speculator-1", "T0", "speculator", "explorer", "SYN1",
                           question="q", requester_finding={})

    _answer_pending_cross_checks(conn, "speculator-1", "T1", {"SYN1": [post("chatter", 0.9)]})

    call_model.assert_not_called()
