"""Business Continuity, first slice (addendum 29; TASK_QUEUE TQ-02): backup of
critical persistent state through a provider-neutral interface, with restore
that is actually exercised.

Addendum 29's discipline, applied at this system's real scale:

- §1.3 no single point of irrecoverable failure: every store this system
  writes lives on one disk. This module creates the first recovery copy.
- §1.4 a backup that has never been restored is not a recovery asset:
  restore is a first-class function here, and tests/test_continuity.py
  performs a real restore-and-read on every run of the suite.
- §8.1 provider neutrality: callers depend on StorageProvider, not on a
  filesystem. The first adapter is a local directory — §1.7 explicitly names
  local storage a legitimate provider; the interface is what keeps Dropbox,
  object storage, or a NAS a new adapter rather than a redesign.
- §7.4 backup metadata: every set carries a manifest with per-file SHA-256,
  source paths, and the FI schema version. The manifest is written *last*,
  so a set interrupted mid-write has no manifest and is invisible to
  list_backups — an incomplete backup cannot be mistaken for a complete one.

What is deliberately excluded from the backup domain, and why (recorded here
because §1.8 forbids silently weakening recoverability — an exclusion must be
a decision, not an accident):

- `.env` (secrets): recovery of an API key is re-issuance at the provider,
  not restore from a copy; duplicating secrets onto more of the same disk
  adds exposure without adding recoverability (§9.1's spirit).
- `simulation/runs/`: reproducible from scenario + recorded seed + code
  version — §12.4's derived-data rule, already stated in .gitignore.
- Source code: Git's job; repository continuity (§38) is a separate concern.

Encryption before upload (§10.1) is deferred for this adapter with the reason
recorded: the local-directory adapter stays in the primary failure domain, so
encryption here adds key-loss risk (§10.3) without moving the copy anywhere a
third party could read it. The first *remote* adapter makes it mandatory.
Note what that means meanwhile: gateway.db session rows and sessions.json are
credentials, and a backup set is exactly as sensitive as the live files.
"""

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from backend.db import now_iso

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Honoured the same way FI_DB_PATH is (see backend/fi_db.py): environment
# first, project-root default second, evaluated at import.
BACKUP_ROOT = Path(os.environ.get("CONTINUITY_BACKUP_ROOT") or (PROJECT_ROOT / "backups"))

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1


class StorageProvider:
    """Addendum 29 §8.1's conceptual interface, sized to what slice 1 uses.

    Names are POSIX-style relative paths ('bk-.../files/gateway.db'). A
    provider stores bytes under a name and gives them back; everything about
    backup sets, manifests, and integrity lives above this line, so a new
    provider implements storage and nothing else.
    """

    def put(self, name: str, data: bytes) -> None:
        raise NotImplementedError

    def get(self, name: str) -> bytes:
        raise NotImplementedError

    def list(self, prefix: str = "") -> list[str]:
        raise NotImplementedError

    def delete(self, name: str) -> None:
        raise NotImplementedError

    def health(self) -> dict:
        raise NotImplementedError

    def capabilities(self) -> dict:
        """§8.3's capability profile, so callers can refuse a provider that
        cannot satisfy policy instead of discovering it during recovery."""
        raise NotImplementedError


class LocalDirectoryProvider(StorageProvider):
    """Local directory as a storage provider — §1.7 names this a legitimate
    resilience layer. Point BACKUP_ROOT (or the constructor) at a second
    disk or a synced folder and the failure-domain separation improves
    without a code change; that is the point of the interface."""

    def __init__(self, root: str | Path = BACKUP_ROOT):
        self.root = Path(root)

    def _path(self, name: str) -> Path:
        path = (self.root / name).resolve()
        # A name is data, not a path: refuse anything that escapes the root
        # (the same closure app/users.py applies to usernames-as-directories).
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError(f"storage name escapes provider root: {name!r}")
        return path

    def put(self, name: str, data: bytes) -> None:
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, name: str) -> bytes:
        return self._path(name).read_bytes()

    def list(self, prefix: str = "") -> list[str]:
        if not self.root.exists():
            return []
        names = []
        for path in self.root.rglob("*"):
            if path.is_file():
                name = path.relative_to(self.root).as_posix()
                if name.startswith(prefix):
                    names.append(name)
        return sorted(names)

    def delete(self, name: str) -> None:
        path = self._path(name)
        if path.exists():
            path.unlink()

    def health(self) -> dict:
        return {"root": str(self.root), "exists": self.root.exists()}

    def capabilities(self) -> dict:
        return {
            "provider": "local_directory",
            "versioning": False,
            "immutability": False,
            "encryption": False,
            "offsite": False,
        }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _snapshot_sqlite(source: Path) -> bytes:
    """A consistent point-in-time copy of a live SQLite database.

    Copying the file bytes of a WAL-mode database that another process is
    writing produces a torn copy — the main file and the -wal file move
    independently. sqlite3's backup API takes a transactional snapshot
    through the engine itself, which is the difference between a backup and
    a file that merely looks like one. The snapshot lands in a sibling temp
    file (same directory, so no cross-device surprises) that is always
    removed."""
    temp = source.parent / f".{source.name}.continuity-snapshot"
    try:
        source_conn = sqlite3.connect(source)
        try:
            dest_conn = sqlite3.connect(temp)
            try:
                source_conn.backup(dest_conn)
            finally:
                dest_conn.close()
        finally:
            source_conn.close()
        return temp.read_bytes()
    finally:
        if temp.exists():
            temp.unlink()


