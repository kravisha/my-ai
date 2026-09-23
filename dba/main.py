"""The DBA as a service (§2.1, §2.2, and §49's open transport question).

    *"The DBA must run as its own agent or service. It must not be embedded as
    hidden database logic inside JARVIS."*

Run it with:

    uvicorn dba.main:app --port 8200

## Why HTTP, which §49 left open

This repository already runs two FastAPI services on their own ports, and
`agents/coo.py`, `panel/app.py` and `monitor/app.py` are all separate processes
speaking HTTP. A message bus would be a new dependency, a new failure mode and
a new thing to operate, for a system whose entire traffic is one assistant
talking to one database. A local socket would be cheaper still and would not
survive the first time Krish wants to reach this from his phone, which is a
thing that has already happened once in this project.

So: HTTP on a port, with the same shape as the Gateway.

## Identity is asserted by a token, not by the body

`requested_by` in the body says which agent is asking. On its own that is a
claim, and §14's whole point is that the DBA enforces access control rather
than trusting it. So the caller also presents `X-DBA-Agent` and `X-DBA-Token`,
the token is checked against `DBA_TOKEN_<AGENT>` in the environment, and the
body's `requested_by` must agree with the header. An agent with no configured
token cannot call this service at all - which means a fresh checkout refuses
everything until somebody deliberately configures a caller, the same posture
`gateway/roles.py` takes about its unconfigured roles.

Nothing is constructed at import. The database is opened per request.
"""

from __future__ import annotations

import hmac
import os
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from dba import agent as agent_module
from dba import contract, entities, explain, health, permissions, tamil

TOKEN_PREFIX = "DBA_TOKEN_"


def token_env_var(agent: str) -> str:
    """The environment variable holding one agent's token."""
    return f"{TOKEN_PREFIX}{agent.upper()}"


