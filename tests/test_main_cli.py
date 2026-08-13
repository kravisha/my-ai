"""Regression tests for main.handle_grant_revoke/handle_preference_commands/
send_chat_message, all driven against a mocked APIClient now (the CLI is a
thin HTTP client - api_client.py's own correctness is tested separately in
test_api_client.py, backend/main.py's in test_backend_*.py)."""

from unittest.mock import MagicMock

from api_client import APIClient, APIError
from app.main import handle_grant_revoke, handle_preference_commands, send_chat_message
from app.tools.portfolio import FORWARDING_KEY


def _fake_client():
    client = MagicMock(spec=APIClient)
    client.token = "test-token"
    return client


def test_grant_command_grants_and_is_handled(capsys):
    client = _fake_client()
    handled = handle_grant_revoke("grant portfolio", client)
    assert handled is True
    client.grant.assert_called_once_with("portfolio")
    assert "Granted" in capsys.readouterr().out


def test_revoke_command_revokes_and_is_handled(capsys):
    client = _fake_client()
    handled = handle_grant_revoke("revoke portfolio", client)
    assert handled is True
    client.revoke.assert_called_once_with("portfolio")
    assert "Revoked" in capsys.readouterr().out


def test_grant_unknown_resource_shows_server_error_message(capsys):
    client = _fake_client()
    client.grant.side_effect = APIError("Unknown resource: not_a_resource")
    handled = handle_grant_revoke("grant not_a_resource", client)
    assert handled is True
    assert "Unknown resource" in capsys.readouterr().out


def test_ordinary_question_is_not_handled_as_grant_revoke():
    client = _fake_client()
    assert handle_grant_revoke("What stocks do I own?", client) is False
    client.grant.assert_not_called()
    client.revoke.assert_not_called()


def test_show_preferences_empty(capsys):
    client = _fake_client()
    client.list_preferences.return_value = {}
    handled = handle_preference_commands("show preferences", client)
    assert handled is True
    assert "No privacy preferences" in capsys.readouterr().out


def test_show_preferences_lists_entries(capsys):
    client = _fake_client()
    client.list_preferences.return_value = {FORWARDING_KEY: {"disposition": "always", "set_at": "2026-01-01"}}
    handle_preference_commands("show preferences", client)
    out = capsys.readouterr().out
    assert FORWARDING_KEY in out
    assert "always" in out


def test_reset_preference_found(capsys):
    client = _fake_client()
    client.reset_preference.return_value = True
    handled = handle_preference_commands(f"reset preference {FORWARDING_KEY}", client)
    assert handled is True
    client.reset_preference.assert_called_once_with(FORWARDING_KEY)
    assert "Forgot preference" in capsys.readouterr().out


def test_reset_preference_not_found(capsys):
    client = _fake_client()
    client.reset_preference.return_value = False
    handled = handle_preference_commands("reset preference nonexistent_key", client)
    assert handled is True
    assert "No preference stored" in capsys.readouterr().out


def test_ordinary_question_is_not_handled_as_preference_command():
    client = _fake_client()
    assert handle_preference_commands("What stocks do I own?", client) is False


def test_send_chat_message_plain_reply_no_consent_needed():
    client = _fake_client()
    client.chat.return_value = {"reply": "Hello!", "messages": [{"role": "user", "content": "hi"}]}
    messages = []

    reply = send_chat_message(client, messages, "hi")

    assert reply == "Hello!"
    assert messages == [{"role": "user", "content": "hi"}]  # synced to the server's response
    client.chat.assert_called_once()


def test_send_chat_message_resolves_consent_via_input_then_returns_reply(monkeypatch):
    client = _fake_client()
    paused_messages = [
        {"role": "user", "content": "What stocks do I own?"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "retrieve_portfolio", "input": {}}]},
    ]
    client.chat.side_effect = [
        {"needs_consent": {"prompt": "Share holdings?", "consent_key": FORWARDING_KEY}, "messages": paused_messages},
        {"reply": "Here you go.", "messages": paused_messages + [{"role": "user", "content": []}]},
    ]
    monkeypatch.setattr("builtins.input", lambda _: "always")

    reply = send_chat_message(client, [], "What stocks do I own?")

    assert reply == "Here you go."
    assert client.chat.call_count == 2
    second_call_kwargs = client.chat.call_args_list[1].kwargs
    assert second_call_kwargs["consent_answer"] == "always"
    assert second_call_kwargs["consent_key"] == FORWARDING_KEY


def test_send_chat_message_reprompts_on_invalid_consent_answer(monkeypatch):
    client = _fake_client()
    paused_messages = [{"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "retrieve_portfolio"}]}]
    client.chat.side_effect = [
        {"needs_consent": {"prompt": "Share holdings?", "consent_key": FORWARDING_KEY}, "messages": paused_messages},
        {"reply": "Here you go.", "messages": paused_messages},
    ]
    answers = iter(["maybe", "always"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    reply = send_chat_message(client, [], "What stocks do I own?")

    assert reply == "Here you go."


def test_send_chat_message_once_does_not_print_recorded(monkeypatch, capsys):
    client = _fake_client()
    paused_messages = [{"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "retrieve_portfolio"}]}]
    client.chat.side_effect = [
        {"needs_consent": {"prompt": "Share holdings?", "consent_key": FORWARDING_KEY}, "messages": paused_messages},
        {"reply": "Here you go.", "messages": paused_messages},
    ]
    monkeypatch.setattr("builtins.input", lambda _: "once")

    send_chat_message(client, [], "What stocks do I own?")

    out = capsys.readouterr().out
    assert "Allowing once" in out
    assert "Recorded" not in out
