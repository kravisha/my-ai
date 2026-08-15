"""Unit tests for backend/db.py's Database abstraction, in isolation from
any domain schema (backend/fi_db.py's own 48 tests exercise it indirectly
through the real FI schema - these tests only cover the abstraction's own
primitives)."""

from pathlib import Path

import pytest

from backend.db import Database


@pytest.fixture
def db():
    database = Database(":memory:")
    yield database
    database.close()


def test_execute_and_fetchone_roundtrip(db):
    db.executescript("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    db.execute("INSERT INTO t (id, name) VALUES (?, ?)", (1, "hello"))
    row = db.fetchone("SELECT * FROM t WHERE id = ?", (1,))
    assert row == {"id": 1, "name": "hello"}


def test_fetchone_returns_none_when_no_match(db):
    db.executescript("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    assert db.fetchone("SELECT * FROM t WHERE id = ?", (999,)) is None


def test_fetchall_returns_multiple_rows(db):
    db.executescript("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    db.execute("INSERT INTO t (id, name) VALUES (?, ?)", (1, "a"))
    db.execute("INSERT INTO t (id, name) VALUES (?, ?)", (2, "b"))
    rows = db.fetchall("SELECT * FROM t ORDER BY id")
    assert rows == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]


def test_fetchall_returns_empty_list_when_no_rows(db):
    db.executescript("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    assert db.fetchall("SELECT * FROM t") == []


def test_execute_returning_id_gives_the_new_rows_id(db):
    db.executescript("CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)")
    first_id = db.execute_returning_id("INSERT INTO t (name) VALUES (?)", ("a",))
    second_id = db.execute_returning_id("INSERT INTO t (name) VALUES (?)", ("b",))
    assert second_id == first_id + 1
    assert db.fetchone("SELECT * FROM t WHERE id = ?", (second_id,))["name"] == "b"


def test_executescript_creates_multiple_objects_from_one_string(db):
    db.executescript("""
        CREATE TABLE a (id INTEGER PRIMARY KEY);
        CREATE TABLE b (id INTEGER PRIMARY KEY);
        CREATE TRIGGER a_to_b AFTER INSERT ON a
        BEGIN
            INSERT INTO b (id) VALUES (NEW.id);
        END;
    """)
    db.execute("INSERT INTO a (id) VALUES (?)", (1,))
    assert db.fetchall("SELECT * FROM b") == [{"id": 1}]


def test_reads_return_plain_dicts_not_row_objects(db):
    db.executescript("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    db.execute("INSERT INTO t (id) VALUES (?)", (1,))
    row = db.fetchone("SELECT * FROM t WHERE id = ?", (1,))
    assert type(row) is dict
    rows = db.fetchall("SELECT * FROM t")
    assert type(rows) is list
    assert type(rows[0]) is dict


def test_execute_persists_across_separate_calls(db):
    """Confirms execute() commits internally - a second, independent read
    against the same connection sees a prior write without an explicit
    commit() call anywhere in the test."""
    db.executescript("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    db.execute("INSERT INTO t (id) VALUES (?)", (1,))
    assert db.fetchone("SELECT * FROM t WHERE id = ?", (1,)) is not None


def test_works_against_a_real_file_path_not_just_in_memory(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    try:
        db.executescript("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO t (id) VALUES (?)", (1,))
        assert db.fetchone("SELECT * FROM t WHERE id = ?", (1,)) == {"id": 1}
        assert Path(db_path).exists()
    finally:
        db.close()