def _authenticate(agent: str | None, token: str | None) -> str:
    if not agent or not token:
        raise HTTPException(
            status_code=401,
            detail="X-DBA-Agent and X-DBA-Token are both required. The DBA "
                   "enforces access control rather than trusting the body.")
    if not permissions.known_agent(agent):
        raise HTTPException(
            status_code=403,
            detail=f"{agent!r} is not an agent this system's policy knows.")
    expected = (os.environ.get(token_env_var(agent), "") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=f"no token is configured for {agent!r}. Set "
                   f"{token_env_var(agent)} to enable it. The service refuses "
                   f"rather than defaulting to open.")
    # Constant-time, because a token compared with == leaks its prefix to
    # anything that can time the response.
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="that token is not valid.")
    return agent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the backup scheduler with the service, stop it with the service.

    THE DBA TAKES ITS OWN BACKUPS. Krish's correction, and he is right: an
    agent whose job is that persistent information is safe, and which needs
    somebody else to remember to run it, is not keeping anything safe.

    Nothing else is constructed here - the database is opened per request, the
    lesson `tests/test_db_isolation.py` exists to keep."""
    from app import crashlog, eventlog
    from dba import scheduler

    # The same pair the Gateway arms, for the same reason: this service runs
    # hidden and unattended, and a thread that dies silently in it is a backup
    # that has stopped happening.
    crashlog.install("dba")
    crashlog.breadcrumb("dba")

    # The same event log the Gateway writes to, tagged with this service. One
    # file for the whole system: a fault Jarvis is investigating usually spans
    # both processes, and two files would make "what happened at 02:14" a
    # question needing a join.
    eventlog.install("dba")

    scheduler.start()
    try:
        yield
    finally:
        scheduler.stop()


app = FastAPI(title="DBA Agent", lifespan=lifespan)


def _install_routes() -> None:
    """The capability routes live in `dba/routes.py` and are attached here.

    Imported inside a function rather than at module scope because that module
    imports this one back - for `_authenticate` and `_http_status`, which must
    be the same check and the same mapping rather than a second copy that
    drifts."""
    from dba import routes

    app.include_router(routes.router)


_install_routes()


@app.post("/request")
def handle_request(payload: dict = Body(...),
                   x_dba_agent: str | None = Header(default=None),
                   x_dba_token: str | None = Header(default=None)):
    """One structured request (§8), one structured response (§42)."""
    agent = _authenticate(x_dba_agent, x_dba_token)
    request = _build(payload, agent)
    response = agent_module.default_agent().handle(request)
    return JSONResponse(status_code=_http_status(response),
                        content=_body(response))


@app.post("/batch")
def handle_batch(payload: dict = Body(...),
                 x_dba_agent: str | None = Header(default=None),
                 x_dba_token: str | None = Header(default=None)):
    """A unit of work that lands or rolls back together (§31, §48 TEST D)."""
    agent = _authenticate(x_dba_agent, x_dba_token)
    raw = payload.get("requests")
    if not isinstance(raw, list) or not raw:
        raise HTTPException(status_code=400,
                            detail="batch needs a non-empty 'requests' list.")
    requests = [_build(item, agent) for item in raw]
    responses = agent_module.default_agent().handle_many(
        requests, atomic=bool(payload.get("atomic", True)))
    applied = all(response.ok for response in responses)
    return JSONResponse(
        status_code=200 if applied else 409,
        content={"applied": applied,
                 "responses": [_body(response) for response in responses]})


@app.get("/health")
def get_health():
    """§28. Deliberately unauthenticated: an operator has to be able to ask
    whether this service is up without holding a write credential, and the
    response carries no record data - only counts and versions."""
    return health.health()


@app.get("/diagnostics")
def get_diagnostics(x_dba_agent: str | None = Header(default=None),
                    x_dba_token: str | None = Header(default=None)):
    """§29. Authenticated, because it names orphaned identifiers."""
    _authenticate(x_dba_agent, x_dba_token)
    return health.diagnose()


@app.get("/policy")
def get_policy():
    """What the DBA will and will not do for whom (§14), as data."""
    return permissions.describe()


@app.get("/types")
def get_types():
    """The declared entity types (§6), so a caller can build a valid request
    without reading this repository."""
    return {"types": [entity_type.to_dict()
                      for entity_type in entities.all_types()]}


def _build(payload: dict, agent: str) -> contract.Request:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400,
                            detail="a request is a JSON object.")
    body = dict(payload)
    claimed = body.get("requested_by")
    if claimed is not None and claimed != agent:
        raise HTTPException(
            status_code=400,
            detail=f"requested_by={claimed!r} does not match the authenticated "
                   f"agent {agent!r}. One request has one asker.")
    body["requested_by"] = agent
    try:
        return contract.Request.from_dict(body)
    except (ValueError, TypeError) as bad:
        raise HTTPException(status_code=400, detail=str(bad)) from bad


def _body(response: contract.Response) -> dict:
    """The structured response, plus §43's sentence alongside it.

    Alongside, never instead: §43 says the structured response remains
    authoritative, so `explanation` is an extra field and every caller that
    matters reads `status`."""
    out = response.to_dict()
    out["explanation"] = explain.explain(response)
    # §16 and §43, in Tamil beside the English rather than instead of it. The
    # structured response stays authoritative and nothing branches on either
    # sentence.
    out["explanation_ta"] = tamil.explain(response)
    return out


def _http_status(response: contract.Response) -> int:
    """The HTTP code for a structured response.

    A clarification is **200**, not 4xx. It is not a failed request - the DBA
    understood it and is asking a question - and returning 4xx would put it in
    the bucket where HTTP clients retry or raise, which is the opposite of
    answering."""
    if response.ok or response.needs_answer:
        return 200
    return {
        contract.PERMISSION_DENIED: 403,
        contract.NOT_FOUND: 404,
        contract.VALIDATION_ERROR: 422,
        contract.SCHEMA_MISMATCH: 422,
        contract.UNKNOWN_ACTION: 422,
        contract.DUPLICATE_DETECTED: 409,
        contract.CONFLICT_DETECTED: 409,
        contract.DATABASE_UNAVAILABLE: 503,
        contract.TIMEOUT: 504,
    }.get((response.error or {}).get("error_code"), 500)
