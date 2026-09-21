"""Backup and restore: is the backup real, and has anyone ever restored it?

§26's first line is the one this file is built around:

> *"A backup is not considered valid until restoration has been tested."*

So most of these tests are not about whether a file gets written. They are
about whether the file is the database, whether anything has checked, and what
happens on the day somebody actually needs it — which is the day every
untested assumption in a backup system gets tested at once.
"""

import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.db import Database
from dba import (agent as agent_module, backup, config, contract, health,
                 permissions, records, registry, store)

JARVIS = permissions.JARVIS
KRISH = permissions.OPERATOR_CONSOLE


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PATH_ENV, str(tmp_path / "dba.db"))
    monkeypatch.setenv("DBA_BACKUP_DIR", str(tmp_path / "backups"))
    agent_module._AGENT = None
    registry.reset_sync()
    config._CACHE.clear()
    yield tmp_path
    agent_module._AGENT = None
    registry.reset_sync()
    config._CACHE.clear()


@pytest.fixture()
def agent():
    return agent_module.DBAgent()


def _people(agent, count=3):
    return [agent.handle(contract.Request(
        action=contract.CREATE, requested_by=JARVIS, entity_type="person",
        data={"name": f"Person {index}"})).entity_id
        for index in range(count)]


# =============================================================================
# The thing a backup has to get right before anything else
# =============================================================================


def test_a_backup_is_not_a_file_copy(tmp_path):
    """THE DEFECT THIS WHOLE APPROACH EXISTS TO AVOID.

    These databases run in WAL mode, so the bytes in the `.db` file are not
    the database - committed pages sit in the `-wal` sidecar. A copy of the
    `.db` alone opens cleanly and is missing data, which is the worst failure
    a backup can have because it looks like success.

    The gap is not subtle: with a handful of rows written, a file copy does
    not contain the table at all."""
    source = tmp_path / "source.db"
    db = Database(source)
    db.executescript("CREATE TABLE t(x TEXT);")
    for index in range(5):
        db.execute("INSERT INTO t VALUES (?)", (f"row{index}",))

    naive = tmp_path / "file-copy.db"
    shutil.copy2(source, naive)
    proper = tmp_path / "online-backup.db"
    db.backup_to(proper)
    db.close()

    with pytest.raises(Exception):
        Database(naive).fetchone("SELECT COUNT(*) FROM t")
    assert Database(proper).fetchone("SELECT COUNT(*) AS n FROM t")["n"] == 5


# =============================================================================
# §26: verified means restored
# =============================================================================


def test_taking_a_backup_restores_it_before_calling_it_good(agent):
    _people(agent)
    taken = backup.take()

    assert taken.verified
    checks = {check["check"]: check["passed"]
              for check in taken.verification["checks"]}
    assert checks["integrity_check"]
    assert checks["restored_contents_match"], "the row counts were compared"
    assert checks["essential_tables_present"]
    assert "restoring it" in taken.verification["tested_by"]


def test_the_verification_compares_the_restored_rows_against_the_source(agent):
    """A file that opens and integrity-checks can still be missing a table's
    worth of rows, so the check that matters is the comparison."""
    _people(agent, 4)
    taken = backup.take()
    assert taken.row_counts["entities"] == 4
    assert taken.row_counts["audit_events"] == 4


def test_a_corrupted_backup_does_not_pass_verification(agent):
    _people(agent)
    taken = backup.take()

    taken.path.write_bytes(b"this is not a database")
    again = backup.verify(taken)

    assert not again["passed"]
    assert "file_intact" in again["failing"]


def test_a_truncated_backup_is_caught_even_if_the_hash_is_not_checked(agent):
    """The hash catches a changed file; `integrity_check` catches one that was
    cut short by a full disk, where the manifest was never written."""
    _people(agent)
    taken = backup.take()
    damaged = backup.Backup(**{**{key: value for key, value
                                  in taken.to_dict().items()
                                  if key not in ("recovery_point",)},
                               "path": taken.path, "sha256": ""})
    taken.path.write_bytes(taken.path.read_bytes()[:2048])

    assert not backup.verify(damaged)["passed"]


def test_an_unverified_backup_is_never_the_current_one(agent, monkeypatch):
    """§26's whole point: recency is not the property that matters."""
    _people(agent)
    monkeypatch.setattr(config, "verify_by_restoring", lambda: False)

    taken = backup.take()

    assert taken.status == backup.UNVERIFIED
    assert backup.current() is None
    assert backup.catalogue()[0].backup_id == taken.backup_id
    assert "never been restored" in taken.verification["why"]


