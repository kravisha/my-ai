"""Cross-cutting regression tests: two My AI accounts must never see each
other's permission, preference or audit state — **or each other's positions**.

That last clause is the one TQ-72 earned, and this file has now recorded three
different opinions about it, which is worth keeping visible.

It first said the shared file was deliberate — *"portfolio.xlsx stays a single
shared file by design - only governance state is per-user"*. It was not a design;
it was the ownerless retrieval wearing a second hat. One file, every account, and
nothing between them but a permission grant, so a fully-granted second account
read the first's positions with no code wrong anywhere.

TQ-46 then gave the *function* an owner and pointed it at a stored `SUPERUSER`
portfolio. §111 removed the store. **TQ-72 gave the source an owner**, which is
where it always mattered: the path is derived from the authenticated username and
is never an argument, so "read the other account's file" is not a call that can
be constructed.
"""

from app.audit import AuditLog
from app.permissions import PermissionManager
from app.privacy_preferences import PrivacyPreferenceStore
from app.tools.portfolio import FORWARDING_KEY, SOURCE_FILENAME, retrieve_portfolio
from app.users import ensure_user_data_dir


def _build_user_stores(root, username):
    user_dir = ensure_user_data_dir(username, root=root)
    return (
        PermissionManager(path=user_dir / "permissions.json"),
        PrivacyPreferenceStore(path=user_dir / "privacy_preferences.json"),
        AuditLog(path=user_dir / "audit_log.jsonl"),
    )


def _write_source(root, username, rows):
    from openpyxl import Workbook

    user_dir = ensure_user_data_dir(username, root=root)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Ticker", "Shares", "Purchase Price", "Purchase Date", "Account ID"])
    for row in rows:
        sheet.append(list(row))
    workbook.save(user_dir / SOURCE_FILENAME)


def _per_user_sources(monkeypatch, root):
    import app.tools.portfolio as tool

    monkeypatch.setattr(tool, "ensure_user_data_dir",
                        lambda username: ensure_user_data_dir(username, root=root))


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

    audit_a.record(action="retrieve_portfolio", resource="portfolio", authorized=True,
                   result="test")

    assert audit_a.path.exists()
    assert not audit_b.path.exists()


def test_full_retrieve_portfolio_isolation_across_users(tmp_path, monkeypatch):
    _per_user_sources(monkeypatch, tmp_path)
    perms_a, prefs_a, audit_a = _build_user_stores(tmp_path, "alice")
    perms_b, prefs_b, audit_b = _build_user_stores(tmp_path, "bob")
    _write_source(tmp_path, "alice", [("AAPL", 25, 172.34, "2023-03-14", "ACCT-1")])

    perms_a.grant("portfolio")
    prefs_a.set(FORWARDING_KEY, "always")

    result_a = retrieve_portfolio(None, "alice", perms_a, prefs_a, audit_a)
    assert [h["symbol"] for h in result_a["holdings"]] == ["AAPL"]

    # Bob never granted or consented, so layer 1 refuses him.
    result_b = retrieve_portfolio(None, "bob", perms_b, prefs_b, audit_b)
    assert "error" in result_b
    assert not audit_b.path.exists() or "denied" in audit_b.path.read_text(encoding="utf-8")


def test_a_fully_granted_user_still_cannot_reach_another_users_positions(tmp_path,
                                                                        monkeypatch):
    """**The test this file existed to be unable to write.**

    Bob does everything right: granted, consented, asking correctly. He gets a
    refusal naming his own missing source — not Alice's positions, and not an
    empty list that would read as "you hold nothing".

    Under the original design this could not have been written, because both
    accounts read one spreadsheet and a granted Bob receiving Alice's holdings
    *was* the intended behaviour."""
    _per_user_sources(monkeypatch, tmp_path)
    perms_a, prefs_a, audit_a = _build_user_stores(tmp_path, "alice")
    perms_b, prefs_b, audit_b = _build_user_stores(tmp_path, "bob")
    for permissions, preferences in ((perms_a, prefs_a), (perms_b, prefs_b)):
        permissions.grant("portfolio")
        preferences.set(FORWARDING_KEY, "always")
    _write_source(tmp_path, "alice", [("AAPL", 25, 172.34, "2023-03-14", "ACCT-1")])

    alice = retrieve_portfolio(None, "alice", perms_a, prefs_a, audit_a)
    bob = retrieve_portfolio(None, "bob", perms_b, prefs_b, audit_b)

    assert [h["symbol"] for h in alice["holdings"]] == ["AAPL"]
    assert "holdings" not in bob, "a granted account reached somebody else's positions"
    assert "anybody else's" in bob["error"]


def test_two_users_directories_are_distinct_on_disk(tmp_path):
    dir_a = ensure_user_data_dir("alice", root=tmp_path)
    dir_b = ensure_user_data_dir("bob", root=tmp_path)

    assert dir_a != dir_b
    assert dir_a.parent == dir_b.parent == tmp_path
