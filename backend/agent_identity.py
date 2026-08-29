"""Who an agent *is*, independent of what it is called and what it does
(TASK_QUEUE TQ-97; addendum 51 §2, §3, §5, §6; addendum 49 §20; addendum 50 §11,
§12; docs/SPEC_RECONCILIATION.md §140).

Addendum 51 §26 names persistent agent identity as implementation priority one,
and everything else in Providence keys off it: a personal agent cannot be bound
to a client without one, and a career cannot be preserved across a role change
without one.

## Most of this was already built, and one part of it was built wrong

The owner decision of 2026-08-17 already separated the two things §140 §4 says
Providence needs separated: **the agent is not the job.** `agent_names.name` is
the durable agent, `agent_registry.identity` is the desk it currently sits at,
`agent_assignments` records which occupied which and when, and no work row is
ever denormalised against a name. Addendum 51 §2's *"Jack Explore Agent 1"* is
that model with a rendering rule on top.

What is wrong is what the durable thing *is*. Addendum 51 §3:

> agent_id — *"Unique. Persistent. Never reused. Independent of display name.
> Independent of current role."*

Today the durable identity **is** the display name. `agent_names.name` is the
primary key everything joins on, and it is the word a human reads. That fails
§3's fourth clause by construction, and this project already has the function
that turns the failure into a defect: `coo_identity.rename()` exists, is
deliberate, and is documented as *"explicit, reasoned, and recorded"*. A rename
of a name-keyed agent either breaks every join or silently re-attributes its
history to whoever holds the name next.

**Never reused** fails the same way, more quietly. The pool is forty first names.
Nothing today releases one, so nothing has been reused - but that is an absence
of a function rather than a guarantee, and §105's habit in this project is to
make the guarantee rather than rely on the gap.

So this module introduces the id and demotes the name to what §3 says it is: a
display attribute of a durable thing, rather than the durable thing.

## The last name is derived, never stored

Addendum 51 §5 lists `first_name`, `last_name`, `display_name`, `current_role`
and `role_version` as separate stored fields. Storing the last name **and** the
role is two places for one fact, which is the collision addendum 47 §5 forbids
and which §122 spent an increment undoing.

§2 says the last name *"is the role or system designation"* - so it is not an
independent fact about the agent, it is a rendering of the desk the agent
currently occupies. It is derived here, from the open assignment, and that is
what makes addendum 50 §12's career path work: **Jack Explore Agent 1 becomes
Jack Reporter Agent 1 without becoming a second agent**, because only the desk
moved and `agent_id` did not.

An agent occupying no desk has no last name, and `display_name` is the first name
alone. Not a placeholder, not a stale previous role - `unknown` where a plausible
default would otherwise go (§100, §104, §118, §132).

## Lifecycle: eight states, and two of them already exist under other names

Addendum 51 §6 suggests CREATED, TRAINING, ACTIVE, WAITING, PAUSED, EVOLVING,
RETIRED, ARCHIVED. `agent_registry.lifecycle_state` already carries `active` and
`dormant`, and `process_state` carries `running`/`stopped`/`crashed`.

**Those are not the same vocabulary and are deliberately not merged.** The
registry's states describe *a process at a desk* - is this slot staffed, is that
process up. §6's states describe *an agent's existence* - has it been created,
is it training, has it been retired. An agent can be RETIRED while its desk is
`active` and staffed by somebody else, and the two answers are both correct.

Only the states something can actually produce are accepted, on the entry rule
`simulation/faults.py` keeps: a vocabulary listing what nothing can cause reads
as a capability. TRAINING, EVOLVING and ARCHIVED are named in `SPECIFIED_STATES`
and refused by `set_lifecycle` until something produces them.

Sits below `fi_db` (which creates this schema), so it must not import it.
"""

from __future__ import annotations

import re
import uuid

