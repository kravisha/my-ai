"""My AI backend: a FastAPI process owning all business logic and state, the
same role vibe-agent's backend/main.py plays for that project. Every client
(the CLI, the desktop GUI) is a thin HTTP caller now - none of them touch
app/users.py, app/permissions.py, etc. directly anymore, only this process
does.

Mirrors vibe-agent's patterns deliberately: token returned in the JSON
response body (not a cookie), Authorization: Bearer <token> on protected
routes, no CORS (local desktop/CLI clients via `requests`, not a browser),
tool dispatch through a flat execute_tool(name, ...) function. The one
route vibe-agent has nothing to copy from is /chat's pause/resume protocol
for the consent prompt - see the docstring on chat() below.
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app import admin_auth
from app import server_auth
from app.audit import AuditLog
from app.main import SYSTEM_PROMPT
from app import model_budget
from app.model_budget import BudgetExceededError
from app.model_gateway import call_reasoning_model
from app.permissions import RESOURCE_PATHS, PermissionManager
from app.privacy_preferences import PrivacyPreferenceStore
from app.session import SessionStore
from app.tools import TOOLS, execute_tool
from app.users import UserStore, ensure_user_data_dir, normalize_username
from backend import chatterbox, continuity, coo_chat, finance_desk, fi_db, metadata_engine, missions, reference_data, remediation, status_events, strategy, view_intents, workspace
# Aliased because this module already has a route handler named `register`
# (/auth/register), which would silently shadow the module name.
from backend import register as strategic_register
from backend.controller import CONTROLLER_IDENTITY, Controller
from backend.transcripts import TranscriptStore

# How often the background loop below checks coo_directives for new work -
# see _controller_poll_loop. Same cadence as an agent's own heartbeat
# interval (agents/base.py), no reason for it to differ.
CONTROLLER_POLL_INTERVAL_SECONDS = 1.0

# The server console's static page (§75/TQ-26).
CONSOLE_DIR = Path(__file__).resolve().parent / "console"


async def _controller_poll_loop(controller: Controller) -> None:
    """Stands in for what a human would otherwise have to trigger by hand:
    repeatedly calls process_next_directive() so COO's spawn/retire requests
    (rows in coo_directives) actually get acted on. Runs as a plain asyncio
    task in this process's own event loop - the Controller itself is not a
    separate process, it lives inside the backend engine (confirmed process
    model), so this needs no subprocess or IPC of its own.

    Takes the Controller as an argument rather than reading a module global, so
    the loop cannot outlive or disagree with the instance lifespan created."""
    while True:
        controller.record_self_heartbeat()
        controller.process_next_directive()
        # The Controller's duty of care toward the one subordinate it manages
        # (Fault Tolerance Framework §4). Rate-limits itself, so calling it every
        # tick costs a comparison rather than a query - see Controller.watch_coo.
        # Nothing watched the COO before this: if it died, the health evaluation
        # that notices every other agent's silence died with it.
        controller.watch_coo()
        await asyncio.sleep(CONTROLLER_POLL_INTERVAL_SECONDS)


def _log_backup_cycle(results: dict) -> None:
    """One line per destination, and a failure is a loud line, not a silent
    return value — a backup loop that fails quietly is addendum 29 §1.8's
    'silently weakened recoverability' in its purest form."""
    for label, outcome in results.items():
        if outcome.get("ok"):
            pruned = f", pruned {len(outcome['pruned'])}" if outcome.get("pruned") else ""
            print(f"[continuity] {label}: {outcome['backup_id']} "
                  f"({outcome['files']} file(s), encryption {outcome['encryption']}{pruned})")
        else:
            print(f"[continuity] {label}: BACKUP FAILED — {outcome['error']}")


async def _backup_loop() -> None:
    """The automated backup addendum 29 §45 requires (SPEC_RECONCILIATION §59):
    every interval, one run_backup_cycle across every configured destination.

    Sleep-first, not backup-first: the shutdown backup in lifespan covers the
    state this process started from, so an immediate startup copy would
    duplicate it; the interval is the de facto RPO either way. The cycle runs
    in a worker thread because it is honest blocking I/O — hashing every file
    in user_data/ must not stall the event loop the Controller shares.
    Exceptions that escape run_backup_cycle's per-destination isolation
    (configuration errors like an unreadable key file) are caught here so the
    loop survives to report them again next interval rather than dying once,
    silently, forever."""
    while True:
        await asyncio.sleep(continuity.backup_interval_seconds())
        try:
            results = await asyncio.to_thread(continuity.run_backup_cycle)
            _log_backup_cycle(results)
        except Exception as exc:  # noqa: BLE001 - the loop must outlive any one failure
            print(f"[continuity] backup cycle FAILED: {exc.__class__.__name__}: {exc}")


def _reference_allows_bootstrap(readiness: dict) -> bool:
    """Whether the reference-data certification this readiness dict records
    is enough to wake the operational workforce.

    A pure function of `readiness` (reference_data.certify_readiness's
    return shape) so this decision is unit-testable directly, without going
    through lifespan - this repo's TestClient has a known lifespan-thread
    quirk, so a `with TestClient` test here would be the wrong tool.

    docs/SPEC_RECONCILIATION.md §40 disposed of blocking as real "once a
    consumer exists" for focus assets; Explorer's parity path
    (agents/explorer.py's `_parity_work`, reference_data.list_focus_assets)
    is that consumer. Only 'READY' passes - any other status, including one
    this function has never seen, is refused rather than assumed safe
    (addendum 24 §21/addendum 26 §17's fail-closed rule)."""
    return readiness.get("status") == "READY"


# Automation's way past the login gate. Not a security bypass - it grants no
# access to anything and the backend is loopback-only; it answers "may the
# workforce start with nobody watching", which is what simulation/harness.py
# needs when it launches a real backend for a live mission (§57). Every
# unattended start is published as such, so "who started this workforce"
# always has an answer.
AUTOSTART_ENV = "SERVER_AUTOSTART_WORKFORCE"


def autostart_requested() -> bool:
    """Read at call time, the convention every other switch here follows."""
    return os.environ.get(AUTOSTART_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _operational_startup(controller: Controller, operator: str | None) -> dict:
    """Addendum 38 §5's startup sequence: metadata, then reference data, then
    the workforce - each gated on the one before it.

    Extracted from lifespan so that *when* it runs is a separate question from
    *what* it does: 38 §3.3 wants an operator login to trigger it, automation
    wants it unattended, and neither should be able to change the sequence.

    Idempotent at the level that matters: `run_reference_engine` re-certifies
    rather than rebuilding, and the Controller will not start a second COO
    under one identity, so a second login re-reports rather than re-creating.

    Returns a report and publishes the same facts to the status stream (§73),
    so the operator who triggered it can watch and one who logs in later can
    read what happened before they arrived."""
    conn = controller.conn
    started_by = operator or "automation"
    status_events.publish(
        conn, "startup_sequence_started", f"Operational startup begun by {started_by}",
        status=status_events.STATUS_STARTING, department="server",
    )

    # The Metadata Engine, before reference data and gating it (addendum 39
    # §14, TQ-23/§72): the one strict ordering constraint that specification
    # has. Everything downstream of METADATA_READY may overlap and use
    # readiness thresholds instead (39 §14's own closing paragraph); this edge
    # is the exception.
    metadata = metadata_engine.run(conn)
    for line in metadata_engine.format_events(metadata["events"]):
        print(f"[metadata] {line}")

    if not metadata["ready"]:
        # 38 §12: a failed component must be visible and its dependents must
        # not falsely report success.
        print(
            "\n" + "!" * 78 + "\n"
            "! METADATA ENGINE FAILED - REFERENCE DATA AND THE WORKFORCE WERE NOT STARTED.\n"
            "! Fix the boot configuration (boot_config.json) and log in again.\n"
            + "!" * 78 + "\n"
        )
        readiness = {"status": "BLOCKED_ON_METADATA", "focus_asset_count": 0, "checks": []}
    else:
        # Day Zero rule (addendum 26 §3): reference data precedes waking any
        # operational agent. Runs on every startup, not just the first - it is
        # idempotent and an existing database still deserves a fresh
        # certification rather than a trusted stale one.
        reference_readiness = reference_data.run_reference_engine(conn)
        readiness = reference_readiness["readiness"]
        print(f"[reference_data] readiness: {readiness['status']} "
              f"({readiness['focus_asset_count']} focus assets)")
        ready = readiness["status"] == "READY"
        status_events.publish(
            conn, "reference_data_readiness",
            f"Reference data {readiness['status']} ({readiness['focus_asset_count']} focus assets)",
            severity=status_events.SEVERITY_INFO if ready else status_events.SEVERITY_ERROR,
            status=status_events.STATUS_READY if ready else status_events.STATUS_FAILED,
            engine="reference_data_engine",
        )

    # §40's disposition made real: FAILED certification blocks waking the
    # operational workforce, because Explorer's parity path consumes focus
    # assets (_reference_allows_bootstrap's docstring). The Controller and the
    # poll loop still run regardless - directives and the admin/dashboard
    # routes must stay reachable to show the failure (addendum 24 §21); it is
    # only the COO, and everything COO would spawn, that waits.
    workforce_started = _reference_allows_bootstrap(readiness)
    if workforce_started:
        controller.bootstrap_coo()
        status_events.publish(
            conn, "workforce_started",
            f"COO bootstrapped; workforce awake (started by {started_by})",
            status=status_events.STATUS_RUNNING, department="server",
        )
    else:
        failed = ", ".join(c["check"] for c in readiness["checks"] if not c["ok"]) or "unknown"
        print(
            "\n" + "!" * 78 + "\n"
            "! REFERENCE DATA NOT READY - COO AND THE OPERATIONAL WORKFORCE WERE NOT STARTED.\n"
            f"! Failed check(s): {failed}\n"
            "! The Controller and admin routes are still up so the dashboard can show this\n"
            "! failure (addendum 24 §21). Fix reference data and log in again.\n"
            + "!" * 78 + "\n"
        )
        status_events.publish(
            conn, "workforce_blocked",
            f"Workforce not started: reference data {readiness['status']} ({failed})",
            severity=status_events.SEVERITY_ERROR, status=status_events.STATUS_FAILED,
            department="server",
        )

    return {
        "started_by": started_by,
        "metadata_ready": metadata["ready"],
        "metadata_counts": metadata.get("counts", {}),
        "lifecycle_stage": metadata.get("lifecycle_stage"),
        "reference_status": readiness["status"],
        "workforce_started": workforce_started,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Owns the Controller for exactly as long as the server is serving.

    The Controller is constructed here, not at module level, because
    Controller.__init__ opens a database and runs init_schema on it - DDL,
    additive migrations and static-metadata seeding. At module level that made
    `import backend.main` a statement that writes to disk: any script, doc build
    or CLI that imported this module created or migrated a database as a side
    effect, and the test suite silently migrated the developer's real
    financial_intelligence.db before any fixture could intervene. Importing a
    module should be free; starting a server is where the cost belongs.

    Nothing outside this function holds the instance. If a route ever needs one,
    it should reach it through app.state or a dependency - not a module global,
    which is what has to be constructed at import time and is therefore how this
    would come back."""
    # The startup sequence the specs give literally (Consolidated §2, Org
    # Addendum §13): server starts -> Controller Agent starts (registering
    # itself as the first agent - it *is* this server process) -> Controller
    # creates COO. Every agent COO wants after this goes through the normal
    # directive queue, picked up by the poll loop above.
    # This process's model spend is the backend's own - /chat and anything
    # else in-process (TQ-18, §66). Agent subprocesses declare their own
    # identity in agents/base.py and are never counted here.
    model_budget.set_caller("backend")
    controller = Controller()
    controller.bootstrap_self()
    # §10: a restarting process must not assume the world stayed frozen while it
    # was away. An unclean shutdown leaves the COO subprocess alive - children
    # outlive their parent - and the old unconditional spawn would have started a
    # second one under the same permanent identity.
    reconciliation = controller.reconcile_on_start()
    print(f"[controller] reconciled on start: {reconciliation}")
    # The operational startup sequence no longer runs here unconditionally -
    # addendum 38 §3.3 requires it to follow an operator login (TQ-25/§74).
    # `_operational_startup` is the whole sequence; this branch only answers
    # who is allowed to trigger it.
    app.state.controller = controller
    # The console reads through this rather than through controller.conn -
    # see _console_read for why a path, not a connection (§78).
    app.state.db_path = controller.db_path
    app.state.startup_report = None
    if autostart_requested():
        # Automation: the simulation harness starts a real backend with no
        # human to log in (simulation/harness.py). Recorded in the event
        # stream as an unattended start rather than passed off as a login,
        # so "who started this workforce" always has an answer.
        print(f"[startup] {AUTOSTART_ENV} set - starting the workforce unattended")
        app.state.startup_report = _operational_startup(controller, operator=None)
    else:
        status_events.publish(
            controller.conn, "awaiting_login",
            "Server ready; workforce dormant until an operator authenticates",
            status=status_events.STATUS_WAITING, department="server",
        )
        print(
            "\n" + "=" * 78 + "\n"
            "= SERVER UP, WORKFORCE DORMANT. The COO and every agent wait for an operator\n"
            "= login (addendum 38 §3.3). POST /server/login with the Server Superuser\n"
            f"= credentials to begin the startup sequence, or set {AUTOSTART_ENV}=1 for\n"
            "= unattended automation.\n"
            + "=" * 78 + "\n"
        )
    poll_task = asyncio.create_task(_controller_poll_loop(controller))
    # Automated backup (addendum 29 §45, SPEC_RECONCILIATION §59). Interval 0
    # disables automated continuity entirely - the loop AND the shutdown
    # backup below - which is the test suite's and a developer's opt-out;
    # the manual CLI (python -m backend.continuity backup) is unaffected.
    backup_interval = continuity.backup_interval_seconds()
    backup_task = asyncio.create_task(_backup_loop()) if backup_interval > 0 else None
    try:
        yield
    finally:
        poll_task.cancel()
        if backup_task is not None:
            backup_task.cancel()
        # Stop the workforce before stopping ourselves. subprocess children
        # outlive their parent, so without this a server stop left every agent
        # running and writing to the database - see Controller.shutdown_agents.
        outcome = controller.shutdown_agents()
        print(f"[controller] agents stopped: {outcome['stopped']}, terminated: {outcome['terminated']}")
        # A clean shutdown is a clean agent exit, not a crash - see
        # Controller.shutdown_self.
        controller.shutdown_self()
        controller.close()
        # The shutdown backup, last, once every writer above has finished: a
        # clean stop leaves a copy of exactly the state a restart will resume
        # from, so the interval-sized RPO window only ever spans a *crash*.
        # After controller.close() because continuity opens its own
        # connections; guarded because a failed backup must not turn a clean
        # shutdown into a dirty one - it is reported, and the periodic loop's
        # last set still stands.
        if backup_interval > 0:
            try:
                _log_backup_cycle(continuity.run_backup_cycle())
            except Exception as exc:  # noqa: BLE001
                print(f"[continuity] shutdown backup FAILED: {exc.__class__.__name__}: {exc}")


app = FastAPI(title="My AI Backend", lifespan=lifespan)
users = UserStore()
sessions = SessionStore()
transcripts = TranscriptStore()


def build_stores(username: str) -> tuple[PermissionManager, PrivacyPreferenceStore, AuditLog]:
    user_dir = ensure_user_data_dir(username)
    return (
        PermissionManager(path=user_dir / "permissions.json"),
        PrivacyPreferenceStore(path=user_dir / "privacy_preferences.json"),
        AuditLog(path=user_dir / "audit_log.jsonl"),
    )


def get_current_user(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.removeprefix("Bearer ")
    username = sessions.validate(token)
    if username is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return username


def require_admin(username: str = Depends(get_current_user)) -> str:
    """Gate for every /admin route (addendum 14 §7).

    Built on the existing session auth rather than a parallel shared secret, so
    there is no second credential type to store, rotate, or leak - and so the
    audit trail records *which person* acted rather than a role name any client
    could type.

    Two distinct refusals, because they need different fixes: nobody is
    configured as an admin, versus this account is not one of them. Collapsing
    them into a single message would leave an operator guessing which."""
    if not admin_auth.admin_usernames():
        raise HTTPException(status_code=403, detail=admin_auth.NO_ADMINS_CONFIGURED)
    if not admin_auth.is_admin(username):
        raise HTTPException(status_code=403, detail=admin_auth.NOT_AN_ADMIN)
    return username


@app.get("/health")
def health():
    return {"status": "ok"}


# --- Auth ---


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    token: str


class MeResponse(BaseModel):
    username: str


@app.post("/auth/register", response_model=AuthResponse)
def register(request: RegisterRequest):
    try:
        normalized = users.register(request.username, request.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return AuthResponse(token=sessions.create(normalized))


@app.post("/auth/login", response_model=AuthResponse)
def login(request: LoginRequest):
    if not users.authenticate(request.username, request.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return AuthResponse(token=sessions.create(normalize_username(request.username)))


@app.post("/server/login")
async def server_login(request: LoginRequest):
    """The operator login addendum 38 §3.1/§3.3 puts in front of everything.

    A successful login starts the organization: metadata, reference data, then
    the workforce (`_operational_startup`). Deliberately **not** the same
    credential as `/auth/login`, which authenticates an ordinary application
    user against `users.json` - 39 §3 requires server authentication to stay
    separate from the Gateway's, and by the same reasoning it stays separate
    from the application's own accounts. An ordinary user must not be able to
    wake the workforce.

    Idempotent: logging in twice re-runs a sequence built to be re-run and
    re-reports, rather than starting a second COO.

    Returns the startup report so the caller sees what its login caused -
    including the case where the workforce did *not* start, which 38 §12
    requires be visible rather than reported as success."""
    problem = server_auth.configuration_problem()
    if problem is not None:
        # 503 rather than 401: nothing the caller typed is wrong, the server
        # is not set up to accept a login at all, and the message says what to
        # set. A 401 here would send an operator hunting for a typo.
        raise HTTPException(status_code=503, detail=problem)

    controller = getattr(app.state, "controller", None)
    if controller is None:
        raise HTTPException(status_code=503, detail="Server is still starting; try again shortly.")

    if not server_auth.verify(request.username, request.password):
        status_events.publish(
            controller.conn, "login_failed",
            f"Rejected server login for {request.username!r}",
            severity=status_events.SEVERITY_WARNING, status=status_events.STATUS_FAILED,
            department="server",
        )
        raise HTTPException(status_code=401, detail="Invalid Server Superuser credentials")

    operator = request.username.strip()
    status_events.publish(
        controller.conn, "login_succeeded", f"Server Superuser {operator!r} authenticated",
        status=status_events.STATUS_COMPLETED, department="server",
    )
    report = _operational_startup(controller, operator=operator)
    app.state.startup_report = report
    return report


@app.get("/console", include_in_schema=False)
def console_page():
    """The server console (addendum 38 §4, owner decision §75): the live
    newspaper of everything the organization is doing.

    Served by the backend because it *is* the server's console. The Gateway
    runs in its own process on its own port so it can outlive the
    organization's absence (16 §22/§23); a console whose entire subject is the
    organization has no reason to live over there."""
    return FileResponse(CONSOLE_DIR / "index.html", media_type="text/html")


async def _console_read(work, fallback):
    """Run a console read **off the event loop, on its own connection**.

    This is the fix for a server that wedged solid under a live workforce
    (SPEC_RECONCILIATION §78). The console's routes are `async def` - they had
    to be, because sqlite3 connections belong to the thread that opened them
    and the lifespan connection belongs to the loop's thread. But that put
    blocking database work *on* the loop, and SQLite admits one writer at a
    time: with agents writing continuously, every console read queued behind
    them for up to the busy timeout and froze the whole server, HTTP and
    controller poll loop alike.

    `gateway/main.py`'s `gateway_db_path` dependency already states the
    answer: hand a worker thread a *path*, because "handing that thread a
    path is the only safe thing to hand it". The thread opens its own
    connection, uses it, and closes it - thread affinity satisfied, loop never
    blocked, and a slow read costs one worker rather than the server.
    """
    db_path = getattr(app.state, "db_path", None)
    if db_path is None:
        return fallback

    def run():
        conn = fi_db.get_connection(db_path)
        try:
            return work(conn)
        finally:
            conn.close()

    try:
        return await asyncio.to_thread(run)
    except Exception as exc:  # noqa: BLE001 - one desk must not blank the console
        return {**fallback, "error": f"{exc.__class__.__name__}: {exc}"} \
            if isinstance(fallback, dict) else fallback



@app.get("/console/feed")
async def console_feed(
    limit: int = 200,
    source: str | None = None,
    attention_only: bool = False,
    since_id: int | None = None,
):
    """The newspaper itself: narration, newest first, filterable (38 §4.2/§4.4).

    **Async on purpose**, the same reason `gateway/main.py`'s `gateway_db`
    dependency is: FastAPI runs *synchronous* routes in a worker threadpool,
    and sqlite3 connections are bound to the thread that opened them. This
    connection is opened in lifespan, on the event loop's thread, so a sync
    route would reach it from the wrong thread and raise. The reads here are
    small and local; blocking the loop for them is the cheaper half of the
    trade.

    `since_id` lets the page ask only for what it has not printed yet, so a
    console left open all day sends small deltas rather than re-fetching the
    whole feed every few seconds - the same restraint 38 §13 asks of the
    publishers.

    Unauthenticated, like `/server/status` and for a narrower version of the
    same reason: this backend is loopback-only (28's posture, TQ-04's recorded
    preconditions), and a console that cannot read the feed cannot be a
    console. If the backend is ever exposed, this moves behind the operator
    session in the same change that opens the port - noted here so the
    coupling is not discovered later."""
    severities = status_events.ATTENTION_SEVERITIES if attention_only else None
    capped = min(limit, 500)

    def work(conn):
        events = status_events.recent(conn, limit=capped, source=source, severities=severities)
        if since_id is not None:
            events = [event for event in events if event["event_id"] > since_id]
        return {
            "events": events,
            # Derived, never enumerated (38 §4.4): a new department appears in
            # the filter control because it published, not because the page
            # was edited.
            "sources": status_events.sources(conn),
            # "Where does everything stand", which a scrolling feed cannot
            # answer without the reader doing the work by eye (§4.5).
            "standing": status_events.current_status(conn),
            "awaiting_login": getattr(app.state, "startup_report", None) is None,
        }

    return await _console_read(
        work, {"events": [], "sources": [], "standing": [], "awaiting_login": True})


@app.get("/console/overview")
async def console_overview():
    """Everything the console's non-feed tabs render (addendum 38 §4.4's
    "different perspectives", owner decision §75).

    One endpoint rather than six, because the page polls once and a console
    that opened six connections every two seconds would be the log-flooding
    mistake wearing a different hat.

    **Every section reports what actually exists.** Where a capability is not
    built, the section says so and names why, rather than showing an empty
    table that reads as "nothing happening" - a newspaper whose parliament
    page is blank has failed to report that parliament never convened. Async
    for the thread reason console_feed's docstring gives."""
    def build(conn):
        return _overview(conn)

    return await _console_read(build, {"available": False, "reason": "Server is still starting."})


def _overview(conn) -> dict:
    """Gathered on a worker thread (see _console_read)."""
    def _safe(section, fn):
        """One broken section must not blank the whole console - 38 §12's
        'a failed component must not silently disappear', applied to the
        thing doing the reporting."""
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{section} unavailable: {exc.__class__.__name__}: {exc}"}

    def _organization():
        agents = conn.fetchall(
            "SELECT identity, role, lifecycle_state, process_state, behavior_version, "
            "spawned_at, last_heartbeat_at FROM agent_registry ORDER BY role, identity"
        )
        named = {
            row["assigned_to_identity"]: row["name"]
            for row in conn.fetchall(
                "SELECT name, assigned_to_identity FROM agent_names "
                "WHERE assigned_to_identity IS NOT NULL"
            )
        }
        return {
            "agents": [{**dict(a), "name": named.get(a["identity"])} for a in agents],
            "names_available": conn.fetchone(
                "SELECT COUNT(*) AS n FROM agent_names "
                "WHERE assigned_to_identity IS NULL AND reserved = 0"
            )["n"],
        }

    def _strategy():
        entries = strategic_register.list_register(conn)
        return {
            "register": strategic_register.queue_order(conn)[:25],
            "total": len(entries),
            # The development queue is a maintained document, not a table -
            # §54 recorded why duplicating one into the other would
            # manufacture two sources of truth. Named so the operator knows
            # where the other half of "strategy" lives.
            "note": "The development queue lives in docs/TASK_QUEUE.md; this register holds "
                    "what the organization itself files (SPEC_RECONCILIATION §54).",
        }

    def _simulation():
        runs = missions.list_missions(conn)
        return {
            "missions": runs[:25],
            "total": len(runs),
        }

    def _alerts():
        """Warnings and failures, plus the corrective recommendations.

        The recommendations were removed from this polled path when they took
        196 seconds on a real database and wedged the console (§79). TQ-29/§80
        indexed the columns the compliance check correlates on and the same
        call now returns in 0.01s, so they are back where they belong. If this
        ever slows again the console is the place it will show first, which is
        the argument for it being here rather than somewhere quieter."""
        return {
            "recent": status_events.recent(
                conn, limit=40, severities=status_events.ATTENTION_SEVERITIES),
            "corrective": [
                {"rule": item.rule, "classification": item.classification,
                 "findings": item.findings, "remedy": getattr(item, "remedy", None)}
                for item in remediation.corrective_items(conn, limit=20)
            ],
            "summary": remediation.summarise(conn),
        }

    def _parliament():
        """Honest reporting of a thing that does not exist.

        Addendum 32's parliament, elections and committees are deferred with
        a stated reason (§47): at a population of a handful of role-agents the
        machinery would be ceremony without constituents. The register below
        is what the organization actually files today, and is the closest
        real thing to a session outcome."""
        filed = strategic_register.list_register(conn)
        return {
            "convened": False,
            "reason": "No parliament, committee or voting body exists yet. Addendum 32's "
                      "machinery is deferred with its reason recorded in "
                      "SPEC_RECONCILIATION §47: at the current population it would be "
                      "ceremony without constituents.",
            "standing_in": "The Strategic Priority Register is where proposals are filed "
                           "and dispositioned today; the owner acts as the Board.",
            "filed_entries": len(filed),
        }

    return {
        "available": True,
        "lifecycle_stage": (getattr(app.state, "startup_report", None) or {}).get("lifecycle_stage"),
        "organization": _safe("organization", _organization),
        "strategy": _safe("strategy", _strategy),
        "simulation": _safe("simulation", _simulation),
        "alerts": _safe("alerts", _alerts),
        "parliament": _safe("parliament", _parliament),
    }


class CooChatRequest(BaseModel):
    question: str
    language: str = coo_chat.DEFAULT_LANGUAGE
    history: list[dict] = []


class WorkspaceSave(BaseModel):
    workspace: dict


@app.get("/console/workspace")
async def console_workspace_load():
    """Rehydrate the workspace (addendum 40 §4.1 step 5, §5).

    Always answers, even when there is nothing to restore or the stored state
    is unusable - the console must open either way, and §15 asks that resumed
    work be clearly distinguished from work that could not be."""
    return await _console_read(
        workspace.load,
        {"restored": False, "reason": "the runtime is still starting", "workspace": {}})


@app.put("/console/workspace")
async def console_workspace_save(request: WorkspaceSave):
    """Checkpoint the workspace. Called continuously, not on close (§5.1).

    Runs on a worker thread like every other database route here (§78), so a
    keystroke's checkpoint never competes with the event loop."""
    try:
        saved = await _console_read(
            lambda conn: workspace.save(conn, request.workspace), None)
    except workspace.WorkspaceTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc))
    if saved is None:
        raise HTTPException(status_code=503, detail="Server is still starting.")
    return saved


@app.get("/console/finance")
async def console_finance():
    """The Finance desk (TQ-27, owner request). Everything it returns is
    generated by this system's own simulation engine and flagged as such -
    see backend/finance_desk.py for why that flag is the design constraint
    rather than a footnote. Async for the thread reason console_feed gives."""
    return await _console_read(
        finance_desk.front_page,
        {"simulated": True, "available": False, "notice": finance_desk.SIMULATED_NOTICE,
         "reason": "Server is still starting.",
         "tickers": [], "movers": {"gainers": [], "losers": []}, "headlines": []})


@app.get("/console/chatterbox")
async def console_chatterbox():
    """The Chatterbox (owner request): every conversation the organization is
    holding, colour-coded by state, plus the measured collaboration health of
    the desks holding them. See backend/chatterbox.py for why silence gets its
    own state rather than being folded into 'not completed'."""
    return await _console_read(
        chatterbox.living_map,
        {"conversations": [], "counts": {}, "edges": [], "health": [], "quiet": True,
         "quiet_note": "Server is still starting."})


@app.post("/console/chat")
async def console_chat(request: CooChatRequest):
    """Ask the COO a question; get the answer streamed back (TQ-27).

    **Streamed so the operator can interrupt it.** A console that must wait
    for a complete reply before it can be stopped is not interruptible, and
    barge-in was an explicit requirement; server-sent events let the browser
    abort mid-sentence and let the page speak each fragment as it lands
    rather than after the whole answer arrives.

    The split across threads is load-bearing and matches
    `gateway/streaming.py`'s stated rule: the state digest is read **here**,
    on the thread that owns the sqlite connection, and only plain strings
    cross into the worker thread that iterates the model. A worker touching
    the database would be reaching into a connection it does not own."""
    controller = getattr(app.state, "controller", None)
    if controller is None:
        raise HTTPException(status_code=503, detail="Server is still starting; try again shortly.")
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Ask something.")

    # A view command is answered here, deterministically, without the model
    # (§84). "show me the chatterbox" has one meaning; spending a model call
    # and a second of latency on it would be worse in every dimension, and a
    # matcher is testable in a way a prompt is not. Anything not recognised
    # with certainty falls through to the model untouched.
    directive = view_intents.interpret(request.question)
    if directive is not None:
        await _console_read(
            lambda conn: status_events.publish(
                conn, "operator_command",
                f"Operator directed the view: {request.question[:180]}",
                department="coo", status=status_events.STATUS_COMPLETED),
            None)

        async def command_events():
            yield _sse({"type": "directive", "directive": directive})
            yield _sse({"type": "text", "text": directive["say"]})
            yield _sse({"type": "done"})

        return StreamingResponse(command_events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # Read the world on a worker thread with its own connection (§78), not
    # on the loop - the digest is several queries and the loop must stay free.
    prepared = await _console_read(
        lambda conn: coo_chat.prepare(conn, request.question,
                                      language=request.language, history=request.history),
        None)
    if prepared is None:
        raise HTTPException(status_code=503, detail="Server is still starting.")
    system, messages = prepared
    # The operator's question is itself part of the organization's record:
    # what was asked, and when, is legitimate narration. The answer is not
    # published - it is derived, and republishing it would double the feed.
    await _console_read(
        lambda conn: status_events.publish(
            conn, "operator_question",
            f"Operator asked the COO: {request.question[:180]}",
            department="coo", status=status_events.STATUS_RUNNING),
        None)

    # §10 asks for both halves - "changes the visual focus, and answers
    # conversationally". A question plainly about one desk focuses it while
    # the prose arrives; a wrong guess costs a tab change during an answer
    # that still comes, which is why this may be looser than `interpret`.
    focus = view_intents.followed_by_view(request.question)

    async def events():
        from gateway.streaming import iterate_in_thread

        if focus:
            yield _sse({"type": "directive",
                        "directive": {"action": view_intents.ACTION_SHOW_VIEW, "view": focus}})

        try:
            async for chunk in iterate_in_thread(
                lambda: coo_chat.stream_answer(system, messages)
            ):
                if isinstance(chunk, BaseException):
                    yield _sse({"type": "error", "error": str(chunk)})
                    return
                yield _sse(chunk)
        except asyncio.CancelledError:
            # The operator hit stop, or closed the tab. Not an error, and not
            # worth a traceback: the point of streaming was that this can
            # happen mid-sentence.
            raise
        yield _sse({"type": "done"})

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",   # so a proxy cannot defeat the streaming
    })


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@app.get("/console/languages")
async def console_languages():
    """What the COO can be asked to answer in. The console renders these as
    buttons; anything else typed in still works, because the prompt asks the
    model to match the operator's own language. Voices are a separate
    question the *browser* answers - see the console page."""
    return {"languages": [{"code": code, "label": label}
                          for code, label in coo_chat.LANGUAGE_LABELS.items()],
            "default": coo_chat.DEFAULT_LANGUAGE}


