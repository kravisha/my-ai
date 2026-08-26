"""What a task *is*, in the terms routing decides on (TASK_QUEUE TQ-53,
docs/SPEC_RECONCILIATION.md §104).

Source: addendum 45 §20 (task signature), §21 (complexity), §36 (privacy),
§42 (the eight task categories), §45 Phase A.

## Why this is first, and why it has no model in it

Nothing here calls a model, ranks one, or chooses one. This is the vocabulary
every later increment keys off: TQ-54's leaderboards are *per task category*,
TQ-59 decides escalation *from a signature*, TQ-60 maps *signature to
leaderboard*. Getting the terms wrong here would be wrong in four places later.

It is also the only entry in the addendum 45 lineage that needs no hardware, no
downloads and no answers from anybody - which is why it went first while TQ-52
waits on what "Inkling" is.

## Exactly eight categories

Addendum 45 §42: *"Start with exactly these eight… Do not prematurely create
dozens of categories. Allow later subdivision based on evidence."*

That is the same instruction this project has now enforced twice under different
names - §70 refusing addendum 39's parallel asset-class labels, §100 withdrawing
addendum 44's EQUITY/OPTION for the eleven codes that already existed. One model
of one fact, and finer distinctions earned by evidence rather than assumed.

**`CREATIVE_GENERATION` is expected to carry no traffic here.** A financial
intelligence system has no consumer for it. It is built because §42 says start
with exactly these eight, and the expectation is recorded now (§102) so that if
it still has none when TQ-63 has evidence, merging it is the review §42
anticipates rather than a surprise.

## Where a vocabulary already existed, the existing one wins

Four fields in §20 name facts this codebase already had words for. Each was
checked rather than assumed, and the rule is §100's: adopt the house vocabulary
where there is one, adopt the spec's where there is not.

- **`agent_role`** is `backend.fi_db.ROLE_CHARTERS`, not a new list. A role this
  system cannot charter is not one a task may claim.
- **`error_cost`** shares `model_registry.yaml`'s `criticality` values, because
  they are the same fact asked twice - "how much does it cost to be wrong here".
  `test_error_cost_and_registry_criticality_are_one_vocabulary` ties them.
- **`privacy_level`** takes §36's four values, which the project had no
  counterpart for - see the warning below about the name it *does* share.
- **`complexity`** and the eight categories take §21's and §42's labels, in the
  spec's own casing, because nothing here already named them.

## The name collision worth reading twice

`privacy_level = LOCAL_ONLY` and `app.data_classification.DataClass.LOCAL_ONLY`
are **different facts wearing the same name**, and confusing them is the failure
this section exists to prevent.

- `DataClass.LOCAL_ONLY` classifies a **field**: this value never leaves the
  process, unconditionally, stripped by `privacy_filter` on the way out.
- `PRIVACY_LOCAL_ONLY` classifies a **task**: this work may not be sent to an
  external model.

They are related by a derivation, not by identity, and the derivation runs one
way only: a task whose inputs contain a `LOCAL_ONLY` *field* must be a
`LOCAL_ONLY` *task*. The reverse does not hold - plenty of tasks must stay local
for reasons that have nothing to do with field classification.

`privacy_floor_for()` makes that derivation mechanical rather than a note
somebody has to remember, because §36's rule - *"sensitive data should never be
sent externally merely because the external model ranks higher"* - is worth
exactly as much as its enforcement.

## Absent is unknown, never a default that reads as a measurement

`context_length` is `None` when nobody has estimated it, never `0` - zero would
claim an empty context, which is a different and false statement. `novelty`,
`ambiguity` and `latency_sensitivity` carry `unknown` as a **member** of their
vocabulary rather than as an absence, the same choice §100 made for
`asset_class`.

What `unknown` *means for routing* is deliberately not decided here. This module
says what a task is; TQ-59 and TQ-60 say what to do about it.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from backend.fi_db import ROLE_CHARTERS

SCHEMA_VERSION = 1

# --- the eight task categories (§42) ------------------------------------------------
#
# Exactly these. Adding a ninth is a decision with evidence behind it, not a
# convenience - `test_there_are_exactly_eight_categories` is the tripwire.

CATEGORY_GENERAL_REASONING = "GENERAL_REASONING_AND_PLANNING"
CATEGORY_CODING = "CODING_AND_DEBUGGING"
CATEGORY_LONG_CONTEXT = "LONG_CONTEXT_AND_MEMORY"
CATEGORY_CLASSIFICATION = "CLASSIFICATION_AND_ROUTING"
CATEGORY_FINANCIAL = "FINANCIAL_AND_ANALYTICAL_REASONING"
CATEGORY_SUMMARIZATION = "SUMMARIZATION_AND_KNOWLEDGE_EXTRACTION"
CATEGORY_CREATIVE = "CREATIVE_GENERATION"
CATEGORY_ESCALATION = "CAPABILITY_AND_ESCALATION_DECISION"

TASK_CATEGORIES = (
    CATEGORY_GENERAL_REASONING,
    CATEGORY_CODING,
    CATEGORY_LONG_CONTEXT,
    CATEGORY_CLASSIFICATION,
    CATEGORY_FINANCIAL,
    CATEGORY_SUMMARIZATION,
    CATEGORY_CREATIVE,
    CATEGORY_ESCALATION,
)

# §17: deciding whether local intelligence suffices is *itself* an intelligent
# task, so it gets a category rather than a constant - and the model best at
# making that call need not be the model best at doing the work.
ESCALATION_CATEGORY = CATEGORY_ESCALATION

# --- complexity (§21) ---------------------------------------------------------------
#
# "Complexity should be one routing input, not the entire routing rule" (§21).
# Named here, weighted nowhere - weighting is TQ-60's.

COMPLEXITY_TRIVIAL = "TRIVIAL"
COMPLEXITY_SIMPLE = "SIMPLE"
COMPLEXITY_MODERATE = "MODERATE"
COMPLEXITY_COMPLEX = "COMPLEX"
COMPLEXITY_HIGH_STAKES = "HIGH_STAKES"
COMPLEXITY_SPECIALIZED = "SPECIALIZED"

COMPLEXITIES = (COMPLEXITY_TRIVIAL, COMPLEXITY_SIMPLE, COMPLEXITY_MODERATE,
                COMPLEXITY_COMPLEX, COMPLEXITY_HIGH_STAKES, COMPLEXITY_SPECIALIZED)

# --- privacy (§36) ------------------------------------------------------------------
#
# Read the module docstring before using these: LOCAL_ONLY here is a *task*
# constraint and DataClass.LOCAL_ONLY is a *field* classification. Different
# facts, one name, one derivation between them (`privacy_floor_for`).

PRIVACY_LOCAL_ONLY = "LOCAL_ONLY"
PRIVACY_LOCAL_PREFERRED = "LOCAL_PREFERRED"
PRIVACY_EXTERNAL_ALLOWED = "EXTERNAL_ALLOWED"
PRIVACY_EXTERNAL_REQUIRED = "EXTERNAL_REQUIRED"

PRIVACY_LEVELS = (PRIVACY_LOCAL_ONLY, PRIVACY_LOCAL_PREFERRED,
                  PRIVACY_EXTERNAL_ALLOWED, PRIVACY_EXTERNAL_REQUIRED)

# Most restrictive first. Ordering exists so `privacy_floor_for` can answer "at
# least this restrictive" without every caller re-deriving it - and so that
# adding a level forces somebody to place it deliberately.
PRIVACY_ORDER = (PRIVACY_LOCAL_ONLY, PRIVACY_LOCAL_PREFERRED,
                 PRIVACY_EXTERNAL_ALLOWED, PRIVACY_EXTERNAL_REQUIRED)

# --- error cost, novelty, ambiguity, latency (§20) -----------------------------------
#
# `error_cost` deliberately reuses model_registry.yaml's `criticality` values:
# "how much does it cost to be wrong here" asked twice is one fact, and two
# vocabularies for it is what §70 and §100 each refused once.

ERROR_COST_LOW = "low"
ERROR_COST_MEDIUM = "medium"
ERROR_COST_HIGH = "high"
ERROR_COSTS = (ERROR_COST_LOW, ERROR_COST_MEDIUM, ERROR_COST_HIGH)

# `unknown` is a member rather than an absence (§100's choice for asset_class):
# "nobody estimated this" is a recorded fact, not a gap each reader interprets.
UNKNOWN = "unknown"

JUDGEMENT_LOW = "low"
JUDGEMENT_MEDIUM = "medium"
JUDGEMENT_HIGH = "high"
JUDGEMENTS = (JUDGEMENT_LOW, JUDGEMENT_MEDIUM, JUDGEMENT_HIGH, UNKNOWN)

LATENCY_INTERACTIVE = "interactive"
LATENCY_SECONDS = "seconds"
LATENCY_MINUTES = "minutes"
LATENCY_BATCH = "batch"
LATENCY_SENSITIVITIES = (LATENCY_INTERACTIVE, LATENCY_SECONDS, LATENCY_MINUTES,
                         LATENCY_BATCH, UNKNOWN)


class UnknownVocabulary(ValueError):
    """A value outside a closed vocabulary, on construction or on read. Fail
    closed: a task this build cannot interpret is not one it may route."""


def _check(value, vocabulary: tuple[str, ...], field: str) -> str:
    if value not in vocabulary:
        raise UnknownVocabulary(
            f"unknown {field} {value!r}; known are {list(vocabulary)}")
    return value


@dataclass(frozen=True)
class TaskSignature:
    """Addendum 45 §20's fifteen fields, normalized.

    Frozen, like `OwnerContext` and `Holding` and for the same reason: it is the
    description a routing decision was made against, and something that could be
    reassigned between classification and selection is not a description of what
    was routed.

    The four fields with no default are the four that drive routing hardest, and
    `privacy_level` is required on purpose: a task whose privacy nobody stated
    must not acquire `EXTERNAL_ALLOWED` by default. §36's rule is that sensitive
    data never leaves because a model ranked higher, and a default would be the
    quietest way to break it."""

    task_category: str
    complexity: str
    privacy_level: str
    error_cost: str

    agent_role: str | None = None
    domain: str | None = None
    # Estimated tokens, or None when nobody has estimated it. Never 0 - zero
    # claims an empty context, which is a different and false statement.
    context_length: int | None = None
    coding_required: bool = False
    math_required: bool = False
    structured_output_required: bool = False
    external_data_required: bool = False
    tool_use_required: bool = False
    latency_sensitivity: str = UNKNOWN
    novelty: str = UNKNOWN
    ambiguity: str = UNKNOWN

    def __post_init__(self) -> None:
        _check(self.task_category, TASK_CATEGORIES, "task category")
        _check(self.complexity, COMPLEXITIES, "complexity")
        _check(self.privacy_level, PRIVACY_LEVELS, "privacy level")
        _check(self.error_cost, ERROR_COSTS, "error cost")
        _check(self.latency_sensitivity, LATENCY_SENSITIVITIES, "latency sensitivity")
        _check(self.novelty, JUDGEMENTS, "novelty")
        _check(self.ambiguity, JUDGEMENTS, "ambiguity")

        if self.agent_role is not None and self.agent_role not in ROLE_CHARTERS:
            raise UnknownVocabulary(
                f"unknown agent role {self.agent_role!r}; this system charters "
                f"{sorted(ROLE_CHARTERS)}. A role it cannot charter is not one a "
                "task may claim.")
        if self.context_length is not None and self.context_length <= 0:
            raise UnknownVocabulary(
                "context_length must be a positive estimate or None. Zero claims an "
                "empty context, which is a different statement from 'nobody measured "
                "it'.")

    def as_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, raw: dict) -> "TaskSignature":
        """Rebuild a signature from stored data, validating on the way in.

        Fail closed on **read** as well as write, the rule every closed
        vocabulary here works under: a signature written by an older build, a
        hand edit or a restored backup must not be interpreted by guessing what
        its values meant. A routing decision replayed from an uninterpretable
        signature would be a decision about a task nobody can describe."""
        known = {f.name for f in fields(cls)}
        unexpected = set(raw) - known
        if unexpected:
            raise UnknownVocabulary(
                f"task signature carries unknown field(s) {sorted(unexpected)}; "
                f"known are {sorted(known)}")
        return cls(**raw)


# --- the derivation between field classification and task privacy -------------------

# Which routing privacy a data class forces, at minimum. Only LOCAL_ONLY forces
# anything: the other classes describe what *may* be shared, which is not the
# same as a task that must stay home.
_DATA_CLASS_FLOOR = {"local_only": PRIVACY_LOCAL_ONLY}


def privacy_floor_for(data_classes) -> str | None:
    """The most restrictive routing privacy these field classifications force,
    or None if they force nothing.

    §36's rule made mechanical: *"sensitive data should never be sent externally
    merely because the external model ranks higher."* A task carrying a
    `DataClass.LOCAL_ONLY` field is a `LOCAL_ONLY` task, and that is a
    derivation rather than a reminder in a docstring.

    Runs one way only. A `LOCAL_ONLY` field forces a `LOCAL_ONLY` task; a
    `LOCAL_ONLY` task implies nothing about its fields, because plenty of work
    stays home for reasons that have nothing to do with field classification.

    Accepts `DataClass` members or their string values, so a caller holding
    either does not have to convert first."""
    floors = []
    for item in data_classes:
        value = getattr(item, "value", item)
        floor = _DATA_CLASS_FLOOR.get(value)
        if floor is not None:
            floors.append(floor)
    if not floors:
        return None
    return min(floors, key=PRIVACY_ORDER.index)


def at_least_as_restrictive(level: str, floor: str) -> bool:
    """Whether `level` is no less restrictive than `floor`. For TQ-60's override
    check; here because the ordering it reads lives here."""
    _check(level, PRIVACY_LEVELS, "privacy level")
    _check(floor, PRIVACY_LEVELS, "privacy level")
    return PRIVACY_ORDER.index(level) <= PRIVACY_ORDER.index(floor)
