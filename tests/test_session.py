"""Regression tests for app/session.py: a single locally-persisted session
(no per-request keying, since this is one long-running CLI process, not a
server) that lets a valid login skip re-prompting on the next run."""

from datetime import timedelta

from app.session import SessionStore


def test_create_then_validate_round_trips_username(session_store):
    session_store.create("alice")
    assert session_store.validate() == "alice"


def test_validate_with_no_session_file_returns_none(session_store):
    assert session_store.validate() is None


def test_validate_expired_session_returns_none(tmp_path):
    store = SessionStore(path=tmp_path / "session.json", lifetime=timedelta(seconds=-1))
    store.create("alice")
    assert store.validate() is None


def test_revoke_then_validate_returns_none(session_store):
    session_store.create("alice")
    session_store.revoke()
    assert session_store.validate() is None


def test_revoke_on_nonexistent_session_does_not_raise(session_store):
    session_store.revoke()  # should not raise


def test_two_instances_against_same_path_agree(tmp_path):
    path = tmp_path / "session.json"
    SessionStore(path=path).create("alice")

    second = SessionStore(path=path)
    assert second.validate() == "alice"


def test_create_returns_a_token(session_store):
    token = session_store.create("alice")
    assert isinstance(token, str)
    assert len(token) > 20


def test_validate_corrupt_session_file_returns_none(tmp_path):
    path = tmp_path / "session.json"
    path.write_text("not valid json", encoding="utf-8")
    store = SessionStore(path=path)
    assert store.validate() is None