from backend.db import Database, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_identities (
    -- Addendum 51 §3. Opaque on purpose: an id a human can read is an id
    -- somebody will eventually parse, and then it is a fact rather than a key.
    agent_id TEXT PRIMARY KEY,
    -- The display name (addendum 51 §2's FIRST NAME), from the approved pool in
    -- fi_db.AGENT_NAME_POOL. Changeable, which is the whole reason the id exists.
    first_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    -- §6's existence states. NOT the registry's lifecycle_state, which describes
    -- a process at a desk. See the module docstring.
    lifecycle_state TEXT NOT NULL DEFAULT 'created',
    activated_at TEXT,
    retired_at TEXT,
    -- Addendum 51 §5: which agent spawned this one, where that is known. NULL
    -- means nobody did - the baseline workforce - and never a guess.
    parent_agent_id TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);
-- One agent per name *at a time*. Not UNIQUE across history: a name released by
-- a retired agent stays attached to that agent's record forever, which is what
-- `name_history` is for.
CREATE UNIQUE INDEX IF NOT EXISTS agent_identities_current_name
    ON agent_identities (first_name) WHERE retired_at IS NULL;

-- Every name an agent has ever been called, and when. Addendum 51 §3's "never
-- reused" is enforced against THIS table rather than against the current
-- binding: a name freed by a rename must not become somebody else's, or the
-- organization's own record of who did what stops being readable.
CREATE TABLE IF NOT EXISTS agent_name_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    first_name TEXT NOT NULL,
    held_from TEXT NOT NULL,
    held_until TEXT,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS agent_name_history_name ON agent_name_history (first_name);
CREATE INDEX IF NOT EXISTS agent_name_history_agent ON agent_name_history (agent_id, id);
"""

SCHEMA_VERSION = 1

# Addendum 51 §6, in full, so the specified vocabulary is visible.
STATE_CREATED = "created"
STATE_TRAINING = "training"
STATE_ACTIVE = "active"
STATE_WAITING = "waiting"
STATE_PAUSED = "paused"
STATE_EVOLVING = "evolving"
STATE_RETIRED = "retired"
STATE_ARCHIVED = "archived"
SPECIFIED_STATES = (STATE_CREATED, STATE_TRAINING, STATE_ACTIVE, STATE_WAITING,
                    STATE_PAUSED, STATE_EVOLVING, STATE_RETIRED, STATE_ARCHIVED)

# What this system can actually put an agent into today. The rest are refused
# rather than accepted-and-unused: nothing here trains, evolves or archives, and
# a state nothing produces reads as a capability the system has (§49).
REACHABLE_STATES = (STATE_CREATED, STATE_ACTIVE, STATE_WAITING, STATE_PAUSED,
                    STATE_RETIRED)

# `explorer-1` -> ("explorer", "1"). The desk identity's shape, which
# backend/controller.py's `_slot_identity` produces.
_SLOT = re.compile(r"^(?P<role>[a-z_]+)-(?P<number>\d+)$")

# Roles whose designation is not `<Role> Agent <n>`. From addendum 51 §2's own
# example - *"Kumbhakarnan COO"*, with no slot number, because there is one COO
# and numbering a singleton implies a second. Data taken from the specification,
# never a rule inferred from it.
DESIGNATIONS = {"coo": "COO"}


class IdentityRefused(ValueError):
    """An identity operation this system will not perform."""


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)


def create(conn: Database, *, first_name: str, parent_agent_id: str | None = None) -> str:
    """Bring an agent into existence and return its permanent id.

    The id is a uuid4 and is generated here rather than derived from anything -
    a derived id is a fact about the moment of creation, and addendum 51 §3 asks
    for an identifier that is independent of everything, including that.

    **Refuses a name any agent has ever held.** Not merely a name currently in
    use: §3's *never reused* is about the organization's record staying readable,
    and a name freed by a rename that later belongs to somebody else makes every
    older sentence about it ambiguous."""
    first_name = (first_name or "").strip()
    if not first_name:
        raise IdentityRefused("An agent needs a name to be called by.")
    prior = conn.fetchone(
        "SELECT agent_id FROM agent_name_history WHERE first_name = ? LIMIT 1", (first_name,))
    if prior is not None:
        raise IdentityRefused(
            f"{first_name!r} has been held by agent {prior['agent_id']} and is not reusable "
            f"(addendum 51 §3). A name that changes hands makes the organization's own "
            f"record of who did what ambiguous.")
    if parent_agent_id is not None and get(conn, parent_agent_id) is None:
        raise IdentityRefused(
            f"No agent {parent_agent_id!r} to be the parent. An unresolvable parent is worse "
            f"than none: it asserts a lineage nobody can follow.")

    agent_id = str(uuid.uuid4())
    stamp = now_iso()
    conn.execute(
        "INSERT INTO agent_identities (agent_id, first_name, created_at, lifecycle_state,"
        " parent_agent_id) VALUES (?, ?, ?, ?, ?)",
        (agent_id, first_name, stamp, STATE_CREATED, parent_agent_id))
    conn.execute(
        "INSERT INTO agent_name_history (agent_id, first_name, held_from, reason)"
        " VALUES (?, ?, ?, ?)",
        (agent_id, first_name, stamp, "created"))
    return agent_id


def rename(conn: Database, agent_id: str, *, first_name: str, reason: str) -> None:
    """Change what an agent is called. It remains the same agent.

    **This is the function the id exists for.** Before it, the durable identity
    was the display name, so this operation either broke every join or handed one
    agent's history to another. Now it moves one column and closes a span.

    The old name is not returned to the pool - see `create`."""
    agent = require(conn, agent_id)
    first_name = (first_name or "").strip()
    if not first_name:
        raise IdentityRefused("A rename needs the new name.")
    if not (reason or "").strip():
        raise IdentityRefused(
            "A rename needs its reason. `coo_identity.rename` set the standard: explicit, "
            "reasoned and recorded, so that redeploying can never look like a new person.")
    if first_name == agent["first_name"]:
        return
    prior = conn.fetchone(
        "SELECT agent_id FROM agent_name_history WHERE first_name = ? LIMIT 1", (first_name,))
    if prior is not None:
        raise IdentityRefused(
            f"{first_name!r} has been held by agent {prior['agent_id']} and is not reusable "
            f"(addendum 51 §3).")

    stamp = now_iso()
    with conn.transaction():
        conn.execute(
            "UPDATE agent_name_history SET held_until = ?, reason = COALESCE(reason, ?)"
            " WHERE agent_id = ? AND held_until IS NULL",
            (stamp, reason.strip(), agent_id))
        conn.execute("UPDATE agent_identities SET first_name = ? WHERE agent_id = ?",
                     (first_name, agent_id))
        conn.execute(
            "INSERT INTO agent_name_history (agent_id, first_name, held_from, reason)"
            " VALUES (?, ?, ?, ?)",
            (agent_id, first_name, stamp, reason.strip()))
        # The name pool moves with the agent (TQ-99). `agent_names` records which
        # of the forty names are taken and by whom; leaving the binding on the old
        # row would make `fi_db.agent_id_for_name` answer for a name this agent no
        # longer holds and answer nothing for the one it does.
        #
        # The old row keeps `agent_id` NULL and is **not** returned to the pool:
        # `create` refuses a name any agent has ever held, so a released name stays
        # spent. That is deliberate - a name that changed hands would make every
        # older sentence about it ambiguous.
        desk = conn.fetchone(
            "SELECT assigned_to_identity FROM agent_names WHERE agent_id = ?", (agent_id,))
        conn.execute(
            "UPDATE agent_names SET agent_id = NULL, assigned_to_identity = NULL"
            " WHERE agent_id = ?", (agent_id,))
        conn.execute(
            "INSERT INTO agent_names (name, assigned_to_identity, assigned_at, reserved,"
            " agent_id, schema_version) VALUES (?, ?, ?, 0, ?, 1)"
            " ON CONFLICT (name) DO UPDATE SET assigned_to_identity = excluded.assigned_to_identity,"
            " assigned_at = excluded.assigned_at, agent_id = excluded.agent_id",
            (first_name, desk["assigned_to_identity"] if desk else None, stamp, agent_id))
        # Spans and personnel events keep the name they were written under - what
        # the record said at the time is a fact - and are found by `agent_id`.
        conn.execute("UPDATE agent_assignments SET agent_id = ? WHERE agent_id IS NULL"
                     " AND name = (SELECT first_name FROM agent_identities WHERE agent_id = ?)",
                     (agent_id, agent_id))


def set_lifecycle(conn: Database, agent_id: str, state: str) -> None:
    """Move an agent through addendum 51 §6's existence states.

    Refuses a state this system cannot produce, rather than storing it. A row
    reading `training` in an organization with no path into training would be a
    capability asserted by a column - §49's failure, and the reason
    `agent_registry` still has no certification column."""
    require(conn, agent_id)
    if state not in REACHABLE_STATES:
        known = f"{list(REACHABLE_STATES)}"
        if state in SPECIFIED_STATES:
            raise IdentityRefused(
                f"{state!r} is specified by addendum 51 §6 and nothing in this system produces "
                f"it. Storing it would assert a capability that does not exist. Reachable "
                f"today: {known}.")
        raise IdentityRefused(f"unknown lifecycle state {state!r}; reachable are {known}")
    stamp = now_iso()
    conn.execute("UPDATE agent_identities SET lifecycle_state = ? WHERE agent_id = ?",
                 (state, agent_id))
    if state == STATE_ACTIVE:
        # First activation only. An agent that pauses and resumes was activated
        # once, and overwriting it would lose when this agent's working life began.
        conn.execute(
            "UPDATE agent_identities SET activated_at = ? WHERE agent_id = ? "
            "AND activated_at IS NULL", (stamp, agent_id))
    if state == STATE_RETIRED:
        conn.execute("UPDATE agent_identities SET retired_at = ? WHERE agent_id = ?",
                     (stamp, agent_id))


def role_designation(identity: str | None) -> str | None:
    """Addendum 51 §2's LAST NAME: the role or system designation, rendered.

    `explorer-1` becomes `Explorer Agent 1`; `coo-1` becomes `COO`.

    **The role is used as the organization spells it, not stemmed toward §2's
    example.** §2 gives two: *"Kumbhakarnan COO"* and *"Jack Explore Agent 1"*.
    The second would need `explorer` turned into `Explore`, and any rule that
    does it (drop a trailing `r`? a trailing `er`?) turns `speculator` into
    something nobody chose. A transformation invented to match one example is a
    guess with a regex around it, and the roles are already named authoritatively
    in `organization.yaml`. The difference between *Explore Agent 1* and
    *Explorer Agent 1* is cosmetic; a role whose designation is genuinely
    different declares it below rather than being derived into.

    Returns None for a desk this cannot parse and for no desk at all - **an
    agent occupying no desk has no last name**, and inventing one would be a
    plausible default where the honest answer is that there is nothing to say."""
    if not identity:
        return None
    match = _SLOT.match(identity.strip().lower())
    if match is None:
        return None
    role, number = match["role"], match["number"]
    if role in DESIGNATIONS:
        return DESIGNATIONS[role]
    return f"{role.replace('_', ' ').title()} Agent {number}"


def display_name(conn: Database, agent_id: str, *, identity: str | None = None) -> str:
    """Addendum 51 §2's human-facing identity: FIRST NAME + LAST NAME.

    Composed rather than stored, so the two cannot disagree. An agent that moves
    desks changes what it is called and stays the same agent - which is exactly
    addendum 50 §12's career path, and it costs nothing here because the last
    name was never a fact about the agent in the first place."""
    agent = require(conn, agent_id)
    last = role_designation(identity)
    return agent["first_name"] if last is None else f"{agent['first_name']} {last}"


def get(conn: Database, agent_id: str) -> dict | None:
    return conn.fetchone("SELECT * FROM agent_identities WHERE agent_id = ?", (agent_id,))


def require(conn: Database, agent_id: str) -> dict:
    agent = get(conn, agent_id)
    if agent is None:
        raise IdentityRefused(f"No agent {agent_id!r}.")
    return agent


def by_name(conn: Database, first_name: str) -> dict | None:
    """The agent currently called this, or None.

    Deliberately *currently*: a retired agent keeps its name in the record and
    does not answer to a lookup, because the caller asking by name wants whoever
    is working under it. `history_of_name` answers the other question."""
    return conn.fetchone(
        "SELECT * FROM agent_identities WHERE first_name = ? AND retired_at IS NULL",
        (first_name,))


def history_of_name(conn: Database, first_name: str) -> list[dict]:
    """Every agent that has ever held this name, oldest first.

    Under `create`'s rule this is at most one agent, possibly across several
    spans. It returns a list anyway: a query that structurally cannot show a
    violation cannot be used to check for one."""
    return conn.fetchall(
        "SELECT * FROM agent_name_history WHERE first_name = ? ORDER BY id", (first_name,))


def names_of(conn: Database, agent_id: str) -> list[dict]:
    return conn.fetchall(
        "SELECT * FROM agent_name_history WHERE agent_id = ? ORDER BY id", (agent_id,))


def roster(conn: Database) -> list[dict]:
    return conn.fetchall(
        "SELECT * FROM agent_identities WHERE retired_at IS NULL ORDER BY created_at, agent_id")


def ensure_for_name(conn: Database, first_name: str, *, created_at: str | None = None) -> str:
    """The agent called this, creating it if the name predates identities (TQ-99).

    **The lazy-backfill path**, and it is the shape `fi_db._ensure_assignment`
    already uses for the same reason: a database whose names were bound before
    `agent_identities` existed acquires its ids on the next registration, without
    a migration step and without a converter that has to be right on its first
    ever run.

    `created_at` backdates the identity to when the name was actually bound.
    Left to `now()`, every agent that predates TQ-97 would appear to have been
    created at the moment somebody happened to restart the system - and
    `_ensure_assignment` records what that costs: spans starting at backfill time
    place every prior hour of work outside every span, attributed to nobody.

    Idempotent by construction: `by_name` answers first, so this is safe to call
    on every registration, which is exactly where it is called from."""
    first_name = (first_name or "").strip()
    if not first_name:
        raise IdentityRefused("A name is needed to find or create the agent called it.")
    existing = by_name(conn, first_name)
    if existing is not None:
        return existing["agent_id"]

    # Not `create()`: that refuses a name any agent has *ever* held, which is the
    # right rule for a fresh assignment and the wrong one here. A name in
    # `agent_names` with no identity is not a reused name - it is a name from
    # before identities existed, and the agent that holds it is the one being
    # given an id now. Refusing it would make the backfill impossible.
    prior = conn.fetchone(
        "SELECT agent_id FROM agent_name_history WHERE first_name = ? AND held_until IS NULL",
        (first_name,))
    if prior is not None:
        return prior["agent_id"]

    agent_id = str(uuid.uuid4())
    stamp = created_at or now_iso()
    conn.execute(
        "INSERT INTO agent_identities (agent_id, first_name, created_at, lifecycle_state)"
        " VALUES (?, ?, ?, ?)",
        (agent_id, first_name, stamp, STATE_ACTIVE))
    conn.execute(
        "INSERT INTO agent_name_history (agent_id, first_name, held_from, reason)"
        " VALUES (?, ?, ?, ?)",
        (agent_id, first_name, stamp, "adopted an existing name on registration"))
    conn.execute(
        "UPDATE agent_identities SET activated_at = ? WHERE agent_id = ? AND activated_at IS NULL",
        (stamp, agent_id))
    return agent_id
