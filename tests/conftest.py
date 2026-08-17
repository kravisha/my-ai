"""Shared fixtures. Two things here must happen at import time, before any
test module is imported, and both are for the same structural reason: the code
under test reads its configuration once, at *its* import time, so a fixture is
already too late.

ANTHROPIC_API_KEY: app.model_gateway constructs the Anthropic client at import
time (`_client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])`) - without
this, merely importing app.main would crash in a clean environment with no
.env file. No real network call is ever made in these tests; call_reasoning_model
itself is always mocked out, so the key's value never matters, only its presence.

FI_DB_PATH: backend/main.py constructs `controller = Controller()` at module
level, and Controller.__init__ runs fi_db.init_schema against fi_db.DB_PATH. So
the mere act of `import backend.main` - which every FastAPI test does, most of
them indirectly through the backend_client/panel_client fixtures below - used to
execute DDL, additive migrations and static-metadata seeding against the
developer's real financial_intelligence.db. That is why overriding the panel_db
dependency alone never fixed the leak: the write had already happened by the
time any fixture ran. fi_db.DB_PATH is `Path(os.environ.get("FI_DB_PATH") or
<project root>/financial_intelligence.db)`, evaluated once when backend.fi_db is
first imported, so redirecting it here - above every import in this file - is
the only place that catches it.

The redirect is deliberately unconditional rather than a setdefault. A developer
with FI_DB_PATH already pointing at a real database is exactly the case the
redirect exists to defend against.

Between them, the redirect and the _isolate_fi_db autouse fixture close the leak
by construction, and _assert_real_database_untouched below proves it stayed
closed - see its docstring for why all three layers are worth having.
"""

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

# Resolved before the redirect below, since afterwards nothing in the process
# can still name the real database. Deliberately not fi_db.DB_PATH: this is the
# file on disk that must not change, independent of what any module thinks its
# database is.
REAL_DB_PATH = Path(__file__).resolve().parent.parent / "financial_intelligence.db"

# Session-wide stand-in for the real database, for every code path that resolves
# the default rather than being handed a path. One directory for the whole
# session, not per test: it exists to be harmless, not to isolate tests from
# each other - per-test isolation is what tmp_path fixtures are for.
_SESSION_DB_DIR = Path(tempfile.mkdtemp(prefix="my-ai-test-fi-db-"))
os.environ["FI_DB_PATH"] = str(_SESSION_DB_DIR / "financial_intelligence.db")


def real_database_fingerprint() -> dict[str, str | None]:
    """Content hash of the real database and its WAL sidecar, or None per file
    if absent.

    The sidecar is included because a leaked write need not reach the main file
    to be a leaked write: the database runs in WAL mode, so an uncheckpointed
    commit lands in financial_intelligence.db-wal and leaves the .db bytes
    identical. Hashing only the .db would miss precisely the fast, partial leak
    most likely to slip through. -shm is skipped - it is a scratch index into the
    WAL, and its bytes churn on plain reads."""
    fingerprint: dict[str, str | None] = {}
    for path in (REAL_DB_PATH, REAL_DB_PATH.with_name(REAL_DB_PATH.name + "-wal")):
        try:
            fingerprint[path.name] = hashlib.md5(path.read_bytes()).hexdigest()
        except FileNotFoundError:
            fingerprint[path.name] = None
    return fingerprint


# Taken at conftest import, which is the earliest moment the suite controls -
# earlier than pytest_sessionstart, and in particular earlier than the import of
# any test module, since a module-level `import backend.main` in one of those
# would already have written.
_REAL_DB_AT_START = real_database_fingerprint()

import pytest
from openpyxl import Workbook

from app import permissions as permissions_module
from app.audit import AuditLog
from app.permissions import PermissionManager
from app.privacy_preferences import PrivacyPreferenceStore
from app.session import SessionStore
from app.users import UserStore
from backend import fi_db

TEST_ACCOUNT_ID = "ACCT-TEST-99999"

TEST_ROWS = [
    ("AAPL", 10, 100.0, "2023-01-01", TEST_ACCOUNT_ID),
    ("MSFT", 5, 200.0, "2023-02-02", TEST_ACCOUNT_ID),
]


