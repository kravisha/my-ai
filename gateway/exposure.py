"""What changes when the Gateway stops being on localhost (addendum 16 §12,
addendum 17 §14).

The owner's decision on how the phone reaches this service is **a tunnel**:
`cloudflared` or Tailscale Funnel terminates TLS and forwards to the Gateway on
loopback. Nothing is opened on the router, the certificate is real, and the
service still binds to 127.0.0.1. That choice shapes this module - everything here
is about being correct *behind a reverse proxy* rather than about running TLS
directly.

## Why the client's address needs care

Behind a tunnel every request arrives from 127.0.0.1. Rate limiting on that
address would lump every phone, every attacker and the owner into one bucket, so
the real address has to come from `X-Forwarded-For`.

That header is also trivially forged by whoever sends it. So it is honoured only
when the connection itself comes from an address the operator has declared to be a
proxy, and the value taken is the **rightmost entry that is not one of those
proxies** - the last hop a trusted proxy actually observed, rather than whatever
the client put at the front of the list.

An unset `GATEWAY_TRUSTED_PROXIES` means loopback, which is exactly the tunnel
case, and a direct connection from anywhere else has its headers ignored.

## Why rate limiting lives in memory

Login attempts are ephemeral, per-process, and worthless after a restart. Writing
each one to SQLite would put a durable record of failed guesses in a database
whose whole point is durable project material, and would make a brute-force
attempt into disk I/O. A dictionary is the right shape; when this service ever
runs as more than one process, the limiter moves to something shared, and that is
a change with a reason rather than a precaution without one.
"""

import os
import time
from collections import defaultdict, deque

TRUSTED_PROXIES_ENV = "GATEWAY_TRUSTED_PROXIES"
LOGIN_ATTEMPTS_ENV = "GATEWAY_LOGIN_ATTEMPTS"
LOGIN_WINDOW_ENV = "GATEWAY_LOGIN_WINDOW_SECONDS"

DEFAULT_TRUSTED_PROXIES = ("127.0.0.1", "::1", "localhost")
DEFAULT_LOGIN_ATTEMPTS = 10
DEFAULT_LOGIN_WINDOW_SECONDS = 300

# Sent on every response. Deliberately short: these are the ones that matter for a
# single-page, same-origin, token-in-memory client reachable from the internet.
#
# `frame-ancestors 'none'` rather than X-Frame-Options because the CSP directive
# is the one browsers still honour. No script-src policy: the client is one file
# with its script and style inline, which was a deliberate choice (no build step,
# no external requests), and a strict script-src would mean splitting it. That
# trade is worth revisiting if the page grows; it is not worth pretending a
# policy exists when it would have to carry 'unsafe-inline' anyway.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "frame-ancestors 'none'",
}

# Only sent when the request actually arrived over TLS. Announcing HSTS on a plain
# HTTP response is how a developer locks themselves out of their own localhost.
HSTS_HEADER = ("Strict-Transport-Security", "max-age=31536000")


def trusted_proxies() -> set[str]:
    raw = os.environ.get(TRUSTED_PROXIES_ENV, "").strip()
    if not raw:
        return set(DEFAULT_TRUSTED_PROXIES)
    return {entry.strip() for entry in raw.split(",") if entry.strip()}


def login_attempt_limit() -> int:
    return _positive_int(LOGIN_ATTEMPTS_ENV, DEFAULT_LOGIN_ATTEMPTS)


def login_window_seconds() -> int:
    return _positive_int(LOGIN_WINDOW_ENV, DEFAULT_LOGIN_WINDOW_SECONDS)


def _positive_int(variable: str, default: int) -> int:
    raw = os.environ.get(variable, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def client_address(peer: str | None, forwarded_for: str | None) -> str:
    """The address to hold responsible for a request.

    `peer` is who actually connected; `forwarded_for` is what they claim about who
    is behind them. The claim is worth nothing unless the peer is a declared
    proxy, which is the whole of the logic here."""
    peer = (peer or "unknown").strip()
    if peer not in trusted_proxies() or not forwarded_for:
        return peer

    hops = [hop.strip() for hop in forwarded_for.split(",") if hop.strip()]
    proxies = trusted_proxies()
    for hop in reversed(hops):
        if hop not in proxies:
            return hop
    # Every hop is a proxy we trust, which means none of them is the client. The
    # peer is the most honest answer available.
    return peer


class AttemptLimiter:
    """A sliding window of failures per key.

    Successes are not counted and clear the record: the thing being limited is
    guessing, not use. Somebody typing their own password correctly ten times has
    done nothing wrong."""

    def __init__(self, limit: int, window_seconds: int, clock=time.monotonic):
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._failures: dict[str, deque] = defaultdict(deque)

    def _prune(self, key: str) -> deque:
        now = self._clock()
        failures = self._failures[key]
        while failures and now - failures[0] > self.window_seconds:
            failures.popleft()
        return failures

    def is_blocked(self, key: str) -> bool:
        return len(self._prune(key)) >= self.limit

    def retry_after_seconds(self, key: str) -> int:
        """How long until the oldest failure ages out - what a 429 should say."""
        failures = self._prune(key)
        if not failures:
            return 0
        return max(1, int(self.window_seconds - (self._clock() - failures[0])) + 1)

    def record_failure(self, key: str) -> int:
        self._prune(key).append(self._clock())
        return len(self._failures[key])

    def record_success(self, key: str) -> None:
        self._failures.pop(key, None)

    def forget_everything(self) -> None:
        """For tests, and for an operator who has locked themselves out and can
        restart the process - which is the only recovery this deliberately
        offers."""
        self._failures.clear()
