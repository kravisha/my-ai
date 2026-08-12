"""Regression tests for main.handle_auth: the login/register prompt that now
runs before anything else in the CLI. Drives it via monkeypatched
builtins.input/getpass.getpass so no real terminal interaction happens."""

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from app.main import handle_auth
from app.session import SessionStore


def test_valid_persisted_session_skips_all_prompting(users_store, session_store, monkeypatch):
    session_store.create("alice")
    input_mock = MagicMock(side_effect=AssertionError("input should not be called"))
    getpass_mock = MagicMock(side_effect=AssertionError("getpass.getpass should not be called"))
    monkeypatch.setattr("builtins.input", input_mock)
    monkeypatch.setattr("getpass.getpass", getpass_mock)

    username = handle_auth(users_store, session_store)

    assert username == "alice"
    input_mock.assert_not_called()
    getpass_mock.assert_not_called()


def test_expired_session_falls_back_to_login_prompt(users_store, session_store, monkeypatch):
    users_store.register("alice", "correct-pw")
    expired = SessionStore(path=session_store.path, lifetime=timedelta(seconds=-1))
    expired.create("alice")

    inputs = iter(["login", "alice"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr("getpass.getpass", lambda _: "correct-pw")

    username = handle_auth(users_store, session_store)

    assert username == "alice"
    assert session_store.validate() == "alice"


def test_register_flow_creates_account_and_session(users_store, session_store, monkeypatch):
    inputs = iter(["register", "alice"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    passwords = iter(["hunter2", "hunter2"])
    monkeypatch.setattr("getpass.getpass", lambda _: next(passwords))

    username = handle_auth(users_store, session_store)

    assert username == "alice"
    assert users_store.authenticate("alice", "hunter2") is True
    assert session_store.validate() == "alice"


def test_register_password_mismatch_reprompts_rather_than_crashing(users_store, session_store, monkeypatch):
    inputs = iter(["register", "alice", "register", "alice"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    passwords = iter(["pw-one", "pw-two-does-not-match", "hunter2", "hunter2"])
    monkeypatch.setattr("getpass.getpass", lambda _: next(passwords))

    username = handle_auth(users_store, session_store)

    assert username == "alice"
    assert users_store.authenticate("alice", "hunter2") is True


def test_register_duplicate_username_reprompts_rather_than_crashing(users_store, session_store, monkeypatch):
    users_store.register("alice", "existing-pw")

    inputs = iter(["register", "alice", "register", "bob"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    passwords = iter(["newpw", "newpw", "bobpw", "bobpw"])
    monkeypatch.setattr("getpass.getpass", lambda _: next(passwords))

    username = handle_auth(users_store, session_store)

    assert username == "bob"
    assert users_store.authenticate("alice", "existing-pw") is True


def test_login_wrong_password_reprompts_rather_than_authenticating(users_store, session_store, monkeypatch):
    users_store.register("alice", "correct-pw")

    inputs = iter(["login", "alice", "login", "alice"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    passwords = iter(["wrong-pw", "correct-pw"])
    monkeypatch.setattr("getpass.getpass", lambda _: next(passwords))

    username = handle_auth(users_store, session_store)

    assert username == "alice"


def test_eof_at_login_prompt_exits_cleanly_instead_of_raising_eof_error(users_store, session_store, monkeypatch):
    """Regression test: pressing Ctrl+D/Ctrl+C at the very first prompt the
    CLI now shows must exit like every other input() loop in the app
    (main()'s command loop already catches EOFError/KeyboardInterrupt),
    not crash with a raw traceback."""
    monkeypatch.setattr("builtins.input", MagicMock(side_effect=EOFError))

    with pytest.raises(SystemExit) as exc_info:
        handle_auth(users_store, session_store)

    assert exc_info.value.code == 0


def test_invalid_top_level_choice_reprompts(users_store, session_store, monkeypatch):
    users_store.register("alice", "correct-pw")

    inputs = iter(["nonsense", "login", "alice"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr("getpass.getpass", lambda _: "correct-pw")

    username = handle_auth(users_store, session_store)

    assert username == "alice"
