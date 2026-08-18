"""The AI Communication Gateway (addenda 16 and 17), increments G1 and G3.

**A separate service, on its own port, in its own process.** Addendum 16 §7 says
the Gateway must be the only externally exposed Jarvis service and that external
clients must not reach internal APIs, Controller, agents or databases. Adding
these routes to `backend/main.py` would have meant exposing every internal and
`/admin` route on the same port the phone talks to, which is the arrangement §7
exists to forbid. §22 wants it able to run while the rest of the system is under
construction, and §23 wants it usable when internal components are down - both of
which a second process gets for free and an added router does not.

It is a *client* of Jarvis, not part of it: the same shape as `agents/coo.py`,
`panel/app.py` and `monitor/app.py`, all of which are separate processes talking
HTTP to the backend. The project's "SQLite is the only IPC" rule governs agents
and is untouched here - the Gateway is not an agent, is not spawned by the
Controller, and outlives the organization's absence.

What exists: the boundary, Super User authentication, a streaming conversation
with the analysis model persisted so a reconnect resumes it (G1), and the Project
Scoreboard - both as REST for programmatic producers and as tools the assistant
calls mid-conversation, which is addendum 16 §10's one-hop requirement applied to
the board itself (G3). What does not: voice, Git, and any call into the backend
at all. This service still does not touch the rest of Jarvis.

Run it with:

    uvicorn gateway.main:app --port 8100

Nothing is constructed at import - the database is opened in `lifespan`, the
lesson `tests/test_db_isolation.py` was written to keep.
"""

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.model_gateway import default_provider
from gateway import auth, conversation, jarvis, scoreboard, store
from gateway.streaming import iterate_in_thread

logger = logging.getLogger("gateway")

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Request validation (addendum 16 §12). A conversational turn has no legitimate
# reason to be book-length, and the limit is what stops an unbounded body from
# becoming an unbounded model call.
MAX_MESSAGE_CHARS = 20_000

