"""Files and images arriving from the owner's phone.

Krish, 2026-09-16 17:36, by phone from abroad: *"Please add FILE AND IMAGE
ATTACHMENTS to the Jarvis chat interface. I should be able to send files and
images through the same text box I currently use for typing or voice input."*

One module owns everything about a received file: what may be sent, how large,
what it is called on disk, and the two sentences written about it afterwards -
one for the assistant reading the turn, one for the engineer session reading the
channel. The route, the socket and the page all go through here, so there is a
single answer to "is this allowed" rather than three that drift.

## Where the files land, and why it is that directory

`C:\\Users\\Krish\\Documents\\Aria-Claude-Communications\\attachments`, beside the
three message files. That is not tidiness - it is the whole point. The Claude
session on this machine can read that directory and nothing else outside the
deployment folder, so a photo Krish sends is a photo Claude can actually open.
A file saved anywhere else would be a filename in a log and no more.

## What this module deliberately does not do

**It does not show an image to the model.** The stored transcript is text
(`gateway/store.py` keeps one string per turn) and the model is handed that
text, so an image block would have to change the shape of the conversation
record. That is a real change with its own failure modes and it is not this one.
Until it exists, an image reaches the assistant as its name, type and size, and
the prompt says plainly that he cannot see inside it - because the failure worth
avoiding is not "Jarvis cannot read the photo", it is Jarvis describing a photo
he never saw.

**It does not delete.** Nothing here removes a file, including on a failed
upload. The standing instruction for this host grants no deletion, and an
attachment directory that grows is a cheaper problem than one that quietly ate
something the owner sent from another continent.

**It does not execute or open anything.** Bytes are written, a name is recorded,
and the extension is checked against an allowlist. A `.docx` here is a blob with
a name, not a document that gets parsed.

## Base64 in a JSON body rather than multipart

`python-multipart` is not installed in this deployment's virtual environment and
`UploadFile` needs it. Installing a package onto the machine that is the owner's
only line of contact, unattended, to save a third of the bytes on a five-megabyte
photo is the wrong trade this week. So the page sends the file base64-encoded in
the JSON body it already knows how to authenticate. The cost is a 33% larger
upload and it is stated in the limits; the benefit is that this ships without
touching the environment the Gateway boots from.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime
from pathlib import Path

DIRECTORY_ENV = "JARVIS_ATTACHMENTS_DIR"

# Beside the message files, for the reason in the docstring: this is the one
# directory both the Gateway and the Claude session can see.
DEFAULT_DIRECTORY = Path(
    r"C:\Users\Krish\Documents\Aria-Claude-Communications\attachments"
)

# A phone photo is two to five megabytes and a scanned PDF can be ten. Fifteen
# leaves room for both without inviting a video, which is the first thing that
# would arrive if this were unbounded - and a video is minutes of upload on a
# hotel connection with no progress bar worth the name.
#
# Binary megabytes, so `human_size` prints "15.0 MB" rather than the 14.3 MB a
# round decimal number would produce. The refusal names the limit, and a ceiling
# that describes itself as 14.3 when the page says 15 is a message that reads
# like a bug in front of the person least able to check.
MAX_BYTES = 15 * 1024 * 1024

# Per message, not per day. Four is what a hand can attach on a phone screen
# before the tray is taller than the keyboard, and it bounds the manifest the
# assistant is handed.
MAX_PER_MESSAGE = 4

# How much of a text file is quoted into the turn. The assistant is handed the
# contents of anything genuinely textual, because a note or a CSV he cannot read
# is an attachment that arrived nowhere. Bounded because the whole transcript is
# re-sent every turn (see gateway/conversation.model_messages), so an unbounded
# paste is a cost the owner pays on every subsequent question in the
# conversation, not once.
INLINE_MAX_CHARS = 4_000

IMAGE = "image"
DOCUMENT = "document"

# Extension -> (kind, content type). The extension is the whole allowlist: it
# decides whether the upload is accepted, what the page's picker offers, and what
# the assistant is told it is. `tests/test_gateway_attachments.py` asserts this
# table and the page's `accept` attributes describe the same set, which is the
# drift that would otherwise show up as a file the picker offers and the server
# refuses - after the upload.
ALLOWED: dict[str, tuple[str, str]] = {
    ".png": (IMAGE, "image/png"),
    ".jpg": (IMAGE, "image/jpeg"),
    ".jpeg": (IMAGE, "image/jpeg"),
    ".gif": (IMAGE, "image/gif"),
    ".webp": (IMAGE, "image/webp"),
    ".heic": (IMAGE, "image/heic"),
    ".heif": (IMAGE, "image/heif"),
    ".pdf": (DOCUMENT, "application/pdf"),
    ".txt": (DOCUMENT, "text/plain"),
    ".md": (DOCUMENT, "text/markdown"),
    ".csv": (DOCUMENT, "text/csv"),
    ".json": (DOCUMENT, "application/json"),
    ".log": (DOCUMENT, "text/plain"),
    ".rtf": (DOCUMENT, "application/rtf"),
    ".doc": (DOCUMENT, "application/msword"),
    ".docx": (DOCUMENT,
              "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".xls": (DOCUMENT, "application/vnd.ms-excel"),
    ".xlsx": (DOCUMENT,
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".ppt": (DOCUMENT, "application/vnd.ms-powerpoint"),
    ".pptx": (DOCUMENT,
              "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
}

# The ones worth quoting into the conversation rather than only naming.
TEXTLIKE = frozenset({".txt", ".md", ".csv", ".json", ".log"})

# First bytes that must match, for the formats where a mismatch means the file is
# not what its name claims. Not a security boundary - nothing here opens the
# file - but it catches the real case: a picker or a share sheet handing over a
# HEIC renamed .jpg, which would reach the assistant described as something it is
# not. Formats absent from this table are stored without a content check.
MAGIC: dict[str, tuple[bytes, ...]] = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".pdf": (b"%PDF-",),
    # The OOXML family is a zip. An empty zip ("PK\x05\x06") is accepted too: it
    # is a valid, useless document and refusing it would be a lie about why.
    ".docx": (b"PK\x03\x04", b"PK\x05\x06"),
    ".xlsx": (b"PK\x03\x04", b"PK\x05\x06"),
    ".pptx": (b"PK\x03\x04", b"PK\x05\x06"),
}

# Identifiers this module issues, and the only shape it will look up. Checked
# before any path is built from a caller's string: the lookup globs
# `<id>-*` inside one directory, and an id that cannot contain a separator or a
# dot cannot walk out of it.
ID_PATTERN = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$")

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_NAME_MAX = 80


class AttachmentError(ValueError):
    """A refusal with a sentence the owner can act on.

    `reason` is written for a phone screen: what was wrong and what to do, not a
    code. It travels to the page as an HTTP detail and is read aloud there.
    """

    def __init__(self, reason: str, status: int = 400):
        super().__init__(reason)
        self.reason = reason
        self.status = status


def directory() -> Path:
    """Where attachments are kept, read from the environment every call.

    Every call rather than once at import, so a test can point it at a temporary
    path with `monkeypatch.setenv` - the same arrangement `_inbox_path` and the
    relay channel use in `gateway/main.py`. Nothing here creates it; `save` does,
    at the moment there is something to put in it.
    """
    configured = os.environ.get(DIRECTORY_ENV)
    return Path(configured) if configured else DEFAULT_DIRECTORY


def human_size(size: int) -> str:
    """A size as it should be read aloud. The page shows this string and so does
    the manifest, so "1.2 MB" is written once."""
    if size < 1024:
        return f"{size} bytes"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def safe_name(name: str) -> str:
    """The original filename, reduced to something that cannot be a path.

    Everything outside `[A-Za-z0-9._-]` collapses to an underscore, which takes
    the separators, the colon a Windows drive letter needs, and the `..` of a
    traversal - `..` survives as characters but has nowhere to go, because the
    result is only ever appended to an id that is matched against ID_PATTERN
    inside one directory. Leading dots are stripped so nothing lands as a hidden
    file, and the length is capped because the stored name is the id plus this
    plus a directory that is already deep.
    """
    base = os.path.basename((name or "").strip().replace("\\", "/"))
    base = _SAFE_NAME.sub("_", base).lstrip(".")
    if len(base) > _NAME_MAX:
        stem, dot, extension = base.rpartition(".")
        if dot and len(extension) <= 12:
            keep = _NAME_MAX - len(extension) - 1
            base = stem[:keep] + "." + extension
        else:
            base = base[:_NAME_MAX]
    return base or "attachment"


def classify(name: str) -> tuple[str, str, str]:
    """(extension, kind, content type) for a filename, or a refusal.

    The refusal names the file and lists nothing: a phone reading out twenty
    extensions is worse than "that is not a type I can take". The page's picker
    is what steers him to an accepted one.
    """
    extension = Path(safe_name(name)).suffix.lower()
    if not extension:
        raise AttachmentError(
            "That file has no extension, so I cannot tell what it is. Rename it "
            "with the right one - .pdf, .txt, .png and so on - and send it again.",
            status=415,
        )
    if extension not in ALLOWED:
        raise AttachmentError(
            f"I cannot take a {extension} file. Photos and images, PDFs, text and "
            "Office documents are the ones that go through.",
            status=415,
        )
    kind, content_type = ALLOWED[extension]
    return extension, kind, content_type


def _check_magic(extension: str, data: bytes) -> None:
    expected = MAGIC.get(extension)
    if not expected:
        return
    if not any(data.startswith(prefix) for prefix in expected):
        bare = extension.lstrip(".")
        raise AttachmentError(
            f"That file is named {extension} but its contents are not a "
            f"{bare} file. Some share sheets rename photos on the way out - try "
            "sending it from the photo library instead.",
            status=415,
        )


def save(name: str, data: bytes) -> dict:
    """Write one attachment and return its record.

    The id carries the time it arrived and eight hex of the content's hash:
    readable in a directory listing, unique per second per file, and stable - the
    same photo sent twice in the same second is the same id, which is the
    harmless outcome rather than two copies.
    """
    if not data:
        raise AttachmentError("That file is empty - nothing arrived to save.")
    if len(data) > MAX_BYTES:
        raise AttachmentError(
            f"That file is {human_size(len(data))} and the limit is "
            f"{human_size(MAX_BYTES)}. Send a smaller one, or a photo rather than "
            "a video.",
            status=413,
        )

    extension, kind, content_type = classify(name)
    _check_magic(extension, data)

    clean = safe_name(name)
    digest = hashlib.sha256(data).hexdigest()[:8]
    now = datetime.now().astimezone()
    identifier = f"{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}-{digest}"
    target_dir = directory()
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{identifier}-{clean}"
        path.write_bytes(data)
    except OSError as error:
        # Said plainly rather than as a traceback: this is the failure where the
        # owner needs to know his file did not arrive, and it is the one an
        # engineer session will have to fix from the log.
        raise AttachmentError(
            f"I could not save that file on this machine: {error}", status=500
        ) from error

    return {
        "id": identifier,
        "name": clean,
        "stored": path.name,
        "path": str(path),
        "kind": kind,
        "extension": extension,
        "content_type": content_type,
        "size": len(data),
        "size_human": human_size(len(data)),
        "at": now.isoformat(timespec="seconds"),
    }


def load(identifier: str) -> dict | None:
    """The record for an id, or None. Never raises on a hostile string.

    None rather than an exception because every caller's answer to "that id is
    not here" is the same sentence, and because the ids come from a page that may
    have been reloaded since the upload - a stale id is an ordinary event, not an
    error condition.
    """
    if not identifier or not ID_PATTERN.match(identifier):
        return None
    try:
        matches = sorted(directory().glob(f"{identifier}-*"))
    except OSError:
        return None
    for path in matches:
        if not path.is_file():
            continue
        name = path.name[len(identifier) + 1:]
        extension = path.suffix.lower()
        kind, content_type = ALLOWED.get(extension, (DOCUMENT, "application/octet-stream"))
        try:
            size = path.stat().st_size
        except OSError:
            continue
        return {
            "id": identifier,
            "name": name,
            "stored": path.name,
            "path": str(path),
            "kind": kind,
            "extension": extension,
            "content_type": content_type,
            "size": size,
            "size_human": human_size(size),
            "at": "",
        }
    return None


def resolve(identifiers) -> tuple[list[dict], list[str]]:
    """(records, ids that are not here) for what the page says it attached.

    Order is preserved and duplicates are dropped: "1 of 3" in the manifest has
    to match what he sees in the tray, and the same id twice would be described
    as two files.
    """
    records: list[dict] = []
    missing: list[str] = []
    seen: set[str] = set()
    for identifier in (identifiers or []):
        key = str(identifier)
        if key in seen:
            continue
        seen.add(key)
        record = load(key)
        if record is None:
            missing.append(key)
        else:
            records.append(record)
    return records, missing


def public(record: dict) -> dict:
    """The record as the page receives it.

    The absolute path is left out. The page has no use for it, it would put this
    machine's directory layout into anything that logs a response body, and the
    page already knows the file by the id it was given.
    """
    return {
        "id": record["id"],
        "name": record["name"],
        "kind": record["kind"],
        "size": record["size"],
        "size_human": record["size_human"],
        "content_type": record["content_type"],
        "at": record.get("at", ""),
    }


def inline_text(record: dict) -> str | None:
    """The contents of a textual attachment, bounded, or None.

    `errors="replace"` rather than a failure: a CSV saved in some other encoding
    should reach the assistant slightly mangled rather than not at all, and the
    replacement characters are visible in the quote so nobody mistakes it for
    clean text.
    """
    if record.get("extension") not in TEXTLIKE:
        return None
    try:
        body = Path(record["path"]).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    body = body.strip()
    if not body:
        return "(the file is empty)"
    if len(body) > INLINE_MAX_CHARS:
        return (body[:INLINE_MAX_CHARS]
                + f"\n... [truncated here; the file is {len(body)} characters]")
    return body


def describe_for_model(records: list[dict]) -> str:
    """What is appended to the owner's message when he attaches something.

    Appended to the text rather than sent beside it, because the transcript is
    one string per turn: a manifest kept out of the text would be invisible to
    every later turn in the conversation, and "what did I send you earlier" is
    the obvious second question.

    The sentence about not being able to see inside an image is the one that
    earns this function. Handed a filename and nothing else, a model asked what
    is in the photo will describe a photo. Saying the limit here means the answer
    is "I cannot see it, and Claude can" instead of an invention.
    """
    if not records:
        return ""
    count = len(records)
    lines = [
        "",
        "---",
        (f"He attached {count} file{'s' if count != 1 else ''} to this message "
         "through the attach button in box 1. They are saved on this machine, in "
         "the folder the Claude engineer session can read, so Claude can open them "
         "and you cannot. Do not describe or guess at the contents of an image, a "
         "PDF or an Office document - say that Claude can look at it. Text files "
         "are quoted in full below and those you can use."),
        "",
    ]
    for index, record in enumerate(records, start=1):
        lines.append(
            f"{index}. {record['name']} - {record['kind']}, {record['size_human']} "
            f"- attachment id {record['id']}"
        )
        body = inline_text(record)
        if body is not None:
            lines.append("   contents:")
            lines.append("   <<<")
            lines.extend("   " + line for line in body.splitlines())
            lines.append("   >>>")
    return "\n".join(lines)


def channel_block(records: list[dict]) -> str:
    """What is appended to the entry Claude reads, and it is mostly one thing: the
    path.

    An attachment described without its path is a message telling an engineer
    that a file exists somewhere on the machine he is on. The path is what makes
    this feature work at all from the receiving end - it is what he opens.
    """
    if not records:
        return ""
    count = len(records)
    lines = [
        "",
        f"ATTACHMENTS ({count}), saved by the Gateway on this machine. Open them at "
        "the paths below:",
        "",
    ]
    for record in records:
        lines.append(
            f"- {record['name']} - {record['kind']}, {record['size_human']} - "
            f"{record['path']}"
        )
    # Trailing newline: this block is the last thing in an append-only file, and
    # the next entry's header has to start on its own line.
    lines.append("")
    return "\n".join(lines)


def prompt_paragraph() -> str:
    """The limits, generated for the operator's prompt.

    Generated rather than typed for the reason `gateway/interface.py` generates
    the control list: the numbers here are enforced by this module, and a prompt
    that promised a twenty-megabyte ceiling while the route refused at fifteen
    would be the assistant telling him to try something that cannot work.
    """
    kinds = sorted({extension for extension in ALLOWED})
    return (
        "\n\nAttachments. He can attach files and images to box 1 with the "
        f"attach button, up to {MAX_PER_MESSAGE} at a time and "
        f"{human_size(MAX_BYTES)} each. Accepted: {', '.join(kinds)}. "
        "They arrive appended to his message as a list of names, types and sizes. "
        "Text files (.txt, .md, .csv, .json, .log) are quoted to you in full and "
        "you can work with them. You cannot see inside an image, a PDF or an "
        "Office document - only its name and size - so never describe the "
        "contents of one. Say that Claude can open it, because every attachment "
        "is saved where the Claude session on this machine reads. If he attaches "
        "something while a message is bound for Claude in box 2, the file travels "
        "with whichever message he sends next and Claude is given the path to it."
    )
