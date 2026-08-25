"""What the client's agent can do, and what it truthfully cannot
(owner direction 2026-08-25; addendum 43 §16; TASK_QUEUE TQ-40,
docs/SPEC_RECONCILIATION.md §95).

The owner's framing: *"initially this will be limited to giving info and later
this agent will have many abilities such as portfolio analysis and trade ideas
and many other skills yet to be decided."*

## Why a registry and not just more tools

§92 decided the mechanism: each skill is its own capability, never a widening of
what `converse` means. This is that decision made concrete, plus the field §92
did not know it needed.

That field is **scope**. When TQ-40 came up, the reason portfolio analysis could
not ship turned out not to be the expected one. There *is* a portfolio producer —
`app/tools/portfolio.py`, reading `data/portfolio.xlsx` through a two-layer
consent model. The problem is that there is exactly one such file and it belongs
to the **operator**. Handing it to a Gateway client would give an external person
somebody else's holdings: the leak §93 closed, arriving by a different route and
wearing a feature's clothes.

A registry that could not express "this producer serves the caller's own data"
would let the next person wire that up in good faith. So every skill declares
whose data it touches, and a skill a client can invoke **must** be
subject-scoped. That is a test, not a convention.

## Declared-but-unbuilt is a real state, not a placeholder

A skill can exist here with `STATUS_UNBUILT` and a reason. That is not empty
machinery — it is the difference this codebase insists on everywhere else
between "nothing is happening" and "this does not exist yet".

Asked "can you look at my portfolio?", an agent with no registry says something
plausible. An agent with this one says it cannot, and why, and what would have
to change. The producer of that answer is this file.

## The prompt is built from it

`capability_paragraph` is what `gateway/conversation.client_prompt` assembles
the client agent's instructions from, so what the agent claims about itself and
what the Gateway will actually permit cannot drift apart. The alternative — a hand-written
paragraph listing abilities — is a second source of truth about permissions, and
it would be wrong within one increment.
"""

from __future__ import annotations

from dataclasses import dataclass

from gateway import roles

# Whose data a skill reads. The distinction that makes the registry worth
# having: a client may only ever invoke a skill scoped to their own data.
SCOPE_SUBJECT = "subject"
SCOPE_ORGANIZATION = "organization"
SCOPES = (SCOPE_SUBJECT, SCOPE_ORGANIZATION)

# Whether the skill can actually run. Unbuilt is a first-class answer, carried
# with the reason it is unbuilt.
STATUS_AVAILABLE = "available"
STATUS_UNBUILT = "unbuilt"
STATUSES = (STATUS_AVAILABLE, STATUS_UNBUILT)


class UnknownScope(ValueError):
    """A skill declared a scope outside the vocabulary. Fail closed: an
    unrecognised scope cannot be checked, and a check that cannot run is worse
    than no check because it looks like one."""


class ScopeViolation(ValueError):
    """A role that may invoke a skill reading data that is not its own.

    Raised at import rather than at request time - this is a mistake in the
    registry, and the suite is where a mistake in the registry should surface."""


@dataclass(frozen=True)
class Skill:
    name: str
    summary: str
    capability: str
    scope: str
    status: str
    # Required when unbuilt, and required to be *specific*. "Not implemented"
    # tells a client nothing; the reason is what lets them ask for the right
    # thing instead.
    blocked_reason: str | None = None


