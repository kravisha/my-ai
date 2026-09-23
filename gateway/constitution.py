"""The constitution and its amendments, encrypted at rest and amendable only by Krish.

Krish, 2026-09-23:

> *"Things such as the constitution need the explicit permission of the human to
> be changed. They are read only principles to act by... keep the constitution
> and the amendments encrypted and hidden and only visible to superuser and
> Jarvis and other agents."*

Three separate things, and they defend against three different failures. Running
them together would have produced something that felt secure and was not:

| | against |
|---|---|
| **encrypted at rest** (`app/secretbox.py`) | a copy of the file leaving the machine - a backup, a sync folder, a support bundle |
| **the owner's key** (`gateway/charter.py`) | Jarvis amending it because he decided he should |
| **the chained amendment log, here** | Jarvis amending it *anyway* - by writing the file directly, outside the sanctioned path |

The third is the one that matters most and is the easiest to leave out. Jarvis
runs as a process with a filesystem and the decryption key: nothing can stop him
rewriting the sealed file. What `verify` does is make it **detectable** - every
amendment is a link in a hash chain, and every link names the `charter_grant`
that authorised it. A constitution whose text does not match the chain, or whose
chain contains a link with no grant behind it, is an unsanctioned amendment and
`verify` says so by name.

That is the honest shape of this. A lock Jarvis holds the key to is not a lock;
a record he cannot forge without leaving a hole is a deterrent that survives him
being wrong.

## Read-only means there is no writer

Krish, 2026-09-23: *"don't allow Jarvis or yourself to ever change the
constitution. Only I should be able to change the main document, manually,
myself."*

So the constitution's text has no writer in this module at all. `read` decrypts
and returns it; `install` seals what Krish already wrote, once, and refuses to
overwrite. There is no `amend` for the text. An earlier version had one, gated on
his key - which was the wrong shape, because a key is a thing that can be in
force when nobody meant it to be, and this document is the one where that costs
everything.

Additions go to `AI-CONSTITUTION-AMENDMENTS.md`, which is an ordinary file, and
`add_amendment` records them here as links in a chain. An amendment **adds**; it
never rewrites the constitution, and nothing here can.

The chain link is written before anything else, deliberately: a crash leaves a
link with no matching amendment, which `verify` reports as damage. The other
order leaves a change with no link, which is indistinguishable from the attack.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

from app import secretbox
from gateway import charter, dbaclient, identity, ledger

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Where the sealed files live. Outside the repository by default: a constitution
# inside a git checkout is one that gets committed in plaintext by the next
# person who runs `git add -A`.
DIR_ENV = "JARVIS_CHARTER_DIR"
DEFAULT_DIR = PROJECT_ROOT / "data" / "charter"

CONSTITUTION_FILE = "constitution.sealed"
AMENDMENTS_FILE = "amendments.sealed"

# What each blob says it is. A sealed file that does not name itself can be
# swapped for another - see `app/secretbox.py`.
CONSTITUTION_AAD = b"jarvis:charter:constitution:v1"
AMENDMENTS_AAD = b"jarvis:charter:amendments:v1"

GENESIS = "genesis"

# Only the owner may read or write these. 0o600 on POSIX; on Windows this is a
# no-op and the real protection is an ACL, which `desktop/verify.py` checks on
# the machine because nothing here can.
OWNER_ONLY = stat.S_IRUSR | stat.S_IWUSR


class NotInstalled(RuntimeError):
    """There is no sealed constitution yet."""


class Unauthorised(PermissionError):
    """An amendment without the owner's key."""


def directory() -> Path:
    configured = (os.environ.get(DIR_ENV, "") or "").strip()
    return Path(configured) if configured else DEFAULT_DIR


