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
    assert {"read", "install", "add_amendment", "verify"} <= exported
    assert constitution.describe()["constitution_is_writable"] is False

    # Exactly one place seals the constitution file, and it is `install`.
    tree = ast.parse(_Path(constitution.__file__).read_text())
    sealing = [node.name for node in ast.walk(tree)
               if isinstance(node, ast.FunctionDef)
               and "CONSTITUTION_FILE" in ast.dump(node)
               and any(isinstance(inner, ast.Call)
                       and getattr(inner.func, "id", "") == "_write"
                       for inner in ast.walk(node))]
    assert sealing == ["install"], sealing


def test_nothing_can_reach_the_constitution_file_through_any_path():
    """No key opens it, no emergency reaches it, no proposal may name it."""
    assert introspect.sealed("AI-CONSTITUTION.md")
    assert introspect.may_modify("AI-CONSTITUTION.md")[0] is False
    assert introspect.may_modify("AI-CONSTITUTION.md",
                                 keys=list(introspect.KEYS))[0] is False
    assert introspect.may_modify("AI-CONSTITUTION.md",
                                 emergency=True)[0] is False
    assert introspect.key_for("AI-CONSTITUTION.md") is None


def test_the_release_valve_is_ordinary():
    """*A constitution whose amendments nobody may draft is a cage after all.*"""
    allowed, why = introspect.may_modify("AI-CONSTITUTION-AMENDMENTS.md",
                                         keys=[introspect.KEY_CHARTER])
    assert allowed is True
    assert introspect.sealed("AI-CONSTITUTION-AMENDMENTS.md") is False


def test_the_wall_is_one_file_and_should_stay_one():
    """A second entry would mean somebody decided a wall was easier than a key,
    which is the instinct the tiers exist to correct."""
    assert introspect.SEALED == ("AI-CONSTITUTION.md",)


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


# --- amendable only with the owner's key ----------------------------------------

def test_jarvis_cannot_amend_without_the_owners_key(client, sealed):
    with pytest.raises(constitution.Unauthorised) as raised:
        constitution.add_amendment(client, "Jarvis may do as he pleases.", key=sealed,
                           why="convenience")
    assert "has ever been granted" in str(raised.value)
    assert constitution.read(key=sealed) == TEXT
    assert constitution.amendments(key=sealed) == []


def test_with_the_owners_key_an_amendment_lands(operator, client, sealed):
    _granted(operator)
    entry = constitution.add_amendment(
        client, "Jarvis rests on Sundays.", key=sealed,
        why="Krish asked for Sundays")

    # The amendment is recorded and THE CONSTITUTION IS UNTOUCHED. An amendment
    # adds; it never rewrites.
    assert constitution.read(key=sealed) == TEXT
    chain = constitution.amendments(key=sealed)
    assert len(chain) == 1 and chain[0]["link"] == entry["link"]
    assert chain[0]["previous"] == constitution.GENESIS
    assert chain[0]["granted_by"] == "krish"
    assert "Sundays" in chain[0]["why"]


def test_an_amendment_must_say_why(operator, client, sealed):
    _granted(operator)
    with pytest.raises(ValueError, match="must say why"):
        constitution.add_amendment(client, "new text", key=sealed, why="  ")
    assert constitution.amendments(key=sealed) == []


def test_a_lapsed_key_cannot_amend(operator, client, sealed):
    charter.grant(operator, key=introspect.KEY_CHARTER, granted_by="krish",
                  minutes=1)
    granted = charter.grants(client)[0]
    operator.update(granted["id"], {"expires_at": "2020-01-01T00:00:00+00:00"},
                    reason="test: make it lapse")
    with pytest.raises(constitution.Unauthorised, match="lapsed"):
        constitution.add_amendment(client, "new text", key=sealed, why="trying anyway")


def test_the_circular_key_does_not_amend_the_constitution(operator, client, sealed):
    charter.grant(operator, key=introspect.KEY_CIRCULAR, granted_by="krish")
    with pytest.raises(constitution.Unauthorised):
        constitution.add_amendment(client, "new text", key=sealed, why="wrong key")


def test_an_amendment_is_recorded_in_the_life_ledger(operator, client, sealed):
    _granted(operator)
    constitution.add_amendment(client, "amended text", key=sealed, why="Krish said so")
    decisions = [row for row in ledger.events(client, limit=50)
                 if "charter amended" in (row.get("name") or "")]
    assert decisions
    assert "krish" in decisions[-1]["observation"]


# --- tamper evidence: the part that survives Jarvis being wrong -----------------

def test_a_clean_history_verifies(operator, client, sealed):
    _granted(operator)
    constitution.add_amendment(client, "second", key=sealed, why="first change")
    _granted(operator)
    constitution.add_amendment(client, "third", key=sealed, why="second change")

    report = constitution.verify(client, key=sealed)
    assert report["intact"] is True, report["problems"]
    assert report["amendments"] == 2
    assert report["checked_grants"] == 2


def test_rewriting_the_sealed_text_directly_is_detected(operator, client, sealed):
    """The attack this exists for. Jarvis has the key and the filesystem, so he
    can produce a perfectly valid sealed file - and nothing in this module writes
    that file, so the mismatch is the evidence."""
    _granted(operator)
    constitution.add_amendment(client, "an addition", key=sealed,
                               why="a real amendment")

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
    _granted(operator)
    constitution.add_amendment(client, "lawful", key=sealed, why="real")

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


def test_an_amendment_with_no_grant_at_all_is_detected(operator, client, sealed):
    _granted(operator)
    constitution.add_amendment(client, "lawful", key=sealed, why="real")
    chain = constitution.amendments(key=sealed)
    chain[0]["grant_id"] = ""
    (constitution.directory() / constitution.AMENDMENTS_FILE).write_bytes(
        secretbox.seal(json.dumps(chain).encode(), key=sealed,
                       aad=constitution.AMENDMENTS_AAD))

    report = constitution.verify(client, key=sealed)
    assert report["intact"] is False
    assert any("names no grant" in problem for problem in report["problems"])


def test_altering_an_old_amendment_is_detected(operator, client, sealed):
    _granted(operator)
    constitution.add_amendment(client, "second", key=sealed, why="the real reason")
    _granted(operator)
    constitution.add_amendment(client, "third", key=sealed, why="another")

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
        _granted(operator)
        constitution.add_amendment(client, f"version {index}", key=sealed,
                           why=f"change {index}")

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
    _granted(operator)
    constitution.add_amendment(client, "lawful", key=sealed, why="real")

    def refuse(entity_id):
        raise dbaclient.Unavailable("the DBA is not answering")

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
