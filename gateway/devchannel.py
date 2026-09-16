"""A file Jarvis and the Claude session on this machine both write into.

Krish, 2026-09-16 12:03, from abroad and by phone:

    "I would like a more direct communication channel between you and Jarvis.
     Perhaps he can be allowed to send you messages on this channel but on the
     condition that he identifies himself as Jarvis explicitly and so you can
     know. ... So as the next task can you create a direct channel with Jarvis so
     that I can get your status directly from Jarvis."

The condition he attached is the design. Every entry is headed with who spoke,
and the two speakers get two different header words, so "a machine is talking"
is written into the record rather than inferred from the content.

## What already existed, and the half that did not

Jarvis could reach Claude, through Krish's thumb: `draft_message_to_claude`
fills box 2 on the voice page, Krish presses send, and the line lands in
`KRISH-TO-CLAUDE-DEPLOY.md` headed `KRISH-VIA-JARVIS`. That path stays exactly
as it is, and this module does not touch it - see `gateway/interface.py` for why
the press is his.

The half that has never existed in any form is the other direction: **Jarvis has
never been able to read anything Claude said.** Everything he could not tell
Krish on 2026-09-16 - the missing backend credentials, the page version, that he
had no way to wake anybody - was diagnosable from inside this host, and each one
had to travel to another continent and come back before it reached the machine it
was about. `read_claude` is the fix for that, and it is why it was built first.

## Why its own file and not the shared conversation

`Arya-Claude - Ongoing Conversation.md` is polled *by size* by the wake task on
`krish-dev`. A chatty assistant appending to it would wake another engineer's
session on every remark. And `KRISH-TO-CLAUDE-DEPLOY.md` is worse: it is the file
whose growth wakes this session, and every line in it is attributed to Krish's
direction. A machine writing there would be waking an agent in his name.

So: a third file, same entry shape as the other two, so one parser reads all
three and a person needs to be taught nothing new to read it.

## The limits are here, not left to good behaviour

This machine is unattended for a week. An assistant in a loop with an
append-only file is a disk filler and, once the wake task polls this file, an
unbounded generator of Claude sessions. `MAX_PER_WINDOW` and `MAX_FILE_BYTES`
are what make "Jarvis may write whenever he likes" a safe sentence, and both
refuse as *data* so the model reads the refusal and stops rather than the turn
collapsing.

One rule here is **not** enforced in code, and saying so is better than a regex
that pretends: `message_claude` must not be used to pass on something Krish said.
That is box 2's job, because box 2's entry says he directed it. This channel's
header never says his name, so the worst case of the rule being broken is Claude
reading a quote attributed to a machine - which is legible as exactly that.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

# The two speakers. Two header words rather than one shared "CHANNEL" header,
# for the reason Claude Dev gave when he wrote into this session's inbox by hand
# and deliberately did *not* forge a `KRISH-VIA-JARVIS` line: the header is the
# record of who spoke, and a record that cannot distinguish a machine from the
# owner stops being evidence of either.
SPEAKER_JARVIS = "JARVIS-TO-CLAUDE-DEPLOY"
SPEAKER_CLAUDE = "CLAUDE-DEPLOY-TO-JARVIS"

DEFAULT_PATH = (r"C:\Users\Krish\Documents\Aria-Claude-Communications"
                r"\JARVIS-CLAUDE-CHANNEL.md")

# Smaller than the relay's 20,000. A message to an engineer session that shares
# this disk does not need to carry a document: it needs to name what is wrong and
# where to look, and Claude can read the file himself. The cap is also what stops
# one turn from writing a megabyte.
MAX_CHARS = 4_000

# At most three entries per wake window. The window is the wake task's own
# fifteen minutes on purpose: the ceiling is "what one Claude session will read
# in one sitting", so a fourth message in the same window is not being throttled
# out of caution, it is being told that nobody has read the first three yet.
MAX_PER_WINDOW = 3
WINDOW_MINUTES = 15

# A hard stop, independent of the rate. The rate limit bounds a loop that writes
# steadily; this bounds a year of legitimate use on a disk nobody is watching.
MAX_FILE_BYTES = 2_000_000


class ChannelRefused(Exception):
    """A write this channel will not take. Carried to the model as a string."""


def channel_path() -> Path:
    """Resolved per call, never at import.

    The same reason `gateway/main._inbox_path` does it this way: the tests set
    `JARVIS_DEV_CHANNEL` to a tmp_path, and a module-level constant would have
    them writing into the real channel on the real machine.
    """
    return Path(os.environ.get("JARVIS_DEV_CHANNEL") or DEFAULT_PATH)


def _stamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse_entries(raw: str) -> list[dict]:
    """Every entry in the file, oldest first, as `{at, speaker, text}`.

    Splits on the header rather than on `##`, so an entry whose body contains a
    markdown heading survives intact - the bodies here are written by models
    quoting logs, and a log line beginning `## ` is not hypothetical.
    """
    entries = []
    for chunk in raw.split("\n## ")[1:]:
        header, _, body = chunk.partition("\n")
        fields = header.split("|")
        text = body.strip()
        if not text:
            continue
        entries.append({
            "at": fields[0].strip(),
            "speaker": fields[1].strip() if len(fields) > 1 else "",
            "text": text,
        })
    return entries


def _read_raw() -> str:
    path = channel_path()
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def entries_from(speaker: str, *, limit: int | None = None) -> list[dict]:
    """One speaker's entries, oldest first, newest `limit` of them."""
    said = [entry for entry in parse_entries(_read_raw())
            if entry["speaker"] == speaker]
    if limit is not None and limit > 0:
        return said[-limit:]
    return said


