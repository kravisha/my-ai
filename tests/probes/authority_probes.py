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
SUITES = {INTROSPECT: TESTS / "test_jarvis_selfmod.py",
          SELFMOD: TESTS / "test_jarvis_selfmod.py"}

PROBES: list[harness.Probe] = [
    # --- the circle stays closed on the ordinary path -------------------------
    (
        INTROSPECT,
        "a proposal can edit the machinery that approves proposals",
        "    key = key_for(as_posix)\n    if key is not None:",
        "    key = key_for(as_posix)\n    if False:",
        ("test_jarvis_cannot_widen_his_own_authority_by_proposing_it",
         "test_the_charter_is_amendable_with_a_key"),
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
        "the constitution is unreachable again",
        "CHARTER = (\n    \"AI-CONSTITUTION.md\",\n    \"CLAUDE.md\",\n)",
        "CHARTER = ()",
        ("test_the_charter_is_amendable_with_a_key",
         "test_the_keyed_tier_is_narrow_and_says_why_each_member_is_there"),
    ),
    (
        INTROSPECT,
        "a keyed refusal reads as a wall rather than a request for the key",
        'f"Amending what Jarvis is for is a large act; it is not a "\n'
        '               f"forbidden one, and this refusal is a request for the key "\n'
        '               f"rather than a wall."',
        'f"Refused."',
        ("test_the_charter_is_amendable_with_a_key",),
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
    (
        SELFMOD,
        "the keys a proposal carries are ignored",
        "    introspect.require_modifiable(affected_files, keys=keys,\n"
        "                                  emergency=bool(emergency))",
        "    introspect.require_modifiable(affected_files)",
        ("test_the_break_glass_reaches_a_keyed_file_and_is_recorded",),
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