def test_a_backup_that_fails_verification_is_kept_and_reported(agent,
                                                               monkeypatch):
    """Kept rather than deleted, so the failure can be looked at."""
    _people(agent)
    monkeypatch.setattr(backup, "verify", lambda *a, **k: {
        "passed": False, "why": "invented failure", "checks": [],
        "failing": ["invented"]})

    with pytest.raises(backup.BackupRefused, match="did not survive"):
        backup.take()

    assert backup.catalogue()[0].status == backup.FAILED


# =============================================================================
# The catalogue does not live in the database it protects
# =============================================================================


def test_the_catalogue_survives_losing_the_database_entirely(agent):
    """The property that makes this a backup system rather than a table.

    A record of your backups kept inside the database you are restoring is a
    record you have lost at the moment you need it."""
    _people(agent)
    taken = backup.take()

    store.database_path().unlink()
    for sidecar in ("-wal", "-shm"):
        Path(str(store.database_path()) + sidecar).unlink(missing_ok=True)

    assert backup.current().backup_id == taken.backup_id
    assert backup.describe()["recovery_point"] == taken.recovery_point


def test_a_damaged_manifest_does_not_take_the_whole_catalogue_down(agent):
    _people(agent)
    good = backup.take()
    broken = good.path.with_name("dba-20200101T000000Z-deadbeef" + backup.MANIFEST_SUFFIX)
    broken.write_text("{not json", encoding="utf-8")

    assert [item.backup_id for item in backup.catalogue()] == [good.backup_id]


def test_a_manifest_whose_file_has_gone_is_not_offered(agent):
    _people(agent)
    taken = backup.take()
    taken.path.unlink()
    assert backup.catalogue() == []


# =============================================================================
# Restoring
# =============================================================================


def test_a_restore_actually_recovers_the_data(agent, conn=None):
    """The round trip, which is the only thing that proves any of this."""
    _people(agent, 3)
    taken = backup.take()

    agent.handle(contract.Request(
        action=contract.CREATE, requested_by=JARVIS, entity_type="person",
        data={"name": "Written after the backup"}))
    connection = store.connect()
    try:
        assert records.count(connection, "person") == 4
    finally:
        connection.close()

    outcome = backup.restore(taken.backup_id, accepted_by=KRISH, confirmed=True)

    connection = store.connect()
    try:
        assert records.count(connection, "person") == 3
        assert not connection.fetchall(
            "SELECT 1 FROM entities WHERE name = 'Written after the backup'")
    finally:
        connection.close()
    assert outcome["recovery_point"] == taken.recovery_point


def test_restoring_needs_the_administer_permission(agent):
    _people(agent)
    taken = backup.take()
    for who in (JARVIS, permissions.DBA, permissions.COO):
        with pytest.raises(backup.BackupRefused, match="administer"):
            backup.restore(taken.backup_id, accepted_by=who, confirmed=True)


def test_restoring_needs_an_explicit_confirmation_that_names_what_is_lost(agent):
    _people(agent)
    taken = backup.take()

    with pytest.raises(backup.BackupRefused) as refused:
        backup.restore(taken.backup_id, accepted_by=KRISH)

    assert taken.recovery_point in str(refused.value)
    assert "discarded" in str(refused.value)


def test_an_unverified_backup_is_refused_unless_overridden_aloud(agent,
                                                                 monkeypatch):
    _people(agent)
    monkeypatch.setattr(config, "verify_by_restoring", lambda: False)
    taken = backup.take()

    with pytest.raises(backup.BackupRefused, match="one bad day becomes two"):
        backup.restore(taken.backup_id, accepted_by=KRISH, confirmed=True)

    outcome = backup.restore(taken.backup_id, accepted_by=KRISH, confirmed=True,
                             allow_unverified=True)
    assert outcome["restored"] == taken.backup_id


def test_restoring_backs_up_the_current_state_first(agent):
    """A restore that was a mistake is then undoable, which is the difference
    between a recovery and a second incident."""
    _people(agent, 2)
    taken = backup.take()
    agent.handle(contract.Request(
        action=contract.CREATE, requested_by=JARVIS, entity_type="person",
        data={"name": "About to be lost"}))

    outcome = backup.restore(taken.backup_id, accepted_by=KRISH, confirmed=True)

    safety_id = outcome["previous_state_backed_up_as"]
    assert safety_id
    safety = backup.get(safety_id)
    assert safety.reason == backup.PRE_RESTORE
    assert safety.row_counts["entities"] == 3

    # And it really is undoable.
    backup.restore(safety_id, accepted_by=KRISH, confirmed=True)
    connection = store.connect()
    try:
        assert connection.fetchall(
            "SELECT 1 FROM entities WHERE name = 'About to be lost'")
    finally:
        connection.close()