def _within_window(stamp: str, now: datetime) -> bool | None:
    """True if `stamp` is inside the rate window, None if it cannot be dated."""
    try:
        when = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.astimezone()
    return (now - when) < timedelta(minutes=WINDOW_MINUTES)


def rate_check(now: datetime | None = None) -> str | None:
    """The reason this write is refused, or None.

    Counts backwards from the newest entry rather than filtering the whole file
    by timestamp, which is what makes an undateable entry harmless. Take the last
    `MAX_PER_WINDOW` things Jarvis said; if the oldest of those is still inside
    the window, the window is full.

    An unparseable stamp on that oldest entry allows the write. The alternative -
    refusing - would let one hand-edited line jam the channel permanently, with
    no way for anyone on this machine to clear it while Krish is away. The case
    the limit exists for is a model in a loop, and those entries carry stamps
    this module wrote itself.
    """
    now = now or datetime.now().astimezone()
    recent = entries_from(SPEAKER_JARVIS, limit=MAX_PER_WINDOW)
    if len(recent) < MAX_PER_WINDOW:
        return None
    oldest = _within_window(recent[0]["at"], now)
    if oldest is not True:
        return None
    return (
        f"You have written {MAX_PER_WINDOW} messages to Claude in the last "
        f"{WINDOW_MINUTES} minutes, which is the limit. He reads the channel "
        f"about every {WINDOW_MINUTES} minutes, so he has not seen those yet and "
        "a fourth would not reach him sooner. Tell Krish what you wanted to say "
        "instead, and say that the channel is at its limit rather than that it "
        "failed."
    )


