"""Who may see what through the Gateway (addendum 40 §13.2/§14, addendum 41
§23, addendum 43 §15/§16; TASK_QUEUE TQ-34, docs/SPEC_RECONCILIATION.md §92).

## The rule this exists to enforce

Addendum 40 §14, and it is the sentence the whole module is shaped by:

    "The presentation layer must never bypass backend authorization just
     because information exists on the server."

Which is to say: hiding a panel is not a permission. Every route decides for
itself what it requires, and a role that lacks it is refused at the boundary
whether or not any interface ever offered it a button.

## What was actually wrong before

Not that the Gateway was insecure - it authenticates, hashes its session
tokens, rate-limits logins and refuses everything when unconfigured. What it
could not do was *say* what any route required. `Depends(require_session)`
means "any valid session", which with one credential is indistinguishable from
"the Super User", and the difference only becomes visible on the day a second
credential exists. Then it is visible as a breach.

So the capability is declared per route and checked per request, and a test
walks every route in the application asserting that none is reachable without
one. A new route cannot quietly join the world-readable set, because there is
no world-readable set left.

## The three roles

From addendum 41 §23 and addendum 43 §15, which agree:

- **operator** - the COO-level user. The full command centre. This is the
  existing Super User under a name that says what it is.
- **internal** - staff and internal agents. Role-relevant views, and
  deliberately not the operational surfaces §14 says must be withheld from
  roles that do not require them.
- **client** - "usually interact with a personal representative agent rather
  than seeing the entire organization" (43 §15). One capability: talk to the
  agent. Everything else is refused at the route.

## Fail closed, in the two places it matters

An unknown role has no capabilities *and raises* rather than returning an empty
set, because a typo that silently denies everything looks exactly like a
correctly-configured lockout and would be debugged as one. An unknown
capability raises for the same reason - and it can only come from a route's own
declaration, never from a request, so raising surfaces it in the test suite
rather than in production.

## Not machinery without a user

Only the operator credential is configured on any machine today, and the other
two roles refuse every login until somebody sets their environment variables.
That is deliberately *not* the same as an unused table: the enforcement path
runs on every request the Gateway already serves, and it is what makes the
current single-role deployment explicit instead of accidental. The second
credential is one environment variable away, and the day it exists the boundary
is already built and already tested rather than being written in a hurry
alongside it.
"""

from __future__ import annotations

# Addendum 41 §23 / addendum 43 §15. A closed vocabulary: a session carrying
# anything else is refused rather than interpreted.
ROLE_OPERATOR = "operator"
ROLE_INTERNAL = "internal"
ROLE_CLIENT = "client"
ROLES = (ROLE_OPERATOR, ROLE_INTERNAL, ROLE_CLIENT)

# One capability per thing a route can do, named for the surface rather than for
# the role that happens to hold it today - so re-granting is a change to GRANTS
# and never a change to a route.
CAP_SCOREBOARD_READ = "scoreboard:read"
CAP_SCOREBOARD_WRITE = "scoreboard:write"
CAP_TECHNOLOGY_READ = "technology:read"
CAP_TECHNOLOGY_FILE = "technology:file"
CAP_SYSTEM_STATUS = "system:status"
CAP_CONVERSE = "converse"
CAP_SESSION = "session"
CAP_REPOSITORY_READ = "repository:read"
CAP_PUBLISH = "publish"
# The full command centre - the same studio the desktop console shows, because
# addendum 40 §13.1 forbids a duplicate: "The Gateway is a secure
# browser-accessible window into the same running organization."
CAP_STUDIO = "studio"
# A client's own holdings - what they have told their representative they hold
# (TQ-42, §96). Subject-scoped by construction: every function behind it takes
# the client id, so the capability cannot reach anybody else's positions.
CAP_HOLDINGS = "holdings"

CAPABILITIES = (
    CAP_SCOREBOARD_READ, CAP_SCOREBOARD_WRITE, CAP_TECHNOLOGY_READ,
    CAP_TECHNOLOGY_FILE, CAP_SYSTEM_STATUS, CAP_CONVERSE, CAP_SESSION,
    CAP_REPOSITORY_READ, CAP_PUBLISH, CAP_STUDIO, CAP_HOLDINGS,
)