# WebSocket close codes. 4401 rather than 1008 so the client can distinguish
# "your session is over, log in again" from any other protocol failure; the 44xx
# range is application-defined.
WS_UNAUTHORIZED = 4401
WS_BAD_REQUEST = 4400


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Owns the database for the life of the server.

    Schema creation and the expired-session sweep happen here, not at import, so
    that importing this module - for a test, a doc build, a `--help` - creates
    nothing on disk."""
    conn = store.get_connection()
    store.init_schema(conn)
    purged = store.purge_expired_sessions(conn)
    if purged:
        logger.info("purged %d expired session(s)", purged)
    if not auth.is_configured():
        logger.warning(auth.NOT_CONFIGURED_MESSAGE)
    app.state.db = conn
    try:
        yield
    finally:
        conn.close()


app = FastAPI(title="AI Communication Gateway", lifespan=lifespan)


async def gateway_db_path():
    """Which database file this request works against.

    Separate from the connection because a turn's tool calls run on a worker
    thread and have to open their own connection there (see
    gateway/conversation.py) - handing that thread a path is the only safe thing
    to hand it. It is also the single point a test redirects."""
    return store.DB_PATH


async def gateway_db(db_path=Depends(gateway_db_path)):
    """The Gateway's database connection.

    Async on purpose. FastAPI runs *synchronous* dependencies in a worker
    threadpool, and sqlite3 connections are bound to the thread that opened them
    - so a sync dependency feeding an async WebSocket handler would hand it a
    connection from the wrong thread. Declaring it async keeps creation and use
    on the event loop thread together.

    One connection per request rather than sharing `app.state.db`: the lifespan
    connection is opened on the startup task's thread, which is not necessarily
    this one, and SQLite in WAL mode makes a second reader cheap."""
    conn = store.get_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_at: str


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return authorization.split(" ", 1)[1].strip()


async def require_session(
    authorization: str | None = Header(default=None), conn=Depends(gateway_db)
) -> str:
    token = _bearer_token(authorization)
    if not store.session_is_valid(conn, token):
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    return token


@app.get("/health")
async def health():
    """Deliberately says nothing about Jarvis. This is the external boundary's own
    liveness, and an unauthenticated caller learns only that a Gateway is here and
    whether its operator has finished configuring it."""
    return {"status": "ok", "configured": auth.is_configured()}


@app.get("/")
async def index():
    """The Super User client (addendum 16 §8: a phone-accessible web client, no
    native app required). Read per request rather than cached at import so that
    editing the page does not require a restart."""
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


@app.post("/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest, conn=Depends(gateway_db)):
    """503 when no Super User is configured, 401 when the credential is wrong.

    Those are different situations and an operator who conflates them will spend
    the evening retyping a correct password. It is not an information leak worth
    avoiding: an unconfigured Gateway refuses everything either way."""
    if not auth.is_configured():
        logger.warning("login attempt against an unconfigured Gateway")
        raise HTTPException(status_code=503, detail=auth.NOT_CONFIGURED_MESSAGE)

    if not auth.verify(request.username, request.password):
        logger.warning("failed Super User login for %r", request.username)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token, expires_at = store.create_session(conn, auth.session_ttl_seconds())
    logger.info("Super User logged in, session expires %s", expires_at)
    return {"token": token, "expires_at": expires_at}


@app.post("/auth/logout")
async def logout(token: str = Depends(require_session), conn=Depends(gateway_db)):
    store.delete_session(conn, token)
    return {"status": "logged out"}


class ItemRequest(BaseModel):
    question: str
    importance: str = "informational"
    blocking: bool = False
    related_spec: str | None = None
    related_component: str | None = None
    source: str | None = None


class NoteRequest(BaseModel):
    note: str
    author: str | None = None


class ResolveRequest(BaseModel):
    resolution: str


@app.get("/scoreboard")
async def list_scoreboard(
    status: str | None = None,
    importance: str | None = None,
    limit: int = 50,
    _: str = Depends(require_session),
    conn=Depends(gateway_db),
):
    try:
        items = scoreboard.list_items(conn, status=status, importance=importance, limit=limit)
    except scoreboard.ScoreboardError as refusal:
        raise HTTPException(status_code=400, detail=str(refusal))
    return {"items": items, "open_counts": scoreboard.open_counts(conn)}


@app.post("/scoreboard", status_code=201)
async def file_scoreboard_item(
    request: ItemRequest, _: str = Depends(require_session), conn=Depends(gateway_db)
):
    """The programmatic way in, for producers that are not the conversation.

    `source` is the caller's own attribution and defaults to "api". Addendum 17
    §6 has Jarvis departments publishing findings into the Gateway rather than
    inventing their own notification channels; this is the route they will use,
    and it is honest for a caller holding the Super User session to name itself.
    The assistant's tool has no such parameter - see gateway/tools.py."""
    try:
        item_id = scoreboard.file_item(
            conn,
            source=request.source or "api",
            question=request.question,
            importance=request.importance,
            blocking=request.blocking,
            related_spec=request.related_spec,
            related_component=request.related_component,
        )
    except scoreboard.ScoreboardError as refusal:
        raise HTTPException(status_code=400, detail=str(refusal))
    return scoreboard.get_item(conn, item_id)


@app.get("/scoreboard/{item_id}")
async def get_scoreboard_item(
    item_id: int, _: str = Depends(require_session), conn=Depends(gateway_db)
):
    item = scoreboard.get_item(conn, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"No Scoreboard item {item_id}")
    return item


@app.post("/scoreboard/{item_id}/notes", status_code=201)
async def add_scoreboard_note(
    item_id: int,
    request: NoteRequest,
    _: str = Depends(require_session),
    conn=Depends(gateway_db),
):
    try:
        scoreboard.add_note(conn, item_id, author=request.author or "api", note=request.note)
    except scoreboard.ScoreboardError as refusal:
        raise HTTPException(status_code=400, detail=str(refusal))
    return scoreboard.get_item(conn, item_id)


@app.post("/scoreboard/{item_id}/resolve")
async def resolve_scoreboard_item(
    item_id: int,
    request: ResolveRequest,
    _: str = Depends(require_session),
    conn=Depends(gateway_db),
):
    try:
        return scoreboard.resolve_item(conn, item_id, request.resolution)
    except scoreboard.ScoreboardError as refusal:
        raise HTTPException(status_code=400, detail=str(refusal))


@app.get("/status")
async def jarvis_status(_: str = Depends(require_session)):
    """Project-wide status visibility (addendum 17 §4), and the §23 promise in
    one route: when the backend is down this answers 200 with available=false and
    a reason, never 5xx. The Gateway's own liveness is not contingent on the
    system it looks at."""
    return jarvis.JarvisClient().status()


