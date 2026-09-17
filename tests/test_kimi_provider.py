"""app/kimi_provider.py - the dialect translation, tested where it can break.

The Gateway assistant carries tools on every turn, so the part of this change
that matters is not "does a sentence come back" - it is whether a tool call
survives the round trip between Anthropic's message shape and OpenAI's. These
tests are written against that, and the two refusals are asserted as loudly as
the successes: a tool run with the wrong arguments is an action that looks like
a success, which is the one failure this provider must not produce.

No network call is made anywhere in this file. `KimiProvider` takes a
`transport` seam for exactly that, and `test_the_production_path_is_not_the_seam`
is what stops the seam from quietly becoming the thing under test.
"""

import json

import pytest

from app import kimi_provider as kp


# --- the outbound translation ---------------------------------------------------


def test_the_system_prompt_becomes_a_leading_message():
    converted = kp.to_openai_messages("you are helpful", [{"role": "user", "content": "hi"}])
    assert converted[0] == {"role": "system", "content": "you are helpful"}
    assert converted[1] == {"role": "user", "content": "hi"}


def test_a_blank_system_prompt_is_not_sent_as_an_empty_message():
    """An empty text message is rejected by servers in this dialect, and a
    caller with no system prompt has nothing to say in one."""
    assert kp.to_openai_messages("   ", [{"role": "user", "content": "hi"}]) == [
        {"role": "user", "content": "hi"}]


def test_an_assistant_tool_call_becomes_tool_calls_with_encoded_arguments():
    converted = kp.to_openai_messages("", [{
        "role": "assistant",
        "content": [
            {"type": "text", "text": "looking"},
            {"type": "tool_use", "id": "t1", "name": "jarvis_status", "input": {"deep": True}},
        ],
    }])
    assert len(converted) == 1
    assert converted[0]["content"] == "looking"
    call = converted[0]["tool_calls"][0]
    assert call["id"] == "t1"
    assert call["type"] == "function"
    assert call["function"]["name"] == "jarvis_status"
    # A JSON *string*, not an object: that is the dialect's shape, and sending
    # an object is the mistake that reads as a tool nobody called.
    assert json.loads(call["function"]["arguments"]) == {"deep": True}


def test_a_tool_only_turn_carries_a_null_content_rather_than_being_dropped():
    converted = kp.to_openai_messages("", [{
        "role": "assistant",
        "content": [{"type": "tool_use", "id": "t1", "name": "x", "input": {}}],
    }])
    assert converted[0]["content"] is None
    assert converted[0]["tool_calls"][0]["id"] == "t1"


def test_tool_results_become_their_own_messages_and_come_before_shared_text():
    """The trap in the third translation. Callers put tool results in a *user*
    turn (Anthropic's convention); this dialect keys each one to its own `tool`
    message. If the ordering were not forced, an answer to a tool call would
    arrive after the next question and the model would answer the wrong one."""
    converted = kp.to_openai_messages("", [{
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": '{"ok": true}'},
            {"type": "text", "text": "and what about the backend"},
        ],
    }])
    assert converted[0] == {"role": "tool", "tool_call_id": "t1", "content": '{"ok": true}'}
    assert converted[1] == {"role": "user", "content": "and what about the backend"}


def test_a_tool_result_given_as_blocks_is_flattened_rather_than_stringified():
    converted = kp.to_openai_messages("", [{
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "t1",
                     "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}],
    }])
    assert converted[0]["content"] == "ab"


def test_thinking_blocks_are_not_forwarded_to_another_vendor():
    """They carry a signature only the vendor that produced them can verify, so
    forwarding them would at best waste tokens."""
    converted = kp.to_openai_messages("", [{
        "role": "assistant",
        "content": [{"type": "thinking", "thinking": "hmm", "signature": "sig"},
                    {"type": "text", "text": "answer"}],
    }])
    assert converted == [{"role": "assistant", "content": "answer"}]


def test_a_turn_that_reduces_to_nothing_is_dropped():
    assert kp.to_openai_messages("", [{"role": "assistant", "content": []}]) == []