# What each capability guards, in the words an operator would use. Carried here
# rather than in comments because `/auth/whoami` returns it: a client told only
# "403" learns nothing, and a client told what it does not have learns exactly
# what to ask for.
DESCRIPTIONS = {
    CAP_SCOREBOARD_READ: "read the project scoreboard",
    CAP_SCOREBOARD_WRITE: "file, annotate and resolve scoreboard items",
    CAP_TECHNOLOGY_READ: "read the technology and architecture review",
    CAP_TECHNOLOGY_FILE: "file review findings onto the scoreboard",
    CAP_SYSTEM_STATUS: "see the running organization's operational status",
    CAP_CONVERSE: "talk to the agent",
    CAP_SESSION: "end your own session",
    CAP_REPOSITORY_READ: "list and read the project's source files",
    CAP_PUBLISH: "publish documents into the repository",
    CAP_STUDIO: "see the full command centre",
    CAP_HOLDINGS: "record and review the holdings you have told me about",
}

# §14: "Sensitive operational views must be withheld from roles that do not
# require them."
#
# The scoreboard is the operator's own decision board and the technology review
# reads this machine, so both stay operator-only for reading and writing. The
# organization's operational status is the clearest example of §14's sentence -
# internal staff have a reason to see whether the system is up; a client has
# none, and "the data is already on the server" is not that reason.
GRANTS: dict[str, frozenset[str]] = {
    ROLE_OPERATOR: frozenset(CAPABILITIES),
    ROLE_INTERNAL: frozenset({
        CAP_SCOREBOARD_READ, CAP_TECHNOLOGY_READ, CAP_SYSTEM_STATUS,
        CAP_CONVERSE, CAP_SESSION,
    }),
    # 43 §15: clients "usually interact with a personal representative agent
    # rather than seeing the entire organization". One surface, and it is a
    # conversation.
    # Holdings reach the client because this is the role with nowhere else to
    # keep them (§96). The operator holds the capability too - every role
    # invariant here is "operator has all of them", and carving out an
    # exception would be a surprise for a smaller gain than it costs - but the
    # operator already owns a portfolio properly through app/tools/portfolio.py.
    # Naming is what keeps those apart: these are holdings *told to a
    # representative*, never a broker account and never data/portfolio.xlsx.
    ROLE_CLIENT: frozenset({CAP_CONVERSE, CAP_SESSION, CAP_HOLDINGS}),
}


class UnknownRole(ValueError):
    """A session carrying a role this build does not know.

    Raised rather than resolved to "no capabilities", because a typo that
    silently denies everything is indistinguishable from a correct lockout and
    gets debugged as one."""


class UnknownCapability(ValueError):
    """A route asked for a capability that does not exist.

    Can only come from a route's own declaration, never from a request - so
    raising surfaces it in the suite rather than in production, and returning
    False would let a mistyped requirement look like a working restriction."""


def capabilities(role: str) -> frozenset[str]:
    if role not in GRANTS:
        raise UnknownRole(f"unknown Gateway role {role!r}; known roles are {list(ROLES)}")
    return GRANTS[role]


def allows(role: str, capability: str) -> bool:
    if capability not in CAPABILITIES:
        raise UnknownCapability(
            f"unknown capability {capability!r}; declared capabilities are {list(CAPABILITIES)}")
    return capability in capabilities(role)


def describe(role: str) -> dict:
    """What a role may do, in a shape a client can render.

    Includes what it *cannot* do as well, which is the more useful half: an
    interface that knows which surfaces are refused can say so plainly instead
    of offering a control that returns 403."""
    granted = capabilities(role)
    return {
        "role": role,
        "capabilities": sorted(granted),
        "granted": {cap: DESCRIPTIONS[cap] for cap in sorted(granted)},
        "withheld": {cap: DESCRIPTIONS[cap] for cap in sorted(set(CAPABILITIES) - granted)},
    }
