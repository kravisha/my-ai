"""Jarvis's client for the DBA Agent's published HTTP interface.

*"JARVIS is not the database. The DBA Agent is responsible for persistent
information."* — the Persistence specification, §2. This module is the whole of
the arrow between them.

## Why HTTP and not a Python call

The DBA is a separate service on port 8200 with its own store, its own policy
and its own version. Jarvis reaches it the way any other client does: a POST to
`/request` carrying the structured contract, authenticated with
`X-DBA-Agent: JARVIS` and the token in `DBA_TOKEN_JARVIS`.

Nothing in this package may reach into the DBA's code, and
`tests/test_dba_development.py` asserts that as an absence across every module
in `gateway/`. The reason is not taste. The three systems here evolve
separately and merge later; a Python-level dependency would make the DBA's
internal names part of Jarvis's build, and the first refactor on the far side
would break a service that never called for it. A published, versioned HTTP
contract is the only coupling that survives the two moving at different speeds.

## Being unavailable is an answer, not an exception to swallow

§34 names `DBA_UNAVAILABLE` as a state the system must *represent*, and §10
forbids filling missing memory with confident fabrication. So a DBA that is
down does not raise past the caller into a stack trace, and it emphatically
does not resolve to an empty result that reads like "nothing was stored". It
raises `Unavailable`, which the rehydration path turns into a named, reported
absence.

The timeouts are the ones `gateway/jarvis.py` settled on for the backend, for
the same reason: a service that accepts connections and never answers is the
same failure as one that is down, and holding a turn open makes it harder to
diagnose rather than easier.
"""

from __future__ import annotations

import os
import re
from typing import Any, Callable

import requests

URL_ENV = "JARVIS_DBA_URL"
TOKEN_ENV = "DBA_TOKEN_JARVIS"
DEFAULT_URL = "http://127.0.0.1:8200"

AGENT = "JARVIS"

CONNECT_TIMEOUT_SECONDS = 2
READ_TIMEOUT_SECONDS = 10

# The DBA's own vocabulary, restated here rather than imported. Two copies of a
# string is the price of the boundary above; a drift between them shows up as a
# contract test failing, which is why `tests/test_jarvis_persistence.py` asserts
# these against the real service rather than against this list.
CREATE = "create"
GET = "get"
FIND = "find"
SEARCH = "search"
UPDATE = "update"
ARCHIVE = "archive"
COUNT = "count"

STATUS_SUCCESS = "success"
STATUS_CLARIFICATION_REQUIRED = "clarification_required"

DUPLICATE_DETECTED = "duplicate_detected"
PERMISSION_DENIED = "permission_denied"
NOT_FOUND = "not_found"
DATABASE_UNAVAILABLE = "database_unavailable"
TIMEOUT = "timeout"


# The shape of an identifier the DBA issues: "<entity_type>-<16 hex>". Restated
# here for the boundary's sake, and `test_jarvis_persistence.py` asserts it
# agrees with the DBA's own parser rather than trusting that it still does.
#
# Parsing it is not a guess: the DBA documents the prefix as the type an id
# *declares*, precisely so a caller can know what it is holding without a
# lookup. `get` and `update` need an entity_type and this is where it comes
# from, with an override for the caller that knows better.
_IDENTIFIER = re.compile(r"^([a-z][a-z0-9_]*)-([0-9a-f]{16})$")


def type_of(entity_id: str) -> str:
    """The entity type an identifier declares."""
    match = _IDENTIFIER.match(entity_id or "")
    if match is None:
        raise ValueError(
            f"{entity_id!r} is not an identifier the DBA issued, so the type "
            f"it belongs to cannot be read off it. Pass entity_type "
            f"explicitly.")
    return match.group(1)


class Unavailable(RuntimeError):
    """The DBA could not be reached, or reported its own store unavailable.

    §34's `DBA_UNAVAILABLE`. Raised rather than returned so that no caller can
    mistake it for an empty answer."""


