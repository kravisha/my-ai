"""Which backend account *is* the Gateway (TASK_QUEUE TQ-69,
docs/SPEC_RECONCILIATION.md §110).

Source: spec §4.2, §4.4, §9.3.

The `/portfolios` surface accepts an **asserted subject**: the Gateway says "I am
acting for this client", and the backend authorizes that client against that
portfolio. Everything about that arrangement rests on one question - *may this
caller assert a subject at all?* - and this module is where it is answered.

## Configuration, not data, for the same reasons as `app/admin_auth.py`

Read from the environment rather than from `users.json`, because a route that
could grant this would be a privilege-escalation surface worth not having, and
because whoever controls the process already controls its database.

It is the **same variable the Gateway logs in with** (`GATEWAY_BACKEND_USER`,
`gateway/jarvis.py`), deliberately. Both processes are configured from the same
`.env`, and a second variable naming the same account is two models of one fact -
the house rule this project has enforced four times (§70, §100, §104, §106). The
failure it prevents is specific and quiet: the Gateway logging in as one account
while the backend expects another produces a 403 on every portfolio call, which
reads exactly like a permissions bug and is a typo.

## Unset means nobody, and the surface is closed

`admin_auth`'s rule, and the reason is the same: an authorization check that
defaults open is worse than none, because it looks protected. Here it is sharper
than usual - **a surface that accepts an asserted subject from anyone is worse
than no surface at all**, since it would let any authenticated backend user read
any client's portfolio (spec §9.3). Unset therefore refuses everybody, and the
message says what to set.

## This is not admin, and must not be folded into it

`MY_AI_ADMIN_USERS` answers "may this person look at the organization's own
state". This answers "is this caller the Gateway". They happen to name the same
account today, because the Gateway's backend user must be an admin to read
`/admin` - and they are still different questions. Collapsing them would mean
adding an operator to the admin list silently granted them the ability to read
every client's portfolio by asserting an owner, which nobody would intend and
nothing would announce.
"""

import os

GATEWAY_USER_ENV = "GATEWAY_BACKEND_USER"


def gateway_username() -> str | None:
    """Read at call time rather than import time, so a test and a restarted
    process both see the current value."""
    return (os.environ.get(GATEWAY_USER_ENV, "") or "").strip().lower() or None


def is_gateway(username: str) -> bool:
    configured = gateway_username()
    if configured is None:
        return False
    return (username or "").strip().lower() == configured


NO_GATEWAY_CONFIGURED = (
    f"No Gateway account is configured, so the on-behalf-of portfolio surface is closed. "
    f"Set {GATEWAY_USER_ENV} to the backend account the Gateway logs in with, and restart "
    f"the backend."
)

NOT_THE_GATEWAY = (
    "This account may not act on behalf of another owner. The portfolio surface is "
    "reachable only by the Gateway's own backend account."
)