@pytest.fixture(autouse=True)
def _isolate_fi_db(tmp_path):
    """Points backend.main's panel_db dependency at a per-test database, for
    every test in the suite whether it asked or not.

    panel_db calls fi_db.get_connection() with no argument. The FI_DB_PATH
    redirect at the top of this file already means "no argument" can no longer
    resolve to the developer's real database, so this is not what keeps the real
    file safe - it is what keeps tests honest about their data. Without it, every
    route test that forgot an override would silently share one session-wide
    database, and would pass or fail depending on what the tests before it left
    behind.

    Autouse, and registered here rather than in the ten backend test modules that
    need it, because the failure mode being designed out is omission: a new route
    test that simply never thinks about the database is the case that reopened
    this hole before. Being autouse means there is nothing to remember.

    The schema is created lazily, on first resolution of the dependency, so the
    ~980 tests that never issue a panel request pay nothing for this. When a
    route does run, it gets a valid empty database - "no rows" is a far more
    legible failure for a new test than "no such table".

    panel_client overwrites this override with its own, which is the intended
    precedence: it needs the route and its panel_conn fixture to share one file."""
    import backend.main as backend_main

    db_path = tmp_path / "autouse-fi.db"
    initialized = False

    def _isolated_panel_db():
        nonlocal initialized
        connection = fi_db.get_connection(db_path)
        try:
            if not initialized:
                fi_db.init_schema(connection)
                initialized = True
            yield connection
        finally:
            connection.close()

    overrides = backend_main.app.dependency_overrides
    overrides[backend_main.panel_db] = _isolated_panel_db
    try:
        yield
    finally:
        # Tolerant of absence: panel_client clears the whole override dict in its
        # own teardown, which runs before this one.
        if overrides.get(backend_main.panel_db) is _isolated_panel_db:
            del overrides[backend_main.panel_db]


def _real_database_change() -> str | None:
    """A description of how the real database changed since session start, or
    None if it did not."""
    after = real_database_fingerprint()
    if after == _REAL_DB_AT_START:
        return None
    lines = []
    for name, before in _REAL_DB_AT_START.items():
        now = after[name]
        if before != now:
            lines.append(f"  {name}: {before or '<absent>'} -> {now or '<absent>'}")
    return "\n".join(lines)


_LEAK_MESSAGE = """\
Some code path in this run wrote to the developer's real database:

  {path}

{diff}

The usual cause is a FastAPI dependency, or a module-level object constructed at
import time, calling fi_db.get_connection() with no argument. Find it and give it
an explicit path. See tests/conftest.py for the two layers that are supposed to
make that impossible, and why each of them is not enough on its own."""


