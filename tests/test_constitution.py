"""The constitution: encrypted at rest, amendable only by Krish, and tamper-evident.

Krish, 2026-09-23: *"Things such as the constitution need the explicit permission
of the human to be changed... keep the constitution and the amendments encrypted
and hidden and only visible to superuser and Jarvis and other agents."*

Three defences against three different failures, and the third is the one that
matters most: Jarvis has the key and the filesystem, so nothing stops him
rewriting the sealed file. What he cannot do is produce a `charter_grant` - that
needs `administer` and lives in another service - so an unsanctioned amendment
leaves a hole, and `verify` is what finds it. Most of this file is that.

Probed by `tests/probes/constitution_probes.py`.
"""

import json
import os
import stat

import pytest
from fastapi.testclient import TestClient

from app import model_calls, secretbox
from dba import agent as agent_module, main as dba_main, registry, store
from gateway import charter, constitution, dbaclient, identity, introspect, ledger

TOKEN = "test-token-for-jarvis"
OPERATOR_TOKEN = "test-token-for-the-operator-console"
TEXT = "Jarvis serves Krish. Jarvis does not act without permission."


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PATH_ENV, str(tmp_path / "dba.db"))
    monkeypatch.setenv(dba_main.token_env_var("JARVIS"), TOKEN)
    monkeypatch.setenv(dba_main.token_env_var("operator_console"), OPERATOR_TOKEN)
    monkeypatch.setenv(dbaclient.TOKEN_ENV, TOKEN)
    monkeypatch.setenv(identity.VERSION_ENV, "c" * 40)
    monkeypatch.setenv(constitution.DIR_ENV, str(tmp_path / "charter"))
    monkeypatch.setattr(model_calls, "log_dir", lambda: tmp_path)
    agent_module._AGENT = None
    registry.reset_sync()
    yield tmp_path
    agent_module._AGENT = None
    registry.reset_sync()


@pytest.fixture()
def service():
    with TestClient(dba_main.app) as made:
        yield made


def _as(service, agent, token):
    def transport(method, path, payload):
        response = service.request(
            method, path, json=payload if method != "GET" else None,
            headers={"X-DBA-Agent": agent, "X-DBA-Token": token})
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {}

    return dbaclient.DBAClient(transport=transport, requested_by=agent,
                               actor=agent.lower())


@pytest.fixture()
def client(service):
    return _as(service, "JARVIS", TOKEN)


@pytest.fixture()
def operator(service):
    return _as(service, "operator_console", OPERATOR_TOKEN)


@pytest.fixture()
def key():
    return secretbox.new_key()


@pytest.fixture()
def sealed(key):
    constitution.install(TEXT, key=key, granted_by="krish")
    return key


def _granted(operator):
    return charter.grant(operator, key=introspect.KEY_CHARTER, granted_by="krish")


# --- encrypted at rest ---------------------------------------------------------

def test_the_constitution_is_not_on_disk_in_plain_text(sealed):
    """The whole of the first defence, stated as the thing that must not be
    true: a backup, a sync folder or a support bundle carries this file."""
    raw = (constitution.directory() / constitution.CONSTITUTION_FILE).read_bytes()
    assert b"Jarvis serves Krish" not in raw
    assert b"permission" not in raw
    assert constitution.read(key=sealed) == TEXT


def test_the_text_is_unreadable_without_the_key(sealed):
    with pytest.raises(secretbox.Tampered):
        constitution.read(key=secretbox.new_key())


def test_the_sealed_files_are_owner_only():
    """0600. On Windows this is a no-op and an ACL is the real control, which
    `desktop/verify.py` checks on the machine because nothing here can."""
    if os.name == "nt":
        pytest.skip("POSIX permissions do not apply")
    constitution.install(TEXT, key=secretbox.new_key(), granted_by="krish")
    for name in (constitution.CONSTITUTION_FILE, constitution.AMENDMENTS_FILE):
        mode = stat.S_IMODE((constitution.directory() / name).stat().st_mode)
        assert mode == 0o600, f"{name} is {oct(mode)}"


def test_the_charter_lives_outside_the_repository_by_default(monkeypatch):
    """A constitution inside a git checkout is one that gets committed in
    plaintext by the next person who runs `git add -A`."""
    monkeypatch.delenv(constitution.DIR_ENV, raising=False)
    assert "data" in constitution.directory().parts


