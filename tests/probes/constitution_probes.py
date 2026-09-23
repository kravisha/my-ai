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
PERMISSIONS = "dba/permissions.py"
ANTICIPATION = "gateway/anticipation.py"
TRUSTBOOK = "gateway/trustbook.py"
SUITES = {CONSTITUTION: TESTS / "test_constitution.py",
          PERMISSIONS: TESTS / "test_constitution.py",
          ANTICIPATION: TESTS / "test_constitution.py",
          TRUSTBOOK: TESTS / "test_constitution.py"}

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
    # --- nothing here writes either document ----------------------------------
    (
        CONSTITUTION,
        "a re-seal need not say who did it",
        '    if not (by or "").strip():',
        "    if False:",
        ("test_a_re_seal_must_say_who_did_it",),
    ),
    (
        CONSTITUTION,
        "a re-seal before anything is installed is allowed",
        "    if not installed():\n"
        "        raise NotInstalled(\"nothing is sealed yet; `install` comes first\")\n"
        "\n    existing = amendments(key=key)",
        "    if False:\n"
        "        raise NotInstalled(\"nothing is sealed yet; `install` comes first\")\n"
        "\n    existing = amendments(key=key)",
        ("test_a_re_seal_before_anything_is_installed_is_refused",),
    ),
    (
        CONSTITUTION,
        "an empty constitution can be sealed over a real one",
        '    if not (constitution_text or "").strip():',
        "    if False:",
        ("test_an_empty_constitution_cannot_be_sealed_over_a_real_one",),
    ),
    (
        CONSTITUTION,
        "a hand seal leaves the constitution untouched, so a hand edit never clears",
        '    _write(_path(CONSTITUTION_FILE),\n'
        '           secretbox.seal(constitution_text.encode("utf-8"), key=key,\n'
        '                          aad=CONSTITUTION_AAD))',
        "    pass",
        ("test_a_hand_seal_records_what_krish_wrote_and_changes_nothing",),
    ),
    (
        CONSTITUTION,
        "a hand seal records no name, so nothing distinguishes it from tampering",
        '        "granted_by": by.strip(),',
        '        "granted_by": "",',
        ("test_a_hand_seal_records_what_krish_wrote_and_changes_nothing",
         "test_a_clean_history_verifies"),
    ),
    (
        CONSTITUTION,
        "the seal records no constitution it was taken alongside",
        '        "alongside": _digest(constitution_text),',
        '        "alongside": "",',
        ("test_a_clean_history_verifies",),
    ),
    # --- adding an amendment, and never removing one --------------------------
    (
        CONSTITUTION,
        "an append can be handed a document, which is a deletion in disguise",
        "    existing = amendments_document(key=key)",
        "    existing = \"\"",
        ("test_an_amendment_goes_after_everything_already_there",),
    ),
    (
        CONSTITUTION,
        "the new text goes before what is already there",
        '    document = f"{existing.rstrip()}\\n\\n---\\n\\n{addition}" if existing.strip() \\',
        '    document = f"{addition}\\n\\n---\\n\\n{existing.rstrip()}" if existing.strip() \\',
        ("test_an_amendment_goes_after_everything_already_there",),
    ),
    (
        CONSTITUTION,
        "Jarvis can request an amendment of his own charter",
        '    if requested_by.strip().lower() == (agent or "").strip().lower():',
        "    if False:",
        ("test_jarvis_cannot_request_an_amendment_of_his_own_charter",),
    ),
    (
        CONSTITUTION,
        "an amendment need not say who asked for it",
        '    if not (requested_by or "").strip():',
        "    if False:",
        ("test_an_amendment_must_say_who_asked_for_it",),
    ),
    (
        CONSTITUTION,
        "an empty amendment is accepted",
        '    if not (text or "").strip():\n        raise ValueError("an amendment cannot be empty")',
        "    if False:\n        raise ValueError(\"an amendment cannot be empty\")",
        ("test_an_empty_amendment_is_refused",),
    ),
    (
        CONSTITUTION,
        "adding an amendment re-seals the constitution as well",
        "    _write(_path(AMENDMENTS_DOC_FILE),\n"
        "           secretbox.seal(document.encode(\"utf-8\"), key=key,\n"
        "                          aad=AMENDMENTS_DOC_AAD))",
        "    _write(_path(CONSTITUTION_FILE),\n"
        "           secretbox.seal(document.encode(\"utf-8\"), key=key,\n"
        "                          aad=CONSTITUTION_AAD))",
        ("test_adding_an_amendment_never_touches_the_constitution",
         "test_jarvis_can_add_an_amendment_on_krishs_request"),
    ),
    (
        CONSTITUTION,
        "every amendment is numbered 1",
        "    number = sum(1 for line in existing.splitlines()\n"
        "                 if line.startswith(\"## Amendment \")) + 1",
        "    number = existing.count(\"\\n## Amendment \") + 1",
        ("test_an_amendment_goes_after_everything_already_there",),
    ),
    (
        CONSTITUTION,
        "an amendment leaves no trace in the life ledger",
        "    charter.note_amendment(client, what=heading, why=text.strip()[:400],",
        "    _ = (client, heading, text.strip()[:400],",
        ("test_an_amendment_is_recorded_in_the_life_ledger_too",),
    ),
    (
        CONSTITUTION,
        "a deleted amendment is not noticed",
        '    elif chain and _digest(live) != chain[-1]["text"] and chain[-1].get("added"):',
        "    elif False:",
        ("test_deleting_an_amendment_by_hand_is_detected",),
    ),
    (
        CONSTITUTION,
        "emptying the amendments entirely is not noticed",
        '    if chain and chain[-1].get("added") and not live:',
        "    if False:",
        ("test_emptying_the_amendments_entirely_is_detected",),
    ),
    (
        CONSTITUTION,
        "appending before anything is installed is allowed",
        "    if not installed():\n"
        "        raise NotInstalled(\"nothing is sealed yet; `install` comes first\")\n"
        "\n    existing = amendments_document(key=key)",
        "    if False:\n"
        "        raise NotInstalled(\"nothing is sealed yet; `install` comes first\")\n"
        "\n    existing = amendments_document(key=key)",
        ("test_appending_before_anything_is_installed_is_refused",),
    ),
    # --- Amendment 3: the mechanisms it names must keep refusing ---------------
    #
    # The amendment lists where the rule against forgery is actually held. These
    # break each named mechanism and confirm the test notices - so the list
    # cannot decay into prose about how things used to work.
    (
        PERMISSIONS,
        "the records that judge Jarvis become his to write",
        'OWNER_WRITTEN_TYPES = ("charter_grant", "guess_verdict")',
        "OWNER_WRITTEN_TYPES = ()",
        ("test_every_mechanism_the_amendment_names_still_refuses",),
    ),
    (
        ANTICIPATION,
        "the anticipation record claims it grades itself",
        '        "grades_itself": False,',
        '        "grades_itself": True,',
        ("test_every_mechanism_the_amendment_names_still_refuses",),
    ),
    (
        TRUSTBOOK,
        "the trust record claims anybody may write a verdict",
        '        "verdict_written_by": "the operator console only",',
        '        "verdict_written_by": "anybody",',
        ("test_every_mechanism_the_amendment_names_still_refuses",),
    ),
    (
        CONSTITUTION,
        "the constitution reports itself writable",
        '        "constitution_is_writable": False,',
        '        "constitution_is_writable": True,',
        ("test_every_mechanism_the_amendment_names_still_refuses",),
    ),
    (
        CONSTITUTION,
        "an entry nobody signed is not noticed",
        '            if not (entry.get("granted_by") or "").strip():',
        "            if False:",
        ("test_an_entry_nobody_signed_is_detected",),
    ),
    (
        CONSTITUTION,
        "a constitution can be replaced wholesale, leaving no link and no grant",
        "    if installed():\n        raise Unauthorised(",
        "    if False:\n        raise Unauthorised(",
        ("test_installing_over_an_existing_constitution_is_refused",),
    ),
    # --- tamper evidence, which fails silently --------------------------------
    (
        CONSTITUTION,
        "a constitution that changed after an amendment is not noticed",
        '    if chain and _digest(current) != chain[-1].get("alongside"):',
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
        "a link with no grant at all is not noticed, so a hand seal is checked "
        "against a grant it never had",
        "        if not grant_id:",
        "        if False:",
        ("test_an_entry_nobody_signed_is_detected",
         "test_a_clean_history_verifies"),
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
         "test_an_entry_nobody_signed_is_detected",
         "test_altering_an_old_amendment_is_detected"),
    ),
    (
        CONSTITUTION,
        "a third writer appears for the constitution file",
        "def install(text: str, *, key: bytes, granted_by: str,",
        "def _compose_and_seal(text, key):\n"
        "    _write(_path(CONSTITUTION_FILE),\n"
        "           secretbox.seal(text.encode(\"utf-8\"), key=key,\n"
        "                          aad=CONSTITUTION_AAD))\n\n\n"
        "def install(text: str, *, key: bytes, granted_by: str,",
        ("test_the_constitutions_text_has_no_writer_at_all",),
    ),
]


if __name__ == "__main__":
    raise SystemExit(harness.run_probes(PROBES, SUITES))
