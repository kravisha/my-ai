"""What SQLite's single writer does under a real agent population
(simulation/contention.py; ARCHITECTURE_READINESS_REVIEW.md N2, R3; directive §19).

Marked `simulation` because it spawns real subprocesses, so it is excluded from
the default run like every other test that does.

Two things are being held here, and the second is what makes the first mean
anything:

1. Under contention nothing is lost and nothing is duplicated. Every attempted
   write either lands or raises, and no write lands twice.
2. **The instrument can see contention at all.** A harness that reports zero
   because it cannot detect the condition reports the same zero as one that
   genuinely found none, and this project has now found six checks that passed
   for that reason (§149). So one case forces the condition and asserts it is
   observed.
"""

import pytest

from simulation import contention

pytestmark = pytest.mark.simulation


def test_no_write_is_lost_or_duplicated_under_concurrent_writers(tmp_path):
    """Eight writers is today's agent population. The invariants hold trivially
    here, which is the point - this is the baseline the forced case is read
    against."""
    result = contention.measure(tmp_path / "c.db", writers=8, writes=200)

    assert result["unaccounted"] == 0, (
        "a write neither landed nor reported failing, which is the only genuinely "
        "alarming outcome this measures")
    assert result["duplicates"] == 0
    assert result["rows_in_table"] == result["reported_landed"]


def test_contention_is_observable_when_it_is_forced(tmp_path, monkeypatch):
    """The instrument check.

    `FI_DB_BUSY_TIMEOUT_MS=0` removes the wait, so writers that lose the race
    fail immediately instead of queueing. If this does not produce contention,
    the zero the sweep reports at the operating timeout says nothing about
    whether contention would be noticed."""
    monkeypatch.setenv("FI_DB_BUSY_TIMEOUT_MS", "0")

    result = contention.measure(tmp_path / "c.db", writers=12, writes=200)

    assert result["contended"] > 0, (
        "no contention was observed even with the wait removed, so this harness "
        "cannot detect the condition it exists to measure")
    # And the invariants still hold while it is happening, which is the property
    # that matters: a contended write is refused, not silently dropped.
    assert result["unaccounted"] == 0
    assert result["duplicates"] == 0
    assert result["rows_in_table"] == result["reported_landed"]


def test_a_lock_failure_is_raised_under_its_own_name(tmp_path, monkeypatch):
    """`Contended` rather than a bare OperationalError.

    Reaching an agent, a generic OperationalError is indistinguishable from that
    agent being broken - so contention at scale would present as several
    unrelated agents becoming unreliable at once. The name is what lets the two
    be counted apart (§93's argument, one subsystem along)."""
    import sqlite3

    from backend.db import Contended, Database

    monkeypatch.setenv("FI_DB_BUSY_TIMEOUT_MS", "0")
    path = tmp_path / "c.db"
    holder = Database(path)
    holder.executescript(contention.SCHEMA)

    blocked = Database(path)
    # An exclusive write held open by another connection is what a losing writer
    # actually meets.
    holder._conn.execute("BEGIN IMMEDIATE")
    holder._conn.execute(
        f"INSERT INTO {contention.TABLE} (writer, sequence, written_at) VALUES (0, 0, 'now')")
    try:
        with pytest.raises(Contended):
            blocked.execute(
                f"INSERT INTO {contention.TABLE} (writer, sequence, written_at) "
                "VALUES (1, 1, 'now')")
        assert issubclass(Contended, sqlite3.OperationalError), (
            "every existing caller handles OperationalError; Contended must not "
            "escape those handlers")
    finally:
        holder._conn.rollback()
        blocked.close()
        holder.close()
