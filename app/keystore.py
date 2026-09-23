"""Where the constitution's key lives, and what to do when it does not.

`gateway/constitution.py` takes a key and never looks for one, which was the
right split and left this open. `docs/JARVIS_PERSISTENCE.md` §3c-quater stated
the two candidates and built neither:

> Windows DPAPI tied to Krish's account (Jarvis inherits it while running as
> Krish; survives a reboot unattended) and a passphrase entered at shell startup
> (stronger; Jarvis cannot read the constitution after an unattended restart).

## It is DPAPI, and Krish's own arrangement decides it

`scripts/keep-jarvis-up.ps1` exists because *"Krish leaves on vacation tomorrow
and the failure he cannot recover from"* is Jarvis staying down. It restarts him
with nobody at the keyboard. A passphrase means that after the first unattended
restart Jarvis cannot read his own constitution until Krish is home and types
it - so the stronger option produces, in his actual use, a Jarvis governed by a
document he cannot open. That is not stronger, it is off.

The seal was never protection from Jarvis and cannot be - `constitution.py` says
so in its own first paragraph, because he runs as a process with the filesystem
and the key. What it protects against is the file being read off the machine, or
altered without it showing. DPAPI is the right size for that job and asks
nothing of a person.

## Which is why the escrow is not optional

DPAPI ties the key to one Windows account. Reinstall Windows, lose the profile,
move to a new machine, and every amendment is unreadable for ever - by Krish as
much as by Jarvis. So the key is also written out wrapped in a passphrase he
chooses and keeps somewhere else, and a keystore with no escrow is reported as
incomplete every single time until there is one. It is the one failure here with
no recovery, so it is the one thing this module nags about.

## The shape

Everything that decides is in this file and runs anywhere. Everything that
touches Windows is `app/dpapi.py`, which has one effect per function and no
judgement in any of them. `Reading` is what somebody looked up about the
machine; `verdict` turns that into a state and the next step in words. Nothing
here reads a file or calls an API, which is why it can be tested at all.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app import secretbox

# Beside the sealed documents rather than in the repository: a key checked in
# next to the thing it opens is not a key. `constitution.directory()` is the
# same folder, and both are outside the git tree.
KEY_FILE = "charter.key"
ESCROW_FILE = "charter.key.escrow"

# What the escrow's passphrase-derived key is salted with. Stored in the escrow
# file itself - a salt is not a secret, and one fixed in the source would mean
# every installation shares a key space.
ESCROW_AAD = b"jarvis/charter-key-escrow/v1"

# The state of the keystore, worst first. The order is the order `verdict`
# checks in, and it is deliberate: a keystore nobody can open is a worse thing
# to be told about second.
ABSENT = "absent"
UNREADABLE = "unreadable"
NO_ESCROW = "no_escrow"
READY = "ready"

# Which states let Jarvis start at all. `NO_ESCROW` does: refusing to run
# because a backup is missing would be a lock that keeps him out of his own
# constitution to protect him from losing it.
WORKABLE = (NO_ESCROW, READY)

# The minimum passphrase for the escrow. Not a general password policy - this
# one guards the only copy of the key that survives the machine, and it is typed
# perhaps twice in a lifetime, so length costs nothing here.
ESCROW_PASSPHRASE_MIN = 12


class NotReady(RuntimeError):
    """The keystore cannot serve a key, and the message says what to do."""


class WeakPassphrase(ValueError):
    """An escrow passphrase short enough to be worth saying so about."""


@dataclass(frozen=True)
class Reading:
    """What somebody looked up about this machine. Facts, no judgement.

    Taken by an adapter and handed here, so that every branch below is
    reachable from a test on a machine that has none of it."""

    windows: bool
    dpapi: bool
    key_present: bool
    key_opens: bool
    escrow_present: bool
    # The fingerprint of the key the escrow holds, when it could be read
    # cheaply. `None` means nobody checked - which is not the same as "it does
    # not match", and is not reported as a mismatch.
    escrow_fingerprint: str | None = None
    key_fingerprint: str | None = None


@dataclass(frozen=True)
class Verdict:
    """What state the keystore is in and the next thing to do about it."""

    state: str
    because: str
    next_step: str

    @property
    def workable(self) -> bool:
        return self.state in WORKABLE

    @property
    def escrow_matches(self) -> bool:
        return self.state == READY


def verdict(reading: Reading) -> Verdict:
    """The whole decision, in one place, with no I/O in it."""
    if not reading.windows or not reading.dpapi:
        return Verdict(
            ABSENT,
            "this machine has no DPAPI, so there is nowhere to put the key that "
            "does not involve a person typing it",
            "run this on the Windows machine. Nothing here is a fallback: a key "
            "written to a plain file would be weaker than the seal it opens, "
            "and one held in an environment variable would be in every crash "
            "dump.")
    if not reading.key_present:
        return Verdict(
            ABSENT,
            "no key has been created on this machine yet, so the constitution "
            "cannot be installed or read",
            "python -m desktop.bringup --make-key  (creates it, seals it to "
            "this Windows account, and asks for an escrow passphrase)")
    if not reading.key_opens:
        return Verdict(
            UNREADABLE,
            "a key file is here but this Windows account cannot open it, which "
            "means it was sealed by a different account or the profile was "
            "rebuilt",
            "restore it from the escrow copy: python -m desktop.bringup "
            "--restore-key. Without the escrow the amendments cannot be "
            "recovered by anybody, including Krish.")
    if not reading.escrow_present:
        return Verdict(
            NO_ESCROW,
            "the key works, but it exists only on this Windows account. A "
            "reinstall or a new machine would make every amendment unreadable "
            "for ever",
            "python -m desktop.bringup --write-escrow  (wraps the key in a "
            "passphrase you choose; keep the file somewhere that is not this "
            "machine)")
    if (reading.escrow_fingerprint is not None
            and reading.key_fingerprint is not None
            and reading.escrow_fingerprint != reading.key_fingerprint):
        return Verdict(
            NO_ESCROW,
            "the escrow holds a different key than the one in use, so it would "
            "restore a key that opens nothing. A stale backup is worse than a "
            "missing one, because it is mistaken for a backup",
            "python -m desktop.bringup --write-escrow  (rewrites it from the "
            "key actually in use)")
    return Verdict(
        READY,
        "the key is sealed to this Windows account and an escrow copy of it "
        "exists",
        "nothing")


def key_path(directory: Path) -> Path:
    return Path(directory) / KEY_FILE


def escrow_path(directory: Path) -> Path:
    return Path(directory) / ESCROW_FILE


def check_passphrase(passphrase: str) -> None:
    """Refuse an escrow passphrase that is not worth the file it guards."""
    if len(passphrase or "") < ESCROW_PASSPHRASE_MIN:
        raise WeakPassphrase(
            f"an escrow passphrase must be at least {ESCROW_PASSPHRASE_MIN} "
            f"characters. This one guards the only copy of the key that "
            f"survives this machine, and it is typed about twice in a "
            f"lifetime, so length costs nothing.")


def wrap_for_escrow(key: bytes, *, passphrase: str) -> bytes:
    """A copy of the key that a person can carry, guarded by what they know.

    The salt is generated per escrow and written into the file, because a salt
    fixed in the source would mean every installation of this shares a key
    space - which is the finding `tests/probes/secretbox_probes.py` already
    holds for the sealing itself."""
    check_passphrase(passphrase)
    salt = secretbox.new_salt()
    wrapping = secretbox.key_from_passphrase(passphrase, salt=salt)
    return salt + secretbox.seal(key, key=wrapping, aad=ESCROW_AAD)


def unwrap_escrow(blob: bytes, *, passphrase: str) -> bytes:
    """The key back out of an escrow file.

    A wrong passphrase surfaces as `secretbox.Tampered`, which is the honest
    report: AES-GCM cannot tell "you mistyped it" from "somebody edited this",
    and a module that guessed between them would be inventing a distinction the
    cryptography does not make."""
    if len(blob) <= secretbox.SALT_BYTES:
        raise secretbox.NotSealed(
            "this escrow file is too short to contain a salt and a sealed key")
    salt, sealed = blob[:secretbox.SALT_BYTES], blob[secretbox.SALT_BYTES:]
    wrapping = secretbox.key_from_passphrase(passphrase, salt=salt)
    return secretbox.unseal(sealed, key=wrapping, aad=ESCROW_AAD)


def describe() -> dict:
    return {
        "where": "Windows DPAPI, sealed to Krish's account",
        "why_not_a_passphrase":
            "the supervisor restarts Jarvis with nobody at the keyboard",
        "escrow": "required, and reported as missing every run until it exists",
        "protects_against_jarvis": False,
        "states": [ABSENT, UNREADABLE, NO_ESCROW, READY],
        "runs_without_an_escrow": True,
    }
