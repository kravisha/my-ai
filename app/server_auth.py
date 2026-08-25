"""Who the Server Superuser is, and how they prove it (addendum 39 §3,
addendum 38 §3.1/§3.2; TASK_QUEUE TQ-25, docs/SPEC_RECONCILIATION.md §74).

## Deliberately not the Gateway's Super User

Addendum 39 §3 is explicit: "Server authentication and Gateway authentication
must not be accidentally conflated." They authorize different things — the
Gateway is a phone-facing surface that can eventually authorize changes to
specifications and repositories (addendum 17 §14), while this credential
starts and observes the organization's own workforce. One credential for both
would mean a phone session compromise starts agents, and an operator console
compromise publishes specifications.

So this is a separate module with separate variables, standing beside
`gateway/auth.py` and `app/admin_auth.py` rather than extending either. All
three share one rule, stated in each: **unset means nobody can log in.** An
auth feature that defaults open is worse than none, because it looks
protected.

## The abstraction 39 §3.2 asks for

"Do not spread direct .env access throughout the codebase. Create an
authentication/configuration abstraction so that later migration from .env
credentials to database-backed or production-grade authentication does not
require rewriting the rest of the application."

That is what this module is: callers ask `verify(...)` and `is_configured()`,
never `os.environ`. Moving to a user table later changes this file and nothing
else.

## Plaintext is a PRE_ALPHA-only convenience, and the code enforces it

Addendum 39 §3 names `SERVER_SUPERUSER_PASSWORD`, which reads as plaintext.
This repository already refuses plaintext credentials in the environment for
the Gateway, with the reason stated there: a plaintext variable puts the
credential in the process listing and in every shell history that ever started
the service. That reasoning does not stop being true because a different
document uses a different variable name.

The resolution, rather than picking one document over the other:

- `SERVER_SUPERUSER_PASSWORD_HASH` (bcrypt) is the real credential and always
  works. `python -m gateway.hash_password` prints one.
- `SERVER_SUPERUSER_PASSWORD` (plaintext, the spec's literal name) is accepted
  **only while the boot configuration says PRE_ALPHA**, and warns every time
  it is used. At ALPHA and beyond it is refused outright, so the convenience
  cannot outlive the stage that justified it.

This is also the lifecycle stage's first behavioral consumer — addendum 38 §2
wanted a persisted stage precisely so components could "alter behavior based
on the current stage", and a stage nothing reads is a value nobody can trust.
"""

from __future__ import annotations

import os

import bcrypt

SUPERUSER_ENV = "SERVER_SUPERUSER_ID"
PASSWORD_HASH_ENV = "SERVER_SUPERUSER_PASSWORD_HASH"
PASSWORD_PLAINTEXT_ENV = "SERVER_SUPERUSER_PASSWORD"

NOT_CONFIGURED_MESSAGE = (
    f"No Server Superuser is configured, so the operator console is closed and the "
    f"workforce cannot be started. Set {SUPERUSER_ENV} and {PASSWORD_HASH_ENV} in .env "
    f"(python -m gateway.hash_password prints a hash), then restart the backend."
)

PLAINTEXT_REFUSED_MESSAGE = (
    f"{PASSWORD_PLAINTEXT_ENV} is only honoured while the boot configuration says PRE_ALPHA. "
    f"Set {PASSWORD_HASH_ENV} to a bcrypt hash instead - a plaintext credential in the "
    "environment is visible in the process listing and in shell history."
)

_PLAINTEXT_WARNING = (
    f"[server_auth] WARNING: authenticating against plaintext {PASSWORD_PLAINTEXT_ENV}. "
    f"This is a PRE_ALPHA convenience only; set {PASSWORD_HASH_ENV} before leaving PRE_ALPHA."
)


def superuser_id() -> str | None:
    """Read at call time, not import, so a reconfigured process sees the
    current value - the convention admin_auth and gateway.auth both follow."""
    value = os.environ.get(SUPERUSER_ENV, "").strip()
    return value or None


def password_hash() -> str | None:
    value = os.environ.get(PASSWORD_HASH_ENV, "").strip()
    return value or None


def _plaintext_password() -> str | None:
    value = os.environ.get(PASSWORD_PLAINTEXT_ENV, "")
    return value or None


def _plaintext_allowed() -> bool:
    """Only at PRE_ALPHA, read from boot configuration.

    A boot configuration that will not load is not a licence: this returns
    False, so a broken config narrows what is accepted rather than widening
    it. Fail-closed, the rule every gate in this codebase follows."""
    try:
        from backend.boot_config import load

        return load().is_pre_alpha
    except Exception:  # noqa: BLE001 - an unreadable stage is not permission
        return False


def is_configured() -> bool:
    """Whether a login could succeed at all. Callers use this to explain
    *why* rather than leaving an operator guessing at a wrong password."""
    if superuser_id() is None:
        return False
    if password_hash() is not None:
        return True
    return _plaintext_password() is not None and _plaintext_allowed()


def configuration_problem() -> str | None:
    """The specific reason login is impossible, or None if it is possible.
    Separate from `is_configured` so the caller can say which of the two
    failures it is - 'nothing configured' and 'plaintext past PRE_ALPHA' need
    different fixes."""
    if superuser_id() is None:
        return NOT_CONFIGURED_MESSAGE
    if password_hash() is not None:
        return None
    if _plaintext_password() is None:
        return NOT_CONFIGURED_MESSAGE
    if not _plaintext_allowed():
        return PLAINTEXT_REFUSED_MESSAGE
    return None


def verify(username: str, password: str) -> bool:
    """True only if both halves match the configured credential.

    Username comparison is case-insensitive, matching `app/admin_auth.py` and
    `gateway/auth.py`. The hash path uses bcrypt's constant-time comparison;
    the plaintext path (PRE_ALPHA only) uses `secrets.compare_digest` rather
    than `==` so it does not leak length or prefix through timing, which
    costs nothing and removes a whole category of footnote."""
    import secrets

    configured = superuser_id()
    if configured is None:
        return False
    if username.strip().lower() != configured.lower():
        return False

    stored_hash = password_hash()
    if stored_hash is not None:
        try:
            return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
        except ValueError:
            # A malformed hash is a configuration error, not a failed login -
            # but it must refuse rather than raise, or a typo in the variable
            # becomes a 500 with a stack trace (gateway/auth.py's own note).
            return False

    plaintext = _plaintext_password()
    if plaintext is None or not _plaintext_allowed():
        return False
    matched = secrets.compare_digest(password, plaintext)
    if matched:
        print(_PLAINTEXT_WARNING)
    return matched
