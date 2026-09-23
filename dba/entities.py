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


# --- the vocabulary for persisting an agent's life ----------------------------
#
# Added for the Persistence / Life Ledger / Self-Modification specification, and
# deliberately written in the DBA's own terms rather than Jarvis's: none of these
# names the Gateway, and a second agent asking the DBA to remember its life gets
# the same types. The DBA stores lives; whose life it is arrives in `agent`.
#
# Built in rather than designed, for `AGENT_STATE`'s reason above. A ledger that
# only exists once somebody publishes a capability has no entry for the restart
# that lost it.

LEDGER_EVENT = register(EntityType(
    name="ledger_event",
    # `external_id` is "<agent>:<zero-padded sequence>", and it is `identifying`
    # so that two racing appends cannot both take one sequence number. The
    # loser is refused as a duplicate and re-reads the tip, which is the whole
    # of the concurrency story - see `gateway/ledger.py`.
    fields={NAME: TEXT, EXTERNAL_ID: TEXT, STATUS: TEXT,
            "agent": TEXT, "sequence_number": INTEGER, "occurred_at": TIMESTAMP,
            "session_id": TEXT, "event_type": TEXT, "actor": TEXT,
            "origin": TEXT, "origin_id": TEXT,
            "input_reference": TEXT, "observation": TEXT,
            # §27 calls this "classification"; renamed because `classification`
            # is a column on every record and means how sensitive it is, not
            # what the agent made of the event.
            "assessment": TEXT, "confidence": NUMBER,
            "verification_state": TEXT, "risk_level": TEXT,
            "related_event_ids": TEXT, "supersedes_event_id": TEXT,
            "checkpoint_id": TEXT, "code_version": TEXT,
            "ledger_schema_version": INTEGER,
            "integrity_hash": TEXT, "previous_event_hash": TEXT},
    required=(NAME, "agent", "sequence_number", "event_type", "occurred_at"),
    identifying=(EXTERNAL_ID,),
    # One status and one only. §4.3 says historical entries are not edited in
    # place, and marking the original "superseded" would be exactly that edit.
    # Supersession is carried by the *later* event's `supersedes_event_id`,
    # which is the direction §6 asks for: a new layer, not a changed record.
    statuses=("recorded",),
    classification=CONFIDENTIAL,
    note="§4.3's life ledger. Append-oriented and hash-chained: each event "
         "carries the hash of its own content and of the one before it, so a "
         "replay can prove the chain was not edited."))

CHECKPOINT = register(EntityType(
    name="checkpoint",
    fields={NAME: TEXT, EXTERNAL_ID: TEXT, STATUS: TEXT,
            "agent": TEXT, "sequence_number": INTEGER, "taken_at": TIMESTAMP,
            "parent_checkpoint_id": TEXT, "reason": TEXT,
            "code_version": TEXT, "state_schema_version": INTEGER,
            "ledger_tip_sequence": INTEGER, "ledger_tip_hash": TEXT,
            "contents_hash": TEXT, "item_counts": TEXT,
            "validated_at": TIMESTAMP, "invalid_reason": TEXT},
    required=(NAME, "agent", "sequence_number", "taken_at"),
    identifying=(EXTERNAL_ID,),
    # §8: a checkpoint is not authoritative until it has been validated, and a
    # corrupted one is rejected rather than quietly skipped. "writing" is the
    # write-complete marker §8 asks for - a checkpoint still in that state when
    # the process died is one that never finished.
    statuses=("writing", "valid", "invalid", "superseded"),
    classification=CONFIDENTIAL,
    note="§8. `ledger_tip_sequence` is what makes a restore honest: it says "
         "which ledger events the checkpoint had seen, so the interval that "
         "may have been lost can be named rather than guessed."))

