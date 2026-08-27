"""The governed knowledge layer: which rule governs, and what may not override it
(TASK_QUEUE TQ-82; addendum 46 §4, §5, §17, §18; addendum 30 §12;
docs/SPEC_RECONCILIATION.md §119, §120, §123, §125).

Addendum 46 §2's architecture is *stable machinery, evolving data*: the
organization's laws, policies, procedures, strategies and directives live as
governed data rather than as program logic, so changing a rule is a change to
data and not a release.

This is the store that makes that true, and almost all of it is the ordering.
Holding the text is trivial. Answering *which text governs* without letting a
lower authority quietly become the answer is the whole problem.

## The rule this exists to enforce

Addendum 46 §5:

> *"Lower-level material cannot silently override higher-level authority."*

**The load-bearing word is `silently`.** Lower-level material sitting beside
higher-level material is ordinary - a procedure lives under a policy, and both
are true at once. What may never happen is a caller asking what governs a subject
and receiving the procedure because the query ordered it first.

So precedence is enforced **on read**. `effective()` returns the highest
authority active on a subject and nothing else can be returned; anything below it
is reachable only through `subordinate()`, which says what it is.

## The honest limit, stated rather than discovered

**This detects precedence violations. It does not detect contradictions.**

Two items at the same level on one subject saying opposite things are caught,
because the store refuses to have two equal authorities on one subject and
`effective()` fails closed rather than picking. An item claiming to replace
something above it is caught, because that is the silent override written down.

A procedure whose *words* quietly contradict the policy above it is **not**
caught. Nothing here reads the text. Saying so is part of the guarantee - a
governance layer implying it could catch a semantic contradiction would be the
falsely-written charter `backend/charter.py` exists to avoid, and §123 made the
same admission one level up about the Constitution.

## Authority requires provenance

Levels 3-9 - law through project instruction - are adopted **only** by an enacted
resolution, and the resolution's own `affects` level must match. The authority
you were granted is the authority you get: a resolution enacted for an
organization policy cannot be spent on a law.

Levels 10-12 - knowledge, observation, suggestion - need no vote, because they
carry no authority. They are the material an agent may file freely, and
`effective()` will happily return one when nothing above it exists on the
subject. That is correct: in the absence of a rule, the best available knowledge
is what the organization has.

## What lives here and what does not

Not the Constitution (§120 - it is nowhere in this system). Not the Articles;
they are Parliament's own record and `backend/parliament.py` holds their
versions. Not lessons and open questions - `knowledge_records` in `fi_db` has
held those since long before this existed, and duplicating them here would
manufacture the two-sources-of-truth problem §54 already declined once. This
store holds **instruments**: things adopted, that govern, and that can be
superseded.

Sits below `fi_db` (`fi_db.init_schema` creates this table), so it must not
import it.
"""

from __future__ import annotations

from backend import parliament
from backend.db import Database, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS governed_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    adopted_at TEXT NOT NULL,
    -- What this is about. Precedence is answered per subject, so two rules only
    -- compete when they claim the same one.
    subject TEXT NOT NULL,
    -- Where it sits in addendum 46 §5's hierarchy.
    level TEXT NOT NULL,
    text TEXT NOT NULL,
    -- Addendum 46 §17: who proposed it, what authorized it, what it replaced.
    adopted_by TEXT NOT NULL,
    resolution_id INTEGER,
    replaces INTEGER,
    -- Superseded, never deleted (addendum 46 §18: nothing erases history).
    superseded_at TEXT,
    superseded_by INTEGER,
    schema_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS governed_items_active ON governed_items (subject, superseded_at);
