"""The Gateway's window onto the backend, and the isolation addendum 16 §23 asks
for.

The contract tests run against the **real backend application** through a
TestClient rather than against a description of its JSON. A test that asserted
the shape this module expects would keep passing after the backend changed its
routes, which is exactly the drift worth catching between two services that are
developed together and deployed as separate processes.
"""

import pytest
import requests

from gateway import jarvis


@pytest.fixture
def backend_transport(panel_conn, tmp_path, monkeypatch):
    """A transport that reaches the real `backend.main:app`, with its admin gate
    satisfied and its database pointed at this test's file."""
    from fastapi.testclient import TestClient

    import backend.main as backend_main
    from backend import fi_db

    def _panel_db():
        connection = fi_db.get_connection(tmp_path / "panel.db")
        try:
            yield connection
        finally:
            connection.close()

    backend_main.app.dependency_overrides[backend_main.panel_db] = _panel_db
    backend_main.app.dependency_overrides[backend_main.require_admin] = lambda: "test-admin"
    client = TestClient(backend_main.app)

    def transport(path, token):
        response = client.get(path)
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {}

    monkeypatch.setenv(jarvis.BACKEND_USER_ENV, "admin")
    monkeypatch.setenv(jarvis.BACKEND_PASSWORD_ENV, "password")
    monkeypatch.setattr(jarvis.JarvisClient, "_login", lambda self: "test-token")
    try:
        yield transport
    finally:
        backend_main.app.dependency_overrides.clear()


@pytest.fixture
def unconfigured(monkeypatch):
    monkeypatch.delenv(jarvis.BACKEND_USER_ENV, raising=False)
    monkeypatch.delenv(jarvis.BACKEND_PASSWORD_ENV, raising=False)


# --- Configuration ---


def test_without_credentials_the_system_is_simply_unavailable(unconfigured):
    """Default closed, and *not* an error: a Gateway whose operator has not wired
    it to a backend still runs, still converses, still holds the board."""
    answer = jarvis.JarvisClient().status()

    assert answer["available"] is False
    assert jarvis.BACKEND_USER_ENV in answer["reason"]


def test_the_backend_url_has_a_sensible_default(monkeypatch):
    monkeypatch.delenv(jarvis.BACKEND_URL_ENV, raising=False)
    assert jarvis.backend_url() == "http://localhost:8000"

    monkeypatch.setenv(jarvis.BACKEND_URL_ENV, "http://elsewhere:9000/")
    assert jarvis.backend_url() == "http://elsewhere:9000/"


# --- Against the real backend ---


def test_status_reports_the_organization_from_the_real_routes(backend_transport, panel_conn):
    """The contract, end to end: rows written through fi_db come back through the
    backend's own route and out of this client in the shape the tools promise."""
    from backend import fi_db

    fi_db.register_agent(panel_conn, "explorer-1", "explorer", 4242)
    fi_db.register_agent(panel_conn, "analysis-1", "analysis", 4243)

    answer = jarvis.JarvisClient(transport=backend_transport).status()

    assert answer["available"] is True
    assert {agent["identity"] for agent in answer["agents"]} == {"explorer-1", "analysis-1"}
    assert answer["counts"]["active"] == 2
    assert answer["crashed"] == []


def test_the_two_lifecycle_axes_are_reported_separately(backend_transport, panel_conn):
    """A dormant agent and a crashed one both have no process, and only one is a
    fault. Merging them is the confusion the two-axis model exists to remove, so
    the Gateway must not undo it on the way out."""
    from backend import fi_db

    fi_db.register_agent(panel_conn, "explorer-1", "explorer", 4242)
    fi_db.register_agent(panel_conn, "dummy-1", "dummy", 4243)
    fi_db.mark_process_crashed(panel_conn, "explorer-1")
    fi_db.request_retirement(panel_conn, "dummy-1")

    answer = jarvis.JarvisClient(transport=backend_transport).status()
    by_identity = {agent["identity"]: agent for agent in answer["agents"]}

    assert by_identity["explorer-1"]["process_state"] == "crashed"
    assert by_identity["explorer-1"]["lifecycle_state"] == "active"
    assert by_identity["dummy-1"]["lifecycle_state"] == "dormant"
    assert answer["crashed"] == ["explorer-1"]


