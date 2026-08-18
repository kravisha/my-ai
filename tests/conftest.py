"""Shared fixtures. Two things here must happen at import time, before any
test module is imported, and both are for the same structural reason: the code
under test reads its configuration once, at *its* import time, so a fixture is
already too late.

FI_DB_PATH: fi_db.DB_PATH is `Path(os.environ.get("FI_DB_PATH") or <project
root>/financial_intelligence.db)`, evaluated once when backend.fi_db is first
imported. Redirecting it here - above every import in this file - is therefore
the only point at which the suite can decide what "the default database" means
for the process; by the time the first fixture runs, every module that cared has
already read it.

GATEWAY_DB_PATH: the same statement about gateway.store.DB_PATH, redirected for
the same reason and defended by the same session guard below. The Gateway is a
second service with a second database (see gateway/store.py for why it is
separate), so it is a second file the suite must not write to.

What made that decisive: backend/main.py used to construct `controller =
Controller()` at module level, and Controller.__init__ runs fi_db.init_schema, so
`import backend.main` executed DDL, additive migrations and static-metadata
seeding against the developer's real financial_intelligence.db. That is why
overriding the panel_db dependency never fixed the leak - the write had already
happened by the time any fixture ran. The Controller now belongs to lifespan
(see backend/main.py), so importing the module writes nothing, and
tests/test_db_isolation.py holds that line in a subprocess.

The redirect stays regardless, because it is not aimed at that one bug. It is
aimed at the class: any code that resolves the default rather than being handed a
path. One import-time constructor already did it once, and the redirect is what
makes the next one harmless rather than discovered by hashing the file by hand.

It is deliberately unconditional rather than a setdefault. A developer with
FI_DB_PATH already pointing at a real database is exactly the case it defends
against.

Between them the redirect and the _isolate_fi_db autouse fixture close the leak
by construction; pytest_sessionfinish below proves it stayed closed - see its
docstring for why all three layers are worth having.
"""

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

# Resolved before the redirect below, since afterwards nothing in the process
# can still name the real databases. Deliberately not fi_db.DB_PATH or
# store.DB_PATH: these are the files on disk that must not change, independent of
# what any module thinks its database is.
REAL_DB_PATH = Path(__file__).resolve().parent.parent / "financial_intelligence.db"
REAL_GATEWAY_DB_PATH = Path(__file__).resolve().parent.parent / "gateway.db"

# Session-wide stand-in for the real databases, for every code path that resolves
# the default rather than being handed a path. One directory for the whole
# session, not per test: it exists to be harmless, not to isolate tests from
# each other - per-test isolation is what tmp_path fixtures are for.
_SESSION_DB_DIR = Path(tempfile.mkdtemp(prefix="my-ai-test-fi-db-"))
os.environ["FI_DB_PATH"] = str(_SESSION_DB_DIR / "financial_intelligence.db")
os.environ["GATEWAY_DB_PATH"] = str(_SESSION_DB_DIR / "gateway.db")


def real_database_fingerprint() -> dict[str, str | None]:
    """Content hash of each real database and its WAL sidecar, or None per file
    if absent.

    The sidecar is included because a leaked write need not reach the main file
    to be a leaked write: the databases run in WAL mode, so an uncheckpointed
    commit lands in financial_intelligence.db-wal and leaves the .db bytes
    identical. Hashing only the .db would miss precisely the fast, partial leak
    most likely to slip through. -shm is skipped - it is a scratch index into the
    WAL, and its bytes churn on plain reads.

    Both databases are watched by one function so that adding a third service
    means adding a path, not a second guard that somebody forgets to call. The
    module globals are read on every call rather than captured in a constant,
    which is what lets tests/test_db_isolation.py point the guard at a stand-in
    and prove it still detects a change."""
    fingerprint: dict[str, str | None] = {}
    for database in (REAL_DB_PATH, REAL_GATEWAY_DB_PATH):
        for path in (database, database.with_name(database.name + "-wal")):
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

import bcrypt
import pytest
from openpyxl import Workbook

from app import permissions as permissions_module
from app.audit import AuditLog
from app.permissions import PermissionManager
from app.privacy_preferences import PrivacyPreferenceStore
from app.session import SessionStore
from app.users import UserStore
from backend import fi_db
from gateway import store as gateway_store

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
One of the developer's real databases changed during this run:

  {paths}

{diff}

Two very different things cause this, and the check cannot tell them apart -
it sees a changed file, not who changed it. Rule out (1) before hunting (2):
it is not a defect at all, and it costs one command to check.

