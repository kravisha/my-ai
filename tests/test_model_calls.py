"""The model call log: does it record what §3.1 says, and does it record the
calls that skipped the router?

The second question is the one that matters. A log that only sees compliant
callers is not evidence of compliance, so most of this file is about the
`direct_call` path rather than the happy one.
"""

import json
import logging
from datetime import datetime, timedelta, timezone

import pytest

from app import model_calls, router_config


@pytest.fixture(autouse=True)
def _isolated_log(tmp_path, monkeypatch):
    monkeypatch.setenv(model_calls.LOG_DIR_ENV, str(tmp_path / "logs"))
    return tmp_path / "logs"


def _written(directory):
    path = directory / model_calls.LOG_FILE_NAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


# --- the schema ---------------------------------------------------------------


SCHEMA_FIELDS = [
    "timestamp", "request_id", "user_request_summary", "call_index", "handler",
    "routed_by", "escalation_reason", "confidence_score", "confidence_threshold",
    "prompt_tokens", "completion_tokens", "latency_ms", "outcome",
    "error_detail", "caller_module",
]


def test_a_record_carries_every_field_the_specification_names(_isolated_log):
    with model_calls.request_context("what do I hold in Tesla?"):
        with model_calls.routing_context(
                escalation_reason=model_calls.REASON_LOCAL_ERROR) as _:
            with model_calls.record_call(model_calls.HANDLER_KIMI) as call:
                call.usage(120, 40)

    record = _written(_isolated_log)[0]
    assert list(record) == SCHEMA_FIELDS, "the schema is §3.1's, in §3.1's order"
    assert record["handler"] == "kimi_k2"
    assert record["routed_by"] == "router"
    assert record["escalation_reason"] == "local_error"
    assert record["outcome"] == "success"
    assert record["prompt_tokens"] == 120
    assert record["completion_tokens"] == 40
    assert record["error_detail"] is None
    assert isinstance(record["latency_ms"], int)


def test_a_vocabulary_value_nothing_can_group_by_is_refused():
    with pytest.raises(ValueError, match="not one of"):
        model_calls.build_record(
            handler="gpt", routed_by="router", escalation_reason="not_applicable",
            outcome="success", request_id="r", user_request_summary=None,
            call_index=0, caller="x::y", latency_ms=1)


def test_only_the_first_200_characters_of_what_he_typed_are_kept():
    long_question = "a" * 500
    assert len(model_calls.summarise(long_question)) == 200


def test_nothing_the_user_said_beyond_the_summary_reaches_the_log(_isolated_log):
    secret = "my account number is 12345678 and my password is hunter2"
    with model_calls.request_context("what do I hold?"):
        with model_calls.record_call(model_calls.HANDLER_KIMI):
            pass
    text = (_isolated_log / model_calls.LOG_FILE_NAME).read_text(encoding="utf-8")
    assert secret not in text
    assert "12345678" not in text


def test_no_originating_user_input_is_none_rather_than_empty(_isolated_log):
    """An agent's own work was not asked for in words, and "nobody asked" is a
    different fact from "they asked for nothing"."""
    with model_calls.request_context(None):
        with model_calls.record_call(model_calls.HANDLER_KIMI):
            pass
    assert _written(_isolated_log)[0]["user_request_summary"] is None


# --- one request, several calls ------------------------------------------------


def test_every_call_serving_one_request_shares_its_id_and_is_ordered(_isolated_log):
    with model_calls.request_context("run the tool loop"):
        for _ in range(3):
            with model_calls.record_call(model_calls.HANDLER_KIMI):
                pass

    records = _written(_isolated_log)
    assert len({r["request_id"] for r in records}) == 1
    assert [r["call_index"] for r in records] == [0, 1, 2]


def test_a_nested_request_context_does_not_start_a_second_request(_isolated_log):
    with model_calls.request_context("outer") as outer:
        with model_calls.request_context("inner") as inner:
            assert inner == outer


# --- routed_by, which is the whole point ---------------------------------------


def test_a_call_with_no_routing_context_is_recorded_as_a_direct_call(_isolated_log):
    """The finding this task exists to be able to make."""
    with model_calls.record_call(model_calls.HANDLER_KIMI):
        pass
    assert _written(_isolated_log)[0]["routed_by"] == "direct_call"


def test_a_call_the_router_made_after_a_local_failure_says_so(_isolated_log):
    with model_calls.routing_context(
            routed_by=model_calls.ROUTED_BY_FALLBACK,
            escalation_reason=model_calls.REASON_LOCAL_ERROR):
        with model_calls.record_call(model_calls.HANDLER_KIMI):
            pass
    assert _written(_isolated_log)[0]["routed_by"] == "fallback_after_error"


def test_the_routing_context_does_not_leak_past_its_block(_isolated_log):
    with model_calls.routing_context(escalation_reason=model_calls.REASON_LOCAL_ERROR):
        pass
    with model_calls.record_call(model_calls.HANDLER_KIMI):
        pass
    assert _written(_isolated_log)[0]["routed_by"] == "direct_call"