def test_a_restore_under_an_open_connection_is_clean(agent):
    """The realistic restore: somebody is using the database, which is usually
    why you are restoring it.

    AND IT BEHAVES DIFFERENTLY ON THE TWO PLATFORMS, which Windows CI found
    and which is asserted here rather than papered over.

    On posix, replacing a file under an open reader is fine: the rename is
    atomic and the old inode survives, unlinked but alive, so the held
    connection finishes safely. That is why `shutil.copy2` was replaced - it
    truncates the destination *in place* and gave the held connection a disk
    I/O error.

    On Windows a file that any process has open **cannot be replaced at all**,
    so the restore refuses with a message naming the real cause. Refusing is
    the right answer: the alternative is the in-place overwrite that caused
    the problem on posix, and quietly choosing the unsafe path on one platform
    is how a restore becomes the incident.

    The stale-log assertion is honestly labelled: no way was found to make it
    fail, since SQLite removes the log on the probe connection's close
    regardless. It is here to catch a future change that removes all of it."""
    _people(agent, 2)
    taken = backup.take()
    agent.handle(contract.Request(
        action=contract.CREATE, requested_by=JARVIS, entity_type="person",
        data={"name": "In the stale wal"}))

    live = store.database_path()
    holding = store.connect()
    try:
        holding.execute(
            "INSERT INTO dba_meta (key, value) VALUES ('probe', 'x') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value")
        assert Path(str(live) + "-wal").exists(), "the sidecar is really there"

        if os.name == "nt":
            with pytest.raises(backup.BackupRefused, match="still has"):
                backup.restore(taken.backup_id, accepted_by=KRISH,
                               confirmed=True)
            # And nothing was changed by the refusal.
            assert holding.fetchone(
                "SELECT COUNT(*) AS n FROM entities")["n"] == 3
            return

        backup.restore(taken.backup_id, accepted_by=KRISH, confirmed=True)

        # THE LOAD-BEARING ASSERTION. The held connection is still usable,
        # which it was not when the file was truncated in place.
        assert holding.fetchone("SELECT COUNT(*) AS n FROM entities")["n"] == 3

        # And no stale log survives. See the docstring: this one has not been
        # shown to be able to fail.
        assert not Path(str(live) + "-wal").exists(), \
            "an old write-ahead log beside a restored database is corruption"
    finally:
        holding.close()

    connection = store.connect()
    try:
        assert records.count(connection, "person") == 2
        assert not connection.fetchall(
            "SELECT 1 FROM entities WHERE name = 'In the stale wal'")
    finally:
        connection.close()


def test_restoring_a_backup_that_is_not_there_is_refused(agent):
    with pytest.raises(backup.BackupRefused, match="no backup"):
        backup.restore("dba-19700101T000000Z-00000000", accepted_by=KRISH,
                       confirmed=True)


def test_a_backup_corrupted_after_cataloguing_is_caught_at_restore_time(agent):
    """The catalogue was read a moment ago; this is the last cheap check."""
    _people(agent)
    taken = backup.take()
    taken.path.write_bytes(b"corrupted since it was catalogued")

    with pytest.raises(backup.BackupRefused, match="at the moment of restore"):
        backup.restore(taken.backup_id, accepted_by=KRISH, confirmed=True)

    connection = store.connect()
    try:
        assert records.count(connection, "person") == 3, "nothing was replaced"
    finally:
        connection.close()


def test_a_restore_refuses_while_another_process_is_writing(agent,
                                                            monkeypatch):
    """The documented procedure says to stop writers first; this is the check
    that it happened rather than the hope that it did."""
    from backend.db import Contended

    _people(agent, 2)
    taken = backup.take()

    def contended(*args, **kwargs):
        raise Contended("database is locked")

    monkeypatch.setattr(Database, "execute", contended)

    with pytest.raises(backup.BackupRefused, match="another process is writing"):
        backup.restore(taken.backup_id, accepted_by=KRISH, confirmed=True)


