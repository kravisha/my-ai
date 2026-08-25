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

Encryption before upload (§10.1), originally deferred here with the reason
recorded (§48), is now half-closed by the §59 increment: the *primary*
destination stays plaintext (same failure domain, same disk — encryption
there adds key-loss risk per §10.3 without moving the copy anywhere a third
party could read it), and any *secondary* destination (CONTINUITY_SECONDARY_ROOT)
is unconditionally wrapped in EncryptedProvider, because a second destination
exists precisely to leave this machine's failure domain, and the moment a copy
leaves the domain the original deferral's reason stops applying.
Note what that means for the plaintext primary: gateway.db session rows and
sessions.json are credentials, and a backup set is exactly as sensitive as
the live files.
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

ROOT_ENV = "CONTINUITY_BACKUP_ROOT"
# The automated-backup policy (§59), all resolved at call time so tests and a
# reconfigured process both see current values:
# - interval: the de facto RPO for everything the backup domain covers - a
#   crash loses at most this much plus whatever the shutdown backup missed.
#   0 disables the loop entirely. Recorded in TIMING_CONSTANTS.md.
# - retention: how many complete sets each destination keeps.
# - secondary root: a second destination in a different failure domain
#   (another disk, a synced folder). Unset means no secondary - this module
#   cannot invent where your second disk is.
# - key path: where the secondary's encryption key lives (see
#   ensure_backup_key for the custody obligation that comes with it).
INTERVAL_ENV = "CONTINUITY_BACKUP_INTERVAL_SECONDS"
RETENTION_ENV = "CONTINUITY_RETENTION_COUNT"
SECONDARY_ROOT_ENV = "CONTINUITY_SECONDARY_ROOT"
KEY_PATH_ENV = "CONTINUITY_KEY_PATH"

DEFAULT_BACKUP_INTERVAL_SECONDS = 21600.0  # 6h - a disclosed convention, not a measured RPO requirement
DEFAULT_RETENTION_COUNT = 14

# Honoured the same way FI_DB_PATH is (see backend/fi_db.py): environment
# first, project-root default second, evaluated at import.
BACKUP_ROOT = Path(os.environ.get(ROOT_ENV) or (PROJECT_ROOT / "backups"))

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1


def _positive_setting(env_name: str, default: float) -> float:
    """Fail-loud numeric config, the model_budget._limit contract: a typo'd
    policy value must not silently become the default."""
    raw = os.environ.get(env_name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(
            f"{env_name}={raw!r} is not a number. Refusing to guess a continuity policy - "
            "fix or unset the variable."
        ) from None
    if value < 0:
        raise ValueError(f"{env_name}={value} is negative; a continuity policy value cannot be.")
    return value


def backup_interval_seconds() -> float:
    return _positive_setting(INTERVAL_ENV, DEFAULT_BACKUP_INTERVAL_SECONDS)


def retention_count() -> int:
    value = int(_positive_setting(RETENTION_ENV, DEFAULT_RETENTION_COUNT))
    if value < 1:
        raise ValueError(f"{RETENTION_ENV} must keep at least one set; got {value}")
    return value


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


def ensure_backup_key(path: str | Path | None = None) -> bytes:
    """Load - or on first use create - the Fernet key the secondary copies
    are encrypted under.

    Addendum 29 §10.3, stated as bluntly as it deserves: **a perfectly
    encrypted backup with a lost key is not a backup.** This key file is
    itself Tier-0 recovery material - it must never be committed
    (.gitignore covers it), and a copy belongs somewhere OFF this machine,
    because the disaster that takes the primary disk takes the key with it
    and turns every secondary copy into noise. Generation is deliberately
    loud for that reason."""
    path = Path(path or os.environ.get(KEY_PATH_ENV) or (PROJECT_ROOT / "backup.key"))
    if path.exists():
        return path.read_bytes().strip()
    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key + b"\n")
    print(
        f"[continuity] NEW backup encryption key generated at {path}.\n"
        "[continuity] Secondary backup copies are unreadable without it - store a copy of this\n"
        "[continuity] file OFF this machine now (addendum 29 SS10.3), and never commit it."
    )
    return key