def test_a_snapshot_captured_before_a_generator_runs_keeps_its_routing(_isolated_log):
    """The trap the module docstring names: a stream is created inside the
    router's context and consumed outside it. A contextvar read in the deferred
    body would say `direct_call` for every streamed call in the system."""
    def make_stream():
        snapshot = model_calls.capture()

        def events():
            with model_calls.record_call(model_calls.HANDLER_KIMI, snapshot):
                yield {"type": "final"}
        return events()

    with model_calls.routing_context(escalation_reason=model_calls.REASON_LOCAL_ERROR):
        stream = make_stream()
    list(stream)  # consumed after the context closed

    assert _written(_isolated_log)[0]["routed_by"] == "router"


# --- the guard ------------------------------------------------------------------


def test_a_runtime_module_calling_a_model_directly_is_refused(_isolated_log, monkeypatch):
    snapshot = model_calls.capture()
    snapshot.caller_module = "gateway.main::conversation_socket"

    with pytest.raises(model_calls.DirectModelCallError, match="without going through"):
        with model_calls.record_call(model_calls.HANDLER_KIMI, snapshot):
            pass


def test_the_refused_call_is_recorded_before_it_is_refused(_isolated_log):
    """A guard that hid the event it fired on would be worse than no guard."""
    snapshot = model_calls.capture()
    snapshot.caller_module = "agents.explorer::work"
    with pytest.raises(model_calls.DirectModelCallError):
        with model_calls.record_call(model_calls.HANDLER_KIMI, snapshot):
            pass

    record = _written(_isolated_log)[0]
    assert record["routed_by"] == "direct_call"
    assert record["outcome"] == "error"
    assert "refused" in record["error_detail"]


def test_a_direct_call_from_the_suite_is_recorded_and_allowed(_isolated_log):
    """Deliberate, and stated in the module docstring: the Kimi provider's own
    conformance suite constructs it directly, and a guard that made the
    provider untestable in isolation would be removed within a week."""
    with model_calls.record_call(model_calls.HANDLER_KIMI):
        pass
    assert _written(_isolated_log)[0]["routed_by"] == "direct_call"


def test_the_router_itself_is_never_treated_as_a_direct_caller(_isolated_log):
    for module in model_calls._PLUMBING_MODULES:
        assert not model_calls._is_runtime_caller(f"{module}::anything")


# --- outcomes -------------------------------------------------------------------


class _Quota(RuntimeError):
    model_call_outcome = "quota_exhausted"


def test_an_exception_naming_its_own_outcome_is_believed(_isolated_log):
    with pytest.raises(_Quota):
        with model_calls.record_call(model_calls.HANDLER_KIMI):
            raise _Quota("spent")
    record = _written(_isolated_log)[0]
    assert record["outcome"] == "quota_exhausted"
    assert "_Quota: spent" in record["error_detail"]


def test_a_timeout_is_recorded_as_a_timeout_not_an_error(_isolated_log):
    with pytest.raises(TimeoutError):
        with model_calls.record_call(model_calls.HANDLER_LOCAL):
            raise TimeoutError("took too long")
    assert _written(_isolated_log)[0]["outcome"] == "timeout"


def test_an_ordinary_failure_is_an_error(_isolated_log):
    with pytest.raises(RuntimeError):
        with model_calls.record_call(model_calls.HANDLER_KIMI):
            raise RuntimeError("upstream refused")
    assert _written(_isolated_log)[0]["outcome"] == "error"


# --- the wrapper for the local tier ----------------------------------------------


class _Local:
    name, model = "local-stand-in", "qwen-stand-in"
    supports_tools = False
    context_window = 4096

    class _Usage:
        input_tokens, output_tokens = 11, 7

    class _Answer:
        usage = None

    def complete(self, system, messages, tools, max_tokens=2048):
        answer = self._Answer()
        answer.usage = self._Usage()
        return answer

    def stream(self, system, messages, tools, max_tokens=2048):
        return iter([{"type": "text", "text": "hi"},
                     {"type": "final", "content": [], "stop_reason": "end_turn",
                      "usage": {"input_tokens": 3, "output_tokens": 4}}])


def test_the_local_wrapper_records_a_completion(_isolated_log):
    wrapped = model_calls.InstrumentedProvider(_Local())
    wrapped.complete("sys", [], [])
    record = _written(_isolated_log)[0]
    assert record["handler"] == "local"
    assert (record["prompt_tokens"], record["completion_tokens"]) == (11, 7)


def test_the_local_wrapper_records_a_stream_with_its_reported_usage(_isolated_log):
    wrapped = model_calls.InstrumentedProvider(_Local())
    list(wrapped.stream("sys", [], []))
    record = _written(_isolated_log)[0]
    assert (record["prompt_tokens"], record["completion_tokens"]) == (3, 4)


