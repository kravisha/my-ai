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

from app.audit import AuditLog
from app.main import SYSTEM_PROMPT
from app.model_gateway import call_reasoning_model
from app.permissions import RESOURCE_PATHS, PermissionManager
from app.privacy_preferences import PrivacyPreferenceStore
from app.session import SessionStore
from app.tools import TOOLS, execute_tool
from app.users import UserStore, ensure_user_data_dir, normalize_username
from backend import fi_db
from backend.controller import Controller
from backend.transcripts import TranscriptStore

# How often the background loop below checks coo_directives for new work -
# see _controller_poll_loop. Same cadence as an agent's own heartbeat
# interval (agents/base.py), no reason for it to differ.
CONTROLLER_POLL_INTERVAL_SECONDS = 1.0

controller = Controller()
_controller_poll_task: asyncio.Task | None = None


async def _controller_poll_loop() -> None:
    """Stands in for what a human would otherwise have to trigger by hand:
    repeatedly calls process_next_directive() so COO's spawn/retire requests
    (rows in coo_directives) actually get acted on. Runs as a plain asyncio
    task in this process's own event loop - the Controller itself is not a
    separate process, it lives inside the backend engine (confirmed process
    model), so this needs no subprocess or IPC of its own."""
    while True:
        controller.record_self_heartbeat()
        controller.process_next_directive()
        await asyncio.sleep(CONTROLLER_POLL_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The startup sequence the specs give literally (Consolidated §2, Org
    # Addendum §13): server starts -> Controller Agent starts (registering
    # itself as the first agent - it *is* this server process) -> Controller
    # creates COO. Every agent COO wants after this goes through the normal
    # directive queue, picked up by the poll loop above.
    global _controller_poll_task
    controller.bootstrap_self()
    controller.bootstrap_coo()
    _controller_poll_task = asyncio.create_task(_controller_poll_loop())
    try:
        yield
    finally:
        _controller_poll_task.cancel()
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
def list_clients():
    return {"clients": transcripts.list_clients()}


@app.get("/admin/clients/{username}/transcript")
def get_client_transcript(username: str):
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
def list_agents(conn=Depends(panel_db)):
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
def describe_agent(identity: str, conn=Depends(panel_db)):
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
def list_intelligence(conn=Depends(panel_db)):
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


@app.get("/admin/regime")
def market_regime(conn=Depends(panel_db)):
    """The system's current estimate of market conditions, per security and
    aggregated. This is an estimate the system inferred from observation - it
    was never told the regime the provider generates under."""
    return {
        "securities": fi_db.list_market_regime(conn),
        "market_wide": fi_db.current_market_characterization(conn),
    }


@app.get("/admin/cross-checks")
def list_cross_checks(limit: int = 25, conn=Depends(panel_db)):
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
def discovery_activity(limit: int = 25, conn=Depends(panel_db)):
    """What the discovery slice has actually produced: the pending queue, and
    the most recent analyses with their grades."""
    results = conn.fetchall(
        "SELECT a.*, g.overall_score, g.worth_the_compute, g.rationale AS grade_rationale "
        "FROM analysis_results a LEFT JOIN grades g ON g.analysis_result_id = a.id "
        "ORDER BY a.id DESC LIMIT ?", (limit,)
    )
    return {
        "pending_reports": conn.fetchall(
            "SELECT id, created_at, producer_identity, report_type, security, summary, cross_check_id "
            "FROM discovery_reports ORDER BY id"
        ),
        "recent_analyses": results,
        "performance_card": fi_db.get_performance_card(conn),
    }