def critical_sources() -> list[dict]:
    """The backup domain: every store that cannot be reproduced from code.

    Resolved through the same import-time constants the owning modules use
    (fi_db.DB_PATH, gateway.store.DB_PATH, app paths), so an environment
    redirect moves the backup domain with the data instead of drifting from
    it. Each entry: label (stable identity), path, kind (sqlite / file /
    tree), and restore_path — where the content belongs relative to a
    restore root, which for every current source is its project-root-relative
    location."""
    from app.session import SESSION_PATH
    from app.users import USERS_PATH, USER_DATA_ROOT
    from backend import fi_db
    from gateway import store as gateway_store

    return [
        {"label": "financial_intelligence", "path": Path(fi_db.DB_PATH), "kind": "sqlite",
         "restore_path": "financial_intelligence.db"},
        {"label": "gateway", "path": Path(gateway_store.DB_PATH), "kind": "sqlite",
         "restore_path": "gateway.db"},
        {"label": "users", "path": Path(USERS_PATH), "kind": "file",
         "restore_path": "users.json"},
        {"label": "sessions", "path": Path(SESSION_PATH), "kind": "file",
         "restore_path": "sessions.json"},
        {"label": "user_data", "path": Path(USER_DATA_ROOT), "kind": "tree",
         "restore_path": "user_data"},
    ]


def _new_backup_id(created_at: str) -> str:
    """Sortable by creation time, collision-proofed by a random suffix (two
    backups within one second must not merge into one set)."""
    stamp = datetime.fromisoformat(created_at).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"bk-{stamp}-{secrets.token_hex(3)}"


def create_backup(provider: StorageProvider, sources: list[dict] | None = None) -> dict:
    """Copy every present source into a new backup set and return its manifest.

    Absent sources are recorded in the manifest rather than skipped silently —
    a restore must be able to distinguish "users.json was not backed up" from
    "users.json did not exist" (§1.8: shortcuts must not silently weaken
    recovery). The manifest is stored last; see the module docstring for why
    that ordering is the completeness guarantee."""
    if sources is None:
        sources = critical_sources()

    created_at = now_iso()
    backup_id = _new_backup_id(created_at)
    files: list[dict] = []
    absent: list[str] = []

    for source in sources:
        path: Path = source["path"]
        if not path.exists():
            absent.append(source["label"])
            continue
        if source["kind"] == "sqlite":
            members = [(source["restore_path"], _snapshot_sqlite(path), str(path))]
        elif source["kind"] == "file":
            members = [(source["restore_path"], path.read_bytes(), str(path))]
        elif source["kind"] == "tree":
            members = []
            for member in sorted(path.rglob("*")):
                if member.is_file():
                    relative = member.relative_to(path).as_posix()
                    members.append((f"{source['restore_path']}/{relative}", member.read_bytes(), str(member)))
        else:
            raise ValueError(f"unknown source kind: {source['kind']!r}")

        for restore_path, data, source_path in members:
            stored_name = f"{backup_id}/files/{restore_path}"
            provider.put(stored_name, data)
            files.append({
                "name": stored_name,
                "label": source["label"],
                "restore_path": restore_path,
                "source_path": source_path,
                "sha256": _sha256(data),
                "bytes": len(data),
            })

    from backend.fi_db import SCHEMA_VERSION

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "backup_id": backup_id,
        "created_at": created_at,
        "fi_schema_version": SCHEMA_VERSION,
        "provider": provider.capabilities(),
        "encryption": "none",  # local-directory adapter; see module docstring
        "parent": None,  # full backups only in this slice; no incrementals
        "files": files,
        "absent": absent,
    }
    provider.put(f"{backup_id}/{MANIFEST_NAME}", json.dumps(manifest, indent=2).encode("utf-8"))
    return manifest