class Refused(RuntimeError):
    """The DBA understood the request and declined it.

    A permission refusal, a validation failure, a duplicate. Distinct from
    `Unavailable` because the two demand opposite responses: one is retried
    when the service returns, the other never succeeds on retry."""

    def __init__(self, message: str, *, code: str | None = None,
                 response: dict | None = None):
        super().__init__(message)
        self.code = code
        self.response = response or {}


class NeedsAnswer(RuntimeError):
    """The DBA asked a clarifying question instead of guessing (§45).

    Jarvis does not answer these on Krish's behalf. It carries the question up."""

    def __init__(self, message: str, *, clarification: dict | None = None):
        super().__init__(message)
        self.clarification = clarification or {}


def service_url() -> str:
    return (os.environ.get(URL_ENV) or DEFAULT_URL).rstrip("/")


def token() -> str | None:
    value = (os.environ.get(TOKEN_ENV) or "").strip()
    return value or None


def is_configured() -> bool:
    """Whether Jarvis has been given a token at all.

    Separate from reachability on purpose: "nobody configured this" and "the
    service is down" are different things to tell Krish, and a single boolean
    would collapse them into one unhelpful sentence."""
    return token() is not None


class DBAClient:
    """One client, one agent identity, one base URL.

    `transport` exists for the same reason `gateway/jarvis.JarvisClient` has
    one: the contract tests wire it to a TestClient over the real DBA service,
    so what they verify is the live interface rather than this module's belief
    about it. A test written against the JSON this file *expects* would keep
    passing the day the DBA changed its response shape, which is precisely the
    failure worth catching."""

    def __init__(self,
                 transport: Callable[[str, str, dict], tuple[int, dict]] | None = None,
                 *, actor: str = "jarvis",
                 requested_by: str = AGENT) -> None:
        """`requested_by` is the DBA identity this client speaks as.

        It is not a claim that can be made falsely: the DBA checks it against
        the agent the token authenticated, and refuses the mismatch with *"one
        request has one asker"*. So a client declaring `operator_console` without
        the operator's token fails at the service, which is what makes
        `charter.grant` an owner action rather than a naming convention."""
        self._transport = transport or self._http
        self._actor = actor
        self._requested_by = requested_by

    # --- transport -----------------------------------------------------------

    def _http(self, method: str, path: str, payload: dict) -> tuple[int, dict]:
        secret = token()
        if secret is None:
            raise Unavailable(
                f"no DBA token is configured. Set {TOKEN_ENV} to the token the "
                f"DBA issued for {AGENT}. Refusing rather than calling "
                f"unauthenticated, which would be a 401 dressed up as an outage.")
        try:
            response = requests.request(
                method, f"{service_url()}{path}",
                json=payload if method != "GET" else None,
                headers={"X-DBA-Agent": AGENT, "X-DBA-Token": secret},
                timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
            )
        except requests.RequestException as exc:
            raise Unavailable(
                f"the DBA Agent at {service_url()} did not answer: {exc}") from exc
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {}

    # --- the one call everything else is built from --------------------------

    def request(self, action: str, **fields: Any) -> dict:
        """Send one structured request and return the DBA's `result`.

        Every non-success is converted here, once, so that no caller has to
        remember which status code means what."""
        payload: dict[str, Any] = {"action": action,
                                   "requested_by": self._requested_by,
                                   "actor": self._actor}
        payload.update({name: value for name, value in fields.items()
                        if value is not None})
        status, body = self._transport("POST", "/request", payload)

        if status in (502, 503, 504):
            raise Unavailable(
                f"the DBA Agent answered {status}: "
                f"{body.get('detail') or body.get('error') or 'no detail given'}")
        if status == 401 or (status == 403 and "token" in str(body.get("detail", ""))):
            raise Unavailable(
                f"the DBA Agent rejected this client's credentials ({status}). "
                f"Check {TOKEN_ENV}. Reported as unavailable rather than as an "
                f"empty result, because Jarvis has no memory either way and "
                f"must not behave as though it does.")

        error = body.get("error") or {}
        code = error.get("error_code")
        if code in (DATABASE_UNAVAILABLE, TIMEOUT):
            raise Unavailable(
                f"the DBA reports its own store unavailable: "
                f"{error.get('message') or code}")
        if body.get("status") == STATUS_CLARIFICATION_REQUIRED:
            raise NeedsAnswer(
                str((body.get("clarification") or {}).get("question")
                    or "the DBA asked for clarification"),
                clarification=body.get("clarification"))
        if body.get("status") == STATUS_SUCCESS:
            return body
        raise Refused(
            f"{action} was refused: {error.get('message') or body.get('detail') or body}",
            code=code, response=body)

    # --- the shapes the persistence layer actually uses ----------------------

    def create(self, entity_type: str, data: dict, *, reason: str | None = None,
               request_id: str | None = None) -> str:
        body = self.request(CREATE, entity_type=entity_type, data=data,
                            reason=reason, request_id=request_id)
        entity_id = body.get("entity_id")
        if not entity_id:
            # §44 in the other direction: a success that names no record is not
            # a success this layer will pass off as one.
            raise Refused(f"the DBA reported {entity_type} created but named no "
                          f"record: {body}", response=body)
        return entity_id

    def get(self, entity_id: str, *,
            entity_type: str | None = None) -> dict | None:
        try:
            return self.request(GET, entity_id=entity_id,
                                entity_type=entity_type or type_of(entity_id)
                                ).get("result")
        except Refused as exc:
            if exc.code == NOT_FOUND:
                return None
            raise

    def find(self, entity_type: str, criteria: dict | None = None, *,
             limit: int = 50, offset: int = 0) -> list[dict]:
        body = self.request(FIND, entity_type=entity_type,
                            criteria={**(criteria or {}),
                                      "limit": limit, "offset": offset})
        result = body.get("result") or {}
        matches = result.get("matches") if isinstance(result, dict) else result
        return list(matches or [])

    def update(self, entity_id: str, changes: dict, *,
               entity_type: str | None = None,
               reason: str | None = None) -> bool:
        body = self.request(UPDATE, entity_id=entity_id, data=changes,
                            entity_type=entity_type or type_of(entity_id),
                            reason=reason)
        return bool(body.get("changed"))

    def archive(self, entity_id: str, *, entity_type: str | None = None,
                reason: str | None = None) -> bool:
        body = self.request(ARCHIVE, entity_id=entity_id,
                            entity_type=entity_type or type_of(entity_id),
                            reason=reason)
        return bool(body.get("changed"))

    def count(self, entity_type: str, criteria: dict | None = None) -> int:
        body = self.request(COUNT, entity_type=entity_type,
                            criteria=dict(criteria or {}))
        result = body.get("result")
        if isinstance(result, dict):
            result = result.get("count")
        return int(result or 0)

    # --- liveness ------------------------------------------------------------

    def health(self) -> dict:
        """What §3 step 4 calls "verify database availability and integrity".

        Goes through `transport` like everything else. It used to call
        `requests` directly, which meant the one call the bootstrap sequence
        depends on was the one call the contract tests could not reach - so the
        suite had to stub it, and stubbing it is how a test comes to assert
        that a health check works without ever running one.

        Raises `Unavailable` rather than returning a falsy dict, so the
        bootstrap sequence cannot proceed on a service that is not there."""
        status, body = self._transport("GET", "/health", {})
        if status != 200:
            raise Unavailable(
                f"the DBA Agent's /health answered {status}")
        if not isinstance(body, dict) or not body:
            raise Unavailable("the DBA Agent's /health did not return JSON")
        return body


def describe() -> dict:
    """What this client is pointed at, for a diagnostics page.

    The token is reported as present or absent and never echoed."""
    return {
        "service_url": service_url(),
        "agent": AGENT,
        "token_configured": is_configured(),
        "connect_timeout_seconds": CONNECT_TIMEOUT_SECONDS,
        "read_timeout_seconds": READ_TIMEOUT_SECONDS,
    }
