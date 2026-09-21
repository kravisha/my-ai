"""Jarvis's report on himself, generated from sample data (§7).

The sample data is written directly into the log rather than produced by
running requests, deliberately: this file is about whether the *analysis* is
right, and building a day of traffic through the router to test a report would
be testing the router again, slower.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app import capability_gaps, confidence, model_calls, retry_queue, self_diagnosis


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(model_calls.LOG_DIR_ENV, str(tmp_path / "logs"))
    return tmp_path


def _call(**overrides):
    record = {
        "timestamp": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        "request_id": "req-1",
        "user_request_summary": "what do I hold?",
        "call_index": 0,
        "handler": "kimi_k2",
        "routed_by": "router",
        "escalation_reason": "local_error",
        "confidence_score": None,
        "confidence_threshold": 0.65,
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "latency_ms": 900,
        "outcome": "success",
        "error_detail": None,
        "caller_module": "backend.main::chat",
    }
    record.update(overrides)
    return record


def _seed(tmp_path, records):
    directory = tmp_path / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / model_calls.LOG_FILE_NAME).write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


# --- the nightly report ---------------------------------------------------------


def test_the_nightly_report_is_written_and_names_the_split(_isolated):
    _seed(_isolated, [_call(handler="local", escalation_reason="not_applicable"),
                      _call(request_id="req-2"),
                      _call(request_id="req-3")])

    path = self_diagnosis.nightly(directory=_isolated / "reports")
    text = path.read_text(encoding="utf-8")

    assert path.name.startswith("self_diagnosis_")
    assert "| Handled locally | 1 | 33.3% |" in text
    assert "| Escalated to the remote model | 2 | 66.7% |" in text
    assert "| Requests | 3 |" in text


def test_an_empty_window_says_so_rather_than_reading_as_good_news(_isolated):
    path = self_diagnosis.nightly(directory=_isolated / "reports")
    text = path.read_text(encoding="utf-8")
    assert "An empty report is not evidence of a well-behaved router" in text


def test_calls_that_skipped_the_router_are_listed_loudly(_isolated):
    _seed(_isolated, [_call(routed_by="direct_call",
                            caller_module="agents.explorer::work")])

    text = self_diagnosis.nightly(directory=_isolated / "reports").read_text(encoding="utf-8")

    assert "1 CALL(S) DID NOT GO THROUGH THE ROUTER" in text
    assert "agents.explorer::work" in text
    assert "These are bugs" in text


def test_a_clean_router_says_so_plainly(_isolated):
    _seed(_isolated, [_call()])
    text = self_diagnosis.nightly(directory=_isolated / "reports").read_text(encoding="utf-8")
    assert "Every model call in this window went through" in text


# --- avoidable escalations --------------------------------------------------------


def test_a_direct_call_is_always_an_avoidable_escalation(_isolated):
    found = self_diagnosis.avoidable_escalations([_call(routed_by="direct_call")])
    assert len(found) == 1
    assert "never reached the router" in found[0]["why_avoidable"]


def test_an_escalation_reason_nobody_sanctioned_is_avoidable(_isolated):
    found = self_diagnosis.avoidable_escalations(
        [_call(escalation_reason="not_applicable")])
    assert len(found) == 1
    assert "no escalation reason recorded" in found[0]["why_avoidable"]


def test_a_low_confidence_escalation_near_the_threshold_is_a_judgement_call(_isolated):
    found = self_diagnosis.avoidable_escalations([
        _call(handler="local", escalation_reason="not_applicable"),
        _call(escalation_reason="low_confidence", confidence_score=0.60,
              confidence_threshold=0.65, call_index=1)])
    assert len(found) == 1
    assert "could as easily have gone the other way" in found[0]["why_avoidable"]


def test_a_clearly_low_score_is_not_counted_as_avoidable(_isolated):
    """The local call is seeded alongside it because a real low-confidence
    escalation always has one - there has to be an answer to have scored."""
    assert self_diagnosis.avoidable_escalations([
        _call(handler="local", escalation_reason="not_applicable"),
        _call(escalation_reason="low_confidence", confidence_score=0.05,
              confidence_threshold=0.65, call_index=1),
    ]) == []


def test_a_low_confidence_escalation_with_no_local_call_is_suspicious(_isolated):
    """Rule 4: the reason given does not explain the absence of a local
    attempt, so something skipped it."""
    found = self_diagnosis.avoidable_escalations(
        [_call(escalation_reason="low_confidence", confidence_score=0.05,
               confidence_threshold=0.65)])
    assert len(found) == 1
    assert "no local call was recorded" in found[0]["why_avoidable"]


def test_an_availability_escalation_is_not_avoidable_by_the_router(_isolated):
    assert self_diagnosis.avoidable_escalations([_call()]) == []


def test_the_report_refuses_to_let_a_zero_read_as_a_clean_bill_of_health(_isolated):
    """Every escalation on this machine is `local_error` because there is no
    local model. "0 avoidable" on a system sending 100% of traffic to a paid
    API is a fact that needs its paragraph."""
    _seed(_isolated, [_call(), _call(request_id="req-2")])
    text = self_diagnosis.nightly(directory=_isolated / "reports").read_text(encoding="utf-8")
    assert "Read the zero above carefully" in text
    assert "is not a clean bill of health" in text


def test_the_avoidable_table_carries_the_three_columns_the_task_asked_for(_isolated):
    _seed(_isolated, [_call(routed_by="direct_call",
                            user_request_summary="summarise my week")])
    text = self_diagnosis.nightly(directory=_isolated / "reports").read_text(encoding="utf-8")
    assert "| Request | Stated reason | Why it looks avoidable |" in text
    assert "summarise my week" in text


# --- quota, errors, latency ---------------------------------------------------------


def test_quota_events_report_what_the_user_saw(_isolated):
    _seed(_isolated, [_call(outcome="quota_exhausted",
                            error_detail="KimiQuotaExhausted: HTTP 429")])
    retry_queue.enqueue(request_id="req-1", reason="remote capacity exhausted")

    text = self_diagnosis.nightly(directory=_isolated / "reports").read_text(encoding="utf-8")

    assert "1 call(s) were refused for capacity" in text
    assert "I can't do that reliably right now" in text
    assert "**Queued for retry:** 1 waiting" in text


def test_latency_outliers_are_picked_out_against_the_median(_isolated):
    _seed(_isolated, [_call(latency_ms=100), _call(latency_ms=110),
                      _call(latency_ms=120), _call(latency_ms=9000)])
    text = self_diagnosis.nightly(directory=_isolated / "reports").read_text(encoding="utf-8")
    assert "Outliers (over 3x the median): 1" in text
    assert "9000 ms" in text


def test_errors_and_timeouts_are_counted_separately(_isolated):
    _seed(_isolated, [_call(outcome="error", error_detail="boom"),
                      _call(outcome="timeout")])
    text = self_diagnosis.nightly(directory=_isolated / "reports").read_text(encoding="utf-8")
    assert "- Errors: 1" in text
    assert "- Timeouts: 1" in text
    assert "boom" in text


# --- the threshold suggestion, which is only ever a suggestion ------------------------


def test_no_scores_means_no_suggestion_and_says_why(_isolated):
    suggestion = self_diagnosis.suggest_threshold([_call()])
    assert suggestion["suggested"] is None
    assert "nothing on this system scores a local answer" in suggestion["reasoning"]


def test_a_run_of_marginal_escalations_produces_a_suggestion_with_reasoning(_isolated):
    records = [_call(escalation_reason="low_confidence", confidence_score=score,
                     confidence_threshold=0.65)
               for score in (0.60, 0.62, 0.64, 0.10)]
    suggestion = self_diagnosis.suggest_threshold(records)

    assert suggestion["suggested"] == 0.59
    assert "75%" in suggestion["reasoning"]
    assert "SUGGESTION ONLY" in suggestion["reasoning"]


def test_genuinely_low_scores_do_not_argue_for_moving_the_threshold(_isolated):
    records = [_call(escalation_reason="low_confidence", confidence_score=0.05,
                     confidence_threshold=0.65) for _ in range(5)]
    assert self_diagnosis.suggest_threshold(records)["suggested"] is None


def test_the_report_never_rewrites_the_policy_file(_isolated, monkeypatch):
    """§5.1: "Jarvis does not tune his own threshold without approval.\""""
    from app import router_config

    before = router_config.config_path().read_text(encoding="utf-8")
    _seed(_isolated, [_call(escalation_reason="low_confidence",
                            confidence_score=0.64, confidence_threshold=0.65)
                      for _ in range(4)])
    text = self_diagnosis.nightly(directory=_isolated / "reports").read_text(encoding="utf-8")

    assert router_config.config_path().read_text(encoding="utf-8") == before
    assert "Jarvis does not tune his own threshold" in text


