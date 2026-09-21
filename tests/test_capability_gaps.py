"""The record of what Jarvis was asked for and could not do (Deliverable D).

Two things are being held here and only one of them is the file format. The
other is §6.2's ranking rule - *by frequency of request, not by how interesting
it is to build* - which is the reason the whole deliverable exists and the
thing a later refactor is most likely to quietly reverse.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app import capability_gaps, model_calls


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(model_calls.LOG_DIR_ENV, str(tmp_path / "logs"))
    return tmp_path


def _entries(tmp_path):
    path = tmp_path / "logs" / capability_gaps.GAPS_FILE_NAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


# --- the record -----------------------------------------------------------------


def test_a_gap_carries_every_field_the_specification_names(_isolated):
    with model_calls.request_context("send this to my accountant"):
        capability_gaps.record(
            gap_type=capability_gaps.GAP_MISSING_INTEGRATION,
            what_was_needed="an email client",
            user_visible_outcome="I can't send email yet.",
            request_summary="send this to my accountant")

    entry = _entries(_isolated)[0]
    assert set(entry) >= {"timestamp", "request_id", "request_summary", "gap_type",
                          "what_was_needed", "user_visible_outcome"}
    assert entry["gap_type"] == "missing_integration"


def test_a_gap_type_outside_the_vocabulary_is_refused(_isolated):
    with pytest.raises(ValueError, match="not one of"):
        capability_gaps.record(gap_type="interesting", what_was_needed="x",
                               user_visible_outcome="y")


def test_a_gap_shares_the_request_id_of_the_turn_that_failed(_isolated):
    with model_calls.request_context("do the thing") as request_id:
        capability_gaps.record(gap_type=capability_gaps.GAP_UNCLEAR,
                               what_was_needed="x", user_visible_outcome="y")
    assert _entries(_isolated)[0]["request_id"] == request_id


def test_a_failure_without_a_stated_reason_is_unclear_rather_than_guessed(_isolated):
    capability_gaps.record_failure(RuntimeError("boom"), user_visible_outcome="sorry")
    assert _entries(_isolated)[0]["gap_type"] == "unclear"


def test_a_routing_failure_is_a_missing_integration(_isolated):
    from app.model_routing import ModelRoutingFailure

    capability_gaps.record_failure(ModelRoutingFailure("no model"),
                                   user_visible_outcome="sorry")
    assert _entries(_isolated)[0]["gap_type"] == "missing_integration"


def test_a_permission_failure_is_classified_as_one(_isolated):
    capability_gaps.record_failure(PermissionError("not allowed"),
                                   user_visible_outcome="sorry")
    assert _entries(_isolated)[0]["gap_type"] == "insufficient_permissions"


# --- the ranking rule, which is the point ------------------------------------------


def _gap(needed, gap_type=capability_gaps.GAP_MISSING_TOOL, **extra):
    return {"timestamp": datetime.now(timezone.utc).isoformat(),
            "gap_type": gap_type, "what_was_needed": needed,
            "user_visible_outcome": "I can't do that.", **extra}


def test_gaps_are_ranked_by_how_often_they_were_asked_for(_isolated):
    rows = ([_gap("send an email")] * 4
            + [_gap("build a compiler", capability_gaps.GAP_MISSING_KNOWLEDGE)]
            + [_gap("check the weather")] * 2)

    ranked = capability_gaps.ranked(rows)

    assert [entry["count"] for entry in ranked] == [4, 2, 1]
    assert ranked[0]["what_was_needed"] == "send an email"
    assert ranked[-1]["what_was_needed"] == "build a compiler"


def test_the_same_need_worded_differently_still_groups(_isolated):
    """Grouping on the raw summary would rank every gap at one occurrence and
    report, truthfully and uselessly, that nothing is ever asked for twice."""
    rows = [_gap("Send an  email"), _gap("send an email\n"), _gap("SEND AN EMAIL")]
    assert [entry["count"] for entry in capability_gaps.ranked(rows)] == [3]


def test_two_gaps_of_different_types_are_not_merged_by_their_wording(_isolated):
    rows = [_gap("email", capability_gaps.GAP_MISSING_TOOL),
            _gap("email", capability_gaps.GAP_INSUFFICIENT_PERMISSIONS)]
    assert len(capability_gaps.ranked(rows)) == 2


# --- the monthly report --------------------------------------------------------------


def _seed(tmp_path, rows):
    directory = tmp_path / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / capability_gaps.GAPS_FILE_NAME).write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_the_monthly_report_separates_often_from_once(_isolated):
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    _seed(_isolated, [_gap("send an email")] * 3 + [_gap("play chess")])

    path = capability_gaps.monthly_report(month, _isolated / "reports")
    text = path.read_text(encoding="utf-8")

    assert path.name == f"skills_audit_{month}.md"
    assert "## Asked for often (two or more times)" in text
    assert "## Asked for once" in text
    assert text.index("send an email") < text.index("## Asked for once")
    assert text.index("play chess") > text.index("## Asked for once")


def test_each_top_gap_says_what_would_close_it_and_what_it_depends_on(_isolated):
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    _seed(_isolated, [_gap("an email client", capability_gaps.GAP_MISSING_INTEGRATION)] * 2)

    text = capability_gaps.monthly_report(month, _isolated / "reports").read_text(encoding="utf-8")

    assert "Capability that would close it" in text
    assert "Depends on:" in text
    assert "an adapter behind an existing interface" in text.lower()


def test_a_month_with_nothing_recorded_does_not_read_as_a_capable_assistant(_isolated):
    text = capability_gaps.monthly_report(
        "2026-01", _isolated / "reports").read_text(encoding="utf-8")
    assert "an empty report is not" in text.lower()


def test_a_report_of_mostly_unclear_gaps_says_that_is_a_finding(_isolated):
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    _seed(_isolated, [_gap("something", capability_gaps.GAP_UNCLEAR)] * 5
          + [_gap("email")])
    text = capability_gaps.monthly_report(month, _isolated / "reports").read_text(encoding="utf-8")
    assert "More than half of this month's gaps are `unclear`" in text


def test_a_pipe_in_a_request_does_not_break_the_table(_isolated):
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    _seed(_isolated, [_gap("run `a | b`")] * 2)
    text = capability_gaps.monthly_report(month, _isolated / "reports").read_text(encoding="utf-8")
    assert "run `a \\| b`" in text


def test_only_the_requested_month_is_reported(_isolated):
    last_month = (datetime.now(timezone.utc) - timedelta(days=45))
    _seed(_isolated, [
        {**_gap("old thing"), "timestamp": last_month.isoformat()},
        _gap("new thing"),
    ])
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    text = capability_gaps.monthly_report(month, _isolated / "reports").read_text(encoding="utf-8")
    assert "new thing" in text
    assert "old thing" not in text


# --- capture on the real failure paths -------------------------------------------------


def test_a_turn_that_ran_out_of_tool_rounds_is_recorded_as_a_gap(_isolated, tmp_path):
    """§6.1's "answered only partially" - the case a human reviewer would
    never think to write down, because the turn did not fail."""
    from gateway import conversation

    class _Looping:
        def stream(self, system, messages, tools, max_tokens=2048):
            return iter([
                {"type": "text", "text": "working on it "},
                {"type": "final", "stop_reason": "tool_use",
                 "content": [{"type": "tool_use", "id": "t1",
                              "name": "list_scoreboard", "input": {}}]},
            ])

    events = list(conversation.run_turn(
        tmp_path / "gateway.db",
        [{"role": "user", "text": "keep going until it is done"}],
        _Looping(), role="operator"))

    assert any("stopped after" in event.get("text", "") for event in events)
    entry = _entries(_isolated)[0]
    assert entry["gap_type"] == "missing_tool"
    assert "rounds of tool calls" in entry["what_was_needed"]
    assert entry["request_summary"] == "keep going until it is done"


def test_the_backend_chat_records_a_gap_when_it_refuses(_isolated, backend_client,
                                                        monkeypatch):
    from unittest.mock import MagicMock

    from app.model_budget import BudgetExceededError

    token = backend_client.post(
        "/auth/register", json={"username": "ada", "password": "hunter2"}
    ).json()["token"]
    monkeypatch.setattr(
        "backend.main.call_reasoning_model",
        MagicMock(side_effect=BudgetExceededError("Daily model token budget exhausted")))

    backend_client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]},
                        headers={"Authorization": f"Bearer {token}"})

    entry = _entries(_isolated)[0]
    assert entry["request_summary"] == "hi"
    assert entry["user_visible_outcome"] == (
        "I can't do that reliably right now - I'll retry shortly.")
