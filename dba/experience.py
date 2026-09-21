"""The DBA's own experience, persisted so it does not start from zero (§10, §11, §30).

    *"The objective is not merely to fix one schema. The objective is to
    improve the DBA's future design behavior."*

## What is actually learned, and why it is not a summary

Three things, each derived from rows rather than written as a judgement:

**Which archetype fitted.** Every design records the class it matched and
whether that design survived to publication. A pattern that keeps being
rejected is a pattern that does not fit what Krish actually wants.

**Which questions kept coming up.** This is the one with immediate value.
If the last three `handoff_queue` designs all had to stop and ask about
retention, the fourth should ask about retention *in the first message* rather
than discovering it again. `advice_for` reads that straight out of the
episodes, so the improvement is mechanical rather than aspirational.

**What corrections were required.** §30: when Krish, a review or a test finds a
defect in a design, the correction is learning material. Counted rather than
duplicated, for the reason `app/learning/memory.py` gives - the value of "this
keeps happening" is entirely in the count, and a hundred rows saying it once
each is the shape that makes it invisible.

## What this deliberately is not

It is not a model summarising its own work. Every lesson here is computed from
stored episodes by a pure function, so two readers get the same answer and a
lesson can be traced to the episodes that produced it. A DBA that could write
itself a flattering lesson would have learning that means nothing.
"""

from __future__ import annotations

import json
from collections import Counter

from backend.db import Database, now_iso
from dba import ids

# Outcomes of a design attempt.
ASKED = "asked"
DESIGNED = "designed"
STAGED = "staged"
PUBLISHED = "published"
REJECTED = "rejected"
FAILED = "failed"
OUTCOMES = (ASKED, DESIGNED, STAGED, PUBLISHED, REJECTED, FAILED)

# Lesson kinds. Closed, because `meta_report` groups on them.
ARCHETYPE_FIT = "archetype_fit"
RECURRING_QUESTION = "recurring_question"
CORRECTION = "correction"
REUSE = "reuse"
TEST_FAILURE = "test_failure"
KINDS = (ARCHETYPE_FIT, RECURRING_QUESTION, CORRECTION, REUSE, TEST_FAILURE)

# Below this many episodes of a kind, a cross-episode claim is one anecdote.
MIN_EPISODES_FOR_TREND = 3


def record_design(conn: Database, *, requirement, design_result,
                  outcome: str, detail: str = "") -> str:
    """One design attempt, whatever came of it."""
    if outcome not in OUTCOMES:
        raise ValueError(f"design outcome={outcome!r} is not one of {OUTCOMES}")
    episode_id = ids.new_id("design")
    designed = design_result.capability
    conn.execute(
        "INSERT INTO design_episodes (episode_id, capability_name, "
        "capability_version, requirement, questions_json, decisions_json, "
        "reused, outcome, detail, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (episode_id,
         designed.name if designed else None,
         designed.version if designed else None,
         requirement.task,
         json.dumps([question.to_dict() for question in design_result.questions],
                    ensure_ascii=False),
         json.dumps({"archetype": design_result.match.to_dict(),
                     "reasoning": design_result.reasoning},
                    ensure_ascii=False, default=str),
         (design_result.reuse or {}).get("capability"),
         outcome, detail, now_iso()))
    _learn_from(conn, design_result, outcome)
    return episode_id


def _learn_from(conn: Database, design_result, outcome: str) -> None:
    """Derive what this attempt teaches. Called once, by `record_design`."""
    archetype = (design_result.match.archetype.name
                 if design_result.match.archetype else None)
    name = design_result.capability.name if design_result.capability else None

    if archetype:
        record_lesson(
            conn, kind=ARCHETYPE_FIT, pattern=f"{archetype}:{outcome}",
            lesson=(f"a {archetype} design reached {outcome}"),
            capability=name)

    described = archetype or "a requirement with no clear archetype"
    for question in design_result.questions:
        needed = question.reason.replace("_", " ")
        record_lesson(
            conn, kind=RECURRING_QUESTION,
            pattern=f"{archetype or 'unmatched'}:{question.reason}",
            lesson=(f"designing {described} needed {needed} settled before it "
                    f"could be built"),
            capability=name)

    if design_result.reuse:
        record_lesson(
            conn, kind=REUSE,
            pattern=f"{archetype or 'unmatched'}:existing",
            lesson=(f"a published capability already covered this: "
                    f"{design_result.reuse['capability']}"),
            capability=name)


def record_publication(conn: Database, *, capability_name: str, version: int,
                       requirement: str, accepted_by: str) -> str:
    """An episode for a capability reaching service.

    Separate from `record_design` because publication happens on a different
    call, by a different hand, possibly days later - and `meta_report` counts
    outcomes, so a state nothing ever writes is a claim that can never be
    true."""
    episode_id = ids.new_id("design")
    conn.execute(
        "INSERT INTO design_episodes (episode_id, capability_name, "
        "capability_version, requirement, questions_json, decisions_json, "
        "reused, outcome, detail, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (episode_id, capability_name, version, requirement, "[]",
         json.dumps({"accepted_by": accepted_by}, ensure_ascii=False), None,
         PUBLISHED, f"accepted by {accepted_by}", now_iso()))
    return episode_id


def record_correction(conn: Database, *, capability_name: str, what: str,
                      found_by: str, why: str = "") -> int:
    """§30. A defect somebody found in a design, kept as learning material."""
    return record_lesson(
        conn, kind=CORRECTION, pattern=f"{capability_name}:{what}",
        lesson=(f"{found_by} found: {what}" + (f". {why}" if why else "")),
        capability=capability_name)


