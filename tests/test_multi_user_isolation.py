"""Cross-cutting regression tests: two different My AI user accounts must never
see each other's permission, preference, or audit state - **or each other's
holdings**.

That last clause is new, and it is the part TQ-46 changed. This file used to say
*"even though they read the same shared demo portfolio.xlsx (portfolio.xlsx stays
a single shared file by design - only governance state is per-user)"*, and that
sentence described the defect rather than the design: one file, every account,
and nothing but a permission grant between them. Isolation was a property of the
governance state around the data, not of the data.

Now each account has its own `SUPERUSER`-owned portfolio behind
`portfolios.resolve`. Alice reading Bob's holdings is not merely ungranted, it is
**unreachable** - there is no argument to `retrieve_portfolio` that could name
somebody else's portfolio, so the isolation is structural rather than
conditional.
"""

from app.audit import AuditLog
from app.permissions import PermissionManager
from app.privacy_preferences import PrivacyPreferenceStore
from app.tools.portfolio import FORWARDING_KEY, retrieve_portfolio
from app.users import ensure_user_data_dir
from backend import holdings, superuser_portfolio


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


def test_full_retrieve_portfolio_isolation_across_users(tmp_path, portfolio_conn):
    perms_a, prefs_a, audit_a = _build_user_stores(tmp_path, "alice")
    perms_b, prefs_b, audit_b = _build_user_stores(tmp_path, "bob")

    perms_a.grant("portfolio")
    prefs_a.set(FORWARDING_KEY, "always")
    holdings.record(portfolio_conn, superuser_portfolio.ensure(portfolio_conn, "alice"),
                    symbol="AAPL", quantity=25, average_cost=172.34)

    result_a = retrieve_portfolio(portfolio_conn, "alice", perms_a, prefs_a, audit_a)
    assert [h["symbol"] for h in result_a["holdings"]] == ["AAPL"]

    # Bob never granted or consented, so layer 1 refuses him.
    result_b = retrieve_portfolio(portfolio_conn, "bob", perms_b, prefs_b, audit_b)
    assert "error" in result_b
    assert not audit_b.path.exists() or "denied" in audit_b.path.read_text(encoding="utf-8")


def test_a_granted_user_still_cannot_reach_another_users_holdings(tmp_path, portfolio_conn):
    """**The version of the above that would have failed before TQ-46.**

    Bob does everything right: he is granted, he has consented, he asks
    correctly. He still gets his own portfolio - which is empty - and not
    Alice's, because there is no argument that names a portfolio and the guard
    compares `(owner_type, owner_id)` as a pair.

    Under the old design this test could not have been written: both accounts
    read one spreadsheet, so a fully-granted Bob got Alice's holdings and that
    was the intended behaviour."""
    perms_a, prefs_a, audit_a = _build_user_stores(tmp_path, "alice")
    perms_b, prefs_b, audit_b = _build_user_stores(tmp_path, "bob")
    for permissions, preferences in ((perms_a, prefs_a), (perms_b, prefs_b)):
        permissions.grant("portfolio")
        preferences.set(FORWARDING_KEY, "always")

    holdings.record(portfolio_conn, superuser_portfolio.ensure(portfolio_conn, "alice"),
                    symbol="AAPL", quantity=25, average_cost=172.34)

    alice = retrieve_portfolio(portfolio_conn, "alice", perms_a, prefs_a, audit_a)
    bob = retrieve_portfolio(portfolio_conn, "bob", perms_b, prefs_b, audit_b)

    assert [h["symbol"] for h in alice["holdings"]] == ["AAPL"]
    assert bob["holdings"] == [], "a granted account reached somebody else's holdings"


def test_two_users_directories_are_distinct_on_disk(tmp_path):
    dir_a = ensure_user_data_dir("alice", root=tmp_path)
    dir_b = ensure_user_data_dir("bob", root=tmp_path)

    assert dir_a != dir_b
    assert dir_a.parent == dir_b.parent == tmp_path