@app.get("/server/status")
async def server_status():
    """Whether the workforce is awake, and what the last startup did.

    Unauthenticated on purpose, and carrying no state beyond that: a login
    screen needs to know whether to offer a login, and refusing to say would
    make the console unable to render itself. It reports no counts, no
    identities, and no configuration."""
    report = getattr(app.state, "startup_report", None)
    return {
        "workforce_started": bool(report and report.get("workforce_started")),
        "awaiting_login": report is None,
        "login_available": server_auth.is_configured(),
        "lifecycle_stage": (report or {}).get("lifecycle_stage"),
    }


@app.post("/auth/logout")
def logout(authorization: str | None = Header(default=None)):
    if authorization and authorization.startswith("Bearer "):
        sessions.revoke(authorization.removeprefix("Bearer "))
    return {"status": "logged out"}


@app.get("/auth/me", response_model=MeResponse)
def me(username: str = Depends(get_current_user)):
    return MeResponse(username=username)


# --- Chat ---


class ChatMessage(BaseModel):
    role: str
    content: Any


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = []
    consent_answer: str | None = None
    consent_key: str | None = None


@app.post("/chat")
def chat(request: ChatRequest, username: str = Depends(get_current_user)):
    """The client sends its full message history on every call (including
    the newest user turn it wants answered) - the server holds no
    conversation state between requests, matching vibe-agent's /chat.

    The one thing vibe-agent's /chat never has to deal with: this tool-use
    loop can pause mid-reply needing a live always/once/never answer. HTTP
    can't just block and wait the way the old in-process chat_turn() did,
    so a pause ends the request early with {"needs_consent": ..., "messages":
    ...} instead of a reply. The client shows its own dialog, then calls
    this route again with the SAME messages list (already containing the
    assistant's pending tool_use turn) plus consent_answer/consent_key -
    that resume branch below finds the pending tool_use block, executes it
    with the given answer, and falls through into the normal loop to get
    the model's actual reply. No server-side session memory needed either
    way; the client already has to hold the messages list to keep chatting,
    so it can hold the one extra paused turn too.

    Also records each completed user/assistant turn into `transcripts`
    (see backend/transcripts.py) for the server monitor (monitor/app.py) -
    a live, in-memory, separate-from-the-actual-protocol side effect. A
    resume call never double-records the user's original question (guarded
    on consent_answer is None), and a needs_consent pause itself isn't
    recorded as an interim entry - only completed exchanges show up.
    """
    permissions, preferences, audit_log = build_stores(username)
    messages = [m.model_dump() for m in request.messages]

    if request.consent_answer is None and messages and messages[-1]["role"] == "user":
        transcripts.record(username, "user", messages[-1]["content"])

    if request.consent_answer is not None:
        last_assistant = next((m for m in reversed(messages) if m["role"] == "assistant"), None)
        pending_block = None
        if last_assistant is not None:
            pending_block = next(
                (b for b in last_assistant["content"] if isinstance(b, dict) and b.get("type") == "tool_use"),
                None,
            )
        if pending_block is None:
            raise HTTPException(status_code=400, detail="No pending tool call to resolve consent for")

        if request.consent_answer in ("always", "never") and request.consent_key:
            preferences.set(request.consent_key, request.consent_answer)
        result = execute_tool(
            pending_block["name"], permissions, preferences, audit_log,
            allow_once=(request.consent_answer == "once"),
        )
        messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": pending_block["id"],
                "content": json.dumps(result),
                "is_error": "error" in result,
            }],
        })

    while True:
        try:
            response = call_reasoning_model(SYSTEM_PROMPT, messages, TOOLS)
        except BudgetExceededError as exc:
            # The cost circuit breaker (app/model_budget.py) refused before
            # spending. 503 rather than 500: the service is fine, the budget
            # is exhausted, and the message says which limit and how to raise
            # it deliberately - a refusal is only a defense if it is legible.
            raise HTTPException(status_code=503, detail=str(exc))
        messages.append({"role": "assistant", "content": [b.model_dump() for b in response.content]})

        if response.stop_reason != "tool_use":
            reply = "".join(b.text for b in response.content if b.type == "text")
            transcripts.record(username, "assistant", reply)
            return {"reply": reply, "messages": messages}

        tool_results = []
        paused = None
        for block in response.content:
            if block.type != "tool_use":
                continue
            result = execute_tool(block.name, permissions, preferences, audit_log)
            if result.get("status") == "needs_consent":
                paused = result
                break
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result),
                "is_error": "error" in result,
            })

        if paused is not None:
            return {"needs_consent": paused, "messages": messages}

        messages.append({"role": "user", "content": tool_results})