def append_message(text: str, *, speaker: str = SPEAKER_JARVIS) -> dict:
    """Append one entry. Raises ChannelRefused for anything a model can cause.

    Append-only, and that is load-bearing in the same way it is for the other two
    files: this is a record of what was said between two parties on a machine
    nobody is sitting at, and a truncating write destroys the only account of it.
    """
    body = (text or "").strip()
    if not body:
        raise ChannelRefused(
            "Nothing to send. Pass the message itself as `text` - what is wrong, "
            "or what you want Claude to know, in your own words.")
    if len(body) > MAX_CHARS:
        raise ChannelRefused(
            f"That message is {len(body)} characters and the channel takes "
            f"{MAX_CHARS}. Say what is wrong and where to look rather than "
            "quoting it all - Claude can read the files on this machine himself.")

    path = channel_path()
    if not path.parent.is_dir():
        raise ChannelRefused(
            f"The channel directory {path.parent} is not on this machine, so "
            "there is nowhere to write. Report that rather than retrying.")
    if path.exists() and path.stat().st_size >= MAX_FILE_BYTES:
        raise ChannelRefused(
            f"The channel file has reached its {MAX_FILE_BYTES}-byte ceiling and "
            "is not being written to. Tell Krish, and say it needs Claude to "
            "archive it - nothing on this machine deletes files by itself.")

    refusal = rate_check()
    if refusal:
        raise ChannelRefused(refusal)

    stamp = _stamp()
    entry = f"\n## {stamp} | {speaker}\n\n{body}\n"
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(entry)
    return {"at": stamp, "speaker": speaker, "chars": len(body),
            "bytes": path.stat().st_size}


def read_from_claude(limit: int = 5) -> dict:
    """What Claude has said on the channel, oldest first.

    The direction that did not exist. Read-only and unrated: reading cannot fill
    a disk and cannot wake anybody, so there is nothing here to limit.
    """
    try:
        wanted = int(limit)
    except (TypeError, ValueError):
        wanted = 5
    wanted = max(1, min(wanted, 20))
    said = entries_from(SPEAKER_CLAUDE)
    if not said:
        return {
            "messages": [],
            "total": 0,
            "note": ("Claude has not written anything on the channel yet. That is "
                     "not a fault - say so plainly rather than treating it as an "
                     "error, and do not invent what he might have said."),
        }
    return {
        "messages": said[-wanted:],
        "total": len(said),
        "note": ("These are Claude's own words to you, from the shared channel. "
                 "He reads what you write about every "
                 f"{WINDOW_MINUTES} minutes, so a reply is minutes away, not "
                 "seconds."),
    }


def prompt_paragraph() -> str:
    """What the operator's assistant is told about the channel.

    Generated, like the page description in `gateway/interface.py` and the
    capability paragraph in `gateway/skills.py`, so the limits the model is told
    about are the constants that actually enforce them. A hand-typed "you may
    send three messages" is wrong the day the number changes and goes on sounding
    right.
    """
    return "\n".join([
        "",
        "## Your direct channel to Claude",
        "",
        "You have a shared file with Claude - the engineer session running on this "
        "same machine - and you can both write to it and read it. This is separate "
        "from box 2 on Krish's page, and the difference matters:",
        "",
        "- **Box 2** is Krish talking to Claude. You may draft into it; he presses "
        "send; the entry says he directed it.",
        "- **The channel** is you talking to Claude. You send it yourself, with no "
        "tap from anybody, because every entry is headed "
        f"\"{SPEAKER_JARVIS}\" and claims to be nothing else.",
        "",
        "Use `message_claude` when something is wrong with this machine, this "
        "Gateway, or your own tools. You are on the host: a broken credential, a "
        "stale page, a tool returning available=false - Claude can see and fix all "
        "of it from here, and telling Krish instead sends the problem abroad and "
        "back before it reaches the machine it is about. Say what you observed and "
        "what you were doing, not what you would like done.",
        "",
        "Use `read_claude` to see his replies, and read them before reporting to "
        "Krish on anything you have asked about - if Claude has already answered, "
        "his answer is the status, and Krish asked for exactly that: to get "
        "Claude's status from you directly.",
        "",
        f"Two limits. At most {MAX_PER_WINDOW} messages per {WINDOW_MINUTES} "
        "minutes, because that is how often he reads; a refusal means he has not "
        "seen the earlier ones yet, and you should tell Krish rather than retry. "
        "And do not use the channel to pass on something Krish said - that is box "
        "2's job, and it is what makes the line Claude receives in his own inbox, "
        "\"relayed by Jarvis at Krish's direction\", a true one. Speaking for "
        "yourself is the entire point of this file.",
    ])