class EncryptedProvider(StorageProvider):
    """Encrypt-before-upload (addendum 29 §10.1) as a wrapping provider -
    the same decorator shape app/model_budget.py's BudgetedProvider uses,
    for the same reason: everything above the interface (manifests, hashes,
    verify, restore) works unchanged, because put/get are the only places
    bytes cross the boundary. The destination never holds decryption
    authority (§10.2): ciphertext goes out, the key stays local.

    Manifest hashes are therefore of the *plaintext* - get() decrypts before
    verify_backup ever hashes - which is what makes a primary set and a
    secondary set of the same files carry comparable integrity records."""

    def __init__(self, inner: StorageProvider, key: bytes):
        from cryptography.fernet import Fernet

        self.inner = inner
        self._fernet = Fernet(key)

    def put(self, name: str, data: bytes) -> None:
        self.inner.put(name, self._fernet.encrypt(data))

    def get(self, name: str) -> bytes:
        return self._fernet.decrypt(self.inner.get(name))

    def list(self, prefix: str = "") -> list[str]:
        return self.inner.list(prefix)

    def delete(self, name: str) -> None:
        self.inner.delete(name)

    def health(self) -> dict:
        return self.inner.health()

    def capabilities(self) -> dict:
        inner = self.inner.capabilities()
        return {**inner, "provider": f"encrypted+{inner.get('provider', 'unknown')}", "encryption": True}


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

    capabilities = provider.capabilities()
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "backup_id": backup_id,
        "created_at": created_at,
        "fi_schema_version": SCHEMA_VERSION,
        "provider": capabilities,
        # What the destination actually holds - 'fernet' through an
        # EncryptedProvider, 'none' on the plain same-domain adapter (§48's
        # recorded deferral, closed by §59's secondary destination).
        "encryption": "fernet" if capabilities.get("encryption") else "none",
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
    try:
        manifest = _load_manifest(provider, backup_id)
    except ValueError:
        raise  # a *missing* manifest means "not a backup", not "damaged backup"
    except Exception as exc:  # noqa: BLE001
        # An unreadable manifest (wrong key, tampered ciphertext) is the
        # whole set failing verification in one line - same reasoning as the
        # per-file case below.
        return [f"{backup_id}/{MANIFEST_NAME}: unreadable ({exc.__class__.__name__})"]
    failures = []
    for entry in manifest["files"]:
        try:
            data = provider.get(entry["name"])
        except FileNotFoundError:
            failures.append(f"{entry['name']}: missing")
            continue
        except Exception as exc:  # noqa: BLE001 - an unreadable file IS the finding
            # An encrypted copy that will not decrypt (tampered ciphertext,
            # wrong key) is a verification failure to report, not an
            # exception to crash the verifier - the fail-closed restore
            # refuses on it exactly as it does on a hash mismatch.
            failures.append(f"{entry['name']}: unreadable ({exc.__class__.__name__})")
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


def prune_backups(provider: StorageProvider, keep: int | None = None) -> list[str]:
    """Delete the oldest complete sets beyond the retention count; returns the
    pruned backup ids.

    Deletion order is the mirror of creation order, on purpose: the manifest
    goes first, so a prune interrupted halfway leaves files-without-a-manifest
    — which this module already defines as "not a backup" (list_backups,
    verify_backup). The invariant that makes an interrupted *create* harmless
    makes an interrupted *delete* harmless too. Sets that were never complete
    (no manifest) are not this function's to touch: it prunes backups, and
    they are not backups."""
    keep = retention_count() if keep is None else keep
    if keep < 1:
        raise ValueError(f"retention must keep at least one set; got {keep}")
    manifests = list_backups(provider)  # oldest first
    pruned = []
    for manifest in manifests[: max(0, len(manifests) - keep)]:
        backup_id = manifest["backup_id"]
        provider.delete(f"{backup_id}/{MANIFEST_NAME}")
        for name in provider.list(f"{backup_id}/"):
            provider.delete(name)
        pruned.append(backup_id)
    return pruned


def secondary_root() -> Path | None:
    """The second destination, if the owner has named one. Resolved at call
    time (unlike BACKUP_ROOT) because the §59 policy block above promises it:
    a reconfigured process sees the current value."""
    raw = os.environ.get(SECONDARY_ROOT_ENV)
    return Path(raw) if raw else None


def backup_destinations() -> list[tuple[str, StorageProvider]]:
    """Every destination the automated cycle writes to, labelled.

    The primary is the plain local adapter. A secondary, when configured, is
    *unconditionally* encrypted — there is no plaintext-secondary option,
    because the only reason to configure one is failure-domain separation,
    and §10.1 makes encryption mandatory the moment a copy leaves the
    primary domain. The module docstring carries the full reasoning."""
    destinations: list[tuple[str, StorageProvider]] = [
        ("primary", LocalDirectoryProvider(BACKUP_ROOT)),
    ]
    root = secondary_root()
    if root is not None:
        destinations.append(
            ("secondary", EncryptedProvider(LocalDirectoryProvider(root), ensure_backup_key()))
        )
    return destinations