def test_the_wrapper_forwards_the_questions_the_router_asks_the_local_tier():
    """A wrapper that swallowed `supports_tools` would answer "does not say",
    which the router reads as "attempt it anyway" - instrumentation silently
    changing a routing decision."""
    wrapped = model_calls.InstrumentedProvider(_Local())
    assert wrapped.supports_tools is False
    assert wrapped.context_window == 4096
    assert wrapped.model == "qwen-stand-in"


# --- rotation and reading --------------------------------------------------------


def test_yesterdays_file_is_rotated_and_old_ones_are_pruned(_isolated_log):
    import os

    _isolated_log.mkdir(parents=True, exist_ok=True)
    live = _isolated_log / model_calls.LOG_FILE_NAME
    live.write_text('{"timestamp": "2020-01-01T00:00:00+00:00"}\n', encoding="utf-8")
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    os.utime(live, (yesterday.timestamp(), yesterday.timestamp()))

    ancient = _isolated_log / f"model_calls-{(datetime.now(timezone.utc) - timedelta(days=90)).date()}.jsonl"
    ancient.write_text("{}\n", encoding="utf-8")

    with model_calls.record_call(model_calls.HANDLER_KIMI):
        pass

    rotated = _isolated_log / f"model_calls-{yesterday.date().isoformat()}.jsonl"
    assert rotated.exists(), "yesterday's lines moved to a dated file"
    assert not ancient.exists(), "a file older than the retention window is pruned"
    assert len(_written(_isolated_log)) == 1, "today's file holds only today"


def test_a_caller_who_stops_reading_a_stream_is_not_an_error(_isolated_log):
    """A closed browser tab throws `GeneratorExit` into the generator, which
    the generic handler classified as a failure - so every abandoned reply
    inflated the nightly report's error count. The call is still recorded, with
    what it managed to produce."""
    wrapped = model_calls.InstrumentedProvider(_Local())
    stream = wrapped.stream("sys", [], [])
    assert next(stream)["type"] == "text"

    stream.close()

    record = _written(_isolated_log)[0]
    assert record["outcome"] == model_calls.OUTCOME_SUCCESS
    assert "stopped reading" in record["error_detail"]


def test_the_configured_retention_window_is_the_one_that_prunes(_isolated_log,
                                                                tmp_path,
                                                                monkeypatch):
    """`logging.retention_days` was validated, exposed, documented - and never
    read, so editing `config/router.yaml` did nothing. A policy file that is
    ignored is not a policy."""
    config = tmp_path / "router.yaml"
    config.write_text("logging:\n  retention_days: 3\n", encoding="utf-8")
    monkeypatch.setenv(router_config.PATH_ENV, str(config))
    assert model_calls.retention_days() == 3

    import os

    _isolated_log.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    within = _isolated_log / f"model_calls-{(now - timedelta(days=2)).date()}.jsonl"
    beyond = _isolated_log / f"model_calls-{(now - timedelta(days=9)).date()}.jsonl"
    for path in (within, beyond):
        path.write_text("{}\n", encoding="utf-8")

    # Pruning happens at rotation, so there has to be something to rotate.
    live = _isolated_log / model_calls.LOG_FILE_NAME
    live.write_text('{"timestamp": "2020-01-01T00:00:00+00:00"}\n', encoding="utf-8")
    yesterday = (now - timedelta(days=1)).timestamp()
    os.utime(live, (yesterday, yesterday))

    with model_calls.record_call(model_calls.HANDLER_KIMI):
        pass

    assert within.exists(), "inside the configured window"
    assert not beyond.exists(), (
        "outside it - and inside the 30 days the constant would have kept, "
        "which is what makes this about the configuration")


def test_reading_spans_the_live_file_and_the_rotated_ones(_isolated_log):
    _isolated_log.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    (_isolated_log / "model_calls-2026-09-01.jsonl").write_text(
        json.dumps({"timestamp": (now - timedelta(hours=2)).isoformat(),
                    "handler": "kimi_k2"}) + "\n", encoding="utf-8")
    with model_calls.record_call(model_calls.HANDLER_KIMI):
        pass

    records = model_calls.read_records(since=now - timedelta(hours=3), until=now + timedelta(hours=1))
    assert len(records) == 2


def test_a_truncated_line_is_skipped_rather_than_failing_the_read(_isolated_log):
    _isolated_log.mkdir(parents=True, exist_ok=True)
    (_isolated_log / model_calls.LOG_FILE_NAME).write_text(
        json.dumps({"timestamp": datetime.now(timezone.utc).isoformat()}) + "\n"
        + '{"timestamp": "2026-09-2',
        encoding="utf-8")
    assert len(model_calls.read_records()) == 1


def test_every_record_also_goes_to_stdout_at_debug(_isolated_log, caplog):
    with caplog.at_level(logging.DEBUG, logger="model.calls"):
        with model_calls.record_call(model_calls.HANDLER_KIMI):
            pass
    assert json.loads(caplog.records[0].message)["handler"] == "kimi_k2"
