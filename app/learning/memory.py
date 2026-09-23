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

## A lesson is a bet, and this module is where it is placed and settled

Krish, 2026-09-23, on whether *"the March invoice from Acme always arrives late"*
is a lesson or a context: *"it's a fact that Claude may choose to remember and
this cost may or may not be rewarded by a cost saving use in the future - that's
how Jarvis learns how to guess correctly what to remember and what to discard -
all deadweight unreferenced information should be eventually garbage collected."*

Three functions here are the two halves of that:

- `learn_from_episode` **places** the bet, and now asks
  `retention.worth_recording` first. A kind of lesson that has been recorded
  enough times and never once helped stops being recorded, which is the
  "learns to guess correctly" part.
- `advice_for` **settles** it, and is the only reason any of the numbers move:
  every lesson it looks at is marked offered, and every lesson it hands over is
  marked referenced. Without this the store would record acquisition for ever and
  never use, and every fact would look like deadweight.
- `collect_garbage` **collects**, by asking `retention.verdict` about each lesson
  and doing what it says. It holds the clock, because `retention` holds none.

## It reports what it cannot yet know

`meta_report()` refuses to generalise from one episode, and says so rather than
returning a confident claim from a sample of one. `MIN_EPISODES_FOR_TREND` is
that floor. A meta-learning module whose first run announced a law of learning
would be the thing this project keeps refusing everywhere else: a number wearing
authority nothing earned.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.learning import practice, retention, store

logger = logging.getLogger(__name__)

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


def _days_between(earlier: str | None, later: datetime) -> float:
    """Whole-and-fractional days, or 0.0 for a stamp nothing can parse.

    0.0 rather than a guess, and rather than raising: an unparseable timestamp
    makes a lesson look brand new, which is the direction that keeps it. A clock
    problem must not turn into a deletion."""
    if not earlier:
        return 0.0
    try:
        when = datetime.fromisoformat(earlier)
    except ValueError:
        return 0.0
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (later - when).total_seconds() / 86400.0)


def as_bet(row: dict, *, now: datetime) -> retention.Bet:
    """One stored lesson, as the numbers that decide its fate.

    The whole conversion is here and nowhere else, so that there is one place
    that knows how a database row becomes a decision - and so `retention` never
    learns what a row looks like."""
    referenced = int(row.get("times_referenced") or 0)
    return retention.Bet(
        kind=row.get("kind") or "",
        cost=float(row.get("cost") or 0.0),
        age_days=_days_between(row.get("at"), now),
        times_referenced=referenced,
        times_offered=int(row.get("times_offered") or 0),
        # None, not zero: a lesson never referenced has been silent since it was
        # acquired, and zero would read as "referenced today".
        days_since_reference=(_days_between(row.get("last_referenced_at"), now)
                              if referenced and row.get("last_referenced_at")
                              else None),
        times_paid_off=int(row.get("times_paid_off") or 0),
        expected_interval_days=row.get("expected_interval_days"))


def collect_garbage(*, now: datetime | None = None, dry_run: bool = False) -> dict:
    """Ask `retention` about every lesson, and do what it says.

    The clock lives here and the judgement lives in `retention`, which is the
    repository's split: every rule about elapsed time is testable at a chosen
    date because nothing in the policy reads `now()`.

    `dry_run` reports the verdicts without acting on them. It exists because the
    first honest thing to do with a collector is watch it for a while and see
    what it would have thrown away."""
    when = now or datetime.now(timezone.utc)
    report: dict = {"at": when.isoformat(timespec="seconds"), "kept": 0,
                    "demoted": [], "discarded": [], "restored": [],
                    "dry_run": dry_run}

    for row in store.lessons(include_demoted=True):
        decided = retention.verdict(as_bet(row, now=when))
        entry = {"id": row["id"], "kind": row["kind"], "pattern": row["pattern"],
                 "because": decided.because}
        if decided.outcome == retention.DISCARD:
            report["discarded"].append(entry)
            if not dry_run:
                store.discard_lesson(row["id"])
        elif decided.outcome == retention.PROBATION:
            if not row.get("demoted_at"):
                report["demoted"].append(entry)
                if not dry_run:
                    store.demote_lesson(row["id"])
        else:
            report["kept"] += 1
            # A lesson whose verdict came back to KEEP is offered again. Without
            # this, probation is a one-way door and a lesson demoted during a
            # quiet spell never recovers from it.
            if row.get("demoted_at"):
                report["restored"].append(entry)
                if not dry_run:
                    store.restore_lesson(row["id"])
    return report


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
                        # Cost is a proxy throughout: the attempts this lesson
                        # was derived from, not model calls measured. Stated as a
                        # count of real rows rather than an estimate, so it is
                        # wrong in a way that can be re-derived.
                        "cost": float(len(seen)),
                        "lesson": (f"hit {len(seen)} times while learning {slug}. "
                                   f"{suggestion}")})

    # 2. Which sources actually carried the skill.
    for item in knowledge:
        if item["confirmed_by_test"]:
            written.append({
                "kind": SOURCE_VALUE, "pattern": item["source_kind"],
                "cost": 1.0,
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
                "cost": float(len(attempts)),
                "lesson": (f"{ratio:.1f} attempts per case learned on {slug}, above "
                           f"the {INEFFICIENT_ATTEMPTS_PER_CASE:g} this system "
                           f"treats as inefficient. The diagnosis classes above "
                           f"say where they went")})
        else:
            written.append({
                "kind": TECHNIQUE, "pattern": "attempts_per_case",
                "cost": float(len(attempts)),
                "lesson": f"{ratio:.1f} attempts per case learned on {slug}"})

    # 4. Which diagnosis rung did the work. §19's "record why external assistance
    #    was required" - and here, usefully, it never was.
    rungs: dict[str, int] = {}
    for attempt in attempts:
        rung = (attempt.get("diagnosis") or {}).get("resolution")
        if rung:
            rungs[rung] = rungs.get(rung, 0) + 1
    if rungs:
        # Cheapest ON THE LADDER, not first inserted. `list(rungs).index` is
        # insertion order, so an episode whose first failure escalated would have
        # reported `external_model` as its cheapest rung - the opposite of what
        # this lesson is for. `practice.RESOLUTIONS` is the ordering.
        cheapest = min(rungs, key=lambda name: (
            practice.RESOLUTIONS.index(name)
            if name in practice.RESOLUTIONS else len(practice.RESOLUTIONS)))
        written.append({
            "kind": TECHNIQUE, "pattern": "diagnosis_resolution",
            "cost": float(sum(rungs.values())),
            "lesson": (f"on {slug}, failures were resolved at: "
                       + ", ".join(f"{name} x{count}" for name, count in rungs.items())
                       + f". Cheapest rung used: {cheapest}")})

    # Placing the bet. A kind that has been recorded enough times and never once
    # helped is not recorded again - except for `retention`'s periodic reprieve,
    # so that a kind which has become useful can be found out. `skipped` is
    # returned rather than dropped, because "we deliberately did not write this
    # down" is exactly the kind of thing that looks like a bug six months later.
    kept, skipped = [], []
    for lesson in written:
        allowed, why = retention.worth_recording(
            retention.KindHistory(**store.kind_history(lesson["kind"])))
        if not allowed:
            skipped.append({**lesson, "not_recorded_because": why})
            continue
        store.record_lesson(kind=lesson["kind"], pattern=lesson["pattern"],
                            lesson=lesson["lesson"], episode_slug=slug,
                            cost=float(lesson.get("cost") or 1.0))
        kept.append(lesson)
    if skipped:
        # Not silent. One line naming what was withheld and why, so the decision
        # is visible in the log rather than only in this return value.
        for lesson in skipped:
            logger.info("not recording a %s lesson (%s): %s", lesson["kind"],
                        lesson["pattern"], lesson["not_recorded_because"])
    return kept