def test_one_agent_can_be_asked_about_in_detail(backend_transport, panel_conn):
    from backend import fi_db

    fi_db.register_agent(panel_conn, "explorer-1", "explorer", 4242)

    answer = jarvis.JarvisClient(transport=backend_transport).agent("explorer-1")

    assert answer["available"] is True
    assert answer["identity"] == "explorer-1"


def test_an_unknown_agent_is_reported_not_raised(backend_transport):
    answer = jarvis.JarvisClient(transport=backend_transport).agent("nobody-1")

    assert answer["available"] is False
    assert "404" in answer["reason"]


# --- Failure isolation (addendum 16 §23) ---


def test_an_unreachable_backend_is_an_answer_not_an_exception(monkeypatch):
    """The §23 case at its source. Everything else the Gateway does has to carry
    on with no knowledge that anything is wrong, and that only works if being down
    is an ordinary value."""
    monkeypatch.setenv(jarvis.BACKEND_USER_ENV, "admin")
    monkeypatch.setenv(jarvis.BACKEND_PASSWORD_ENV, "password")

    def refuse(*args, **kwargs):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(requests, "get", refuse)
    monkeypatch.setattr(requests, "post", refuse)

    answer = jarvis.JarvisClient().status()

    assert answer["available"] is False
    assert "did not answer" in answer["reason"]
    assert "ConnectionError" in answer["reason"]


def test_a_backend_that_accepts_and_never_answers_times_out(monkeypatch):
    """A hang is worse than a refusal: it holds a model turn open for as long as
    the socket allows. The timeouts are asserted rather than assumed, because
    nothing else would notice if they were dropped."""
    captured = {}

    def record(url, **kwargs):
        captured.update(kwargs)
        raise requests.Timeout("too slow")

    monkeypatch.setenv(jarvis.BACKEND_USER_ENV, "admin")
    monkeypatch.setenv(jarvis.BACKEND_PASSWORD_ENV, "password")
    monkeypatch.setattr(requests, "post", record)

    answer = jarvis.JarvisClient().status()

    assert captured["timeout"] == (jarvis.CONNECT_TIMEOUT_SECONDS, jarvis.READ_TIMEOUT_SECONDS)
    assert answer["available"] is False


def test_refused_credentials_say_what_to_fix(monkeypatch):
    monkeypatch.setenv(jarvis.BACKEND_USER_ENV, "admin")
    monkeypatch.setenv(jarvis.BACKEND_PASSWORD_ENV, "password")

    client = jarvis.JarvisClient(transport=lambda path, token: (403, {}))
    monkeypatch.setattr(jarvis.JarvisClient, "_login", lambda self: "test-token")

    answer = client.status()

    assert answer["available"] is False
    assert "MY_AI_ADMIN_USERS" in answer["reason"]


def test_a_stale_session_is_renewed_once_and_only_once(monkeypatch):
    """The backend's sessions expire after seven days, so a long-running Gateway
    will meet a 401 eventually. Renewing forever would turn a wrong password into
    a hammering of the login route."""
    monkeypatch.setenv(jarvis.BACKEND_USER_ENV, "admin")
    monkeypatch.setenv(jarvis.BACKEND_PASSWORD_ENV, "password")
    logins = []

    def login(self):
        logins.append(1)
        return f"token-{len(logins)}"

    monkeypatch.setattr(jarvis.JarvisClient, "_login", login)
    attempts = []

    def always_stale(path, token):
        attempts.append(token)
        return 401, {}

    answer = jarvis.JarvisClient(transport=always_stale).status()

    assert len(logins) == 2, "one login, then exactly one renewal"
    assert attempts == ["token-1", "token-2"]
    assert answer["available"] is False


