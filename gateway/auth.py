"""Who the Super User is, and how they prove it.

Addendum 17 §14: because this interface can eventually authorize actions
affecting specifications, architecture, Git repositories and implementation
workflows, "Super User authentication and authorization must be treated as a
high-security boundary."

The credential comes from the process environment, not from `users.json`, for the
reasons `app/admin_auth.py` already gives about admin status: a route that could
grant this privilege would be an escalation surface worth not having at all, and
whoever controls the process already controls its data. Keeping it out of
`users.json` also means the Gateway credential is not the ordinary application
password - a phone-facing, spec-publishing session and a desktop portfolio login
should not fall together.

**Unset means nobody can log in, and every attempt is refused.** Same rule as
admin_auth, for the same reason: an auth feature that defaults open is worse than
none, because it looks protected. The refusal names exactly what to set.

The password is supplied as a bcrypt hash, never as plaintext:

    GATEWAY_SUPER_USER=krish
    GATEWAY_PASSWORD_HASH=$2b$12$...

`python -m gateway.hash_password` prints a hash to paste in. A plaintext variable
would put the credential in the process listing and in every shell history that
ever started the service.
"""

import os

import bcrypt

SUPER_USER_ENV = "GATEWAY_SUPER_USER"
PASSWORD_HASH_ENV = "GATEWAY_PASSWORD_HASH"
SESSION_TTL_ENV = "GATEWAY_SESSION_TTL_SECONDS"

DEFAULT_SESSION_TTL_SECONDS = 12 * 60 * 60

NOT_CONFIGURED_MESSAGE = (
    f"No Super User is configured, so this Gateway refuses every login. "
    f"Set {SUPER_USER_ENV} and {PASSWORD_HASH_ENV} (generate the hash with "
    f"`python -m gateway.hash_password`) and restart the service."
)


def super_user() -> str | None:
    """Read at call time, not import time, so a restarted process and a test that
    sets the variable both see the current value."""
    name = os.environ.get(SUPER_USER_ENV, "").strip()
    return name or None


def password_hash() -> str | None:
    value = os.environ.get(PASSWORD_HASH_ENV, "").strip()
    return value or None


def is_configured() -> bool:
    return super_user() is not None and password_hash() is not None


def session_ttl_seconds() -> int:
    raw = os.environ.get(SESSION_TTL_ENV, "").strip()
    if not raw:
        return DEFAULT_SESSION_TTL_SECONDS
    try:
        ttl = int(raw)
    except ValueError:
        return DEFAULT_SESSION_TTL_SECONDS
    return ttl if ttl > 0 else DEFAULT_SESSION_TTL_SECONDS


def verify(username: str, password: str) -> bool:
    """True only if both halves match a configured credential.

    The username comparison is case-insensitive to match `app/admin_auth.py`;
    the password comparison is bcrypt's, which is constant-time. An unconfigured
    Gateway returns False here - `is_configured` is what lets a caller explain
    why, rather than leaving the user guessing at a wrong password."""
    if not is_configured():
        return False
    if username.strip().lower() != super_user().lower():
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash().encode("utf-8"))
    except ValueError:
        # A malformed hash in the environment is a configuration error, not a
        # failed login - but it must still refuse rather than raise, or a typo in
        # the variable becomes a 500 that leaks a stack trace to an external
        # client.
        return False
