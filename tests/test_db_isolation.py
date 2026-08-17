"""Tests for the test suite's own database isolation.

Everything here checks machinery in tests/conftest.py rather than product code,
which is unusual enough to justify. The regression guard there is a
pytest_sessionfinish hook, and a hook that has quietly stopped working looks
exactly like a hook that has nothing to report - a green run either way. So the
guard's own moving parts get tested like anything else: the fingerprint must
actually notice a changed file, and the two isolation layers must actually be in
place. If someone removes either layer, one of these fails immediately and
names what was removed, instead of the leak reappearing and being discovered
months later by hashing the file by hand.
"""

import hashlib
import shutil
from pathlib import Path

import conftest

from backend import fi_db


def test_the_default_database_path_is_not_the_real_one():
    """The FI_DB_PATH redirect, checked at the level that matters: whatever
    fi_db resolves when handed no path must not be the developer's file."""
    assert conftest.REAL_DB_PATH.name == "financial_intelligence.db", (
        "REAL_DB_PATH no longer names the project database; the guard is watching "
        "the wrong file"
    )
    assert fi_db.DB_PATH != conftest.REAL_DB_PATH


def test_a_no_argument_connection_does_not_open_the_real_database():
    """get_connection() with no argument is the exact call every leak so far has
    gone through, so it is worth asserting against directly rather than only
    through DB_PATH.

    Asks sqlite which file it actually opened rather than trusting a module
    constant, since the constant is the thing under suspicion."""
    connection = fi_db.get_connection()
    try:
        opened = Path(connection.fetchone("PRAGMA database_list")["file"])
    finally:
        connection.close()

    assert opened != conftest.REAL_DB_PATH


def test_the_module_level_controller_is_not_on_the_real_database():
    """backend.main builds a Controller at import time, and Controller.__init__
    runs init_schema. This is the write that used to land on the real database
    before any fixture could intervene."""
    import backend.main as backend_main

    assert backend_main.controller.db_path != str(conftest.REAL_DB_PATH)


def test_panel_db_is_overridden_for_every_test(tmp_path):
    """The autouse layer. This test asked for no database fixture at all, which
    is the point - a new route test that forgets is still covered."""
    import backend.main as backend_main

    assert backend_main.panel_db in backend_main.app.dependency_overrides


def test_an_unprepared_client_reads_an_empty_temp_database(backend_client):
    """What a route test that forgot about the database now sees: a working,
    empty database rather than the developer's populated one. Uses
    backend_client, which overrides no database dependency of its own."""
    import backend.main as backend_main

    backend_main.app.dependency_overrides[backend_main.require_admin] = lambda: "test-admin"
    try:
        response = backend_client.get("/admin/agents")
    finally:
        del backend_main.app.dependency_overrides[backend_main.require_admin]

    assert response.status_code == 200
    assert response.json()["agents"] == []


def test_the_fingerprint_notices_a_modified_database(tmp_path, monkeypatch):
    """The guard's detection logic, exercised against a stand-in copy.

    Pointed at a temp file rather than the real one, because a test that proved
    the guard works by writing to the real database would be the very thing the
    guard exists to catch."""
    stand_in = tmp_path / "financial_intelligence.db"
    connection = fi_db.get_connection(stand_in)
    fi_db.init_schema(connection)
    connection.close()
    monkeypatch.setattr(conftest, "REAL_DB_PATH", stand_in)

    before = conftest.real_database_fingerprint()
    assert before["financial_intelligence.db"] == hashlib.md5(stand_in.read_bytes()).hexdigest()

    connection = fi_db.get_connection(stand_in)
    try:
        fi_db.register_agent(connection, "explorer-1", "explorer", 4242)
    finally:
        connection.close()

    assert conftest.real_database_fingerprint() != before


def test_the_fingerprint_notices_a_write_that_only_reached_the_wal(tmp_path, monkeypatch):
    """The partial case the .db hash alone would miss: an uncheckpointed commit
    that lands entirely in the WAL sidecar."""
    stand_in = tmp_path / "financial_intelligence.db"
    connection = fi_db.get_connection(stand_in)
    fi_db.init_schema(connection)
    connection.close()

    wal = tmp_path / "financial_intelligence.db-wal"
    shutil.copyfile(stand_in, wal)  # any nonempty sidecar content will do
    monkeypatch.setattr(conftest, "REAL_DB_PATH", stand_in)
    with_sidecar = conftest.real_database_fingerprint()

    wal.unlink()
    without_sidecar = conftest.real_database_fingerprint()

    assert without_sidecar["financial_intelligence.db-wal"] is None
    assert with_sidecar != without_sidecar
    assert with_sidecar["financial_intelligence.db"] == without_sidecar["financial_intelligence.db"], (
        "the .db bytes are identical in both cases - which is exactly why the "
        "sidecar has to be hashed too"
    )


def test_the_guard_reports_nothing_when_the_database_is_untouched():
    """The other half of detection, and the half a broken guard would still
    pass. Worth stating anyway: a guard that reported a leak unconditionally
    would fail every run and be deleted rather than believed."""
    assert conftest._real_database_change() is None
