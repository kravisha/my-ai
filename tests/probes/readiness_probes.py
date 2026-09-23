"""Mutations that `tests/test_readiness.py` and `tests/test_keystore.py` must
notice.

These two modules exist to answer *"does it run on my PC"*, and they fail in one
direction that is silent and comfortable: **reporting that something is fine
when nobody checked it.** A bring-up that says GREEN is the end of the
conversation, and nothing downstream ever contradicts it.

This repository has already had that exact failure once - a real-machine log
check that passed on a machine with no log, because scanning nothing returns
nothing. Everything here is aimed at the same shape.

Run it directly:

    python tests/probes/readiness_probes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

TESTS = Path(__file__).resolve().parents[1]

READINESS = "desktop/readiness.py"
KEYSTORE = "app/keystore.py"
SUITES = {READINESS: TESTS / "test_readiness.py",
          KEYSTORE: TESTS / "test_keystore.py"}

PROBES: list[harness.Probe] = [

    # --- an unchecked thing is never green -----------------------------------
    (
        READINESS,
        "a check whose dependency failed is judged anyway",
        "        blocked = _need_met(name, done)\n        if blocked:",
        "        blocked = _need_met(name, done)\n        if False:",
        ("test_a_check_whose_dependency_failed_is_blocked_and_not_green",
         "test_being_blocked_survives_two_hops"),
    ),
    (
        READINESS,
        "only a red dependency blocks, so a blocked one passes its block on as "
        "permission",
        "        if done[required].status in (RED, BLOCKED):",
        "        if done[required].status == RED:",
        ("test_being_blocked_survives_two_hops",),
    ),
    # A probe lived here for a dependency that had not run yet. The branch it
    # mutated turned out to be unreachable - `look` declares the checks in
    # dependency order, so a precondition has always run - and an unreachable
    # branch is one no test can reach either. It was deleted and replaced by
    # `test_every_precondition_names_a_check_that_has_already_run`, which holds
    # the table to the order instead, and by the probe below that breaks it.
    (
        READINESS,
        "a missing checkpoint is treated as a fresh one",
        "    if machine.checkpoint_age_hours is None:\n        return (RED,",
        "    if machine.checkpoint_age_hours is None:\n        return (GREEN,",
        ("test_no_checkpoint_at_all_is_red_rather_than_fresh",),
    ),
    (
        READINESS,
        "an absent log is reported as a clean one",
        "    if machine.log_written_within_hours is None:\n        return (RED,",
        "    if machine.log_written_within_hours is None:\n        return (GREEN,",
        ("test_no_log_at_all_is_red_and_says_why_that_is_the_point",),
    ),
    (
        READINESS,
        "the reading defaults to a machine where everything works",
        "    state_directory_writable: bool = False",
        "    state_directory_writable: bool = True",
        ("test_every_field_of_a_blank_reading_defaults_to_the_worse_case",
         "test_a_machine_nobody_looked_at_is_not_reported_as_working"),
    ),
    (
        READINESS,
        "a checkpoint age of zero is used where nobody looked",
        "    checkpoint_age_hours: float | None = None",
        "    checkpoint_age_hours: float | None = 0.0",
        ("test_every_field_of_a_blank_reading_defaults_to_the_worse_case",),
    ),

    # --- causes before symptoms ----------------------------------------------
    (
        READINESS,
        "nothing depends on anything, so one cause produces a page of red",
        "NEEDS = {",
        "NEEDS = {}\n_WAS_NEEDS = {",
        ("test_a_missing_token_blocks_the_dba_check_rather_than_doubling_the_red",
         "test_a_check_whose_dependency_failed_is_blocked_and_not_green"),
    ),
    (
        READINESS,
        "the report is not ordered, so the worst line is wherever it happened",
        "        return sorted(self.results,\n"
        "                      key=lambda one: (ORDER[one.status], one.name))",
        "        return list(self.results)",
        ("test_the_report_is_worst_first",),
    ),
    (
        READINESS,
        "a Gateway that cannot reach its memory is not remarked on",
        "                 if machine.gateway_reaches_dba else",
        "                 if True else",
        ("test_a_gateway_that_cannot_reach_its_memory_is_red_not_green",),
    ),

    # --- the overall answer --------------------------------------------------
    (
        READINESS,
        "the overall status is the best line rather than the worst",
        "        return min((one.status for one in self.results), "
        "key=lambda s: ORDER[s])",
        "        return max((one.status for one in self.results), "
        "key=lambda s: ORDER[s])",
        ("test_a_non_blocking_red_does_not_claim_he_cannot_start",
         "test_one_yellow_makes_the_whole_report_yellow_and_still_runnable"),
    ),
    (
        READINESS,
        "a report with nothing in it is green",
        '        if not self.results:\n            return RED',
        '        if not self.results:\n            return GREEN',
        ("test_an_empty_report_is_red_rather_than_green",),
    ),
    (
        READINESS,
        "every red stops him starting, so a failed ledger reads as a dead Jarvis",
        "        return not [one for one in self.results\n"
        "                    if one.status in (RED, BLOCKED) and one.blocking]",
        "        return not [one for one in self.results\n"
        "                    if one.status in (RED, BLOCKED)]",
        ("test_a_non_blocking_red_does_not_claim_he_cannot_start",),
    ),
    (
        READINESS,
        "nothing blocks him starting, so nowhere to put the key reads as "
        "runnable",
        "    \"gateway_reaches_dba\", \"keystore\",\n)",
        "    \"gateway_reaches_dba\",\n)",
        ("test_a_keystore_with_nowhere_to_put_the_key_stops_him_starting",),
    ),
    (
        READINESS,
        "a precondition names a check that has not run yet, so it blocks for ever",
        '    "logs": ("gateway",),',
        '    "logs": ("gateway", "something_nobody_checks"),',
        ("test_every_precondition_names_a_check_that_has_already_run",),
    ),
    (
        READINESS,
        "the checkpoint staleness limit is loosened to a fortnight",
        "CHECKPOINT_STALE_HOURS = 48.0",
        "CHECKPOINT_STALE_HOURS = 336.0",
        ("test_the_thresholds_are_what_they_are",),
    ),
    (
        READINESS,
        "the log silence limit is loosened to a week",
        "LOG_SILENT_HOURS = 24.0",
        "LOG_SILENT_HOURS = 168.0",
        ("test_the_thresholds_are_what_they_are",),
    ),
    (
        READINESS,
        "the Python minimum drops below what this code needs",
        "MINIMUM_PYTHON = (3, 11)",
        "MINIMUM_PYTHON = (3, 6)",
        ("test_the_thresholds_are_what_they_are",),
    ),
    (
        READINESS,
        "a red line is allowed to say nothing about what to do",
        '            result = Result(name, means, status, because, said_fix or fix)',
        '            result = Result(name, means, status, because, "")',
        ("test_every_red_and_yellow_line_carries_a_fix",
         "test_the_summary_puts_the_fix_under_the_line_it_fixes"),
    ),
    (
        READINESS,
        "the keystore's own next step is replaced by a generic one",
        "                  machine.keystore_because, machine.keystore_next_step)))",
        '                  machine.keystore_because, "see the documentation")))',
        ("test_the_keystore_passes_through_its_own_next_step",),
    ),
    (
        READINESS,
        "a keystore with no escrow is reported as fully ready",
        '                 if machine.keystore_state == "ready" else',
        '                 if machine.keystore_state in ("ready", "no_escrow") else',
        ("test_the_keystore_passes_through_its_own_next_step",),
    ),

    # --- where the key lives --------------------------------------------------
    (
        KEYSTORE,
        "a machine with no DPAPI falls back to something weaker",
        "    if not reading.windows or not reading.dpapi:",
        "    if False:",
        ("test_a_machine_without_dpapi_is_refused_rather_than_given_a_plain_file",
         "test_windows_without_dpapi_is_also_refused"),
    ),
    (
        KEYSTORE,
        "only one of the two platform facts is consulted",
        "    if not reading.windows or not reading.dpapi:",
        "    if not reading.windows:",
        ("test_windows_without_dpapi_is_also_refused",),
    ),
    (
        KEYSTORE,
        "a key this account cannot open is reported as simply absent, sending "
        "him to make a new one over the top",
        "    if not reading.key_opens:\n        return Verdict(\n            UNREADABLE,",
        "    if not reading.key_opens:\n        return Verdict(\n            ABSENT,",
        ("test_a_key_this_account_cannot_open_is_named_as_that",
         "test_every_state_the_module_names_is_one_some_reading_produces"),
    ),
    (
        KEYSTORE,
        "a missing escrow is never mentioned",
        "    if not reading.escrow_present:",
        "    if False:",
        ("test_a_key_with_no_escrow_still_runs_but_is_reported",),
    ),
    (
        KEYSTORE,
        "a missing escrow locks him out of his own key",
        "WORKABLE = (NO_ESCROW, READY)",
        "WORKABLE = (READY,)",
        ("test_a_key_with_no_escrow_still_runs_but_is_reported",),
    ),
    (
        KEYSTORE,
        "an escrow holding a different key is accepted as a backup",
        "            and reading.escrow_fingerprint != reading.key_fingerprint):",
        "            and False):",
        ("test_a_stale_escrow_is_reported_as_no_escrow_and_says_why",),
    ),
    (
        KEYSTORE,
        "an escrow nobody checked is reported as stale, sending him to rewrite "
        "a good backup",
        "    if (reading.escrow_fingerprint is not None\n"
        "            and reading.key_fingerprint is not None\n",
        "    if (True\n"
        "            or reading.key_fingerprint is not None\n",
        ("test_an_unchecked_escrow_is_not_reported_as_a_mismatch",),
    ),
    (
        KEYSTORE,
        "the escrow salt is fixed, so every installation shares a key space",
        "    salt = secretbox.new_salt()",
        "    salt = b\"0123456789abcdef\"",
        ("test_two_escrows_of_one_key_differ",),
    ),
    (
        KEYSTORE,
        "the escrow is sealed with no passphrase strength at all",
        "    check_passphrase(passphrase)\n    salt = secretbox.new_salt()",
        "    salt = secretbox.new_salt()",
        ("test_a_short_passphrase_is_refused_when_writing_the_escrow",
         "test_the_escrow_passphrase_minimum_is_twelve"),
    ),
    (
        KEYSTORE,
        "the passphrase minimum drops to something guessable",
        "ESCROW_PASSPHRASE_MIN = 12",
        "ESCROW_PASSPHRASE_MIN = 4",
        ("test_the_escrow_passphrase_minimum_is_twelve",),
    ),
    (
        KEYSTORE,
        "a truncated escrow is sliced into nonsense instead of refused",
        "    if len(blob) <= secretbox.SALT_BYTES:",
        "    if False:",
        ("test_a_truncated_escrow_says_so_rather_than_crashing",),
    ),
    (
        KEYSTORE,
        "the escrow's own purpose string is dropped, so any sealed blob opens "
        "as a key",
        "ESCROW_AAD = b\"jarvis/charter-key-escrow/v1\"",
        "ESCROW_AAD = b\"\"",
        (),  # recorded: `secretbox` refuses an empty AAD outright, so this is
             # caught at the layer that owns it and asserted by
             # `tests/test_secretbox.py`. A probe here would only re-test that.
    ),
    (
        KEYSTORE,
        "`describe` claims a protection this does not give",
        '        "protects_against_jarvis": False,',
        '        "protects_against_jarvis": True,',
        ("test_describe_says_what_was_decided_and_what_it_does_not_buy",),
    ),
]


if __name__ == "__main__":
    raise SystemExit(harness.run_probes(PROBES, SUITES))
