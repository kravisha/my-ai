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
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from app import admin_auth
from app.audit import AuditLog
from app.main import SYSTEM_PROMPT
from app.model_gateway import call_reasoning_model
from app.permissions import RESOURCE_PATHS, PermissionManager
from app.privacy_preferences import PrivacyPreferenceStore
from app.session import SessionStore
from app.tools import TOOLS, execute_tool
from app.users import UserStore, ensure_user_data_dir, normalize_username
from backend import fi_db
from backend.controller import CONTROLLER_IDENTITY, Controller
from backend.transcripts import TranscriptStore

# How often the background loop below checks coo_directives for new work -
# see _controller_poll_loop. Same cadence as an agent's own heartbeat
# interval (agents/base.py), no reason for it to differ.
CONTROLLER_POLL_INTERVAL_SECONDS = 1.0


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
    controller = Controller()
    controller.bootstrap_self()
    # §10: a restarting process must not assume the world stayed frozen while it
    # was away. An unclean shutdown leaves the COO subprocess alive - children
    # outlive their parent - and the old unconditional spawn would have started a
    # second one under the same permanent identity.
    reconciliation = controller.reconcile_on_start()
    print(f"[controller] reconciled on start: {reconciliation}")
    controller.bootstrap_coo()
    poll_task = asyncio.create_task(_controller_poll_loop(controller))
    try:
        yield
    finally:
        poll_task.cancel()
        # Stop the workforce before stopping ourselves. subprocess children
        # outlive their parent, so without this a server stop left every agent
        # running and writing to the database - see Controller.shutdown_agents.
        outcome = controller.shutdown_agents()
        print(f"[controller] agents stopped: {outcome['stopped']}, terminated: {outcome['terminated']}")
        # A clean shutdown is a clean agent exit, not a crash - see
        # Controller.shutdown_self.
        controller.shutdown_self()
        controller.close()


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
        response = call_reasoning_model(SYSTEM_PROMPT, messages, TOOLS)
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
    return {"artifacts": artifacts}


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
        "SELECT a.*, g.overall_score, g.worth_the_compute, g.rationale AS grade_rationale "
        "FROM analysis_results a LEFT JOIN grades g ON g.analysis_result_id = a.id "
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
