"""Regression tests for backend/main.py's POST /chat route - the HTTP
migration of the old app.main.chat_turn test suite (see git history for
tests/test_chat_turn.py, removed once chat_turn itself was removed). Same
regression intent, now exercised through the route: tool-use loop
correctness, the consent pause/resume protocol, distinct denial wording,
and no cross-request caching.

call_reasoning_model is mocked exactly like the old suite - no real network
call is ever made. Anthropic's SDK content blocks need a .model_dump()
method since backend/main.py serializes them for the JSON response; the
fakes below provide one so they act like real SDK objects for both purposes
(attribute access during the loop, model_dump() when appending to the
outgoing message list).
"""

import json
from unittest.mock import MagicMock

from app.tools.portfolio import FORWARDING_KEY


class FakeBlock:
    def __init__(self, type, text=None, name=None, id=None, input=None):
        self.type = type
        self.text = text
        self.name = name
        self.id = id
        self.input = input if input is not None else {}

    def model_dump(self):
        if self.type == "text":
            return {"type": "text", "text": self.text}
        if self.type == "tool_use":
            return {"type": "tool_use", "id": self.id, "name": self.name, "input": self.input}
        return {"type": self.type}


class FakeResponse:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


def text_response(text):
    return FakeResponse("end_turn", [FakeBlock("text", text=text)])


def tool_use_response(tool_name="retrieve_portfolio", tool_id="tool_1"):
    return FakeResponse("tool_use", [FakeBlock("tool_use", name=tool_name, id=tool_id)])


def _register_and_auth_header(backend_client, username="alice", password="hunter2"):
    token = backend_client.post("/auth/register", json={"username": username, "password": password}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _grant_portfolio(backend_client, headers):
    backend_client.post("/permissions/grant", json={"resource": "portfolio"}, headers=headers)


def test_simple_text_reply(backend_client, monkeypatch):
    headers = _register_and_auth_header(backend_client)
    monkeypatch.setattr("backend.main.call_reasoning_model", MagicMock(return_value=text_response("Hello!")))

    response = backend_client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]}, headers=headers)

    assert response.status_code == 200
    assert response.json()["reply"] == "Hello!"


def test_tool_use_with_stored_disposition_reaches_model_without_reprompt(backend_client, monkeypatch, mock_portfolio_path):
    """There's no direct 'set preference' route by design (matching the CLI/
    GUI, which only ever set a disposition via the consent flow itself) - so
    establishing an 'always' disposition here means actually resolving one
    consent pause first, then confirming a *second*, separate conversation
    doesn't get paused again."""
    headers = _register_and_auth_header(backend_client)
    _grant_portfolio(backend_client, headers)
    call_model = MagicMock(side_effect=[tool_use_response(), text_response("noted")])
    monkeypatch.setattr("backend.main.call_reasoning_model", call_model)
    first = backend_client.post(
        "/chat", json={"messages": [{"role": "user", "content": "What stocks do I own?"}]}, headers=headers
    ).json()
    backend_client.post(
        "/chat",
        json={"messages": first["messages"], "consent_answer": "always", "consent_key": FORWARDING_KEY},
        headers=headers,
    )

    call_model.side_effect = [tool_use_response(), text_response("Here are your holdings.")]
    response = backend_client.post(
        "/chat", json={"messages": [{"role": "user", "content": "What stocks do I own?"}]}, headers=headers
    )

    body = response.json()
    assert body["reply"] == "Here are your holdings."
    assert "needs_consent" not in body
    tool_result = next(
        b for m in body["messages"] if m["role"] == "user" and isinstance(m["content"], list)
        for b in m["content"] if b.get("type") == "tool_result"
    )
    assert "holdings" in json.loads(tool_result["content"])
    assert tool_result["is_error"] is False


def test_tool_use_needing_consent_returns_needs_consent_without_calling_model_twice_upfront(
    backend_client, monkeypatch, mock_portfolio_path,
):
    headers = _register_and_auth_header(backend_client)
    _grant_portfolio(backend_client, headers)
    monkeypatch.setattr("backend.main.call_reasoning_model", MagicMock(return_value=tool_use_response()))

    response = backend_client.post(
        "/chat", json={"messages": [{"role": "user", "content": "What stocks do I own?"}]}, headers=headers
    )

    body = response.json()
    assert "needs_consent" in body
    assert body["needs_consent"]["consent_key"] == FORWARDING_KEY
    assert "messages" in body


def test_consent_resume_with_always_persists_and_returns_holdings(backend_client, monkeypatch, mock_portfolio_path):
    headers = _register_and_auth_header(backend_client)
    _grant_portfolio(backend_client, headers)
    call_model = MagicMock(side_effect=[tool_use_response(), text_response("Here you go.")])
    monkeypatch.setattr("backend.main.call_reasoning_model", call_model)

    paused = backend_client.post(
        "/chat", json={"messages": [{"role": "user", "content": "What stocks do I own?"}]}, headers=headers
    ).json()

    resumed = backend_client.post(
        "/chat",
        json={"messages": paused["messages"], "consent_answer": "always", "consent_key": FORWARDING_KEY},
        headers=headers,
    )

    assert resumed.status_code == 200
    body = resumed.json()
    assert body["reply"] == "Here you go."
    prefs = backend_client.get("/preferences", headers=headers).json()
    assert prefs[FORWARDING_KEY]["disposition"] == "always"


