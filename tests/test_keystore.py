"""Where the constitution's key lives.

The open question from `docs/JARVIS_PERSISTENCE.md` §3c-quater, answered by
Krish's own arrangement rather than by preference: `keep-jarvis-up.ps1` restarts
Jarvis with nobody at the keyboard, so a key that needs a person typing it is a
key he stops having exactly when he is away.

Four claims, and the tests are grouped by them:

1. Every state the keystore can be in is reachable and named, and each one says
   what to do rather than that something is wrong.
2. There is no fallback when DPAPI is missing. A key in a plain file would be
   weaker than the seal it opens.
3. A missing escrow does not stop Jarvis, and is never stopped being reported.
4. The escrow round-trips, is salted per installation, and a wrong passphrase is
   reported as what the cryptography actually says.

Probed by `tests/probes/keystore_probes.py`.
"""

import pytest

from app import dpapi, keystore, secretbox
from app.keystore import (ABSENT, NO_ESCROW, READY, UNREADABLE, Reading,
                          WeakPassphrase, verdict)

GOOD = "a passphrase long enough"


def reading(**kwargs):
    """A machine where everything is in order, before the test breaks one thing."""
    base = dict(windows=True, dpapi=True, key_present=True, key_opens=True,
                escrow_present=True, escrow_fingerprint="aa:bb",
                key_fingerprint="aa:bb")
    base.update(kwargs)
    return Reading(**base)


# --- 1. every state is reachable and says what to do ------------------------

def test_a_machine_in_order_is_ready():
    said = verdict(reading())
    assert said.state == READY
    assert said.workable
    assert said.escrow_matches
    assert said.next_step == "nothing"


def test_a_machine_with_no_key_yet_says_how_to_make_one():
    said = verdict(reading(key_present=False))
    assert said.state == ABSENT
    assert not said.workable
    assert "--make-key" in said.next_step


def test_a_key_this_account_cannot_open_is_named_as_that():
    """The shape of a rebuilt profile or a copied folder, and it is not the same
    problem as no key at all - one is restored, the other is created."""
    said = verdict(reading(key_opens=False))
    assert said.state == UNREADABLE
    assert not said.workable
    assert "--restore-key" in said.next_step
    assert "different account" in said.because


def test_a_key_with_no_escrow_still_runs_but_is_reported():
    said = verdict(reading(escrow_present=False))
    assert said.state == NO_ESCROW
    assert said.workable, "a missing backup must not lock him out of the key"
    assert not said.escrow_matches
    assert "--write-escrow" in said.next_step


def test_a_stale_escrow_is_reported_as_no_escrow_and_says_why():
    """A backup that restores the wrong key is worse than no backup, because it
    is mistaken for one."""
    said = verdict(reading(escrow_fingerprint="cc:dd"))
    assert said.state == NO_ESCROW
    assert "different key" in said.because


def test_an_unchecked_escrow_is_not_reported_as_a_mismatch():
    """`None` means nobody looked, which is not the same as "it does not match".
    Reporting it as stale would send him to rewrite a good backup."""
    assert verdict(reading(escrow_fingerprint=None)).state == READY
    assert verdict(reading(key_fingerprint=None)).state == READY


def test_every_state_the_module_names_is_one_some_reading_produces():
    """A state nothing can reach is a branch nobody has tested."""
    produced = {
        verdict(reading()).state,
        verdict(reading(key_present=False)).state,
        verdict(reading(key_opens=False)).state,
        verdict(reading(escrow_present=False)).state,
        verdict(reading(windows=False, dpapi=False)).state,
    }
    assert produced == set(keystore.describe()["states"])


# --- 2. there is no weaker fallback -----------------------------------------

def test_a_machine_without_dpapi_is_refused_rather_than_given_a_plain_file():
    said = verdict(reading(windows=False, dpapi=False))
    assert said.state == ABSENT
    assert not said.workable
    assert "Nothing here is a fallback" in said.next_step
    assert "environment variable" in said.next_step


def test_windows_without_dpapi_is_also_refused():
    """Not a hypothetical worth ignoring: the check is two facts, and a machine
    that answers yes to one and no to the other must not fall between them."""
    assert verdict(reading(dpapi=False)).state == ABSENT
    assert verdict(reading(windows=False)).state == ABSENT