"""

SCHEMA_VERSION = 1

# The precedence order is `parliament.LEVELS` and is not restated here. One place
# for the hierarchy, or two places that drift.
LEVELS = parliament.LEVELS

# Levels an enacted resolution must authorize. Everything between a law and a
# project instruction governs somebody, so somebody had to vote for it.
AUTHORIZED_LEVELS = (
    "law", "organization_policy", "department_policy", "procedure",
    "strategy", "operational_directive", "project_instruction",
)

# Levels anyone may file. They carry no authority over anything, which is exactly
# why they need none to exist.
UNGOVERNED_LEVELS = ("knowledge", "observation", "suggestion")

# The same words `parliament` refuses with, imported rather than copied: a second
# refusal string that drifted would be a way to tell the two boundaries apart.
REFUSAL = parliament.REFUSAL


class NotGoverned(LookupError):
    """Nothing governs this subject."""


class AmbiguousAuthority(RuntimeError):
    """Two active items claim the same subject at the same level.

    Raised on **read**, which is the point. A store that answered anyway would be
    resolving a governance conflict by whichever row the query happened to order
    first - the one thing addendum 46 §5 forbids, arriving through the least
    visible door in the system."""


class AdoptionRefused(PermissionError):
    """An item this layer will not take."""


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)


def adopt(
    conn: Database,
    *,
    subject: str,
    level: str,
    text: str,
    adopted_by: str,
    resolution_id: int | None = None,
    replaces: int | None = None,
) -> int:
    """Put an instrument into force.

    Four ways this is refused, and they are not all the same kind of refusal:

    - **Level 0, or a level that does not exist** - identical words, and
      escalated to the owner. §123's rule: a caller able to tell *"that level does
      not exist"* from *"that level is out of reach"* can map the boundary by
      probing it.
    - **The Articles** - refused by name, because they are Parliament's record and
      not this store's. Nothing is hidden by saying so; the Speaker reports their
      version publicly.
    - **No authorizing resolution, or the wrong one** - refused plainly. This says
      nothing about what the store contains, only about what the caller brought,
      so an identical-refusal rule would hide a mistake for no benefit.
    - **Claiming to replace something above you** - refused *and escalated*,
      because that is the silent override with its intent declared out loud.
    """
    subject = (subject or "").strip().lower()
    if not subject:
        raise AdoptionRefused("An instrument governs a subject; it needs one.")
    if not (text or "").strip():
        raise AdoptionRefused("An instrument with no text governs nothing.")
    if not (adopted_by or "").strip():
        raise AdoptionRefused("An instrument needs whoever adopted it.")

    if level == parliament.LEVEL_CONSTITUTION or level not in LEVELS:
        parliament.escalate(
            conn,
            summary=(f"Attempt to adopt {subject!r} at level {level!r}, which this store "
                     f"may not hold."),
            raised_by=adopted_by)
        raise AdoptionRefused(REFUSAL)
    if level in ("articles", "articles_amendment"):
        raise AdoptionRefused(
            "The Articles are Parliament's own record and are amended by vote, not adopted here.")

    _check_authorization(conn, level, resolution_id)

    standing = effective_item(conn, subject, allow_ambiguous=True)
    if standing is not None and replaces is not None:
        if _rank(level) > _rank(standing["level"]) and replaces == standing["id"]:
            # `_rank` counts downward in authority, so a bigger number is weaker.
            parliament.escalate(
                conn,
                summary=(f"An item at {level!r} claimed to replace {standing['level']!r} "
                         f"authority on {subject!r}."),
                raised_by=adopted_by)
            raise AdoptionRefused(REFUSAL)

    peer = _active_at_level(conn, subject, level)
    if peer is not None and replaces != peer["id"]:
        raise AdoptionRefused(
            f"{subject!r} already has an instrument at {level!r}. Replace it by naming it, "
            f"or this store would hold two equal authorities on one subject.")

    item_id = conn.execute_returning_id(
        "INSERT INTO governed_items (adopted_at, subject, level, text, adopted_by,"
        " resolution_id, replaces) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (now_iso(), subject, level, text.strip(), adopted_by.strip(), resolution_id, replaces))

    if replaces is not None:
        conn.execute(
            "UPDATE governed_items SET superseded_at = ?, superseded_by = ?"
            " WHERE id = ? AND superseded_at IS NULL",
            (now_iso(), item_id, replaces))
    return item_id


def _check_authorization(conn: Database, level: str, resolution_id: int | None) -> None:
    if level in UNGOVERNED_LEVELS:
        if resolution_id is not None:
            raise AdoptionRefused(
                f"{level!r} carries no authority, so a resolution cannot be spent on it. "
                f"Filing it needs no vote.")
        return
    if level not in AUTHORIZED_LEVELS:  # pragma: no cover - LEVELS covers both lists
        raise AdoptionRefused(REFUSAL)
    if resolution_id is None:
        raise AdoptionRefused(
            f"{level!r} governs somebody, so it needs the enacted resolution that authorized it.")
    resolution = parliament.get_resolution(conn, resolution_id)
    if resolution is None or resolution["status"] != parliament.STATUS_ENACTED:
        raise AdoptionRefused(
            "That resolution is not enacted, so it authorizes nothing.")
    if resolution["affects"] != level:
        raise AdoptionRefused(
            f"That resolution was enacted for {resolution['affects']!r} and cannot be spent "
            f"on {level!r}. The authority granted is the authority given.")


def effective(conn: Database, subject: str) -> str:
    """The text that governs this subject.

    Raises rather than guessing when nothing governs it, and raises rather than
    choosing when two equal authorities do."""
    item = effective_item(conn, subject)
    if item is None:
        raise NotGoverned(f"Nothing governs {subject!r}.")
    return item["text"]


def effective_item(conn: Database, subject: str, *, allow_ambiguous: bool = False) -> dict | None:
    """The highest active authority on a subject, whole.

    `allow_ambiguous` exists for `adopt`, which has to look at what is standing
    before it can decide whether the new item is a legitimate replacement. Nothing
    else passes it, and no read path exposes it - a caller that could ask for
    "whatever, just pick one" would have the override this module exists to
    prevent."""
    active = _active(conn, subject)
    if not active:
        return None
    best = min(_rank(item["level"]) for item in active)
    contenders = [item for item in active if _rank(item["level"]) == best]
    if len(contenders) > 1 and not allow_ambiguous:
        raise AmbiguousAuthority(
            f"{subject!r} has {len(contenders)} active items at {contenders[0]['level']!r}. "
            f"Nothing here will choose between them; this needs a resolution.")
    return contenders[0]


def subordinate(conn: Database, subject: str) -> list[dict]:
    """Everything active on the subject that does *not* govern it.

    Reachable, and reachable under a name that says what it is. A procedure under
    a policy is ordinary and useful; a procedure returned as *the rule* is the
    silent override."""
    active = _active(conn, subject)
    if not active:
        return []
    best = min(_rank(item["level"]) for item in active)
    return [item for item in active if _rank(item["level"]) > best]


def history(conn: Database, subject: str) -> list[dict]:
    """Every item ever adopted on the subject, oldest first, superseded included.

    Addendum 46 §18: nothing erases history. A store that dropped superseded rows
    could not answer *"what previous version did it replace"* - one of §17's
    provenance questions, and the one a rollback needs."""
    return conn.fetchall(
        "SELECT * FROM governed_items WHERE subject = ? ORDER BY id", (subject.strip().lower(),))


def subjects(conn: Database) -> list[str]:
    return [row["subject"] for row in conn.fetchall(
        "SELECT DISTINCT subject FROM governed_items WHERE superseded_at IS NULL"
        " ORDER BY subject")]


def conflicts(conn: Database) -> list[dict]:
    """Subjects with more than one active item at their top level.

    A conflict is *reported*, never resolved here. Addendum 46 §5 says conflicts
    must be detected and escalated through governance - which means a vote, not a
    rule of thumb inside a query."""
    found = []
    for subject in subjects(conn):
        active = _active(conn, subject)
        best = min(_rank(item["level"]) for item in active)
        contenders = [item for item in active if _rank(item["level"]) == best]
        if len(contenders) > 1:
            found.append({"subject": subject, "level": contenders[0]["level"],
                          "items": [item["id"] for item in contenders]})
    return found


def _active(conn: Database, subject: str) -> list[dict]:
    return conn.fetchall(
        "SELECT * FROM governed_items WHERE subject = ? AND superseded_at IS NULL ORDER BY id",
        (subject.strip().lower(),))


def _active_at_level(conn: Database, subject: str, level: str) -> dict | None:
    return conn.fetchone(
        "SELECT * FROM governed_items WHERE subject = ? AND level = ? AND superseded_at IS NULL"
        " ORDER BY id LIMIT 1", (subject, level))


def _rank(level: str) -> int:
    """Position in the hierarchy. **Lower is more authoritative**, because
    `parliament.LEVELS` is written most-authoritative first and the index is the
    honest reading of it. Inverting it here to make bigger mean stronger would put
    the precedence in two places, which is how the two stop agreeing."""
    return LEVELS.index(level)
