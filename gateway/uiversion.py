"""One source of truth for which build of the voice client is current.

Why this exists as a module rather than a string in two places: today Krish and I
lost time three separate times to a browser serving a cached page. Each time, both
of us were reasoning about code that was not the code on his screen — he reported a
button as broken that I had already fixed, and I told him it was fixed while he was
looking at the version where it was not.

A version he can read off the screen ends that, but only if the agent knows the
same number. Otherwise the agent nods along with whatever the owner reports and the
confusion survives. So the page and the prompt read from **here**, and the number is
derived from the file's own modification time rather than typed, because a
hand-maintained version is wrong the first time somebody forgets to bump it — and
forgetting is exactly what happens during a long day of small fixes.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

VOICE_PAGE = Path(__file__).resolve().parent / "static" / "voice.html"


def current() -> dict:
    """The version of the voice client as it exists on disk right now.

    Returned as a dict rather than a string because the page and the prompt want
    different parts of it, and formatting it in two places is how they drift.
    """
    try:
        mtime = VOICE_PAGE.stat().st_mtime
    except OSError:
        # A missing page is a real failure, but not one this function should raise
        # into a request. Report it as an unusable version rather than crash.
        return {"version": "unknown", "built": "unknown", "ok": False}

    when = datetime.fromtimestamp(mtime)
    return {
        # Sortable and comparable by eye: a later build is a larger number.
        "version": when.strftime("%Y%m%d.%H%M"),
        "built": when.strftime("%H:%M:%S on %d %b"),
        "ok": True,
    }


def prompt_paragraph() -> str:
    """What the agent is told about versions, so it can correct the owner.

    Deliberately instructs the agent to *volunteer* the right number rather than
    merely confirm a wrong one. An agent that answers "yes that sounds right" to a
    stale version is worse than one that says nothing, because it ends the
    investigation.
    """
    info = current()
    if not info["ok"]:
        return ""
    return (
        "\nAbout the page the owner is using:\n"
        f"- The current version of this voice page is {info['version']}, built "
        f"{info['built']}. The version is printed at the bottom of the page.\n"
        "- If he tells you a version that is not that one, or says a button does "
        "nothing, say plainly that he is on an old cached copy, give him "
        f"{info['version']} as the version he should see, and tell him to close the "
        "tab and open it again — in a private tab if it persists.\n"
        "- Do not agree that his version sounds right unless it matches exactly. "
        "Agreeing with a stale version ends the investigation and wastes his time."
    )