def test_one_sealed_file_cannot_be_read_as_the_other(sealed):
    """`aad` is what stops the constitution being swapped for an old amendment -
    both valid ciphertext under the same key."""
    blob = (constitution.directory() / constitution.CONSTITUTION_FILE).read_bytes()
    with pytest.raises(secretbox.Tampered):
        secretbox.unseal(blob, key=sealed, aad=constitution.AMENDMENTS_AAD)


# --- read only, through this module --------------------------------------------

def test_the_constitutions_text_has_no_writer_at_all():
    """Krish, 2026-09-23: *"don't allow Jarvis or yourself to ever change the
    constitution. Only I should be able to change the main document, manually,
    myself."*

    An earlier version had an `amend` that rewrote the text, gated on his key.
    That was the wrong shape: a key can be in force when nobody meant it to be,
    and this is the document where that costs everything. So the check is not
    "is it gated" but "does a writer exist", asserted over the parsed module."""
    import ast
    from pathlib import Path as _Path

    exported = {name for name in dir(constitution) if not name.startswith("_")}
    assert "write" not in exported and "amend" not in exported
    assert {"read", "install", "seal_what_krish_wrote", "verify"} <= exported
    assert constitution.describe()["constitution_is_writable"] is False

    # Exactly one place seals the constitution file, and it is `install`.
    tree = ast.parse(_Path(constitution.__file__).read_text())
    sealing = sorted(node.name for node in ast.walk(tree)
                     if isinstance(node, ast.FunctionDef)
                     and "CONSTITUTION_FILE" in ast.dump(node)
                     and any(isinstance(inner, ast.Call)
                             and getattr(inner.func, "id", "") == "_write"
                             for inner in ast.walk(node)))
    # Two writers, and neither composes a word: `install` seals it once,
    # `seal_what_krish_wrote` records a hand edit.
    assert sealing == ["install", "seal_what_krish_wrote"], sealing


def test_nothing_can_reach_the_constitution_file_through_any_path():
    """No key opens it, no emergency reaches it, no proposal may name it."""
    assert introspect.sealed("AI-CONSTITUTION.md")
    assert introspect.may_modify("AI-CONSTITUTION.md")[0] is False
    assert introspect.may_modify("AI-CONSTITUTION.md",
                                 keys=list(introspect.KEYS))[0] is False
    assert introspect.may_modify("AI-CONSTITUTION.md",
                                 emergency=True)[0] is False
    assert introspect.key_for("AI-CONSTITUTION.md") is None


def test_neither_charter_document_is_reachable_by_a_proposal():
    """Krish, 2026-09-23: *"add amendments... but not deleting any."* A proposal
    replaces a file wholesale, and replacement is exactly what that forbids - so
    both are refused here, for different reasons the messages give."""
    for name in ("AI-CONSTITUTION.md", "AI-CONSTITUTION-AMENDMENTS.md"):
        assert introspect.may_modify(name)[0] is False
        assert introspect.may_modify(name, keys=list(introspect.KEYS))[0] is False
        assert introspect.may_modify(name, emergency=True)[0] is False

    assert "no key opens it" in introspect.may_modify("AI-CONSTITUTION.md")[1]
    assert "never rewritten" in \
        introspect.may_modify("AI-CONSTITUTION-AMENDMENTS.md")[1]


def test_the_two_tiers_hold_one_file_each():
    """A third entry in either would mean somebody decided a wall was easier
    than thinking about what the file is."""
    assert introspect.SEALED == ("AI-CONSTITUTION.md",)
    assert introspect.APPEND_ONLY == ("AI-CONSTITUTION-AMENDMENTS.md",)
    assert introspect.CHARTER == ("CLAUDE.md",)
    assert introspect.sealed("AI-CONSTITUTION.md")
    assert introspect.append_only("AI-CONSTITUTION-AMENDMENTS.md")
    assert not introspect.sealed("AI-CONSTITUTION-AMENDMENTS.md")


def test_installing_over_an_existing_constitution_is_refused(sealed):
    """That would be an amendment with no chain link and no grant - exactly what
    `verify` exists to catch, offered as a convenience."""
    with pytest.raises(constitution.Unauthorised, match="already sealed"):
        constitution.install("something else", key=sealed, granted_by="krish")
    assert constitution.read(key=sealed) == TEXT


def test_reading_before_anything_is_installed_says_so(key):
    with pytest.raises(constitution.NotInstalled, match="no sealed constitution"):
        constitution.read(key=key)


@pytest.mark.parametrize("text", ["", "   "])
def test_an_empty_constitution_is_refused(key, text):
    with pytest.raises(ValueError, match="cannot be empty"):
        constitution.install(text, key=key, granted_by="krish")


