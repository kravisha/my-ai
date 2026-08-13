"""Regression tests for GET /preferences, POST /preferences/reset - thin
wiring tests, PrivacyPreferenceStore itself is already covered by
tests/test_privacy_preferences.py. There's deliberately no direct "set
preference" route (matching the CLI/GUI - a disposition is only ever set
via the /chat consent flow, see test_backend_chat.py).

FakeBlock/FakeResponse/text_response/tool_use_response are duplicated from
test_backend_chat.py rather than imported - tests/ has no __init__.py (see
conftest.py's own comment about this), so cross-test-file imports are
ambiguous between "test_backend_chat" and "tests.test_backend_chat"; this
project's convention (see test_tools_portfolio.py's TEST_ACCOUNT_ID) is to
duplicate small local constants/helpers rather than import across test
modules.
"""

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


def _auth_header(backend_client, username="alice"):
    token = backend_client.post("/auth/register", json={"username": username, "password": "hunter2"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_list_preferences_starts_empty(backend_client):
    headers = _auth_header(backend_client)
    response = backend_client.get("/preferences", headers=headers)
    assert response.status_code == 200
    assert response.json() == {}


def test_reset_nonexistent_preference_reports_not_forgotten(backend_client):
    headers = _auth_header(backend_client)
    response = backend_client.post("/preferences/reset", json={"key": FORWARDING_KEY}, headers=headers)
    assert response.status_code == 200
    assert response.json()["forgotten"] is False


def test_preferences_routes_require_authentication(backend_client):
    assert backend_client.get("/preferences").status_code == 401
    assert backend_client.post("/preferences/reset", json={"key": FORWARDING_KEY}).status_code == 401


def test_two_users_preferences_are_isolated(backend_client, monkeypatch, mock_portfolio_path):
    """Establishes a real 'always' disposition for alice via the consent
    flow (the only way one gets set), then confirms bob never sees it."""
    headers_a = _auth_header(backend_client, "alice")
    headers_b = _auth_header(backend_client, "bob")
    backend_client.post("/permissions/grant", json={"resource": "portfolio"}, headers=headers_a)

    monkeypatch.setattr(
        "backend.main.call_reasoning_model",
        MagicMock(side_effect=[tool_use_response(), text_response("noted")]),
    )
    paused = backend_client.post(
        "/chat", json={"messages": [{"role": "user", "content": "What stocks do I own?"}]}, headers=headers_a
    ).json()
    backend_client.post(
        "/chat",
        json={"messages": paused["messages"], "consent_answer": "always", "consent_key": FORWARDING_KEY},
        headers=headers_a,
    )

    assert backend_client.get("/preferences", headers=headers_a).json()[FORWARDING_KEY]["disposition"] == "always"
    assert backend_client.get("/preferences", headers=headers_b).json() == {}
