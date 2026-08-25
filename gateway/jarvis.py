"""The Gateway's window onto the running Jarvis backend (addendum 17 §4:
"project-wide status visibility", "access to recommendations produced by Jarvis
departments and monitoring agents").

This is the first code in the Gateway that talks to the rest of the system at
all. Four things about how it does so.

## It is a client, and a read-only one

The Gateway issues GETs against the backend's `/admin` surface and nothing else.
It cannot retire an agent, resume one, or file a directive - those are lifecycle
actions, addendum 11 §15 makes the Controller their exclusive executor, and the
panel already exists for a human to request them.

Giving a conversational model lifecycle authority over the organization is a much
larger step than "show me what is running", and it is not this increment's to
take. The read-only surface is enforced here, in the one method that reaches the
network, rather than by hoping no future tool asks for a POST.

## Its failure is a value, not an exception

Addendum 16 §23 requires the Gateway to stay usable when an internal component is
unavailable. That is not achieved by catching exceptions somewhere upstream: it
is achieved by this module treating "the backend is down" as an ordinary answer -
`{"available": False, "reason": ...}` - so that a conversation, the Scoreboard and
Git carry on with no knowledge that anything is wrong.

## Timeouts are short on purpose

A dead backend that accepts connections and never answers would otherwise hold a
model turn open for as long as the socket allowed, which is the same failure as
being down but harder to diagnose. Two seconds to connect, five to answer, then
it is unavailable.

## The session is held in memory and never written down

The backend's sessions live seven days, so a static token in the environment
would quietly expire; the Gateway therefore logs in with credentials and renews
on a 401. The resulting token is a live credential and stays in this process -
writing it into `gateway.db` would put a second copy of an authenticated session
on disk for no benefit.
"""

import json
import os
from typing import Callable

import requests

BACKEND_URL_ENV = "GATEWAY_BACKEND_URL"
BACKEND_USER_ENV = "GATEWAY_BACKEND_USER"
BACKEND_PASSWORD_ENV = "GATEWAY_BACKEND_PASSWORD"

DEFAULT_BACKEND_URL = "http://localhost:8000"

CONNECT_TIMEOUT_SECONDS = 2
READ_TIMEOUT_SECONDS = 5

NOT_CONFIGURED_REASON = (
    f"No Jarvis backend credentials are configured, so the Gateway cannot see the running "
    f"system. Set {BACKEND_USER_ENV} and {BACKEND_PASSWORD_ENV} (an account listed in the "
    f"backend's MY_AI_ADMIN_USERS) and restart."
)


def backend_url() -> str:
    return os.environ.get(BACKEND_URL_ENV, "").strip() or DEFAULT_BACKEND_URL


def credentials() -> tuple[str | None, str | None]:
    return (
        os.environ.get(BACKEND_USER_ENV, "").strip() or None,
        os.environ.get(BACKEND_PASSWORD_ENV, "") or None,
    )


def is_configured() -> bool:
    username, password = credentials()
    return username is not None and password is not None