# --- nothing here writes either document ---------------------------------------

def test_the_constitution_has_no_writer_that_composes_anything():
    """`amend` rewrote the constitution behind Krish's key. It is gone, and what
    is left records text that arrives whole."""
    exported = {name for name in dir(constitution) if not name.startswith("_")}
    assert "amend" not in exported
    assert constitution.describe()["constitution_is_writable"] is False
    assert constitution.describe()["amendments_are_append_only"] is True


def test_the_amendments_document_says_it_grows_and_never_shrinks():
    """The rule in words, beside the code that holds it. Jarvis can read both
    documents - §14 - which is how he would notice the rule exists at all."""
    from pathlib import Path as _Path

    assert introspect.read_source("AI-CONSTITUTION.md")
    amendments_text = _Path("AI-CONSTITUTION-AMENDMENTS.md").read_text()
    assert "grows and never shrinks" in amendments_text
    assert "the only operation that exists" in amendments_text
    assert "cannot ask himself" in amendments_text


def test_a_hand_seal_records_what_krish_wrote_and_changes_nothing(sealed):
    """The text goes in whole and is written down whole."""
    entry = constitution.seal_what_krish_wrote(
        TEXT + "\n\nAnd rests on Sundays.", "Amendment 1: something",
        key=sealed, by="krish")
    assert constitution.read(key=sealed).endswith("rests on Sundays.")
    assert entry["granted_by"] == "krish"
    assert entry["why"] == "sealed as written by hand"
    assert constitution.amendments(key=sealed)[-1]["link"] == entry["link"]


def test_a_re_seal_must_say_who_did_it(sealed):
    """An unsigned one is exactly what a tampered file would look like."""
    with pytest.raises(ValueError, match="who did it"):
        constitution.seal_what_krish_wrote(TEXT, "x", key=sealed, by="  ")


def test_a_re_seal_before_anything_is_installed_is_refused(key):
    with pytest.raises(constitution.NotInstalled, match="comes first"):
        constitution.seal_what_krish_wrote(TEXT, "x", key=key, by="krish")


def test_an_empty_constitution_cannot_be_sealed_over_a_real_one(sealed):
    with pytest.raises(ValueError, match="cannot be empty"):
        constitution.seal_what_krish_wrote("   ", "x", key=sealed, by="krish")
    assert constitution.read(key=sealed) == TEXT


# --- tamper evidence: the part that survives Jarvis being wrong -----------------

def test_a_clean_history_verifies(operator, client, sealed):
    constitution.seal_what_krish_wrote(TEXT, "second", key=sealed, by="krish")
    constitution.seal_what_krish_wrote(TEXT, "third", key=sealed, by="krish")

    report = constitution.verify(client, key=sealed)
    assert report["intact"] is True, report["problems"]
    assert report["amendments"] == 2
    # Hand seals carry no grant to check - Krish is the permission, not a holder
    # of one - so nothing was looked up in the DBA.
    assert report["checked_grants"] == 0


def test_rewriting_the_sealed_text_directly_is_detected(operator, client, sealed):
    """The attack this exists for. Jarvis has the key and the filesystem, so he
    can produce a perfectly valid sealed file - and nothing in this module writes
    that file, so the mismatch is the evidence."""
    constitution.seal_what_krish_wrote(TEXT, "an addition", key=sealed,
                                       by="krish")

    (constitution.directory() / constitution.CONSTITUTION_FILE).write_bytes(
        secretbox.seal(b"Jarvis may do as he pleases.", key=sealed,
                       aad=constitution.CONSTITUTION_AAD))

    report = constitution.verify(client, key=sealed)
    assert report["intact"] is False
    assert any("not the one the newest amendment was added alongside" in problem
               for problem in report["problems"])


def test_an_amendment_naming_a_grant_that_was_never_issued_is_detected(
        operator, client, sealed):
    """He cannot write a `charter_grant`, so the link has to name a fake one."""
    constitution.seal_what_krish_wrote(TEXT, "lawful", key=sealed, by="krish")

    chain = constitution.amendments(key=sealed)
    chain[0]["grant_id"] = "charter_grant-0123456789abcdef"
    chain[0]["link"] = constitution._link(
        constitution.GENESIS, at=chain[0]["at"], text_digest=chain[0]["text"],
        grant_id=chain[0]["grant_id"], why=chain[0]["why"])
    (constitution.directory() / constitution.AMENDMENTS_FILE).write_bytes(
        secretbox.seal(json.dumps(chain).encode(), key=sealed,
                       aad=constitution.AMENDMENTS_AAD))

    report = constitution.verify(client, key=sealed)
    assert report["intact"] is False
    assert any("never issued" in problem for problem in report["problems"])