def test_a_renewed_session_is_reused_for_later_questions(monkeypatch):
    monkeypatch.setenv(jarvis.BACKEND_USER_ENV, "admin")
    monkeypatch.setenv(jarvis.BACKEND_PASSWORD_ENV, "password")
    logins = []
    monkeypatch.setattr(
        jarvis.JarvisClient, "_login", lambda self: logins.append(1) or f"token-{len(logins)}"
    )

    client = jarvis.JarvisClient(transport=lambda path, token: (200, {"agents": []}))
    client.status()
    client.status()

    assert len(logins) == 1, "the session is held in memory, not fetched per question"


# --- The Gateway's own /status route, and isolation at the service level ---


def test_the_status_route_requires_a_session(gateway_client):
    assert gateway_client.get("/status").status_code == 401


def test_the_status_route_answers_200_when_the_backend_is_down(
    gateway_client, gateway_token, monkeypatch
):
    """Not 502, and not a stack trace. The Gateway's own liveness is not
    contingent on the system it looks at - a status page that 500s when the thing
    it reports on is down has confused the two."""
    monkeypatch.setenv(jarvis.BACKEND_USER_ENV, "admin")
    monkeypatch.setenv(jarvis.BACKEND_PASSWORD_ENV, "password")
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("refused"))
    )

    response = gateway_client.get("/status", headers={"Authorization": f"Bearer {gateway_token}"})

    assert response.status_code == 200
    assert response.json()["available"] is False


def test_everything_else_works_while_the_backend_is_down(
    gateway_client, gateway_token, gateway_conn, private_repo, monkeypatch
):
    """Addendum 16 §23, stated as one test: with the backend unreachable, the
    conversation, the Scoreboard and Git all carry on.

    This is the assertion the whole separate-process, separate-database design
    was for. If it ever fails, something has quietly made the Gateway depend on
    the system it is supposed to outlive."""
    from app import model_gateway
    from gateway import scoreboard
    from test_gateway_service import FakeProvider, authenticated_socket

    def refuse(*args, **kwargs):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setenv(jarvis.BACKEND_USER_ENV, "admin")
    monkeypatch.setenv(jarvis.BACKEND_PASSWORD_ENV, "password")
    monkeypatch.setattr(requests, "get", refuse)
    monkeypatch.setattr(requests, "post", refuse)

    headers = {"Authorization": f"Bearer {gateway_token}"}

    # The Scoreboard, over HTTP.
    filed = gateway_client.post("/scoreboard", headers=headers, json={"question": "still working?"})
    assert filed.status_code == 201
    assert gateway_client.get("/scoreboard", headers=headers).status_code == 200

    # A conversation that files an item and publishes a document - the two things
    # that touch durable state - with the backend gone throughout.
    provider = FakeProvider(
        fragments=("Both done.",),
        tool_calls=[
            ("file_scoreboard_item", {"question": "filed while the backend was down"}),
            (
                "publish_document",
                {"path": "docs/offline.md", "content": "# Offline\n", "message": "Add"},
            ),
        ],
    )
    model_gateway.set_provider(provider)
    try:
        socket, ready = authenticated_socket(gateway_client, gateway_token)
        try:
            socket.send_json({"type": "message", "text": "file it and publish it"})
            frames = []
            while True:
                frame = socket.receive_json()
                frames.append(frame)
                if frame["type"] == "done":
                    break
        finally:
            socket.__exit__(None, None, None)
    finally:
        model_gateway.set_provider(None)

    assert {"type": "tool", "name": "file_scoreboard_item", "ok": True} in frames
    assert {"type": "tool", "name": "publish_document", "ok": True} in frames
    assert {item["question"] for item in scoreboard.list_items(gateway_conn)} == {
        "still working?",
        "filed while the backend was down",
    }

    import subprocess

    published = subprocess.run(
        ["git", "show", "gateway/offline:docs/offline.md"],
        cwd=private_repo.path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert published.returncode == 0, published.stderr

    # And the status question, asked in the same conversation, answers honestly.
    assert gateway_client.get("/status", headers=headers).json()["available"] is False
