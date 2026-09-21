"""One request, end to end, with the external API mocked at the wire (§7).

Every other test in this task's set substitutes something: a stand-in provider,
a stand-in transport, a snapshot built by hand. This one substitutes only
`httpx.post`, so everything between an HTTP route and an outbound request is
the real code - `call_reasoning_model`, the spend ledger, `LocalFirstRouter`,
`KimiProvider`'s dialect translation, the call log, the user-facing vocabulary.

That is the part worth one slow test: the unit tests each hold one seam, and
none of them would notice if the seams stopped lining up.
"""

import json

import pytest

from app import model_budget, model_calls, model_gateway


class _HTTPResponse:
    """What `httpx.post` returns, as `KimiProvider.complete` reads it."""

    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _reply(text, tool_call=None, finish="stop"):
    message = {"role": "assistant", "content": text}
    if tool_call is not None:
        message["tool_calls"] = [tool_call]
        finish = "tool_calls"
    return {
        "model": "k3-256k",
        "choices": [{"message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": 31, "completion_tokens": 9},
    }


@pytest.fixture
def live_router(tmp_path, monkeypatch):
    """The real provider chain, with a credential and a mocked socket."""
    monkeypatch.setenv(model_calls.LOG_DIR_ENV, str(tmp_path / "logs"))
    monkeypatch.setenv("KIMI_API_KEY", "test-key-not-real")
    monkeypatch.setenv(model_budget.PATH_ENV, str(tmp_path / "model_spend.db"))
    monkeypatch.setattr(model_gateway, "_provider", None)
    yield tmp_path / "logs"
    model_gateway.set_provider(None)


def _records(directory):
    path = directory / model_calls.LOG_FILE_NAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _register(backend_client, username="ada"):
    token = backend_client.post(
        "/auth/register", json={"username": username, "password": "hunter2"}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_a_request_travels_from_the_route_to_the_wire_and_back(
        backend_client, live_router, monkeypatch):
    sent = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent["url"] = url
        sent["payload"] = json
        sent["authorization"] = (headers or {}).get("Authorization")
        return _HTTPResponse(200, _reply("Three holdings, all equities."))

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)

    headers = _register(backend_client)
    response = backend_client.post(
        "/chat", json={"messages": [{"role": "user", "content": "what do I hold?"}]},
        headers=headers)

    assert response.status_code == 200
    assert response.json()["reply"] == "Three holdings, all equities."

    # The wire: the right endpoint, the right dialect, the credential present.
    assert sent["url"] == "https://api.kimi.com/coding/v1/chat/completions"
    assert sent["payload"]["model"] == "k3-256k"
    assert sent["payload"]["messages"][0]["role"] == "system"
    assert sent["authorization"] == "Bearer test-key-not-real"

    # The log: one record, through the router, with the vendor's own counts.
    records = _records(live_router)
    assert len(records) == 1
    assert records[0]["handler"] == "kimi_k2"
    assert records[0]["routed_by"] == "router"
    assert records[0]["escalation_reason"] == "local_error"
    assert records[0]["outcome"] == "success"
    assert (records[0]["prompt_tokens"], records[0]["completion_tokens"]) == (31, 9)
    assert records[0]["user_request_summary"] == "what do I hold?"
    assert records[0]["caller_module"] == "backend.main::chat"
    assert records[0]["confidence_score"] is None


def test_a_tool_loop_records_every_call_under_one_request_id(
        backend_client, live_router, monkeypatch, mock_portfolio_path):
    """The reason a request id exists: one question, several calls.

    The consent dance at the top is not incidental - a paused turn genuinely
    is two HTTP requests and therefore two requests in the log, because this
    backend holds no conversation state. The loop worth measuring is the one
    that runs to completion inside a single route call, so the disposition is
    stored first and then a fresh question is asked."""
    from app.tools.portfolio import FORWARDING_KEY

    tool_call = {"id": "call_1", "type": "function",
                 "function": {"name": "retrieve_portfolio", "arguments": "{}"}}
    replies = [
        _reply("", tool_call=tool_call),          # 1st question -> pauses for consent
        _reply("Noted."),                         # the resume
        _reply("", tool_call=tool_call),          # 2nd question, no pause this time
        _reply("You hold three positions."),      # ... and its answer
    ]

    def fake_post(url, headers=None, json=None, timeout=None):
        return _HTTPResponse(200, replies.pop(0))

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)

    headers = _register(backend_client)
    backend_client.post("/permissions/grant", json={"resource": "portfolio"},
                        headers=headers)
    paused = backend_client.post(
        "/chat", json={"messages": [{"role": "user", "content": "what do I hold?"}]},
        headers=headers).json()
    backend_client.post(
        "/chat", json={"messages": paused["messages"], "consent_answer": "always",
                       "consent_key": FORWARDING_KEY},
        headers=headers)

    answered = backend_client.post(
        "/chat", json={"messages": [{"role": "user", "content": "and now?"}]},
        headers=headers)
    assert answered.json()["reply"] == "You hold three positions."

    per_request = {}
    for record in _records(live_router):
        per_request.setdefault(record["request_id"], []).append(record)
    longest = max(per_request.values(), key=len)

    assert len(longest) == 2, "the uninterrupted loop's two calls share one id"
    assert [r["call_index"] for r in longest] == [0, 1]
    assert {r["user_request_summary"] for r in longest} == {"and now?"}


def test_exhausted_capacity_at_the_wire_never_reaches_the_client(
        backend_client, live_router, monkeypatch):
    """The whole fault, end to end: a 429 from the vendor, and what Krish sees."""
    from app import user_messages

    def fake_post(url, headers=None, json=None, timeout=None):
        return _HTTPResponse(429, {"error": {"message": "insufficient_quota",
                                             "type": "rate_limit_exceeded"}})

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)

    headers = _register(backend_client)
    response = backend_client.post(
        "/chat", json={"messages": [{"role": "user", "content": "what do I hold?"}]},
        headers=headers)

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail == "I can't do that reliably right now - I'll retry shortly."
    assert user_messages.is_clean(detail)
    assert "429" not in detail and "quota" not in detail.lower()

    record = _records(live_router)[0]
    assert record["outcome"] == "quota_exhausted"
    assert "429" in record["error_detail"], "the operator's version is kept"


def test_a_routing_failure_with_no_credential_is_told_to_the_user_gently(
        backend_client, tmp_path, monkeypatch):
    from app import user_messages

    monkeypatch.setenv(model_calls.LOG_DIR_ENV, str(tmp_path / "logs"))
    monkeypatch.setenv(model_budget.PATH_ENV, str(tmp_path / "model_spend.db"))
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.setattr(model_gateway, "_provider", None)
    try:
        headers = _register(backend_client)
        response = backend_client.post(
            "/chat", json={"messages": [{"role": "user", "content": "hello"}]},
            headers=headers)

        assert response.status_code == 503
        detail = response.json()["detail"]
        assert "KIMI_API_KEY" not in detail
        assert user_messages.is_clean(detail)
    finally:
        model_gateway.set_provider(None)


def test_the_assembled_runtime_provider_has_no_path_to_the_retired_vendor(live_router):
    """Held here as well as in test_model_routing.py, because this is the one
    test that builds the chain the way the process does."""
    from app.model_routing import assert_no_anthropic

    assert_no_anthropic(model_gateway.default_provider())