def test_no_half_written_database_is_left_if_the_swap_fails(agent,
                                                            monkeypatch):
    """Copied beside the live file and renamed into place, so there is no
    moment at which the database is a partially written file."""
    _people(agent, 2)
    taken = backup.take()
    live = store.database_path()

    # The rename is the atomic step, so that is what is made to fail. Patching
    # the copy instead broke the pre-restore safety backup's own verification
    # and the restore never reached the swap - the test would have passed
    # while proving nothing about it.
    def failing_rename(*args, **kwargs):
        raise OSError("the disk filled up at the rename")

    monkeypatch.setattr(backup.os, "replace", failing_rename)
    with pytest.raises(OSError):
        backup.restore(taken.backup_id, accepted_by=KRISH, confirmed=True)

    assert not live.with_name(live.name + ".restoring").exists()
    connection = store.connect()
    try:
        assert records.count(connection, "person") == 2, \
            "the live database was never touched"
    finally:
        connection.close()


# =============================================================================
# §25: retention, scheduling, and the disk
# =============================================================================


def test_retention_keeps_the_configured_number(agent, monkeypatch):
    monkeypatch.setattr(config, "keep", lambda: 2)
    _people(agent, 1)
    taken = [backup.take() for _ in range(4)]

    remaining = {item.backup_id for item in backup.catalogue()}

    assert len(remaining) == 2
    assert taken[-1].backup_id in remaining
    assert taken[0].backup_id not in remaining


def test_retention_never_deletes_the_last_verified_backup(agent, monkeypatch):
    """The case this rule exists for: every recent backup has been failing
    verification unnoticed, and retention is about to remove the only good
    one."""
    _people(agent, 1)
    good = backup.take()

    monkeypatch.setattr(config, "verify_by_restoring", lambda: False)
    monkeypatch.setattr(config, "keep", lambda: 1)
    for _ in range(3):
        backup.take()

    remaining = {item.backup_id for item in backup.catalogue()}
    assert good.backup_id in remaining, \
        "the only verified backup was pruned in favour of unverified ones"


def test_a_backup_that_would_fill_the_disk_is_refused(agent, monkeypatch):
    """A backup that fills the disk takes the live database with it."""
    _people(agent)
    monkeypatch.setattr(config, "minimum_free_bytes", lambda: 10 ** 15)

    with pytest.raises(backup.BackupRefused, match="refusing to back up"):
        backup.take()


def test_the_schedule_runs_once_a_day_and_not_twice(agent):
    _people(agent)
    hour = config.backup_hour()
    moment = datetime.now().astimezone().replace(
        hour=max(hour, 12), minute=0, second=0, microsecond=0)

    first = backup.run_if_due(moment)
    second = backup.run_if_due(moment)

    assert first is not None and first.reason == backup.SCHEDULED
    assert second is None, "a backup already taken today is not taken twice"


def test_the_schedule_hour_is_local_whatever_zone_the_caller_holds(agent):
    """Same property `app/self_diagnosis.py` needed: a caller holding a UTC
    instant must not shift the schedule by the machine's offset."""
    hour = config.backup_hour()
    if hour < 2:
        pytest.skip(f"backup.hour is {hour}; nothing is below it")
    here = datetime.now().astimezone().replace(
        hour=hour, minute=30, second=0, microsecond=0)
    elsewhere = here.astimezone(timezone(here.utcoffset() - timedelta(hours=2)))

    assert elsewhere.hour == hour - 2
    assert backup.due(here) is True
    assert backup.due(elsewhere) is True
    assert backup.due(here.astimezone(timezone.utc)) is True


def test_nothing_is_due_before_the_configured_hour(agent):
    hour = config.backup_hour()
    if hour < 1:
        pytest.skip("configured for midnight")
    before = datetime.now().astimezone().replace(hour=hour - 1, minute=0)
    assert backup.due(before) is False


def test_backing_up_a_store_this_agent_does_not_own_is_refused(agent):
    with pytest.raises(backup.BackupRefused, match="still their own owners"):
        backup.take(source="gateway")


def test_backing_up_nothing_is_said_plainly(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PATH_ENV, str(tmp_path / "does-not-exist.db"))
    with pytest.raises(backup.BackupRefused, match="nothing has been stored"):
        backup.take()


# =============================================================================
# What a review found: the safety net breaking the recovery path
# =============================================================================


def test_the_safety_backup_does_not_delete_the_backup_being_restored(
        agent, monkeypatch):
    """THE SHARPEST FINDING. `restore` takes a safety backup first, and that
    new entry pushed the backup being restored past `keep` and pruned it - so
    restoring the oldest copy destroyed it and then failed for its absence."""
    monkeypatch.setattr(config, "keep", lambda: 3)
    _people(agent, 2)
    oldest = backup.take()
    backup.take()
    backup.take()

    outcome = backup.restore(oldest.backup_id, accepted_by=KRISH,
                             confirmed=True)

    assert outcome["restored"] == oldest.backup_id
    assert oldest.path.exists(), "the backup being restored was deleted"


