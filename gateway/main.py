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

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app import model_budget
from app.model_gateway import default_provider
from gateway import auth, client_agent, conversation, exposure, jarvis, roles, scoreboard, store, technology
from gateway.streaming import iterate_in_thread

logger = logging.getLogger("gateway")

STATIC_DIR = Path(__file__).resolve().parent / "static"

# The desktop console's own page, served unchanged to an operator who comes in
# through the Gateway (TQ-34, §92). Referenced, never copied: two files would be
# two consoles, which is the duplication addendum 40 §13.1 forbids.
CONSOLE_HTML = Path(__file__).resolve().parent.parent / "backend" / "console" / "index.html"

# Request validation (addendum 16 §12). A conversational turn has no legitimate
# reason to be book-length, and the limit is what stops an unbounded body from
# becoming an unbounded model call.
MAX_MESSAGE_CHARS = 20_000

# A ceiling on what the studio may push through the Gateway. The workspace has
# its own 256KB limit on the backend; this is the doorway's own refusal, because
# a boundary that relies on the thing behind it to enforce a limit is not a
# boundary.
MAX_STUDIO_BODY_BYTES = 512 * 1024

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
    # This process's model spend is the Gateway's (TQ-18, §66) - declared in
    # lifespan rather than at import, so importing this module still creates
    # and changes nothing.
    model_budget.set_caller("gateway")
    conn = store.get_connection()
    store.init_schema(conn)
    purged = store.purge_expired_sessions(conn)
    if purged:
        logger.info("purged %d expired session(s)", purged)
    if not auth.is_configured():
        logger.warning(auth.NOT_CONFIGURED_MESSAGE)
    app.state.db = conn

    reviewer = asyncio.create_task(_technology_review_loop())
    try:
        yield
    finally:
        reviewer.cancel()
        conn.close()