KNOWLEDGE_ITEM = register(EntityType(
    name="knowledge_item",
    fields={NAME: TEXT, STATUS: TEXT, "agent": TEXT, "subject": TEXT,
            "statement": TEXT, "evidence": TEXT, "learned_at": TIMESTAMP,
            "origin": TEXT, "confidence": NUMBER, "verification_state": TEXT,
            "superseded_by": TEXT, "ledger_event_id": TEXT},
    required=(NAME, "agent", "statement"),
    statuses=("provisional", "confirmed", "superseded", "retracted"),
    classification=CONFIDENTIAL,
    note="§4.1's knowledge state. `verification_state` is what §10 rests on: "
         "an item restored as 'provisional' may not be asserted as fact."))

SKILL_STATE = register(EntityType(
    name="skill_state",
    fields={NAME: TEXT, STATUS: TEXT, "agent": TEXT, "skill": TEXT,
            "level": TEXT, "evidence": TEXT, "last_practised_at": TIMESTAMP,
            "episode_slug": TEXT, "notes": TEXT},
    required=(NAME, "agent", "skill"),
    statuses=("learning", "practising", "demonstrated", "stale", "lost"),
    classification=CONFIDENTIAL,
    note="§4.1's skill state. `episode_slug` points back into the Learning "
         "Engine's own episode rather than copying it (§23)."))

COMMITMENT = register(EntityType(
    name="commitment",
    fields={NAME: TEXT, STATUS: TEXT, "agent": TEXT, "owed_to": TEXT,
            "promise": TEXT, "made_at": TIMESTAMP, "due_on": DATE,
            "settled_at": TIMESTAMP, "outcome": TEXT, "ledger_event_id": TEXT},
    required=(NAME, "agent", "promise"),
    statuses=("open", "kept", "broken", "released"),
    classification=CONFIDENTIAL,
    note="§4.1. Separate from `task` because a commitment is owed to somebody "
         "and a task is not - and 'what did I promise and not deliver' is the "
         "question a restart must still be able to answer."))

CAPABILITY_GAP = register(EntityType(
    name="capability_gap",
    # §28's fields. The lifecycle is §11's, and the reason it is a status
    # rather than a boolean is §11's own sentence: a perceived lack is not a
    # confirmed lack.
    fields={NAME: TEXT, STATUS: TEXT, "agent": TEXT, "description": TEXT,
            "detected_at": TIMESTAMP, "detected_by": TEXT,
            "evidence": TEXT, "counter_evidence": TEXT,
            "impact": TEXT, "frequency": INTEGER, "severity": TEXT,
            "confidence": NUMBER, "affected_capability": TEXT,
            "requires_code_change": BOOLEAN, "alternative_remedies": TEXT,
            "user_review_required": BOOLEAN, "user_decision": TEXT,
            "approved_scope": TEXT, "resolution": TEXT,
            "resolved_at": TIMESTAMP},
    required=(NAME, "agent", "description", "detected_at"),
    statuses=("suspected", "investigating", "unsupported", "confirmed",
              "rejected", "deferred", "approved_for_remediation",
              "remediating", "resolved", "unresolved"),
    classification=CONFIDENTIAL,
    note="§11/§12/§28."))

CHANGE_PROPOSAL = register(EntityType(
    name="change_proposal",
    # §29's fields, plus §18's proposal format. `approval_state` is deliberately
    # not the record's `status`: the record's status is where the *work* is, and
    # the two answer different questions - an approved proposal whose build
    # failed is approved and failed at once.
    fields={NAME: TEXT, STATUS: TEXT, "agent": TEXT, "gap_id": TEXT,
            "proposal_version": INTEGER, "reason": TEXT, "scope": TEXT,
            "affected_components": TEXT, "affected_files": TEXT,
            "risk": TEXT, "expected_benefit": TEXT, "test_plan": TEXT,
            "rollback_plan": TEXT, "baseline_version": TEXT,
            "target_branch": TEXT, "approval_state": TEXT,
            "approved_by": TEXT, "approved_at": TIMESTAMP,
            "implementation_state": TEXT, "commit_id": TEXT,
            "build_id": TEXT, "deployment_id": TEXT,
            "post_validation_state": TEXT, "checkpoint_id": TEXT},
    required=(NAME, "agent", "reason", "scope"),
    statuses=("drafted", "awaiting_approval", "denied", "approved",
              "implementing", "tested", "committed", "deploying",
              "accepted", "degraded", "failed", "rolled_back"),
    classification=CONFIDENTIAL,
    note="§18/§29. The record the approval gate turns on, and the record a "
         "relaunched runtime reads to learn what was done to it."))

