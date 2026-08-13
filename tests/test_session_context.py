"""Regression test for desktop/session_context.py: build_session() is a thin
wrapper over already-tested pieces (ensure_user_data_dir, the three per-user
stores) - this just confirms the wiring is correct, not their internals."""

from app.users import ensure_user_data_dir
from desktop.session_context import AppSession, build_session


def test_build_session_scopes_stores_to_the_users_own_directory(tmp_path, monkeypatch):
    monkeypatch.setattr("desktop.session_context.ensure_user_data_dir", lambda username: ensure_user_data_dir(username, root=tmp_path))

    session = build_session("alice")

    assert isinstance(session, AppSession)
    assert session.username == "alice"
    assert session.permissions.path == tmp_path / "alice" / "permissions.json"
    assert session.preferences.path == tmp_path / "alice" / "privacy_preferences.json"
    assert session.audit_log.path == tmp_path / "alice" / "audit_log.jsonl"
    assert session.messages == []


def test_build_session_gives_two_users_independent_stores(tmp_path, monkeypatch):
    monkeypatch.setattr("desktop.session_context.ensure_user_data_dir", lambda username: ensure_user_data_dir(username, root=tmp_path))

    alice = build_session("alice")
    bob = build_session("bob")

    alice.permissions.grant("portfolio")

    assert alice.permissions.is_granted("portfolio") is True
    assert bob.permissions.is_granted("portfolio") is False


def test_build_session_messages_default_is_not_shared_between_instances(tmp_path, monkeypatch):
    monkeypatch.setattr("desktop.session_context.ensure_user_data_dir", lambda username: ensure_user_data_dir(username, root=tmp_path))

    first = build_session("alice")
    first.messages.append({"role": "user", "content": "hi"})
    second = build_session("alice")

    assert second.messages == []