def record_test_failure(conn: Database, *, capability_name: str,
                        case: str, detail: str) -> int:
    return record_lesson(
        conn, kind=TEST_FAILURE, pattern=case,
        lesson=f"the generated test {case!r} failed: {detail}"[:400],
        capability=capability_name)


def record_lesson(conn: Database, *, kind: str, pattern: str, lesson: str,
                  capability: str | None = None) -> int:
    """A lesson, or one more sighting of one already recorded."""
    if kind not in KINDS:
        raise ValueError(f"lesson kind={kind!r} is not one of {KINDS}")
    existing = conn.fetchone(
        "SELECT lesson_id, capabilities_json, times_seen FROM design_lessons "
        "WHERE kind = ? AND pattern = ?", (kind, pattern))
    if existing is not None:
        seen = json.loads(existing["capabilities_json"] or "[]")
        if capability and capability not in seen:
            seen.append(capability)
        conn.execute(
            "UPDATE design_lessons SET times_seen = times_seen + 1, "
            "capabilities_json = ?, at = ?, lesson = ? WHERE lesson_id = ?",
            (json.dumps(seen), now_iso(), lesson, existing["lesson_id"]))
        return int(existing["lesson_id"])
    return conn.execute_returning_id(
        "INSERT INTO design_lessons (kind, pattern, lesson, capabilities_json, at) "
        "VALUES (?, ?, ?, ?, ?)",
        (kind, pattern, lesson,
         json.dumps([capability] if capability else []), now_iso()))


# --- reading it back ----------------------------------------------------------


def lessons(conn: Database, kind: str | None = None) -> list[dict]:
    query = "SELECT * FROM design_lessons"
    params: list = []
    if kind is not None:
        query += " WHERE kind = ?"
        params.append(kind)
    rows = conn.fetchall(query + " ORDER BY times_seen DESC, at DESC", params)
    out = []
    for row in rows:
        item = dict(row)
        item["capabilities"] = json.loads(item.pop("capabilities_json") or "[]")
        out.append(item)
    return out


def episodes(conn: Database, limit: int = 50) -> list[dict]:
    rows = conn.fetchall(
        "SELECT * FROM design_episodes ORDER BY at DESC LIMIT ?", (limit,))
    out = []
    for row in rows:
        item = dict(row)
        for field_name in ("questions_json", "decisions_json"):
            try:
                item[field_name[:-5]] = json.loads(item.pop(field_name) or "[]")
            except (TypeError, ValueError):
                item.pop(field_name, None)
        out.append(item)
    return out


def advice_for(conn: Database, archetype_name: str | None) -> list[str]:
    """What past designs of this class say to settle up front (§10).

    The useful half of this module. A question that had to be asked three times
    for the same archetype is a question the fourth design should put in its
    first message, and that is a mechanical improvement rather than an
    aspiration."""
    if not archetype_name:
        return []
    said: list[str] = []
    for lesson in lessons(conn, RECURRING_QUESTION):
        if not lesson["pattern"].startswith(f"{archetype_name}:"):
            continue
        if lesson["times_seen"] >= MIN_EPISODES_FOR_TREND:
            reason = lesson["pattern"].split(":", 1)[1]
            said.append(
                f"ask about {reason.replace('_', ' ')} up front: the last "
                f"{lesson['times_seen']} {archetype_name} designs all had to "
                f"stop for it")
    for lesson in lessons(conn, CORRECTION):
        if archetype_name in lesson["lesson"] and lesson["times_seen"] >= 2:
            said.append(f"previously corrected here: {lesson['lesson']}")
    return said


def meta_report(conn: Database) -> dict:
    """What the DBA has learned about its own design work."""
    all_episodes = episodes(conn, limit=1000)
    if len(all_episodes) < MIN_EPISODES_FOR_TREND:
        return {
            "episodes": len(all_episodes),
            "claims": [],
            "outcomes": dict(Counter(episode["outcome"]
                                     for episode in all_episodes)),
            "lesson_counts": {kind: len(lessons(conn, kind)) for kind in KINDS},
            "note": (f"{len(all_episodes)} design(s) recorded. A claim about "
                     f"how this agent designs needs at least "
                     f"{MIN_EPISODES_FOR_TREND}; below that it is one anecdote "
                     f"with a percentage sign on it."),
        }

    outcomes = Counter(episode["outcome"] for episode in all_episodes)
    claims: list[str] = []

    published = outcomes.get(PUBLISHED, 0)
    if published:
        claims.append(
            f"{published} of {len(all_episodes)} design(s) reached publication")

    asked = outcomes.get(ASKED, 0)
    if asked:
        claims.append(
            f"{asked} design(s) stopped to ask rather than guessing")

    recurring = [lesson for lesson in lessons(conn, RECURRING_QUESTION)
                 if lesson["times_seen"] >= MIN_EPISODES_FOR_TREND]
    if recurring:
        worst = max(recurring, key=lambda item: item["times_seen"])
        claims.append(
            f"the question that keeps recurring is {worst['pattern']} "
            f"({worst['times_seen']} times) - worth asking up front")

    corrections = lessons(conn, CORRECTION)
    if corrections:
        claims.append(
            f"{len(corrections)} correction(s) recorded from review or testing")

    return {
        "episodes": len(all_episodes),
        "outcomes": dict(outcomes),
        "claims": claims,
        "lesson_counts": {kind: len(lessons(conn, kind)) for kind in KINDS},
    }