def list_backups(provider: StorageProvider) -> list[dict]:
    """Every *complete* backup set, oldest first. Completeness is defined by
    manifest presence — an interrupted create_backup left files but no
    manifest, and those files are not a backup."""
    manifests = []
    for name in provider.list():
        if name.endswith(f"/{MANIFEST_NAME}") and name.count("/") == 1:
            manifests.append(json.loads(provider.get(name).decode("utf-8")))
    manifests.sort(key=lambda m: m["created_at"])
    return manifests


def _load_manifest(provider: StorageProvider, backup_id: str) -> dict:
    try:
        raw = provider.get(f"{backup_id}/{MANIFEST_NAME}")
    except FileNotFoundError:
        raise ValueError(f"no complete backup set named {backup_id!r} (no manifest)") from None
    return json.loads(raw.decode("utf-8"))


def verify_backup(provider: StorageProvider, backup_id: str) -> list[str]:
    """Recompute every stored file's hash against the manifest. Returns the
    list of failures, empty meaning the set is intact — the continuous
    integrity check addendum 29 §51 asks for, callable from anywhere."""
    manifest = _load_manifest(provider, backup_id)
    failures = []
    for entry in manifest["files"]:
        try:
            data = provider.get(entry["name"])
        except FileNotFoundError:
            failures.append(f"{entry['name']}: missing")
            continue
        if _sha256(data) != entry["sha256"]:
            failures.append(f"{entry['name']}: hash mismatch")
    return failures


def restore_backup(
    provider: StorageProvider, backup_id: str, dest_root: str | Path, overwrite: bool = False
) -> list[Path]:
    """Restore a backup set under dest_root, reproducing each source at its
    restore_path. Returns the written paths.

    Fail-closed in both directions: the entire set is verified before a
    single byte is written (restoring the intact half of a corrupt backup is
    how partial states that never existed get created), and an existing
    destination file refuses to be clobbered unless overwrite is explicit —
    a restore aimed at live state should hurt a little."""
    failures = verify_backup(provider, backup_id)
    if failures:
        raise ValueError(f"backup {backup_id} failed verification; refusing to restore: {failures}")

    manifest = _load_manifest(provider, backup_id)
    dest_root = Path(dest_root)

    if not overwrite:
        for entry in manifest["files"]:
            target = dest_root / entry["restore_path"]
            if target.exists():
                raise FileExistsError(
                    f"{target} exists; pass overwrite=True to replace live state deliberately"
                )

    written = []
    for entry in manifest["files"]:
        target = dest_root / entry["restore_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(provider.get(entry["name"]))
        written.append(target)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.continuity",
        description="Backup and restore of critical persistent state (addendum 29, slice 1).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("backup", help="create a new backup set of every present critical source")
    sub.add_parser("list", help="list complete backup sets")
    p_verify = sub.add_parser("verify", help="recompute a set's integrity hashes")
    p_verify.add_argument("backup_id")
    p_restore = sub.add_parser("restore", help="restore a set under a destination root")
    p_restore.add_argument("backup_id")
    p_restore.add_argument("dest_root")
    p_restore.add_argument("--overwrite", action="store_true",
                           help="replace existing files at the destination")
    args = parser.parse_args(argv)

    provider = LocalDirectoryProvider()

    if args.command == "backup":
        manifest = create_backup(provider)
        print(f"{manifest['backup_id']}: {len(manifest['files'])} file(s) stored under {BACKUP_ROOT}")
        if manifest["absent"]:
            print(f"absent sources (recorded in manifest): {', '.join(manifest['absent'])}")
        return 0
    if args.command == "list":
        manifests = list_backups(provider)
        if not manifests:
            print(f"no complete backup sets under {BACKUP_ROOT}")
        for manifest in manifests:
            print(f"{manifest['backup_id']}  {manifest['created_at']}  "
                  f"{len(manifest['files'])} file(s), absent: {manifest['absent'] or 'none'}")
        return 0
    if args.command == "verify":
        failures = verify_backup(provider, args.backup_id)
        if failures:
            for failure in failures:
                print(f"FAIL {failure}")
            return 1
        print(f"{args.backup_id}: intact")
        return 0
    if args.command == "restore":
        written = restore_backup(provider, args.backup_id, args.dest_root, overwrite=args.overwrite)
        print(f"{args.backup_id}: restored {len(written)} file(s) under {args.dest_root}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
