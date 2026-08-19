"""Atomic report claiming, and the additive-column migration it needed.

Both exist because of one measurement: a judgment cycle spends ~19.5s inside a
model call, and nothing marked the report as taken during that window. With
exactly one judgment agent that is invisible. It is the first thing that breaks
when capacity is added, which is the fix R1 actually calls for.

The migration is here because adding `claimed_at` exposed that this project had
no way to add a column to a database that already existed - `CREATE TABLE IF NOT
EXISTS` silently does nothing, so the column reaches fresh databases only.
"""

from datetime import datetime, timedelta, timezone

import pytest

from backend import fi_db


@pytest.fixture
def db(conn):
    fi_db.init_schema(conn)
    return conn


def file_report(conn, security: str, producer: str = "speculator-1") -> int:
    return fi_db.enqueue_report(
        conn, producer_identity=producer, producer_spawned_at="2026-08-17T00:00:00+00:00",
        report_type="social", security=security, summary="generated",
    )


# -- the claim ----------------------------------------------------------------

def test_claiming_removes_a_report_from_the_queue(db):
    file_report(db, "SYN1")
    claimed = fi_db.claim_next_report(db, "analysis-1", "spawn-1")

    assert claimed is not None
    assert fi_db.prioritised_pending_reports(db) == []


def test_two_agents_cannot_claim_the_same_report(db):
    """The race the whole change exists for.

    Before claiming, both agents read the same top-ranked report and both spent
    twenty seconds analysing it."""
    file_report(db, "SYN1")

    first = fi_db.claim_next_report(db, "analysis-1", "spawn-1")
    second = fi_db.claim_next_report(db, "analysis-2", "spawn-2")

    assert first is not None
    assert second is None, "a second agent claimed a report that was already taken"


def test_a_second_agent_takes_the_next_report_rather_than_idling(db):
    """Losing a claim must not stop an agent working - it moves down the queue."""
    file_report(db, "SYN1")
    file_report(db, "SYN2")

    first = fi_db.claim_next_report(db, "analysis-1", "spawn-1")
    second = fi_db.claim_next_report(db, "analysis-2", "spawn-2")

    assert {first["id"], second["id"]} == {1, 2}


def test_claiming_an_empty_queue_returns_none(db):
    assert fi_db.claim_next_report(db, "analysis-1", "spawn-1") is None


def test_a_claimed_report_records_who_took_it_and_when(db):
    file_report(db, "SYN1")
    fi_db.claim_next_report(db, "analysis-1", "spawn-1")

    row = db.fetchone("SELECT status, claimed_at, handled_by_identity FROM discovery_reports")
    assert row["status"] == "in_progress"
    assert row["handled_by_identity"] == "analysis-1"
    assert row["claimed_at"] is not None


def test_a_claimed_report_still_blocks_a_new_one_for_that_security(db):
    """In-progress is not free.

    If the guard ignored claimed reports, a security would accumulate a fresh
    report every cycle while the first was being analysed."""
    file_report(db, "SYN1")
    fi_db.claim_next_report(db, "analysis-1", "spawn-1")

    assert fi_db.has_pending_report(db, "speculator-1", "SYN1") is True


def test_claiming_preserves_the_triage_order(db):
    """The claim must not quietly become first-in-first-out."""
    file_report(db, "SYN1")
    file_report(db, "SYN2")
    expected = fi_db.prioritised_pending_reports(db)[0]["id"]

    assert fi_db.claim_next_report(db, "analysis-1", "spawn-1")["id"] == expected


# -- abandoned claims ---------------------------------------------------------

def age_claim(conn, report_id: int, seconds: float):
    stale = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    conn.execute("UPDATE discovery_reports SET claimed_at = ? WHERE id = ?", (stale, report_id))


def test_an_abandoned_claim_returns_to_the_queue(db):
    """Claiming introduces a way to lose work that did not exist before.

    An agent that dies mid-analysis would otherwise hold its report forever, and
    because the guard still counts it, that security goes permanently silent."""
    report_id = file_report(db, "SYN1")
    fi_db.claim_next_report(db, "analysis-1", "spawn-1")
    age_claim(db, report_id, fi_db.CLAIM_TIMEOUT_SECONDS + 60)

    assert fi_db.release_stale_claims(db) == 1
    assert len(fi_db.prioritised_pending_reports(db)) == 1


def test_a_claim_still_within_the_timeout_is_left_alone(db):
    """Stealing a working agent's report reintroduces the duplication the claim prevents."""
    report_id = file_report(db, "SYN1")
    fi_db.claim_next_report(db, "analysis-1", "spawn-1")
    age_claim(db, report_id, fi_db.CLAIM_TIMEOUT_SECONDS / 2)

    assert fi_db.release_stale_claims(db) == 0
    assert fi_db.prioritised_pending_reports(db) == []


def test_the_claim_timeout_exceeds_a_realistic_judgment_cycle(db):
    """Measured, not guessed.

    A judgment cycle is ~19.5s of model call with one observed outlier at 42s.
    A timeout below that steals reports from agents that are working normally -
    which is how three timing constants in this project were wrong."""
    assert fi_db.CLAIM_TIMEOUT_SECONDS > 42 * 2