def advice_for(objective, *, episode_slug: str | None = None) -> list[str]:
    """What past episodes suggest before this one starts (§25's purpose).

    Read at planning time, so a learning plan can say "last time this class of
    failure cost four attempts; check the field names first". Empty on the first
    episode, which is the honest answer rather than generic advice.

    **This function is what settles every bet in the store.** Each lesson it
    looks at is marked offered and each lesson it hands over is marked
    referenced, and those two numbers are the entire difference between a dormant
    seasonal fact and deadweight. A copy of this loop that read lessons without
    marking them would make every fact it used look unused, so the marking is not
    optional bookkeeping - it is the measurement.

    `episode_slug` is what a later `store.credit_episode(slug)` needs to find
    these references again and pay them off. Without it the advice is still
    given and still counted as used; it simply can never be counted as having
    helped, which is the honest consequence of not saying who it was for."""
    said: list[str] = []
    considered: list[int] = []
    used: list[int] = []

    def offer(lesson: dict, line: str | None) -> None:
        considered.append(lesson["id"])
        if line is not None:
            said.append(line)
            used.append(lesson["id"])

    for lesson in store.lessons(FAILURE_PATTERN):
        offer(lesson, (f"{lesson['pattern']} has come up {lesson['times_seen']} "
                       f"times before: {lesson['lesson']}")
              if lesson["times_seen"] >= MIN_EPISODES_FOR_TREND else None)
    sources = store.lessons(SOURCE_VALUE)
    for position, lesson in enumerate(sources):
        # Everything of this kind was looked at; only the first three were used.
        # Counting only the three would make a lesson that never quite makes the
        # cut look like one nothing ever asked about, and those call for opposite
        # actions.
        offer(lesson, (f"{lesson['pattern']} has produced {lesson['times_seen']} "
                       f"confirmed finding(s); prefer it") if position < 3 else None)
    for lesson in store.lessons(COST):
        offer(lesson, f"cost warning: {lesson['lesson']}")

    store.note_offered(considered)
    for lesson_id in used:
        store.note_referenced(lesson_id, episode_slug=episode_slug)
    return said


def meta_report() -> dict:
    """§26's second-order analysis, or an honest refusal to make one yet."""
    episodes = store.list_episodes()
    # Reporting, not advising, so demoted lessons are included: a demoted lesson
    # is still part of the record of what was learned, and a report that hid it
    # would disagree with the database.
    all_lessons = store.lessons(include_demoted=True)

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

    # What collection has thrown away, which is the claim no surviving row can
    # make. A kind that cost something and returned nothing is the finding, and
    # the rows that would have shown it are exactly the rows that are gone.
    kinds = store.kind_histories()
    wasted = [item for item in kinds
              if item["discarded_unreferenced"] and not item["paid_off"]]
    if wasted:
        claims.append(
            "Kinds of lesson recorded and never once used: "
            + "; ".join(f"`{item['kind']}` ({item['discarded_unreferenced']} "
                        f"collected, {item['cost_sunk']:g} spent)"
                        for item in wasted)
            + ". Recording these was a bad bet, and `retention.worth_recording` "
              "is what stops it repeating.")

    return {
        "episodes": len(episodes),
        "claims": claims,
        "lessons": all_lessons,
        "kinds": kinds,
        "note": ("Computed from the learning store. Every claim here is "
                 "re-derivable from the rows behind it - except the one about "
                 "collected lessons, whose rows are deliberately gone and whose "
                 "evidence is the per-kind tally they left behind."),
    }
