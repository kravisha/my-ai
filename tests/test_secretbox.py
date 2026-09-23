"""Encrypting something at rest.

Krish, 2026-09-23: *"keep the constitution and the amendments encrypted and
hidden and only visible to superuser and Jarvis and other agents."*

Crypto is the one place in this repository where a passing test is least
reassuring: a round-trip works with the tag ignored, with a fixed nonce, with a
key silently padded to length. So most of these tests are about **refusals**,
and `tests/probes/secretbox_probes.py` breaks each protection in turn.
"""

import os
from collections import Counter

import pytest

from app import secretbox
from app.secretbox import (HEADER, KEY_BYTES, MAGIC, NONCE_BYTES, NotSealed,
                           Tampered, new_key, new_salt, seal, unseal)

AAD = b"charter:constitution:v1"


def test_a_sealed_blob_comes_back_exactly():
    key = new_key()
    for text in (b"", b"x", b"the constitution" * 500, bytes(range(256))):
        assert unseal(seal(text, key=key, aad=AAD), key=key, aad=AAD) == text


def test_the_plaintext_is_not_in_the_ciphertext():
    """The test that would catch the worst possible bug here - a `seal` that
    encodes rather than encrypts."""
    secret = b"KRISH_PRIVATE_CONSTITUTION_MARKER"
    blob = seal(secret * 20, key=new_key(), aad=AAD)
    assert secret not in blob
    assert b"KRISH" not in blob


def test_sealing_the_same_text_twice_gives_different_bytes():
    """A fresh nonce every time. Identical ciphertext for identical plaintext
    leaks that the file did not change, and under GCM a repeated nonce does not
    weaken the encryption, it destroys it."""
    key = new_key()
    blobs = {seal(b"same text", key=key, aad=AAD) for _ in range(20)}
    assert len(blobs) == 20


def test_the_caller_cannot_supply_a_nonce():
    """So that no caller can supply the same one twice."""
    import inspect
    assert "nonce" not in inspect.signature(seal).parameters


def test_a_blob_sealed_under_another_key_is_refused():
    blob = seal(b"secret", key=new_key(), aad=AAD)
    with pytest.raises(Tampered):
        unseal(blob, key=new_key(), aad=AAD)


def test_a_blob_labelled_as_something_else_is_refused():
    """The reason `aad` is required. Without it the constitution and an old
    amendment are interchangeable ciphertext under the same key."""
    key = new_key()
    blob = seal(b"the constitution", key=key, aad=b"charter:constitution:v1")
    with pytest.raises(Tampered):
        unseal(blob, key=key, aad=b"charter:amendment:7")


@pytest.mark.parametrize("position", [len(HEADER), len(HEADER) + NONCE_BYTES, -1])
def test_a_single_flipped_bit_anywhere_is_refused(position):
    key = new_key()
    blob = bytearray(seal(b"the constitution, at some length", key=key, aad=AAD))
    blob[position] ^= 0x01
    with pytest.raises(Tampered):
        unseal(bytes(blob), key=key, aad=AAD)


def test_plaintext_is_not_accepted_as_a_sealed_blob():
    """A store that silently reads unencrypted content is one an attacker can
    downgrade: delete the ciphertext, write plaintext, and it is trusted."""
    with pytest.raises(NotSealed, match="not a sealed blob"):
        unseal(b"We hold these truths to be self-evident", key=new_key(), aad=AAD)


def test_a_future_version_is_named_as_a_re_key_not_a_corruption():
    """The difference decides whether you reach for a backup."""
    key = new_key()
    blob = bytearray(seal(b"text", key=key, aad=AAD))
    blob[len(MAGIC)] = 99
    with pytest.raises(NotSealed, match="re-key"):
        unseal(bytes(blob), key=key, aad=AAD)


def test_a_truncated_blob_is_refused_rather_than_crashing():
    key = new_key()
    blob = seal(b"text", key=key, aad=AAD)
    for cut in range(len(HEADER), len(HEADER) + NONCE_BYTES + 1):
        with pytest.raises((NotSealed, Tampered)):
            unseal(blob[:cut], key=key, aad=AAD)


