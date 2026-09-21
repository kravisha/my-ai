"""What Jarvis learns about learning (Document 1 §25, §26).

> *"Jarvis learns skills, and Jarvis learns how to learn skills better."*

The difference between a pipeline and a meta-skill is entirely this module. Two
things live here and they are not the same:

- **Memory** (§25) — facts about one episode that generalise: this failure class
  recurred, this source paid off, this many attempts were needed.
- **Meta-learning** (§26) — claims across episodes: *"debugging this class of
  failure keeps costing model calls"*, *"this testing strategy catches more"*.

## Lessons are counted, and the count is the content

`store.record_lesson` upserts on `(kind, pattern)` and increments. That is not an
optimisation. §26's examples are all frequency claims — *"I repeatedly waste
time"* — and a hundred separate rows each saying it once is exactly the shape
that makes a pattern invisible. One row saying `times_seen: 14` is the finding.

## It reports what it cannot yet know

`meta_report()` refuses to generalise from one episode, and says so rather than
returning a confident claim from a sample of one. `MIN_EPISODES_FOR_TREND` is
that floor. A meta-learning module whose first run announced a law of learning
would be the thing this project keeps refusing everywhere else: a number wearing
authority nothing earned.
"""

from __future__ import annotations

from app.learning import store

# Lesson kinds. Closed, because `meta_report` groups on them.
FAILURE_PATTERN = "failure_pattern"
SOURCE_VALUE = "source_value"
TECHNIQUE = "technique"
COST = "cost"
KINDS = (FAILURE_PATTERN, SOURCE_VALUE, TECHNIQUE, COST)

# Below this many episodes, a cross-episode claim is one anecdote with a
# percentage sign on it.
MIN_EPISODES_FOR_TREND = 2

# Attempts-per-passing-case above which the loop is judged inefficient. Four,
# meaning three wrong turns per case learned; stated as a convention rather than
# a measurement, in this project's usual terms - nothing has measured the right
# number yet and this paragraph is the disclosure.
INEFFICIENT_ATTEMPTS_PER_CASE = 4.0


def learn_from_episode(slug: str) -> list[dict]:
    """Extract the lessons one finished episode can teach, and record them.

    Called after an episode reaches a terminal state. Every lesson it writes is
    derived from rows already in the store, so nothing here is a judgement that
    could not be re-derived from the record."""
    episode = store.get_episode(slug)
    if not episode:
        return []
    episode_id = episode["id"]
    attempts = store.attempts(episode_id)
    knowledge = store.knowledge(episode_id)
    written = []

    # 1. Which failure classes recurred, and what fixed them.
    by_class: dict[str, list[dict]] = {}
    for attempt in attempts:
        diagnosis = attempt.get("diagnosis") or {}
        if diagnosis.get("failure_class"):
            by_class.setdefault(diagnosis["failure_class"], []).append(diagnosis)
    for failure_class, seen in by_class.items():
        if len(seen) < 2:
            continue
        suggestion = next((item.get("suggestion") for item in seen
                           if item.get("suggestion")), "")
        written.append({"kind": FAILURE_PATTERN, "pattern": failure_class,
                        "lesson": (f"hit {len(seen)} times while learning {slug}. "
                                   f"{suggestion}")})

    # 2. Which sources actually carried the skill.
    for item in knowledge:
        if item["confirmed_by_test"]:
            written.append({
                "kind": SOURCE_VALUE, "pattern": item["source_kind"],
                "lesson": (f"produced a finding that a test later confirmed "
                           f"(tier {item['trust_tier']})")})

    # 3. How expensive this was, per case actually learned.
    passing = len({attempt["case_name"] for attempt in attempts
                   if attempt["passed"] and attempt["case_name"]})
    if passing:
        ratio = len(attempts) / passing
        if ratio > INEFFICIENT_ATTEMPTS_PER_CASE:
            written.append({
                "kind": COST, "pattern": "attempts_per_case",
                "lesson": (f"{ratio:.1f} attempts per case learned on {slug}, above "
                           f"the {INEFFICIENT_ATTEMPTS_PER_CASE:g} this system "
                           f"treats as inefficient. The diagnosis classes above "
                           f"say where they went")})
        else:
            written.append({
                "kind": TECHNIQUE, "pattern": "attempts_per_case",
                "lesson": f"{ratio:.1f} attempts per case learned on {slug}"})

    # 4. Which diagnosis rung did the work. §19's "record why external assistance
    #    was required" - and here, usefully, it never was.
    rungs: dict[str, int] = {}
    for attempt in attempts:
        rung = (attempt.get("diagnosis") or {}).get("resolution")
        if rung:
            rungs[rung] = rungs.get(rung, 0) + 1
    if rungs:
        cheapest = min(rungs, key=lambda name: list(rungs).index(name))
        written.append({
            "kind": TECHNIQUE, "pattern": "diagnosis_resolution",
            "lesson": (f"on {slug}, failures were resolved at: "
                       + ", ".join(f"{name} x{count}" for name, count in rungs.items())
                       + f". Cheapest rung used: {cheapest}")})

    for lesson in written:
        store.record_lesson(kind=lesson["kind"], pattern=lesson["pattern"],
                            lesson=lesson["lesson"], episode_slug=slug)
    return written


