"""The Gateway's client for the backend's portfolio surface (TASK_QUEUE TQ-69,
docs/SPEC_RECONCILIATION.md §110).

Source: owner direction 2026-08-26 (§109); spec §4.4, §4.5, §5, §11 Risk 3.

Shaped like `gateway/jarvis.py`, which is the model the spec names: short
timeouts, log in with `GATEWAY_BACKEND_USER` and renew once on a 401, and the
whole network surface in one place. Where it deliberately differs from that
module is the interesting part.

## Its failure is an exception, not a value

`gateway/jarvis.py` treats "the backend is down" as an ordinary answer -
`{"available": False, "reason": ...}` - so a conversation carries on knowing
nothing is wrong. That is right for a status panel and addendum 16 §23 asks for
it.

**It is wrong here, and the difference is the point of §4.5.** A conversation the
Gateway cannot reach is an inconvenience. Holdings it cannot reach must not
degrade into something that looks like an answer: an empty list reads as "you
hold nothing", and a `{"available": False}` dict is one careless caller away from
being rendered as an empty portfolio. So this raises `BackendUnavailable`, which
has to be caught and turned into words, and `gateway/tools.py` turns it into a
refusal that names the backend.

## There is no cache, and there will not be one

Addendum 16 §23 is why the Gateway has local storage at all, and that reasoning
does not extend to money. **Showing somebody last week's positions as though they
were current is worse than showing them nothing** - the same class of wrong as
serving a simulated price as a real one (§101), and §17's rule stated from the
other side: *do not silently claim it is current.*

That is not a preference, it is the property this module exists to hold. A cache
here would recreate, in the Gateway, exactly the second copy of client financial
data that TQ-69 spent an increment removing.

## Every call carries the owner

There is no method on this class that reaches portfolio data without a `subject`.
The backend refuses an ownerless call anyway - that is the whole point of the new
surface - but a client that *could* form one would be a client somebody could
accidentally use, and the shape of an interface is what people build against.

The subject comes from the session (§93, §98) and never from an argument a model
supplied. `gateway/tools.py` is where that is enforced, for the same reason it
always was: the model is never asked to name a client, so there is no shape of
tool call that reaches another client's positions.

## It knows nothing about what a portfolio *is*

No vocabulary, no `is_priced`, no refusal string of its own. Everything it says
about somebody's money is quoted from the backend's answer, including the
refusal - which matters more than it looks: addendum 44 §9.3 requires one
identical refusal for absent, foreign and archived, and a Gateway that composed
its own message would be a second place that rule could be broken.
"""

from __future__ import annotations

import os
from typing import Callable

import requests

BACKEND_URL_ENV = "GATEWAY_BACKEND_URL"
BACKEND_USER_ENV = "GATEWAY_BACKEND_USER"
BACKEND_PASSWORD_ENV = "GATEWAY_BACKEND_PASSWORD"

DEFAULT_BACKEND_URL = "http://localhost:8000"

# The same two seconds and five seconds as gateway/jarvis.py, for the same
# reason: a dead backend that accepts connections and never answers would
# otherwise hold a model turn open for as long as the socket allowed - the same
# failure as being down, and harder to diagnose.
CONNECT_TIMEOUT_SECONDS = 2
READ_TIMEOUT_SECONDS = 5

# The wire vocabulary: the only portfolio words the Gateway is allowed to say.
#
# These are **quoted from the backend's surface, not a second definition of it**.
# `backend/portfolios.py` owns these vocabularies and validates every one of them
# on read and on write; what is here is the subset the Gateway has a reason to
# send, written out because importing the backend's portfolio modules into the
# Gateway is the thing TQ-69 exists to stop.
#
# A copy that could drift is normally what this project refuses (§70, §100,
# §104), and the answer here is the same as everywhere else: a test holds them
# together. `test_the_wire_vocabulary_matches_the_backends` fails if any of these
# stops being the backend's own value - so there are two spellings and one fact,
# with something that fails when that stops being true.
OWNER_CLIENT = "CLIENT"
PROVIDER_SIMULATED = "SIMULATED"
MODE_SIMULATED = "SIMULATED"

NOT_CONFIGURED_REASON = (
    f"I cannot reach the system that holds your portfolio: this Gateway has no backend "
    f"credentials configured. Set {BACKEND_USER_ENV} and {BACKEND_PASSWORD_ENV} and restart. "
    f"I am not going to show you anything from memory, because holdings that are out of "
    f"date look exactly like holdings that are current."
)


