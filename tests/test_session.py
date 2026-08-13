"""Regression tests for app/session.py: a server-side store holding many
concurrently-valid tokens (one per logged-in client), not a single local
session - the shape a real backend needs, matching vibe-agent's DB Session
table but JSON-file-backed."""

from datetime import timedelta

from app.session import SessionStore


def test_create_then_validate_round_trips_username(session_store):
    token = session_store.create("alice")
    assert session_store.validate(token) == "alice"


def test_validate_unknown_token_returns_none(session_store):
    assert session_store.validate("not-a-real-token") is None


def test_validate_expired_session_returns_none(tmp_path):
    store = SessionStore(path=tmp_path / "sessions.json", lifetime=timedelta(seconds=-1))
    token = store.create("alice")
    assert store.validate(token) is None


def test_revoke_then_validate_returns_none(session_store):
    token = session_store.create("alice")
    session_store.revoke(token)
    assert session_store.validate(token) is None


def test_revoke_on_unknown_token_does_not_raise(session_store):
    session_store.revoke("not-a-real-token")  # should not raise


def test_two_instances_against_same_path_agree(tmp_path):
    path = tmp_path / "sessions.json"
    token = SessionStore(path=path).create("alice")

    second = SessionStore(path=path)
    assert second.validate(token) == "alice"


def test_create_returns_a_token(session_store):
    token = session_store.create("alice")
    assert isinstance(token, str)
    assert len(token) > 20


def test_validate_corrupt_session_file_returns_none(tmp_path):
    path = tmp_path / "sessions.json"
    path.write_text("not valid json", encoding="utf-8")
    store = SessionStore(path=path)
    assert store.validate("anything") is None


def test_two_tokens_are_independently_valid(session_store):
    """The core new behavior a real server needs: multiple logged-in clients
    at once, each with their own token, none of them interfering."""
    token_a = session_store.create("alice")
    token_b = session_store.create("bob")

    assert session_store.validate(token_a) == "alice"
    assert session_store.validate(token_b) == "bob"


def test_revoking_one_token_leaves_the_other_valid(session_store):
    token_a = session_store.create("alice")
    token_b = session_store.create("bob")

    session_store.revoke(token_a)

    assert session_store.validate(token_a) is None
    assert session_store.validate(token_b) == "bob"


def test_same_user_can_hold_two_independent_tokens(session_store):
    """A user logged in from both the CLI and the desktop GUI at once should
    get two distinct, independently-revocable tokens."""
    token_1 = session_store.create("alice")
    token_2 = session_store.create("alice")

    assert token_1 != token_2
    assert session_store.validate(token_1) == "alice"
    assert session_store.validate(token_2) == "alice"

    session_store.revoke(token_1)
    assert session_store.validate(token_1) is None
    assert session_store.validate(token_2) == "alice"