async def _technology_review_loop() -> None:
    """The periodic half of addendum 17 §7, at the cadence §7 asks for: low.

    Each pass opens its own connection, because this task outlives no request and
    shares no thread with one. The whole body is defensive - a review that raised
    would take the task with it and the function would stop existing silently,
    which is the failure mode a monitoring component can least afford."""
    interval_hours = technology.review_interval_hours()
    if interval_hours <= 0:
        logger.info("technology review disabled (%s=0)", technology.REVIEW_INTERVAL_ENV)
        return

    while True:
        await asyncio.sleep(interval_hours * 3600)
        try:
            # One crossing, not two. Opening the connection here and handing it to
            # a worker thread raised sqlite3's thread-affinity error on every pass
            # - survivably, because of the catch below, and therefore silently.
            report, filed = await asyncio.to_thread(technology.review_and_file, store.DB_PATH)
            logger.info(
                "technology review: %s; filed %d item(s)",
                report["counts"],
                len([f for f in filed if "item_id" in f and "skipped" not in f]),
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a failed review must not end the loop
            logger.exception("technology review failed; will try again next interval")


app = FastAPI(title="AI Communication Gateway", lifespan=lifespan)

# One limiter for the whole process, covering both ways a credential can be
# offered: the login route and the WebSocket's opening frame. Limiting only the
# route would leave the socket as an unlimited oracle for guessing tokens.
login_limiter = exposure.AttemptLimiter(
    limit=exposure.login_attempt_limit(), window_seconds=exposure.login_window_seconds()
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Headers for a service reachable from the internet (addendum 16 §12).

    HSTS is sent only when the request actually arrived over TLS - behind the
    tunnel that is `X-Forwarded-Proto: https`. Announcing it on a plain HTTP
    response is how a developer locks themselves out of their own localhost."""
    response = await call_next(request)
    for header, value in exposure.SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)

    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    if request.url.scheme == "https" or forwarded_proto == "https":
        response.headers.setdefault(*exposure.HSTS_HEADER)
    return response


def caller_address(request: Request | WebSocket) -> str:
    """Who to hold responsible for this attempt - see gateway/exposure.py for why
    the forwarded header is only believed from a declared proxy."""
    peer = request.client.host if request.client else None
    return exposure.client_address(peer, request.headers.get("x-forwarded-for"))


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
    # Returned so a client can render what it actually has rather than
    # discovering its limits one 403 at a time (TQ-34, §92).
    role: str
    capabilities: list[str]


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


def require(capability: str):
    """A dependency that admits only roles holding `capability` (TQ-34, §92).

    Addendum 40 §14: "The presentation layer must never bypass backend
    authorization just because information exists on the server." So the check
    is here, on the route, and holds whether or not any interface ever offered
    the caller a way to ask.

    401 and 403 are kept apart deliberately. "Log in again" and "your role does
    not include this" send an operator down entirely different paths, and
    collapsing them to be coy about which is true would cost more in confusion
    than it buys in secrecy - the caller already authenticated, so they learn
    nothing about the credential from being told about the grant.

    The capability is validated at import, not per request: a mistyped
    requirement must fail the suite rather than quietly refuse everybody."""
    if capability not in roles.CAPABILITIES:
        raise roles.UnknownCapability(
            f"route declares unknown capability {capability!r}; "
            f"declared capabilities are {list(roles.CAPABILITIES)}")

    async def dependency(
        authorization: str | None = Header(default=None), conn=Depends(gateway_db)
    ) -> str:
        token = _bearer_token(authorization)
        role = store.session_role(conn, token)
        if role is None:
            raise HTTPException(status_code=401, detail="Session expired or invalid")
        if not roles.allows(role, capability):
            logger.warning("role %r refused %r", role, capability)
            raise HTTPException(
                status_code=403,
                detail=f"Your role ({role}) does not include the ability to "
                       f"{roles.DESCRIPTIONS[capability]}.",
            )
        return token

    return dependency


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
async def login(request: LoginRequest, http_request: Request, conn=Depends(gateway_db)):
    """503 when no Super User is configured, 401 when the credential is wrong.

    Those are different situations and an operator who conflates them will spend
    the evening retyping a correct password. It is not an information leak worth
    avoiding: an unconfigured Gateway refuses everything either way."""
    caller = caller_address(http_request)
    if login_limiter.is_blocked(caller):
        retry_after = login_limiter.retry_after_seconds(caller)
        logger.warning("rate-limited login attempt from %s", caller)
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    if not auth.is_configured():
        logger.warning("login attempt against an unconfigured Gateway from %s", caller)
        raise HTTPException(status_code=503, detail=auth.NOT_CONFIGURED_MESSAGE)

    role = auth.identify(request.username, request.password)
    if role is None:
        # Counted, and logged with the address, because on a service reachable
        # from the internet "somebody guessed wrong" and "somebody is guessing"
        # are different events and only the count tells them apart.
        failures = login_limiter.record_failure(caller)
        logger.warning(
            "failed Super User login for %r from %s (%d in the current window)",
            request.username,
            caller,
            failures,
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")

    login_limiter.record_success(caller)
    token, expires_at = store.create_session(
        conn, auth.session_ttl_seconds(), role, subject=request.username.strip().lower())
    logger.info("%s logged in from %s, session expires %s", role, caller, expires_at)
    return {"token": token, "expires_at": expires_at, "role": role,
            "capabilities": sorted(roles.capabilities(role))}


@app.post("/auth/logout")
async def logout(token: str = Depends(require(roles.CAP_SESSION)), conn=Depends(gateway_db)):
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
    _: str = Depends(require(roles.CAP_SCOREBOARD_READ)),
    conn=Depends(gateway_db),
):
    try:
        items = scoreboard.list_items(conn, status=status, importance=importance, limit=limit)
    except scoreboard.ScoreboardError as refusal:
        raise HTTPException(status_code=400, detail=str(refusal))
    return {"items": items, "open_counts": scoreboard.open_counts(conn)}


@app.post("/scoreboard", status_code=201)
async def file_scoreboard_item(
    request: ItemRequest, _: str = Depends(require(roles.CAP_SCOREBOARD_WRITE)), conn=Depends(gateway_db)
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
    item_id: int, _: str = Depends(require(roles.CAP_SCOREBOARD_READ)), conn=Depends(gateway_db)
):
    item = scoreboard.get_item(conn, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"No Scoreboard item {item_id}")
    return item


@app.post("/scoreboard/{item_id}/notes", status_code=201)
async def add_scoreboard_note(
    item_id: int,
    request: NoteRequest,
    _: str = Depends(require(roles.CAP_SCOREBOARD_WRITE)),
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
    _: str = Depends(require(roles.CAP_SCOREBOARD_WRITE)),
    conn=Depends(gateway_db),
):
    try:
        return scoreboard.resolve_item(conn, item_id, request.resolution)
    except scoreboard.ScoreboardError as refusal:
        raise HTTPException(status_code=400, detail=str(refusal))


@app.get("/status")
async def jarvis_status(_: str = Depends(require(roles.CAP_SYSTEM_STATUS))):
    """Project-wide status visibility (addendum 17 §4), and the §23 promise in
    one route: when the backend is down this answers 200 with available=false and
    a reason, never 5xx. The Gateway's own liveness is not contingent on the
    system it looks at."""
    return jarvis.JarvisClient().status()


@app.get("/technology")
async def technology_review(
    file_findings: bool = False,
    _: str = Depends(require(roles.CAP_TECHNOLOGY_READ)),
    conn=Depends(gateway_db),
):
    """The Technology and Architecture review on demand (addendum 17 §7-§9).

    `file_findings` is opt-in even here: reading the review is a question, and
    putting items on the Super User's board is an act."""
    report = technology.review()
    if file_findings:
        report["filed"] = technology.file_findings(conn, report)
    return report


# The studio's read endpoints, as an allowlist rather than a wildcard.
#
# A proxy that forwarded whatever path a browser asked for would be a tunnel
# straight through the boundary addendum 16 §7 draws - the backend is
# loopback-only precisely so that nothing external can reach its admin surface,
# and "the Gateway forwards /console/*" is one path-traversal away from "the
# Gateway forwards anything". Named paths cost a line each and cannot be
# talked into forwarding something else.
STUDIO_READS = frozenset({
    "feed", "overview", "finance", "chatterbox", "languages", "identity",
    "briefing", "workspace",
})


@app.get("/studio")
async def studio():
    """The same studio the desktop console shows (addendum 40 §13.1, §92).

    Literally the same file - `backend/console/index.html`, not a copy - so the
    Gateway cannot drift into being a second, subtly different command centre.
    Addendum 41 §23's "COO / operator: Full studio", and 40 §13.1's "must never
    create a duplicate COO, duplicate organization, or independent source of
    truth", both satisfied by serving one page from one place.

    **Unauthenticated, and deliberately - this is the empty shell, not the
    view.** The first version required `studio` here and was unreachable: a
    top-level browser navigation cannot carry an `Authorization` header, so
    clicking through to the studio produced a 401 and a blank page. The
    alternatives are a token in the query string, which this codebase already
    rejected for the WebSocket because it writes credentials into server logs
    and browser history, or a session cookie, which is a larger change to the
    auth model than one page warrants.

    So the page is served the way `/` already is: it contains no organizational
    data at all - every byte of that arrives through `/console/*`, which *is*
    gated on `studio`. An anonymous visitor gets markup and a redirect to the
    login page, which is what they would have got from `/` anyway.

    That is the §14 line drawn where it belongs. The rule is that the
    presentation layer must never bypass backend authorization; it is not that
    markup must be secret."""
    return FileResponse(CONSOLE_HTML, media_type="text/html; charset=utf-8")


@app.get("/console/{surface}")
async def studio_read(surface: str, _: str = Depends(require(roles.CAP_STUDIO))):
    """One of the studio's reads, forwarded to the backend that owns it.

    The page fetches these paths whether it is served by the backend or by the
    Gateway, so the same file works behind both doors without knowing which one
    it came through."""
    if surface not in STUDIO_READS:
        raise HTTPException(status_code=404, detail="No such studio surface")
    status, body = jarvis.JarvisClient().console(f"/console/{surface}")
    if status != 200:
        # Reported rather than raised: the console renders an unreachable
        # backend as a state it knows about, and a 502 here would blank a page
        # that is perfectly capable of saying "backend unreachable — retrying".
        return {"available": False, "unavailable": True,
                "reason": f"The backend answered {status} for /console/{surface}."}
    return body


@app.put("/console/workspace")
async def studio_workspace_save(request: Request, _: str = Depends(require(roles.CAP_STUDIO))):
    """The studio's checkpoint, forwarded (addendum 40 §5.1).

    Needed rather than optional: the page checkpoints continuously, so a Gateway
    that served the studio but refused its writes would drop a half-typed
    question every time - §5.3's one unambiguous requirement, broken by the
    door rather than by the feature."""
    body = await request.body()
    if len(body) > MAX_STUDIO_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Workspace payload too large")
    status, payload = jarvis.JarvisClient().console_write("/console/workspace", body, method="PUT")
    if status != 200:
        raise HTTPException(status_code=502, detail=f"The backend answered {status}.")
    return payload


@app.post("/console/chat")
async def studio_chat(request: Request, _: str = Depends(require(roles.CAP_STUDIO))):
    """Kumbhakarnan, through the Gateway's door instead of the desktop's.

    Streamed straight through rather than buffered, because the whole point of
    the console's chat is that it can be interrupted mid-sentence (addendum 41
    §9) - and a proxy that collected the answer before forwarding it would turn
    a conversation into a wait.

    `iterate_in_thread` exists for exactly this shape: a blocking generator
    feeding an async socket without occupying the event loop."""
    body = await request.body()
    if len(body) > MAX_STUDIO_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Question too large")
    client = jarvis.JarvisClient()
    return StreamingResponse(
        iterate_in_thread(lambda: client.console_stream("/console/chat", body)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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

    caller = caller_address(websocket)
    if login_limiter.is_blocked(caller):
        logger.warning("rate-limited WebSocket attempt from %s", caller)
        await websocket.send_json({"type": "error", "error": "too many attempts"})
        await websocket.close(code=WS_UNAUTHORIZED)
        return

    token = payload.get("token") if payload.get("type") == "auth" else None
    role = store.session_role(conn, token) if token else None
    if not token or role is None or not roles.allows(role, roles.CAP_CONVERSE):
        # The same counter as the login route. A socket that accepted unlimited
        # token guesses would be an oracle sitting beside a rate-limited door.
        failures = login_limiter.record_failure(caller)
        logger.warning(
            "unauthenticated WebSocket attempt from %s (%d in the current window)",
            caller,
            failures,
        )
        await websocket.send_json({"type": "error", "error": "unauthorized"})
        await websocket.close(code=WS_UNAUTHORIZED)
        return

    login_limiter.record_success(caller)

    # Scoped to whoever logged in (TQ-39, §93). This used to be the newest
    # conversation in the database regardless of who asked, which handed a
    # client the operator's transcript in this very frame.
    subject = store.session_subject(conn, token)
    if subject is None:
        await websocket.send_json({"type": "error", "error": "unauthorized"})
        await websocket.close(code=WS_UNAUTHORIZED)
        return

    conversation_id = store.current_conversation_id(conn, subject)
    ready = {
        "type": "ready",
        "conversation_id": conversation_id,
        "messages": store.history(conn, conversation_id),
        # What this session may actually do, sent once so the client can render
        # itself honestly rather than offering controls that will 403.
        "role": role,
        "capabilities": sorted(roles.capabilities(role)),
    }
    # The open counts are a scoreboard read, so they travel only to a role that
    # holds one. A client meeting their agent has no business receiving a
    # summary of the operator's decision board in the handshake - which is
    # exactly the "information exists on the server" reasoning §14 forbids.
    if roles.allows(role, roles.CAP_SCOREBOARD_READ):
        ready["open_counts"] = scoreboard.open_counts(conn)

    # Addendum 43 §16: a client meets a named representative rather than a
    # search box with manners. The greeting is recorded state, not a phrase -
    # a returning client is greeted as one because `meetings` says so.
    agent_name = None
    if role == roles.ROLE_CLIENT:
        agent = client_agent.greet(conn, subject)
        agent_name = agent["name"]
        ready["agent"] = {
            "name": agent["name"],
            "since": agent["created_at"],
            "returning": agent["returning"],
            "meetings": agent["meetings"],
            "voice": agent["voice"],
            "visual": agent["visual"],
        }
        ready["introduction"] = client_agent.introduction(agent)

    await websocket.send_json(ready)

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
                lambda: conversation.run_turn(db_path, history, provider, role=role,
                                          subject=subject, agent_name=agent_name)
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
