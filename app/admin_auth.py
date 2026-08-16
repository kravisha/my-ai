"""Who counts as a superuser (addendum 14 §7: "Direct UQI access must be
privilege-controlled and auditable").

Admin status is configuration, not data. It comes from the MY_AI_ADMIN_USERS
environment variable rather than a flag in users.json, for two reasons:

1. A route that grants admin would be a privilege-escalation surface, and one
   worth avoiding entirely rather than guarding carefully.
2. Whoever controls the process already controls the database file. Making the
   process's own environment the source of authority does not weaken anything,
   and it keeps the grant visible at startup instead of buried in a JSON blob.

**Unset means nobody is an admin, and every /admin route refuses.** An auth
feature that defaults open is worse than no auth feature, because it looks
protected. The refusal message says exactly what to set.
"""

import os

ADMIN_USERS_ENV = "MY_AI_ADMIN_USERS"


def admin_usernames() -> set[str]:
    """Read at call time, not import time, so tests and a restarted process
    both see the current value rather than whatever was set when this module
    first loaded."""
    raw = os.environ.get(ADMIN_USERS_ENV, "")
    return {name.strip().lower() for name in raw.split(",") if name.strip()}


def is_admin(username: str) -> bool:
    return username.strip().lower() in admin_usernames()


NO_ADMINS_CONFIGURED = (
    f"No superusers are configured, so administrative routes are closed. "
    f"Set {ADMIN_USERS_ENV} to a comma-separated list of usernames and restart the backend."
)

NOT_AN_ADMIN = "This account is not authorized for administrative access."