def test_the_restore_holds_no_connection_when_it_swaps_the_file(agent,
                                                                monkeypatch):
    """A posix-runnable proxy for the Windows constraint.

    Windows cannot replace a file any process has open, so a restore that
    still held a connection of its own would fail there and pass here - which
    is exactly what happened, and it took a seventeen-minute CI run to find.
    This asserts the property directly: at the moment of the swap, the restore
    is holding nothing."""
    import gc
    import sqlite3

    _people(agent, 2)
    taken = backup.take()

    def still_open():
        """Connections that are OPEN, not merely still referenced.

        `isinstance(o, sqlite3.Connection)` counts closed ones too - a closed
        connection is still an object - and a closed connection holds no file
        handle. The first version of this test counted those and failed
        against correct code, which would have sent me looking for a defect
        that was not there."""
        gc.collect()
        live_ones = 0
        for item in gc.get_objects():
            if not isinstance(item, sqlite3.Connection):
                continue
            try:
                item.total_changes
            except sqlite3.ProgrammingError:
                continue  # closed
            except Exception:  # noqa: BLE001 - open but unhappy still counts
                pass
            live_ones += 1
        return live_ones

    original_replace = backup.os.replace
    seen = {}

    def counting_replace(source, destination):
        seen["connections"] = still_open()
        return original_replace(source, destination)

    monkeypatch.setattr(backup.os, "replace", counting_replace)
    before = still_open()

    backup.restore(taken.backup_id, accepted_by=KRISH, confirmed=True)

    assert seen["connections"] <= before, (
        f"the restore held {seen['connections']} open connection(s) when it "
        f"replaced the file (was {before} before); on Windows that is an "
        f"access-denied failure")


def test_a_failed_open_does_not_leave_the_file_held(tmp_path):
    """WINDOWS CI FOUND THIS, and it is a defect in `backend/db.py` rather
    than in backup.

    `sqlite3.connect` succeeds on any file - it does not read it - so a
    corrupt one gets a live connection and then raises on the first PRAGMA.
    That connection used to stay open until the garbage collector happened to
    run. On posix a leaked descriptor; on Windows a held lock, which made a
    restore unable to replace the corrupt database it was recovering from.
    A recovery blocked by the damage it was recovering from."""
    import gc
    import sqlite3

    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"this is not a database at all")

    before = len([item for item in gc.get_objects()
                  if isinstance(item, sqlite3.Connection)])
    with pytest.raises(sqlite3.DatabaseError):
        Database(corrupt)
    after = len([item for item in gc.get_objects()
                 if isinstance(item, sqlite3.Connection)])

    assert after == before, "the failed open left a connection behind"


def test_a_restore_still_works_when_the_live_database_is_corrupt(agent):
    """It failed in exactly the situation a restore exists for: the mandatory
    safety backup raised an uncaught sqlite3 error on the damaged database, and
    neither the CLI nor the route caught it."""
    _people(agent, 2)
    taken = backup.take()

    live = store.database_path()
    for sidecar in ("-wal", "-shm"):
        Path(str(live) + sidecar).unlink(missing_ok=True)
    live.write_bytes(b"this is not a database at all")

    outcome = backup.restore(taken.backup_id, accepted_by=KRISH,
                             confirmed=True)

    assert outcome["restored"] == taken.backup_id
    assert outcome["previous_state_backed_up_as"] is None
    assert "raw byte copy" in outcome["previous_state_note"]
    connection = store.connect()
    try:
        assert records.count(connection, "person") == 2
    finally:
        connection.close()


def test_the_unrestorable_raw_copy_is_not_offered_as_a_backup(agent):
    """It is evidence, not a backup. Putting it in the catalogue would let
    something later treat it as one."""
    _people(agent, 1)
    taken = backup.take()
    live = store.database_path()
    for sidecar in ("-wal", "-shm"):
        Path(str(live) + sidecar).unlink(missing_ok=True)
    live.write_bytes(b"not a database")
    backup.restore(taken.backup_id, accepted_by=KRISH, confirmed=True)

    assert [item.backup_id for item in backup.catalogue()] == [taken.backup_id]
    rescued = list(Path(taken.path).parent.glob("UNRESTORABLE-*"))
    assert len(rescued) == 1


