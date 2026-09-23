"""Mutations that the memory-economy wiring must notice.

Krish, 2026-09-23: *"this cost may or may not be rewarded by a cost saving use in
the future - that's how Jarvis learns how to guess correctly what to remember and
what to discard."*

`retention_probes.py` covers the judgement. This covers the machinery around it,
which fails differently: the judgement fails loudly and wrongly, the machinery
fails by *silently not happening*. Three call sites carry the whole scheme -
`advice_for` marks lessons used, `engine.accept` credits payoffs,
`upkeep.run_once` collects - and deleting any one of them leaves a system that
still works, still reports, and quietly deletes the lessons that were helping.
So most of the probes here delete a call site rather than change a number.

Run it directly:

    python tests/probes/memory_economy_probes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

TESTS = Path(__file__).resolve().parents[1]

STORE = "app/learning/store.py"
MEMORY = "app/learning/memory.py"
ENGINE = "app/learning/engine.py"
UPKEEP = "gateway/upkeep.py"

SUITES = {STORE: TESTS / "test_memory_economy.py",
          MEMORY: TESTS / "test_memory_economy.py",
          ENGINE: TESTS / "test_memory_economy.py",
          UPKEEP: TESTS / "test_jarvis_upkeep.py"}

PROBES: list[harness.Probe] = [
    # --- the migration --------------------------------------------------------
    (
        STORE,
        "the added columns are never added to an existing database",
        "        if column not in have:",
        "        if False:",
        ("test_recording_a_lesson_counts_it_against_its_kind",),
    ),
    # --- placing the bet ------------------------------------------------------
    (
        STORE,
        "seeing a lesson again counts as a second bet on its kind",
        "            _bump_kind(db, kind, cost_sunk=float(cost))\n"
        "            return int(existing[\"id\"])",
        "            _bump_kind(db, kind, recorded=1, cost_sunk=float(cost))\n"
        "            return int(existing[\"id\"])",
        ("test_seeing_the_same_lesson_again_is_not_a_second_bet",),
    ),
    (
        STORE,
        "the cost of re-learning something is overwritten, not accumulated",
        "cost = cost + ?, ",
        "cost = ?, ",
        ("test_seeing_the_same_lesson_again_is_not_a_second_bet",),
    ),
    (
        STORE,
        "a new lesson is not counted against its kind at all",
        "        _bump_kind(db, kind, recorded=1, cost_sunk=float(cost))",
        "        _bump_kind(db, kind)",
        ("test_recording_a_lesson_counts_it_against_its_kind",
         "test_a_kind_that_never_pays_off_stops_being_recorded_by_the_producer"),
    ),
    (
        STORE,
        "a kind nothing has recorded reports nothing instead of zeroes",
        '    if row is None:\n        return {"kind": kind, "recorded": 0,',
        '    if False:\n        return {"kind": kind, "recorded": 0,',
        ("test_a_kind_nothing_has_recorded_reports_zeroes_not_nothing",),
    ),
    # --- settling it ----------------------------------------------------------
    (
        STORE,
        "being a candidate is not recorded",
        "        db.execute(f\"UPDATE lessons SET times_offered = times_offered + 1 \"",
        "        db.execute(f\"UPDATE lessons SET times_offered = times_offered + 0 \"",
        ("test_a_lesson_looked_at_and_not_used_is_offered_not_referenced",
         "test_giving_advice_is_what_marks_a_lesson_used"),
    ),
    (
        STORE,
        "being handed over is not recorded",
        "        db.execute(\"UPDATE lessons SET times_referenced = times_referenced + 1, \"",
        "        db.execute(\"UPDATE lessons SET times_referenced = times_referenced + 0, \"",
        ("test_giving_advice_is_what_marks_a_lesson_used",),
    ),
    (
        STORE,
        "a reference leaves no trail, so it can never be credited",
        '        db.execute("INSERT INTO lesson_references (lesson_id, episode_slug, at) "',
        '        db.execute("SELECT ?, ?, ? -- ',
        ("test_giving_advice_is_what_marks_a_lesson_used",
         "test_crediting_an_episode_pays_off_the_lessons_it_was_given"),
    ),
    (
        STORE,
        "a kind's reference count counts uses instead of lessons",
        '        first = int(row["times_referenced"] or 0) == 0\n'
        '        _bump_kind(db, row["kind"], **({"referenced": 1} if first else {}))',
        '        _bump_kind(db, row["kind"], referenced=1)',
        ("test_a_kinds_payoff_count_is_lessons_not_uses",),
    ),
    (
        STORE,
        "crediting an episode twice pays twice",
        '            "WHERE episode_slug = ? AND credited = 0", (episode_slug,)).fetchall()',
        '            "WHERE episode_slug = ?", (episode_slug,)).fetchall()',
        ("test_crediting_twice_does_not_pay_twice",),
    ),
    (
        STORE,
        "a payoff is not recorded on the lesson",
        '            db.execute("UPDATE lessons SET times_paid_off = times_paid_off + 1 "',
        '            db.execute("UPDATE lessons SET times_paid_off = times_paid_off + 0 "',
        ("test_crediting_an_episode_pays_off_the_lessons_it_was_given",),
    ),
    (
        STORE,
        "a kind's payoff count counts uses instead of lessons",
        '            first = int(lesson["times_paid_off"] or 0) == 0\n'
        '            _bump_kind(db, lesson["kind"], **({"paid_off": 1} if first else {}))',
        '            _bump_kind(db, lesson["kind"], paid_off=1)',
        ("test_a_kinds_payoff_count_is_lessons_not_uses",),
    ),
    # --- collecting -----------------------------------------------------------
    (
        STORE,
        "a collection leaves nothing behind, so the finding dies with the rows",
        '        _bump_kind(db, gone["kind"],\n'
        '                   **({"discarded_unreferenced": 1} if never_used else {}))',
        '        _bump_kind(db, gone["kind"])',
        ("test_what_a_collection_leaves_behind_is_the_lesson_about_the_kind",),
    ),
    (
        STORE,
        "a collected lesson leaves its references behind",
        '        db.execute("DELETE FROM lesson_references WHERE lesson_id = ?", (lesson_id,))',
        '        pass',
        ("test_a_collected_lesson_takes_its_references_with_it",),
    ),
    (
        STORE,
        "demoted lessons are offered anyway, so probation does nothing",
        '    if not include_demoted:\n        where.append("demoted_at IS NULL")',
        "    if False:\n        pass",
        ("test_a_lesson_on_probation_stops_being_offered",),
    ),
    (
        STORE,
        "there is no way back off probation",
        '        db.execute("UPDATE lessons SET demoted_at = NULL WHERE id = ?",',
        '        db.execute("SELECT ? -- ",',
        ("test_a_demoted_lesson_is_restored_when_its_verdict_comes_back_to_keep",),
    ),
    # --- memory: the measurement ---------------------------------------------
    (
        MEMORY,
        "advice is given without marking anything as a candidate",
        "    store.note_offered(considered)",
        "    store.note_offered([])",
        ("test_a_lesson_looked_at_and_not_used_is_offered_not_referenced",
         "test_a_failure_pattern_below_the_trend_floor_is_offered_and_not_used"),
    ),
    (
        MEMORY,
        "advice is given without marking anything as used",
        "    for lesson_id in used:\n        store.note_referenced(lesson_id, episode_slug=episode_slug)",
        "    for lesson_id in []:\n        store.note_referenced(lesson_id, episode_slug=episode_slug)",
        ("test_giving_advice_is_what_marks_a_lesson_used",),
    ),
    (
        MEMORY,
        "only the lessons actually used are counted as candidates",
        "        considered.append(lesson[\"id\"])\n        if line is not None:",
        "        if line is not None:\n            considered.append(lesson[\"id\"])\n        if line is not None:",
        ("test_a_lesson_looked_at_and_not_used_is_offered_not_referenced",
         "test_a_failure_pattern_below_the_trend_floor_is_offered_and_not_used"),
    ),
    (
        MEMORY,
        "the producer records a kind it was told not to",
        "        if not allowed:\n            skipped.append(",
        "        if False:\n            skipped.append(",
        ("test_the_producer_honours_the_refusal_to_record_a_worthless_kind",),
    ),
    (
        MEMORY,
        "a withheld lesson is dropped silently",
        '            logger.info("not recording a %s lesson (%s): %s", lesson["kind"],',
        '            _ = ("not recording a %s lesson (%s): %s", lesson["kind"],',
        ("test_a_withheld_lesson_is_logged_rather_than_silently_dropped",),
    ),
    (
        MEMORY,
        "an unparseable timestamp makes a lesson look ancient instead of new",
        "    except ValueError:\n        return 0.0",
        "    except ValueError:\n        return 99999.0",
        ("test_an_unparseable_timestamp_keeps_a_lesson_rather_than_collecting_it",),
    ),
    (
        MEMORY,
        "a lesson never referenced looks as though it was referenced today",
        "        days_since_reference=(_days_between(row.get(\"last_referenced_at\"), now)\n"
        "                              if referenced and row.get(\"last_referenced_at\")\n"
        "                              else None),",
        "        days_since_reference=_days_between(row.get(\"last_referenced_at\"), now),",
        ("test_a_lesson_never_referenced_reports_no_reference_rather_than_a_recent_one",
         "test_deadweight_is_collected_by_the_sweep"),
    ),
    (
        MEMORY,
        "the collector cannot see demoted lessons, so probation is permanent",
        "    for row in store.lessons(include_demoted=True):",
        "    for row in store.lessons():",
        ("test_a_demoted_lesson_is_restored_when_its_verdict_comes_back_to_keep",),
    ),
    (
        MEMORY,
        "a dry run deletes anyway",
        "            if not dry_run:\n                store.discard_lesson(row[\"id\"])",
        "            if True:\n                store.discard_lesson(row[\"id\"])",
        ("test_a_dry_run_reports_and_deletes_nothing",),
    ),
    (
        MEMORY,
        "the collector demotes instead of collecting",
        "        if decided.outcome == retention.DISCARD:",
        "        if False:",
        ("test_deadweight_is_collected_by_the_sweep",
         "test_what_a_collection_leaves_behind_is_the_lesson_about_the_kind"),
    ),
    (
        MEMORY,
        "a demoted lesson is never offered again even when it recovers",
        "            if row.get(\"demoted_at\"):\n                report[\"restored\"].append(entry)",
        "            if False:\n                report[\"restored\"].append(entry)",
        ("test_a_demoted_lesson_is_restored_when_its_verdict_comes_back_to_keep",),
    ),
    (
        MEMORY,
        "a collection is reported without saying why",
        '        entry = {"id": row["id"], "kind": row["kind"], "pattern": row["pattern"],\n'
        '                 "because": decided.because}',
        '        entry = {"id": row["id"], "kind": row["kind"], "pattern": row["pattern"],\n'
        '                 "because": ""}',
        ("test_every_collection_says_why_in_words",),
    ),
    (
        MEMORY,
        "the report hides demoted lessons, disagreeing with the database",
        "    all_lessons = store.lessons(include_demoted=True)",
        "    all_lessons = store.lessons()",
        ("test_a_demoted_lesson_is_still_in_the_report",),
    ),
    # --- the engine's two call sites -----------------------------------------
    (
        ENGINE,
        "nothing credits a payoff",
        "        store.credit_episode(slug)",
        "        pass",
        ("test_both_settling_call_sites_exist_in_the_engine",),
    ),
    (
        ENGINE,
        "advice is given without a slug, so it can never be credited",
        '            "advice_from_past_episodes": memory.advice_for(\n'
        '                objective, episode_slug=slug),',
        '            "advice_from_past_episodes": memory.advice_for(objective),',
        ("test_both_settling_call_sites_exist_in_the_engine",),
    ),
    # --- the one periodic caller ---------------------------------------------
    (
        UPKEEP,
        "nothing ever collects",
        "        if collection_due(client, agent=agent):",
        "        if False:",
        ("test_the_maintenance_loop_collects_deadweight_memory",),
    ),
    (
        UPKEEP,
        "the sweep never records that it ran, so it runs every time",
        "            persistence.put(client, persistence.SELF_ASSESSMENT, _LAST_COLLECTION,",
        "            _ = (client, persistence.SELF_ASSESSMENT, _LAST_COLLECTION,",
        ("test_collecting_is_not_repeated_every_sweep",),
    ),
    (
        UPKEEP,
        "the dry-run switch is ignored",
        "            collected = memory.collect_garbage(dry_run=collection_is_dry())",
        "            collected = memory.collect_garbage(dry_run=False)",
        ("test_the_sweep_can_report_without_deleting",),
    ),
    (
        UPKEEP,
        "a broken learning store takes the whole maintenance loop down",
        "    except (dbaclient.Unavailable, dbaclient.Refused, OSError, ValueError,\n"
        "            sqlite3.Error) as exc:\n"
        "        result[\"problems\"].append(f\"memory collection: {exc}\")",
        "    except dbaclient.Refused as exc:\n"
        "        result[\"problems\"].append(f\"memory collection: {exc}\")",
        ("test_a_broken_learning_store_does_not_stop_the_rest_of_the_sweep",),
    ),
    (
        UPKEEP,
        "the checkpoint cadence is loosened to daily",
        "CHECKPOINT_EVERY_HOURS = 6",
        "CHECKPOINT_EVERY_HOURS = 24",
        ("test_the_maintenance_cadences_are_what_they_are",),
    ),
    (
        UPKEEP,
        "gaps are promoted as often as the log is read",
        "PROMOTE_GAPS_EVERY_HOURS = 24",
        "PROMOTE_GAPS_EVERY_HOURS = 6",
        ("test_the_maintenance_cadences_are_what_they_are",),
    ),
    (
        UPKEEP,
        "collecting runs as often as the log scan",
        "COLLECT_MEMORY_EVERY_HOURS = 24 * 7",
        "COLLECT_MEMORY_EVERY_HOURS = 6",
        ("test_the_maintenance_cadences_are_what_they_are",),
    ),
]


if __name__ == "__main__":
    raise SystemExit(harness.run_probes(PROBES, SUITES))