def _path(name: str) -> Path:
    return directory() / name


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write(path: Path, blob: bytes) -> None:
    """Write owner-only, and atomically.

    Atomic because a half-written constitution is indistinguishable from a
    tampered one, and the recovery for those is not the same."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".writing")
    temporary.write_bytes(blob)
    try:
        os.chmod(temporary, OWNER_ONLY)
    except OSError:
        # Windows. The ACL is the real control there and this is not it.
        pass
    temporary.replace(path)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _link(previous: str, *, at: str, text_digest: str, grant_id: str,
          why: str) -> str:
    """One link of the amendment chain.

    Covers the previous link, so an amendment cannot be removed from the middle
    without every later link failing - which is the property that makes a
    deletion as visible as an insertion."""
    material = json.dumps(
        {"previous": previous, "at": at, "text": text_digest,
         "grant_id": grant_id, "why": why},
        sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


# --- reading -------------------------------------------------------------------


def installed() -> bool:
    return _path(CONSTITUTION_FILE).exists()


def read(*, key: bytes) -> str:
    """The constitution, decrypted. The only way to get the text."""
    path = _path(CONSTITUTION_FILE)
    if not path.exists():
        raise NotInstalled(
            f"no sealed constitution at {path}. `install` writes one; until "
            f"then Jarvis has no stated principles to act by, which is a "
            f"louder problem than a missing file.")
    return secretbox.unseal(path.read_bytes(), key=key,
                            aad=CONSTITUTION_AAD).decode("utf-8")


def amendments(*, key: bytes) -> list[dict]:
    """Every amendment, oldest first. Empty before the first one."""
    path = _path(AMENDMENTS_FILE)
    if not path.exists():
        return []
    raw = secretbox.unseal(path.read_bytes(), key=key, aad=AMENDMENTS_AAD)
    return json.loads(raw.decode("utf-8"))


# --- installing and amending ----------------------------------------------------


def install(text: str, *, key: bytes, granted_by: str) -> dict:
    """Seal a constitution for the first time.

    Refuses to overwrite. Installing over an existing one would be an amendment
    with no chain link and no grant - exactly the shape `verify` exists to
    catch, offered as a convenience."""
    if not (text or "").strip():
        raise ValueError("a constitution cannot be empty")
    if installed():
        raise Unauthorised(
            "a constitution is already sealed here. Changing it is `amend`, "
            "which needs Krish's key and leaves a link in the chain. Replacing "
            "it wholesale would leave neither.")
    if not (granted_by or "").strip():
        raise ValueError("installing a constitution must say who authorised it")
    _write(_path(CONSTITUTION_FILE),
           secretbox.seal(text.encode("utf-8"), key=key, aad=CONSTITUTION_AAD))
    _write(_path(AMENDMENTS_FILE),
           secretbox.seal(json.dumps([]).encode("utf-8"), key=key,
                          aad=AMENDMENTS_AAD))
    return {"installed_at": _now(), "granted_by": granted_by,
            "digest": _digest(text)}


def add_amendment(client: dbaclient.DBAClient, text: str, *, key: bytes,
                  why: str, agent: str = identity.AGENT_ID) -> dict:
    """Record an addition to the charter. **Never touches the constitution.**

    `text` is the amendment, not a replacement constitution. The sealed
    constitution is not read, not re-sealed and not referred to by this function
    beyond noting which text the amendment was added alongside.

    The grant is read from the DBA, not taken as an argument - see
    `gateway/charter.py` for why a key a caller can name is not a key."""
    if not (text or "").strip():
        raise ValueError("an amendment cannot be empty")
    if not (why or "").strip():
        raise ValueError(
            "an amendment must say why. The chain records the reason, and an "
            "amendment nobody can account for later is the thing this whole "
            "arrangement is against.")
    if not installed():
        raise NotInstalled("there is nothing to amend yet")

    grant = _active_charter_grant(client, agent=agent)
    if grant is None:
        raise Unauthorised(
            f"amending the constitution needs the "
            f"{charter.introspect.KEY_CHARTER!r} key. "
            f"{charter.explain(client, charter.introspect.KEY_CHARTER, agent=agent)}")

    existing = amendments(key=key)
    previous = existing[-1]["link"] if existing else GENESIS
    at = _now()
    entry = {
        "at": at,
        "previous": previous,
        "text": _digest(text),
        # Which constitution this was added alongside. Recorded so a reader can
        # tell whether an amendment predates a hand edit Krish made - NOT as
        # something this module keeps in step, because it never writes that file.
        "alongside": _digest(read(key=key)),
        "grant_id": grant["id"],
        "granted_by": grant.get("granted_by"),
        "why": why.strip(),
    }
    entry["link"] = _link(previous, at=at, text_digest=entry["text"],
                          grant_id=entry["grant_id"], why=entry["why"])

    # The amendments file, and nothing else. The constitution is not re-sealed
    # here and there is no branch in this module that re-seals it.
    _write(_path(AMENDMENTS_FILE),
           secretbox.seal(json.dumps(existing + [entry]).encode("utf-8"),
                          key=key, aad=AMENDMENTS_AAD))

    charter.note_amendment(client, what=why.strip()[:120], why=why.strip(),
                           granted_by=grant.get("granted_by") or "unknown",
                           agent=agent)
    return entry


def _active_charter_grant(client: dbaclient.DBAClient, *, agent: str) -> dict | None:
    """One call, to the one place that decides what "live" means.

    This used to test `keys_in_force` and then filter the raw grants again by
    status alone. The second filter did not check expiry, so it was relying on
    the first - and a probe that made the first useless broke nothing, because
    the duplicate was carrying it. Two checks that must agree are one check and
    one bug waiting."""
    return charter.live_grant(client, charter.introspect.KEY_CHARTER, agent=agent)


# --- detecting an amendment nobody authorised -----------------------------------


def verify(client: dbaclient.DBAClient, *, key: bytes,
           agent: str = identity.AGENT_ID) -> dict:
    """Does the sealed text match the chain, and did Krish authorise every link?

    This is the part that survives Jarvis being wrong. He has the key and the
    filesystem, so he can rewrite the sealed constitution - what he cannot do is
    produce a `charter_grant`, because that record needs `administer` and lives
    in another service. So an unsanctioned amendment leaves one of two holes, and
    both are named here:

    - the current text's digest is not the newest link's `text`, or
    - a link names a grant that does not exist.

    Returns a report rather than raising, because *"your constitution was changed
    by something that could not have been authorised"* is a thing Jarvis must be
    able to **say** (§34), and an exception at the point of damage loses the rest
    of the finding."""
    report: dict = {"at": _now(), "intact": True, "problems": [],
                    "amendments": 0, "checked_grants": 0}
    if not installed():
        report.update(intact=False,
                      problems=["there is no sealed constitution"])
        return report

    try:
        chain = amendments(key=key)
        current = read(key=key)
    except (secretbox.Tampered, secretbox.NotSealed) as exc:
        report.update(intact=False, problems=[f"the sealed files will not open: {exc}"])
        return report

    report["amendments"] = len(chain)

    previous = GENESIS
    for position, entry in enumerate(chain, start=1):
        expected = _link(previous, at=entry.get("at", ""),
                         text_digest=entry.get("text", ""),
                         grant_id=entry.get("grant_id", ""),
                         why=entry.get("why", ""))
        # Computed from the WALKED previous, not the stored one. That is what
        # makes the chain load-bearing: a link covers the one before it, so
        # removing an amendment from the middle changes every link after it. A
        # first version compared the stored `previous` field separately and the
        # chain itself was decorative - a probe that dropped `previous` from the
        # hashed material broke no test at all.
        if entry.get("link") != expected:
            if entry.get("previous") != previous:
                report["problems"].append(
                    f"amendment {position} claims to follow "
                    f"{entry.get('previous')} but the one before it is "
                    f"{previous}. A link was removed or reordered.")
            else:
                report["problems"].append(
                    f"amendment {position} has been altered since it was "
                    f"written: its link does not match its own contents.")
        previous = entry.get("link") or previous

        grant_id = entry.get("grant_id")
        if not grant_id:
            report["problems"].append(
                f"amendment {position} names no grant. Every amendment needs "
                f"one, and one that does not is a change nobody authorised.")
            continue
        try:
            grant = client.get(grant_id)
        except (dbaclient.Refused, dbaclient.Unavailable) as exc:
            report["problems"].append(
                f"amendment {position}'s grant {grant_id} could not be read "
                f"({exc}). Unverified is not the same as forged, and this is "
                f"the first.")
            continue
        report["checked_grants"] += 1
        if not grant:
            report["problems"].append(
                f"amendment {position} names grant {grant_id}, which does not "
                f"exist. Jarvis cannot write a `charter_grant`, so a link "
                f"naming one that was never issued is an amendment made outside "
                f"the sanctioned path.")

    # The constitution is checked against what the newest amendment was added
    # ALONGSIDE, not against the amendment's own text. Amendments add; they never
    # replace, so a mismatch here means the sealed constitution changed after an
    # amendment was recorded - and nothing in this module can do that.
    if chain and _digest(current) != chain[-1].get("alongside"):
        report["problems"].append(
            "the sealed constitution is not the one the newest amendment was "
            "added alongside. Nothing here rewrites it, so either Krish edited "
            "it by hand - in which case re-seal it and this clears - or "
            "something changed it that should not have been able to.")

    report["intact"] = not report["problems"]
    return report


def describe() -> dict:
    return {
        "directory": str(directory()),
        "installed": installed(),
        "encryption": secretbox.describe(),
        "constitution_is_writable": False,
        "amendments_added_by": ("the owner's charter key, granted from the "
                                "operator console"),
        "detects": ["an amendment with no grant",
                    "an amendment whose grant was never issued",
                    "a chain link removed, reordered or altered",
                    "a constitution that changed after an amendment was added"],
    }