# --- the weekly roll-up ---------------------------------------------------------------


def test_the_weekly_report_carries_a_day_by_day_trend(_isolated):
    now = datetime.now(timezone.utc)
    _seed(_isolated, [
        _call(timestamp=(now - timedelta(days=offset, hours=1)).isoformat(),
              request_id=f"req-{offset}")
        for offset in range(5)])

    path = self_diagnosis.weekly(now, directory=_isolated / "reports")
    text = path.read_text(encoding="utf-8")

    assert "W" in path.name
    assert "## Trend across the week" in text
    assert "| Day | Calls | Local | Remote | Errors | Quota | Direct |" in text
    assert text.count("| 1 | 0 | 1 | 0 | 0 | 0 |") >= 4


# --- the schedule ------------------------------------------------------------------------


def test_nothing_runs_before_the_configured_hour(_isolated):
    assert self_diagnosis.due(datetime(2026, 9, 21, 1, 0)) is False
    assert self_diagnosis.due(datetime(2026, 9, 21, 4, 0)) is True


def test_a_report_already_written_today_is_not_written_twice(_isolated):
    _seed(_isolated, [_call()])
    reports = _isolated / "reports"
    # A Wednesday, so only the nightly is due - the weekly has its own test.
    moment = datetime(2026, 9, 23, 4, 0, tzinfo=timezone.utc)

    first = self_diagnosis.run_if_due(moment, reports)
    second = self_diagnosis.run_if_due(moment, reports)

    assert [path.name for path in first] == ["self_diagnosis_2026-09-23.md"]
    assert second == []


