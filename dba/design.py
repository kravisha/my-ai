"""Reasoning from a task to a data model (§8), and asking when it cannot (§19).

## What this module is answerable for

§8 lists twelve questions a design must answer:

    What are the entities? What are their attributes? How are they related?
    What must be unique? What can change? What must never change? What history
    must be preserved? What will agents need to search? What must be indexed?
    What must be audited? What should be retained? What should eventually
    expire?

`Design.reasoning` answers all twelve, in words, attached to the design. Not as
documentation - as the thing a reviewer reads instead of the schema, and the
thing `dba/experience.py` stores so the next design can start from it. A design
that cannot say why it has the shape it has is a design nobody can correct.

## The three things it will not do

**It will not guess the class of problem.** `dba/patterns.match` reports
whether it is sure, and an unsure match becomes §19's "unclear entity
definition" rather than the fallback shape.

**It will not invent a permission.** A requirement that does not say who reads
and who writes produces a question, because a capability published with a
guessed grant is a data surface somebody can reach that nobody decided they
could.

**It will not leave retention unanswered.** §8 asks what should eventually
expire. "Nobody said" is not `keep_forever`; it is a question. A table that
grows until somebody notices is the default this refuses to have.

## Why the designer does not call a model

The requirements specification's §36 keeps the model out of anything that
decides what is written, and a schema decides what can ever be written. A model
may turn Krish's sentence into a `Requirement` before it arrives here. From
there it is archetype matching, rules, and questions - deterministic, so the
same requirement designs the same schema twice, which is what makes §27's
generated tests meaningful and §35's golden tests possible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.db import Database
from dba import capability, entities, patterns, permissions

# §19's eight cases, as a closed vocabulary.
UNCLEAR_ENTITY = "unclear_entity_definition"
CONFLICTING_REQUIREMENTS = "conflicting_requirements"
UNKNOWN_OWNERSHIP = "unknown_ownership"
UNCLEAR_RETENTION = "unclear_retention"
AMBIGUOUS_IDENTITY = "ambiguous_identity"
UNCERTAIN_RELATIONSHIP = "uncertain_relationship"
UNSAFE_DELETION = "unsafe_deletion"
INSUFFICIENT_PERMISSIONS = "insufficient_permission_information"

DESIGN_QUESTIONS = (UNCLEAR_ENTITY, CONFLICTING_REQUIREMENTS, UNKNOWN_OWNERSHIP,
                    UNCLEAR_RETENTION, AMBIGUOUS_IDENTITY,
                    UNCERTAIN_RELATIONSHIP, UNSAFE_DELETION,
                    INSUFFICIENT_PERMISSIONS)

# How much field overlap makes an existing capability a candidate for reuse
# rather than a coincidence (§29).
REUSE_OVERLAP = 0.6

_STOPWORDS = frozenset((
    "a", "an", "the", "to", "of", "for", "and", "or", "so", "that", "this",
    "with", "in", "on", "at", "by", "from", "need", "needs", "create",
    "please", "some", "new", "persistent", "system", "structured", "able",
    "can", "should", "must", "we", "i", "it", "be", "is", "are", "want"))


@dataclass(frozen=True)
class Question:
    """One thing the DBA will not decide on its own."""

    reason: str
    question: str
    options: tuple = ()
    about: str = ""

    def __post_init__(self) -> None:
        if self.reason not in DESIGN_QUESTIONS:
            raise ValueError(f"design question reason={self.reason!r} is not "
                             f"one of {DESIGN_QUESTIONS}")

    def to_dict(self) -> dict:
        return {"reason": self.reason, "question": self.question,
                "options": list(self.options), "about": self.about}


@dataclass(frozen=True)
class Requirement:
    """What a requesting agent says it needs.

    Deliberately small. Everything here is something the *requester* knows and
    the DBA cannot deduce - who will read it, who will write it, how long it
    should live - and everything else is the DBA's job. A requirement that has
    to spell out the schema has not asked the DBA to design anything."""

    task: str
    requested_by: str
    name: str | None = None
    readers: tuple[str, ...] = ()
    writers: tuple[str, ...] = ()
    retention: capability.Retention | None = None
    sensitive: bool = False
    # Fields the requester knows it needs beyond the archetype's, as
    # {name: type}. The DBA validates them; it does not discard them.
    extra_fields: dict[str, str] = field(default_factory=dict)
    relates_to: tuple[tuple[str, str], ...] = ()
    # Whether records of this kind may ever be hard-deleted (§19's unsafe
    # deletion). None means nobody said, which is a question.
    deletable: bool | None = None
    # Answers to questions from a previous pass, keyed by reason.
    answers: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "task": self.task, "requested_by": self.requested_by,
            "name": self.name, "readers": list(self.readers),
            "writers": list(self.writers),
            "retention": self.retention.to_dict() if self.retention else None,
            "sensitive": self.sensitive,
            "extra_fields": dict(self.extra_fields),
            "relates_to": [list(pair) for pair in self.relates_to],
            "deletable": self.deletable, "answers": dict(self.answers),
        }


@dataclass(frozen=True)
class Design:
    """A proposed capability, what was asked, and why it looks like this."""

    requirement: Requirement
    match: patterns.Match
    capability: capability.Capability | None
    questions: tuple[Question, ...]
    reasoning: dict
    reuse: dict | None = None

    @property
    def ready(self) -> bool:
        return self.capability is not None and not self.questions

    def to_dict(self) -> dict:
        return {
            "ready": self.ready,
            "requirement": self.requirement.to_dict(),
            "match": self.match.to_dict(),
            "capability": self.capability.to_dict() if self.capability else None,
            "questions": [question.to_dict() for question in self.questions],
            "reasoning": self.reasoning,
            "reuse": self.reuse,
        }


def slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return re.sub(r"_+", "_", cleaned)


def derive_name(text: str, archetype: patterns.Archetype) -> str:
    """A name for the capability, from the requirement's own words.

    The word in front of the decisive trigger, joined to it: *"a persistent
    task handoff system"* becomes `task_handoff`. When there is no such word
    the archetype's own name is used, which is honest rather than clever - the
    requester can always name it themselves, and `reasoning` says which
    happened."""
    tokens = [slugify(word) for word in re.split(r"\W+", text or "") if word]
    for index, token in enumerate(tokens):
        stem = token[:-1] if token.endswith("s") and len(token) > 3 else token
        if stem in archetype.decisive:
            previous = tokens[index - 1] if index else ""
            if previous and previous not in _STOPWORDS and not previous.isdigit():
                return f"{previous}_{stem}"
            return stem
    return archetype.name


def design(requirement: Requirement, conn: Database | None = None) -> Design:
    """Turn a requirement into a proposed capability, or into questions."""
    questions: list[Question] = []
    answers = requirement.answers or {}

    # --- what class of problem is this? (§8, "what are the entities?") --------
    matched = patterns.match(requirement.task)
    chosen_name = answers.get(UNCLEAR_ENTITY)
    archetype = None
    if chosen_name:
        archetype = patterns.get(chosen_name)
    elif matched.confident:
        archetype = matched.archetype

    if archetype is None:
        options = ([matched.archetype.name, matched.runner_up.name]
                   if matched.archetype and matched.runner_up
                   else [item.name for item in patterns.ARCHETYPES])
        questions.append(Question(
            reason=UNCLEAR_ENTITY,
            question=(f"I cannot tell what kind of data problem this is: "
                      f"{matched.why}. Which shape does it need?"),
            options=tuple({"archetype": name, "describes": patterns.get(name).describes}
                          for name in dict.fromkeys(options)),
            about="the shape of the schema"))
        return Design(requirement, matched, None, tuple(questions),
                      _reasoning(requirement, None, None), None)

    name = slugify(requirement.name or derive_name(requirement.task, archetype))

    if entities.is_built_in(name):
        # Caught here rather than at publication. A capability published under
        # a built-in's name would make `sync_entities` raise on every request
        # from then on, and designing one failed all fifteen self-tests with an
        # opaque internal error - a bad answer to a question that has an
        # obvious good one.
        questions.append(Question(
            reason=CONFLICTING_REQUIREMENTS,
            question=(f"{name!r} is already a built-in type of this system, and "
                      f"a capability may not redefine one - that would change "
                      f"what stored rows mean by writing a row. Name it "
                      f"something else, or say that the built-in already does "
                      f"what you need."),
            options=({"existing_type": name,
                      "fields": sorted(entities.get(name).fields)},),
            about="naming"))
        return Design(requirement, matched, None, tuple(questions),
                      _reasoning(requirement, archetype, None), None)

    # --- §29: has this been solved already? -----------------------------------
    reuse = _reuse_candidate(conn, archetype, name) if conn is not None else None

    # --- who reads and who writes? (§19's ownership and permissions) ----------
    writers = tuple(requirement.writers or answers.get(UNKNOWN_OWNERSHIP, ()) or ())
    readers = tuple(requirement.readers
                    or answers.get(INSUFFICIENT_PERMISSIONS, ()) or ())
    if not writers and not readers:
        questions.append(Question(
            reason=INSUFFICIENT_PERMISSIONS,
            question=(f"Nobody is named as reading or writing {name}. I will "
                      f"not guess a grant - a capability published with an "
                      f"invented one is a data surface somebody can reach that "
                      f"nobody decided they could. Which agents read it, and "
                      f"which write it?"),
            options=tuple({"agent": agent} for agent in sorted(permissions.POLICY)),
            about="permissions"))
    elif not writers:
        questions.append(Question(
            reason=UNKNOWN_OWNERSHIP,
            question=(f"{name} has readers but no writer, so nothing would ever "
                      f"put a record in it. Which agent owns writing to it?"),
            options=tuple({"agent": agent} for agent in sorted(permissions.POLICY)),
            about="ownership"))

    unknown = sorted({agent for agent in writers + readers
                      if not permissions.known_agent(agent)})
    if unknown:
        questions.append(Question(
            reason=INSUFFICIENT_PERMISSIONS,
            question=(f"{', '.join(unknown)} is not an agent this system's "
                      f"policy knows, so I cannot grant it anything. Should it "
                      f"be declared first, or did you mean another agent?"),
            options=tuple({"agent": agent} for agent in sorted(permissions.POLICY)),
            about="permissions"))

    # --- how long do these records live? (§8's "what should expire") ----------
    retention = requirement.retention
    if retention is None and answers.get(UNCLEAR_RETENTION):
        retention = capability.Retention.from_dict(answers[UNCLEAR_RETENTION])
    if retention is None:
        questions.append(Question(
            reason=UNCLEAR_RETENTION,
            question=(f"How long should a {name} record live? §8 asks what "
                      f"should eventually expire, and 'nobody said' is not the "
                      f"same as 'keep forever' - a table that grows until "
                      f"somebody notices is what that default produces."),
            options=(
                {"rule": capability.KEEP_FOREVER,
                 "means": "kept indefinitely; right for anything auditable"},
                {"rule": capability.KEEP_WHILE_REFERENCED,
                 "means": "kept while something still links to it"},
                {"rule": capability.ARCHIVE_AFTER_DAYS, "needs": "days",
                 "means": "hidden from normal reads after N days, still there"},
                {"rule": capability.DELETE_AFTER_DAYS, "needs": "days",
                 "means": "removed after N days; only for data you must not keep"}),
            about="retention"))

    # --- may these ever be hard-deleted? (§19's unsafe deletion) --------------
    deletable = requirement.deletable
    if deletable is None and UNSAFE_DELETION in answers:
        deletable = bool(answers[UNSAFE_DELETION])
    if deletable is None and retention is not None \
            and retention.rule == capability.DELETE_AFTER_DAYS:
        questions.append(Question(
            reason=UNSAFE_DELETION,
            question=(f"{name} is set to delete records after "
                      f"{retention.days} days, but nobody said whether an agent "
                      f"may delete one on demand. Those are different powers "
                      f"and the second one is the dangerous half."),
            options=({"deletable": False,
                      "means": "only the retention rule removes records"},
                     {"deletable": True,
                      "means": "an authorised agent may delete one directly"}),
            about="deletion"))

    # --- what must be unique? (§8, and §19's ambiguous identity) --------------
    identifying = archetype.identifying
    if not identifying and archetype.name != patterns.EVENT_LOG.name:
        if answers.get(AMBIGUOUS_IDENTITY):
            identifying = tuple(answers[AMBIGUOUS_IDENTITY])
        else:
            questions.append(Question(
                reason=AMBIGUOUS_IDENTITY,
                question=(f"Nothing about a {name} is declared unique, so two "
                          f"identical records would both be accepted and "
                          f"nothing could later tell them apart. Which field "
                          f"identifies one?"),
                options=tuple({"field": field_name}
                              for field_name in sorted(archetype.fields)),
                about="identity"))

    # --- relationships (§19's uncertain relationship) -------------------------
    relationships: list[capability.Relationship] = []
    for relation, target in requirement.relates_to:
        if not entities.known(target):
            questions.append(Question(
                reason=UNCERTAIN_RELATIONSHIP,
                question=(f"{name} is meant to relate to {target!r} by "
                          f"{relation!r}, but no such type exists. Should it be "
                          f"designed first?"),
                options=tuple({"type": item.name} for item in entities.all_types()),
                about="relationships"))
            continue
        relationships.append(capability.Relationship(
            relation=relation, from_type=name, to_type=target,
            description=f"a {name} {relation.replace('_', ' ')} a {target}"))

    # --- contradictions (§19's conflicting requirements) ----------------------
    immutable_but_writable = sorted(
        set(archetype.immutable) & set(requirement.extra_fields))
    because = (archetype.notes[0] if archetype.notes
               else "it is part of what the record is")
    for field_name in immutable_but_writable:
        questions.append(Question(
            reason=CONFLICTING_REQUIREMENTS,
            question=(f"{field_name!r} never changes in a {archetype.name} - "
                      f"{because} - but the requirement redeclares it as a "
                      f"field to write. Which is intended?"),
            options=({"keep_immutable": True}, {"make_writable": True}),
            about="conflicting fields"))

    bad_fields = {
        field_name: declared
        for field_name, declared in requirement.extra_fields.items()
        if declared not in entities.FIELD_TYPES}
    for field_name, declared in sorted(bad_fields.items()):
        questions.append(Question(
            reason=CONFLICTING_REQUIREMENTS,
            question=(f"field {field_name!r} was asked for as type "
                      f"{declared!r}, which is not a type this system has. "
                      f"Which of {', '.join(entities.FIELD_TYPES)}?"),
            options=tuple({"type": name} for name in entities.FIELD_TYPES),
            about="field types"))

    if questions:
        return Design(requirement, matched, None, tuple(questions),
                      _reasoning(requirement, archetype, None), reuse)

    # --- assemble ------------------------------------------------------------
    fields = dict(archetype.fields)
    fields.update({key: value for key, value in requirement.extra_fields.items()
                   if key not in archetype.immutable})

    classification = (entities.SENSITIVE if requirement.sensitive
                      else entities.INTERNAL)
    entity_type = entities.EntityType(
        name=name, fields=fields, required=archetype.required,
        identifying=tuple(item for item in identifying if item in fields),
        label=archetype.label if archetype.label in fields else entities.NAME,
        statuses=archetype.statuses, classification=classification,
        note=f"designed from: {requirement.task}")

    operations = list(archetype.operations)
    if deletable:
        operations.append("delete_authorized")
    if relationships and "link" not in operations:
        operations += ["link", "unlink"]

    grants: dict[str, tuple[str, ...]] = {}
    for agent in readers:
        grants[agent] = (permissions.READ,)
    for agent in writers:
        held = {permissions.READ, permissions.CREATE, permissions.UPDATE,
                permissions.ARCHIVE}
        if deletable:
            # DECLARED AND GRANTED, OR NEITHER. The first version added
            # `delete_authorized` to the operations and gave the permission to
            # nobody, so the endpoint was published, documented, and refused
            # for every agent alive. An operation nothing can call is a lie in
            # the contract.
            held.add(permissions.DELETE)
        if requirement.sensitive:
            held |= {permissions.READ_SENSITIVE, permissions.WRITE_SENSITIVE}
        grants[agent] = tuple(sorted(held | set(grants.get(agent, ()))))
    if requirement.sensitive:
        for agent in readers:
            grants[agent] = tuple(sorted(set(grants[agent]) | {permissions.READ_SENSITIVE}))

    # THE OWNER IS NEVER LOCKED OUT OF THEIR OWN DATA.
    #
    # Capability grants are checked on top of the global policy, so a
    # capability that did not name Krish's console made his own records
    # unreadable to him - by a rule the DBA wrote for him, which is the wrong
    # way round. The console already holds `administer` globally and is the
    # hand that published this in the first place.
    grants[permissions.OPERATOR_CONSOLE] = tuple(sorted(
        set(permissions.permissions_of(permissions.OPERATOR_CONSOLE))))

    designed = capability.Capability(
        name=name, version=1, purpose=requirement.task.strip(),
        entity_type=entity_type, retention=retention,
        operations=tuple(dict.fromkeys(operations)), grants=grants,
        relationships=tuple(relationships),
        indexes=tuple(item for item in archetype.index_on if item in fields),
        examples=_examples(name, entity_type),
        requirement=requirement.task, designed_by=permissions.DBA,
        notes=archetype.notes + (
            f"matched archetype {archetype.name}: {matched.why}",))

    return Design(requirement, matched, designed, (),
                  _reasoning(requirement, archetype, designed), reuse)


def _examples(name: str, entity_type: entities.EntityType) -> tuple[dict, ...]:
    """§25 wants examples. Built from the declaration so they cannot drift."""
    sample = {}
    for field_name in entity_type.required:
        declared = entity_type.fields.get(field_name, entities.TEXT)
        sample[field_name] = {
            entities.TEXT: f"<{field_name}>", entities.EMAIL: "someone@example.com",
            entities.PHONE: "+1 555 0100", entities.INTEGER: 1,
            entities.NUMBER: 1.0, entities.BOOLEAN: True,
            entities.DATE: "2026-09-21",
            entities.TIMESTAMP: "2026-09-21T09:00:00+00:00",
        }.get(declared, f"<{field_name}>")
    if entity_type.statuses:
        sample[entities.STATUS] = entity_type.statuses[0]
    return ({"operation": "create", "request": {"data": sample}},)


def _reasoning(requirement: Requirement,
               archetype: patterns.Archetype | None,
               designed: capability.Capability | None) -> dict:
    """§8's twelve questions, answered in words, attached to the design."""
    if archetype is None:
        return {"entities": "undetermined - the class of problem is not clear "
                            "yet, and every other answer depends on it"}
    entity_type = designed.entity_type if designed else None
    changeable = (sorted(set(entity_type.fields) - set(archetype.immutable))
                  if entity_type else
                  sorted(set(archetype.fields) - set(archetype.immutable)))
    return {
        "entities": (f"one: {designed.name if designed else archetype.name}, a "
                     f"{archetype.name} - {archetype.describes}"),
        "attributes": sorted(entity_type.fields) if entity_type
        else sorted(archetype.fields),
        "relationships": ([r.to_dict() for r in designed.relationships]
                          if designed else []) or
        "none declared; records stand alone",
        "unique": (list(entity_type.identifying) if entity_type
                   and entity_type.identifying else
                   "nothing beyond the identifier the DBA issues"),
        "can_change": changeable,
        "never_changes": (list(archetype.immutable) or
                          "nothing is declared immutable for this class"),
        "history_preserved": ("every change, in the audit trail: who asked, "
                              "which agent, what moved, when and why"),
        "searched_by": (list(designed.indexes) if designed and designed.indexes
                        else "the identifier and free text"),
        "indexed": (f"{list(designed.indexes)} - {archetype.index_because}"
                    if designed and designed.indexes else "nothing beyond the key"),
        "audited": ("every write, and every refusal; reads are not audited "
                    "because a log that is mostly reads hides the writes"),
        "retained": (requirement.retention.describe() if requirement.retention
                     else "not yet decided - this is an open question"),
        "expires": (requirement.retention.describe() if requirement.retention
                    else "not yet decided - this is an open question"),
    }


def _reuse_candidate(conn: Database, archetype: patterns.Archetype,
                     name: str) -> dict | None:
    """§29: is there already something that does this?

    Checked before designing rather than after, because a duplicate found
    afterwards has already cost the design. Same archetype and enough field
    overlap is the test - two capabilities of the same class that share most of
    their fields are the same capability with two names."""
    from dba import registry

    for existing in registry.published(conn):
        if existing.name == name:
            return {"capability": existing.key, "why": "same name",
                    "recommendation": "extend it as a new version rather than "
                                      "designing a second one"}
        theirs = set(existing.entity_type.fields)
        mine = set(archetype.fields)
        overlap = len(theirs & mine) / max(1, len(mine))
        if overlap >= REUSE_OVERLAP and archetype.name in " ".join(existing.notes):
            return {"capability": existing.key,
                    "why": f"{int(overlap * 100)}% of the fields this design "
                           f"needs already exist there, and it is the same "
                           f"kind of problem",
                    "recommendation": "reuse it, or extend it as a new version"}
    return None
