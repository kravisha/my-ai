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

from gateway import roles

SUPER_USER_ENV = "GATEWAY_SUPER_USER"
PASSWORD_HASH_ENV = "GATEWAY_PASSWORD_HASH"
SESSION_TTL_ENV = "GATEWAY_SESSION_TTL_SECONDS"

# One credential pair per *environment-configured* role (TQ-34, §92; narrowed by
# TQ-43, §98). The operator's keeps its original variable names: renaming them
# would log out every existing deployment to buy nothing, and "SUPER_USER" is
# still what that credential is.
#
# Both follow the Super User's rules rather than getting relaxed ones - bcrypt
# hash only, never plaintext, and unset means that role cannot log in. A second
# credential is exactly as much of a security boundary as the first.
#
# Clients are deliberately absent. A shared environment variable is
# an acceptable credential for a role that is one person by definition, and a
# group password for one that is many - so operator and internal keep theirs,
# and clients register individually in gateway/clients.py. Leaving a
# GATEWAY_CLIENT_PASSWORD_HASH configurable "for compatibility" would leave the
# shared password available, which is the hole TQ-43 closes rather than a
# migration path away from it.
ROLE_CREDENTIAL_ENV: dict[str, tuple[str, str]] = {
    roles.ROLE_OPERATOR: (SUPER_USER_ENV, PASSWORD_HASH_ENV),
    roles.ROLE_INTERNAL: ("GATEWAY_INTERNAL_USER", "GATEWAY_INTERNAL_PASSWORD_HASH"),
}

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


def credential_for(role: str) -> tuple[str | None, str | None]:
    """The (username, hash) pair configured for a role, either half possibly None."""
    if role not in ROLE_CREDENTIAL_ENV:
        raise roles.UnknownRole(f"no credential is defined for role {role!r}")
    user_env, hash_env = ROLE_CREDENTIAL_ENV[role]
    return (os.environ.get(user_env, "").strip() or None,
            os.environ.get(hash_env, "").strip() or None)


def configured_roles() -> list[str]:
    """Which roles have an environment credential on this machine.

    Reported so an operator can see that the internal door is shut without
    reading the environment - a role that silently refuses looks identical to a
    wrong password from the outside.

    Clients are not listed here and their absence is not a misconfiguration:
    they authenticate through the registry, and `gateway.clients.listing` is
    where "who can log in as a client" is answered."""
    return [role for role in roles.ROLES
            if role in ROLE_CREDENTIAL_ENV and all(credential_for(role))]


def identify(username: str, password: str) -> str | None:
    """The **environment-configured** role this credential belongs to, or None.

    Covers the operator and internal roles only. Clients authenticate through
    `gateway.clients.authenticate`, which returns an identity rather than a role
    because a client session needs to know *which* client it is (TQ-43, §98).

    Every configured role is checked rather than stopping at the first username
    match, so two roles sharing a username cannot make one of them
    unreachable - and each check is bcrypt's, so the work is constant per role
    rather than depending on which one matched.

    Returns the role rather than a boolean because the session has to record
    it: a Gateway that verified a credential and then assumed which role it
    belonged to would be guessing at exactly the wrong moment."""
    supplied = (username or "").strip().lower()
    matched = None
    for role in ROLE_CREDENTIAL_ENV:
        name, digest = credential_for(role)
        if name is None or digest is None:
            continue
        if supplied != name.lower():
            continue
        try:
            if bcrypt.checkpw((password or "").encode("utf-8"), digest.encode("utf-8")):
                # No early return: leaving the loop here would make the time
                # taken depend on which role matched, and the roles are ordered.
                matched = matched or role
        except ValueError:
            # A malformed hash is a configuration error, not a failed login -
            # but it must refuse rather than raise, or a typo in the variable
            # becomes a 500 that leaks a stack trace to an external client.
            continue
    return matched


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
