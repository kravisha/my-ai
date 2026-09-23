"""Windows DPAPI, as thin as it goes.

The adapter half of `app/keystore.py`. Three functions, one effect each, and no
judgement in any of them - the judgement is in `keystore`, which can be tested
on this machine, and this file is the part that cannot be.

**What DPAPI is.** `CryptProtectData` encrypts a blob with a key Windows derives
from the logged-in user's credentials and keeps in the operating system. Krish's
account can decrypt it; another account on the same machine cannot; a copy taken
off the machine is inert. There is no passphrase to type, which is the whole
reason it is here: `scripts/keep-jarvis-up.ps1` restarts Jarvis unattended,
including while Krish is away, and a key that needs a person present is a key
Jarvis stops having the moment he most needs it.

**What it is not.** It is not protection from Jarvis, and nothing can be:
`gateway/constitution.py` says so in its own first paragraph - he runs as a
process with the filesystem and the key. The seal's job is tamper-evidence and
protection off the machine, and DPAPI is exactly the right size for that job.

**And the failure it brings with it.** The key is tied to a Windows account. A
reinstall, a lost profile, a new machine - and every amendment is unreadable for
ever, by anyone. That is why `keystore` will not call this the finished article
without an escrow copy, and why bring-up reports its absence.
"""

from __future__ import annotations

import ctypes
import sys

# Passed as the description; Windows stores it beside the blob and hands it back
# on decrypt. Useful in a dump, harmless otherwise.
DESCRIPTION = "Jarvis charter key"


class Unavailable(RuntimeError):
    """This is not Windows, or the API did not load."""


class Refused(RuntimeError):
    """Windows declined. The usual cause is a blob sealed by another account."""


def available() -> bool:
    """Whether this machine has DPAPI at all.

    Returned rather than raised, and never consulted by this module itself: the
    decision about what to do on a machine without DPAPI belongs to `keystore`,
    where it can be tested."""
    return sys.platform == "win32"


class _Blob(ctypes.Structure):
    # `DWORD` is `c_ulong`, spelled out rather than imported from
    # `ctypes.wintypes`: that module is documented as Windows-only and raises on
    # some builds of every other platform, which would make merely importing
    # this file fail on the machine it is developed and tested on.
    _fields_ = [("cbData", ctypes.c_ulong),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _read(blob: _Blob) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def _free(blob: _Blob) -> None:
    ctypes.windll.kernel32.LocalFree(blob.pbData)


def protect(secret: bytes) -> bytes:
    """Encrypt to this Windows account. Raises rather than returning plaintext."""
    if not available():
        raise Unavailable("DPAPI is a Windows API and this is not Windows")
    out = _Blob()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(_blob(secret)), DESCRIPTION, None, None, None, 0,
        ctypes.byref(out))
    if not ok:
        raise Refused(f"CryptProtectData failed: {ctypes.GetLastError()}")
    try:
        return _read(out)
    finally:
        _free(out)


def unprotect(sealed: bytes) -> bytes:
    """Decrypt a blob this account sealed."""
    if not available():
        raise Unavailable("DPAPI is a Windows API and this is not Windows")
    out = _Blob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(_blob(sealed)), None, None, None, None, 0,
        ctypes.byref(out))
    if not ok:
        raise Refused(
            f"CryptUnprotectData failed: {ctypes.GetLastError()}. A blob sealed "
            f"by a different Windows account cannot be opened by this one.")
    try:
        return _read(out)
    finally:
        _free(out)
