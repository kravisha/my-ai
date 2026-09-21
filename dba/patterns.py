"""Data-problem archetypes: the schema patterns the DBA reasons with (§8, §10).

§10 asks the DBA to learn *"what type of problem it represents, what schema
pattern fits it"*. This module is that vocabulary, and it is data rather than
code for the same reason `app/learning/recipe.py` made a learned skill data:
the machinery stays still and what it knows grows.

## Why archetypes rather than free invention

A schema invented fresh for every requirement is a schema that will be subtly
different each time - one capability calling it `assignee`, the next
`assigned_to`, a third `owner` - and §29's reuse goal dies on that. An
archetype is a claim that a class of data problem has a known good shape, and
naming the class is what makes two requirements comparable.

Each archetype carries the answers §8 demands for its class: what the entities
are, what is unique, what changes, what must be searched, what must be indexed,
what history matters. What it deliberately does *not* carry is retention or
permissions - those are properties of the particular requirement, not of the
class, and guessing them is exactly what §19 says to ask about instead.

## The matching is keyword-based, and that is stated rather than hidden

`match` scores a requirement's words against each archetype's triggers. It is
a blunt instrument. It is also inspectable, deterministic and testable, which a
model's opinion would not be - and §36 of the requirements specification keeps
the model out of anything that decides what gets written. When the score is
low or two archetypes tie, that is not a coin toss: `match` says so and the
designer asks (§19's "unclear entity definition").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dba import entities

# A match at or below this is not a match. The designer asks instead of
# guessing, which is §19's first case.
DECISIVE_WEIGHT = 3
WEAK_MATCH = 2
# Two archetypes within this of each other is a tie, and a tie is a question.
TIE_MARGIN = 1


@dataclass(frozen=True)
class Archetype:
    """One known class of persistent-data problem."""

    name: str
    describes: str
    # Words that merely lean towards this class, worth one point each.
    triggers: tuple[str, ...]
    # The fields this class always has, as {name: type}.
    fields: dict[str, str]
    required: tuple[str, ...]
    # Words that all but name this class, worth `DECISIVE_WEIGHT`. The split
    # exists because "work" and "record" appear in almost every requirement
    # while "mailbox" and "handoff" appear in exactly one kind, and a flat
    # count let two weak words outvote one decisive one.
    decisive: tuple[str, ...] = ()
    # What is unique about one record of this class, if anything.
    identifying: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ()
    label: str = entities.NAME
    # Fields worth an index for this class, and why (§8's "what must be
    # indexed"). The reason is carried because an index nobody can justify is
    # an index nobody will dare remove.
    index_on: tuple[str, ...] = ()
    index_because: str = ""
    # Which operations this class needs. A log does not get `update`.
    operations: tuple[str, ...] = ("create", "get", "find", "update", "archive",
                                   "history", "count", "search")
    # What §8 calls "what must never change".
    immutable: tuple[str, ...] = ()
    relationships: tuple[tuple[str, str], ...] = ()
    notes: tuple[str, ...] = ()

    def score(self, words: set[str]) -> int:
        return (sum(1 for trigger in self.triggers if trigger in words)
                + DECISIVE_WEIGHT * sum(1 for trigger in self.decisive
                                        if trigger in words))

    def matched_words(self, words: set[str]) -> list[str]:
        """Which words argued for this archetype, so a design can say why."""
        return sorted({trigger for trigger in self.triggers + self.decisive
                       if trigger in words})

    def to_dict(self) -> dict:
        return {
            "name": self.name, "describes": self.describes,
            "triggers": list(self.triggers), "fields": dict(self.fields),
            "required": list(self.required),
            "identifying": list(self.identifying),
            "statuses": list(self.statuses),
            "index_on": list(self.index_on), "index_because": self.index_because,
            "operations": list(self.operations),
            "immutable": list(self.immutable),
            "notes": list(self.notes),
        }


HANDOFF_QUEUE = Archetype(
    name="handoff_queue",
    describes="one agent assigning a unit of work to another and following it "
              "to completion",
    triggers=("hand", "work", "task", "request", "job", "worker", "agent",
              "another", "complete", "priority"),
    decisive=("handoff", "assign", "assignment", "delegate", "dispatch",
              "queue"),
    fields={
        entities.NAME: entities.TEXT,
        "requested_by": entities.TEXT,
        "assigned_to": entities.TEXT,
        entities.STATUS: entities.TEXT,
        "payload": entities.TEXT,
        "priority": entities.INTEGER,
        "correlation_id": entities.TEXT,
        "due_at": entities.TIMESTAMP,
        "result": entities.TEXT,
        "error": entities.TEXT,
        "accepted_at": entities.TIMESTAMP,
        "completed_at": entities.TIMESTAMP,
    },
    required=(entities.NAME, "requested_by", "assigned_to"),
    identifying=("correlation_id",),
    statuses=("queued", "accepted", "in_progress", "blocked", "done", "failed",
              "cancelled"),
    index_on=("assigned_to", entities.STATUS),
    index_because="the query this class exists to serve is 'what is waiting "
                  "for me?', which is assignee and status together",
    immutable=("requested_by", "correlation_id"),
    notes=("A work request that could change who asked for it is a work "
           "request whose audit trail cannot be trusted.",
           "`correlation_id` is identifying so the same handoff submitted "
           "twice is caught rather than duplicated."))

MESSAGE_STREAM = Archetype(
    name="message_stream",
    describes="durable messages between agents, with acknowledgement and "
              "threading",
    triggers=("send", "notify", "reply", "agent", "between", "structured",
              "acknowledge", "acknowledgement", "receive", "receiver"),
    decisive=("message", "mailbox", "inbox", "exchange", "sender",
              "recipient", "communicate", "communication", "conversation"),
    fields={
        entities.NAME: entities.TEXT,
        "sender": entities.TEXT,
        "recipient": entities.TEXT,
        "message_type": entities.TEXT,
        "payload": entities.TEXT,
        entities.STATUS: entities.TEXT,
        "correlation_id": entities.TEXT,
        "parent_message_id": entities.TEXT,
        "acknowledged_at": entities.TIMESTAMP,
        "error": entities.TEXT,
    },
    required=(entities.NAME, "sender", "recipient"),
    identifying=("correlation_id",),
    statuses=("queued", "delivered", "processing", "completed", "failed",
              "clarification_required", "cancelled"),
    index_on=("recipient", entities.STATUS),
    index_because="a mailbox is read by its recipient, filtered to what is "
                  "still outstanding",
    immutable=("sender", "payload"),
    notes=("A message whose payload can change after sending is not a "
           "message, it is a shared variable.",))

AGENT_STATE = Archetype(
    name="agent_state",
    describes="an agent's durable state, kept so it survives a restart",
    triggers=("setting", "goal", "plan", "memory", "remember", "durable",
              "persist", "persistent", "decision", "survive", "agent"),
    decisive=("state", "configuration", "config", "restart", "checkpoint"),
    fields={
        entities.NAME: entities.TEXT,
        "agent": entities.TEXT,
        "kind": entities.TEXT,
        "value": entities.TEXT,
        entities.STATUS: entities.TEXT,
        "revision": entities.INTEGER,
        "effective_from": entities.TIMESTAMP,
    },
    required=(entities.NAME, "agent", "kind"),
    index_on=("agent", "kind"),
    index_because="every read of this class is 'what does agent X hold for "
                  "kind Y', and it is read on every restart",
    statuses=("current", "superseded"),
    immutable=("agent",),
    notes=("State belonging to an agent that could be reassigned to another "
           "agent is state nobody owns.",))

EVENT_LOG = Archetype(
    name="event_log",
    describes="an append-only record of things that happened",
    triggers=("history", "trail", "record", "everything", "each", "severity"),
    decisive=("log", "event", "happened", "occurred", "journal", "timeline",
              "audit"),
    fields={
        entities.NAME: entities.TEXT,
        "occurred_at": entities.TIMESTAMP,
        "actor": entities.TEXT,
        "subject": entities.TEXT,
        "detail": entities.TEXT,
        "severity": entities.TEXT,
        "correlation_id": entities.TEXT,
    },
    required=(entities.NAME, "occurred_at"),
    statuses=(),
    index_on=("subject", "occurred_at"),
    index_because="a log is read as 'what happened to this thing, in order'",
    # NO `update`. That is the whole claim of this class.
    operations=("create", "get", "find", "count", "search", "history"),
    immutable=(entities.NAME, "occurred_at", "actor", "subject", "detail"),
    notes=("This archetype declares no `update` operation. An event log whose "
           "entries can be edited is a table with timestamps in it.",))

CATALOGUE = Archetype(
    name="catalogue",
    describes="a kind of thing the system keeps a list of, with attributes",
    triggers=("list", "entity", "item", "record", "profile", "detail",
              "attribute"),
    decisive=("catalogue", "catalog", "registry", "directory", "inventory"),
    fields={
        entities.NAME: entities.TEXT,
        "external_id": entities.TEXT,
        "description": entities.TEXT,
        entities.STATUS: entities.TEXT,
    },
    required=(entities.NAME,),
    identifying=("external_id",),
    statuses=("active", "inactive"),
    index_on=(entities.NAME,),
    index_because="a catalogue is looked up by the name people call it",
    notes=("The fallback shape. If the designer reaches for this one on a "
           "requirement that is really a queue or a log, the resulting "
           "capability will work and will be the wrong shape - which is why a "
           "weak match asks rather than settling here.",))

ARCHETYPES = (HANDOFF_QUEUE, MESSAGE_STREAM, AGENT_STATE, EVENT_LOG, CATALOGUE)


def get(name: str) -> Archetype:
    for archetype in ARCHETYPES:
        if archetype.name == name:
            return archetype
    raise KeyError(f"{name!r} is not a known archetype. Known: "
                   f"{', '.join(a.name for a in ARCHETYPES)}")


def words_of(text: str) -> set[str]:
    """The requirement's words, lower-cased and stripped of punctuation.

    Crude stemming - a trailing 's' is dropped - so that "messages" matches the
    trigger "message". Anything cleverer would need a library and would make
    the matching harder to predict, which is the property that matters here."""
    cleaned = "".join(char.lower() if char.isalnum() else " " for char in text)
    found = set()
    for word in cleaned.split():
        found.add(word)
        if word.endswith("s") and len(word) > 3:
            found.add(word[:-1])
    return found


@dataclass(frozen=True)
class Match:
    """Which archetype a requirement looks like, and how sure that is."""

    archetype: Archetype | None
    score: int
    runner_up: Archetype | None
    runner_up_score: int
    confident: bool
    why: str

    def to_dict(self) -> dict:
        return {
            "archetype": self.archetype.name if self.archetype else None,
            "score": self.score,
            "runner_up": self.runner_up.name if self.runner_up else None,
            "runner_up_score": self.runner_up_score,
            "confident": self.confident, "why": self.why,
        }


def match(text: str) -> Match:
    """Which class of data problem this requirement is, or an honest "unsure".

    Never returns a guess dressed as an answer: a weak best score or a near-tie
    sets `confident=False`, and the designer turns that into a question rather
    than into a schema."""
    words = words_of(text)
    scored = sorted(((archetype.score(words), archetype)
                     for archetype in ARCHETYPES),
                    key=lambda pair: (-pair[0], pair[1].name))
    best_score, best = scored[0]
    second_score, second = scored[1] if len(scored) > 1 else (0, None)

    if best_score <= WEAK_MATCH:
        return Match(
            archetype=None, score=best_score, runner_up=best,
            runner_up_score=best_score, confident=False,
            why=(f"the requirement matched no archetype above {WEAK_MATCH} "
                 f"trigger word(s); the closest was {best.name} with "
                 f"{best_score}"))
    if best_score - second_score <= TIE_MARGIN and second is not None:
        return Match(
            archetype=best, score=best_score, runner_up=second,
            runner_up_score=second_score, confident=False,
            why=(f"{best.name} ({best_score}) and {second.name} "
                 f"({second_score}) are within {TIE_MARGIN} of each other, "
                 f"and they produce different shapes"))
    return Match(
        archetype=best, score=best_score, runner_up=second,
        runner_up_score=second_score, confident=True,
        why=f"{best.name} matched {best_score} trigger word(s), clear of "
            f"{second.name if second else 'nothing'} at {second_score}")
