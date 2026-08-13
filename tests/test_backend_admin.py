"""Regression tests for the server monitor's admin routes (GET /admin/clients,
GET /admin/clients/{username}/transcript) - unauthenticated by design, see
backend/main.py's comment on why. Also covers the /chat integration: does a
real chat call actually populate the transcript, does a consent pause/resume
round-trip record the user's question only once, and do two users' logged
conversations stay isolated.

FakeBlock/FakeResponse/text_response/tool_use_response are duplicated from
test_backend_chat.py per this project's established convention for
cross-test-file helpers (see test_backend_preferences.py's own copy and its
docstring for why - tests/ has no __init__.py, so cross-file imports are
ambiguous).
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


def _register_and_auth_header(backend_client, username="alice", password="hunter2"):
    token = backend_client.post("/auth/register", json={"username": username, "password": password}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_list_clients_starts_empty(backend_client):
    response = backend_client.get("/admin/clients")
    assert response.status_code == 200
    assert response.json()["clients"] == []


def test_transcript_for_unknown_client_returns_empty_entries(backend_client):
    response = backend_client.get("/admin/clients/nobody/transcript")
    assert response.status_code == 200
    assert response.json() == {"username": "nobody", "entries": []}


def test_chat_call_populates_the_transcript(backend_client, monkeypatch):
    headers = _register_and_auth_header(backend_client)
    monkeypatch.setattr("backend.main.call_reasoning_model", MagicMock(return_value=text_response("Hello!")))

    backend_client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]}, headers=headers)

    clients = backend_client.get("/admin/clients").json()["clients"]
    assert clients == ["alice"]
    entries = backend_client.get("/admin/clients/alice/transcript").json()["entries"]
    assert [e["role"] for e in entries] == ["user", "assistant"]
    assert entries[0]["text"] == "hi"
    assert entries[1]["text"] == "Hello!"


def test_consent_pause_resume_records_the_question_only_once(backend_client, monkeypatch, mock_portfolio_path):
    headers = _register_and_auth_header(backend_client)
    backend_client.post("/permissions/grant", json={"resource": "portfolio"}, headers=headers)
    call_model = MagicMock(side_effect=[tool_use_response(), text_response("Here you go.")])
    monkeypatch.setattr("backend.main.call_reasoning_model", call_model)

    paused = backend_client.post(
        "/chat", json={"messages": [{"role": "user", "content": "What stocks do I own?"}]}, headers=headers
    ).json()
    backend_client.post(
        "/chat",
        json={"messages": paused["messages"], "consent_answer": "always", "consent_key": FORWARDING_KEY},
        headers=headers,
    )

    entries = backend_client.get("/admin/clients/alice/transcript").json()["entries"]
    user_entries = [e for e in entries if e["role"] == "user"]
    assistant_entries = [e for e in entries if e["role"] == "assistant"]
    assert len(user_entries) == 1
    assert user_entries[0]["text"] == "What stocks do I own?"
    assert len(assistant_entries) == 1
    assert assistant_entries[0]["text"] == "Here you go."


def test_two_users_transcripts_stay_isolated(backend_client, monkeypatch):
    headers_a = _register_and_auth_header(backend_client, "alice")
    headers_b = _register_and_auth_header(backend_client, "bob")
    monkeypatch.setattr("backend.main.call_reasoning_model", MagicMock(return_value=text_response("Hi alice")))

    backend_client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]}, headers=headers_a)

    clients = backend_client.get("/admin/clients").json()["clients"]
    assert clients == ["alice"]
    assert backend_client.get("/admin/clients/bob/transcript").json()["entries"] == []
