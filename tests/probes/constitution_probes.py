"""Mutations that `tests/test_constitution.py` must notice.

The three defences here fail in three different ways, and the third fails
silently. Encryption that stops encrypting is caught by a byte check; a key
requirement that stops requiring is caught by an amendment landing. But tamper
*detection* that stops detecting looks exactly like a clean history - the report
says `intact: True` and nobody has any reason to look further. Most of these
probes blind one check in `verify` and confirm that a test notices the silence.

Run it directly:

    python tests/probes/constitution_probes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

TESTS = Path(__file__).resolve().parents[1]

CONSTITUTION = "gateway/constitution.py"
SUITES = {CONSTITUTION: TESTS / "test_constitution.py"}

PROBES: list[harness.Probe] = [
    # --- encrypted at rest ----------------------------------------------------
    (
        CONSTITUTION,
        "the constitution is written to disk in plain text",
        "    _write(_path(CONSTITUTION_FILE),\n"
        "           secretbox.seal(text.encode(\"utf-8\"), key=key, aad=CONSTITUTION_AAD))\n"
        "    _write(_path(AMENDMENTS_FILE),",
        "    _write(_path(CONSTITUTION_FILE), text.encode(\"utf-8\"))\n"
        "    _write(_path(AMENDMENTS_FILE),",
        ("test_the_constitution_is_not_on_disk_in_plain_text",),
    ),
    (
        CONSTITUTION,
        "the two sealed files are interchangeable",
        "CONSTITUTION_AAD = b\"jarvis:charter:constitution:v1\"\n"
        "AMENDMENTS_AAD = b\"jarvis:charter:amendments:v1\"",
        "CONSTITUTION_AAD = b\"jarvis:charter:v1\"\n"
        "AMENDMENTS_AAD = b\"jarvis:charter:v1\"",
        ("test_one_sealed_file_cannot_be_read_as_the_other",),
    ),
    (
        CONSTITUTION,
        "the sealed files are readable by anybody on the machine",
        "        os.chmod(temporary, OWNER_ONLY)",
        "        os.chmod(temporary, 0o644)",
        ("test_the_sealed_files_are_owner_only",),
    ),
    (
        CONSTITUTION,
        "the charter is kept inside the git checkout",
        'DEFAULT_DIR = PROJECT_ROOT / "data" / "charter"',
        "DEFAULT_DIR = PROJECT_ROOT",
        ("test_the_charter_lives_outside_the_repository_by_default",),
    ),
    # --- amendable only with the owner's key ----------------------------------
    (
        CONSTITUTION,
        "an amendment does not need the owner's key",
        "    if grant is None:\n        raise Unauthorised(",
        "    if False:\n        raise Unauthorised(",
        ("test_jarvis_cannot_amend_without_the_owners_key",
         "test_a_lapsed_key_cannot_amend"),
    ),
    (
        CONSTITUTION,
        "any key in force amends the constitution, including the circular one",
        "    return charter.live_grant(client, charter.introspect.KEY_CHARTER, agent=agent)",
        "    live = charter.live_grants(client, agent=agent)\n"
        "    return live[0] if live else None",
        ("test_the_circular_key_does_not_amend_the_constitution",),
    ),
    (
        CONSTITUTION,
        "an amendment need not say why",
        '    if not (why or "").strip():',
        "    if False:",
        ("test_an_amendment_must_say_why",),
    ),
    (
        CONSTITUTION,
        "a constitution can be replaced wholesale, leaving no link and no grant",
        "    if installed():\n        raise Unauthorised(",
        "    if False:\n        raise Unauthorised(",
        ("test_installing_over_an_existing_constitution_is_refused",),
    ),
    (
        CONSTITUTION,
        "an amendment leaves no trace in the life ledger",
        "    charter.note_amendment(client, what=why.strip()[:120], why=why.strip(),",
        "    _ = (client, why.strip()[:120], why.strip(),",
        ("test_an_amendment_is_recorded_in_the_life_ledger",),
    ),
    # --- tamper evidence, which fails silently --------------------------------
    (
        CONSTITUTION,
        "sealed text that no amendment accounts for is not noticed",
        "    if chain and _digest(current) != expected_text:",
        "    if False:",
        ("test_rewriting_the_sealed_text_directly_is_detected",),
    ),
    (
        CONSTITUTION,
        "a link naming a grant that was never issued is not noticed",
        "        if not grant:\n            report[\"problems\"].append(",
        "        if False:\n            report[\"problems\"].append(",
        ("test_an_amendment_naming_a_grant_that_was_never_issued_is_detected",),
    ),
    (
        CONSTITUTION,
        "a link with no grant at all is not noticed",
        "        if not grant_id:",
        "        if False:",
        ("test_an_amendment_with_no_grant_at_all_is_detected",),
    ),
    (
        CONSTITUTION,
        "an altered amendment is not noticed",
        '        if entry.get("link") != expected:',
        "        if False:",
        ("test_altering_an_old_amendment_is_detected",
         "test_removing_an_amendment_from_the_middle_is_detected"),
    ),
    (
        CONSTITUTION,
        "a removed amendment is reported as an alteration, losing the cause",
        '            if entry.get("previous") != previous:',
        "            if False:",
        ("test_removing_an_amendment_from_the_middle_is_detected",),
    ),
    (
        CONSTITUTION,
        "the chain does not cover the link before it, so a deletion is invisible",
        '        {"previous": previous, "at": at, "text": text_digest,',
        '        {"at": at, "text": text_digest,',
        ("test_removing_an_amendment_from_the_middle_is_detected",),
    ),
    (
        CONSTITUTION,
        "a DBA that is down is reported as a forgery",
        "        except (dbaclient.Refused, dbaclient.Unavailable) as exc:\n"
        "            report[\"problems\"].append(\n"
        "                f\"amendment {position}'s grant {grant_id} could not be read \"",
        "        except (dbaclient.Refused,) as exc:\n"
        "            report[\"problems\"].append(\n"
        "                f\"amendment {position}'s grant {grant_id} could not be read \"",
        ("test_a_dba_that_is_down_is_reported_as_unverified_not_as_forged",),
    ),
    (
        CONSTITUTION,
        "verify raises instead of reporting, losing the rest of the finding",
        "    except (secretbox.Tampered, secretbox.NotSealed) as exc:\n"
        "        report.update(intact=False, problems=[f\"the sealed files will not open: {exc}\"])\n"
        "        return report",
        "    except KeyError as exc:\n"
        "        report.update(intact=False, problems=[f\"the sealed files will not open: {exc}\"])\n"
        "        return report",
        ("test_verify_reports_rather_than_raising_when_the_files_will_not_open",),
    ),
    (
        CONSTITUTION,
        "verify always says intact",
        '    report["intact"] = not report["problems"]',
        '    report["intact"] = True',
        ("test_rewriting_the_sealed_text_directly_is_detected",
         "test_an_amendment_with_no_grant_at_all_is_detected",
         "test_altering_an_old_amendment_is_detected"),
    ),
    (
        CONSTITUTION,
        "the text is written before the link, so a crash hides the change",
        "    _write(_path(AMENDMENTS_FILE),\n"
        "           secretbox.seal(json.dumps(existing + [entry]).encode(\"utf-8\"),\n"
        "                          key=key, aad=AMENDMENTS_AAD))\n"
        "    _write(_path(CONSTITUTION_FILE),",
        "    _write(_path(CONSTITUTION_FILE),",
        ("test_with_the_owners_key_an_amendment_lands",
         "test_a_clean_history_verifies"),
    ),
]


if __name__ == "__main__":
    raise SystemExit(harness.run_probes(PROBES, SUITES))