GUESS = register(EntityType(
    name="guess",
    # What Jarvis thought Krish would want, written down before the outcome was
    # known. His to write: the prediction is the thing he is being judged on,
    # and an assistant who cannot record a prediction cannot be judged at all.
    fields={NAME: TEXT, STATUS: TEXT, "agent": TEXT, "domain": TEXT,
            "what": TEXT, "because": TEXT, "made_at": TIMESTAMP,
            "by_when": TIMESTAMP,
            # Whether the trust ladder allowed this to be said out loud, and
            # when it was. A guess recorded but never said is the bottom rung
            # working, not a guess that failed.
            "to_say": BOOLEAN, "said_at": TIMESTAMP},
    required=(NAME, "agent", "domain", "what", "because", "made_at"),
    statuses=("open", "settled"),
    classification=CONFIDENTIAL,
    note="The anticipation record behind `gateway/anticipation.py`'s trust "
         "ladder. Written before the outcome is known; recorded afterwards it "
         "is hindsight, and hindsight scores perfectly."))

GUESS_VERDICT = register(EntityType(
    name="guess_verdict",
    # How the guess turned out, and how the work was then done. NOT Jarvis's to
    # write - `dba/permissions.OWNER_WRITTEN_TYPES` holds it, because this is
    # the record that decides how much latitude he gets, and a mark an agent can
    # award itself is not a mark.
    fields={NAME: TEXT, STATUS: TEXT, "agent": TEXT, "guess_id": TEXT,
            "outcome": TEXT, "quality": TEXT, "settled_by": TEXT,
            "settled_at": TIMESTAMP, "rated_by": TEXT, "rated_at": TIMESTAMP},
    required=(NAME, "guess_id", "outcome", "settled_by", "settled_at"),
    statuses=("recorded",),
    classification=CONFIDENTIAL,
    note="Krish's word on a guess, kept apart from the guess so that the agent "
         "being judged cannot write the judgement."))

CHARTER_GRANT = register(EntityType(
    name="charter_grant",
    # Krish's explicit permission to change something that is otherwise
    # read-only: the constitution, or the machinery that decides what Jarvis may
    # do. `dba/permissions.OWNER_WRITTEN_TYPES` makes every write here need
    # `administer`, which only the operator console holds - so Jarvis can read
    # his grants and cannot write one.
    fields={NAME: TEXT, STATUS: TEXT, "agent": TEXT, "key": TEXT,
            "granted_by": TEXT, "granted_at": TIMESTAMP, "expires_at": TIMESTAMP,
            "scope": TEXT, "note": TEXT, "interface": TEXT},
    required=(NAME, "key", "granted_by", "granted_at", "expires_at"),
    statuses=("active", "revoked"),
    classification=CONFIDENTIAL,
    note="§16. The owner's explicit permission, as a record rather than an "
         "argument. `expires_at` is set at grant time and cannot be moved by "
         "the agent it is for, because moving it is a write."))

APPROVAL_DECISION = register(EntityType(
    name="approval_decision",
    fields={NAME: TEXT, STATUS: TEXT, "agent": TEXT, "proposal_id": TEXT,
            "decided_by": TEXT, "decided_at": TIMESTAMP, "decision": TEXT,
            "scope_granted": TEXT, "note": TEXT, "interface": TEXT,
            "ledger_event_id": TEXT},
    required=(NAME, "proposal_id", "decided_by", "decision", "decided_at"),
    statuses=("recorded",),
    classification=CONFIDENTIAL,
    note="§18's last line - *the decision must be persisted* - as its own "
         "record rather than a field on the proposal, so that a denial "
         "followed by a later approval leaves both, in order. `interface` is "
         "which surface Krish answered on: the conversation, or the CLI."))
