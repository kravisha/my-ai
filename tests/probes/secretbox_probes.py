"""Mutations that `tests/test_secretbox.py` must notice.

Crypto is where a green suite reassures least. A round-trip passes with the
authentication tag ignored, with a fixed nonce, with a short key quietly hashed
up to length - every one of those is a total failure that looks exactly like
success from the outside. So these probes mostly *weaken* the primitive and check
that something objects.

Run it directly:

    python tests/probes/secretbox_probes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

TESTS = Path(__file__).resolve().parents[1]

SECRETBOX = "app/secretbox.py"
SUITES = {SECRETBOX: TESTS / "test_secretbox.py"}

PROBES: list[harness.Probe] = [
    # --- the worst possible bug: encoding rather than encrypting --------------
    (
        SECRETBOX,
        "seal encodes instead of encrypting",
        "    return HEADER + nonce + AESGCM(key).encrypt(nonce, plaintext, aad)",
        "    return HEADER + nonce + plaintext",
        ("test_the_plaintext_is_not_in_the_ciphertext",
         "test_ciphertext_does_not_look_like_the_text_it_came_from",
         "test_a_sealed_blob_comes_back_exactly"),
    ),
    # --- the nonce ------------------------------------------------------------
    (
        SECRETBOX,
        "the nonce is fixed, which under GCM destroys the encryption",
        "    nonce = os.urandom(NONCE_BYTES)",
        "    nonce = b'\\\\x00' * NONCE_BYTES",
        ("test_sealing_the_same_text_twice_gives_different_bytes",),
    ),
    (
        SECRETBOX,
        "the caller can supply a nonce, and so can supply it twice",
        "def seal(plaintext: bytes, *, key: bytes, aad: bytes) -> bytes:",
        "def seal(plaintext: bytes, *, key: bytes, aad: bytes, nonce=None) -> bytes:",
        ("test_the_caller_cannot_supply_a_nonce",),
    ),
    # --- authentication -------------------------------------------------------
    (
        SECRETBOX,
        "additional authenticated data is dropped on the way in",
        "AESGCM(key).encrypt(nonce, plaintext, aad)",
        "AESGCM(key).encrypt(nonce, plaintext, None)",
        ("test_a_blob_labelled_as_something_else_is_refused",
         "test_a_sealed_blob_comes_back_exactly"),
    ),
    (
        SECRETBOX,
        "additional authenticated data is optional",
        '    if not aad:\n        raise ValueError(',
        "    if False:\n        raise ValueError(",
        ("test_sealing_without_saying_what_it_is_is_refused",
         "test_unsealing_without_saying_what_it_is_is_refused"),
    ),
    (
        SECRETBOX,
        "a tampered blob is returned instead of refused",
        "    except InvalidTag as exc:\n        raise Tampered(",
        "    except InvalidTag as exc:\n        return payload  # noqa\n    except ValueError as exc:\n        raise Tampered(",
        ("test_a_single_flipped_bit_anywhere_is_refused",
         "test_a_blob_sealed_under_another_key_is_refused"),
    ),
    # --- the header -----------------------------------------------------------
    (
        SECRETBOX,
        "plaintext is accepted as a sealed blob",
        "    if not blob.startswith(MAGIC):",
        "    if False:",
        ("test_plaintext_is_not_accepted_as_a_sealed_blob",),
    ),
    (
        SECRETBOX,
        "a future version is read as the current one",
        "    if version != VERSION:",
        "    if False:",
        ("test_a_future_version_is_named_as_a_re_key_not_a_corruption",),
    ),
    (
        SECRETBOX,
        "a truncated blob crashes instead of refusing",
        "    if len(body) <= NONCE_BYTES:",
        "    if False:",
        ("test_a_truncated_blob_is_refused_rather_than_crashing",),
    ),
    # --- keys -----------------------------------------------------------------
    (
        SECRETBOX,
        "a short key is padded up to length rather than refused",
        "    if not isinstance(key, (bytes, bytearray)) or len(key) != KEY_BYTES:",
        "    if False:",
        ("test_a_key_of_the_wrong_size_is_refused_not_padded",),
    ),
    (
        SECRETBOX,
        "keys are 128-bit",
        "KEY_BYTES = 32            # AES-256.",
        "KEY_BYTES = 16            # AES-256.",
        ("test_generated_keys_are_the_right_size_and_not_repeated",),
    ),
    (
        SECRETBOX,
        "the salt is fixed, so every installation shares a key space",
        "def new_salt() -> bytes:\n    return os.urandom(SALT_BYTES)",
        "def new_salt() -> bytes:\n    return b'jarvis-fixed-sa'",
        ("test_the_same_passphrase_under_a_different_salt_is_a_different_key",
         "test_a_salt_is_random_and_long_enough"),
    ),
    (
        SECRETBOX,
        "a short salt is stretched instead of refused",
        "    if len(salt) < SALT_BYTES:",
        "    if False:",
        ("test_a_short_salt_is_refused_rather_than_stretched",),
    ),
    (
        SECRETBOX,
        "an empty passphrase is accepted",
        "    if not passphrase:",
        "    if False:",
        ("test_an_empty_passphrase_is_refused",),
    ),
    (
        SECRETBOX,
        "the fingerprint is the start of the key",
        '    digest = hashes.Hash(hashes.SHA256())\n'
        '    digest.update(b"fingerprint:" + key)\n'
        '    return digest.finalize().hex()[:16]',
        "    return key.hex()[:16]",
        ("test_a_fingerprint_identifies_a_key_without_revealing_it",),
    ),
    (
        SECRETBOX,
        "`describe` claims a protection the module does not give",
        '        "does_not_protect_against": ["code running as Jarvis"],',
        '        "does_not_protect_against": [],',
        ("test_describe_is_honest_about_the_limit",),
    ),
]


if __name__ == "__main__":
    raise SystemExit(harness.run_probes(PROBES, SUITES))