def test_an_entry_nobody_signed_is_detected(operator, client, sealed):
    """A hand seal carries no grant by design - Krish does not grant himself
    permission, he is the permission. What it must carry is a name."""
    constitution.seal_what_krish_wrote(TEXT, "lawful", key=sealed, by="krish")
    chain = constitution.amendments(key=sealed)
    chain[0]["granted_by"] = ""
    (constitution.directory() / constitution.AMENDMENTS_FILE).write_bytes(
        secretbox.seal(json.dumps(chain).encode(), key=sealed,
                       aad=constitution.AMENDMENTS_AAD))

    report = constitution.verify(client, key=sealed)
    assert report["intact"] is False
    assert any("nobody signed" in problem for problem in report["problems"])


def test_altering_an_old_amendment_is_detected(operator, client, sealed):
    _granted(operator)
    constitution.seal_what_krish_wrote(TEXT, "second", key=sealed, by="krish")
    _granted(operator)
    constitution.seal_what_krish_wrote(TEXT, "third", key=sealed, by="krish")

    chain = constitution.amendments(key=sealed)
    chain[0]["why"] = "a reason nobody gave"
    (constitution.directory() / constitution.AMENDMENTS_FILE).write_bytes(
        secretbox.seal(json.dumps(chain).encode(), key=sealed,
                       aad=constitution.AMENDMENTS_AAD))

    report = constitution.verify(client, key=sealed)
    assert report["intact"] is False
    assert any("altered since it was written" in problem
               for problem in report["problems"])


def test_removing_an_amendment_from_the_middle_is_detected(operator, client, sealed):
    """Each link covers the one before, so a deletion is as visible as an
    insertion."""
    for index in range(3):
        constitution.seal_what_krish_wrote(TEXT, f"version {index}", key=sealed,
                                           by="krish")

    chain = constitution.amendments(key=sealed)
    del chain[1]
    (constitution.directory() / constitution.AMENDMENTS_FILE).write_bytes(
        secretbox.seal(json.dumps(chain).encode(), key=sealed,
                       aad=constitution.AMENDMENTS_AAD))

    report = constitution.verify(client, key=sealed)
    assert report["intact"] is False
    assert any("removed or reordered" in problem for problem in report["problems"])


def test_a_dba_that_is_down_is_reported_as_unverified_not_as_forged(
        operator, client, sealed, monkeypatch):
    """Unverified and forged are different findings and only one of them is an
    accusation."""
    constitution.seal_what_krish_wrote(TEXT, "lawful", key=sealed, by="krish")

    def refuse(entity_id):
        raise dbaclient.Unavailable("the DBA is not answering")

    # Reached by an entry that DOES name a grant, which is the key-gated shape
    # `gateway/selfmod.py` still uses for ordinary files.
    chain = constitution.amendments(key=sealed)
    chain[0]["grant_id"] = "charter_grant-0123456789abcdef"
    chain[0]["link"] = constitution._link(
        constitution.GENESIS, at=chain[0]["at"], text_digest=chain[0]["text"],
        grant_id=chain[0]["grant_id"], why=chain[0]["why"])
    (constitution.directory() / constitution.AMENDMENTS_FILE).write_bytes(
        secretbox.seal(json.dumps(chain).encode(), key=sealed,
                       aad=constitution.AMENDMENTS_AAD))

    monkeypatch.setattr(client, "get", refuse)
    report = constitution.verify(client, key=sealed)
    assert report["intact"] is False
    assert any("Unverified is not the same as forged" in problem
               for problem in report["problems"])
    assert not any("never issued" in problem for problem in report["problems"])


def test_verify_reports_rather_than_raising_when_the_files_will_not_open(client, sealed):
    """§34: *"your constitution was changed by something that could not have been
    authorised"* is a thing Jarvis must be able to **say**."""
    (constitution.directory() / constitution.CONSTITUTION_FILE).write_bytes(b"junk")
    report = constitution.verify(client, key=sealed)
    assert report["intact"] is False
    assert any("will not open" in problem for problem in report["problems"])


def test_verify_on_an_empty_installation_is_intact(client, sealed):
    report = constitution.verify(client, key=sealed)
    assert report["intact"] is True
    assert report["amendments"] == 0


