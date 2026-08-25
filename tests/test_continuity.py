"""Business Continuity slice 1 (backend/continuity.py, addendum 29, TQ-02).

The load-bearing test here is the restore: addendum 29 §1.4 says a backup that
has never been restored is not a recovery asset, so this suite performs an
actual restore-and-read — including reopening a restored SQLite database and
reading its rows back — on every run.
"""

import json
import sqlite3

import pytest

from backend import continuity
from backend.continuity import (
    LocalDirectoryProvider,
    create_backup,
    critical_sources,
    list_backups,
    restore_backup,
    verify_backup,
)


def _make_sqlite(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("CREATE TABLE things (id INTEGER PRIMARY KEY, name TEXT)")
    conn.executemany("INSERT INTO things (name) VALUES (?)", [(r,) for r in rows])
    conn.commit()
    return conn


def _sources(tmp_path):
    """A miniature of the real backup domain: a live WAL database, a flat
    file, and a user_data-style tree."""
    db_path = tmp_path / "live" / "fi.db"
    db_path.parent.mkdir()
    conn = _make_sqlite(db_path, ["alpha", "beta"])

    users = tmp_path / "live" / "users.json"
    users.write_text(json.dumps({"alice": "hash"}), encoding="utf-8")

    tree = tmp_path / "live" / "user_data"
    (tree / "alice").mkdir(parents=True)
    (tree / "alice" / "permissions.json").write_text("{}", encoding="utf-8")
    (tree / "alice" / "audit_log.jsonl").write_text('{"event": 1}\n', encoding="utf-8")

    sources = [
        {"label": "fi", "path": db_path, "kind": "sqlite", "restore_path": "fi.db"},
        {"label": "users", "path": users, "kind": "file", "restore_path": "users.json"},
        {"label": "user_data", "path": tree, "kind": "tree", "restore_path": "user_data"},
        {"label": "sessions", "path": tmp_path / "live" / "sessions.json", "kind": "file",
         "restore_path": "sessions.json"},
    ]
    return sources, conn


def test_provider_roundtrip_and_listing(tmp_path):
    provider = LocalDirectoryProvider(tmp_path / "store")
    provider.put("a/b.txt", b"hello")
    provider.put("a/c.txt", b"world")
    assert provider.get("a/b.txt") == b"hello"
    assert provider.list() == ["a/b.txt", "a/c.txt"]
    assert provider.list("a/c") == ["a/c.txt"]
    provider.delete("a/b.txt")
    assert provider.list() == ["a/c.txt"]
    assert provider.capabilities()["provider"] == "local_directory"


def test_provider_refuses_names_escaping_root(tmp_path):
    provider = LocalDirectoryProvider(tmp_path / "store")
    with pytest.raises(ValueError):
        provider.put("../outside.txt", b"nope")


def test_create_backup_records_files_hashes_and_absentees(tmp_path):
    sources, conn = _sources(tmp_path)
    provider = LocalDirectoryProvider(tmp_path / "store")
    manifest = create_backup(provider, sources=sources)
    conn.close()

    assert manifest["backup_id"].startswith("bk-")
    assert manifest["encryption"] == "none"
    assert manifest["parent"] is None
    # sessions.json did not exist: recorded, not silently skipped.
    assert manifest["absent"] == ["sessions"]
    restore_paths = {entry["restore_path"] for entry in manifest["files"]}
    assert restore_paths == {
        "fi.db", "users.json",
        "user_data/alice/permissions.json", "user_data/alice/audit_log.jsonl",
    }
    for entry in manifest["files"]:
        assert entry["sha256"] == continuity._sha256(provider.get(entry["name"]))
        assert entry["bytes"] > 0
    # The manifest itself is stored inside the set and the set is listable.
    assert [m["backup_id"] for m in list_backups(provider)] == [manifest["backup_id"]]


def test_sqlite_snapshot_is_consistent_while_connection_open(tmp_path):
    """The WAL case the naive file copy gets wrong: rows written through a
    still-open connection must appear in the snapshot, because the backup
    goes through the engine, not through the filesystem."""
    sources, conn = _sources(tmp_path)
    conn.execute("INSERT INTO things (name) VALUES ('gamma')")
    conn.commit()  # sits in the -wal file, not yet checkpointed

    provider = LocalDirectoryProvider(tmp_path / "store")
    manifest = create_backup(provider, sources=sources)

    restored_root = tmp_path / "restored"
    restore_backup(provider, manifest["backup_id"], restored_root)
    restored = sqlite3.connect(restored_root / "fi.db")
    names = [row[0] for row in restored.execute("SELECT name FROM things ORDER BY id")]
    restored.close()
    conn.close()
    assert names == ["alpha", "beta", "gamma"]


def test_restore_reproduces_bytes_exactly(tmp_path):
    sources, conn = _sources(tmp_path)
    provider = LocalDirectoryProvider(tmp_path / "store")
    manifest = create_backup(provider, sources=sources)
    conn.close()

    restored_root = tmp_path / "restored"
    written = restore_backup(provider, manifest["backup_id"], restored_root)
    assert len(written) == len(manifest["files"])
    live = tmp_path / "live"
    assert (restored_root / "users.json").read_bytes() == (live / "users.json").read_bytes()
    assert (restored_root / "user_data" / "alice" / "audit_log.jsonl").read_bytes() == \
        (live / "user_data" / "alice" / "audit_log.jsonl").read_bytes()


def test_corruption_is_detected_and_restore_refuses_entirely(tmp_path):
    """Fail-closed both ways: verify names the damage, and restore writes
    nothing at all rather than the intact remainder of a corrupt set."""
    sources, conn = _sources(tmp_path)
    provider = LocalDirectoryProvider(tmp_path / "store")
    manifest = create_backup(provider, sources=sources)
    conn.close()

    victim = next(e for e in manifest["files"] if e["restore_path"] == "users.json")
    provider.put(victim["name"], b'{"alice": "tampered"}')

    failures = verify_backup(provider, manifest["backup_id"])
    assert failures == [f"{victim['name']}: hash mismatch"]

    restored_root = tmp_path / "restored"
    with pytest.raises(ValueError, match="refusing to restore"):
        restore_backup(provider, manifest["backup_id"], restored_root)
    assert not restored_root.exists()


def test_restore_refuses_to_overwrite_without_explicit_flag(tmp_path):
    sources, conn = _sources(tmp_path)
    provider = LocalDirectoryProvider(tmp_path / "store")
    manifest = create_backup(provider, sources=sources)
    conn.close()

    restored_root = tmp_path / "restored"
    (restored_root / "users.json").parent.mkdir(parents=True)
    (restored_root / "users.json").write_text("live state", encoding="utf-8")

    with pytest.raises(FileExistsError):
        restore_backup(provider, manifest["backup_id"], restored_root)
    assert (restored_root / "users.json").read_text(encoding="utf-8") == "live state"

    restore_backup(provider, manifest["backup_id"], restored_root, overwrite=True)
    assert json.loads((restored_root / "users.json").read_text(encoding="utf-8")) == {"alice": "hash"}


def test_incomplete_set_without_manifest_is_not_a_backup(tmp_path):
    """The manifest-last ordering: files without a manifest are an interrupted
    write, and neither listing nor verification will treat them as a set."""
    provider = LocalDirectoryProvider(tmp_path / "store")
    provider.put("bk-20260824T000000Z-abcdef/files/fi.db", b"orphan bytes")
    assert list_backups(provider) == []
    with pytest.raises(ValueError, match="no complete backup set"):
        verify_backup(provider, "bk-20260824T000000Z-abcdef")


def test_backup_ids_are_unique_and_time_ordered(tmp_path):
    sources, conn = _sources(tmp_path)
    provider = LocalDirectoryProvider(tmp_path / "store")
    first = create_backup(provider, sources=sources)
    second = create_backup(provider, sources=sources)
    conn.close()
    assert first["backup_id"] != second["backup_id"]
    listed = [m["backup_id"] for m in list_backups(provider)]
    assert set(listed) == {first["backup_id"], second["backup_id"]}


# --- The §59 increment: policy settings, retention, the encrypted secondary ---


def test_policy_settings_fail_loud_on_bad_values(monkeypatch):
    """A typo'd policy value must refuse, not silently become the default
    (the model_budget._limit contract, restated for continuity)."""
    monkeypatch.delenv(continuity.INTERVAL_ENV, raising=False)
    monkeypatch.delenv(continuity.RETENTION_ENV, raising=False)
    assert continuity.backup_interval_seconds() == continuity.DEFAULT_BACKUP_INTERVAL_SECONDS
    assert continuity.retention_count() == continuity.DEFAULT_RETENTION_COUNT

    monkeypatch.setenv(continuity.INTERVAL_ENV, "six hours")
    with pytest.raises(ValueError, match="not a number"):
        continuity.backup_interval_seconds()
    monkeypatch.setenv(continuity.INTERVAL_ENV, "-1")
    with pytest.raises(ValueError, match="negative"):
        continuity.backup_interval_seconds()
    # 0 is legal for the interval (it means: automated backups off)...
    monkeypatch.setenv(continuity.INTERVAL_ENV, "0")
    assert continuity.backup_interval_seconds() == 0.0
    # ...but not for retention: keeping zero backups is not a retention policy.
    monkeypatch.setenv(continuity.RETENTION_ENV, "0")
    with pytest.raises(ValueError, match="at least one"):
        continuity.retention_count()


def test_ensure_backup_key_creates_once_then_reuses(tmp_path, capsys):
    key_path = tmp_path / "backup.key"
    first = continuity.ensure_backup_key(key_path)
    assert key_path.exists()
    assert "NEW backup encryption key" in capsys.readouterr().out
    second = continuity.ensure_backup_key(key_path)
    assert second == first
    # Reuse is silent: the loud warning belongs to generation only.
    assert capsys.readouterr().out == ""


def _encrypted(tmp_path, key_name="backup.key"):
    inner = continuity.LocalDirectoryProvider(tmp_path / "secondary")
    key = continuity.ensure_backup_key(tmp_path / key_name)
    return continuity.EncryptedProvider(inner, key), inner


def test_encrypted_provider_stores_ciphertext_roundtrips_plaintext(tmp_path):
    provider, inner = _encrypted(tmp_path)
    provider.put("a/b.txt", b"credentials live here")
    # Through the wrapper: plaintext. On the destination: not.
    assert provider.get("a/b.txt") == b"credentials live here"
    assert b"credentials" not in inner.get("a/b.txt")
    caps = provider.capabilities()
    assert caps["provider"] == "encrypted+local_directory"
    assert caps["encryption"] is True


def test_backup_through_encrypted_provider_verifies_and_restores(tmp_path):
    """The full §1.4 exercise on the secondary path: create, verify, restore,
    read back — with manifest hashes of the *plaintext*, so a primary set and
    a secondary set of the same files carry comparable integrity records."""
    sources, conn = _sources(tmp_path)
    provider, inner = _encrypted(tmp_path)
    manifest = create_backup(provider, sources=sources)
    conn.close()

    assert manifest["encryption"] == "fernet"
    users_entry = next(e for e in manifest["files"] if e["restore_path"] == "users.json")
    # Plaintext hash in the manifest; ciphertext (a different hash) at rest.
    assert continuity._sha256(inner.get(users_entry["name"])) != users_entry["sha256"]
    assert verify_backup(provider, manifest["backup_id"]) == []

    restored_root = tmp_path / "restored"
    restore_backup(provider, manifest["backup_id"], restored_root)
    assert (restored_root / "users.json").read_bytes() == (tmp_path / "live" / "users.json").read_bytes()
    restored = sqlite3.connect(restored_root / "fi.db")
    names = [row[0] for row in restored.execute("SELECT name FROM things ORDER BY id")]
    restored.close()
    assert names == ["alpha", "beta"]


def test_wrong_key_is_a_verification_failure_not_a_crash(tmp_path):
    """Tampered ciphertext and a wrong key look identical from outside: the
    file will not decrypt. Verify reports it per file; restore refuses the
    whole set, fail-closed, exactly as it does on a hash mismatch."""
    sources, conn = _sources(tmp_path)
    provider, inner = _encrypted(tmp_path)
    manifest = create_backup(provider, sources=sources)
    conn.close()

    wrong = continuity.EncryptedProvider(inner, continuity.ensure_backup_key(tmp_path / "other.key"))
    failures = verify_backup(wrong, manifest["backup_id"])
    assert failures and all("unreadable" in f for f in failures)
    with pytest.raises(ValueError, match="refusing to restore"):
        restore_backup(wrong, manifest["backup_id"], tmp_path / "restored")


def test_prune_keeps_newest_sets_and_removes_every_file(tmp_path):
    sources, conn = _sources(tmp_path)
    provider = LocalDirectoryProvider(tmp_path / "store")
    manifests = [create_backup(provider, sources=sources) for _ in range(4)]
    conn.close()

    pruned = continuity.prune_backups(provider, keep=2)
    assert pruned == [m["backup_id"] for m in manifests[:2]]
    kept = [m["backup_id"] for m in list_backups(provider)]
    assert kept == [m["backup_id"] for m in manifests[2:]]
    # No orphan files linger from the pruned sets.
    for backup_id in pruned:
        assert provider.list(f"{backup_id}/") == []
    # Pruning to the current size is a no-op.
    assert continuity.prune_backups(provider, keep=2) == []
    with pytest.raises(ValueError, match="at least one"):
        continuity.prune_backups(provider, keep=0)


def test_prune_does_not_touch_incomplete_sets(tmp_path):
    """Files without a manifest are an interrupted write, not a backup —
    prune_backups has no authority over them (they may be a create_backup in
    progress right now)."""
    sources, conn = _sources(tmp_path)
    provider = LocalDirectoryProvider(tmp_path / "store")
    create_backup(provider, sources=sources)
    conn.close()
    provider.put("bk-20990101T000000Z-ffffff/files/fi.db", b"in-flight bytes")

    assert continuity.prune_backups(provider, keep=1) == []
    assert provider.get("bk-20990101T000000Z-ffffff/files/fi.db") == b"in-flight bytes"


def test_run_backup_cycle_writes_primary_plain_and_secondary_encrypted(tmp_path, monkeypatch):
    sources, conn = _sources(tmp_path)
    monkeypatch.setattr(continuity, "BACKUP_ROOT", tmp_path / "primary")
    monkeypatch.setenv(continuity.SECONDARY_ROOT_ENV, str(tmp_path / "secondary"))
    monkeypatch.setenv(continuity.KEY_PATH_ENV, str(tmp_path / "backup.key"))
    monkeypatch.delenv(continuity.RETENTION_ENV, raising=False)

    results = continuity.run_backup_cycle(sources=sources)
    conn.close()
    assert results["primary"]["ok"] and results["primary"]["encryption"] == "none"
    assert results["secondary"]["ok"] and results["secondary"]["encryption"] == "fernet"

    # The primary holds plaintext, the secondary does not — same content,
    # different failure-domain posture.
    primary_raw = continuity.LocalDirectoryProvider(tmp_path / "primary")
    secondary_raw = continuity.LocalDirectoryProvider(tmp_path / "secondary")
    users_primary = next(n for n in primary_raw.list() if n.endswith("users.json"))
    users_secondary = next(n for n in secondary_raw.list() if n.endswith("users.json"))
    assert b"alice" in primary_raw.get(users_primary)
    assert b"alice" not in secondary_raw.get(users_secondary)

    # And the secondary is restorable through the wrapper — the §1.4 proof
    # for the destination that actually leaves the failure domain.
    wrapped = continuity.EncryptedProvider(
        secondary_raw, continuity.ensure_backup_key(tmp_path / "backup.key"))
    restore_backup(wrapped, results["secondary"]["backup_id"], tmp_path / "restored")
    assert (tmp_path / "restored" / "users.json").read_bytes() == \
        (tmp_path / "live" / "users.json").read_bytes()


def test_run_backup_cycle_enforces_retention_each_pass(tmp_path, monkeypatch):
    sources, conn = _sources(tmp_path)
    monkeypatch.setattr(continuity, "BACKUP_ROOT", tmp_path / "primary")
    monkeypatch.delenv(continuity.SECONDARY_ROOT_ENV, raising=False)
    monkeypatch.setenv(continuity.RETENTION_ENV, "1")

    first = continuity.run_backup_cycle(sources=sources)
    second = continuity.run_backup_cycle(sources=sources)
    conn.close()
    assert first["primary"]["pruned"] == []
    assert second["primary"]["pruned"] == [first["primary"]["backup_id"]]
    provider = continuity.LocalDirectoryProvider(tmp_path / "primary")
    assert [m["backup_id"] for m in list_backups(provider)] == [second["primary"]["backup_id"]]
    assert "secondary" not in first  # no secondary configured, none invented


def test_run_backup_cycle_destinations_fail_independently(tmp_path, monkeypatch):
    """Two destinations that share a failure mode are not two failure
    domains: a broken secondary must cost nothing but its own copy."""
    sources, conn = _sources(tmp_path)

    class BrokenProvider(continuity.StorageProvider):
        def put(self, name, data):
            raise OSError("disk full")

        def capabilities(self):
            return {"provider": "broken", "encryption": True}

    good = LocalDirectoryProvider(tmp_path / "primary")
    monkeypatch.setattr(continuity, "backup_destinations",
                        lambda: [("primary", good), ("secondary", BrokenProvider())])
    monkeypatch.delenv(continuity.RETENTION_ENV, raising=False)

    results = continuity.run_backup_cycle(sources=sources)
    conn.close()
    assert results["primary"]["ok"]
    assert results["secondary"] == {"ok": False, "error": "OSError: disk full"}
    assert len(list_backups(good)) == 1


def test_critical_sources_names_the_real_backup_domain():
    """The domain is the gitignored state: both databases, both credential
    files, and the per-user tree. Paths resolve through the owning modules'
    own constants, so the suite's environment redirects apply here too."""
    sources = critical_sources()
    assert [s["label"] for s in sources] == [
        "financial_intelligence", "gateway", "users", "sessions", "user_data",
    ]
    assert all(s["kind"] in {"sqlite", "file", "tree"} for s in sources)
    by_label = {s["label"]: s for s in sources}
    assert by_label["financial_intelligence"]["kind"] == "sqlite"
    assert by_label["gateway"]["kind"] == "sqlite"
    assert by_label["user_data"]["kind"] == "tree"
