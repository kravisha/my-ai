"""Mutations that `tests/test_readback.py` must notice.

Krish, 2026-09-23: *"Jarvis should reiterate his understanding back to the user
for critical tasks... When user confirms Jarvis will act and complete execution."*

This module fails in two directions and both are quiet. Confirm too much and the
user is trained to say yes without listening, which costs the confirmations that
matter; confirm too little and something irreversible happens on a
misunderstanding. And the most valuable behaviour here - marking which
particulars Jarvis inferred - can be removed without any test that checks only
for a read-back noticing.

Run it directly:

    python tests/probes/readback_probes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

TESTS = Path(__file__).resolve().parents[1]

READBACK = "gateway/readback.py"
SUITES = {READBACK: TESTS / "test_readback.py"}

PROBES: list[harness.Probe] = [
    # --- where the line is drawn ----------------------------------------------
    (
        READBACK,
        "everything needs a confirmation, including the radio",
        "    if verdict.disposition == initiative.PROPOSE:\n        return True, verdict.reason",
        "    if True:\n        return True, verdict.reason",
        ("test_turning_up_the_radio_does_not",
         "test_the_line_is_drawn_by_the_policy_that_already_owns_it",
         "test_a_trivial_action_proceeds_with_no_mandate_at_all"),
    ),
    (
        READBACK,
        "nothing needs a confirmation, including sending mail",
        "    if verdict.disposition == initiative.PROPOSE:",
        "    if False:",
        ("test_sending_an_email_needs_the_read_back",
         "test_a_consequential_action_without_confirmation_is_refused"),
    ),
    (
        READBACK,
        "a refused action is offered for confirmation anyway",
        "    if verdict.disposition == initiative.REFUSE:",
        "    if False:",
        ("test_a_refused_action_has_nothing_to_confirm",),
    ),
    (
        READBACK,
        "the line is a list of verbs kept here rather than the existing policy",
        "    verdict = initiative.decide(action, level=level)",
        '    class verdict:\n'
        '        disposition = initiative.PROPOSE if action.name in ("send_email",) \\\n'
        '            else initiative.ACT\n'
        '        reason = "on the list"',
        ("test_the_line_is_drawn_by_the_policy_that_already_owns_it",
         "test_a_refused_action_has_nothing_to_confirm"),
    ),
    # --- the user decides -----------------------------------------------------
    (
        READBACK,
        "Jarvis can confirm his own understanding",
        "    if confirmed_by.strip().lower() == (agent or \"\").strip().lower():",
        "    if False:",
        ("test_jarvis_cannot_confirm_his_own_understanding",
         "test_the_check_is_not_case_sensitive"),
    ),
    (
        READBACK,
        "the self-confirmation check is fooled by whitespace and case",
        "    if confirmed_by.strip().lower() == (agent or \"\").strip().lower():",
        "    if confirmed_by == agent:",
        ("test_the_check_is_not_case_sensitive",),
    ),
    (
        READBACK,
        "a confirmation need not say who gave it",
        '    if not (confirmed_by or "").strip():',
        "    if False:",
        ("test_a_confirmation_must_say_who_gave_it",),
    ),
    # --- the read-back is particulars, and marks what was inferred ------------
    (
        READBACK,
        "a read-back with no particulars is accepted",
        "        if required and not self.particulars:",
        "        if False:",
        ("test_a_read_back_with_no_particulars_is_refused",),
    ),
    (
        READBACK,
        "inferred particulars are not marked, so the read-back confirms nothing",
        "    TOLD: \"you said\",\n"
        "    INFERRED: \"I worked that out\",\n"
        "    DEFAULTED: \"nobody said, so I used the usual\",",
        "    TOLD: \"you said\",\n"
        "    INFERRED: \"you said\",\n"
        "    DEFAULTED: \"you said\",",
        ("test_the_inferred_particulars_are_marked_in_place_and_counted",
         "test_a_defaulted_particular_reads_as_a_convention_not_a_fact"),
    ),
    (
        READBACK,
        "the count of Jarvis's own guesses is dropped from the close",
        "        guessed = self.inferred()\n        if guessed:",
        "        guessed = self.inferred()\n        if False:",
        ("test_the_inferred_particulars_are_marked_in_place_and_counted",),
    ),
    (
        READBACK,
        "everything counts as inferred, so the marking means nothing",
        "        return tuple(item for item in self.particulars if item.source != TOLD)",
        "        return tuple(self.particulars)",
        ("test_a_read_back_of_only_what_it_was_told_confirms_nothing_and_says_so",),
    ),
    (
        READBACK,
        "unknowns are not read out",
        "        for unknown in self.unknowns:\n"
        "            lines.append(f\"  - I could not work out: {unknown}\")",
        "        for unknown in []:\n"
        "            lines.append(f\"  - I could not work out: {unknown}\")",
        ("test_unknowns_are_read_out",),
    ),
    (
        READBACK,
        "the read-back does not end by asking",
        '        lines.append("Have I got that right?")',
        "        pass",
        ("test_the_read_back_ends_by_asking",),
    ),
    (
        READBACK,
        "a particular needs no label",
        '        if not (self.label or "").strip():',
        "        if False:",
        ("test_an_unlabelled_particular_is_refused",),
    ),
    (
        READBACK,
        "the sources are open",
        "        if self.source not in SOURCES:",
        "        if False:",
        ("test_the_sources_are_a_closed_set",),
    ),
    # --- corrections ----------------------------------------------------------
    (
        READBACK,
        "a correction keeps its old source, so Jarvis's guess stays a guess",
        '                revised.append(Particular(label=label, value=value, source=TOLD))\n'
        "                found = True",
        "                revised.append(item)\n                found = True",
        ("test_a_correction_becomes_something_krish_said",),
    ),
    (
        READBACK,
        "a correction naming something new is dropped",
        "        if not found:\n"
        "            revised.append(Particular(label=label, value=value, source=TOLD))",
        "        if False:\n"
        "            revised.append(Particular(label=label, value=value, source=TOLD))",
        ("test_a_correction_can_add_something_nobody_had_mentioned",),
    ),
    (
        READBACK,
        "correcting an unknown leaves it unresolved",
        "            unknowns=tuple(item for item in self.unknowns if item != label))",
        "            unknowns=self.unknowns)",
        ("test_correcting_an_unknown_resolves_it",),
    ),
    # --- unknowns -------------------------------------------------------------
    (
        READBACK,
        "an unresolved unknown does not block confirmation",
        "    if standing:\n        raise NotStated(",
        "    if False:\n        raise NotStated(",
        ("test_an_unresolved_unknown_blocks_confirmation",
         "test_each_unknown_must_be_named_to_proceed_without_it"),
    ),
    (
        READBACK,
        "naming one unknown accepts all of them",
        "    standing = [item for item in understanding.unknowns if item not in accepted]",
        "    standing = [] if accepted else list(understanding.unknowns)",
        ("test_each_unknown_must_be_named_to_proceed_without_it",),
    ),
    (
        READBACK,
        "an unknown nobody raised can be accepted",
        "    if unknown:\n        raise NotStated(\n"
        "            f\"accepted unknown(s) nobody raised",
        "    if False:\n        raise NotStated(\n"
        "            f\"accepted unknown(s) nobody raised",
        ("test_accepting_an_unknown_nobody_raised_is_refused",),
    ),
    # --- what a confirmation licenses -----------------------------------------
    (
        READBACK,
        "a confirmation for one action covers any action",
        "        if action.name != self.understanding.action.name:",
        "        if False:",
        ("test_confirming_one_thing_is_not_confirming_the_next",),
    ),
    (
        READBACK,
        "a confirmed action may be carried out with different particulars",
        "            if agreed[label] != value:",
        "            if False:",
        ("test_the_same_action_with_a_different_particular_is_out_of_scope",),
    ),
    (
        READBACK,
        "particulars can be added after the confirmation",
        "            if label not in agreed:",
        "            if False:",
        ("test_a_particular_added_after_the_fact_is_out_of_scope",),
    ),
    (
        READBACK,
        "a consequential action proceeds with no mandate",
        "    if mandate is None:\n        raise NotConfirmed(",
        "    if False:\n        raise NotConfirmed(",
        ("test_a_consequential_action_without_confirmation_is_refused",),
    ),
    (
        READBACK,
        "the mandate can be widened after the fact",
        "@dataclass(frozen=True)\nclass Mandate:",
        "@dataclass\nclass Mandate:",
        ("test_a_mandate_cannot_be_edited_into_a_wider_one",),
    ),
    (
        READBACK,
        "`describe` claims a protection the module does not give",
        '        "self_confirmation": "refused",',
        '        "self_confirmation": "allowed",',
        ("test_describe_says_what_a_confirmation_licenses",),
    ),
]


if __name__ == "__main__":
    raise SystemExit(harness.run_probes(PROBES, SUITES))