def test_a_released_report_can_be_claimed_by_another_agent(db):
    report_id = file_report(db, "SYN1")
    fi_db.claim_next_report(db, "analysis-1", "spawn-1")
    age_claim(db, report_id, fi_db.CLAIM_TIMEOUT_SECONDS + 60)
    fi_db.release_stale_claims(db)

    assert fi_db.claim_next_report(db, "analysis-2", "spawn-2") is not None


# -- additive migrations ------------------------------------------------------

def test_a_column_missing_from_an_existing_database_is_added(db):
    """Regression for a silent gap under every future schema change.

    `CREATE TABLE IF NOT EXISTS` does nothing when the table exists, so a column
    added to SCHEMA reaches fresh databases only. Everything passes on a fresh
    database and fails with 'no such column' against a real one."""
    db.execute("ALTER TABLE discovery_reports DROP COLUMN claimed_at")
    assert "claimed_at" not in _columns(db, "discovery_reports")

    applied = fi_db.apply_additive_migrations(db)

    assert "discovery_reports.claimed_at" in applied
    assert "claimed_at" in _columns(db, "discovery_reports")


def test_migration_is_idempotent(db):
    assert fi_db.apply_additive_migrations(db) == []


def test_migration_preserves_existing_rows(db):
    file_report(db, "SYN1")
    db.execute("ALTER TABLE discovery_reports DROP COLUMN claimed_at")

    fi_db.apply_additive_migrations(db)

    assert db.fetchone("SELECT COUNT(*) AS n FROM discovery_reports")["n"] == 1


def test_table_constraints_are_not_mistaken_for_columns():
    """`UNIQUE(name, version)` has no space after the keyword, so the first token
    is `UNIQUE(name,` - an equality check let it through and produced a syntax
    error at migration time."""
    declared = fi_db._declared_columns((fi_db.SCHEMA,))
    for table, columns in declared.items():
        for name, _ in columns:
            assert not name.upper().startswith(fi_db._TABLE_CONSTRAINTS), (
                f"{table} has a constraint parsed as a column: {name!r}"
            )


def test_every_declared_table_is_parsed():
    declared = fi_db._declared_columns((fi_db.SCHEMA,))
    assert set(declared) == set(fi_db.list_tables_in_schema())
    assert all(columns for columns in declared.values())


def _columns(conn, table: str) -> set[str]:
    return {row["name"] for row in conn.fetchall(f"PRAGMA table_info({table})")}


# -- trigger drift ------------------------------------------------------------

def _trigger_sql(db, name):
    row = db.fetchone("SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?", (name,))
    return row["sql"] if row else None


def test_a_stale_trigger_is_replaced(db):
    """The same trap as the column case, and it hides better.

    `CREATE TRIGGER IF NOT EXISTS` silently keeps the old definition when the
    trigger exists, and unlike a missing column there is no PRAGMA that reveals
    it and no query that fails - the outdated trigger just keeps running.

    Measured before the fix was written: with the archive trigger still on its
    two-outcome version, a directive completed as 'objected' was never archived
    and stayed in the pending queue, so an executor would re-process it every
    cycle forever."""
    db.execute("DROP TRIGGER coo_directives_archive")
    db.execute(
        "CREATE TRIGGER coo_directives_archive AFTER UPDATE OF status ON coo_directives "
        "WHEN NEW.status IN ('success', 'failure') BEGIN "
        "DELETE FROM coo_directives WHERE id = NEW.id; END"
    )
    assert "objected" not in _trigger_sql(db, "coo_directives_archive")

    applied = fi_db.apply_additive_migrations(db)

    assert "trigger coo_directives_archive" in applied
    assert "objected" in _trigger_sql(db, "coo_directives_archive")


def test_an_unchanged_trigger_is_left_alone(db):
    """Comparison is by content, not by formatting - SQLite stores the text as
    written, so whitespace differences would read as drift on every startup and
    the trigger would be dropped and rebuilt forever."""
    before = _trigger_sql(db, "coo_directives_archive")
    assert fi_db.apply_additive_migrations(db) == []
    assert _trigger_sql(db, "coo_directives_archive") == before


def test_a_replaced_trigger_actually_archives_the_new_outcome(db):
    """The behavioural half. A trigger whose text was updated but which does not
    fire would pass the comparison above and fail in production."""
    db.execute("DROP TRIGGER coo_directives_archive")
    db.execute(
        "CREATE TRIGGER coo_directives_archive AFTER UPDATE OF status ON coo_directives "
        "WHEN NEW.status IN ('success', 'failure') BEGIN "
        "DELETE FROM coo_directives WHERE id = NEW.id; END"
    )
    fi_db.apply_additive_migrations(db)

    directive_id = fi_db.enqueue_directive(
        db, directive_type="retire", requested_by="coo-1", target_identity="explorer-404",
    )
    fi_db.file_objection(
        db, directive_id, filed_by="controller-1", ground="missing dependency",
        evidence="no such agent", remedy="spawn it first",
    )

    assert fi_db.fetch_next_pending_directive(db) is None, "objected directive stayed in the queue"
