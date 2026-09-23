"""Mutations that the keyed-authority tiers must notice.

Krish, 2026-09-23, on the absolute `GOVERNANCE` list this replaced: *"too
conservative and reeks of trauma... don't put anything in there that Jarvis may
need to change like his prime directive which is the constitution and the
amendments to the constitution etc. Don't put anything in there that Jarvis may
need to change under some emergency to save me."*

A tier system fails in two opposite directions and both are silent. Too tight and
Jarvis cannot amend his own constitution or reach a file while Krish needs him
to; too loose and he can approve a change to the thing doing the approving. Most
of these probes push it one way or the other.

Run it directly:

    python tests/probes/authority_probes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

TESTS = Path(__file__).resolve().parents[1]

INTROSPECT = "gateway/introspect.py"
SELFMOD = "gateway/selfmod.py"
CHARTER = "gateway/charter.py"
DBA_PERMISSIONS = "dba/permissions.py"
SUITES = {INTROSPECT: (TESTS / "test_jarvis_selfmod.py",
                       TESTS / "test_constitution.py"),
          SELFMOD: TESTS / "test_jarvis_selfmod.py",
          CHARTER: TESTS / "test_jarvis_selfmod.py",
          DBA_PERMISSIONS: TESTS / "test_jarvis_selfmod.py"}

PROBES: list[harness.Probe] = [
    # --- the circle stays closed on the ordinary path -------------------------
    (
        INTROSPECT,
        "a proposal can edit the machinery that approves proposals",
        "    key = key_for(as_posix)\n    if key is not None:",
        "    key = key_for(as_posix)\n    if False:",
        ("test_jarvis_cannot_widen_his_own_authority_by_proposing_it",
         "test_the_working_notes_are_amendable_with_a_key"),
    ),
    (
        INTROSPECT,
        "any key opens any keyed file",
        "        if key in set(keys or ()):",
        "        if keys:",
        ("test_one_key_does_not_open_the_other_tier",),
    ),
    (
        INTROSPECT,
        "the circular tier is emptied",
        '    "gateway/selfmod.py",\n    "gateway/introspect.py",',
        "",
        ("test_the_keyed_tier_is_narrow_and_says_why_each_member_is_there",
         "test_jarvis_cannot_widen_his_own_authority_by_proposing_it"),
    ),
    (
        INTROSPECT,
        "the lifecycle and the reasoning are put back behind a key",
        'CIRCULAR = (\n',
        'CIRCULAR = (\n    "gateway/gaps.py",\n    "gateway/inquiry.py",\n',
        ("test_the_lifecycle_and_the_reasoning_are_his_to_improve",
         "test_the_keyed_tier_is_narrow_and_says_why_each_member_is_there"),
    ),
    # --- the charter is reachable --------------------------------------------
    (
        INTROSPECT,
        "the working notes are unreachable, so the keyed tier is empty",
        "CHARTER = (\n    \"CLAUDE.md\",\n)",
        "CHARTER = ()",
        ("test_the_working_notes_are_amendable_with_a_key",
         "test_the_keyed_tier_is_narrow_and_says_why_each_member_is_there"),
    ),
    (
        INTROSPECT,
        "a keyed refusal reads as a wall rather than a request for the key",
        'f"Amending what Jarvis is for is a large act; it is not a "\n'
        '               f"forbidden one, and this refusal is a request for the key "\n'
        '               f"rather than a wall."',
        'f"Refused."',
        ("test_the_working_notes_are_amendable_with_a_key",),
    ),
    # --- the one wall ---------------------------------------------------------
    (
        INTROSPECT,
        "the constitution is reachable again",
        "    if as_posix in SEALED:",
        "    if False:",
        ("test_the_charter_documents_are_refused_even_with_the_key",),
    ),
    (
        INTROSPECT,
        "the wall is empty, so the constitution is reachable",
        'SEALED = (\n    "AI-CONSTITUTION.md",\n)',
        "SEALED = ()",
        ("test_the_charter_documents_are_refused_even_with_the_key",
         "test_the_keyed_tier_is_narrow_and_says_why_each_member_is_there"),
    ),
    (
        INTROSPECT,
        "the seal is checked after the key, so a key opens it",
        "    if as_posix in SEALED:\n        return False, (",
        "    if as_posix in SEALED and not keys and not emergency:\n        return False, (",
        ("test_the_charter_documents_are_refused_even_with_the_key",),
    ),
    (
        INTROSPECT,
        "a sealed file reports a key, which reads as obtainable",
        "def sealed(path: str | Path) -> bool:\n"
        '    """Whether nothing may change this, ever."""\n'
        "    return _relative(path).as_posix() in SEALED",
        "def sealed(path: str | Path) -> bool:\n"
        '    """Whether nothing may change this, ever."""\n'
        "    return False",
        ("test_nothing_can_reach_the_constitution_file_through_any_path",),
    ),
    (
        INTROSPECT,
        "the amendments become rewritable by a proposal",
        'APPEND_ONLY = (\n    "AI-CONSTITUTION-AMENDMENTS.md",\n)',
        "APPEND_ONLY = ()",
        ("test_the_keyed_tier_is_narrow_and_says_why_each_member_is_there",
         "test_the_charter_documents_are_refused_even_with_the_key"),
    ),
    # --- the break-glass ------------------------------------------------------
    (
        INTROSPECT,
        "the break-glass does not open a keyed file",
        "        if emergency:\n            return True, \"\"",
        "        if False:\n            return True, \"\"",
        ("test_the_break_glass_reaches_a_keyed_file_and_is_recorded",),
    ),
    (
        INTROSPECT,
        "an emergency reaches another system's code",
        "    if not relative.parts or relative.parts[0] not in MODIFIABLE_ROOTS:\n"
        "        if emergency:",
        "    if not relative.parts or relative.parts[0] not in MODIFIABLE_ROOTS:\n"
        "        if False:",
        ("test_an_emergency_still_does_not_reach_another_system",),
    ),
    # --- the key is the owner's to write --------------------------------------
    (
        DBA_PERMISSIONS,
        "Jarvis can write himself a key",
        "    if (entity_type in OWNER_WRITTEN_TYPES\n"
        "            and action in WRITING_ACTIONS and ADMINISTER not in held):",
        "    if False:",
        ("test_jarvis_cannot_write_himself_a_key",
         "test_a_lapsed_key_stops_working_and_says_so"),
    ),
    (
        DBA_PERMISSIONS,
        "only creating a key needs the owner, so an expiry can be moved",
        'WRITING_ACTIONS = ("create", "update", "archive", "delete_authorized", "link",\n'
        '                   "unlink", "reconcile")',
        'WRITING_ACTIONS = ("create",)',
        ("test_a_lapsed_key_stops_working_and_says_so",),
    ),
    (
        INTROSPECT,
        "the machinery that decides who may approve is ordinary again",
        '    "app/permissions.py",',
        "",
        # Named for the membership test rather than the behavioural one: the
        # behavioural test walks five paths and this is not among them, so it
        # passed with the entry deleted. A tier whose membership is only
        # spot-checked is a tier anything can quietly leave.
        ("test_the_keyed_tier_is_narrow_and_says_why_each_member_is_there",),
    ),
    (
        INTROSPECT,
        "the self-modification path itself drops out of the circle",
        '    "gateway/selfmod.py",',
        "",
        ("test_the_keyed_tier_is_narrow_and_says_why_each_member_is_there",
         "test_jarvis_cannot_widen_his_own_authority_by_proposing_it"),
    ),
    (
        DBA_PERMISSIONS,
        "no record type is the owner's to write",
        'OWNER_WRITTEN_TYPES = ("charter_grant", "guess_verdict")',
        "OWNER_WRITTEN_TYPES = ()",
        ("test_jarvis_cannot_write_himself_a_key",),
    ),
    (
        CHARTER,
        "a lapsed grant still counts",
        "        if expires is None or expires <= when:\n            continue",
        "        if False:\n            continue",
        ("test_a_lapsed_key_stops_working_and_says_so",),
    ),
    (
        CHARTER,
        "a revoked grant still counts",
        '        if (row.get("status") or ACTIVE) != ACTIVE:\n            continue',
        "        if False:\n            continue",
        ("test_a_revoked_key_is_not_in_force",),
    ),
    (
        CHARTER,
        "a grant for one key is read as a grant for every key",
        '    return tuple(sorted({row["key"] for row in\n'
        '                         live_grants(client, agent=agent, now=now)}))',
        "    return introspect.KEYS if live_grants(\n"
        "        client, agent=agent, now=now) else ()",
        ("test_one_granted_key_does_not_open_the_other_tier",),
    ),
    (
        CHARTER,
        "a grant never expires",
        "DEFAULT_MINUTES = 60",
        "DEFAULT_MINUTES = 60 * 24 * 365 * 100",
        ("test_a_grant_is_short_by_default",),
    ),
    (
        CHARTER,
        "a live grant is explained as a revoked one",
        "    if live:",
        "    if False:",
        ("test_a_lapsed_key_stops_working_and_says_so",),
    ),
    (
        CHARTER,
        "a missing grant is not explained as something Krish can fix",
        '        return (f"no {key!r} key has ever been granted. Krish grants one from "\n'
        '                f"the operator console; Jarvis cannot write the record, which "\n'
        '                f"is the safeguard rather than an inconvenience.")',
        '        return "no."',
        ("test_a_missing_key_is_explained_as_a_next_step_not_a_wall",),
    ),
    (
        SELFMOD,
        "keys are taken from the caller again instead of the store",
        "    keys = charter.keys_in_force(client, agent=agent)",
        "    keys = introspect.KEYS",
        ("test_a_missing_key_is_explained_as_a_next_step_not_a_wall",
         "test_one_granted_key_does_not_open_the_other_tier"),
    ),
    (
        SELFMOD,
        "a refusal does not say which key is missing",
        "        if missing and not emergency:",
        "        if False:",
        ("test_a_missing_key_is_explained_as_a_next_step_not_a_wall",),
    ),
    (
        SELFMOD,
        "the keys in force are ignored",
        "        introspect.require_modifiable(affected_files, keys=keys,\n"
        "                                      emergency=bool(emergency))",
        "        introspect.require_modifiable(affected_files)",
        ("test_the_break_glass_reaches_a_keyed_file_and_is_recorded",
         "test_a_granted_key_actually_drafts_the_proposal"),
    ),
    (
        SELFMOD,
        "a blank emergency is accepted, leaving an override with no reason",
        '    if emergency and not emergency.strip():',
        "    if False:",
        ("test_an_emergency_must_say_what_the_emergency_is",),
    ),
    (
        SELFMOD,
        "an emergency is not written to the life ledger",
        "        _note(client, ledger.EMERGENCY_OVERRIDE,",
        "        _ = (client, ledger.EMERGENCY_OVERRIDE,",
        ("test_the_break_glass_reaches_a_keyed_file_and_is_recorded",),
    ),
    (
        SELFMOD,
        "an emergency leaves no mark on the proposal Krish reads",
        '        client.update(entity_id,\n'
        '                      {"reason": f"{EMERGENCY_MARKER}: {emergency.strip()}',
        '        client.update(entity_id,\n'
        '                      {"ignored": f"{EMERGENCY_MARKER}: {emergency.strip()}',
        ("test_the_break_glass_reaches_a_keyed_file_and_is_recorded",),
    ),
    (
        SELFMOD,
        "every proposal is marked as an emergency",
        "    if emergency:\n        keyed = sorted(",
        "    if True:\n        keyed = sorted(",
        ("test_an_ordinary_proposal_records_no_override",),
    ),
    (
        SELFMOD,
        "a granted key is then vetoed by the policy anyway",
        "    granted = set(keys or ())",
        "    granted = set()",
        ("test_a_granted_key_actually_drafts_the_proposal",
         "test_an_unkeyed_reach_at_the_circle_is_still_named_as_widening_authority"),
    ),
    (
        SELFMOD,
        "a change touching the circular tier is not named as widening authority",
        "    touches_authority = any(\n"
        "        introspect.key_for(path) == introspect.KEY_CIRCULAR\n"
        "        and introspect.KEY_CIRCULAR not in granted for path in paths)",
        "    touches_authority = False",
        ("test_an_unkeyed_reach_at_the_circle_is_still_named_as_widening_authority",),
    ),
]


if __name__ == "__main__":
    raise SystemExit(harness.run_probes(PROBES, SUITES))