@app.websocket("/ws")
async def conversation_socket(
    websocket: WebSocket, conn=Depends(gateway_db), db_path=Depends(gateway_db_path)
):
    """The conversation transport (addendum 16 §11: HTTPS for normal operations,
    WebSockets for real-time streaming).

    **The token arrives as the first message, not in the URL.** Browsers cannot
    set headers on a WebSocket handshake, and the usual workaround - a query
    parameter - writes the credential into server logs, proxy logs and browser
    history. One extra round trip avoids all three.

    Protocol, client to server:
        {"type": "auth", "token": "..."}      once, first
        {"type": "message", "text": "..."}    thereafter

    Server to client:
        {"type": "ready", "conversation_id": N, "messages": [...]}
        {"type": "delta", "text": "..."}      many, as the reply arrives
        {"type": "done", "message_id": N}
        {"type": "error", "error": "..."}
    """
    await websocket.accept()

    try:
        opening = await websocket.receive_text()
    except WebSocketDisconnect:
        return

    try:
        payload = json.loads(opening)
    except json.JSONDecodeError:
        await websocket.close(code=WS_BAD_REQUEST)
        return

    token = payload.get("token") if payload.get("type") == "auth" else None
    if not token or not store.session_is_valid(conn, token):
        logger.warning("unauthenticated WebSocket attempt")
        await websocket.send_json({"type": "error", "error": "unauthorized"})
        await websocket.close(code=WS_UNAUTHORIZED)
        return

    conversation_id = store.current_conversation_id(conn)
    await websocket.send_json({
        "type": "ready",
        "conversation_id": conversation_id,
        "messages": store.history(conn, conversation_id),
        "open_counts": scoreboard.open_counts(conn),
    })

    provider = default_provider()

    while True:
        try:
            raw = await websocket.receive_text()
        except WebSocketDisconnect:
            return

        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            await websocket.send_json({"type": "error", "error": "malformed message"})
            continue

        if message.get("type") != "message":
            await websocket.send_json({"type": "error", "error": "unknown message type"})
            continue

        text = (message.get("text") or "").strip()
        if not text:
            await websocket.send_json({"type": "error", "error": "empty message"})
            continue
        if len(text) > MAX_MESSAGE_CHARS:
            await websocket.send_json({"type": "error", "error": "message too long"})
            continue

        # The session is re-checked every turn, not only at connection. A socket
        # opened before expiry would otherwise stay privileged indefinitely,
        # which is the same bug as a session that never expires.
        if not store.session_is_valid(conn, token):
            logger.warning("revoked or expired session attempted to continue a conversation")
            await websocket.send_json({"type": "error", "error": "unauthorized"})
            await websocket.close(code=WS_UNAUTHORIZED)
            return

        conversation.record_user_message(conn, conversation_id, text)
        history = store.history(conn, conversation_id)

        said: list[str] = []
        reply = None
        try:
            async for event in iterate_in_thread(
                lambda: conversation.run_turn(db_path, history, provider)
            ):
                if event["type"] == "text":
                    said.append(event["text"])
                    await websocket.send_json({"type": "delta", "text": event["text"]})
                elif event["type"] == "tool":
                    # Surfaced rather than hidden: a turn that files something on
                    # the Scoreboard has done something durable, and the user
                    # should see that it happened while it happens.
                    await websocket.send_json(
                        {"type": "tool", "name": event["name"], "ok": event["ok"]}
                    )
                elif event["type"] == "reply":
                    reply = event["text"]
        except WebSocketDisconnect:
            # The user closed the tab mid-reply. Keep what arrived: a partial
            # answer is still part of the conversation, and discarding it would
            # leave a user turn with no reply at all on reconnect.
            if said:
                conversation.record_assistant_message(conn, conversation_id, "".join(said))
            return
        except Exception as exc:  # noqa: BLE001 - reported to the client, not swallowed
            logger.exception("model turn failed")
            if said:
                conversation.record_assistant_message(conn, conversation_id, "".join(said))
            await websocket.send_json({"type": "error", "error": f"model error: {exc}"})
            continue

        # `reply` is what the turn says it said; `said` is what actually went down
        # the socket. They agree unless the turn ended early, and then the
        # transcript should match what the user saw.
        answer = reply if reply is not None else "".join(said)
        message_id = (
            conversation.record_assistant_message(conn, conversation_id, answer) if answer else None
        )
        await websocket.send_json({
            "type": "done",
            "message_id": message_id,
            "open_counts": scoreboard.open_counts(conn),
        })