def test_a_write_during_the_copy_does_not_condemn_a_good_backup(agent,
                                                                monkeypatch):
    """The counts were read before the copy, so any write landing in between
    made the restored copy disagree with the manifest and a perfectly good
    backup was marked FAILED - `take` raising because somebody was working."""
    _people(agent, 2)
    original_backup_to = Database.backup_to

    def write_then_copy(self, path):
        agent.handle(contract.Request(
            action=contract.CREATE, requested_by=JARVIS,
            entity_type="person", data={"name": "Arrived mid-copy"}))
        return original_backup_to(self, path)

    monkeypatch.setattr(Database, "backup_to", write_then_copy)

    taken = backup.take()

    assert taken.verified, taken.verification
    # The manifest describes the SNAPSHOT, so it agrees with what a restore
    # produces. The write that arrived mid-copy is recorded as drift rather
    # than treated as a fault.
    assert taken.row_counts["entities"] == 3
    assert taken.verification["wrote_while_copying"]["entities"] == (2, 3)


def test_the_schedule_does_not_loop_when_backups_are_failing(agent,
                                                             monkeypatch):
    """`due` asked for the newest *verified* backup, so a newer unverified one
    was invisible: the schedule thought nothing had been taken and took
    another on every call - a failing backup becoming an unbounded series of
    them."""
    _people(agent, 1)
    monkeypatch.setattr(config, "verify_by_restoring", lambda: False)
    moment = datetime.now().astimezone().replace(
        hour=max(config.backup_hour(), 12), minute=0)

    first = backup.run_if_due(moment)
    second = backup.run_if_due(moment)
    third = backup.run_if_due(moment)

    assert first is not None
    assert second is None and third is None
    assert len(backup.catalogue()) == 1


def test_retention_counts_restorable_copies_not_entries(agent, monkeypatch):
    """`keep` counted every entry, so a run of failed backups pushed the good
    ones out and left one verified copy where the policy said three -
    retention deleting exactly what it exists to retain."""
    monkeypatch.setattr(config, "keep", lambda: 3)
    _people(agent, 1)
    verified = [backup.take() for _ in range(3)]

    monkeypatch.setattr(config, "verify_by_restoring", lambda: False)
    for _ in range(4):
        backup.take()

    remaining = {item.backup_id for item in backup.catalogue()
                 if item.verified}
    assert remaining == {item.backup_id for item in verified}, \
        "verified backups were pruned to make room for unverified ones"


def test_a_restore_that_fails_partway_leaves_the_database_untouched(
        agent, monkeypatch):
    """A failed restore must leave the database exactly as it was.

    This started as a test of ordering: the sidecars were unlinked *before*
    the swap, so a rename that failed would leave the live database missing
    every transaction still in the log. The order was changed to
    replace-then-unlink, which is strictly safer and costs nothing.

    HONESTLY: the hazard could not be reproduced. Closing the probe connection
    makes SQLite checkpoint the log into the main file, so by the time
    anything is unlinked the transactions are already safe - the test passes
    against both orderings even with the explicit checkpoint sabotaged. What
    is asserted here is the property that matters and can fail: a restore that
    dies partway through has not lost anything."""
    _people(agent, 2)
    taken = backup.take()
    agent.handle(contract.Request(
        action=contract.CREATE, requested_by=JARVIS, entity_type="person",
        data={"name": "Committed but still in the log"}))

    original_fetchone = Database.fetchone

    def no_checkpoint(self, sql, params=()):
        if "wal_checkpoint" in sql:
            raise RuntimeError("the checkpoint could not run")
        return original_fetchone(self, sql, params)

    def failing_rename(*args, **kwargs):
        raise OSError("the rename failed")

    monkeypatch.setattr(Database, "fetchone", no_checkpoint)
    monkeypatch.setattr(backup.os, "replace", failing_rename)
    with pytest.raises(OSError):
        backup.restore(taken.backup_id, accepted_by=KRISH, confirmed=True,
                       allow_unverified=True)

    connection = store.connect()
    try:
        assert connection.fetchall(
            "SELECT 1 FROM entities WHERE name = 'Committed but still in the log'"), \
            "a failed restore threw away a committed transaction"
    finally:
        connection.close()


# =============================================================================
# §32: the configuration is externalised, and validated
# =============================================================================


def test_the_shipped_configuration_is_valid():
    assert config.load()["backup"]["keep"] >= 1
    assert 0 <= config.backup_hour() <= 23
    assert config.describe()["exists"] is True


