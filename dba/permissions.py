"""Who may ask the DBA for what (§14, §15, §16, §2.2).

Fail closed, in the shape `gateway/roles.py` already established here: an agent
nobody declared has no permissions **and the refusal says so**, because an
unknown name that silently denied everything would look exactly like a
correctly-configured lockout and be debugged as one.

## Two axes, not one

An operation needs a permission (`update`), and the **record** may need a
second one (`write_sensitive`). §15 says security policy may vary by
classification, and one flat list cannot express "may update a task, may not
update a person's medical note". So `required_for` answers the first and
`sensitivity_permission` the second, and `check` refuses if either is missing.

## §2.2, stated as policy rather than assumed

    *"Other agents may be permitted to contact the DBA directly only when
    explicitly authorized by system policy."*

`POLICY` is that policy. Jarvis is the orchestrator and holds most of it. The
learning engine gets reads only - it should be able to answer a question from
stored records without being able to change one. Everything else is refused
until somebody adds a line here, which is a code change with a diff and a
review rather than a sentence in a conversation.
"""

from __future__ import annotations

from dba import entities

READ = "read"
CREATE = "create"
UPDATE = "update"
ARCHIVE = "archive"
DELETE = "delete"
ADMINISTER = "administer"
READ_SENSITIVE = "read_sensitive"
WRITE_SENSITIVE = "write_sensitive"

PERMISSIONS = (READ, CREATE, UPDATE, ARCHIVE, DELETE, ADMINISTER,
               READ_SENSITIVE, WRITE_SENSITIVE)

# The agent Jarvis identifies itself as. A constant rather than a literal
# scattered through call sites, so renaming the orchestrator is one edit.
JARVIS = "JARVIS"
LEARNING_ENGINE = "learning_engine"
OPERATOR_CONSOLE = "operator_console"
# The DBA acting as itself: designing capabilities, running their self-checks,
# recording its own design experience (§11). Deliberately NOT an agent that can
# publish - see POLICY below.
DBA = "dba"
# §13: any agent on this machine may need persistent state. The COO is the
# first of the backend's own agents to have one.
COO = "coo"

POLICY: dict[str, frozenset[str]] = {
    # The orchestrator. Everything except `delete` and `administer`: §5.6 wants
    # hard deletion restricted, and a coordinator that can erase history is a
    # coordinator whose mistakes cannot be reconstructed. Krish's own console
    # holds those two.
    JARVIS: frozenset({READ, CREATE, UPDATE, ARCHIVE, READ_SENSITIVE,
                       WRITE_SENSITIVE}),
    # Krish, through the operator surface. The only holder of `delete` and
    # `administer`.
    OPERATOR_CONSOLE: frozenset(PERMISSIONS),
    # Reads only, and nothing sensitive. A skill that summarises stored records
    # is exactly Document 1 §4.4's deterministic replacement for a model call;
    # a skill that can change one is a different proposition entirely.
    LEARNING_ENGINE: frozenset({READ}),
    # THE DBA'S OWN HANDS, AND WHAT THEY CANNOT REACH. It designs capabilities,
    # stages them and runs their self-checks, so it needs to create and update
    # records of its own. It does NOT hold `administer`, which is what
    # publishing a capability requires - so the agent that designs a new data
    # surface cannot be the one that brings it into service. That is §31's
    # stage 2 made structural rather than procedural, and it is the same shape
    # as `register_learned_skill` refusing without Krish.
    DBA: frozenset({READ, CREATE, UPDATE, ARCHIVE, READ_SENSITIVE,
                    WRITE_SENSITIVE}),
    # §13's "any agent operating on the computer may require persistent state".
    # Ordinary working access, nothing sensitive, no deletion.
    COO: frozenset({READ, CREATE, UPDATE}),
}

# §8's actions mapped to the permission each needs. Not derived from the action
# name: `delete_authorized` needs `delete`, and the two vocabularies are
# deliberately allowed to differ.
REQUIRED: dict[str, str] = {
    "create": CREATE,
    "get": READ,
    "find": READ,
    "search": READ,
    "list": READ,
    "count": READ,
    "history": READ,
    "validate": READ,
    "update": UPDATE,
    "archive": ARCHIVE,
    "delete_authorized": DELETE,
    "link": UPDATE,
    "unlink": UPDATE,
    "reconcile": UPDATE,
    "begin_transaction": READ,
    "commit_transaction": READ,
    "rollback_transaction": READ,
}

# §15: which classifications need the sensitive permissions.
SENSITIVE_CLASSIFICATIONS = (entities.SENSITIVE, entities.HIGHLY_SENSITIVE)

# Record types that are the OWNER'S to write, whatever else an agent holds.
#
# Krish, 2026-09-23: *"we do need to put the necessary safeguards from rogue or
# hallucinating AI - so the explicit rule as the safe safeguard that owner
# permissions necessary to change the constitution."*
#
# Classification cannot express this. Jarvis holds `create`, `update` and
# `write_sensitive`, so any classification he can read he can also write, and a
# grant that the agent needing it can create is not a grant. What he does not
# hold is `administer`, which only `OPERATOR_CONSOLE` has - so these types
# require it for **every** write, not only for create. Update matters as much:
# a one-shot grant Jarvis could mark unspent, or whose expiry he could move, is
# a standing grant wearing a limit.
OWNER_WRITTEN_TYPES = ("charter_grant",)

