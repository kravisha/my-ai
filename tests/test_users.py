"""Regression tests for app/users.py: registration, authentication, and the
username normalization that keeps a username safe to use as a directory
name (user_data/<username>/)."""

import json

from app.users import UserStore, normalize_username


def test_register_then_authenticate_succeeds(users_store):
    users_store.register("alice", "hunter2")
    assert users_store.authenticate("alice", "hunter2") is True


def test_authenticate_wrong_password_fails(users_store):
    users_store.register("alice", "hunter2")
    assert users_store.authenticate("alice", "wrong-password") is False


def test_authenticate_nonexistent_user_fails_without_raising(users_store):
    assert users_store.authenticate("ghost", "anything") is False


def test_register_duplicate_username_raises_and_does_not_overwrite(users_store):
    users_store.register("alice", "first-password")
    try:
        users_store.register("alice", "second-password")
        assert False, "expected ValueError"
    except ValueError:
        pass
    assert users_store.authenticate("alice", "first-password") is True
    assert users_store.authenticate("alice", "second-password") is False


def test_register_invalid_username_raises(users_store):
    for bad in ("", "a" * 33, "has spaces", "Has/Slash", "..\\..\\evil"):
        try:
            users_store.register(bad, "password")
            assert False, f"expected ValueError for {bad!r}"
        except ValueError:
            pass


def test_password_is_never_stored_in_plaintext(users_store, tmp_path):
    users_store.register("alice", "a-very-secret-password")
    raw = users_store.path.read_text(encoding="utf-8")
    assert "a-very-secret-password" not in raw


def test_username_case_insensitive_for_registration_and_login(users_store):
    users_store.register("Alice", "hunter2")
    assert users_store.authenticate("alice", "hunter2") is True
    assert users_store.authenticate("ALICE", "hunter2") is True

    try:
        users_store.register("ALICE", "different-password")
        assert False, "expected ValueError for case-insensitive duplicate"
    except ValueError:
        pass


def test_register_returns_normalized_username(users_store):
    normalized = users_store.register("Alice", "hunter2")
    assert normalized == "alice"


def test_exists(users_store):
    assert users_store.exists("alice") is False
    users_store.register("alice", "hunter2")
    assert users_store.exists("alice") is True
    assert users_store.exists("Alice") is True


def test_persistence_round_trip_across_instances(tmp_path):
    path = tmp_path / "users.json"
    UserStore(path=path).register("alice", "hunter2")

    second = UserStore(path=path)
    assert second.authenticate("alice", "hunter2") is True


def test_normalize_username_strips_and_lowercases():
    assert normalize_username("  Alice  ") == "alice"