# --- Permissions ---


class ResourceRequest(BaseModel):
    resource: str


@app.get("/permissions")
def list_permissions(username: str = Depends(get_current_user)):
    permissions, _, _ = build_stores(username)
    return {resource: permissions.is_granted(resource) for resource in RESOURCE_PATHS}


@app.post("/permissions/grant")
def grant_permission(request: ResourceRequest, username: str = Depends(get_current_user)):
    if request.resource not in RESOURCE_PATHS:
        raise HTTPException(status_code=400, detail=f"Unknown resource: {request.resource}")
    permissions, _, _ = build_stores(username)
    permissions.grant(request.resource)
    return {"resource": request.resource, "granted": True}


@app.post("/permissions/revoke")
def revoke_permission(request: ResourceRequest, username: str = Depends(get_current_user)):
    if request.resource not in RESOURCE_PATHS:
        raise HTTPException(status_code=400, detail=f"Unknown resource: {request.resource}")
    permissions, _, _ = build_stores(username)
    permissions.revoke(request.resource)
    return {"resource": request.resource, "granted": False}


# --- Preferences ---


class PreferenceKeyRequest(BaseModel):
    key: str


@app.get("/preferences")
def list_preferences(username: str = Depends(get_current_user)):
    _, preferences, _ = build_stores(username)
    return preferences.list_all()


