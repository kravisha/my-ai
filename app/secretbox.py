"""Encrypting something at rest, and being honest about what that buys.

Krish, 2026-09-23: *"keep the constitution and the amendments encrypted and
hidden and only visible to superuser and Jarvis and other agents."*

## What this protects against, and what it does not

It protects a copy of the file that leaves the machine: a stolen disk, a backup,
a sync folder, a support bundle somebody emails. Those are real and they are the
common case.

It does **not** protect against code running as Jarvis, because Jarvis has to be
able to read his own constitution, which means the key has to be reachable from
his process. Anything running as him can therefore decrypt it. Saying so here
rather than in a footnote, because a module named `secretbox` invites the
assumption that it solves more than it does, and the safeguard against a rogue
Jarvis is somewhere else entirely - `gateway/charter.py`'s owner-written grant,
and an amendment log that makes a change without one detectable.

## Shape

`seal` and `unseal` are pure: bytes in, bytes out, no filesystem, no clock, no
environment. Where the key comes from is an adapter with one function per source
and no branching, because key sources are the part that needs a real machine and
the part that cannot be tested here.

Additional authenticated data is **required**, not optional. AES-GCM will happily
authenticate nothing, and a sealed blob that does not name what it is can be
moved somewhere else and still decrypt - the constitution swapped for an old
amendment, both valid ciphertext under the same key. `aad` is what makes a blob
refuse to be read as something it is not.
"""

from __future__ import annotations

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

# The header every blob starts with. Versioned so that a future change of cipher
# can be told from a corrupt file, which is the difference between "re-key this"
# and "restore from backup".
MAGIC = b"JARVISBOX"
VERSION = 1
HEADER = MAGIC + bytes([VERSION])

NONCE_BYTES = 12          # AES-GCM's standard; anything else is a footgun.
KEY_BYTES = 32            # AES-256.
SALT_BYTES = 16

# scrypt parameters for turning a passphrase into a key. Chosen for a laptop
# that must not take a visible pause at startup: ~100ms and ~64MB.
SCRYPT_N = 2 ** 16
SCRYPT_R = 8
SCRYPT_P = 1


class Tampered(ValueError):
    """The blob was not produced by this key, or has been altered.

    One exception for both, deliberately. AES-GCM cannot tell a wrong key from a
    flipped bit and neither can anything above it, so a pair of exceptions would
    be inviting a caller to act on a distinction that does not exist."""


class NotSealed(ValueError):
    """This is not a sealed blob at all - wrong header, or too short."""


def new_key() -> bytes:
    return AESGCM.generate_key(bit_length=KEY_BYTES * 8)


def key_from_passphrase(passphrase: str, *, salt: bytes) -> bytes:
    """Derive a key from something a person can remember.

    `salt` is required and is stored alongside the ciphertext, not with the
    passphrase. A fixed salt in the source would make every installation of this
    project share a key space, which is the kind of mistake that is invisible
    until it is in the news."""
    if not passphrase:
        raise ValueError("a passphrase cannot be empty")
    if len(salt) < SALT_BYTES:
        raise ValueError(f"salt must be at least {SALT_BYTES} bytes")
    return Scrypt(salt=salt, length=KEY_BYTES, n=SCRYPT_N, r=SCRYPT_R,
                  p=SCRYPT_P).derive(passphrase.encode("utf-8"))


def new_salt() -> bytes:
    return os.urandom(SALT_BYTES)


def seal(plaintext: bytes, *, key: bytes, aad: bytes) -> bytes:
    """Encrypt, with a fresh nonce every time.

    The nonce is generated here rather than taken, because a caller that could
    supply one is a caller that can supply the same one twice, and nonce reuse
    under GCM does not degrade the encryption - it destroys it."""
    _check_key(key)
    _check_aad(aad)
    nonce = os.urandom(NONCE_BYTES)
    return HEADER + nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def unseal(blob: bytes, *, key: bytes, aad: bytes) -> bytes:
    """Decrypt, or refuse. Never returns a partial or unauthenticated result."""
    _check_key(key)
    _check_aad(aad)
    if not blob.startswith(MAGIC):
        raise NotSealed(
            "this is not a sealed blob: it does not start with the expected "
            "header. Refusing rather than trying to read it as plaintext, "
            "because a store that silently accepts unencrypted content is one "
            "an attacker can downgrade.")
    version = blob[len(MAGIC)]
    if version != VERSION:
        raise NotSealed(
            f"sealed with version {version}, and this build understands "
            f"{VERSION}. That is a re-key, not a corruption, and the difference "
            f"decides whether you reach for a backup.")
    body = blob[len(HEADER):]
    if len(body) <= NONCE_BYTES:
        raise NotSealed("sealed blob is truncated: there is not even a nonce")
    nonce, payload = body[:NONCE_BYTES], body[NONCE_BYTES:]
    try:
        return AESGCM(key).decrypt(nonce, payload, aad)
    except InvalidTag as exc:
        raise Tampered(
            "this blob was not produced by this key, or has been altered since "
            "it was. AES-GCM cannot tell those apart and neither can this - "
            "check the key first, then the file's history.") from exc


def fingerprint(key: bytes) -> str:
    """A short, non-reversible label for a key, so two can be told apart.

    Used in logs and error messages. Hashed rather than truncated, because the
    first bytes of a key are key material and a log is a file somebody copies."""
    _check_key(key)
    digest = hashes.Hash(hashes.SHA256())
    digest.update(b"fingerprint:" + key)
    return digest.finalize().hex()[:16]


def _check_key(key: bytes) -> None:
    if not isinstance(key, (bytes, bytearray)) or len(key) != KEY_BYTES:
        raise ValueError(
            f"a key must be exactly {KEY_BYTES} bytes. Refusing a short one "
            f"rather than padding or hashing it, because both would accept a "
            f"weak key and report success.")


def _check_aad(aad: bytes) -> None:
    if not aad:
        raise ValueError(
            "additional authenticated data is required. A blob that does not "
            "say what it is can be moved somewhere else and still decrypt - the "
            "constitution replaced by an old amendment, both valid under the "
            "same key. `aad` is what makes that fail.")


def describe() -> dict:
    return {
        "cipher": "AES-256-GCM",
        "version": VERSION,
        "nonce_bytes": NONCE_BYTES,
        "key_bytes": KEY_BYTES,
        "kdf": "scrypt",
        "aad_required": True,
        "protects_against": ["a copy of the file leaving the machine"],
        "does_not_protect_against": ["code running as Jarvis"],
    }
