"""Regression tests for main.handle_auth: the login/register prompt that
runs before anything else in the CLI. Drives it via monkeypatched
builtins.input/getpass.getpass, with a mocked APIClient standing in for the
backend (api_client.py's own correctness is tested separately in
test_api_client.py, backend/main.py's in test_backend_auth.py) - no real
HTTP call is made here, no server needed."""

from unittest.mock import MagicMock

import pytest

from api_client import APIClient, APIError
from app.main import handle_auth


@pytest.fixture
def fake_client():
    client = MagicMock(spec=APIClient)
    client.token = None
    return client


@pytest.fixture
def cli_session_path(tmp_path, monkeypatch):
    path = tmp_path / ".cli_session"
    monkeypatch.setattr("app.main.CLI_SESSION_PATH", path)
    return path


def test_valid_cached_token_skips_all_prompting(fake_client, cli_session_path, monkeypatch):
    cli_session_path.write_text("cached-token", encoding="utf-8")
    fake_client.me.return_value = "alice"
    input_mock = MagicMock(side_effect=AssertionError("input should not be called"))
    getpass_mock = MagicMock(side_effect=AssertionError("getpass.getpass should not be called"))
    monkeypatch.setattr("builtins.input", input_mock)
    monkeypatch.setattr("getpass.getpass", getpass_mock)

    username = handle_auth(fake_client)

    assert username == "alice"
    assert fake_client.token == "cached-token"
    input_mock.assert_not_called()
    getpass_mock.assert_not_called()


def test_invalid_cached_token_clears_it_and_falls_back_to_login_prompt(fake_client, cli_session_path, monkeypatch):
    cli_session_path.write_text("stale-token", encoding="utf-8")
    fake_client.me.side_effect = APIError("Invalid or expired session")

    def do_login(username, password):
        fake_client.token = "fresh-token"

    fake_client.login.side_effect = do_login

    inputs = iter(["login", "alice"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr("getpass.getpass", lambda _: "correct-pw")

    username = handle_auth(fake_client)

    assert username == "alice"
    assert cli_session_path.read_text(encoding="utf-8") == "fresh-token"


def test_register_flow_saves_token_and_returns_username(fake_client, cli_session_path, monkeypatch):
    def do_register(username, password):
        fake_client.token = "new-token"

    fake_client.register.side_effect = do_register

    inputs = iter(["register", "alice"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    passwords = iter(["hunter2", "hunter2"])
    monkeypatch.setattr("getpass.getpass", lambda _: next(passwords))

    username = handle_auth(fake_client)

    assert username == "alice"
    assert cli_session_path.read_text(encoding="utf-8") == "new-token"
    fake_client.register.assert_called_once_with("alice", "hunter2")


def test_register_password_mismatch_reprompts_without_calling_register(fake_client, cli_session_path, monkeypatch):
    def do_register(username, password):
        fake_client.token = "new-token"

    fake_client.register.side_effect = do_register

    inputs = iter(["register", "alice", "register", "alice"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    passwords = iter(["pw-one", "pw-two-does-not-match", "hunter2", "hunter2"])
    monkeypatch.setattr("getpass.getpass", lambda _: next(passwords))

    handle_auth(fake_client)

    fake_client.register.assert_called_once_with("alice", "hunter2")


def test_register_duplicate_username_reprompts_rather_than_crashing(fake_client, cli_session_path, monkeypatch):
    def do_register(username, password):
        if username == "alice":
            raise APIError("Username already exists: alice")
        fake_client.token = "bob-token"

    fake_client.register.side_effect = do_register

    inputs = iter(["register", "alice", "register", "bob"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    passwords = iter(["newpw", "newpw", "bobpw", "bobpw"])
    monkeypatch.setattr("getpass.getpass", lambda _: next(passwords))

    username = handle_auth(fake_client)

    assert username == "bob"


def test_login_wrong_password_reprompts_rather_than_authenticating(fake_client, cli_session_path, monkeypatch):
    def do_login(username, password):
        if password != "correct-pw":
            raise APIError("Invalid username or password")
        fake_client.token = "alice-token"

    fake_client.login.side_effect = do_login

    inputs = iter(["login", "alice", "login", "alice"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    passwords = iter(["wrong-pw", "correct-pw"])
    monkeypatch.setattr("getpass.getpass", lambda _: next(passwords))

    username = handle_auth(fake_client)

    assert username == "alice"


def test_eof_at_login_prompt_exits_cleanly_instead_of_raising_eof_error(fake_client, cli_session_path, monkeypatch):
    monkeypatch.setattr("builtins.input", MagicMock(side_effect=EOFError))

    with pytest.raises(SystemExit) as exc_info:
        handle_auth(fake_client)

    assert exc_info.value.code == 0


def test_invalid_top_level_choice_reprompts(fake_client, cli_session_path, monkeypatch):
    def do_login(username, password):
        fake_client.token = "alice-token"

    fake_client.login.side_effect = do_login

    inputs = iter(["nonsense", "login", "alice"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr("getpass.getpass", lambda _: "correct-pw")

    username = handle_auth(fake_client)

    assert username == "alice"