def test_tools_become_functions_and_input_schema_becomes_parameters():
    schema = {"type": "object", "properties": {"target": {"type": "string"}}}
    converted = kp.to_openai_tools([
        {"name": "remote_diagnose", "description": "look at a machine", "input_schema": schema}])
    assert converted == [{"type": "function", "function": {
        "name": "remote_diagnose", "description": "look at a machine", "parameters": schema}}]


def test_no_tools_sends_no_tools_field_at_all():
    """"No tools" and "an empty tools array" are different requests, and the
    client role is offered none - so an empty array turning into a 400 would
    break the only capability they have."""
    assert kp.to_openai_tools([]) is None
    assert kp.to_openai_tools(None) is None


def test_a_tool_without_a_schema_still_declares_an_object():
    converted = kp.to_openai_tools([{"name": "ping"}])
    assert converted[0]["function"]["parameters"] == {"type": "object", "properties": {}}


# --- the inbound translation ----------------------------------------------------


def test_a_plain_reply_becomes_one_text_block():
    assert kp.from_openai_message({"content": "hello"}) == [{"type": "text", "text": "hello"}]


def test_content_parts_are_flattened_rather_than_refused():
    assert kp.from_openai_message(
        {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}
    ) == [{"type": "text", "text": "ab"}]


def test_a_tool_call_becomes_a_tool_use_block_with_decoded_arguments():
    blocks = kp.from_openai_message({"content": None, "tool_calls": [
        {"id": "call_9", "function": {"name": "jarvis_status", "arguments": '{"deep": true}'}}]})
    assert blocks == [{"type": "tool_use", "id": "call_9", "name": "jarvis_status",
                       "input": {"deep": True}}]


def test_a_tool_call_with_no_id_gets_a_positional_one():
    """The id pairs a result back to its call. A turn whose calls have no ids
    could never be answered, so one is synthesised rather than left empty."""
    blocks = kp.from_openai_message({"tool_calls": [
        {"function": {"name": "x", "arguments": "{}"}}]})
    assert blocks[0]["id"] == "call_0"


def test_empty_arguments_mean_no_arguments_rather_than_a_refusal():
    """A tool with no parameters is legitimately called with nothing, and
    several servers send an empty string for it."""
    assert kp._decoded_arguments("", "ping") == {}
    assert kp._decoded_arguments(None, "ping") == {}
    assert kp._decoded_arguments("{}", "ping") == {}


def test_unparseable_arguments_are_refused_rather_than_emptied():
    """The refusal that earns this file's keep. Passing `{}` along instead would
    execute the tool with no arguments, and a tool that ran with the wrong
    arguments looks exactly like a tool that worked."""
    with pytest.raises(kp.KimiCallFailed) as refused:
        kp._decoded_arguments('{"target": ', "remote_diagnose")
    assert "remote_diagnose" in str(refused.value)


def test_arguments_that_parse_to_the_wrong_type_are_refused():
    with pytest.raises(kp.KimiCallFailed):
        kp._decoded_arguments("[1, 2, 3]", "remote_diagnose")


def test_a_tool_call_wins_over_the_reported_finish_reason():
    """Some servers in this dialect report `stop` on a turn that also asked for
    a tool. Believing them would drop the call silently and the caller would
    answer as though the tool had been consulted."""
    blocks = [{"type": "tool_use", "id": "t1", "name": "x", "input": {}}]
    assert kp.stop_reason_for("stop", blocks) == "tool_use"
    assert kp.stop_reason_for(None, blocks) == "tool_use"


def test_finish_reasons_map_into_the_vocabulary_callers_branch_on():
    assert kp.stop_reason_for("stop", []) == "end_turn"
    assert kp.stop_reason_for("tool_calls", []) == "tool_use"
    assert kp.stop_reason_for("length", []) == "max_tokens"
    # Fails open to a finished turn rather than to a tool call: an unknown
    # reason must never be read as "the model wants a tool run".
    assert kp.stop_reason_for("something_new", []) == "end_turn"


# --- the response object --------------------------------------------------------


def _transport(body):
    def send(url, headers, payload, stream, timeout):
        send.seen = {"url": url, "headers": headers, "payload": payload,
                     "stream": stream, "timeout": timeout}
        return body
    return send


