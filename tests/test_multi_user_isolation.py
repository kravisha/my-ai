"""Cross-cutting regression tests: two different My AI user accounts must
never see each other's permission, preference, or audit state, even though
they read the same shared demo portfolio.xlsx (portfolio.xlsx stays a
single shared file by design - only governance state is per-user)."""

from app.audit import AuditLog
from app.permissions import PermissionManager
from app.privacy_preferences import PrivacyPreferenceStore
from app.tools.portfolio import FORWARDING_KEY, retrieve_portfolio
from app.users import ensure_user_data_dir


def _build_user_stores(root, username):
    user_dir = ensure_user_data_dir(username, root=root)
    return (
        PermissionManager(path=user_dir / "permissions.json"),
        PrivacyPreferenceStore(path=user_dir / "privacy_preferences.json"),
        AuditLog(path=user_dir / "audit_log.jsonl"),
    )


def test_permission_grant_for_one_user_is_invisible_to_another(tmp_path):
    perms_a, _, _ = _build_user_stores(tmp_path, "alice")
    perms_b, _, _ = _build_user_stores(tmp_path, "bob")

    perms_a.grant("portfolio")

    assert perms_a.is_granted("portfolio") is True
    assert perms_b.is_granted("portfolio") is False


def test_preference_for_one_user_is_invisible_to_another(tmp_path):
    _, prefs_a, _ = _build_user_stores(tmp_path, "alice")
    _, prefs_b, _ = _build_user_stores(tmp_path, "bob")

    prefs_a.set(FORWARDING_KEY, "always")

    assert prefs_a.get(FORWARDING_KEY) == "always"
    assert prefs_b.get(FORWARDING_KEY) is None


def test_audit_log_for_one_user_is_invisible_to_another(tmp_path):
    _, _, audit_a = _build_user_stores(tmp_path, "alice")
    _, _, audit_b = _build_user_stores(tmp_path, "bob")

    audit_a.record(action="retrieve_portfolio", resource="portfolio", authorized=True, result="test")

    assert audit_a.path.exists()
    assert not audit_b.path.exists()


def test_full_retrieve_portfolio_isolation_across_users(tmp_path, mock_portfolio_path):
    perms_a, prefs_a, audit_a = _build_user_stores(tmp_path, "alice")
    perms_b, prefs_b, audit_b = _build_user_stores(tmp_path, "bob")

    perms_a.grant("portfolio")
    prefs_a.set(FORWARDING_KEY, "always")

    result_a = retrieve_portfolio(perms_a, prefs_a, audit_a)
    assert "holdings" in result_a

    # Bob never granted or consented - must be denied even though the
    # underlying portfolio.xlsx is the exact same shared file Alice just read.
    result_b = retrieve_portfolio(perms_b, prefs_b, audit_b)
    assert "error" in result_b
    assert not audit_b.path.exists() or "denied" in audit_b.path.read_text(encoding="utf-8")


def test_two_users_directories_are_distinct_on_disk(tmp_path):
    dir_a = ensure_user_data_dir("alice", root=tmp_path)
    dir_b = ensure_user_data_dir("bob", root=tmp_path)

    assert dir_a != dir_b
    assert dir_a.parent == dir_b.parent == tmp_path
