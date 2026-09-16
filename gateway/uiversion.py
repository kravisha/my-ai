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

WHY THE NUMBER COVERS THE CODE AND NOT ONLY THE PAGE, added 2026-09-16T16:05. It
counted the page alone until this afternoon, and Krish asked twice in one day
whether he had the latest version — at 06:11 and again at 15:25, the second time
hours after a release he had been told about. Both times the number was correct
and both times it told him less than he needed: the afternoon's work changed the
modules behind the page rather than the page itself, so a real deployment moved
nothing on his screen. A number that does not move when something ships teaches
the owner to distrust it, and a version he distrusts is worse than none, because
the next genuinely stale page will not be believed either.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

GATEWAY_CODE = Path(__file__).resolve().parent
VOICE_PAGE = GATEWAY_CODE / "static" / "voice.html"

# The code this process runs out of this repository: the Gateway package, and the
# shared model layer it imports directly (`app/model_gateway.py`, and the provider
# under it that every turn is spent through).
#
# The boundary is "what is imported into this process", and it is chosen rather
# than convenient. `backend/` is a separate service reached over HTTP, so a
# release there changes nothing about the page or the assistant answering on it,
# and dating this build by it would report a new build for a deployment the owner
# could not observe here. `app/` is the opposite case: it is in the import graph,
# so a change to it is a change to what he is talking to.
CODE_DIRS = (GATEWAY_CODE, GATEWAY_CODE.parent / "app")


def _code_mtime() -> float:
    """The newest modification time across the code this process runs.

    A deployment writes only the files it changed, so the newest of them is the
    moment that deployment landed — which is the thing Krish means when he asks
    for the version, and it needs no hand-maintained string and no git.
    """
    newest = 0.0
    for directory in CODE_DIRS:
        # A directory that is not there contributes nothing rather than raising:
        # `glob` on a missing path yields no entries, and a version is not worth
        # failing a request over.
        for path in directory.glob("*.py"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                # A module that disappears between the glob and the stat is not
                # worth failing a request over either; the remaining files still
                # date the build.
                continue
            newest = max(newest, mtime)
    return newest


# Snapshotted once, at import, and this is the whole subtlety of the module.
#
# The page is read from disk on every request, so its timestamp is a live fact.
# The code is not: `git pull` without a restart leaves this process running the
# modules it started with. Claude Dev did exactly that on Krish's live page on
# 2026-09-15 — the pull landed, the restart did not, and the handset served a raw
# placeholder for an hour. A version that stat'd the code per request would have
# announced the new build while still executing the old one, which is precisely
# the lie this module exists to prevent. Read at import, it dates the code that
# is actually running, and the number only moves after the restart that makes it
# true.
_RUNNING_CODE_MTIME = _code_mtime()


def current() -> dict:
    """The version of the Gateway the owner is being served right now.

    Returned as a dict rather than a string because the page and the prompt want
    different parts of it, and formatting it in two places is how they drift.
    """
    try:
        mtime = VOICE_PAGE.stat().st_mtime
    except OSError:
        # A missing page is a real failure, but not one this function should raise
        # into a request. Report it as an unusable version rather than crash.
        return {"version": "unknown", "built": "unknown", "ok": False}

    # The page's own mtime stays in the comparison rather than being replaced by
    # the code's: a page edited on the running host with no code change is still a
    # new build to the person looking at it, and it is the case the cache check
    # was built for.
    when = datetime.fromtimestamp(max(mtime, _RUNNING_CODE_MTIME))
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
        f"- The current version of this Gateway is {info['version']}, built "
        f"{info['built']}. It is printed at the bottom of the page, and it moves "
        "when either the page or the code behind it is deployed — so a release he "
        "was told about does show up here.\n"
        "- If he tells you a version that is not that one, or says a button does "
        "nothing, say plainly that he is on an old cached copy, give him "
        f"{info['version']} as the version he should see, and tell him to close the "
        "tab and open it again — in a private tab if it persists.\n"
        "- Do not agree that his version sounds right unless it matches exactly. "
        "Agreeing with a stale version ends the investigation and wastes his time."
    )
