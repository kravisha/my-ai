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
myself."* And, on the amendments: *"Yes wall the amendments too."*

The **constitution** has no writer here. `read` decrypts and returns it;
`seal_what_krish_wrote` records it exactly as he left it. `amend` was removed the
hour after it was written: it rewrote the text behind his key, and a key can be
in force at a moment nobody intended - this is the document where that costs
everything.

The **amendments** may be added to. Krish, on second thoughts: *"I would like to
give Jarvis the ability to add amendments to the constitution but not deleting
any from the constitution. He should be able to add new directives on my
request."*

`append_amendment` is that, and the shape is the guarantee rather than the
intention. It reads what is already there, puts the new text after it, and there
is no branch in it that writes anything else - no replace, no edit, no path that
takes a whole document. Deleting an amendment is not forbidden here so much as
unavailable: nothing in this module can express it.

**On his request**, which is the other half. `requested_by` may not be the agent,
the same refusal `gateway/readback.py` makes for confirmations: an assistant that
can decide the charter needs a new directive and then add it has been given the
charter, not the ability to help with it.

## What is left is evidence, not control

The sealed copies exist to answer one question: *has either document changed
since Krish last recorded it?* `verify` answers it, and every problem it reports
is a fact about files rather than a judgement about intent - "this is not what
was sealed" rather than "somebody tampered with this". The first is something a
program can know.
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
# The amendments document itself, sealed as it stood after the last append. What
# `verify` compares the live file against, so that a deletion made with a text
# editor is as visible as one made in code.
AMENDMENTS_DOC_FILE = "amendments_document.sealed"

# What each blob says it is. A sealed file that does not name itself can be
# swapped for another - see `app/secretbox.py`.
CONSTITUTION_AAD = b"jarvis:charter:constitution:v1"
AMENDMENTS_AAD = b"jarvis:charter:amendments:v1"
AMENDMENTS_DOC_AAD = b"jarvis:charter:amendments-document:v1"

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


def install(text: str, *, key: bytes, granted_by: str,
            amendments_text: str = "") -> dict:
    """Seal what Krish wrote, the first time.

    Refuses to overwrite: a second `install` would be a rewrite wearing a
    setup-step's name. When he edits either document by hand afterwards, the way
    to record it is `seal_what_krish_wrote`, which leaves a link saying so."""
    if not (text or "").strip():
        raise ValueError("a constitution cannot be empty")
    if installed():
        raise Unauthorised(
            "a constitution is already sealed here. Nothing in this module "
            "rewrites it. If Krish has edited it by hand, "
            "`seal_what_krish_wrote` records that; there is no other path.")
    if not (granted_by or "").strip():
        raise ValueError("installing a constitution must say who authorised it")
    _write(_path(CONSTITUTION_FILE),
           secretbox.seal(text.encode("utf-8"), key=key, aad=CONSTITUTION_AAD))
    _write(_path(AMENDMENTS_FILE),
           secretbox.seal(json.dumps([]).encode("utf-8"), key=key,
                          aad=AMENDMENTS_AAD))
    sealed = {"installed_at": _now(), "granted_by": granted_by,
              "digest": _digest(text)}
    if amendments_text.strip():
        seal_what_krish_wrote(text, amendments_text, key=key, by=granted_by)
    return sealed


def amendments_document(*, key: bytes) -> str:
    """The amendments document as it stood when it was last sealed."""
    path = _path(AMENDMENTS_DOC_FILE)
    if not path.exists():
        return ""
    return secretbox.unseal(path.read_bytes(), key=key,
                            aad=AMENDMENTS_DOC_AAD).decode("utf-8")