@app.post("/preferences/reset")
def reset_preference(request: PreferenceKeyRequest, username: str = Depends(get_current_user)):
    _, preferences, _ = build_stores(username)
    return {"key": request.key, "forgotten": preferences.forget(request.key)}


# --- Activity ---


@app.get("/activity")
def list_activity(username: str = Depends(get_current_user)):
    _, _, audit_log = build_stores(username)
    if not audit_log.path.exists():
        return []
    return [json.loads(line) for line in audit_log.path.read_text(encoding="utf-8").splitlines()]


# --- Admin (server monitor) ---
#
# Unauthenticated, unlike every other route - this is an operator/admin view
# across every account's conversations, not a route scoped to "your own"
# data via get_current_user. The project has no admin-auth concept to reuse
# yet and the whole system is local-only right now, so this is a deliberate,
# flagged simplification rather than an oversight.


@app.get("/admin/clients")
def list_clients(admin: str = Depends(require_admin)):
    return {"clients": transcripts.list_clients()}


@app.get("/admin/clients/{username}/transcript")
def get_client_transcript(username: str, admin: str = Depends(require_admin)):
    return {"username": username, "entries": transcripts.get_transcript(username)}


# --- Admin (Controller control panel) ---
#
# Read-only observability over the agent organization, for the operator panel
# (addendum 14 §7). Unauthenticated for the same flagged reason as the routes
# above: there is no admin-auth concept yet and the system is local-only.
#
# Nothing here mutates. Lifecycle actions belong to the Controller alone
# (addendum 11 §15), so they are a separate, audited increment rather than
# something the observability layer quietly acquires.


