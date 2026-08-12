import pytest

from app.privacy_preferences import PrivacyPreferenceStore


def test_get_missing_key_returns_none(preferences_store):
    assert preferences_store.get("nope") is None


def test_set_then_get_roundtrip(preferences_store):
    preferences_store.set("portfolio_holdings:reasoning_model", "always")
    assert preferences_store.get("portfolio_holdings:reasoning_model") == "always"


def test_set_invalid_disposition_raises(preferences_store):
    with pytest.raises(ValueError):
        preferences_store.set("k", "sometimes")


def test_set_records_timestamp(preferences_store):
    preferences_store.set("k", "never")
    assert "set_at" in preferences_store._state["k"]


def test_forget_removes_and_returns_true(preferences_store):
    preferences_store.set("k", "always")
    assert preferences_store.forget("k") is True
    assert preferences_store.get("k") is None


def test_forget_missing_key_returns_false(preferences_store):
    assert preferences_store.forget("never_set") is False


def test_list_all_reflects_stored_entries(preferences_store):
    preferences_store.set("a", "always")
    preferences_store.set("b", "never")
    entries = preferences_store.list_all()
    assert set(entries.keys()) == {"a", "b"}
    assert entries["a"]["disposition"] == "always"
    assert entries["b"]["disposition"] == "never"


def test_list_all_returns_a_copy_not_internal_state(preferences_store):
    preferences_store.set("a", "always")
    entries = preferences_store.list_all()
    entries["a"]["disposition"] = "tampered"
    assert preferences_store.get("a") == "always"


def test_persists_across_instances(tmp_path):
    path = tmp_path / "privacy_preferences.json"
    PrivacyPreferenceStore(path=path).set("k", "never")

    reloaded = PrivacyPreferenceStore(path=path)
    assert reloaded.get("k") == "never"