def test_the_weekly_and_the_audit_land_on_their_days(_isolated):
    _seed(_isolated, [_call()])
    reports = _isolated / "reports"
    # 2026-11-02 is a Monday and the 2nd, so only the weekly is due with it.
    written = self_diagnosis.run_if_due(
        datetime(2026, 11, 2, 4, 0, tzinfo=timezone.utc), reports)
    assert any("weekly" in path.name for path in written)

    # 2026-12-01 is the 1st of a month: the skills audit.
    written = self_diagnosis.run_if_due(
        datetime(2026, 12, 1, 4, 0, tzinfo=timezone.utc), reports)
    assert any("skills_audit" in path.name for path in written)


# --- what reaches the morning brief -------------------------------------------------------


def test_a_quiet_night_puts_nothing_in_the_brief(_isolated):
    assert self_diagnosis.brief_items() == []


def test_a_router_bypass_reaches_the_brief(_isolated):
    _seed(_isolated, [_call(routed_by="direct_call", caller_module="agents.explorer::work")])
    items = self_diagnosis.brief_items()

    # Two items, not one: a bypass is also an avoidable escalation, and both
    # lines are worth having - one says a rule was broken, the other says what
    # it cost.
    assert [item["category"] for item in items] == ["needs_attention"] * 2
    assert "bypassed the router" in items[0]["text"]
    assert "agents.explorer::work" in items[0]["text"]
    assert "could have stayed local" in items[1]["text"]


def test_quota_exhaustion_is_reported_in_the_morning_not_in_conversation(_isolated):
    """§4.2.4: "Notify Krish through the normal brief, not mid-conversation.\""""
    _seed(_isolated, [_call(outcome="quota_exhausted")])
    items = self_diagnosis.brief_items()
    assert any("ran out of capacity" in item["text"] for item in items)
    assert any("You were not told about it at the time" in item["text"] for item in items)


def test_the_brief_says_nothing_a_user_may_not_read():
    """The brief is Krish's operator surface, and still keeps the vocabulary -
    it is rendered into a spoken briefing that a room can hear."""
    from app import user_messages

    for message in user_messages.MESSAGES.values():
        assert user_messages.is_clean(message)


def test_the_briefing_survives_an_unreadable_call_log(_isolated, monkeypatch):
    from backend import briefing

    monkeypatch.setattr(self_diagnosis, "brief_items",
                        lambda **_: (_ for _ in ()).throw(RuntimeError("bad log")))
    assert briefing._self_report(None) == []