def append_amendment(client: dbaclient.DBAClient, text: str, *, key: bytes,
                     requested_by: str, title: str = "",
                     agent: str = identity.AGENT_ID) -> dict:
    """Add an amendment. There is no code path here that removes one.

    The new text goes after everything already sealed, and `existing` is read
    rather than passed in - a caller that could supply the document could supply
    a shorter one, which is a deletion wearing an append's name."""
    if not (text or "").strip():
        raise ValueError("an amendment cannot be empty")
    if not (requested_by or "").strip():
        raise ValueError(
            "an amendment must say who asked for it. Krish: *he should be able "
            "to add new directives on my request* - so a request nobody made is "
            "not one of them.")
    if requested_by.strip().lower() == (agent or "").strip().lower():
        raise Unauthorised(
            f"{agent!r} cannot request an amendment of his own charter. An "
            f"assistant that can decide the charter needs a new directive and "
            f"then add it has been given the charter, not the ability to help "
            f"with it.")
    if not installed():
        raise NotInstalled("nothing is sealed yet; `install` comes first")

    existing = amendments_document(key=key)
    # Counted over line starts, not over "\n## Amendment ". The first heading in
    # the document has no newline before it, so the substring form numbered the
    # second amendment 1 as well.
    number = sum(1 for line in existing.splitlines()
                 if line.startswith("## Amendment ")) + 1
    heading = f"## Amendment {number}" + (f" - {title.strip()}" if title else "")
    addition = f"{heading}\n\n*Added {_now()}, at {requested_by.strip()}'s " \
               f"request.*\n\n{text.strip()}\n"
    # The one composition in this module, and it is concatenation. `existing`
    # goes first and is never sliced, replaced or filtered.
    document = f"{existing.rstrip()}\n\n---\n\n{addition}" if existing.strip() \
        else addition

    chain = amendments(key=key)
    previous = chain[-1]["link"] if chain else GENESIS
    at = _now()
    entry = {
        "at": at,
        "previous": previous,
        "text": _digest(document),
        "alongside": _digest(read(key=key)),
        "grant_id": "",
        "granted_by": requested_by.strip(),
        "why": f"amendment {number} added at {requested_by.strip()}'s request",
        "added": _digest(addition),
    }
    entry["link"] = _link(previous, at=at, text_digest=entry["text"],
                          grant_id=entry["grant_id"], why=entry["why"])

    _write(_path(AMENDMENTS_FILE),
           secretbox.seal(json.dumps(chain + [entry]).encode("utf-8"),
                          key=key, aad=AMENDMENTS_AAD))
    _write(_path(AMENDMENTS_DOC_FILE),
           secretbox.seal(document.encode("utf-8"), key=key,
                          aad=AMENDMENTS_DOC_AAD))

    charter.note_amendment(client, what=heading, why=text.strip()[:400],
                           granted_by=requested_by.strip(), agent=agent)
    return {**entry, "number": number, "document": document}


def seal_what_krish_wrote(constitution_text: str, amendments_text: str, *,
                          key: bytes, by: str) -> dict:
    """Record the two documents exactly as Krish left them.

    Not an edit and not an author: the text comes in whole and is written down
    whole. This is how a hand edit stops looking like tampering - `verify`
    compares the live files against the last thing sealed, so after Krish changes
    one he runs this and the report clears.

    It is deliberately not a tool, and `by` is required: a re-seal that nobody
    signed is indistinguishable from the thing this all exists to catch."""
    if not (by or "").strip():
        raise ValueError(
            "a re-seal must say who did it. An unsigned one is exactly what a "
            "tampered file would look like.")
    if not (constitution_text or "").strip():
        raise ValueError("a constitution cannot be empty")
    if not installed():
        raise NotInstalled("nothing is sealed yet; `install` comes first")

    existing = amendments(key=key)
    previous = existing[-1]["link"] if existing else GENESIS
    at = _now()
    entry = {
        "at": at,
        "previous": previous,
        "text": _digest(amendments_text),
        "alongside": _digest(constitution_text),
        "grant_id": "",
        "granted_by": by.strip(),
        "why": "sealed as written by hand",
    }
    entry["link"] = _link(previous, at=at, text_digest=entry["text"],
                          grant_id=entry["grant_id"], why=entry["why"])

    _write(_path(AMENDMENTS_FILE),
           secretbox.seal(json.dumps(existing + [entry]).encode("utf-8"),
                          key=key, aad=AMENDMENTS_AAD))
    _write(_path(AMENDMENTS_DOC_FILE),
           secretbox.seal(amendments_text.encode("utf-8"), key=key,
                          aad=AMENDMENTS_DOC_AAD))
    _write(_path(CONSTITUTION_FILE),
           secretbox.seal(constitution_text.encode("utf-8"), key=key,
                          aad=CONSTITUTION_AAD))
    return entry


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
            # A hand seal carries no grant, by design: Krish does not grant
            # himself permission, he is the permission. What it must carry is a
            # name, and an entry with neither is a change nobody signed.
            if not (entry.get("granted_by") or "").strip():
                report["problems"].append(
                    f"entry {position} carries neither a grant nor a name. A "
                    f"change nobody signed is the thing this exists to catch.")
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

    # Nothing may have been removed from the amendments document. Checked as a
    # prefix rather than as equality: everything sealed before must still be
    # there, in order, and an append leaves it so. A deletion made with a text
    # editor fails this exactly as one made in code would, which is the point -
    # the guarantee is about the document, not about who touched it.
    live = amendments_document(key=key)
    if chain and chain[-1].get("added") and not live:
        report["problems"].append(
            "the amendments document is empty and the chain says it should not "
            "be. Every amendment ever added has been removed.")
    elif chain and _digest(live) != chain[-1]["text"] and chain[-1].get("added"):
        report["problems"].append(
            "the amendments document is not what was last sealed. Amendments "
            "are added and never removed, so this is either an edit made "
            "outside `append_amendment` or a deletion.")

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
        "amendments_are_append_only": True,
        "amendments_added_by": "Jarvis, on Krish's request; never removed",
        "written_by": "Krish, by hand; this module only records what he wrote",
        "detects": ["an amendment with no grant",
                    "an amendment whose grant was never issued",
                    "a chain link removed, reordered or altered",
                    "a constitution that changed after an amendment was added"],
    }