class JarvisClient:
    """A read-only client for the backend's admin surface.

    `transport` exists so the contract can be tested against the real backend
    application rather than against a description of it - see
    tests/test_gateway_jarvis.py, which wires this to a TestClient over
    `backend.main:app`. A test that asserted the JSON this module *expects* would
    keep passing after the backend changed its routes, which is precisely the
    failure worth catching."""

    def __init__(self, transport: Callable[[str, str | None], tuple[int, dict]] | None = None):
        self._transport = transport or self._http
        self._token: str | None = None

    # --- transport ---

    def _http(self, path: str, token: str | None) -> tuple[int, dict]:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = requests.get(
            f"{backend_url().rstrip('/')}{path}",
            headers=headers,
            timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
        )
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {}

    def _login(self) -> str | None:
        username, password = credentials()
        if username is None or password is None:
            return None
        response = requests.post(
            f"{backend_url().rstrip('/')}/auth/login",
            json={"username": username, "password": password},
            timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
        )
        if response.status_code != 200:
            return None
        return response.json().get("token")

    def _get(self, path: str) -> tuple[int, dict]:
        """One GET, renewing the session once if the backend says it is stale.

        Once, not in a loop: a second 401 after a fresh login means the account is
        not an admin or the credentials are wrong, and retrying that forever would
        turn a configuration error into a hammering of the login route."""
        if self._token is None:
            self._token = self._login()
        status, body = self._transport(path, self._token)
        if status == 401:
            self._token = self._login()
            if self._token is None:
                return status, body
            status, body = self._transport(path, self._token)
        return status, body

    # --- questions ---

    def _unavailable(self, reason: str) -> dict:
        return {"available": False, "reason": reason}

    def _fetch(self, path: str) -> dict:
        if not is_configured():
            return self._unavailable(NOT_CONFIGURED_REASON)
        try:
            status, body = self._get(path)
        except requests.RequestException as unreachable:
            # The §23 case. Not an error to propagate: an unreachable backend is
            # an ordinary answer, and everything else the Gateway does carries on.
            return self._unavailable(f"The Jarvis backend at {backend_url()} did not answer ({unreachable.__class__.__name__}).")

        if status == 401 or status == 403:
            return self._unavailable(
                "The Jarvis backend refused the Gateway's credentials. The configured account "
                "must be listed in the backend's MY_AI_ADMIN_USERS."
            )
        if status != 200:
            return self._unavailable(f"The Jarvis backend answered {status} for {path}.")
        return {"available": True, **body}

    def console(self, path: str) -> tuple[int, dict]:
        """Proxy one of the backend console's read endpoints (TQ-34, §92).

        Addendum 40 §13.1: the Gateway "must never create a duplicate COO,
        duplicate organization, or independent source of truth". So the studio an
        operator sees through the Gateway is not a second console reading a
        second copy of anything - it is this proxy in front of the same
        endpoints the desktop console calls, answering out of the same database.
        Addendum 43 §17's "one organization, many windows", implemented as a
        window rather than as a second room.

        Reads only, and the caller passes a path from a fixed allowlist rather
        than anything a browser sent - a proxy that forwarded arbitrary paths
        into a loopback-only backend would be a hole straight through the
        boundary addendum 16 §7 exists to draw.

        Returns (status, body) rather than the `available` shape the rest of
        this class uses, because the console's own routes already answer
        honestly when the organization is quiet and the page renders that
        itself."""
        try:
            status, body = self._transport(path, None)
        except requests.RequestException as unreachable:
            return 503, self._unavailable(
                f"The Jarvis backend at {backend_url()} did not answer "
                f"({unreachable.__class__.__name__}).")
        return status, body

    def console_write(self, path: str, body: bytes, *, method: str = "PUT") -> tuple[int, dict]:
        """Forward one studio write to the backend.

        Kept separate from `console` and from every other method on this class,
        which are GETs by design (see the module docstring: the Gateway cannot
        retire an agent or file a directive). This does not widen that: the
        workspace is the operator's own view state, not organizational
        lifecycle, and the allowlist in gateway/main.py is what decides which
        paths may arrive here at all."""
        try:
            response = requests.request(
                method, f"{backend_url().rstrip('/')}{path}", data=body,
                headers={"Content-Type": "application/json"},
                timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
            )
        except requests.RequestException as unreachable:
            return 503, {"error": f"backend unreachable ({unreachable.__class__.__name__})"}
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {}

    def console_stream(self, path: str, body: bytes):
        """Forward a streaming POST and yield the bytes as they arrive.

        A blocking generator on purpose - `gateway.streaming.iterate_in_thread`
        is what turns it into something an async socket can consume without
        occupying the event loop, and that module exists because this shape kept
        recurring."""
        try:
            with requests.post(
                f"{backend_url().rstrip('/')}{path}", data=body,
                headers={"Content-Type": "application/json"},
                stream=True,
                # No read timeout: the whole point is a response that arrives
                # over seconds. The connect timeout still bounds a dead backend.
                timeout=(CONNECT_TIMEOUT_SECONDS, None),
            ) as response:
                if response.status_code != 200:
                    yield _sse_error(f"the backend answered {response.status_code}")
                    return
                for chunk in response.iter_content(chunk_size=None):
                    if chunk:
                        yield chunk
        except requests.RequestException as unreachable:
            # Reported in the stream's own vocabulary, so the console renders it
            # as an answer it could not get rather than as a broken page.
            yield _sse_error(
                f"the backend at {backend_url()} did not answer "
                f"({unreachable.__class__.__name__})")

    def status(self) -> dict:
        """The organization as it stands: who exists, on which of the two
        lifecycle axes, and whether anything looks unhealthy.

        Both axes are reported separately and never merged, for the reason
        `backend/main.py` gives at the same route: a dormant agent and a crashed
        one both have no process, and only one of them is a problem."""
        answer = self._fetch("/admin/agents")
        if not answer["available"]:
            return answer

        agents = answer.get("agents", [])
        counts = {"active": 0, "dormant": 0, "running": 0, "stopped": 0, "crashed": 0}
        for agent in agents:
            for axis in ("lifecycle_state", "process_state"):
                value = agent.get(axis)
                if value in counts:
                    counts[value] += 1

        # What the organization noticed about itself. Fetched with the roster
        # rather than behind its own tool, because "who is running" and "what
        # broke" are one question when the answer to the first is "fewer things
        # than there should be" - and an escalated incident is the one state that
        # is waiting on a person rather than on a watcher.
        incidents = self._fetch("/admin/incidents")

        return {
            "available": True,
            "backend_url": backend_url(),
            "agents": agents,
            "counts": counts,
            "crashed": [a["identity"] for a in agents if a.get("process_state") == "crashed"],
            "incidents": {
                "open": incidents.get("open", 0),
                "escalated": incidents.get("escalated", 0),
                "recent": incidents.get("incidents", [])[:5],
            } if incidents["available"] else {"unavailable": incidents["reason"]},
        }

    def agent(self, identity: str) -> dict:
        """One agent in full - what the UQI would be asked about, and what a
        question like "why did explorer-1 restart" needs."""
        return self._fetch(f"/admin/agents/{identity}")


def _sse_error(reason: str) -> bytes:
    """One server-sent event in the shape backend/console/index.html parses.

    The console already renders a `{"type": "error"}` event as an answer it
    could not get. Reusing that vocabulary means a Gateway-side failure looks
    like every other failure the page knows how to explain, instead of like a
    broken stream."""
    payload = json.dumps({"type": "error", "error": reason})
    return f"data: {payload}\n\n".encode("utf-8")
