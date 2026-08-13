"""Regression tests for GET /activity - thin wiring test, AuditLog itself is
already covered by tests/test_audit.py."""


def _auth_header(backend_client, username="alice"):
    token = backend_client.post("/auth/register", json={"username": username, "password": "hunter2"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_activity_starts_empty(backend_client):
    headers = _auth_header(backend_client)
    response = backend_client.get("/activity", headers=headers)
    assert response.status_code == 200
    assert response.json() == []


def test_activity_requires_authentication(backend_client):
    assert backend_client.get("/activity").status_code == 401


def test_two_users_activity_is_isolated(backend_client, monkeypatch, mock_portfolio_path):
    from unittest.mock import MagicMock

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

    def tool_use_response():
        return FakeResponse("tool_use", [FakeBlock("tool_use", name="retrieve_portfolio", id="t1")])

    headers_a = _auth_header(backend_client, "alice")
    headers_b = _auth_header(backend_client, "bob")
    # alice: not granted, ask a question -> a denial gets audited for alice only
    monkeypatch.setattr(
        "backend.main.call_reasoning_model",
        MagicMock(side_effect=[tool_use_response(), text_response("denied")]),
    )
    backend_client.post(
        "/chat", json={"messages": [{"role": "user", "content": "Analyze my portfolio"}]}, headers=headers_a
    )

    alice_activity = backend_client.get("/activity", headers=headers_a).json()
    bob_activity = backend_client.get("/activity", headers=headers_b).json()

    assert len(alice_activity) == 1
    assert alice_activity[0]["authorized"] is False
    assert bob_activity == []
