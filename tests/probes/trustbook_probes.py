"""Mutations that `tests/test_trustbook.py` must notice.

Two things fail silently here. A store that drops a row looks exactly like a
domain nobody has guessed in, and a loader that quietly skips a verdict it cannot
match looks exactly like a clean record - which is the shape a forged promotion
would take.

Run it directly:

    python tests/probes/trustbook_probes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

TESTS = Path(__file__).resolve().parents[1]

TRUSTBOOK = "gateway/trustbook.py"
PERMISSIONS = "dba/permissions.py"
SUITES = {TRUSTBOOK: TESTS / "test_trustbook.py",
          PERMISSIONS: TESTS / "test_trustbook.py"}

PROBES: list[harness.Probe] = [
    # --- who writes which half ------------------------------------------------
    (
        PERMISSIONS,
        "Jarvis can write his own verdict",
        'OWNER_WRITTEN_TYPES = ("charter_grant", "guess_verdict")',
        'OWNER_WRITTEN_TYPES = ("charter_grant",)',
        ("test_jarvis_cannot_write_his_own_verdict",
         "test_jarvis_cannot_rate_his_own_work_either"),
    ),
    (
        PERMISSIONS,
        "only creating a verdict needs the owner, so a rating can be added later",
        'WRITING_ACTIONS = ("create", "update", "archive", "delete_authorized", "link",\n'
        '                   "unlink", "reconcile")',
        'WRITING_ACTIONS = ("create",)',
        ("test_jarvis_cannot_rate_his_own_work_either",),
    ),
    # --- the record survives ---------------------------------------------------
    (
        TRUSTBOOK,
        "a guess is never written down",
        '    return client.create(GUESS, data, reason="anticipated what Krish would want")',
        '    return "guess-not-written"',
        ("test_jarvis_records_his_own_guess",
         "test_the_record_outlives_the_process"),
    ),
    (
        TRUSTBOOK,
        "the reason a guess was made is dropped",
        '        "because": guess.because,',
        '        "because": "",',
        ("test_jarvis_records_his_own_guess",),
    ),
    (
        TRUSTBOOK,
        "timestamps are recorded to the second, so a run cannot be ordered",
        '    return when.isoformat(timespec="microseconds") if when else None',
        '    return when.isoformat(timespec="seconds") if when else None',
        ("test_one_botched_execution_still_drops_the_rung_after_a_reload",),
    ),
    (
        TRUSTBOOK,
        "every domain is loaded together, so one bad domain costs the others",
        '    if domain is not None:\n        criteria["domain"] = domain',
        "    if False:\n        pass",
        (),  # recorded: `load` is always called without a domain by `standing`,
             # which filters per domain itself. The parameter is for a caller
             # that wants one domain's rows, and no test goes through it yet.
    ),
    (
        TRUSTBOOK,
        "a rating is written without saying who gave it",
        '    if not (rated_by or "").strip():',
        "    if False:",
        ("test_a_rating_must_say_who_gave_it",),
    ),
    (
        TRUSTBOOK,
        "outcomes are open",
        "    if outcome not in anticipation.OUTCOMES:",
        "    if False:",
        ("test_outcomes_and_qualities_stay_closed",),
    ),
    (
        TRUSTBOOK,
        "qualities are open",
        "    if quality not in anticipation.QUALITIES:",
        "    if False:",
        ("test_outcomes_and_qualities_stay_closed",),
    ),
    (
        TRUSTBOOK,
        "a verdict need not say who gave it",
        '    if not (settled_by or "").strip():',
        "    if False:",
        ("test_a_verdict_must_say_who_gave_it",),
    ),
    # --- loading is hostile ----------------------------------------------------
    (
        TRUSTBOOK,
        "a verdict pointing at nothing is quietly skipped",
        '        if target not in known:\n            problems.append(',
        "        if False:\n            problems.append(",
        ("test_a_verdict_naming_a_guess_that_is_not_there_is_reported",),
    ),
    (
        TRUSTBOOK,
        "a second verdict silently replaces the first",
        "        if target in by_guess:\n            problems.append(",
        "        if False:\n            problems.append(",
        ("test_two_verdicts_on_one_guess_are_reported",),
    ),
    (
        TRUSTBOOK,
        "the verdict is never joined to its guess",
        "        verdict = by_guess.get(row[\"id\"])\n        if verdict:",
        "        verdict = by_guess.get(row[\"id\"])\n        if False:",
        ("test_krish_settles_and_rates_through_the_operator",
         "test_the_record_outlives_the_process"),
    ),
    (
        TRUSTBOOK,
        "the rating is joined but the outcome is not",
        '            guess.outcome = verdict.get("outcome")',
        '            guess.outcome = None',
        ("test_krish_settles_and_rates_through_the_operator",
         "test_the_record_outlives_the_process"),
    ),
    (
        TRUSTBOOK,
        "the outcome is joined but the rating is not",
        '            guess.quality = verdict.get("quality")',
        "            guess.quality = None",
        ("test_krish_settles_and_rates_through_the_operator",
         "test_the_record_outlives_the_process"),
    ),
    (
        TRUSTBOOK,
        "a value that is not a string takes the loader down",
        "        when = datetime.fromisoformat(str(stamp))",
        "        when = datetime.fromisoformat(stamp)",
        ("test_an_unparseable_timestamp_returns_none_rather_than_raising",),
    ),
    (
        TRUSTBOOK,
        "a naive timestamp is read as local time",
        "    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)",
        "    return when",
        ("test_a_naive_timestamp_is_read_as_utc",),
    ),
    (
        TRUSTBOOK,
        "`describe` claims the record survives when it does not",
        '        "verdict_written_by": "the operator console only",',
        '        "verdict_written_by": "anybody",',
        ("test_describe_says_who_writes_which_half",),
    ),
]


if __name__ == "__main__":
    raise SystemExit(harness.run_probes(PROBES, SUITES))