WRITING_ACTIONS = ("create", "update", "archive", "delete_authorized", "link",
                   "unlink", "reconcile")


class Refused(PermissionError):
    """An operation the policy does not allow, carrying why."""

    def __init__(self, message: str, *, agent: str, permission: str):
        super().__init__(message)
        self.agent = agent
        self.permission = permission


def permissions_of(agent: str) -> frozenset[str]:
    """What this agent may do. An empty set for an agent nobody declared."""
    return POLICY.get(agent, frozenset())


def known_agent(agent: str) -> bool:
    return agent in POLICY


def required_for(action: str) -> str:
    try:
        return REQUIRED[action]
    except KeyError:
        raise KeyError(
            f"action {action!r} has no declared permission. Every action in "
            f"dba/contract.ACTIONS must appear in REQUIRED - an action that "
            f"falls through this table would be an unguarded operation."
        ) from None


def sensitivity_permission(classification: str, *, writing: bool) -> str | None:
    """The extra permission this classification demands, or None."""
    if classification not in SENSITIVE_CLASSIFICATIONS:
        return None
    return WRITE_SENSITIVE if writing else READ_SENSITIVE


def check(agent: str, action: str, *, classification: str | None = None,
          writing: bool | None = None, entity_type: str | None = None,
          capability_grants: dict | None = None) -> None:
    """Raise `Refused` unless this agent may do this. Silent on success.

    `writing` defaults to whether the action is one of the writing actions, and
    is overridable only because `validate` inspects a write it will not perform
    and should be judged as the read it actually is.

    `capability_grants` is the grant table of a published capability, and BOTH
    it and the global policy must allow the action. The global policy is a
    ceiling - what an agent could ever do - and the grant is the specific
    allowance for this data. Requiring both is what makes §17's *"an agent
    should receive only the data and operations it is authorized to use"* true
    per capability rather than per system.

    THE DBA'S OWN GENERATED TESTS FOUND THIS MISSING. A capability declared
    grants and nothing read them, so any agent holding global `create` could
    write to a capability that had granted it nothing - permissions defined and
    not enforced, which is worse than not defining them, because the
    declaration says otherwise to anybody reading it.

    `None` means the type is a built-in and the global policy is the whole
    answer. An empty dict is a capability that granted nobody anything, and it
    denies - the two must not be conflated."""
    from dba import contract

    if not known_agent(agent):
        raise Refused(
            f"{agent!r} is not an agent this system's policy knows. The DBA "
            f"refuses rather than assuming a default set, because an unknown "
            f"caller granted anything is how a permission model stops meaning "
            f"anything. Declared agents: {', '.join(sorted(POLICY))}.",
            agent=agent, permission=required_for(action))

    held = permissions_of(agent)

    if (entity_type in OWNER_WRITTEN_TYPES
            and action in WRITING_ACTIONS and ADMINISTER not in held):
        raise Refused(
            f"{agent!r} may not {action} a {entity_type!r}: this record type is "
            f"the owner's to write and needs {ADMINISTER!r}, which only the "
            f"operator console holds. A grant the agent needing it could write "
            f"is not a grant - that is the whole of the safeguard, and it is "
            f"structural rather than a rule Jarvis is asked to follow.",
            agent=agent, permission=ADMINISTER)

    needed = required_for(action)
    if needed not in held:
        raise Refused(
            f"{agent!r} may not {action}: that needs {needed!r} and this agent "
            f"holds {sorted(held)}.", agent=agent, permission=needed)

    if capability_grants is not None:
        allowed = set(capability_grants.get(agent, ()))
        if needed not in allowed:
            raise Refused(
                f"{agent!r} may not {action} this capability: it grants "
                f"{sorted(allowed) if allowed else 'nothing'} to {agent!r}, and "
                f"{action} needs {needed!r}. Holding {needed!r} generally is "
                f"not the same as being granted it here.",
                agent=agent, permission=needed)

    if classification is None:
        return
    is_write = contract.Request(action=action, requested_by=agent).writes \
        if writing is None else writing
    extra = sensitivity_permission(classification, writing=is_write)
    if extra is not None and capability_grants is not None:
        if extra not in set(capability_grants.get(agent, ())):
            raise Refused(
                f"{agent!r} is not granted {extra!r} on this "
                f"{classification} capability.", agent=agent, permission=extra)
    if extra is not None and extra not in held:
        raise Refused(
            f"{agent!r} may {action} ordinary records but not {classification} "
            f"ones: that needs {extra!r}.", agent=agent, permission=extra)


def describe() -> dict:
    """The policy, for §28's health response and for a review."""
    return {
        "agents": {agent: sorted(held) for agent, held in sorted(POLICY.items())},
        "action_permissions": dict(sorted(REQUIRED.items())),
        "sensitive_classifications": list(SENSITIVE_CLASSIFICATIONS),
    }