def run_backup_cycle(sources: list[dict] | None = None) -> dict:
    """One full automated pass: back up to every destination, then enforce
    retention on each. Returns a per-destination summary.

    Destinations fail independently — a full secondary disk must not stop the
    primary copy, and vice versa; two destinations that share a failure mode
    in this code would not be two failure domains. Each destination's outcome
    (including the failure text) lands in the summary for the caller to log;
    nothing here is allowed to raise past the loop."""
    keep = retention_count()
    results: dict[str, dict] = {}
    for label, provider in backup_destinations():
        try:
            manifest = create_backup(provider, sources=sources)
            pruned = prune_backups(provider, keep=keep)
            results[label] = {
                "ok": True,
                "backup_id": manifest["backup_id"],
                "files": len(manifest["files"]),
                "absent": manifest["absent"],
                "encryption": manifest["encryption"],
                "pruned": pruned,
            }
        except Exception as exc:  # noqa: BLE001 - the summary IS the error channel
            results[label] = {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}
    return results


def main(argv: list[str] | None = None) -> int:
    # The CLI loads .env; importing this module does not (§69).
    #
    # Found by configuring a real secondary destination and watching the CLI
    # ignore it: the server process reads .env only because something in its
    # import graph calls load_dotenv, and nothing in this module's graph
    # does - so `python -m backend.continuity backup` wrote to the primary
    # alone and reported success, which is §1.8's "silently weakened
    # recoverability" on the exact path INCIDENT_RESPONSE.md sends a human
    # down mid-incident. Loaded here rather than at import so importing this
    # module stays free (the lesson tests/test_db_isolation.py exists to
    # keep), and after argparse would be too late for nothing - it is the
    # first thing main does.
    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(
        prog="python -m backend.continuity",
        description="Backup and restore of critical persistent state (addendum 29, slice 1).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("backup",
                   help="run one full cycle: back up every present critical source to every "
                        "configured destination, then enforce retention on each")
    sub.add_parser("prune", help="enforce the retention count on every configured destination")
    # list/verify/restore address one destination. --secondary exists because
    # an encrypted copy nobody can restore from the command line is not a
    # recovery asset (§1.4 applies to the secondary too).
    secondary_help = "address the encrypted secondary destination instead of the primary"
    p_list = sub.add_parser("list", help="list complete backup sets")
    p_list.add_argument("--secondary", action="store_true", help=secondary_help)
    p_verify = sub.add_parser("verify", help="recompute a set's integrity hashes")
    p_verify.add_argument("backup_id")
    p_verify.add_argument("--secondary", action="store_true", help=secondary_help)
    p_restore = sub.add_parser("restore", help="restore a set under a destination root")
    p_restore.add_argument("backup_id")
    p_restore.add_argument("dest_root")
    p_restore.add_argument("--overwrite", action="store_true",
                           help="replace existing files at the destination")
    p_restore.add_argument("--secondary", action="store_true", help=secondary_help)
    args = parser.parse_args(argv)

    def _print_cycle(results: dict, root_note: str) -> int:
        failed = False
        for label, outcome in results.items():
            if outcome.get("ok"):
                pruned = f", pruned {len(outcome['pruned'])}" if outcome.get("pruned") else ""
                print(f"{label}: {outcome['backup_id']} — {outcome['files']} file(s), "
                      f"encryption {outcome['encryption']}{pruned}")
                if outcome["absent"]:
                    print(f"{label}: absent sources (recorded in manifest): "
                          f"{', '.join(outcome['absent'])}")
            else:
                failed = True
                print(f"{label}: FAILED — {outcome['error']}")
        print(root_note)
        return 1 if failed else 0

    if args.command == "backup":
        return _print_cycle(run_backup_cycle(), f"primary root: {BACKUP_ROOT}")
    if args.command == "prune":
        keep = retention_count()
        code = 0
        for label, provider in backup_destinations():
            try:
                pruned = prune_backups(provider, keep=keep)
            except Exception as exc:  # noqa: BLE001 - report and continue to the next destination
                print(f"{label}: FAILED — {exc.__class__.__name__}: {exc}")
                code = 1
                continue
            print(f"{label}: pruned {len(pruned)} set(s) beyond retention {keep}"
                  + (f": {', '.join(pruned)}" if pruned else ""))
        return code

    if getattr(args, "secondary", False):
        root = secondary_root()
        if root is None:
            print(f"{SECONDARY_ROOT_ENV} is not set; there is no secondary destination to address")
            return 2
        provider: StorageProvider = EncryptedProvider(LocalDirectoryProvider(root), ensure_backup_key())
        described_root = root
    else:
        provider = LocalDirectoryProvider()
        described_root = BACKUP_ROOT

    if args.command == "list":
        manifests = list_backups(provider)
        if not manifests:
            print(f"no complete backup sets under {described_root}")
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
