"""Who is responsible for noticing that somebody stopped doing their job.

The Fault Tolerance and Organizational Resilience Framework's core rule is two
lines: NO CRITICAL FAILURE GOES UNNOTICED, NO NOTICED FAILURE GOES OWNERLESS. Its
§16 is equally firm about how *not* to achieve that - "do not implement this as
every agent continuously monitoring every other agent" - so monitoring follows
declared relationships and nothing else.

This module is those relationships, in one place, because §3 requires the system
to *know* them rather than have them emerge from whichever loop happens to scan
whichever table.

## The map, and why it is shaped like this

    controller  watches  coo          and can recover it
    coo         watches  the workforce and can request recovery
    coo         watches  controller    and can only report it

**The Controller watches the COO** because the Controller is COO's manager
(`docs/organization.yaml`: `coo.reports_to: controller`) *and* the only thing that
may start a process (addendum 11 §15). Detection and authority land on the same
entity, which is the arrangement the framework asks for in §4 and the one that
needs no new authority to act.

**The COO watches the workforce** and already did - `agents/coo.py`'s health
evaluation is the oldest fault-tolerance mechanism in this system. What is new is
that its detections are now recorded as incidents instead of only as a state
change on a registry row.

**Nobody can recover the Controller, and that is declared rather than hidden.**
The Controller is the server process; a dead server cannot restart itself from the
inside, and an in-process watcher would die with the thing it watches. COO does
detect its silence - the heartbeat stops advancing and COO marks it crashed - so
the failure is *noticed*. Recovery belongs to a human or to whatever supervises
the process, and `RECOVERY_OWNER` says so in as many words. The framework's §17
defers "who monitors the CEO/top-level authority"; this is that deferral made
explicit at the level the system actually has.

## Why this is not a mutual-watching hazard

COO watches the Controller and the Controller watches COO, which looks like the
circular relationship §18 asks about. It is safe only because the loop is
asymmetric: **exactly one direction carries recovery authority.** The Controller
can restart COO; COO cannot restart the Controller and does not try. Two watchers
that could each restart the other would thrash, each interpreting the other's
restart as a failure. If anything ever gains the authority to restart the server,
this asymmetry is what it breaks.

## Health expectations

§6 says presence is more than a process existing, and that each role may have its
own expectation. Today there is one measured threshold for every role
(`agents/coo.py`'s HEALTH_STALE_THRESHOLD_SECONDS, raised to 45s after real
duplicate-spawn incidents), and inventing per-role numbers without measuring them
is precisely what this project does not do. The structure below takes an override
per role so that a measured difference has somewhere to live; the absence of
entries is the honest current state, not an oversight.
"""

# Named here rather than imported from backend/controller.py, which imports this
# module: the relationship map is the lower layer and must not reach up into the
# thing that consults it. tests/test_watch.py asserts the two agree, so the
# duplication is checked rather than trusted.
CONTROLLER_ROLE = "controller"
COO_ROLE = "coo"

# Watcher -> the roles it is responsible for noticing the silence of.
WATCHES = {
    CONTROLLER_ROLE: (COO_ROLE,),
    COO_ROLE: ("explorer", "speculator", "analysis", "dummy", "speaker", CONTROLLER_ROLE),
}

# The inverse, which is the question actually asked: who is watching this role?
WATCHED_BY = {
    watched: watcher for watcher, watched_roles in WATCHES.items() for watched in watched_roles
}

# Where a detected failure goes when the watcher cannot fix it. A role absent from
# here is recoverable by its watcher; a role present here is one whose recovery
# lives outside this system, and the value names who owns it.
RECOVERY_OWNER = {
    CONTROLLER_ROLE: "human operator (the Controller is the server process; it cannot restart itself)",
}

# Per-role overrides for how long silence is tolerated. Deliberately empty: one
# threshold has been measured, and a second number without a measurement behind it
# would be a guess wearing the costume of a policy.
SILENCE_OVERRIDES: dict[str, float] = {}


def silence_threshold_seconds(role: str, default: float) -> float:
    """How long this role may go quiet before it is treated as failed."""
    return SILENCE_OVERRIDES.get(role, default)


def watcher_of(role: str) -> str | None:
    return WATCHED_BY.get(role)


def recovery_owner(role: str) -> str | None:
    """Who restores this role, when the watcher cannot. None means its watcher
    can, which is the ordinary case."""
    return RECOVERY_OWNER.get(role)


def unwatched(roles) -> list[str]:
    """Roles nobody is responsible for noticing - the framework's §5 question,
    asked of a live roster rather than of this file.

    Used by a test against the roles that actually exist, so adding a role
    without giving it a watcher fails the suite instead of creating a silent
    hole years before anybody looks."""
    return sorted(role for role in set(roles) if role not in WATCHED_BY)
