"""Regression tests for api_client.py's own logic (URL/header construction,
response parsing, error raising) via a mocked `requests` module - consistent
with this project's established pattern of mocking the one external call a
unit makes (call_reasoning_model is mocked everywhere it's touched; here
requests.post/get is the external call). Wire-level compatibility with the
real backend (does the JSON api_client.py sends/expects actually match what
backend/main.py sends/expects) is exercised by the backend route tests
locking in exact response shapes, plus manual end-to-end verification with
a real server - a live-server integration test here would mostly duplicate
that at much higher fragility (port binding, startup races) for little
extra confidence.
"""

from unittest.mock import MagicMock

import pytest

from api_client import APIClient, APIError


class FakeHTTPResponse:
    def __init__(self, status_code=200, json_body=None, text=""):
        self.status_code = status_code
        self._json_body = json_body if json_body is not None else {}
        self.text = text or str(self._json_body)

    def json(self):
        return self._json_body


def test_register_stores_token_on_success(monkeypatch):
    client = APIClient()
    monkeypatch.setattr(
        "api_client.requests.post",
        MagicMock(return_value=FakeHTTPResponse(200, {"token": "abc123"})),
    )
    client.register("alice", "hunter2")
    assert client.token == "abc123"


def test_register_raises_api_error_on_failure(monkeypatch):
    client = APIClient()
    monkeypatch.setattr(
        "api_client.requests.post",
        MagicMock(return_value=FakeHTTPResponse(400, {"detail": "Username already exists: alice"})),
    )
    with pytest.raises(APIError, match="Username already exists"):
        client.register("alice", "hunter2")
    assert client.token is None


def test_login_stores_token_on_success(monkeypatch):
    client = APIClient()
    monkeypatch.setattr(
        "api_client.requests.post",
        MagicMock(return_value=FakeHTTPResponse(200, {"token": "xyz789"})),
    )
    client.login("alice", "hunter2")
    assert client.token == "xyz789"


def test_login_raises_api_error_on_401(monkeypatch):
    client = APIClient()
    monkeypatch.setattr(
        "api_client.requests.post",
        MagicMock(return_value=FakeHTTPResponse(401, {"detail": "Invalid username or password"})),
    )
    with pytest.raises(APIError, match="Invalid username or password"):
        client.login("alice", "wrong")


def test_requests_include_bearer_header_once_logged_in(monkeypatch):
    client = APIClient()
    client.token = "my-token"
    post_mock = MagicMock(return_value=FakeHTTPResponse(200, {"resource": "portfolio", "granted": True}))
    monkeypatch.setattr("api_client.requests.post", post_mock)

    client.grant("portfolio")

    _, kwargs = post_mock.call_args
    assert kwargs["headers"] == {"Authorization": "Bearer my-token"}


def test_requests_have_no_auth_header_before_login(monkeypatch):
    client = APIClient()
    post_mock = MagicMock(return_value=FakeHTTPResponse(200, {"resource": "portfolio", "granted": True}))
    monkeypatch.setattr("api_client.requests.post", post_mock)

    client.grant("portfolio")

    _, kwargs = post_mock.call_args
    assert kwargs["headers"] == {}


def test_logout_clears_token(monkeypatch):
    client = APIClient()
    client.token = "my-token"
    monkeypatch.setattr("api_client.requests.post", MagicMock(return_value=FakeHTTPResponse(200, {})))
    client.logout()
    assert client.token is None


def test_logout_with_no_token_does_not_call_the_server(monkeypatch):
    client = APIClient()
    post_mock = MagicMock()
    monkeypatch.setattr("api_client.requests.post", post_mock)
    client.logout()
    post_mock.assert_not_called()


def test_me_returns_username(monkeypatch):
    client = APIClient()
    client.token = "my-token"
    monkeypatch.setattr(
        "api_client.requests.get", MagicMock(return_value=FakeHTTPResponse(200, {"username": "alice"}))
    )
    assert client.me() == "alice"


def test_me_raises_on_401(monkeypatch):
    client = APIClient()
    monkeypatch.setattr(
        "api_client.requests.get",
        MagicMock(return_value=FakeHTTPResponse(401, {"detail": "Invalid or expired session"})),
    )
    with pytest.raises(APIError):
        client.me()


def test_chat_sends_messages_and_returns_full_response(monkeypatch):
    client = APIClient()
    client.token = "my-token"
    post_mock = MagicMock(return_value=FakeHTTPResponse(200, {"reply": "Hi!", "messages": []}))
    monkeypatch.setattr("api_client.requests.post", post_mock)

    result = client.chat([{"role": "user", "content": "hi"}])

    assert result == {"reply": "Hi!", "messages": []}
    _, kwargs = post_mock.call_args
    assert kwargs["json"] == {"messages": [{"role": "user", "content": "hi"}]}


def test_chat_includes_consent_answer_only_when_provided(monkeypatch):
    client = APIClient()
    post_mock = MagicMock(return_value=FakeHTTPResponse(200, {"reply": "ok", "messages": []}))
    monkeypatch.setattr("api_client.requests.post", post_mock)

    client.chat([{"role": "user", "content": "hi"}], consent_answer="always", consent_key="portfolio_holdings:reasoning_model")

    _, kwargs = post_mock.call_args
    assert kwargs["json"]["consent_answer"] == "always"
    assert kwargs["json"]["consent_key"] == "portfolio_holdings:reasoning_model"


def test_list_permissions_returns_parsed_json(monkeypatch):
    client = APIClient()
    monkeypatch.setattr(
        "api_client.requests.get", MagicMock(return_value=FakeHTTPResponse(200, {"portfolio": True}))
    )
    assert client.list_permissions() == {"portfolio": True}


def test_reset_preference_returns_forgotten_flag(monkeypatch):
    client = APIClient()
    monkeypatch.setattr(
        "api_client.requests.post",
        MagicMock(return_value=FakeHTTPResponse(200, {"key": "k", "forgotten": True})),
    )
    assert client.reset_preference("k") is True


def test_list_activity_returns_a_list(monkeypatch):
    client = APIClient()
    monkeypatch.setattr(
        "api_client.requests.get",
        MagicMock(return_value=FakeHTTPResponse(200, [{"action": "retrieve_portfolio"}])),
    )
    assert client.list_activity() == [{"action": "retrieve_portfolio"}]


def test_raise_for_error_falls_back_to_response_text_on_non_json_body(monkeypatch):
    client = APIClient()
    response = FakeHTTPResponse(500, text="Internal Server Error")
    response.json = MagicMock(side_effect=ValueError("not json"))
    monkeypatch.setattr("api_client.requests.get", MagicMock(return_value=response))
    with pytest.raises(APIError, match="Internal Server Error"):
        client.me()