def test_a_configuration_that_cannot_be_read_is_refused_not_defaulted(
        tmp_path, monkeypatch):
    """A backup policy that is silently ignored is a backup policy that does
    not exist."""
    bad = tmp_path / "dba.yaml"
    bad.write_text("backup: [this is not a mapping\n", encoding="utf-8")
    monkeypatch.setenv(config.PATH_ENV, str(bad))
    config._CACHE.clear()

    with pytest.raises(config.DBAConfigError):
        config.load()


def test_a_section_that_is_not_a_mapping_is_refused(tmp_path, monkeypatch):
    """Silently replacing it with the defaults is exactly the behaviour this
    module promises not to have: the whole policy would run on values nobody
    chose, and look fine."""
    path = tmp_path / "dba.yaml"
    path.write_text("backup:\n  - keep: 99\n", encoding="utf-8")
    monkeypatch.setenv(config.PATH_ENV, str(path))
    config._CACHE.clear()

    with pytest.raises(config.DBAConfigError, match="must be a mapping"):
        config.load()


@pytest.mark.parametrize("section,expected", [
    ("keep: 0", "at least 1"),
    ("hour: 99", "must be 0-23"),
    ("verify_by_restoring: maybe", "true or false"),
    ("minimum_free_megabytes: -5", "must not be negative"),
])
def test_an_impossible_policy_is_refused_with_the_reason(tmp_path, monkeypatch,
                                                         section, expected):
    path = tmp_path / "dba.yaml"
    path.write_text(f"backup:\n  {section}\n", encoding="utf-8")
    monkeypatch.setenv(config.PATH_ENV, str(path))
    config._CACHE.clear()

    with pytest.raises(config.DBAConfigError, match=expected):
        config.load()


def test_no_secret_is_in_the_configuration_file():
    """§18: tokens are environment variables, because a credential in a
    committed file is a credential in the history for ever."""
    text = Path(config.DEFAULT_PATH).read_text(encoding="utf-8").lower()
    for word in ("token", "password", "secret", "api_key"):
        assert f"{word}:" not in text, word


# =============================================================================
# §26's documentation, and §28/§29's reporting
# =============================================================================


def test_the_documentation_answers_what_section_twenty_six_asks_for(agent):
    _people(agent)
    backup.take()
    described = backup.describe()

    assert described["how_to_restore"]
    assert described["current"]["backup_id"]
    assert described["recovery_point"]
    assert described["schema_version"] == store.SCHEMA_VERSION
    assert described["validation_procedure"]


def test_the_documentation_is_honest_about_what_is_missing(agent):
    missing = backup.describe()["not_implemented"]
    assert "encrypted_secondary_location" in missing
    assert "other_databases" in missing
    assert "financial_intelligence.db" in missing["other_databases"]


def test_health_reports_no_backup_as_a_failure_rather_than_silence(agent):
    _people(agent)
    assert health.health()["last_backup"] is None
    diagnosis = health.diagnose()
    assert "backup_age" in diagnosis["failing"]
    assert diagnosis["status"] == health.DEGRADED


def test_health_reports_a_real_backup_once_one_exists(agent):
    _people(agent)
    taken = backup.take()

    reported = health.health()["last_backup"]

    assert reported["backup_id"] == taken.backup_id
    assert reported["verified"] is True
    assert reported["recovery_point"] == taken.recovery_point
    assert health.diagnose()["failing"] == []


def test_backups_that_exist_but_are_unverified_do_not_count_as_healthy(
        agent, monkeypatch):
    _people(agent)
    monkeypatch.setattr(config, "verify_by_restoring", lambda: False)
    backup.take()

    diagnosis = health.diagnose()
    check = next(item for item in diagnosis["checks"]
                 if item["check"] == "backup_age")

    assert not check["passed"]
    assert "none verified" in check["detail"]


def test_a_stale_backup_is_reported_as_stale(agent, monkeypatch):
    _people(agent)
    taken = backup.take()
    old = (datetime.now(timezone.utc)
           - timedelta(days=health.STALE_BACKUP_DAYS + 1)).isoformat()
    manifest = json.loads(taken.manifest_path.read_text(encoding="utf-8"))
    manifest["taken_at"] = old
    taken.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    check = next(item for item in health.diagnose()["checks"]
                 if item["check"] == "backup_age")

    assert not check["passed"]
    assert "scheduled run has been missed" in check["detail"]