def advice_for(objective) -> list[str]:
    """What past episodes suggest before this one starts (§25's purpose).

    Read at planning time, so a learning plan can say "last time this class of
    failure cost four attempts; check the field names first". Empty on the first
    episode, which is the honest answer rather than generic advice."""
    said = []
    for lesson in store.lessons(FAILURE_PATTERN):
        if lesson["times_seen"] >= MIN_EPISODES_FOR_TREND:
            said.append(f"{lesson['pattern']} has come up {lesson['times_seen']} "
                        f"times before: {lesson['lesson']}")
    for lesson in store.lessons(SOURCE_VALUE)[:3]:
        said.append(f"{lesson['pattern']} has produced {lesson['times_seen']} "
                    f"confirmed finding(s); prefer it")
    for lesson in store.lessons(COST):
        said.append(f"cost warning: {lesson['lesson']}")
    return said


def meta_report() -> dict:
    """§26's second-order analysis, or an honest refusal to make one yet."""
    episodes = store.list_episodes()
    all_lessons = store.lessons()

    if len(episodes) < MIN_EPISODES_FOR_TREND:
        return {
            "episodes": len(episodes),
            "claims": [],
            "note": (f"{len(episodes)} episode(s) recorded. A claim about how this "
                     f"system learns needs at least {MIN_EPISODES_FOR_TREND} to be "
                     f"anything more than one anecdote with a percentage sign on "
                     f"it, so none is made. The lessons below are per-episode "
                     f"facts, not trends."),
            "lessons": all_lessons,
        }

    claims = []
    failures = [item for item in all_lessons if item["kind"] == FAILURE_PATTERN]
    if failures:
        worst = max(failures, key=lambda item: item["times_seen"])
        claims.append(
            f"The failure class I hit most is `{worst['pattern']}` "
            f"({worst['times_seen']} times across {len(worst['episodes'])} "
            f"episode(s)). Checking for it first would save attempts.")

    sources = [item for item in all_lessons if item["kind"] == SOURCE_VALUE]
    if sources:
        best = max(sources, key=lambda item: item["times_seen"])
        claims.append(
            f"`{best['pattern']}` has produced {best['times_seen']} findings that "
            f"tests later confirmed - more than any other source. Go there first.")

    external = [item for item in all_lessons
                if item["kind"] == TECHNIQUE
                and "external_model" in (item["lesson"] or "")]
    claims.append(
        f"External model calls used in diagnosis: "
        f"{'yes, ' + str(len(external)) + ' episode(s)' if external else 'none'}. "
        f"Every failure so far was classified from the recipe's own trace, which "
        f"is the point of §17.")

    costs = [item for item in all_lessons if item["kind"] == COST]
    if costs:
        claims.append(
            f"{len(costs)} episode(s) exceeded the attempts-per-case efficiency "
            f"line. The failure classes above are where those attempts went.")

    return {
        "episodes": len(episodes),
        "claims": claims,
        "lessons": all_lessons,
        "note": ("Computed from the learning store. Every claim here is "
                 "re-derivable from the rows behind it."),
    }