SKILLS: tuple[Skill, ...] = (
    Skill(
        name="conversation",
        summary="answer questions from what you know, and say plainly when you do not",
        capability=roles.CAP_CONVERSE,
        scope=SCOPE_SUBJECT,
        status=STATUS_AVAILABLE,
    ),
    Skill(
        name="portfolio_analysis",
        summary="look at the client's holdings and answer questions about them",
        capability=roles.CAP_CONVERSE,
        scope=SCOPE_SUBJECT,
        status=STATUS_UNBUILT,
        blocked_reason=(
            "There is a portfolio in this system, but it is the operator's, not yours - one "
            "file, one owner, no per-client holdings. Reading it for you would hand you "
            "somebody else's positions. This needs client-owned holdings first, not a wire-up."
        ),
    ),
    Skill(
        name="trade_ideas",
        summary="suggest trades",
        capability=roles.CAP_CONVERSE,
        scope=SCOPE_SUBJECT,
        status=STATUS_UNBUILT,
        blocked_reason=(
            "Every price and signal this organization currently produces is simulated training "
            "data (addendum 25). Presenting it as a suggestion about real money would be "
            "presenting synthetic output as real, which this system refuses everywhere else "
            "and will not start doing here."
        ),
    ),
)


def _validate() -> None:
    """Checked at import, because a registry mistake is a permissions mistake.

    The invariant worth the whole file: **no skill a client can invoke may read
    organization data.** Everything else here is bookkeeping; this is the line
    that stops portfolio analysis from being wired to the operator's holdings by
    somebody acting in good faith."""
    seen = set()
    for skill in SKILLS:
        if skill.name in seen:
            raise ValueError(f"duplicate skill {skill.name!r}")
        seen.add(skill.name)
        if skill.scope not in SCOPES:
            raise UnknownScope(f"skill {skill.name!r} declares unknown scope {skill.scope!r}")
        if skill.status not in STATUSES:
            raise ValueError(f"skill {skill.name!r} declares unknown status {skill.status!r}")
        if skill.capability not in roles.CAPABILITIES:
            raise roles.UnknownCapability(
                f"skill {skill.name!r} requires unknown capability {skill.capability!r}")
        if skill.status == STATUS_UNBUILT and not (skill.blocked_reason or "").strip():
            raise ValueError(
                f"skill {skill.name!r} is unbuilt without a reason; "
                "'not implemented' tells a client nothing they can act on")
        if (roles.allows(roles.ROLE_CLIENT, skill.capability)
                and skill.scope != SCOPE_SUBJECT):
            raise ScopeViolation(
                f"skill {skill.name!r} is reachable by a client but reads {skill.scope} data. "
                "A client may only invoke skills scoped to their own data."
            )


_validate()


def for_role(role: str, *, status: str | None = None) -> list[Skill]:
    granted = roles.capabilities(role)
    return [s for s in SKILLS
            if s.capability in granted and (status is None or s.status == status)]


def available_for(role: str) -> list[Skill]:
    return for_role(role, status=STATUS_AVAILABLE)


def unbuilt_for(role: str) -> list[Skill]:
    """Skills this role would be allowed to use, if they existed.

    Reported rather than hidden: "I am not allowed to" and "that does not exist
    yet" are different answers, and only one of them is worth asking again
    about later."""
    return for_role(role, status=STATUS_UNBUILT)


def describe(role: str) -> dict:
    return {
        "role": role,
        "available": [{"name": s.name, "summary": s.summary} for s in available_for(role)],
        "unbuilt": [{"name": s.name, "summary": s.summary, "reason": s.blocked_reason}
                    for s in unbuilt_for(role)],
    }


def capability_paragraph(role: str) -> str:
    """The honest statement of what this agent can do, for its own prompt.

    Generated rather than written, so that what the agent says about itself and
    what the Gateway will actually permit cannot drift. A hand-written list of
    abilities is a second source of truth about permissions, and it would be
    wrong within one increment."""
    lines = ["What you can actually do, and nothing beyond it:"]
    for skill in available_for(role):
        lines.append(f"- {skill.summary}.")
    unbuilt = unbuilt_for(role)
    if unbuilt:
        lines.append(
            "\nThings you will be asked for and cannot do yet. If asked, say so plainly and "
            "give the reason - do not improvise an answer, and do not promise a date:")
        for skill in unbuilt:
            lines.append(f"- {skill.summary}: {skill.blocked_reason}")
    return "\n".join(lines)
