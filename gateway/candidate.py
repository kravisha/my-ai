"""Where a candidate change to Jarvis's own code is written and tested.

Krish, 2026-09-23: *"At some point the idea is that Jarvis will be able to
change his own programming and test them out in a sandbox environment and then
seek approval to merge into master."*

## Why not `app/learning/sandbox.py`

That sandbox exists and cannot serve here, deliberately. It is read-only, has no
shell, and lists no interpreter, on its own stated grounds: *"a recipe able to
run `python` would be a recipe able to do anything, and the whole point of a
declarative skill is that it cannot."* Testing a code change means running
pytest, which means running Python. Extending that allow-list to permit it would
destroy the property it exists to hold.

So this is a second, different mechanism with a different shape: not an
allow-list of safe commands, but **an isolated copy of the repository**.

## A git worktree, and why that is the isolation

`git worktree add` gives a separate directory on its own branch, sharing the
object store and touching nothing in the live checkout. Candidate code is
written there, the suite runs there, and if it is all wrong the worktree is
removed and the running Jarvis never saw it.

This also fixes something I shipped and should not have.
`selfmod.commit_candidate` checked out its branch **in the live tree** - the one
the running Gateway imports from - so preparing a candidate mutated the
process's own source under it. That is the opposite of a sandbox.

## What may be written, and the rule that matters

Three rules, and the third is §16:

1. Only files inside the **approved scope**: the paths Krish named in the
   proposal, nothing else. Approving a change to one file is not approving a
   change to whatever else turns out to be convenient.
2. Only under `gateway/` and `app/`, and never a governance file - the same
   `introspect.may_modify` the proposal was checked against.
3. **An existing test may never be modified.** A new test file may be created,
   because §17 wants a test plan and a change usually needs one. But editing a
   test that exists is how *"redefine success criteria simply to make himself
   pass"* happens, and §16 forbids it at every boldness setting. Adding a test
   cannot weaken another test; editing one can.

## This module is itself out of reach

It needs `introspect.KEY_CIRCULAR`. A sandbox Jarvis could rewrite is a
sandbox that reports whatever he needs it to report, and the approval gate then
turns on a verdict he produced.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from gateway import introspect

logger = logging.getLogger("gateway.candidate")

WORKTREE_PREFIX = "jarvis-candidate-"

# Bounded, because this runs code that did not exist when the process started.
GIT_TIMEOUT_SECONDS = 300
TEST_TIMEOUT_SECONDS = 3600

# A file this size is not a source change. The cap is a cheap guard against a
# runaway generation filling a disk in a directory nobody is watching.
MAX_FILE_BYTES = 512_000


class WorkspaceRefused(PermissionError):
    """A write the sandbox will not perform, said with why."""


class WorkspaceUnavailable(RuntimeError):
    """The worktree could not be created. Distinct from a refusal: one is
    policy and never succeeds on retry, the other is the machine."""


def _git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd or introspect.PROJECT_ROOT), *args],
        capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS, check=False)


@dataclass
class Workspace:
    """One isolated copy of the repository, on its own branch."""

    path: Path
    branch: str
    scope: tuple[str, ...]
    written: list[str] = field(default_factory=list)

    # --- what may be written ---------------------------------------------------

    def _check(self, relative: str) -> Path:
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise WorkspaceRefused(
                f"{relative!r} is not a repository-relative path. A candidate "
                f"writes inside the workspace and nowhere else.")
        as_posix = candidate.as_posix()

        if as_posix not in self.scope:
            raise WorkspaceRefused(
                f"{as_posix} is not in the approved scope for this change "
                f"({', '.join(self.scope) or 'nothing'}). Approving a change to "
                f"one file is not approving a change to whatever else turns out "
                f"to be convenient.")

        if _is_existing_test(as_posix):
            raise WorkspaceRefused(
                f"{as_posix} is an existing test. §16 forbids redefining "
                f"success criteria to make yourself pass, and editing a test "
                f"that already exists is how that happens. A new test file is "
                f"allowed; changing one is not.")

        if not as_posix.startswith("tests/"):
            allowed, why = introspect.may_modify(as_posix)
            if not allowed:
                raise WorkspaceRefused(why)

        return self.path / candidate

    def write(self, relative: str, content: str) -> Path:
        """Write one file in the workspace. Refuses anything out of scope."""
        target = self._check(relative)
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise WorkspaceRefused(
                f"{relative} would be {len(content)} characters, over the "
                f"{MAX_FILE_BYTES}-byte cap. A source change is not this large.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        if relative not in self.written:
            self.written.append(relative)
        return target

    def read(self, relative: str) -> str:
        """Read a file as it stands in the workspace, scope or not.

        Reading is `introspect`'s business and is already granted; what is
        checked here is writing."""
        allowed, why = introspect.may_read(relative)
        if not allowed:
            raise WorkspaceRefused(why)
        return (self.path / relative).read_text(encoding="utf-8")

    # --- what it does ----------------------------------------------------------

    def test(self, targets: list[str] | None = None, *,
             timeout_seconds: int = TEST_TIMEOUT_SECONDS) -> dict:
        """Run the suite inside the workspace.

        A timeout and a crash are reported as *did not run*, never as a pass -
        the same distinction `selfmod.run_tests` makes, and for the same reason:
        "the tests failed" and "the tests did not run" lead to opposite next
        steps."""
        command = [sys.executable, "-m", "pytest", "-q"] + list(targets or [])
        try:
            result = subprocess.run(
                command, cwd=str(self.path), capture_output=True, text=True,
                timeout=timeout_seconds, check=False)
        except subprocess.TimeoutExpired:
            return {"passed": False, "ran": False, "in_workspace": str(self.path),
                    "why": f"the suite did not finish within {timeout_seconds}s",
                    "output": ""}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"passed": False, "ran": False, "in_workspace": str(self.path),
                    "why": f"could not run: {exc}", "output": ""}
        return {
            "passed": result.returncode == 0,
            "ran": True,
            "in_workspace": str(self.path),
            "why": "" if result.returncode == 0 else f"pytest exit {result.returncode}",
            "output": "\n".join((result.stdout or "").splitlines()[-40:]),
        }

    def diff(self) -> str:
        """What changed, for Krish to read before he approves anything."""
        result = _git("diff", cwd=self.path)
        untracked = _git("ls-files", "--others", "--exclude-standard", cwd=self.path)
        extra = ""
        for name in (untracked.stdout or "").split():
            extra += f"\n--- /dev/null\n+++ b/{name}\n"
        return (result.stdout or "") + extra

    def commit(self, message: str) -> str | None:
        """Commit the written files in the workspace. Returns the commit id.

        Stages only what was written, for the reason `selfmod` learned the hard
        way: `git add -A` sweeps in whatever else is lying about and commits
        changes nobody approved."""
        if not self.written:
            return None
        staged = _git("add", "--", *self.written, cwd=self.path)
        if staged.returncode != 0:
            raise WorkspaceUnavailable(
                f"could not stage the candidate: {staged.stderr.strip()[:300]}")
        committed = _git("commit", "-m", message, cwd=self.path)
        if committed.returncode != 0:
            raise WorkspaceUnavailable(
                f"could not commit the candidate: "
                f"{(committed.stderr or committed.stdout).strip()[:300]}")
        head = _git("rev-parse", "HEAD", cwd=self.path)
        return (head.stdout or "").strip() or None

    def discard(self) -> None:
        """Throw the candidate away entirely: worktree and branch both.

        The first version removed only the worktree, so every abandoned
        candidate left a branch behind for ever - and the next attempt at the
        same proposal then failed, because `worktree add -b` refuses a branch
        that already exists. Found by the probe run, not by the tests, which is
        the argument for probing.

        Use `keep()` instead when the candidate is good and its commit is going
        to be deployed."""
        self._remove_worktree()
        if self.branch:
            _git("branch", "-D", self.branch)

    def keep(self) -> None:
        """Remove the worktree but keep the branch and its commits.

        What a *successful* candidate gets: the code is going to be deployed
        from that branch, and the working copy has done its job."""
        self._remove_worktree()

    def _remove_worktree(self) -> None:
        _git("worktree", "remove", "--force", str(self.path))
        if self.path.exists():
            shutil.rmtree(self.path, ignore_errors=True)
        _git("worktree", "prune")


def _is_existing_test(as_posix: str) -> bool:
    """Whether this path is a test that already exists in the live repository.

    Checked against the live tree rather than the workspace, so a candidate
    cannot delete a test in the worktree and then write a weaker one under the
    same name."""
    if not as_posix.startswith("tests/"):
        return False
    return (introspect.PROJECT_ROOT / as_posix).exists()


def open_workspace(*, branch: str, scope: list[str],
                   base: str | None = None) -> Workspace:
    """Create the worktree. Refuses a scope it would not let anything write to.

    The scope is checked here, up front, rather than at the first write: a
    workspace opened for a change that can never be written is a failure worth
    having before any code is generated."""
    cleaned = []
    for path in scope:
        as_posix = Path(path).as_posix()
        if _is_existing_test(as_posix):
            raise WorkspaceRefused(
                f"{as_posix} is an existing test and is not writable by a "
                f"candidate. §16: success criteria are not the candidate's to "
                f"redefine.")
        if not as_posix.startswith("tests/"):
            allowed, why = introspect.may_modify(as_posix)
            if not allowed:
                raise WorkspaceRefused(why)
        cleaned.append(as_posix)
    if not cleaned:
        raise WorkspaceRefused(
            "a candidate needs an approved scope; there is nothing it may write.")

    directory = Path(tempfile.mkdtemp(prefix=WORKTREE_PREFIX))
    # mkdtemp made it; git insists on creating the worktree directory itself.
    directory.rmdir()

    # A branch that already exists is reused rather than refused. The proposal
    # names one target branch, so a second attempt at the same change - after a
    # failed test run, or after a restart - arrives here with the same name. The
    # first version passed `-b` unconditionally and git refused, which turned
    # "try again" into a permanent failure.
    exists = _git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    args = (["worktree", "add", str(directory), branch] if exists.returncode == 0
            else ["worktree", "add", "-b", branch, str(directory)]
                 + ([base] if base else []))
    result = _git(*args)
    if result.returncode != 0:
        directory.parent.joinpath(directory.name).exists() and shutil.rmtree(
            directory, ignore_errors=True)
        detail = (result.stderr or result.stdout).strip()[:300]
        raise WorkspaceUnavailable(
            f"could not create a worktree for {branch}: {detail}"
            + (" - it may already be checked out in another workspace"
               if "already used by worktree" in detail else ""))
    logger.info("candidate workspace for %s at %s", branch, directory)
    return Workspace(path=directory, branch=branch, scope=tuple(cleaned))


def describe() -> dict:
    return {
        "isolation": "git worktree",
        "may_write": list(introspect.MODIFIABLE_ROOTS) + ["tests/ (new files only)"],
        "needs_a_separate_key": list(introspect.CIRCULAR),
        "test_timeout_seconds": TEST_TIMEOUT_SECONDS,
        "max_file_bytes": MAX_FILE_BYTES,
        "why_not_the_learning_sandbox":
            "app/learning/sandbox.py lists no interpreter on purpose; testing a "
            "code change means running pytest, and widening that allow-list "
            "would destroy the property it exists to hold",
    }
