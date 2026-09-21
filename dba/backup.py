"""Backup and restore (§25, §26).

    *"A backup is not considered valid until restoration has been tested."*

That sentence decides the whole design. Taking a backup here **restores it**
into a throwaway location, opens it, integrity-checks it and compares its
contents against the source before recording it as good. A file that has never
been restored is recorded as `unverified` and `current()` will not return it,
because an untested backup is a belief rather than a backup — and it is a
belief that is only tested on the worst day.

## Four things this gets right on purpose

**It is not a file copy.** These databases run in WAL mode, so the bytes in the
`.db` file are not the database: committed pages sit in the `-wal` sidecar, and
a copy taken mid-write opens cleanly with the last transactions missing. That
is the worst failure a backup can have, because it looks like success.
`Database.backup_to` uses SQLite's online backup API, which copies pages under
the engine's own lock and produces one self-contained file.

**The catalogue does not live in the database it backs up.** Each backup has a
JSON manifest beside it, and the catalogue is built by *scanning the
directory*. A record of your backups stored in the database you are trying to
restore is a record you lose at exactly the moment you need it.

**Restoring takes a backup first.** A restore overwrites the live database,
which is the most destructive thing in this package. So the current state is
backed up as `pre_restore` before anything is replaced — if the restore was a
mistake, the mistake is undoable.

**The last good copy is never pruned.** Retention deletes the oldest beyond
`keep`, and refuses to delete the newest verified backup whatever the number
says. A retention rule that can delete the last good copy is not a retention
rule.

## What is not here, said rather than omitted

§25's *"encrypted secondary location"* — the spec says *eventually*, and there
is no second location on this machine to write to. `describe()` reports it as
absent with that reason rather than leaving the field out, because an absent
measurement reads as a clean one.

Only `dba.db` is covered. `financial_intelligence.db` and `gateway.db` belong
to services that are still their own owners (see `dba/__init__.py`), and
backing up a database this agent does not govern would be taking
responsibility it has not been given. `STORES` is the list; adding one is a
line, and each needs its own restore story before it goes in.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from backend.db import Database, now_iso
from dba import config, ids, store

# Which stores this agent backs up. One today, and the reason the list exists
# rather than a constant is that adding the second one should be a line plus a
# restore story, not a rewrite.
STORES = ("dba",)

MANIFEST_SUFFIX = ".manifest.json"
BACKUP_SUFFIX = ".db"

# Reasons a backup was taken, for the manifest and the audit trail.
SCHEDULED = "scheduled"
REQUESTED = "requested"
PRE_RESTORE = "pre_restore"
REASONS = (SCHEDULED, REQUESTED, PRE_RESTORE)

# Verification outcomes.
VERIFIED = "verified"
UNVERIFIED = "unverified"
FAILED = "failed"


class BackupRefused(RuntimeError):
    """A backup or restore that will not proceed, carrying why."""


@dataclass(frozen=True)
class Backup:
    """One taken backup and everything known about it."""

    backup_id: str
    path: Path
    taken_at: str
    reason: str
    source: str
    bytes: int
    sha256: str
    schema_version: int
    row_counts: dict
    status: str
    verification: dict = field(default_factory=dict)

    @property
    def manifest_path(self) -> Path:
        return self.path.with_name(self.path.name.replace(BACKUP_SUFFIX, "")
                                   + MANIFEST_SUFFIX)

    @property
    def verified(self) -> bool:
        return self.status == VERIFIED

    @property
    def recovery_point(self) -> str:
        """§26: the moment the restored database would be at."""
        return self.taken_at

    def to_dict(self) -> dict:
        return {
            "backup_id": self.backup_id, "path": str(self.path),
            "taken_at": self.taken_at, "reason": self.reason,
            "source": self.source, "bytes": self.bytes, "sha256": self.sha256,
            "schema_version": self.schema_version,
            "row_counts": dict(self.row_counts), "status": self.status,
            "verification": dict(self.verification),
            "recovery_point": self.recovery_point,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "Backup":
        return cls(
            backup_id=payload["backup_id"], path=Path(payload["path"]),
            taken_at=payload["taken_at"], reason=payload.get("reason", REQUESTED),
            source=payload.get("source", "dba"), bytes=int(payload.get("bytes", 0)),
            sha256=payload.get("sha256", ""),
            schema_version=int(payload.get("schema_version", 0)),
            row_counts=dict(payload.get("row_counts") or {}),
            status=payload.get("status", UNVERIFIED),
            verification=dict(payload.get("verification") or {}))


# --- taking one ---------------------------------------------------------------


def take(*, reason: str = REQUESTED, source: str = "dba",
         directory: Path | None = None, protect: str | None = None) -> Backup:
    """§25: a full, timestamped, verified backup. Raises `BackupRefused`.

    `protect` names a backup that must survive the prune at the end. It exists
    for one caller and one very sharp bug: `restore` takes a safety backup
    first, and that new entry pushed the backup **being restored** past `keep`
    and deleted it - so restoring the oldest copy destroyed it and then failed.
    The safety net removed the thing it was protecting."""
    if reason not in REASONS:
        raise ValueError(f"backup reason={reason!r} is not one of {REASONS}")
    if source not in STORES:
        raise BackupRefused(
            f"{source!r} is not a store this agent backs up. It backs up "
            f"{', '.join(STORES)}; the others belong to services that are "
            f"still their own owners.")

    live = store.database_path()
    if not live.exists():
        raise BackupRefused(
            f"there is no database at {live} to back up. That is a fact about "
            f"this machine rather than a failure - nothing has been stored yet.")

    target_dir = Path(directory) if directory else config.backup_directory()
    target_dir.mkdir(parents=True, exist_ok=True)
    _require_room(target_dir, live)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_id = f"{source}-{stamp}-{ids.new_id('b').split('-')[1][:8]}"
    path = target_dir / f"{backup_id}{BACKUP_SUFFIX}"

    conn = store.connect()
    try:
        store.init_schema(conn)
        live_counts = row_counts(conn)
        conn.backup_to(path)
    finally:
        conn.close()

    # THE COUNTS ARE READ FROM THE BACKUP, NOT FROM THE LIVE DATABASE.
    #
    # Reading them before the copy meant any write landing in between made the
    # restored copy disagree with the manifest, and a perfectly good backup was
    # marked FAILED - `take` raising because somebody else was working. The
    # backup API takes a consistent snapshot; what the manifest should describe
    # is what is *in that snapshot*, which is also exactly what a restore will
    # produce.
    taken_conn = Database(path)
    try:
        source_counts = row_counts(taken_conn)
        source_version = _schema_version_of(taken_conn)
    finally:
        taken_conn.close()

    drifted = {table: (live_counts.get(table), source_counts.get(table))
               for table in sorted(set(live_counts) | set(source_counts))
               if live_counts.get(table) != source_counts.get(table)}

    backup = Backup(
        backup_id=backup_id, path=path, taken_at=now_iso(), reason=reason,
        source=source, bytes=path.stat().st_size, sha256=_sha256(path),
        schema_version=source_version, row_counts=source_counts,
        status=UNVERIFIED,
        verification={"wrote_while_copying": drifted} if drifted else {})

    # `replace` rather than rebuilding from `to_dict`: the dict carries
    # `recovery_point`, which is a derived property and not a field, and
    # round-tripping through it passes an argument the constructor has never
    # had. A frozen dataclass has one correct way to make a changed copy.
    if config.verify_by_restoring():
        verification = verify(backup, expected_counts=source_counts,
                              expected_version=source_version)
        if drifted:
            verification = {**verification, "wrote_while_copying": drifted}
        backup = dataclasses.replace(
            backup,
            status=VERIFIED if verification["passed"] else FAILED,
            verification=verification)
    else:
        backup = dataclasses.replace(
            backup, status=UNVERIFIED,
            verification={
                "passed": False,
                "why": "backup.verify_by_restoring is off in config/dba.yaml. "
                       "This backup has never been restored, so nothing is "
                       "known about whether it can be."})

    _write_manifest(backup)
    if backup.status == FAILED:
        raise BackupRefused(
            f"the backup was written to {path} and did not survive "
            f"verification: {backup.verification.get('why', 'unknown')}. It is "
            f"kept and marked failed rather than deleted, so the failure can "
            f"be looked at.")
    prune(directory=target_dir, protect={backup_id} | (
        {protect} if protect else set()))
    return backup


def _require_room(target_dir: Path, live: Path) -> None:
    """§25, and the failure mode nobody plans for: the backup that fills the
    disk and takes the live database down with it."""
    try:
        usage = shutil.disk_usage(target_dir)
    except OSError:
        return
    needed = live.stat().st_size + config.minimum_free_bytes()
    if usage.free < needed:
        raise BackupRefused(
            f"refusing to back up: {usage.free // (1024 * 1024)} MB free at "
            f"{target_dir}, and this needs {needed // (1024 * 1024)} MB "
            f"including the {config.minimum_free_bytes() // (1024 * 1024)} MB "
            f"headroom config/dba.yaml requires. A backup that fills the disk "
            f"takes the live database with it.")


# --- §26: it is not valid until restoration has been tested -------------------


def verify(backup: Backup, *, expected_counts: dict | None = None,
           expected_version: int | None = None) -> dict:
    """Restore the backup somewhere harmless and check it is really there.

    Four questions, and the third is the one §26 is actually about:

    1. Is the file intact? (sha256 against the manifest, `PRAGMA integrity_check`)
    2. Does it open as a database, with the schema this build expects?
    3. **Does a restore of it produce the data that was backed up?** - restored
       into a temporary directory, opened as a fresh database, row counts
       compared table by table against the source.
    4. Is anything the DBA needs actually in it? - the capability declarations
       and the audit trail, named explicitly, because a backup that restored an
       empty schema would pass a row-count comparison against an empty source.
    """
    checks: list[dict] = []
    workspace = Path(tempfile.mkdtemp(prefix="dba-restore-test-"))
    try:
        if not backup.path.exists():
            return {"passed": False, "why": f"{backup.path} is not there",
                    "checks": checks}

        digest = _sha256(backup.path)
        intact = (not backup.sha256) or digest == backup.sha256
        checks.append(_check("file_intact", intact,
                             "sha256 matches the manifest" if intact
                             else f"sha256 is {digest}, manifest says "
                                  f"{backup.sha256}"))

        # The restore test proper: a real copy, opened as a real database.
        restored_path = workspace / "restored.db"
        shutil.copy2(backup.path, restored_path)
        restored = Database(restored_path)
        try:
            integrity = restored.fetchone("PRAGMA integrity_check")
            verdict = list(integrity.values())[0] if integrity else "unknown"
            checks.append(_check("integrity_check", verdict == "ok", str(verdict)))

            version = _schema_version_of(restored)
            expected = (expected_version if expected_version is not None
                        else backup.schema_version)
            checks.append(_check(
                "schema_version", version == expected,
                f"restored at version {version}, backup recorded {expected}"))

            counts = row_counts(restored)
            wanted = expected_counts if expected_counts is not None \
                else backup.row_counts
            differing = {table: (wanted.get(table), counts.get(table))
                         for table in sorted(set(wanted) | set(counts))
                         if wanted.get(table) != counts.get(table)}
            checks.append(_check(
                "restored_contents_match", not differing,
                f"{len(counts)} table(s) match the source" if not differing
                else f"differences: {differing}"))

            # A backup of an empty database is a valid backup of an empty
            # database, and saying so is more useful than a check that passes
            # because there was nothing to compare.
            total = sum(counts.values())
            checks.append(_check(
                "has_contents", True,
                f"{total} row(s) across {len(counts)} table(s)"
                + ("" if total else " - the source was empty, and this backup "
                                    "faithfully contains nothing"),
            ))

            essential = [table for table in ("capabilities", "audit_events",
                                             "entities")
                         if table not in counts]
            checks.append(_check(
                "essential_tables_present", not essential,
                "the capability, audit and record tables restored"
                if not essential else f"missing: {', '.join(essential)}"))
        finally:
            restored.close()
    except Exception as bad:  # noqa: BLE001 - a crash is a failed verification
        checks.append(_check("verification_completed", False,
                             f"{type(bad).__name__}: {bad}"))
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    failing = [check["check"] for check in checks if not check["passed"]]
    return {
        "passed": not failing,
        "checks": checks,
        "failing": failing,
        "why": ("restored into a throwaway database and matched the source"
                if not failing else f"failed: {', '.join(failing)}"),
        "tested_by": "restoring it, per §26 - a backup that has never been "
                     "restored is a belief rather than a backup",
        "at": now_iso(),
    }


def _check(name: str, passed: bool, detail: str) -> dict:
    return {"check": name, "passed": bool(passed), "detail": detail}


# --- the catalogue, which does not live in the database it protects -----------


def catalogue(directory: Path | None = None) -> list[Backup]:
    """Every backup on disk, newest first, read from the manifests beside them.

    Built by scanning rather than by querying, because a record of your backups
    stored inside the database you are restoring is a record you have lost at
    the moment you need it."""
    target_dir = Path(directory) if directory else config.backup_directory()
    if not target_dir.exists():
        return []
    found: list[Backup] = []
    for manifest in sorted(target_dir.glob(f"*{MANIFEST_SUFFIX}")):
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            backup = Backup.from_dict(payload)
        except (OSError, ValueError, KeyError):
            # A manifest that will not parse is a real problem and is not this
            # function's to solve: it reports what it can read rather than
            # failing the whole catalogue over one damaged sidecar.
            continue
        if not backup.path.exists():
            continue
        found.append(backup)
    return sorted(found, key=lambda item: item.taken_at, reverse=True)


def current(directory: Path | None = None) -> Backup | None:
    """§26's "which backup is current": the newest **verified** one.

    Never an unverified backup, however recent. The whole point of §26 is that
    recency is not the property that matters."""
    for backup in catalogue(directory):
        if backup.verified:
            return backup
    return None


def get(backup_id: str, directory: Path | None = None) -> Backup | None:
    for backup in catalogue(directory):
        if backup.backup_id == backup_id:
            return backup
    return None


def prune(directory: Path | None = None,
          protect: set[str] | None = None) -> list[str]:
    """§25's retention. `keep` counts **verified** backups.

    The first version counted every entry, so a run of failed or unverified
    backups pushed the good ones out and left one verified copy where the
    policy said fourteen - retention deleting exactly what it exists to
    retain. `keep` now means "this many restorable copies".

    Unverified and failed entries are kept while they are among the newest
    `keep` of their own kind, because a recent failure is diagnostic and an
    old one is litter.

    Two things are never deleted whatever the arithmetic says: the newest
    verified backup, and anything named in `protect` - which is how `restore`
    stops its own safety backup from evicting the backup being restored."""
    target_dir = Path(directory) if directory else config.backup_directory()
    everything = catalogue(target_dir)
    limit = config.keep()
    protect = set(protect or ())

    keeping: set[str] = set(protect)
    verified_kept = 0
    other_kept = 0
    for backup in everything:  # newest first
        if backup.verified:
            if verified_kept < limit:
                keeping.add(backup.backup_id)
                verified_kept += 1
        elif other_kept < limit:
            keeping.add(backup.backup_id)
            other_kept += 1

    newest_verified = next((backup.backup_id for backup in everything
                            if backup.verified), None)
    if newest_verified:
        keeping.add(newest_verified)

    removed: list[str] = []
    for backup in everything:
        if backup.backup_id in keeping:
            continue
        try:
            backup.path.unlink(missing_ok=True)
            backup.manifest_path.unlink(missing_ok=True)
            removed.append(backup.backup_id)
        except OSError:
            continue
    return removed


# --- restoring ----------------------------------------------------------------


def restore(backup_id: str, *, accepted_by: str, confirmed: bool = False,
            allow_unverified: bool = False,
            directory: Path | None = None) -> dict:
    """Replace the live database with a backup. The dangerous one.

    Four guards, and each is here because of what this does rather than out of
    caution in general:

    - **`administer` only.** Restoring discards everything written since the
      backup. That is not an operation an ordinary agent should be able to
      reach, and the DBA itself does not hold the permission.
    - **`confirmed` must be explicit.** The recovery point is in the refusal
      message, so whoever confirms has been told what they are giving up.
    - **A verified backup, unless overridden aloud.** Restoring an untested
      file over a working database is how one bad day becomes two.
    - **The current state is backed up first.** A restore that was a mistake
      is then undoable, which is the difference between a recovery and a
      second incident.
    """
    from dba import permissions

    if permissions.ADMINISTER not in permissions.permissions_of(accepted_by):
        raise BackupRefused(
            f"{accepted_by!r} cannot restore: that needs "
            f"{permissions.ADMINISTER!r}. A restore discards every write made "
            f"since the backup was taken.")

    backup = get(backup_id, directory)
    if backup is None:
        raise BackupRefused(f"no backup {backup_id!r} is on disk.")

    if not backup.verified and not allow_unverified:
        raise BackupRefused(
            f"{backup_id} is {backup.status}: {backup.verification.get('why', 'it has never been restored')}. "
            f"Restoring an untested file over a working database is how one "
            f"bad day becomes two. Pass allow_unverified to override, having "
            f"read that sentence.")

    live = store.database_path()
    if not confirmed:
        raise BackupRefused(
            f"restoring {backup_id} would replace {live} with the database as "
            f"it was at {backup.recovery_point}. Everything written since is "
            f"discarded. Confirm to proceed.")

    # The current state, kept. If this restore was the mistake, it is undoable.
    #
    # AND IT MUST NOT BE ABLE TO STOP THE RESTORE. The first version called
    # `take` unguarded, so a restore from a **corrupt live database** died
    # inside its own safety net with an uncaught sqlite3 error - failing in
    # precisely the situation a restore exists for. A proper backup of a
    # corrupt database is not possible; a byte copy of it is, and it is better
    # evidence than nothing. `protect` stops this new entry from evicting the
    # backup being restored, which is how the safety net used to delete it.
    safety = None
    safety_note = None
    if live.exists():
        try:
            safety = take(reason=PRE_RESTORE, directory=directory,
                          protect=backup_id)
        except Exception as bad:  # noqa: BLE001 - see above
            safety_note = _raw_copy(live, directory, bad)

    # Re-verify immediately before overwriting. The catalogue was read a moment
    # ago and this is the last point at which a corrupt file can be caught
    # cheaply.
    verification = verify(backup)
    if not verification["passed"] and not allow_unverified:
        raise BackupRefused(
            f"{backup_id} failed verification at the moment of restore: "
            f"{verification['why']}. Nothing was replaced"
            + (f"; the current state is backed up as {safety.backup_id}."
               if safety else f"; {safety_note}." if safety_note else "."))

    _replace(live, backup.path)

    conn = store.connect()
    try:
        restored_version = _schema_version_of(conn)
        restored_counts = row_counts(conn)
    finally:
        conn.close()

    return {
        "restored": backup_id,
        "recovery_point": backup.recovery_point,
        "schema_version": restored_version,
        "row_counts": restored_counts,
        "previous_state_backed_up_as": safety.backup_id if safety else None,
        "previous_state_note": safety_note,
        "verification": verification,
        "restored_by": accepted_by,
        "at": now_iso(),
    }


def _raw_copy(live: Path, directory: Path | None,
              why: BaseException) -> str:
    """A byte copy of a database that could not be backed up properly.

    Used only when the safety backup fails, which in practice means the live
    database is damaged - and a byte copy of a damaged database is still the
    only surviving evidence of what was there. Deliberately NOT given a
    manifest: it is not a backup, it cannot be restored from through
    `restore`, and putting it in the catalogue would let something later treat
    it as one."""
    target_dir = Path(directory) if directory else config.backup_directory()
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rescue = target_dir / f"UNRESTORABLE-raw-copy-{stamp}.db"
    try:
        shutil.copy2(live, rescue)
        return (f"the current database could not be backed up "
                f"({type(why).__name__}: {why}); a raw byte copy was kept at "
                f"{rescue.name}. It is not a backup and is not in the "
                f"catalogue - it is evidence")
    except OSError as bad:
        return (f"the current database could not be backed up "
                f"({type(why).__name__}: {why}) and a raw copy also failed "
                f"({bad}). Nothing of the current state was preserved")


def _replace(live: Path, source: Path) -> None:
    """Put the backup in place of the live database.

    Three things, and each was found by the restore test failing rather than by
    thinking about it beforehand.

    **Refuse while another process is writing.** `BEGIN IMMEDIATE` takes the
    write lock; if it cannot, somebody is mid-transaction and replacing the
    file under them would lose their write.

    It is a POINT-IN-TIME check and not a held lock, and saying so matters:
    `Database.execute` commits after every statement, so the lock is taken and
    released immediately, and nothing prevents a writer arriving a millisecond
    later. No lock *can* be held across replacing the file - the connection
    holding it has to close first. So this catches the common case and the
    documented procedure ("stop the service first") remains the real
    protection.

    **Swap atomically, do not overwrite.** `shutil.copy2` opens the
    destination for writing, which truncates it **in place** - so a connection
    that is already open watches its database become a half-written file and
    gets a disk I/O error. Writing beside it and `os.replace`-ing is atomic:
    an open connection keeps the old inode, which is unlinked but alive, and
    finishes safely on it. New connections get the restored database.

    **The sidecars must go.** A WAL-mode database has `-wal` and `-shm` files
    beside it belonging to the database that was there before, and the engine
    would apply that old write-ahead log to the new file - which is not a
    restore, it is corruption produced by a recovery. They are checkpointed
    first, so nothing committed is thrown away with them.

    HONESTLY: the explicit removal below could not be shown to be
    load-bearing. In every case that could be constructed - including one
    where the checkpoint itself is made to fail - closing the probe connection
    already causes SQLite to delete the log, and the tests passed with the
    `unlink` deleted. It is kept because the hazard it guards is corruption
    rather than an error, and five lines is a cheap guard against a future
    change to the lines above it. But `tests/test_dba_backup.py` asserts the
    outcome, not this mechanism, because a test that cannot fail is worse than
    no test."""
    from backend.db import Contended

    live.parent.mkdir(parents=True, exist_ok=True)

    if live.exists():
        try:
            probe = Database(live)
        except Exception:  # noqa: BLE001 - see below
            # A database that cannot be opened has no writer to wait for, and
            # is exactly the one being restored over. The first version let
            # this raise, so a restore from a corrupt live database died here
            # - in the swap, after the safety copy had already coped with the
            # same corruption.
            probe = None
        if probe is not None:
            try:
                try:
                    probe.execute("BEGIN IMMEDIATE")
                except Contended as busy:
                    raise BackupRefused(
                        f"another process is writing to {live} and the restore "
                        f"would replace the database underneath it: {busy}. "
                        f"Stop the DBA service first - that is step 1 of the "
                        f"procedure, and this is the check that it happened."
                    ) from busy
                except Exception:  # noqa: BLE001 - unopenable, see above
                    pass
                try:
                    # Reports busy by RETURNING busy=1, not by raising - so an
                    # `except` around this never fires, and the first version
                    # could not tell a checkpoint that happened from one that
                    # did not. Not fatal either way: the pre-restore backup
                    # went through the online backup API, which includes
                    # everything in the log.
                    probe.fetchone("PRAGMA wal_checkpoint(TRUNCATE)")
                except Exception:  # noqa: BLE001 - best effort; swap is next
                    pass
            finally:
                probe.close()

    staging = live.with_name(live.name + ".restoring")
    try:
        shutil.copy2(source, staging)
        # REPLACE FIRST, THEN REMOVE THE SIDECARS. The other order unlinks a
        # write-ahead log that may hold committed transactions and then, if
        # the rename fails, leaves the live database missing them.
        #
        # That hazard could not be reproduced - closing the probe connection
        # above makes SQLite checkpoint the log into the main file first, so
        # the transactions are already safe by the time anything is unlinked.
        # The order is this way round because it is strictly safer and costs
        # nothing, not because a test demanded it; the test asserts that a
        # failed restore loses nothing, which is the property either way.
        try:
            os.replace(staging, live)
        except PermissionError as denied:
            # WINDOWS. A file that any process has open cannot be replaced -
            # `os.replace` fails with access denied rather than doing what it
            # does on POSIX, where the old inode survives for existing
            # readers. Windows CI found this, on the platform Krish runs.
            #
            # Refused rather than falling back to overwriting in place. The
            # in-place write is what gave an open connection a half-written
            # database in the first place, and quietly choosing the unsafe
            # path on one platform is how a restore becomes the incident.
            raise BackupRefused(
                f"the database could not be replaced because something still "
                f"has {live.name} open ({denied}). On Windows a file in use "
                f"cannot be swapped. Stop the DBA service and retry - that is "
                f"step 1 of the restore procedure. Nothing was changed."
            ) from denied
        for sidecar in (live.with_name(live.name + "-wal"),
                        live.with_name(live.name + "-shm")):
            try:
                sidecar.unlink(missing_ok=True)
            except OSError:
                pass
    finally:
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            pass


# --- §25's scheduled backup ---------------------------------------------------


def due(now: datetime | None = None, last_backup: datetime | None = None,
        directory: Path | None = None) -> bool:
    """Whether a backup should be taken.

    Hour-based rather than cron, for the reason `app/self_diagnosis.py` gives
    about its own schedule: this runs inside whatever process happens to be up,
    and a scheduler that assumes it is running silently stops on a machine that
    was asleep. A backup already taken today is not taken twice."""
    moment = now or datetime.now()
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    if moment.hour < config.backup_hour():
        return False
    if last_backup is None:
        # The newest backup of ANY status. Asking `current()` first meant a
        # newer unverified or failed backup was invisible, so the schedule
        # thought nothing had been taken and took another on every call -
        # a failing backup turning into an unbounded loop of failing backups.
        everything = catalogue(directory)
        latest = everything[0] if everything else None
        if latest is not None:
            try:
                last_backup = datetime.fromisoformat(latest.taken_at)
            except ValueError:
                last_backup = None
    if last_backup is not None:
        if last_backup.tzinfo is not None:
            last_backup = last_backup.astimezone()
        if last_backup.date() >= moment.date():
            return False
    return True


def run_if_due(now: datetime | None = None,
               directory: Path | None = None) -> Backup | None:
    """Take today's backup if it has not been taken. Idempotent through the
    catalogue, so a caller that invokes this hourly gets one a day."""
    if not due(now, directory=directory):
        return None
    return take(reason=SCHEDULED, directory=directory)


# --- §26's documentation ------------------------------------------------------


def describe(directory: Path | None = None) -> dict:
    """§26: how to restore, which backup is current, the recovery point, the
    schema version and the validation procedure - answered from what is
    actually on disk rather than from a runbook that can go stale."""
    latest = current(directory)
    everything = catalogue(directory)
    return {
        "policy": config.describe()["backup"],
        "backups_on_disk": len(everything),
        "verified": len([item for item in everything if item.verified]),
        "failed": len([item for item in everything if item.status == FAILED]),
        "current": latest.to_dict() if latest else None,
        "recovery_point": latest.recovery_point if latest else None,
        "schema_version": latest.schema_version if latest else None,
        "how_to_restore": [
            "1. Stop anything writing to the DBA (the service on port 8200).",
            "2. POST /backups/{backup_id}/restore with an operator credential "
            "and {\"confirmed\": true}. Or, in a shell: "
            "python -c \"from dba import backup; "
            "print(backup.restore('<backup_id>', "
            "accepted_by='operator_console', confirmed=True))\"",
            "3. The current database is backed up as a `pre_restore` backup "
            "before anything is replaced; note its id from the response.",
            "4. The response carries the recovery point, the schema version "
            "and the row counts actually restored. Check them.",
            "5. Restart the DBA service.",
        ],
        "validation_procedure": [
            "Every backup is verified when it is taken: the file is hashed, "
            "restored into a throwaway database, integrity-checked, and its "
            "row counts compared table by table against the source (§26).",
            "`current()` returns only a verified backup, so recency alone "
            "never makes a backup eligible to restore from.",
            "The same verification runs again immediately before a restore "
            "overwrites anything.",
        ],
        "not_implemented": {
            "encrypted_secondary_location":
                "§25 says this should eventually be supported. There is no "
                "second location configured on this machine to write to, and "
                "nothing is encrypted at rest. Reported rather than omitted, "
                "because an absent measurement reads as a clean one.",
            "other_databases":
                "financial_intelligence.db and gateway.db are not backed up "
                "here. They belong to services that are still their own "
                "owners, and each needs its own restore story before it joins "
                "this list.",
        },
    }


# --- helpers ------------------------------------------------------------------


def row_counts(conn: Database) -> dict[str, int]:
    """Every table and how many rows it holds.

    The comparison that makes a restore test mean something: a file that opens
    and integrity-checks can still be missing a table's worth of rows."""
    tables = [row["name"] for row in conn.fetchall(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    counts: dict[str, int] = {}
    for table in tables:
        row = conn.fetchone(f'SELECT COUNT(*) AS n FROM "{table}"')
        counts[table] = int(row["n"]) if row else 0
    return counts


def _schema_version_of(conn: Database) -> int:
    row = conn.fetchone("SELECT value FROM dba_meta WHERE key = 'schema_version'")
    return int(row["value"]) if row else 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- the command a scheduler calls --------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """`python -m dba.backup --if-due`, the shape `app/self_diagnosis.py` uses.

    Nothing in this repository runs on a timer by itself, and pretending
    otherwise would be the worst kind of backup story - one everybody believes
    is running. This is the command a cron entry, a systemd timer or Task
    Scheduler calls; until one exists, `--if-due` does nothing on most runs
    and says so."""
    import argparse

    parser = argparse.ArgumentParser(
        description="The DBA's backups: take, verify, list, restore.")
    parser.add_argument("--if-due", action="store_true",
                        help="take today's backup if the schedule says so")
    parser.add_argument("--take", action="store_true", help="take one now")
    parser.add_argument("--list", action="store_true",
                        help="the catalogue and how to restore")
    parser.add_argument("--verify", metavar="BACKUP_ID",
                        help="restore it somewhere harmless and check it")
    parser.add_argument("--restore", metavar="BACKUP_ID")
    parser.add_argument("--confirmed", action="store_true",
                        help="required by --restore; it discards every write "
                             "made since the backup")
    arguments = parser.parse_args(argv)

    try:
        if arguments.list or not any((arguments.if_due, arguments.take,
                                      arguments.verify, arguments.restore)):
            described = describe()
            print(json.dumps(described, indent=2, default=str))
            return 0
        if arguments.if_due:
            taken = run_if_due()
            print(f"took {taken.backup_id}" if taken
                  else "nothing was due; today's backup already exists")
            return 0
        if arguments.take:
            taken = take(reason=REQUESTED)
            print(f"took {taken.backup_id} ({taken.bytes} bytes, "
                  f"{taken.status})")
            return 0
        if arguments.verify:
            found = get(arguments.verify)
            if found is None:
                print(f"no backup {arguments.verify!r} is on disk")
                return 1
            outcome = verify(found)
            print(json.dumps(outcome, indent=2, default=str))
            return 0 if outcome["passed"] else 1
        if arguments.restore:
            from dba import permissions

            outcome = restore(arguments.restore,
                              accepted_by=permissions.OPERATOR_CONSOLE,
                              confirmed=arguments.confirmed)
            print(json.dumps(outcome, indent=2, default=str))
            return 0
    except BackupRefused as refused:
        print(f"refused: {refused}")
        return 1
    return 0


def _write_manifest(backup: Backup) -> None:
    backup.manifest_path.write_text(
        json.dumps(backup.to_dict(), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover - a command, not a code path
    raise SystemExit(main())