def test_the_adapter_refuses_rather_than_returning_plaintext_off_windows():
    assert dpapi.available() is False or dpapi.available() is True
    if not dpapi.available():
        with pytest.raises(dpapi.Unavailable):
            dpapi.protect(b"secret")
        with pytest.raises(dpapi.Unavailable):
            dpapi.unprotect(b"secret")


def test_the_adapter_holds_no_judgement():
    """The split this repository keeps: a branch inside an adapter is a branch
    that cannot be tested on the machine it is written on."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(dpapi))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in ("protect",
                                                               "unprotect"):
            tests = [one for one in ast.walk(node) if isinstance(one, ast.If)]
            assert len(tests) <= 2, (
                f"dpapi.{node.name} has {len(tests)} branches; the decisions "
                f"belong in keystore, where they can be tested")


def test_describe_says_what_was_decided_and_what_it_does_not_buy():
    said = keystore.describe()
    assert said["protects_against_jarvis"] is False
    assert said["runs_without_an_escrow"] is True
    assert "DPAPI" in said["where"]
    assert "keyboard" in said["why_not_a_passphrase"]


# --- 3 & 4. the escrow ------------------------------------------------------

def test_the_escrow_gives_the_key_back():
    key = secretbox.new_key()
    assert keystore.unwrap_escrow(
        keystore.wrap_for_escrow(key, passphrase=GOOD), passphrase=GOOD) == key


def test_two_escrows_of_one_key_differ():
    """A salt fixed in the source would mean every installation of this shares a
    key space - the finding the secretbox probes already hold for the sealing."""
    key = secretbox.new_key()
    first = keystore.wrap_for_escrow(key, passphrase=GOOD)
    second = keystore.wrap_for_escrow(key, passphrase=GOOD)
    assert first != second
    assert first[:secretbox.SALT_BYTES] != second[:secretbox.SALT_BYTES]
    assert keystore.unwrap_escrow(second, passphrase=GOOD) == key


def test_a_wrong_passphrase_is_reported_as_what_the_cryptography_says():
    """AES-GCM cannot tell a typo from an edit, and inventing that distinction
    would be inventing a fact."""
    blob = keystore.wrap_for_escrow(secretbox.new_key(), passphrase=GOOD)
    with pytest.raises(secretbox.Tampered):
        keystore.unwrap_escrow(blob, passphrase="a different passphrase")


def test_an_edited_escrow_does_not_open():
    key = secretbox.new_key()
    blob = bytearray(keystore.wrap_for_escrow(key, passphrase=GOOD))
    blob[-1] ^= 0x01
    with pytest.raises(secretbox.Tampered):
        keystore.unwrap_escrow(bytes(blob), passphrase=GOOD)


def test_an_escrow_with_its_salt_swapped_does_not_open():
    """The salt is not authenticated by the seal it precedes, so this is the one
    edit that could plausibly go unnoticed."""
    key = secretbox.new_key()
    blob = keystore.wrap_for_escrow(key, passphrase=GOOD)
    swapped = secretbox.new_salt() + blob[secretbox.SALT_BYTES:]
    with pytest.raises(secretbox.Tampered):
        keystore.unwrap_escrow(swapped, passphrase=GOOD)


def test_a_truncated_escrow_says_so_rather_than_crashing():
    with pytest.raises(secretbox.NotSealed):
        keystore.unwrap_escrow(b"short", passphrase=GOOD)


def test_a_short_passphrase_is_refused_when_writing_the_escrow():
    with pytest.raises(WeakPassphrase):
        keystore.wrap_for_escrow(secretbox.new_key(), passphrase="hunter2")


def test_the_escrow_passphrase_minimum_is_twelve():
    """Written as a literal: a test saying `len(p) >= MIN` holds at every value
    of MIN, including one."""
    assert keystore.ESCROW_PASSPHRASE_MIN == 12
    key = secretbox.new_key()
    with pytest.raises(WeakPassphrase):
        keystore.wrap_for_escrow(key, passphrase="x" * 11)
    assert keystore.wrap_for_escrow(key, passphrase="x" * 12)


def test_the_key_and_the_escrow_are_not_in_the_repository():
    """A key checked in next to the thing it opens is not a key."""
    from pathlib import Path

    directory = Path("/some/state/folder")
    assert keystore.key_path(directory).parent == directory
    assert keystore.escrow_path(directory).parent == directory
    assert keystore.key_path(directory) != keystore.escrow_path(directory)
    for name in (keystore.KEY_FILE, keystore.ESCROW_FILE):
        assert not (Path(__file__).resolve().parent.parent / name).exists()