1. Something outside the suite is writing to it. A running backend
   (`uvicorn backend.main:app`) heartbeats into this file about once a second,
   and so does any agent process left over from an earlier run. If you have the
   stack up, stop it and re-run before reading any further.

2. A leak from the suite: a FastAPI dependency, or an object constructed at
   import time, calling fi_db.get_connection() or gateway.store.get_connection()
   with no argument. Find it and give it an explicit path. See tests/conftest.py
   for the two layers that are meant to make that impossible, and why neither is
   enough on its own."""

# Sentinel rather than None, since None is a real answer here - it means checked
# and clean.
_UNCHECKED = object()
_leak_report_cached: str | None | object = _UNCHECKED


def _leak_report() -> str | None:
    """The leak report for this session, computed once.

    Cached because both hooks below ask, and they ask at slightly different
    moments. Hashing twice would let the two answers disagree whenever anything
    outside the suite is writing to the file - a heartbeat landing between the
    two calls would print a report and exit 0, or exit 1 with nothing printed to
    explain it. One answer per session, whichever hook gets there first."""
    global _leak_report_cached
    if _leak_report_cached is _UNCHECKED:
        diff = _real_database_change()
        _leak_report_cached = None if diff is None else _LEAK_MESSAGE.format(
            diff=diff, paths="\n  ".join(str(p) for p in (REAL_DB_PATH, REAL_GATEWAY_DB_PATH))
        )
    return _leak_report_cached


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Prints the leak report. Split from pytest_sessionfinish because each hook
    can do only half the job: this one is guaranteed a place in the summary but
    cannot change the exit status, and sessionfinish can change the exit status
    but has no guaranteed ordering against the terminal reporter, so anything it
    printed might land above the summary or be swallowed. They share one cached
    answer, so which of them runs first changes nothing but the timing."""
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
    # ignore_errors rather than a guarantee that nothing holds these files: any
    # connection a test opened against the default path lives here, and Windows
    # will not delete an open file. A few KB left in the system temp directory is
    # not worth failing an otherwise green run over.
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


# The Gateway's Super User credential for tests. Hashed once at conftest import
# rather than per test: bcrypt is deliberately slow (~100ms a hash at the default
# cost), which is the point of using it and a waste of a second across a suite
# that logs in dozens of times with the same password.
GATEWAY_TEST_USER = "test-super-user"
GATEWAY_TEST_PASSWORD = "correct-horse-battery-staple"
GATEWAY_TEST_PASSWORD_HASH = bcrypt.hashpw(
    GATEWAY_TEST_PASSWORD.encode("utf-8"), bcrypt.gensalt()
).decode("ascii")


@pytest.fixture
def gateway_conn(tmp_path):
    """File-backed, like panel_conn and for the same reason: the Gateway's routes
    open their own connection through a dependency, so a test that wants to see
    what a route wrote has to share a file with it rather than a connection."""
    connection = gateway_store.get_connection(tmp_path / "gateway.db")
    gateway_store.init_schema(connection)
    yield connection
    connection.close()


@pytest.fixture
def gateway_client(tmp_path, monkeypatch, gateway_conn):
    """TestClient for the Gateway, with a configured Super User and its database
    pointed at this test's file - the same one gateway_conn holds open.

    Deliberately not a context manager: `with TestClient(...)` runs the app's
    lifespan, which opens the *default* database to create its schema. Nothing in
    these tests needs lifespan, and the routes take their connection from the
    overridden dependency, so leaving it unentered keeps the suite off that path
    entirely."""
    from fastapi.testclient import TestClient

    import gateway.main as gateway_main
    from gateway import auth as gateway_auth

    monkeypatch.setenv(gateway_auth.SUPER_USER_ENV, GATEWAY_TEST_USER)
    monkeypatch.setenv(gateway_auth.PASSWORD_HASH_ENV, GATEWAY_TEST_PASSWORD_HASH)

    # Only the path is overridden. gateway_db builds its connection from it, and
    # a turn's tool calls open their own from the same value on the worker
    # thread - so one override covers every way this test's database is reached,
    # and there is no second place to forget.
    async def _gateway_db_path():
        return tmp_path / "gateway.db"

    gateway_main.app.dependency_overrides[gateway_main.gateway_db_path] = _gateway_db_path
    try:
        yield TestClient(gateway_main.app)
    finally:
        gateway_main.app.dependency_overrides.clear()


@pytest.fixture
def gateway_token(gateway_client):
    """A live Super User session, obtained through the real login route rather
    than by inserting a row - so every test that needs a session also exercises
    the way one is actually issued."""
    response = gateway_client.post(
        "/auth/login",
        json={"username": GATEWAY_TEST_USER, "password": GATEWAY_TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


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
