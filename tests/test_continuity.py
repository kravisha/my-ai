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
