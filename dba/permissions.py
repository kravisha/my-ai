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
          writing: bool | None = None) -> None:
    """Raise `Refused` unless this agent may do this. Silent on success.

    `writing` defaults to whether the action is one of the writing actions, and
    is overridable only because `validate` inspects a write it will not perform
    and should be judged as the read it actually is."""
    from dba import contract

    if not known_agent(agent):
        raise Refused(
            f"{agent!r} is not an agent this system's policy knows. The DBA "
            f"refuses rather than assuming a default set, because an unknown "
            f"caller granted anything is how a permission model stops meaning "
            f"anything. Declared agents: {', '.join(sorted(POLICY))}.",
            agent=agent, permission=required_for(action))

    held = permissions_of(agent)
    needed = required_for(action)
    if needed not in held:
        raise Refused(
            f"{agent!r} may not {action}: that needs {needed!r} and this agent "
            f"holds {sorted(held)}.", agent=agent, permission=needed)

    if classification is None:
        return
    is_write = contract.Request(action=action, requested_by=agent).writes \
        if writing is None else writing
    extra = sensitivity_permission(classification, writing=is_write)
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
