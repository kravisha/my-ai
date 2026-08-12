import pytest

from app.permissions import PermissionManager


def test_is_granted_defaults_false(permissions_store):
    assert permissions_store.is_granted("portfolio") is False


def test_grant_makes_is_granted_true(permissions_store):
    permissions_store.grant("portfolio")
    assert permissions_store.is_granted("portfolio") is True


def test_grant_records_timestamp_and_resource_path(permissions_store):
    permissions_store.grant("portfolio")
    entry = permissions_store._state["portfolio"]
    assert entry["status"] == "granted"
    assert "granted_at" in entry
    assert entry["resource_path"]


def test_revoke_after_grant_makes_is_granted_false(permissions_store):
    permissions_store.grant("portfolio")
    permissions_store.revoke("portfolio")
    assert permissions_store.is_granted("portfolio") is False


def test_revoke_without_prior_grant_is_safe(permissions_store):
    permissions_store.revoke("portfolio")
    assert permissions_store.is_granted("portfolio") is False


def test_grant_unknown_resource_raises(permissions_store):
    with pytest.raises(ValueError):
        permissions_store.grant("not_a_real_resource")


def test_revoke_unknown_resource_raises(permissions_store):
    with pytest.raises(ValueError):
        permissions_store.revoke("not_a_real_resource")


def test_grant_persists_across_instances(tmp_path):
    path = tmp_path / "permissions.json"
    PermissionManager(path=path).grant("portfolio")

    reloaded = PermissionManager(path=path)
    assert reloaded.is_granted("portfolio") is True


def test_fresh_instance_with_no_file_has_no_grants(tmp_path):
    manager = PermissionManager(path=tmp_path / "does_not_exist.json")
    assert manager.is_granted("portfolio") is False