def test_complete_returns_something_the_existing_callers_can_read():
    """backend/main.py walks attributes and then calls model_dump(); the
    Gateway reads dictionaries. Both, on the same object."""
    send = _transport({
        "model": "k3-256k",
        "choices": [{"finish_reason": "tool_calls", "message": {
            "content": "checking", "tool_calls": [
                {"id": "t1", "function": {"name": "jarvis_status", "arguments": '{"a": 1}'}}]}}],
        "usage": {"prompt_tokens": 93, "completion_tokens": 8},
    })
    provider = kp.KimiProvider(api_key="not-a-real-key", transport=send)
    answer = provider.complete("sys", [{"role": "user", "content": "hi"}], [], max_tokens=64)

    assert answer.stop_reason == "tool_use"
    assert [block.type for block in answer.content] == ["text", "tool_use"]
    assert answer.content[1].name == "jarvis_status"
    assert answer.content[1].input == {"a": 1}
    assert answer.content[1].model_dump() == {
        "type": "tool_use", "id": "t1", "name": "jarvis_status", "input": {"a": 1}}
    assert answer.usage.input_tokens == 93
    assert answer.usage.output_tokens == 8


def test_model_dump_hands_back_a_copy_rather_than_the_block():
    send = _transport({"choices": [{"finish_reason": "stop", "message": {"content": "hi"}}]})
    answer = kp.KimiProvider(api_key="k", transport=send).complete("", [], [])
    dumped = answer.content[0].model_dump()
    dumped["text"] = "tampered"
    assert answer.content[0].text == "hi"


def test_usage_the_provider_did_not_report_is_none_and_never_zero():
    """The ledger treats zero as a call that cost nothing. "Not reported" is a
    different fact and has to survive as one."""
    send = _transport({"choices": [{"finish_reason": "stop", "message": {"content": "hi"}}]})
    answer = kp.KimiProvider(api_key="k", transport=send).complete("", [], [])
    assert answer.usage.input_tokens is None
    assert answer.usage.output_tokens is None


def test_a_reply_with_no_choices_is_refused_rather_than_returned_empty():
    send = _transport({"choices": []})
    with pytest.raises(kp.KimiCallFailed):
        kp.KimiProvider(api_key="k", transport=send).complete("", [], [])


def test_the_request_carries_the_model_and_the_bearer_token():
    send = _transport({"choices": [{"finish_reason": "stop", "message": {"content": "x"}}]})
    provider = kp.KimiProvider(model="k3-256k", api_key="secret-key",
                               base_url="https://example.invalid/v1", transport=send)
    provider.complete("sys", [{"role": "user", "content": "hi"}], [{"name": "t"}], max_tokens=7)

    assert send.seen["url"] == "https://example.invalid/v1/chat/completions"
    assert send.seen["headers"]["Authorization"] == "Bearer secret-key"
    assert send.seen["payload"]["model"] == "k3-256k"
    assert send.seen["payload"]["max_tokens"] == 7
    assert send.seen["payload"]["tools"][0]["function"]["name"] == "t"
    assert "stream" not in send.seen["payload"]


def test_no_credential_is_its_own_refusal(monkeypatch):
    """"No key" and "the endpoint refused us" need different actions from Krish,
    so they are different exceptions rather than one failure string."""
    monkeypatch.delenv(kp.API_KEY_ENV, raising=False)
    with pytest.raises(kp.KimiCredentialMissing):
        kp.KimiProvider(transport=_transport({})).complete("", [], [])


def test_the_verified_endpoint_and_model_are_the_defaults(monkeypatch):
    """Both were measured by Deployments/probe-kimi-api.ps1 at 2026-09-16 22:40,
    against a credential the two Moonshot bases had refused. They are pinned
    here so that a well-meaning correction to the documented address fails a
    test instead of failing a conversation."""
    monkeypatch.delenv(kp.BASE_URL_ENV, raising=False)
    monkeypatch.delenv(kp.MODEL_ENV, raising=False)
    assert kp.configured_base_url() == "https://api.kimi.com/coding/v1"
    assert kp.configured_model() == "k3-256k"