def panel_db():
    """A short-lived read connection per request, deliberately *not*
    conn.

    Two reasons, one forced and one chosen. Forced: sqlite3 connections are
    bound to the thread that opened them, and FastAPI runs sync handlers in a
    worker threadpool, so reusing the Controller's connection raises
    ProgrammingError at request time - an error no import check catches, only a
    real request does.

    Chosen: even with that solved, the panel should not share the handle the
    Controller uses to execute lifecycle actions. The database is in WAL mode,
    so additional readers are safe and concurrent, and this way a slow panel
    query can never stall the directive poll loop."""
    conn = fi_db.get_connection()
    try:
        yield conn
    finally:
        conn.close()


def _parse_json_field(value, default=None):
    """Several tables store JSON in TEXT columns. Parsed here so the panel
    receives structured data rather than re-parsing strings."""
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


@app.get("/admin/agents")
def list_agents(conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """The organization as it currently stands, on both axes.

    lifecycle_state and process_state are reported separately and never
    collapsed - that separation is the whole point of the two-axis model, and a
    panel that showed one merged status would reintroduce the confusion the
    model exists to remove. `status` is included only because historical rows
    carry it; nothing should decide from it."""
    agents = []
    for agent in fi_db.list_agents(conn):
        age = fi_db.heartbeat_age_seconds(agent)
        agents.append({
            "identity": agent["identity"],
            "role": agent["role"],
            "pid": agent["pid"],
            "lifecycle_state": agent["lifecycle_state"],
            "process_state": agent["process_state"],
            "status": agent["status"],
            "retire_requested": bool(agent["retire_requested"]),
            "spawned_at": agent["spawned_at"],
            "last_heartbeat_at": agent["last_heartbeat_at"],
            "heartbeat_age_seconds": None if age is None else round(age, 2),
            # Directive E17: which code this life is running. NULL means the
            # row predates the column - unknown, not "current".
            "behavior_version": agent["behavior_version"],
        })
    return {"agents": agents}


@app.get("/admin/agents/{identity}")
def describe_agent(identity: str, conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """Addendum 14 §6's fifteen self-awareness questions for one agent.

    Sourced from the organizational record and the role's charter, so it is
    accurate but it is not the agent *speaking* - a live-answered version is
    what the UQI adds. Flagged in the payload as `answered_by` so the panel can
    never present a database read as an agent's own reply."""
    description = fi_db.describe_agent(conn, identity)
    if description is None:
        raise HTTPException(status_code=404, detail=f"No agent with identity {identity!r}")
    return {"answered_by": "organizational_record", **description}


class RegisterEntryRequest(BaseModel):
    title: str
    category: str
    rationale: str
    need_flag: str | None = None
    quick_win: bool = False
    source_reference: str | None = None


class RegisterStatusRequest(BaseModel):
    status: str
    reason: str | None = None
    record_reference: str | None = None


@app.get("/admin/register")
def read_register(status: str | None = None, conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """The Strategic Priority Register (addendum 31 §3): every entry, plus the
    open ones in working order by the doctrine's own rules — Needs before
    Wants, flag severity, Quick-Win acceleration. Both views from one store,
    so there is exactly one queue however it is read."""
    try:
        entries = strategic_register.list_register(conn, status=status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "entries": entries,
        "queue": [entry["id"] for entry in strategic_register.queue_order(conn)],
    }


@app.post("/admin/register")
def file_register_entry(request: RegisterEntryRequest, conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """File a petition or mandate (addendum 31 §5). The admin's username is the
    recorded origin - a register where entries do not say who filed them would
    fail 32 §9.2 (who proposed the change) on day one."""
    try:
        entry_id = strategic_register.file_entry(
            conn,
            title=request.title,
            category=request.category,
            origin=admin,
            rationale=request.rationale,
            need_flag=request.need_flag,
            quick_win=request.quick_win,
            source_reference=request.source_reference,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": entry_id, "entry": strategic_register.get_entry(conn, entry_id)}


@app.post("/admin/register/{entry_id}/status")
def transition_register_entry(entry_id: int, request: RegisterStatusRequest, conn=Depends(panel_db), admin: str = Depends(require_admin)):
    try:
        strategic_register.set_status(
            conn, entry_id, request.status,
            reason=request.reason, record_reference=request.record_reference,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"entry": strategic_register.get_entry(conn, entry_id)}


@app.get("/admin/intelligence")
def list_intelligence(conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """Every lens, active or stale, with the evidence behind its standing.

    Stale artifacts are included deliberately. A lens that expired is the most
    informative thing in this table - it is the system having noticed something
    - and hiding it would leave the panel showing only what still looks fine."""
    artifacts = []
    for artifact in fi_db.list_intelligence_artifacts(conn, artifact_kind=fi_db.LENS_KIND):
        conditions = _parse_json_field(artifact["validity_conditions"], {})
        regime = conditions.get("regime") or {}
        artifacts.append({
            "id": artifact["id"],
            "name": artifact["name"],
            "version": artifact["version"],
            "value": _parse_json_field(artifact["value"]),
            "status": artifact["status"],
            "rationale": artifact["rationale"],
            "staleness_reason": artifact["staleness_reason"],
            "validity_conditions": conditions,
            "observed_under_regime": regime.get("observed_under"),
            "regime_bound_at": regime.get("bound_at"),
            "performance": fi_db.lens_performance(conn, artifact["id"]),
            "created_at": artifact["created_at"],
        })
    proposals = [
        _artifact_json(artifact)
        for artifact in fi_db.list_intelligence_artifacts(conn, status="proposed")
    ]
    return {"artifacts": artifacts, "proposals": proposals}


@app.get("/admin/strategies")
def list_strategies(conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """Every strategy, any status, plus which active ones rest on knowledge
    that is no longer active.

    Mirrors /admin/intelligence's shape: all rows are returned rather than
    only active ones, for the same reason a stale lens is shown there - a
    retired or superseded strategy is part of the organization's history,
    and hiding it would leave the panel showing only what still looks
    fine."""
    return {"strategies": strategy.list_strategies(conn), "unhealthy": strategy.unhealthy(conn)}


def _artifact_json(artifact: dict) -> dict:
    """Shared shape for an intelligence_artifacts row across the read routes
    below, so a proposal and an adopted/rejected row serialize identically."""
    return {
        "id": artifact["id"],
        "name": artifact["name"],
        "version": artifact["version"],
        "artifact_kind": artifact["artifact_kind"],
        "value": _parse_json_field(artifact["value"]),
        "status": artifact["status"],
        "rationale": artifact["rationale"],
        "validity_conditions": _parse_json_field(artifact["validity_conditions"], {}),
        "producer_identity": artifact["producer_identity"],
        "created_at": artifact["created_at"],
    }


# --- Artifact succession (the Trainer's seat, held by a human) --------------
#
# The expiry cycle (active -> stale, agents/coo.py) flags a lens that evidence
# says no longer holds, but flagging alone leaves the organization on that
# flagged value forever, or dropped to the hardcoded seed once it goes stale
# (agents/explorer.py's fallback). These three routes are the other half:
# proposing and adjudicating a successor.
#
# The Trainer's seat, held by a human. Addendum 13's Trainer would propose
# from evidence; until Phase D, the operator reads lens_performance and the
# staleness_reason on this same panel and proposes the correction. What
# matters is that the act is recorded - proposer, rationale, adjudication -
# so when a Trainer exists it inherits a recorded practice, not a blank.

class ProposeRevisionRequest(BaseModel):
    value: Any
    rationale: str
    evidence_ref: str | None = None


class RejectRevisionRequest(BaseModel):
    reason: str


@app.post("/admin/intelligence/{name}/proposals")
def propose_intelligence_revision(name: str, request: ProposeRevisionRequest,
                                   conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """File a candidate revision for an existing lens, attributed to the admin
    who filed it. 400s on the same refusals propose_artifact_revision makes -
    no prior artifact by this name, no rationale, or an open proposal already
    in flight - because those are operator mistakes worth reporting, not
    server errors."""
    try:
        revision_id = fi_db.propose_artifact_revision(
            conn, name, request.value, request.rationale, proposed_by=admin,
            evidence_ref=request.evidence_ref,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _artifact_json(conn.fetchone("SELECT * FROM intelligence_artifacts WHERE id = ?", (revision_id,)))


@app.post("/admin/intelligence/proposals/{revision_id}/adopt")
def adopt_intelligence_revision(revision_id: int, conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """Adjudicate a proposal in: it becomes active, its predecessor(s) become
    superseded, and the next agent cycle resolves it through
    get_active_artifact with no restart and no config edit."""
    try:
        adopted = fi_db.adopt_artifact_revision(conn, revision_id, adopted_by=admin)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _artifact_json(adopted)


@app.post("/admin/intelligence/proposals/{revision_id}/reject")
def reject_intelligence_revision(revision_id: int, request: RejectRevisionRequest,
                                  conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """Adjudicate a proposal out, with a reason on the record - a rejection
    without one teaches nothing to whoever reads this later."""
    try:
        fi_db.reject_artifact_revision(conn, revision_id, rejected_by=admin, reason=request.reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _artifact_json(conn.fetchone("SELECT * FROM intelligence_artifacts WHERE id = ?", (revision_id,)))


@app.get("/admin/knowledge")
def knowledge(limit: int = 50, include_history: bool = False,
              conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """What the organization believes, and what it knows it does not know.

    Superseded and resolved records are available via include_history rather
    than shown by default - the current view is what is believed *now*, but a
    belief that turned out wrong is itself knowledge and must stay reachable."""
    status = None if include_history else fi_db.KNOWLEDGE_ACTIVE
    return {
        "lessons": fi_db.list_knowledge(conn, record_kind=fi_db.KNOWLEDGE_LESSON, status=status, limit=limit),
        "open_questions": fi_db.list_knowledge(conn, record_kind=fi_db.KNOWLEDGE_OPEN_QUESTION, status=status, limit=limit),
    }


@app.get("/admin/reference")
def reference_status(conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """The Reference Data Engine's dashboard shape (addendum 24 §19): ready
    state, the latest certification, and enough counts that an operator does
    not need to read terminal output to know what happened at startup."""
    return reference_data.status(conn)


@app.get("/admin/sources")
def source_reliability(conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """What each evidence source has earned, and what is not yet known about
    it. Sources below the evidence threshold are included with stated=False -
    "not yet judged" is a different answer from "unreliable"."""
    return {"sources": fi_db.list_source_reliability(conn),
            "min_graded_contributions": fi_db.MIN_GRADED_CONTRIBUTIONS}


@app.get("/admin/regime")
def market_regime(conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """The system's current estimate of market conditions, per security and
    aggregated. This is an estimate the system inferred from observation - it
    was never told the regime the provider generates under."""
    return {
        "securities": fi_db.list_market_regime(conn),
        "market_wide": fi_db.current_market_characterization(conn),
    }


@app.get("/admin/cross-checks")
def list_cross_checks(limit: int = 25, conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """Recent Explorer<->Speculator contracts, both findings intact.

    Returned unreconciled, exactly as stored. The panel must show two claims
    and no verdict - collapsing them into "agreed"/"disagreed" here would erase
    the disagreement this table exists to preserve (addendum 12 §14)."""
    rows = conn.fetchall(
        "SELECT * FROM cross_check_requests ORDER BY id DESC LIMIT ?", (limit,)
    )
    return {"cross_checks": [
        {
            "id": row["id"],
            "security": row["security"],
            "requester_role": row["requester_role"],
            "responder_role": row["responder_role"],
            "question": row["question"],
            "requester_finding": _parse_json_field(row["requester_finding"], {}),
            "responder_finding": _parse_json_field(row["responder_finding"]),
            "status": row["status"],
            "outcome": row["outcome"],
            "created_at": row["created_at"],
            "answered_at": row["answered_at"],
        }
        for row in rows
    ]}


@app.get("/admin/discovery")
def discovery_activity(limit: int = 25, conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """What the discovery slice has actually produced: the pending queue, and
    the most recent analyses with their grades."""
    results = conn.fetchall(
        "SELECT a.*, g.overall_score, g.worth_the_compute, g.rationale AS grade_rationale, "
        "r.overall AS risk_overall, r.factors AS risk_factors "
        "FROM analysis_results a LEFT JOIN grades g ON g.analysis_result_id = a.id "
        "LEFT JOIN risk_assessments r ON r.analysis_result_id = a.id "
        "ORDER BY a.id DESC LIMIT ?", (limit,)
    )
    return {
        # In the order Analysis will actually take them, each with its reason.
        # Showing arrival order would misrepresent what the system is about to
        # do now that the queue is no longer worked FIFO.
        "pending_reports": fi_db.prioritised_pending_reports(conn),
        "recent_analyses": results,
        "performance_card": fi_db.get_performance_card(conn),
    }


# --- Universal Human Query Interface (addendum 14 §7) ---
#
# Human-to-agent only. §8 is explicit that agents do not use this to talk to
# each other; inter-agent work goes through the queue/directive tables.
#
# §7 also requires this to be "privilege-controlled and auditable". Auditable is
# satisfied: uqi_requests keeps every question, who asked, the answer, and which
# process produced it. Privilege-controlled is NOT satisfied yet - these routes
# are unauthenticated like the rest of /admin/*, because the project has no
# admin-auth concept to hang it on. Flagged here rather than quietly claimed.


class AskRequest(BaseModel):
    question: str


@app.post("/admin/agents/{identity}/uqi")
def ask_agent(identity: str, request: AskRequest, conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """Put a question to a specific running agent.

    Returns immediately with a request id rather than blocking. The agent
    answers on its own cycle, which is the same non-blocking discipline every
    other cross-process exchange in this system uses - an HTTP handler that
    waited on an agent's poll loop would be the one place holding a thread open
    against another process's schedule.

    The target must exist in the registry. Asking a nonexistent agent is an
    operator error worth surfacing, not a question left to time out."""
    if fi_db.get_agent(conn, identity) is None:
        raise HTTPException(status_code=404, detail=f"No agent with identity {identity!r}")
    request_id = fi_db.ask_agent(conn, admin, identity, request.question)
    return {"request_id": request_id, "status": fi_db.UQI_PENDING}


@app.get("/admin/uqi/{request_id}")
def get_uqi_answer(request_id: int, conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """Poll one question for its answer.

    Expiry runs here rather than on a timer: the asker is the only party that
    needs the verdict, so it is computed when they look. An unanswered question
    is a real diagnostic result - the agent's process is not servicing its loop
    - and is reported as such rather than left pending forever."""
    fi_db.expire_stale_uqi_requests(conn)
    row = fi_db.get_uqi_request(conn, request_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No UQI request {request_id}")
    return {
        "request_id": row["id"],
        "target_identity": row["target_identity"],
        "asked_by": row["asked_by"],
        "question": row["question"],
        "status": row["status"],
        "answer": row["answer"],
        "answered_at": row["answered_at"],
        # Present only when a live process replied. Its absence on an answered
        # row would mean something wrote an answer without being an agent.
        "answered_by_pid": row["answered_by_pid"],
        "answered_by": "agent" if row["status"] == fi_db.UQI_ANSWERED else None,
    }


@app.get("/admin/uqi")
def list_uqi_history(limit: int = 25, conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """The audit trail §7 requires: every question asked and how it was
    answered, newest first."""
    return {"requests": fi_db.list_uqi_requests(conn, limit=limit)}


# --- Lifecycle control (addendum 11 §15, addendum 14 §7) ---
#
# The panel does NOT change lifecycle state. It files a directive, and the
# Controller's poll loop executes it - the same path COO's requests take.
#
# This is not ceremony. Addendum 11 §15 makes the Controller the *exclusive*
# executor of lifecycle actions, and a route that wrote lifecycle_state itself
# would make the backend a second executor, quietly ending that guarantee. It
# also happens to be the only correct option mechanically: Controller.conn
# belongs to the event-loop thread, so a request handler cannot drive it
# directly anyway.
#
# Filing a directive also buys auditability for free. Every action lands in
# coo_directives with who asked, why, and what outcome the Controller recorded.

class LifecycleRequest(BaseModel):
    reason: str


@app.post("/admin/agents/{identity}/retire")
def retire_agent(identity: str, request: LifecycleRequest, conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """Ask the Controller to stand this agent down.

    Non-destructive and reversible: the agent keeps its permanent identity,
    name, and entire history, and `resume` is the exact inverse. What stops is
    the process; what persists is the agent."""
    agent = _require_agent(conn, identity)
    if identity == CONTROLLER_IDENTITY:
        # The Controller *is* this server process. Retiring it would have the
        # backend ask its own poll loop to shut itself down - a genuinely
        # reachable footgun, since controller-1 appears in the roster like any
        # other agent and the panel offers the same button for every row.
        #
        # Compared against the role's fixed identity rather than a live
        # Controller's .identity: the two are always equal, and this way the
        # check needs no instance - so refusing to retire the Controller does not
        # depend on the server having constructed one.
        raise HTTPException(status_code=400, detail="The Controller cannot retire itself; stop the server instead")
    if agent["lifecycle_state"] == fi_db.LIFECYCLE_DORMANT:
        raise HTTPException(status_code=409, detail=f"{identity} is already dormant")

    directive_id = fi_db.enqueue_directive(
        conn, "retire", requested_by=admin,
        target_role=agent["role"], target_identity=identity, reason=request.reason,
    )
    return {"directive_id": directive_id, "status": "pending", "executed_by": "controller"}


@app.post("/admin/agents/{identity}/resume")
def resume_agent(identity: str, request: LifecycleRequest, conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """Ask the Controller to return this agent to service.

    Restores organizational standing only. The process comes back because COO's
    baseline check then sees an in-service role with nothing running and
    requests the spawn - the agent returns under the same permanent identity."""
    agent = _require_agent(conn, identity)
    if agent["lifecycle_state"] != fi_db.LIFECYCLE_DORMANT:
        raise HTTPException(status_code=409, detail=f"{identity} is not dormant")

    directive_id = fi_db.enqueue_directive(
        conn, "resume", requested_by=admin,
        target_role=agent["role"], target_identity=identity, reason=request.reason,
    )
    return {"directive_id": directive_id, "status": "pending", "executed_by": "controller"}


def _require_agent(conn, identity: str) -> dict:
    agent = fi_db.get_agent(conn, identity)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"No agent with identity {identity!r}")
    return agent


@app.get("/admin/incidents")
def list_incidents(limit: int = 50, conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """What stopped working, who noticed, and whether it came back (Fault
    Tolerance Framework §14).

    The framework's rule is that a noticed failure must acquire an owner, so the
    open and escalated counts are returned alongside the rows: an escalated
    incident is one a watcher could not resolve and handed upward, and it is the
    only thing here that is waiting on a person."""
    incidents = fi_db.list_incidents(conn, limit=limit)
    return {
        "incidents": incidents,
        "open": sum(1 for incident in incidents if incident["status"] == "open"),
        "escalated": sum(1 for incident in incidents if incident["status"] == "escalated"),
    }


@app.get("/admin/directives")
def list_directives(limit: int = 25, conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """Pending and recently completed lifecycle actions - who asked, why, and
    what the Controller made of it. The audit trail for everything the panel
    can cause."""
    pending = conn.fetchall("SELECT * FROM coo_directives ORDER BY id DESC LIMIT ?", (limit,))
    completed = conn.fetchall(
        "SELECT * FROM coo_directives_completed ORDER BY id DESC LIMIT ?", (limit,)
    )
    return {"pending": pending, "completed": completed}


# --- Mission control (addendum 25 SS4/SS22/SS23; docs/SPEC_RECONCILIATION.md
# SS39) ------------------------------------------------------------------
#
# The Market Data Simulation Engine's UI backend: what a mission-control
# panel would read (options, the mission list, one mission's pipeline
# progress) and the one action it would take (register a mission, evaluate
# one that has run). backend/missions.py owns the actual logic; these routes
# only translate its refusals into HTTP status codes.


@app.get("/admin/mission-options")
def mission_options(conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """What the interface's dropdowns are fed from - run modes, strategies,
    capable asset classes (backend/missions.py's mission_options)."""
    return missions.mission_options(conn)


@app.post("/admin/mission")
def start_mission(config: dict = Body(...), conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """Register (or retry) a mission.

    Authority note (comment, not a route): the server process itself - the
    Controller, addendum 21's orchestration layer - invokes the Market Data
    Simulation Engine directly here, the same docs/SPEC_RECONCILIATION.md
    SS40 disposition already used for the Reference Data Engine's startup
    invocation. COO-mediated mission orchestration is deferred until a
    mission actually needs agent-side sequencing - today's engine start is a
    synchronous database write, nothing a directive queue would improve.

    HTTP mapping: a run_mode other than 'simulation' (addendum 25 SS2's
    activation rule) and any other bad config both answer 400; an
    already-running or already-completed mission_id answers 409, since
    re-storing over it would silently discard real work; a mission blocked
    on reference data answers 200 with a WAITING_FOR_REFERENCE_DATA row -
    addendum 25 SS23 treats that as a successful, visible registration of a
    blocked mission, not an error - and so does an ordinary success."""
    try:
        return missions.start_mission(conn, config)
    except missions.ActivationRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except missions.MissionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/admin/missions")
def list_missions(conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """Every mission, newest request first, each with its own pipeline
    progress (addendum 25 SS22's dashboard numbers)."""
    return {
        "missions": [
            {**mission, "pipeline": missions.pipeline_counts(conn, mission["mission_id"])}
            for mission in missions.list_missions(conn)
        ]
    }


@app.get("/admin/mission/{mission_id}")
def get_mission(mission_id: str, conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """One mission's row, its pipeline progress, and its latest evaluation's
    per-scenario detail when one exists on disk - read directly rather than
    only from the cached metrics, so the panel can show the full scenario
    breakdown addendum 25 SS22 asks for, not only the summary numbers."""
    mission = missions.get_mission(conn, mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail=f"No mission with id {mission_id!r}")

    evaluation_scenarios = None
    evaluation_detail = None
    if mission["evaluation_path"]:
        try:
            evaluation_detail = json.loads(Path(mission["evaluation_path"]).read_text(encoding="utf-8"))
            evaluation_scenarios = evaluation_detail.get("scenarios")
        except FileNotFoundError:
            # Told rather than 500'd - the row still knows an evaluation ran,
            # even if the file backing it is gone (moved runs directory,
            # cleaned-up disk).
            evaluation_detail = None

    return {
        "mission": mission,
        "pipeline": missions.pipeline_counts(conn, mission_id),
        "evaluation_scenarios": evaluation_scenarios,
        "evaluation_file_missing": bool(mission["evaluation_path"]) and evaluation_detail is None,
    }


@app.post("/admin/mission/{mission_id}/evaluate")
def evaluate_mission_route(mission_id: str, conn=Depends(panel_db), admin: str = Depends(require_admin)):
    """Run the Evaluator and diagnosis stage over a stored mission (addendum
    25 SS16-SS19) and cache the result on its row.

    404 for a mission_id nobody ever registered; 409 for one that has - but
    has not yet stored a world, so there is no ground truth to grade
    against."""
    try:
        result = missions.evaluate(conn, mission_id)
    except missions.MissionNotStored as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail=f"No mission with id {mission_id!r}")
    return result