def _leak_report() -> str | None:
    diff = _real_database_change()
    if diff is None:
        return None
    return _LEAK_MESSAGE.format(diff=diff, path=REAL_DB_PATH)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Reports the leak. The check runs in two hooks rather than one because
    each can do only half the job: this one is guaranteed a place in the summary
    but cannot change the exit status, and pytest_sessionfinish below can change
    the exit status but has no guaranteed ordering against the terminal reporter,
    so anything it printed might land above the summary or be swallowed. Both
    re-derive the answer independently - hashing a few hundred KB twice is
    cheaper than depending on plugin hook order."""
    report = _leak_report()
    if report is not None:
        terminalreporter.section("REAL DATABASE MODIFIED", red=True, bold=True)
        terminalreporter.write_line(report)


def pytest_sessionfinish(session, exitstatus):
    """Fails the run if the real database changed, and only then cleans up.

    This is the layer that catches a leak through a dependency nobody thought
    about - which is the only kind that matters, since the ones we did think
    about are already handled above. A test could not do this job: the leak may
    happen in any test, or at import, and only a session-end hook sees all of
    them."""
    if _leak_report() is not None:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
    # ignore_errors because sqlite handles opened by module-level objects (see
    # backend.main's Controller) are still open here, and Windows will not delete
    # an open file. A few KB left in the system temp directory is not worth
    # failing a green run over.
    shutil.rmtree(_SESSION_DB_DIR, ignore_errors=True)


@pytest.fixture
def permissions_store(tmp_path):
    return PermissionManager(path=tmp_path / "permissions.json")


@pytest.fixture
def preferences_store(tmp_path):
    return PrivacyPreferenceStore(path=tmp_path / "privacy_preferences.json")


@pytest.fixture
def isolated_audit_log(tmp_path):
    return AuditLog(path=tmp_path / "audit_log.jsonl")


@pytest.fixture
def users_store(tmp_path):
    return UserStore(path=tmp_path / "users.json")


@pytest.fixture
def session_store(tmp_path):
    return SessionStore(path=tmp_path / "sessions.json")


@pytest.fixture
def backend_client(tmp_path, monkeypatch):
    """A FastAPI TestClient against backend.main.app with its module-level
    users/sessions singletons redirected to tmp_path, and per-user store
    construction (ensure_user_data_dir's default root) redirected too - the
    backend equivalent of permissions_store/preferences_store/users_store/
    session_store, bundled together since every backend route needs all of
    them wired consistently."""
    from fastapi.testclient import TestClient

    import backend.main as backend_main
    from app.users import ensure_user_data_dir as real_ensure_user_data_dir
    from backend.transcripts import TranscriptStore

    monkeypatch.setattr(backend_main, "users", UserStore(path=tmp_path / "users.json"))
    monkeypatch.setattr(backend_main, "sessions", SessionStore(path=tmp_path / "sessions.json"))
    monkeypatch.setattr(backend_main, "transcripts", TranscriptStore())
    monkeypatch.setattr(
        backend_main,
        "ensure_user_data_dir",
        lambda username: real_ensure_user_data_dir(username, root=tmp_path / "user_data"),
    )

    return TestClient(backend_main.app)


@pytest.fixture
def conn():
    """Shared by every FI test file (test_fi_db.py, test_coo.py,
    test_explorer.py, test_speculator.py, test_analysis.py) - previously
    duplicated identically five times, consolidated here as part of the
    Pre-Alpha persistence-abstraction work."""
    connection = fi_db.get_connection(":memory:")
    fi_db.init_schema(connection)
    yield connection
    connection.close()


@pytest.fixture
def panel_conn(tmp_path):
    """File-backed rather than in-memory, unlike `conn`.

    The control-panel routes run in FastAPI's worker threadpool, and sqlite3
    connections are bound to the thread that opened them. Handing a test's own
    connection to a route therefore raises ProgrammingError - so the panel
    tests give the route a *path* and let it open its own connection, exactly
    as production does. An in-memory database cannot be shared that way, since
    a second connection to ":memory:" gets a different, empty database."""
    connection = fi_db.get_connection(tmp_path / "panel.db")
    fi_db.init_schema(connection)
    yield connection
    connection.close()


@pytest.fixture
def panel_client(panel_conn, tmp_path):
    """TestClient for the Controller control-panel routes, with panel_db
    overridden onto *this test's* panel.db - the same file panel_conn holds open.

    That shared file is now the whole reason for the override. It used to be
    stated as protection against panel_db's argument-less get_connection()
    reaching the developer's real financial_intelligence.db; that protection has
    moved to the FI_DB_PATH redirect and the _isolate_fi_db autouse fixture
    above, which cover every route rather than only these. What remains here is
    the part those two cannot do: _isolate_fi_db hands out a database of its own,
    and a panel test that arranged its rows through panel_conn would find the
    route querying a different, empty file.

    Opening per request mirrors production rather than approximating it, which
    means these tests also exercise the WAL cross-connection visibility the
    panel depends on."""
    from fastapi.testclient import TestClient

    import backend.main as backend_main

    def _panel_db():
        connection = fi_db.get_connection(tmp_path / "panel.db")
        try:
            yield connection
        finally:
            connection.close()

    backend_main.app.dependency_overrides[backend_main.panel_db] = _panel_db
    # Stand in for an authenticated superuser. The gate itself is tested
    # directly in tests/test_admin_auth.py against an un-overridden client -
    # overriding it here would otherwise mean no test ever exercised the real
    # thing, which is the classic way an auth check rots unnoticed.
    backend_main.app.dependency_overrides[backend_main.require_admin] = lambda: "test-admin"
    try:
        yield TestClient(backend_main.app)
    finally:
        backend_main.app.dependency_overrides.clear()


@pytest.fixture
def mock_portfolio_path(tmp_path, monkeypatch):
    """Writes a small real .xlsx with known rows and redirects
    permissions.RESOURCE_PATHS["portfolio"] to it, so tools/portfolio.py
    reads test data instead of the real data/portfolio.xlsx."""
    path = tmp_path / "portfolio.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["Ticker", "Shares", "Purchase Price", "Purchase Date", "Account ID"])
    for row in TEST_ROWS:
        ws.append(list(row))
    wb.save(path)

    monkeypatch.setitem(permissions_module.RESOURCE_PATHS, "portfolio", path)
    return path