def test_consent_resume_with_once_returns_holdings_without_persisting(backend_client, monkeypatch, mock_portfolio_path):
    """Regression test for the exact bug fixed earlier in the CLI/GUI
    versions: 'once' must actually grant the pending call without writing a
    disposition - now verified at the HTTP layer too."""
    headers = _register_and_auth_header(backend_client)
    _grant_portfolio(backend_client, headers)
    call_model = MagicMock(side_effect=[tool_use_response(), text_response("Here you go.")])
    monkeypatch.setattr("backend.main.call_reasoning_model", call_model)

    paused = backend_client.post(
        "/chat", json={"messages": [{"role": "user", "content": "What stocks do I own?"}]}, headers=headers
    ).json()

    resumed = backend_client.post(
        "/chat", json={"messages": paused["messages"], "consent_answer": "once"}, headers=headers
    )

    assert resumed.json()["reply"] == "Here you go."
    prefs = backend_client.get("/preferences", headers=headers).json()
    assert FORWARDING_KEY not in prefs


def test_denial_reasons_reach_the_model_distinctly(backend_client, monkeypatch, mock_portfolio_path):
    headers = _register_and_auth_header(backend_client)
    call_model = MagicMock(side_effect=[tool_use_response(), text_response("denied")])
    monkeypatch.setattr("backend.main.call_reasoning_model", call_model)

    not_granted = backend_client.post(
        "/chat", json={"messages": [{"role": "user", "content": "Analyze my portfolio"}]}, headers=headers
    ).json()
    not_granted_result = next(
        b for m in not_granted["messages"] if m["role"] == "user" and isinstance(m["content"], list)
        for b in m["content"] if b.get("type") == "tool_result"
    )
    not_granted_error = json.loads(not_granted_result["content"])["error"]

    _grant_portfolio(backend_client, headers)
    backend_client.post("/preferences/reset", json={"key": FORWARDING_KEY}, headers=headers)
    call_model.side_effect = [tool_use_response(), text_response("still denied")]
    paused = backend_client.post(
        "/chat", json={"messages": [{"role": "user", "content": "Analyze my portfolio"}]}, headers=headers
    ).json()
    never = backend_client.post(
        "/chat",
        json={"messages": paused["messages"], "consent_answer": "never", "consent_key": FORWARDING_KEY},
        headers=headers,
    ).json()
    never_result = next(
        b for m in never["messages"] if m["role"] == "user" and isinstance(m["content"], list)
        for b in m["content"] if b.get("type") == "tool_result"
    )
    never_error = json.loads(never_result["content"])["error"]

    assert not_granted_error != never_error


def test_each_chat_call_invokes_the_model_fresh(backend_client, monkeypatch, mock_portfolio_path):
    headers = _register_and_auth_header(backend_client)
    _grant_portfolio(backend_client, headers)
    backend_client.post("/preferences/reset", json={"key": FORWARDING_KEY}, headers=headers)
    call_model = MagicMock(side_effect=[
        tool_use_response(tool_id="t1"), text_response("First answer."),
        tool_use_response(tool_id="t2"), text_response("Second answer."),
    ])
    monkeypatch.setattr("backend.main.call_reasoning_model", call_model)

    paused = backend_client.post(
        "/chat", json={"messages": [{"role": "user", "content": "What stocks do I own?"}]}, headers=headers
    ).json()
    resumed = backend_client.post(
        "/chat",
        json={"messages": paused["messages"], "consent_answer": "always", "consent_key": FORWARDING_KEY},
        headers=headers,
    ).json()

    second = backend_client.post(
        "/chat", json={"messages": resumed["messages"] + [{"role": "user", "content": "What price?"}]},
        headers=headers,
    ).json()

    # 2 model calls to establish "always" via the pause/resume dance (no
    # direct "set preference" route exists, matching the CLI/GUI) + 2 more
    # for the second, unpaused conversation's own tool_use-then-reply cycle.
    assert call_model.call_count == 4
    assert second["reply"] == "Second answer."


def test_permission_revoked_between_calls_is_reflected_immediately(backend_client, monkeypatch, mock_portfolio_path):
    headers = _register_and_auth_header(backend_client)
    _grant_portfolio(backend_client, headers)
    backend_client.post("/preferences/reset", json={"key": FORWARDING_KEY}, headers=headers)
    call_model = MagicMock(side_effect=[tool_use_response(), text_response("Here you go.")])
    monkeypatch.setattr("backend.main.call_reasoning_model", call_model)

    paused = backend_client.post(
        "/chat", json={"messages": [{"role": "user", "content": "What stocks do I own?"}]}, headers=headers
    ).json()
    resumed = backend_client.post(
        "/chat",
        json={"messages": paused["messages"], "consent_answer": "always", "consent_key": FORWARDING_KEY},
        headers=headers,
    ).json()
    tool_result = next(
        b for m in resumed["messages"] if m["role"] == "user" and isinstance(m["content"], list)
        for b in m["content"] if b.get("type") == "tool_result"
    )
    assert "holdings" in json.loads(tool_result["content"])

    backend_client.post("/permissions/revoke", json={"resource": "portfolio"}, headers=headers)
    call_model.side_effect = [tool_use_response(), text_response("Can't help with that.")]
    second = backend_client.post(
        "/chat", json={"messages": resumed["messages"] + [{"role": "user", "content": "Analyze it"}]},
        headers=headers,
    ).json()
    # second["messages"] now holds two tool_results (the earlier successful
    # one plus this call's new one) since the conversation history was
    # chained rather than started fresh - take the *last* one, not the first.
    all_tool_results = [
        b for m in second["messages"] if m["role"] == "user" and isinstance(m["content"], list)
        for b in m["content"] if b.get("type") == "tool_result"
    ]
    assert "error" in json.loads(all_tool_results[-1]["content"])


def test_chat_requires_authentication(backend_client):
    response = backend_client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 401