class BackendUnavailable(RuntimeError):
    """The backend could not be reached or would not answer, and **nothing is
    being served in its place** (§4.5).

    Carries a sentence meant to be repeated to the person who asked. The message
    names the backend as the missing thing rather than saying "no holdings",
    because those are different facts and only one of them is true."""


class NotAuthorized(PermissionError):
    """The backend refused. Absent, foreign and archived arrive here identically
    - one status, one body - and this re-raises the backend's own words rather
    than composing any, so §9.3's single refusal has exactly one author."""


class PortfolioRefused(ValueError):
    """Data or a request the backend would not accept, with the reason it gave."""


class CapabilityUnavailable(NotImplementedError):
    """This portfolio's provider cannot answer that, and said why. Distinct from
    `PortfolioRefused` because the answer to the client is different: "I cannot
    tell you that, and here is why" rather than "what you sent will not do"."""


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


class PortfolioClient:
    """Every portfolio call the Gateway makes, and the only place it makes one.

    `transport` exists for the same reason `JarvisClient`'s does, and it earns it
    harder here: the headline test of this whole increment is addendum 44 §15.5's
    permanent regression run **through this client against the real backend
    application**. A test that asserted the JSON this module expects would keep
    passing after the backend changed its routes, which is precisely the failure
    worth catching - and in this case the thing it would stop catching is a
    client receiving somebody else's portfolio.

    Login goes through the transport too, unlike `JarvisClient`'s, so a test
    exercises the real `/auth/login` and the real `require_gateway` rather than
    a stand-in for them. An authorization gate that no test ever reaches is one
    that rots without anybody noticing."""

    def __init__(self, transport: Callable[..., tuple[int, dict]] | None = None):
        self._transport = transport or self._http
        self._token: str | None = None

    # --- transport ---

    def _http(self, method: str, path: str, *, params: dict | None = None,
              json: dict | None = None, token: str | None = None) -> tuple[int, dict]:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = requests.request(
            method, f"{backend_url().rstrip('/')}{path}",
            params=params, json=json, headers=headers,
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
        status, body = self._transport(
            "POST", "/auth/login", json={"username": username, "password": password})
        if status != 200:
            return None
        return body.get("token")

    def _call(self, method: str, path: str, *, params: dict | None = None,
              json: dict | None = None) -> dict:
        """One request, with the whole failure vocabulary applied in one place.

        Renews the session once on a 401 and no more. A second 401 after a fresh
        login means the account is wrong or is not the configured Gateway user,
        and retrying that in a loop would turn a configuration error into a
        hammering of the login route."""
        if not is_configured():
            raise BackendUnavailable(NOT_CONFIGURED_REASON)
        try:
            if self._token is None:
                self._token = self._login()
            status, body = self._transport(method, path, params=params, json=json,
                                           token=self._token)
            if status == 401:
                self._token = self._login()
                if self._token is not None:
                    status, body = self._transport(method, path, params=params,
                                                   json=json, token=self._token)
        except requests.RequestException as unreachable:
            raise BackendUnavailable(
                f"I cannot reach the system that holds your portfolio - the backend at "
                f"{backend_url()} did not answer ({unreachable.__class__.__name__}). I am "
                f"not showing you anything from memory: holdings that are out of date look "
                f"exactly like holdings that are current."
            ) from None

        if status == 200:
            return body

        detail = body.get("detail") if isinstance(body, dict) else None
        if status == 403:
            # The backend's own refusal, re-raised with the backend's own words.
            # Composing a message here would put a second author on §9.3's single
            # refusal, and the second one is where the distinction leaks back in.
            raise NotAuthorized(str(detail or "Not authorized."))
        if status == 409:
            raise CapabilityUnavailable(str(detail or "That cannot be answered."))
        if status in (400, 422):
            raise PortfolioRefused(str(detail or "That request could not be used."))
        if status == 401:
            raise BackendUnavailable(
                "The backend refused this Gateway's credentials, so I cannot reach your "
                f"portfolio. The account in {BACKEND_USER_ENV} must be the one the backend "
                "is configured to accept."
            )
        raise BackendUnavailable(
            f"The system that holds your portfolio answered {status} for {path}, so I do "
            "not have your holdings and I am not going to guess at them."
        )

    # --- portfolios ---

    def primary(self, subject: str, *, display_name: str | None = None,
                simulated: bool = False, provider_type: str | None = None,
                data_mode: str | None = None) -> dict:
        """This subject's primary portfolio, created on first use.

        Where every holdings tool starts, and the reason no tool takes a
        portfolio id: the model is never asked to name one, so there is no shape
        of tool call that reaches somebody else's."""
        payload = {**self._owner(subject),
                   "display_name": display_name, "simulated": simulated}
        # Omitted rather than passed as None, so the backend's own defaults stay
        # the single definition of what an ordinary portfolio is.
        if provider_type is not None:
            payload["provider_type"] = provider_type
        if data_mode is not None:
            payload["data_mode"] = data_mode
        return self._call("POST", "/portfolios/primary", json=payload)["portfolio"]

    def resolve(self, subject: str, portfolio_id: str) -> dict:
        return self._call("POST", "/portfolios/resolve", json={
            **self._owner(subject), "portfolio_id": portfolio_id})["portfolio"]

    def listing(self, subject: str) -> list[dict]:
        return self._call("GET", "/portfolios",
                          params=self._owner(subject))["portfolios"]

    # --- holdings ---

    def holdings(self, subject: str, portfolio_id: str) -> list[dict]:
        return self._call("GET", f"/portfolios/{portfolio_id}/holdings",
                          params=self._owner(subject))["holdings"]

    def record(self, subject: str, portfolio_id: str, **holding) -> dict:
        return self._call("POST", f"/portfolios/{portfolio_id}/holdings",
                          json={**self._owner(subject), **holding})["recorded"]

    def forget(self, subject: str, portfolio_id: str, symbol: str) -> bool:
        return self._call("DELETE", f"/portfolios/{portfolio_id}/holdings/{symbol}",
                          params=self._owner(subject))["forgotten"]

    def balances(self, subject: str, portfolio_id: str) -> dict:
        return self._call("GET", f"/portfolios/{portfolio_id}/balances",
                          params=self._owner(subject))["balances"]

    def analysis(self, subject: str, portfolio_id: str) -> dict:
        return self._call("GET", f"/portfolios/{portfolio_id}/analysis",
                          params=self._owner(subject))["analysis"]

    def account(self, subject: str, portfolio_id: str) -> dict:
        return self._call("GET", f"/portfolios/{portfolio_id}/account",
                          params=self._owner(subject))

    def refresh(self, subject: str, portfolio_id: str) -> dict:
        return self._call("POST", f"/portfolios/{portfolio_id}/refresh",
                          json=self._owner(subject))["refreshed"]

    def purge(self, subject: str) -> dict:
        """Everything this subject owns, gone. For demo clearing (§96), the only
        caller that should ever want it."""
        return self._call("POST", "/portfolios/purge", json=self._owner(subject))

    def simulated(self) -> dict:
        """Demo-data hygiene, from `/admin` rather than from the on-behalf-of
        surface: it is not owner-scoped, so it does not belong on a surface whose
        rule is that everything is."""
        return self._call("GET", "/admin/portfolios/simulated")

    @staticmethod
    def _owner(subject: str) -> dict:
        """The asserted owner, on every single call.

        A static method with one line, and it is here rather than inlined so that
        there is nowhere in this class an owner could be *forgotten*. Every
        method above names it; a method that did not would be visibly missing
        something."""
        if not (subject or "").strip():
            raise PortfolioRefused(
                "I cannot reach a portfolio without knowing whose it is.")
        return {"owner_type": OWNER_CLIENT, "owner_id": subject}


# One client per process, following `app/local_ai.service()`.
#
# Not an optimisation for its own sake: `_token` lives on the instance, so a new
# client per tool call would mean a fresh `/auth/login` per tool call, and the
# backend hashes passwords with bcrypt deliberately slowly. A conversation that
# records a holding and then lists them would pay for that twice, for no benefit.
#
# The token stays in memory and is never written down, for the reason
# gateway/jarvis.py gives: it is a live credential, and putting a second copy of
# an authenticated session on disk buys nothing.
_SERVICE: PortfolioClient | None = None


def service() -> PortfolioClient:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = PortfolioClient()
    return _SERVICE


def reset() -> None:
    """Drop the cached client. For tests, and for a credential change that should
    not need a restart to take effect."""
    global _SERVICE
    _SERVICE = None