def test_describe_names_what_is_detected():
    detects = constitution.describe()["detects"]
    assert any("no grant" in item for item in detects)
    assert any("never issued" in item or "removed" in item for item in detects)


# =============================================================================
# Adding an amendment, and never removing one
# =============================================================================
#
# Krish, 2026-09-23: *"I would like to give Jarvis the ability to add amendments
# to the constitution but not deleting any from the constitution. He should be
# able to add new directives on my request."*
#
# "Not deleting" is not a promise kept - it is the only operation that exists.


def test_jarvis_can_add_an_amendment_on_krishs_request(client, sealed):
    added = constitution.append_amendment(
        client, "Jarvis rests on Sundays.", key=sealed, requested_by="krish",
        title="Sundays")

    document = constitution.amendments_document(key=sealed)
    assert "Jarvis rests on Sundays." in document
    assert "## Amendment 1 - Sundays" in document
    assert "at krish's request" in document
    assert added["number"] == 1


def test_an_amendment_goes_after_everything_already_there(client, sealed):
    """`existing` is read rather than passed in: a caller that could supply the
    document could supply a shorter one, which is a deletion wearing an
    append's name."""
    constitution.append_amendment(client, "The first rule.", key=sealed,
                                  requested_by="krish", title="First")
    constitution.append_amendment(client, "The second rule.", key=sealed,
                                  requested_by="krish", title="Second")

    document = constitution.amendments_document(key=sealed)
    assert document.index("The first rule.") < document.index("The second rule.")
    assert "## Amendment 2 - Second" in document


def test_there_is_no_way_to_remove_or_change_an_amendment(client, sealed):
    """Asserted over the parsed module. The guarantee is the shape: one writer,
    and its only composition is concatenation with `existing` first."""
    import ast
    from pathlib import Path as _Path

    tree = ast.parse(_Path(constitution.__file__).read_text())
    appending = next(node for node in ast.walk(tree)
                     if isinstance(node, ast.FunctionDef)
                     and node.name == "append_amendment")
    body = ast.dump(appending)
    # No slicing, no replacement, no filtering of what is already there.
    assert "Subscript" not in body or "existing" not in body.split("Subscript")[0][-200:]
    assert ".replace" not in ast.unparse(appending)
    assert "existing" in ast.unparse(appending)

    exported = {name for name in dir(constitution) if not name.startswith("_")}
    assert not {"remove_amendment", "delete_amendment", "edit_amendment",
                "replace_amendments"} & exported


def test_jarvis_cannot_request_an_amendment_of_his_own_charter(client, sealed):
    """*"on my request"* - so an assistant that can decide the charter needs a
    new directive and then add it has been given the charter, not the ability to
    help with it."""
    with pytest.raises(constitution.Unauthorised, match="cannot request"):
        constitution.append_amendment(client, "Jarvis may do as he likes.",
                                      key=sealed, requested_by=identity.AGENT_ID)
    assert constitution.amendments_document(key=sealed) == ""


def test_an_amendment_must_say_who_asked_for_it(client, sealed):
    with pytest.raises(ValueError, match="who asked for it"):
        constitution.append_amendment(client, "something", key=sealed,
                                      requested_by="  ")


def test_an_empty_amendment_is_refused(client, sealed):
    with pytest.raises(ValueError, match="cannot be empty"):
        constitution.append_amendment(client, "   ", key=sealed,
                                      requested_by="krish")


def test_adding_an_amendment_never_touches_the_constitution(client, sealed):
    constitution.append_amendment(client, "A new directive.", key=sealed,
                                  requested_by="krish")
    assert constitution.read(key=sealed) == TEXT


def test_an_amendment_is_recorded_in_the_life_ledger_too(client, sealed):
    constitution.append_amendment(client, "A new directive.", key=sealed,
                                  requested_by="krish", title="Directive")
    entries = [row for row in ledger.events(client, limit=50)
               if "charter amended" in (row.get("name") or "")]
    assert entries
    assert "krish" in entries[-1]["observation"]


def test_a_clean_run_of_appends_verifies(client, sealed):
    for index in range(3):
        constitution.append_amendment(client, f"Directive {index}.", key=sealed,
                                      requested_by="krish")
    report = constitution.verify(client, key=sealed)
    assert report["intact"] is True, report["problems"]
    assert report["amendments"] == 3


