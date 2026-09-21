"""What kinds of thing this database holds, declared as data (§6, §10, §11).

## Stable machinery, evolving data

An entity type is a row in a registry, not a table of its own and not a Python
class per kind. This is the same call `app/learning/recipe.py` made for learned
skills and for the same stated reason: the schema stops changing every time the
system learns about a new kind of thing, and adding one becomes an edit to a
declaration that validation, duplicate detection and search all read - rather
than four edits that can disagree.

## The half of §6.3 that is easy to get wrong

    *"Records should support metadata without requiring a schema change for
    every minor extension ... Important searchable fields should still be
    represented explicitly rather than buried entirely inside generic JSON."*

Both halves. So there is a fixed set of **promoted** columns - the fields that
recur across every category in §6.1 and that searches and duplicate rules
actually use - and everything else lives in `data_json`. A type says which
promoted columns it uses; it does not get to invent new ones, because a column
invented per type is a schema change per type and that is the thing §6.3's
first half is against.

Pure EAV - a row per field - was the other option and is the architectural dead
end §27 warns about: every query becomes a self-join, and no index helps.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- field types, for §10's "data type" check ---------------------------------

TEXT = "text"
EMAIL = "email"
PHONE = "phone"
INTEGER = "integer"
NUMBER = "number"
BOOLEAN = "boolean"
DATE = "date"
TIMESTAMP = "timestamp"
FIELD_TYPES = (TEXT, EMAIL, PHONE, INTEGER, NUMBER, BOOLEAN, DATE, TIMESTAMP)

# --- §15's classification ladder ----------------------------------------------

PUBLIC = "public"
INTERNAL = "internal"
CONFIDENTIAL = "confidential"
SENSITIVE = "sensitive"
HIGHLY_SENSITIVE = "highly_sensitive"
CLASSIFICATIONS = (PUBLIC, INTERNAL, CONFIDENTIAL, SENSITIVE, HIGHLY_SENSITIVE)

# Deliberately a different axis from `app/data_classification.py`, which
# classifies a field by **where it may go** (local-only versus shareable with an
# external model). This one classifies a record by **how sensitive it is**.
# A field can be highly sensitive and perfectly fine to keep locally; the two
# were not merged because merging them would make one of the two questions
# unanswerable.

# --- the promoted columns (§6.3) ----------------------------------------------

NAME = "name"
EMAIL_FIELD = "email"
PHONE_FIELD = "phone"
EXTERNAL_ID = "external_id"
STATUS = "status"
PROMOTED = (NAME, EMAIL_FIELD, PHONE_FIELD, EXTERNAL_ID, STATUS)


class UnknownEntityType(KeyError):
    """A type nobody declared, said as such rather than as a KeyError on a dict."""


@dataclass(frozen=True)
class EntityType:
    """One declared kind of record."""

    name: str
    fields: dict[str, str]
    required: tuple[str, ...] = ()
    # §11's duplicate keys. Each entry is a field whose value, when present,
    # should not appear twice. Checked, never auto-merged (§11's last line).
    identifying: tuple[str, ...] = ()
    # The field that answers "which one?" in an ask-back option list (§4.2).
    label: str = NAME
    statuses: tuple[str, ...] = ()
    classification: str = INTERNAL
    note: str = ""

    def __post_init__(self) -> None:
        for field_name, field_type in self.fields.items():
            if field_type not in FIELD_TYPES:
                raise ValueError(
                    f"{self.name}.{field_name} has type {field_type!r}, which is "
                    f"not one of {FIELD_TYPES}")
        for declared, what in ((self.required, "required"),
                               (self.identifying, "identifying")):
            for field_name in declared:
                if field_name not in self.fields:
                    raise ValueError(
                        f"{self.name}: {what} names {field_name!r}, which the "
                        f"type does not declare as a field. A required field "
                        f"nothing can supply refuses every write.")
        if self.label not in self.fields:
            raise ValueError(
                f"{self.name}: label={self.label!r} is not a declared field, so "
                f"an ask-back could not say which record it means.")
        if self.classification not in CLASSIFICATIONS:
            raise ValueError(
                f"{self.name}: classification={self.classification!r} is not one "
                f"of {CLASSIFICATIONS}")

    def promoted_fields(self) -> tuple[str, ...]:
        return tuple(name for name in PROMOTED if name in self.fields)

    def extra_fields(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.fields) - set(PROMOTED)))

    def to_dict(self) -> dict:
        return {
            "name": self.name, "fields": dict(self.fields),
            "required": list(self.required), "identifying": list(self.identifying),
            "label": self.label, "statuses": list(self.statuses),
            "classification": self.classification, "note": self.note,
        }


# --- the registry -------------------------------------------------------------
#
# A deliberately small opening set from §6.1's list, which says outright that
# *"Not every category has to be implemented immediately."* Each of these five
# has a use in the acceptance tests or in the examples §4 gives; the rest are
# one declaration each on the day something needs them.

# Two registries, and the split is the point.
#
# `_BUILT_IN` is written in this file and changes only by a commit. `_ADOPTED`
# holds the types of capabilities the DBA designed and Krish published, loaded
# from the database at runtime - which is what lets a new capability become a
# working API without an edit here, and is the whole of §6 and §7.
#
# A built-in is never shadowed by an adopted one. A published capability that
# could redefine `person` would be a way to change the meaning of stored data
# by writing a row, and the audit trail would be describing two different
# things under one name.
_BUILT_IN: dict[str, EntityType] = {}
_ADOPTED: dict[str, EntityType] = {}


def register(entity_type: EntityType) -> EntityType:
    """Declare a built-in type. Only this module calls it."""
    if entity_type.name in _BUILT_IN:
        raise ValueError(f"entity type {entity_type.name!r} is already declared")
    _BUILT_IN[entity_type.name] = entity_type
    return entity_type


def adopt(entity_type: EntityType) -> EntityType:
    """Take on the type of a published capability (§6).

    Refused for a name a built-in already holds, for the reason above."""
    if entity_type.name in _BUILT_IN:
        raise ValueError(
            f"{entity_type.name!r} is a built-in type and a published "
            f"capability may not redefine it. Publishing a type that shadowed "
            f"one would change what stored rows mean by writing a row.")
    _ADOPTED[entity_type.name] = entity_type
    return entity_type


def adopted() -> list[EntityType]:
    return [_ADOPTED[name] for name in sorted(_ADOPTED)]


def snapshot_adopted() -> dict:
    """The adopted registry as it stands, for a caller that must put it back.

    `dba/selfcheck.py` adopts a capability that is not published yet so it can
    test it against the real agent. Without a way to restore, that test would
    leave an unpublished type live in the process - a capability serving
    traffic because somebody tested it, which is the gate in `dba/registry.py`
    walked around from inside."""
    return dict(_ADOPTED)


def restore_adopted(snapshot: dict) -> None:
    _ADOPTED.clear()
    _ADOPTED.update(snapshot)


def forget_adopted() -> None:
    """Drop every adopted type. For a retire, and for test isolation."""
    _ADOPTED.clear()


def is_built_in(name: str) -> bool:
    return name in _BUILT_IN


def get(name: str) -> EntityType:
    if name in _BUILT_IN:
        return _BUILT_IN[name]
    if name in _ADOPTED:
        return _ADOPTED[name]
    raise UnknownEntityType(
        f"{name!r} is not a declared entity type. Declared: "
        f"{', '.join(sorted(set(_BUILT_IN) | set(_ADOPTED)))}. A built-in type "
        f"is an edit to dba/entities.py; anything else arrives by the DBA "
        f"designing a capability and it being published."
    ) from None


def known(name: str) -> bool:
    return name in _BUILT_IN or name in _ADOPTED


def all_types() -> list[EntityType]:
    merged = dict(_ADOPTED)
    merged.update(_BUILT_IN)
    return [merged[name] for name in sorted(merged)]


def from_dict(payload: dict) -> EntityType:
    """Rebuild a type from its stored declaration. The inverse of `to_dict`."""
    return EntityType(
        name=payload["name"],
        fields=dict(payload["fields"]),
        required=tuple(payload.get("required") or ()),
        identifying=tuple(payload.get("identifying") or ()),
        label=payload.get("label", NAME),
        statuses=tuple(payload.get("statuses") or ()),
        classification=payload.get("classification", INTERNAL),
        note=payload.get("note", ""))


PERSON = register(EntityType(
    name="person",
    fields={NAME: TEXT, EMAIL_FIELD: EMAIL, PHONE_FIELD: PHONE,
            EXTERNAL_ID: TEXT, STATUS: TEXT, "organization": TEXT,
            "notes": TEXT},
    required=(NAME,),
    identifying=(EMAIL_FIELD, PHONE_FIELD, EXTERNAL_ID),
    statuses=("active", "inactive"),
    classification=CONFIDENTIAL,
    note="§4's examples A and C are both about people, which is why this is first."))

ORGANIZATION = register(EntityType(
    name="organization",
    fields={NAME: TEXT, EXTERNAL_ID: TEXT, STATUS: TEXT, "website": TEXT},
    required=(NAME,),
    identifying=(EXTERNAL_ID,),
    statuses=("active", "inactive"),
    classification=INTERNAL))

PROJECT = register(EntityType(
    name="project",
    fields={NAME: TEXT, STATUS: TEXT, EXTERNAL_ID: TEXT, "description": TEXT,
            "starts_on": DATE, "ends_on": DATE},
    required=(NAME,),
    identifying=(EXTERNAL_ID,),
    statuses=("planned", "active", "paused", "complete"),
    classification=INTERNAL,
    note="§4's example E - attaching a document to 'the project' - needs several."))

TASK = register(EntityType(
    name="task",
    fields={NAME: TEXT, STATUS: TEXT, "description": TEXT, "due_on": DATE,
            "priority": INTEGER},
    required=(NAME,),
    statuses=("open", "in_progress", "blocked", "done", "cancelled"),
    classification=INTERNAL))

# §12 and §13: Jarvis's own durable state, and any other agent's.
#
# BUILT IN RATHER THAN DESIGNED, and the reason is §12's own sentence: *"JARVIS
# must be able to stop and restart without losing the persistent state that the
# system has decided should be retained."* State that only works once somebody
# publishes a capability is state that is missing on the first restart, which
# is exactly the restart that matters.
#
# Its shape is not invented here: it is `dba/patterns.AGENT_STATE`, the same
# archetype the designer reaches for when a requirement says "survive a
# restart", and `tests/test_dba_development.py` asserts the two agree. So this
# is the designer's own output, shipped rather than waiting to be asked for.
AGENT_STATE = register(EntityType(
    name="agent_state",
    fields={NAME: TEXT, "agent": TEXT, "kind": TEXT, "value": TEXT,
            STATUS: TEXT, "revision": INTEGER, "effective_from": TIMESTAMP},
    required=(NAME, "agent", "kind"),
    statuses=("current", "superseded"),
    classification=CONFIDENTIAL,
    note="§12/§13. One row per thing an agent must remember across restarts: "
         "configuration, goals, tasks, plans, decisions, assignments. `agent` "
         "is immutable in the archetype - state that could be reassigned to "
         "another agent is state nobody owns."))

DOCUMENT = register(EntityType(
    name="document",
    fields={NAME: TEXT, EXTERNAL_ID: TEXT, STATUS: TEXT, "location": TEXT,
            "hash": TEXT, "mime_type": TEXT},
    required=(NAME,),
    # §11 names "same document hash" as a duplicate signal, and §40 wants the
    # hash kept for exactly this. The file itself is not stored here (§39).
    identifying=("hash", EXTERNAL_ID),
    statuses=("ingested", "indexed", "failed"),
    classification=CONFIDENTIAL))
