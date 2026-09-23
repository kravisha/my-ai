"""Who Jarvis is, and which build of him is running.

Two questions the Persistence specification keeps asking and the repository had
no single answer to:

**§38 q12 — what identifies JARVIS across model replacements?** Not the model,
not the process, not the machine. `AGENT_ID` is a constant in this file. It was
tempting to derive it from something - a hostname, a database row, the model
name - and every one of those is a way for Jarvis to become somebody else by
being moved. §36 asks that a fresh model on a fresh machine reconstruct *the
same* Jarvis; an identity that changes when the machine does cannot do that.

**"I know which code version I am running" (§36).** `code_version()` answers it
from git where git is available, and from `DEPLOYED-COMMIT.txt` where it is not
- which is the case that matters, because the relaunched runtime in §21 step 6
is the one that must verify the approved change is present, and it may be
running from a checkout the supervisor prepared.

Neither answer is guessed. `code_version()` returns `None` rather than a
plausible string when it cannot tell, because §21 asks the new runtime to
*verify* the version and a made-up answer would pass that check while meaning
nothing.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# The stable identity. A constant, deliberately.
AGENT_ID = "jarvis"

# The name the DBA's policy knows this agent by. Different from `AGENT_ID` on
# purpose: one is who Jarvis is, the other is how a particular service
# addresses him, and collapsing them would mean a rename on either side
# silently rewrote his identity.
DBA_AGENT_NAME = "JARVIS"

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Written by the build/relaunch controller (`scripts/keep-jarvis-up.ps1`) when
# it deploys an approved commit. Present on a deployed machine, absent in a
# developer checkout - which is why git is tried first and this second.
DEPLOYED_COMMIT_FILE = "DEPLOYED-COMMIT.txt"

VERSION_ENV = "JARVIS_CODE_VERSION"

# Who a commit Jarvis makes is authored by. Stated here rather than inherited
# from whatever `git config` happens to hold on the machine, for two reasons and
# the second is the one that bit:
#
# A commit Jarvis wrote should say Jarvis wrote it. Inheriting the identity means
# a candidate change Krish has not seen arrives in the history under his name,
# which is Amendment 3's first item - a record that claims to come from somebody
# else - reached by doing nothing in particular.
#
# And `git commit` with no identity configured does not fall back to anything. It
# fails, with "Author identity unknown". A CI runner has none, and neither does a
# fresh Windows account, so self-modification worked only on machines where
# somebody had already set git up by hand. It failed on the one place it most
# needs to work.
GIT_AUTHOR_NAME = AGENT_ID
GIT_AUTHOR_EMAIL = f"{AGENT_ID}@localhost"


def git_identity() -> tuple[str, ...]:
    """The `-c` flags that make a `git` invocation carry Jarvis's identity.

    Passed per-invocation rather than written into any config file: this must
    not change what the rest of the machine's git does, and a repository whose
    config Jarvis edits is one he can later commit through as somebody else."""
    return ("-c", f"user.name={GIT_AUTHOR_NAME}",
            "-c", f"user.email={GIT_AUTHOR_EMAIL}")


# What a durable state record is shaped like. Bumped when a restore of an older
# record would need converting; `rehydrate` refuses a state it does not
# understand rather than reading it optimistically.
STATE_SCHEMA_VERSION = 1


def code_version() -> str | None:
    """The commit this runtime is running, or `None` if it cannot be determined.

    Order: an explicit environment override, then the file the deployer writes,
    then git. The override exists for the test that needs a known value and for
    a container that has neither of the other two."""
    override = (os.environ.get(VERSION_ENV) or "").strip()
    if override:
        return override

    stamped = PROJECT_ROOT / DEPLOYED_COMMIT_FILE
    try:
        text = stamped.read_text(encoding="utf-8").strip()
    except OSError:
        text = ""
    if text:
        return text.split()[0]

    try:
        result = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    commit = (result.stdout or "").strip()
    return commit if result.returncode == 0 and commit else None


def describe() -> dict:
    """Identity as a restored runtime should report it.

    `code_version` may be `None`, and it is reported as `None` rather than as
    "unknown" so that a caller comparing versions cannot match on the word."""
    return {
        "agent_id": AGENT_ID,
        "dba_agent_name": DBA_AGENT_NAME,
        "code_version": code_version(),
        "state_schema_version": STATE_SCHEMA_VERSION,
    }
