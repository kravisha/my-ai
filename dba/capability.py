"""A data capability: a schema, its API contract, and its lifecycle (§5–§7, §25, §26).

## What a capability is

One published unit of persistent-data service. It carries everything §25 says
an API contract must define - purpose, request and response structure, required
and optional fields, validation, permissions, errors, version, examples - plus
the schema behind it, in one declaration that is stored as data.

## Why a declaration and not generated Python

Krish's instruction is that *"the agent seeking this service will seek to use
the API provided by the DBA, and therefore the DBA is in charge of creating the
APIs."* The deliverable is a real, named, versioned API at its own URL, with
its own contract, that a client agent calls without knowing anything about the
database underneath. That is what `dba/routes.py` publishes.

What the DBA writes to make that true is a declaration, not a `.py` file, and
that is a deliberate constraint rather than a shortcut. `backend/engineering.py`
§8 stops an engineer at the "code" rung; `app/initiative.HARM_WIDENS_ITS_OWN_-
AUTHORITY` refuses self-granted authority at every boldness setting, and code an
agent wrote and then executed is that harm wearing a feature's clothes. The
Learning Engine hit this exact wall and resolved it the same way. The client
cannot tell the difference: `/api/v1/work_request/create` is a real endpoint
either way. The difference is that this one can be reviewed as a diff, rolled
back with a SELECT, and cannot reach anything its declaration does not name.

## The lifecycle, and why publishing is a separate step

    DRAFT -> STAGED -> PUBLISHED -> RETIRED
                |
                +-> REJECTED

A capability is designed into DRAFT, moved to STAGED once its self-check and
generated tests pass, and reaches PUBLISHED only when Krish accepts it (§31's
stage 2). Nothing serves traffic before PUBLISHED. That gate is the same one
`register_learned_skill` has: a system that can bring its own new data surfaces
into service has granted itself authority, however good its tests were.

## Versioning (§26)

A published declaration is never edited. A change publishes a new version
beside it and the old one keeps serving until it is retired, so an agent
written against v1 does not fail because the DBA improved something. Breaking
and non-breaking changes are distinguished by `compare`, not by judgement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from dba import entities, permissions

# --- lifecycle ----------------------------------------------------------------

DRAFT = "draft"
STAGED = "staged"
PUBLISHED = "published"
REJECTED = "rejected"
RETIRED = "retired"
STATUSES = (DRAFT, STAGED, PUBLISHED, REJECTED, RETIRED)

# Only one of these serves traffic.
SERVING = (PUBLISHED,)

# --- retention (§8's "what should eventually expire") -------------------------

KEEP_FOREVER = "keep_forever"
KEEP_WHILE_REFERENCED = "keep_while_referenced"
ARCHIVE_AFTER_DAYS = "archive_after_days"
DELETE_AFTER_DAYS = "delete_after_days"
RETENTION_RULES = (KEEP_FOREVER, KEEP_WHILE_REFERENCED, ARCHIVE_AFTER_DAYS,
                   DELETE_AFTER_DAYS)


@dataclass(frozen=True)
class Retention:
    """How long this capability's records live.

    Required on every capability, and `UNSPECIFIED` is not one of the options.
    §8 asks what should eventually expire; a design that never answers leaves a
    table that grows until somebody notices, so a requirement that does not say
    becomes an ask-back rather than a silent `keep_forever`."""

    rule: str
    days: int | None = None
    why: str = ""

    def __post_init__(self) -> None:
        if self.rule not in RETENTION_RULES:
            raise ValueError(f"retention rule={self.rule!r} is not one of "
                             f"{RETENTION_RULES}")
        if self.rule in (ARCHIVE_AFTER_DAYS, DELETE_AFTER_DAYS) and not self.days:
            raise ValueError(f"{self.rule} needs a number of days")

    def to_dict(self) -> dict:
        return {"rule": self.rule, "days": self.days, "why": self.why}

    @classmethod
    def from_dict(cls, payload: dict) -> "Retention":
        return cls(rule=payload["rule"], days=payload.get("days"),
                   why=payload.get("why", ""))

    def describe(self) -> str:
        if self.rule == KEEP_FOREVER:
            return "kept indefinitely"
        if self.rule == KEEP_WHILE_REFERENCED:
            return "kept while something still links to it"
        verb = "archived" if self.rule == ARCHIVE_AFTER_DAYS else "deleted"
        return f"{verb} {self.days} days after it was last updated"


@dataclass(frozen=True)
class Relationship:
    """One edge this capability declares (§6.2, §7)."""

    relation: str
    from_type: str
    to_type: str
    description: str = ""

    def to_dict(self) -> dict:
        return {"relation": self.relation, "from_type": self.from_type,
                "to_type": self.to_type, "description": self.description}

    @classmethod
    def from_dict(cls, payload: dict) -> "Relationship":
        return cls(relation=payload["relation"], from_type=payload["from_type"],
                   to_type=payload["to_type"],
                   description=payload.get("description", ""))


@dataclass(frozen=True)
class Capability:
    """One designed, testable, publishable data capability."""

    name: str
    version: int
    purpose: str
    entity_type: entities.EntityType
    retention: Retention
    operations: tuple[str, ...]
    grants: dict[str, tuple[str, ...]] = field(default_factory=dict)
    relationships: tuple[Relationship, ...] = ()
    indexes: tuple[str, ...] = ()
    examples: tuple[dict, ...] = ()
    requirement: str = ""
    designed_by: str = permissions.DBA if hasattr(permissions, "DBA") else "dba"
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        from dba import contract

        if self.name != self.entity_type.name:
            raise ValueError(
                f"capability {self.name!r} declares entity type "
                f"{self.entity_type.name!r}. One capability is one kind of "
                f"record, and two names for it is two things to keep in step.")
        if self.version < 1:
            raise ValueError("versions start at 1")
        for action in self.operations:
            if action not in contract.ACTIONS:
                raise ValueError(
                    f"{self.name}: operation {action!r} is not one of the "
                    f"declared actions. A capability composes the DBA's "
                    f"vocabulary; it does not invent verbs.")
        for agent, held in self.grants.items():
            for permission in held:
                if permission not in permissions.PERMISSIONS:
                    raise ValueError(
                        f"{self.name}: grant to {agent!r} names {permission!r}, "
                        f"which is not a permission this system has.")
        for name in self.indexes:
            if name not in self.entity_type.fields:
                raise ValueError(
                    f"{self.name}: index on {name!r}, which the type does not "
                    f"declare as a field.")

    # --- identity -------------------------------------------------------------

    @property
    def key(self) -> str:
        """How one version is named. `work_request@2`."""
        return f"{self.name}@{self.version}"

    @property
    def route_prefix(self) -> str:
        """Where a client agent finds it. §36: the agent knows this, not the
        database underneath."""
        return f"/api/v{self.version}/{self.name}"

    def to_dict(self) -> dict:
        return {
            "name": self.name, "version": self.version, "purpose": self.purpose,
            "entity_type": self.entity_type.to_dict(),
            "retention": self.retention.to_dict(),
            "operations": list(self.operations),
            "grants": {agent: list(held) for agent, held in sorted(self.grants.items())},
            "relationships": [r.to_dict() for r in self.relationships],
            "indexes": list(self.indexes),
            "examples": list(self.examples),
            "requirement": self.requirement,
            "designed_by": self.designed_by,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "Capability":
        return cls(
            name=payload["name"], version=int(payload["version"]),
            purpose=payload.get("purpose", ""),
            entity_type=entities.from_dict(payload["entity_type"]),
            retention=Retention.from_dict(payload["retention"]),
            operations=tuple(payload.get("operations") or ()),
            grants={agent: tuple(held)
                    for agent, held in (payload.get("grants") or {}).items()},
            relationships=tuple(Relationship.from_dict(item)
                                for item in payload.get("relationships") or ()),
            indexes=tuple(payload.get("indexes") or ()),
            examples=tuple(payload.get("examples") or ()),
            requirement=payload.get("requirement", ""),
            designed_by=payload.get("designed_by", "dba"),
            notes=tuple(payload.get("notes") or ()))

    def fingerprint(self) -> str:
        """A stable hash of the declaration, so an unchanged redesign is
        recognisable as one rather than published as a new version."""
        import hashlib

        payload = json.dumps(self.to_dict(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# --- what changed between two versions (§26) ----------------------------------

BREAKING = "breaking"
ADDITIVE = "additive"
UNCHANGED = "unchanged"


def compare(old: Capability, new: Capability) -> dict:
    """Whether moving from `old` to `new` can break an existing caller.

    Decided by rules rather than by judgement, because "is this breaking?" is
    the question a hurried person answers optimistically. Removing a field,
    removing an operation, adding a required field, narrowing an allowed value
    set, or tightening a grant all break somebody. Adding an optional field
    does not."""
    reasons: list[str] = []

    removed_fields = sorted(set(old.entity_type.fields) - set(new.entity_type.fields))
    for name in removed_fields:
        reasons.append(f"field {name!r} was removed")

    for name, declared in sorted(new.entity_type.fields.items()):
        was = old.entity_type.fields.get(name)
        if was is not None and was != declared:
            reasons.append(f"field {name!r} changed type from {was} to {declared}")

    added_required = sorted(set(new.entity_type.required)
                            - set(old.entity_type.required))
    for name in added_required:
        reasons.append(f"{name!r} became required")

    removed_operations = sorted(set(old.operations) - set(new.operations))
    for action in removed_operations:
        reasons.append(f"operation {action!r} was removed")

    if old.entity_type.statuses and new.entity_type.statuses:
        lost = sorted(set(old.entity_type.statuses) - set(new.entity_type.statuses))
        for value in lost:
            reasons.append(f"status {value!r} is no longer allowed")

    for agent, held in sorted(old.grants.items()):
        now = set(new.grants.get(agent, ()))
        lost = sorted(set(held) - now)
        for permission in lost:
            reasons.append(f"{agent} lost {permission!r}")

    added = sorted(set(new.entity_type.fields) - set(old.entity_type.fields))
    additive = [f"field {name!r} was added" for name in added]
    additive += [f"operation {action!r} was added"
                 for action in sorted(set(new.operations) - set(old.operations))]

    if reasons:
        verdict = BREAKING
    elif additive:
        verdict = ADDITIVE
    else:
        verdict = UNCHANGED
    return {"verdict": verdict, "breaking": reasons, "additive": additive}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