def test_the_command_a_scheduler_calls(agent, capsys):
    """Nothing here runs on a timer by itself. Pretending otherwise would be
    the worst kind of backup story - one everybody believes is running."""
    _people(agent, 1)

    assert backup.main(["--take"]) == 0
    assert "took" in capsys.readouterr().out

    assert backup.main(["--if-due"]) == 0
    assert "already exists" in capsys.readouterr().out

    taken = backup.catalogue()[0]
    assert backup.main(["--verify", taken.backup_id]) == 0
    assert backup.main(["--verify", "dba-19700101T000000Z-00000000"]) == 1


def test_the_command_refuses_a_restore_that_was_not_confirmed(agent, capsys):
    _people(agent, 1)
    backup.main(["--take"])
    capsys.readouterr()

    assert backup.main(["--restore", backup.catalogue()[0].backup_id]) == 1
    assert "refused" in capsys.readouterr().out


# =============================================================================
# Through the service
# =============================================================================


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from dba.main import app

    monkeypatch.setenv("DBA_TOKEN_JARVIS", "jarvis-token-not-real")
    monkeypatch.setenv("DBA_TOKEN_OPERATOR_CONSOLE", "krish-token-not-real")
    return TestClient(app)


AS_JARVIS = {"X-DBA-Agent": JARVIS, "X-DBA-Token": "jarvis-token-not-real"}
AS_KRISH = {"X-DBA-Agent": KRISH, "X-DBA-Token": "krish-token-not-real"}


def test_only_an_operator_may_operate_backups(client):
    assert client.get("/backups", headers=AS_JARVIS).status_code == 403
    assert client.post("/backups", headers=AS_JARVIS).status_code == 403
    assert client.get("/backups").status_code == 401


def test_the_whole_cycle_through_the_service(client, agent):
    _people(agent, 2)

    response = client.post("/backups", headers=AS_KRISH).json()
    assert response["status"] == "taken"
    taken = response["backup"]
    assert taken["status"] == backup.VERIFIED
    assert taken["verification"]["passed"]
    backup_id = taken["backup_id"]

    assert client.post(f"/backups/{backup_id}/verify",
                       headers=AS_KRISH).json()["passed"]

    catalogue = client.get("/backups", headers=AS_KRISH).json()
    assert catalogue["current"]["backup_id"] == backup_id
    assert catalogue["how_to_restore"]

    agent.handle(contract.Request(
        action=contract.CREATE, requested_by=JARVIS, entity_type="person",
        data={"name": "Lost on restore"}))

    unconfirmed = client.post(f"/backups/{backup_id}/restore", json={},
                              headers=AS_KRISH)
    assert unconfirmed.status_code == 409

    restored = client.post(f"/backups/{backup_id}/restore",
                           json={"confirmed": True}, headers=AS_KRISH).json()
    assert restored["status"] == "restored"
    assert restored["previous_state_backed_up_as"]

    connection = store.connect()
    try:
        assert records.count(connection, "person") == 2
    finally:
        connection.close()


def test_the_response_does_not_confuse_two_meanings_of_status(client, agent):
    """A Backup carries its own `status` - verified / unverified / failed -
    and spreading it into the response silently overwrote the response's own.
    Two meanings under one key is a field nobody can read correctly."""
    _people(agent, 1)
    body = client.post("/backups", headers=AS_KRISH).json()
    assert body["status"] == "taken"
    assert body["backup"]["status"] == backup.VERIFIED


def test_a_backup_operation_is_recorded_in_the_audit_trail(client, agent):
    from dba import audit

    _people(agent, 1)
    client.post("/backups", headers=AS_KRISH)

    connection = store.connect()
    try:
        actions = [event["action"] for event in audit.recent(connection)]
    finally:
        connection.close()
    assert "take_backup" in actions


def test_a_restore_is_audited_into_the_database_that_survives_it(client, agent):
    """Written after the operation and on a fresh connection: a restore
    replaces the database underneath anything opened before it, so an audit
    row written into the file about to be overwritten never happened."""
    from dba import audit

    _people(agent, 1)
    backup_id = client.post("/backups",
                            headers=AS_KRISH).json()["backup"]["backup_id"]
    client.post(f"/backups/{backup_id}/restore", json={"confirmed": True},
                headers=AS_KRISH)

    connection = store.connect()
    try:
        actions = [event["action"] for event in audit.recent(connection)]
    finally:
        connection.close()
    assert "restore_backup" in actions


def test_a_missing_backup_is_a_404(client):
    assert client.get("/backups/dba-19700101T000000Z-00000000",
                      headers=AS_KRISH).status_code == 404