def test_configuration_overrides_the_defaults(monkeypatch):
    monkeypatch.setenv(kp.BASE_URL_ENV, "https://elsewhere.invalid/v1/")
    monkeypatch.setenv(kp.MODEL_ENV, "k3")
    assert kp.configured_base_url() == "https://elsewhere.invalid/v1"
    assert kp.configured_model() == "k3"


def test_an_unreadable_timeout_is_refused_rather_than_defaulted(monkeypatch):
    monkeypatch.setenv(kp.TIMEOUT_ENV, "soon")
    with pytest.raises(ValueError):
        kp.configured_timeout()


# --- streaming ------------------------------------------------------------------


def _sse(*chunks):
    lines = [f"data: {json.dumps(chunk)}" for chunk in chunks]
    lines.append("data: [DONE]")
    return lines


def test_streaming_yields_text_as_it_arrives_then_one_final_event():
    lines = _sse(
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        {"usage": {"prompt_tokens": 11, "completion_tokens": 2}, "choices": []},
    )
    provider = kp.KimiProvider(api_key="k", transport=lambda *a: lines)
    events = list(provider.stream("", [{"role": "user", "content": "hi"}], []))

    assert events[0] == {"type": "text", "text": "Hel"}
    assert events[1] == {"type": "text", "text": "lo"}
    final = events[-1]
    assert final["type"] == "final"
    assert final["content"] == [{"type": "text", "text": "Hello"}]
    assert final["stop_reason"] == "end_turn"
    assert final["usage"] == {"input_tokens": 11, "output_tokens": 2}


def test_a_streamed_tool_call_is_assembled_from_its_fragments():
    """The arguments arrive in pieces and the name lands once. Nothing about the
    call is yielded mid-stream: a partially decoded argument string is not a
    tool call, and a caller that acted on one would act on half an
    instruction."""
    lines = _sse(
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "t1", "function": {"name": "remote_diagnose", "arguments": ""}}]}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '{"targ'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": 'et": "dev"}'}}]}}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    )
    provider = kp.KimiProvider(api_key="k", transport=lambda *a: lines)
    events = list(provider.stream("", [], [{"name": "remote_diagnose"}]))

    assert [event["type"] for event in events] == ["final"]
    final = events[0]
    assert final["stop_reason"] == "tool_use"
    assert final["content"] == [{"type": "tool_use", "id": "t1", "name": "remote_diagnose",
                                 "input": {"target": "dev"}}]


def test_several_streamed_tool_calls_keep_their_order():
    lines = _sse(
        {"choices": [{"delta": {"tool_calls": [
            {"index": 1, "id": "b", "function": {"name": "second", "arguments": "{}"}},
            {"index": 0, "id": "a", "function": {"name": "first", "arguments": "{}"}}]}}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    )
    final = list(kp.KimiProvider(api_key="k", transport=lambda *a: lines).stream("", [], []))[-1]
    assert [block["name"] for block in final["content"]] == ["first", "second"]


def test_one_unreadable_chunk_does_not_discard_the_rest_of_the_reply():
    """A turn that loses a fragment reads as a short answer. Discarding the
    whole stream over one bad line would read as the model refusing."""
    lines = ["data: {not json", 'data: {"choices": [{"delta": {"content": "still here"}}]}',
             "data: [DONE]"]
    final = list(kp.KimiProvider(api_key="k", transport=lambda *a: lines).stream("", [], []))[-1]
    assert final["content"] == [{"type": "text", "text": "still here"}]


def test_the_streaming_request_asks_for_usage_counts():
    seen = {}

    def send(url, headers, payload, stream, timeout):
        seen.update(payload=payload, stream=stream)
        return _sse({"choices": [{"delta": {}, "finish_reason": "stop"}]})

    list(kp.KimiProvider(api_key="k", transport=send).stream("", [], []))
    assert seen["stream"] is True
    assert seen["payload"]["stream"] is True
    assert seen["payload"]["stream_options"] == {"include_usage": True}


def test_the_production_path_is_not_the_seam():
    """A seam the suite always takes is a seam that hides the code that runs.
    Every real construction leaves `transport` None, so the HTTP path is the
    default and this file's stand-in has to be asked for explicitly."""
    assert kp.KimiProvider()._transport is None
    from app import model_routing

    router = model_routing.build_router()
    if router.remote is not None:
        assert router.remote._transport is None