@pytest.mark.parametrize("key", [b"", b"short", b"x" * 31, b"x" * 33, "a" * 32])
def test_a_key_of_the_wrong_size_is_refused_not_padded(key):
    """Padding or hashing a short key accepts a weak one and reports success."""
    with pytest.raises(ValueError, match="exactly 32 bytes"):
        seal(b"text", key=key, aad=AAD)


@pytest.mark.parametrize("aad", [b"", None])
def test_sealing_without_saying_what_it_is_is_refused(aad):
    with pytest.raises(ValueError, match="additional authenticated data"):
        seal(b"text", key=new_key(), aad=aad)


def test_unsealing_without_saying_what_it_is_is_refused():
    key = new_key()
    blob = seal(b"text", key=key, aad=AAD)
    with pytest.raises(ValueError, match="additional authenticated data"):
        unseal(blob, key=key, aad=b"")


# --- keys ---------------------------------------------------------------------

def test_generated_keys_are_the_right_size_and_not_repeated():
    """32 as a literal, not as `KEY_BYTES`.

    Written against the constant, this passed with the key halved to 128 bits -
    the constant moved and the assertion moved with it. Third time this class of
    mistake has been found by a probe in this repository, so: AES-256, stated as
    a number."""
    assert KEY_BYTES == 32
    keys = [new_key() for _ in range(50)]
    assert all(len(key) == 32 for key in keys)
    assert len(set(keys)) == 50
    assert secretbox.NONCE_BYTES == 12   # AES-GCM's standard.
    assert secretbox.SALT_BYTES == 16


def test_a_passphrase_derives_a_stable_key_for_a_given_salt():
    salt = new_salt()
    assert secretbox.key_from_passphrase("correct horse", salt=salt) == \
        secretbox.key_from_passphrase("correct horse", salt=salt)


def test_the_same_passphrase_under_a_different_salt_is_a_different_key():
    """A fixed salt would make every installation of this project share a key
    space."""
    first = secretbox.key_from_passphrase("correct horse", salt=new_salt())
    second = secretbox.key_from_passphrase("correct horse", salt=new_salt())
    assert first != second


def test_a_salt_is_random_and_long_enough():
    salts = [new_salt() for _ in range(50)]
    assert len(set(salts)) == 50
    assert all(len(salt) >= secretbox.SALT_BYTES for salt in salts)


def test_an_empty_passphrase_is_refused():
    with pytest.raises(ValueError, match="cannot be empty"):
        secretbox.key_from_passphrase("", salt=new_salt())


def test_a_short_salt_is_refused_rather_than_stretched():
    with pytest.raises(ValueError, match="at least"):
        secretbox.key_from_passphrase("passphrase", salt=b"tiny")


def test_a_fingerprint_identifies_a_key_without_revealing_it():
    """It goes in logs, and a log is a file somebody copies."""
    key = new_key()
    printed = secretbox.fingerprint(key)
    assert printed == secretbox.fingerprint(key)
    assert secretbox.fingerprint(new_key()) != printed
    assert key.hex()[:16] not in printed
    assert printed not in key.hex()


def test_ciphertext_does_not_look_like_the_text_it_came_from():
    """A weak check, and worth having: byte-frequency of a long run of one
    character survives encoding and does not survive encryption."""
    blob = seal(b"A" * 5000, key=new_key(), aad=AAD)
    counts = Counter(blob[len(HEADER) + NONCE_BYTES:])
    assert max(counts.values()) < 100


def test_describe_is_honest_about_the_limit():
    """A module named `secretbox` invites the assumption that it solves more
    than it does."""
    described = secretbox.describe()
    assert described["cipher"] == "AES-256-GCM"
    assert described["aad_required"] is True
    assert "code running as Jarvis" in described["does_not_protect_against"]