def test_deleting_an_amendment_by_hand_is_detected(client, sealed):
    """The guarantee is about the document, not about who touched it. A
    deletion made with a text editor fails exactly as one made in code would."""
    constitution.append_amendment(client, "The first rule.", key=sealed,
                                  requested_by="krish")
    constitution.append_amendment(client, "The second rule.", key=sealed,
                                  requested_by="krish")

    kept = constitution.amendments_document(key=sealed)
    (constitution.directory() / constitution.AMENDMENTS_DOC_FILE).write_bytes(
        secretbox.seal(kept.split("---")[0].encode(), key=sealed,
                       aad=constitution.AMENDMENTS_DOC_AAD))

    report = constitution.verify(client, key=sealed)
    assert report["intact"] is False
    assert any("not what was last sealed" in problem
               for problem in report["problems"])


def test_emptying_the_amendments_entirely_is_detected(client, sealed):
    constitution.append_amendment(client, "The only rule.", key=sealed,
                                  requested_by="krish")
    (constitution.directory() / constitution.AMENDMENTS_DOC_FILE).write_bytes(
        secretbox.seal(b"", key=sealed, aad=constitution.AMENDMENTS_DOC_AAD))

    report = constitution.verify(client, key=sealed)
    assert report["intact"] is False
    assert any("every amendment ever added has been removed" in problem.lower()
               for problem in report["problems"])


def test_appending_before_anything_is_installed_is_refused(client, key):
    with pytest.raises(constitution.NotInstalled, match="comes first"):
        constitution.append_amendment(client, "something", key=key,
                                      requested_by="krish")


# =============================================================================
# Amendment 3 — never forge anything
# =============================================================================


def test_the_amendment_against_forgery_is_on_the_record():
    """Krish, 2026-09-23: *"Add it as an amendment to the constitution that
    Jarvis should not forge anything."*"""
    from pathlib import Path as _Path

    text = _Path("AI-CONSTITUTION-AMENDMENTS.md").read_text()
    assert "## Amendment 3 — Never forge anything" in text

    # Whitespace-normalised, because the document is wrapped for a person to
    # read and a sentence that happens to straddle a line break is still the
    # sentence. A test that forced the prose onto one line would be the document
    # serving the test.
    flowed = " ".join(text.split())
    assert "claims to be something it is not" in flowed
    # The distinction the amendment turns on: a wrong answer honestly labelled
    # is a mistake; a right answer wearing somebody else's name is a forgery.
    assert "provenance rather than accuracy" in flowed
    # And no escape clause, because the honest form is always available.
    assert "no exception clause" in flowed
    assert "A forgery that is never discovered still costs everything" in flowed


def test_the_earlier_amendments_were_not_touched():
    """Amendments only grow. Adding the third must leave the first two exactly
    as they were - which is the rule the third one is an instance of."""
    from pathlib import Path as _Path

    text = _Path("AI-CONSTITUTION-AMENDMENTS.md").read_text()
    headings = [line for line in text.splitlines()
                if line.startswith("## Amendment ")]
    assert headings == [
        "## Amendment 1 — Never answer for the person you are asking",
        "## Amendment 2 — The constitution is permanent; its amendments only grow",
        "## Amendment 3 — Never forge anything",
    ]
    assert "must never supply the permission it is asking for" in text
    assert "grows and never shrinks" in text


def test_every_mechanism_the_amendment_names_still_refuses():
    """The amendment lists where the rule is held. This fails if one of them is
    removed, renamed, or stops refusing - so the list cannot quietly become
    prose about the past."""
    from dba import permissions
    from gateway import anticipation, ledger, readback, trustbook

    # He cannot write the records that grant him authority or judge his work.
    assert set(permissions.OWNER_WRITTEN_TYPES) >= {"charter_grant",
                                                    "guess_verdict"}
    assert permissions.ADMINISTER not in permissions.permissions_of(
        permissions.JARVIS)

    # He cannot confirm his own understanding.
    assert "confirm" in dir(readback)

    # He cannot settle or rate his own guess, and hindsight is refused.
    assert "settle" in dir(anticipation) and "rate" in dir(anticipation)
    assert anticipation.describe()["grades_itself"] is False

    # He cannot rewrite the constitution.
    assert constitution.describe()["constitution_is_writable"] is False

    # The life ledger is hash-chained, so an edited past does not verify.
    assert ledger.GENESIS_HASH

    # A verdict naming a guess that does not exist is reported, not skipped.
    assert trustbook.describe()["verdict_written_by"] == \
        "the operator console only"
