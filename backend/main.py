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

import json
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

app = FastAPI(title="My AI Backend")
users = UserStore()
sessions = SessionStore()


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
    """
    permissions, preferences, audit_log = build_stores(username)
    messages = [m.model_dump() for m in request.messages]

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
