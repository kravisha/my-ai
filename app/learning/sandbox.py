"""Where a skill is practised, and the two lists Jarvis cannot extend
(Document 1 §13).

> *"Jarvis must not learn by experimenting recklessly against the live system."*

Everything a recipe can reach passes through here. Two allow-lists define that
reach, both fixed in this module:

- `READ_PATTERNS` — the paths a recipe may read.
- `COMMANDS` — the programs a recipe may run, by name, with no shell.

**Jarvis composes primitives; it cannot add one, and it cannot extend either
list.** That is `app/initiative.HARM_WIDENS_ITS_OWN_AUTHORITY` applied where it
would otherwise be easiest to lose: a learning engine whose first lesson was
"add the command you need to the allow-list" has no allow-list.

When a skill genuinely needs something not here, the outcome is a boundary
proposal (`app/boundaries.py`) naming the command and what it would cost —
which is the mechanism Krish asked for on the same day, doing the job it was
built for. `SandboxRefusal` carries that sentence so the engine can file one.

## Every command here is read-only, and that is the selection rule

Not "low risk" or "commonly safe": each program listed reports state and has no
mode that changes any. `netstat`, `ss`, `ps`, `tasklist` and the rest print and
exit. Anything with a write mode - a package manager, an editor, `wmic`, and
above all an interpreter - is absent, because a recipe able to run `python`
would be a recipe able to do anything, and the whole point of a declarative
skill is that it cannot.

There is no shell. Commands run as an argv list, so quoting, pipes, redirection
and substitution do not exist as concepts here rather than being escaped.

## Bounded in four directions

A learning loop runs unattended and a sandbox that could hang, fill a disk or
fetch the internet would be a worse problem than the one it solves. Every call
is bounded on **time** (`DEFAULT_TIMEOUT`), **output size** (`MAX_OUTPUT`),
**path** (the read patterns) and **network** (nothing here opens a socket, and
no listed command takes a URL).

## Practice runs in a temporary directory that is deleted

`Sandbox` is a context manager over `tempfile.mkdtemp`. Files a recipe writes
during practice go there and nowhere else, and leaving the block removes them -
which is what makes an experiment reversible in the sense
`app/initiative.py` means.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Seconds any single command may take. Generous for a status command and short
# enough that a hung probe fails a practice attempt instead of a learning run.
DEFAULT_TIMEOUT = 10.0

# Bytes of output kept from one read or command. A recipe that reads something
# enormous is a recipe with a bug, and truncating loudly beats holding a
# hundred megabytes in a learning record.
MAX_OUTPUT = 4_000_000

# Paths a recipe may read. Globs, matched against the resolved absolute path.
#
# `/proc` and `/sys/class/net` are the Linux system-state surfaces the first
# exercise needs. The project's own `logs/` and `docs/` are here because a skill
# that summarises this system's own records is exactly the kind of deterministic
# replacement for a model call that Document 1 §4.4 is about. Nothing else on
# the machine is readable, and in particular no home directory, no `.env`, no
# key material and no database file.
# Paths a recipe may read. Segment-aware globs (see `_segments_match`), matched
# against the normalised absolute path.
#
# `/proc` and `/sys/class/net` are the Linux system-state surfaces the first
# exercise needs. The project's own `logs/`, `docs/` and `config/` are here
# because a skill that answers a question from this system's own records is
# exactly the deterministic replacement for a model call that Document 1 §4.4 is
# about.
#
# **What is deliberately absent is the interesting half.** `/proc/*/environ`
# holds every process's environment and therefore every API key on this machine;
# `/proc/*/mem` and `/proc/*/maps` are its memory. None is listed, and the pid
# segment is a single-segment `*` rather than a prefix, so no pattern here can be
# walked sideways into one. Nothing outside these roots is readable at all - no
# home directory, no `.env`, no database, no key material.
READ_PATTERNS = (
    # network state
    "/proc/net/*",
    "/proc/*/net/*",          # /proc/net is a symlink to /proc/self/net
    "/sys/class/net/*",
    "/sys/class/net/*/*",
    # process identity, and only identity
    "/proc/*/comm",
    "/proc/*/cmdline",
    "/proc/*/stat",
    # machine state
    "/proc/uptime",
    "/proc/meminfo",
    "/proc/loadavg",
    # this system's own records
    str(PROJECT_ROOT / "logs" / "*"),
    str(PROJECT_ROOT / "docs" / "*"),
    str(PROJECT_ROOT / "docs" / "**" / "*"),
    str(PROJECT_ROOT / "config" / "*"),
)

# Never readable, whatever a pattern above might otherwise admit. A second,
# explicit list because the cost of one wrong wildcard here is every credential
# on the machine, and a deny-list checked after the allow-list is the cheapest
# insurance against that.
# Paths whose **link target** may be read but whose **contents** may not.
#
# `/proc/<pid>/fd/<n>` is the only way to map a socket to a process, so the first
# exercise cannot exist without `read_link` on it. Reading it as a *file*,
# however, returns the contents of whatever that descriptor points at - and a
# review of this module found exactly that: `read_file("/proc/self/fd/3")`
# returned a `.env` that `read_file(".../.env")` had just refused. The deny-list
# was intact and had been walked around through a descriptor.
#
# So the capability is split. `read_link` reads these; `read_file` never does,
# whatever the deny-list says about the target, because the target is not
# knowable from the pattern.
LINK_ONLY_PATTERNS = (
    "/proc/*/fd",
    "/proc/*/fd/*",
    "/proc/*/cwd",
    "/proc/*/exe",
)

DENIED_PATTERNS = (
    "/proc/*/environ", "/proc/*/mem", "/proc/*/maps", "/proc/*/smaps",
    "/proc/*/root/**", "/proc/*/cwd/**", "/proc/*/task/**",
    "**/.env", "**/.env.*", "**/*.key", "**/*.pem", "**/id_rsa*",
    "**/*.db", "**/*.sqlite*",
)

# Programs a recipe may run. Read-only, no shell, argv only. See the docstring
# for the selection rule.
COMMANDS = (
    # network state
    "ss", "netstat", "ip", "ipconfig", "ifconfig",
    # process state
    "ps", "tasklist",
    # machine state
    "hostname", "uname", "df", "free", "uptime", "systeminfo",
)

# Arguments refused whatever the command, because they are how a read-only
# program stops being one. Checked as whole arguments and as prefixes.
FORBIDDEN_ARGUMENT_PREFIXES = ("--exec", "-exec", "--command", "/c", "/k")


class SandboxRefusal(PermissionError):
    """The sandbox refused, and the message says what to propose instead.

    Not a bare denial: Document 1 §13 puts the sandbox inside a *learning* loop,
    and a refusal a learner cannot act on teaches it nothing. Every refusal here
    names the allow-list it hit and says that widening it is a boundary
    proposal rather than something to work around."""


class SandboxUnavailable(SandboxRefusal):
    """The path is a system surface this platform does not have.

    A subclass, so existing handlers keep working, and a distinct class because
    the two mean opposite things to a learner. `SandboxRefusal` says *you may not
    read that* and the answer is to propose a boundary. This says *there is
    nothing there on this machine* and the answer is to find the platform's own
    route.

    Windows CI found this the hard way: `os.path.abspath("/proc/net/tcp")` on
    Windows is `D:\\proc\\net\\tcp`, which matched no declared pattern, so a
    recipe written for Linux was refused as a **permission** problem. Jarvis
    would have gone off to propose an allow-list change for a file that does not
    exist, instead of reaching for `netstat`. A diagnosis that sends the learner
    in the wrong direction is worse than no diagnosis."""


# System surfaces that exist on one platform and not the other, with the route to
# the same information on the other one. Named here rather than in a diagnosis
# table because this module is the thing that knows a path was refused for being
# absent rather than for being forbidden.
PLATFORM_SURFACES = {
    "/proc": {
        "on": "posix",
        "instead": ("on Windows the same information comes from commands: "
                    "`netstat -ano` for sockets, `tasklist` for processes. Both "
                    "are on the command allow-list"),
    },
    "/sys": {
        "on": "posix",
        "instead": ("on Windows use `ipconfig` for interfaces and `systeminfo` "
                    "for machine state. Both are on the command allow-list"),
    },
}


def _platform_surface_for(path: str, platform: str | None = None) -> dict | None:
    """Whether this path belongs to a surface this platform does not have.

    Matched on the path **as written**, before `abspath` mangles it with a drive
    letter - which is the whole reason the Windows failure was misdiagnosed.

    `platform` is a parameter rather than a direct `os.name` read so a test can
    assert the Windows behaviour from Linux. The first attempt to probe this
    monkeypatched `os.name` and broke `pathlib` instead, which is a good sign
    that the dependency belonged in the signature."""
    here = platform or os.name
    written = str(path).replace("\\", "/")
    for root, meta in PLATFORM_SURFACES.items():
        if not (written == root or written.startswith(root + "/")):
            continue
        if meta["on"] == "posix" and here == "nt":
            return {**meta, "root": root}
    return None


class Sandbox:
    """One practice environment. A context manager; its directory is removed.

    `allow_commands=False` is the default for a reason: most recipes read files,
    the command surface is the larger one, and a skill that never needed a
    subprocess should not have been able to start one."""

    def __init__(self, *, allow_commands: bool = False,
                 timeout: float = DEFAULT_TIMEOUT):
        self.allow_commands = allow_commands
        self.timeout = timeout
        self.directory: Path | None = None
        # Every acquisition, in order, so a practice attempt can be reviewed
        # afterwards without re-running it (§13's "captured logs").
        self.trace: list[dict] = []

    def __enter__(self) -> "Sandbox":
        self.directory = Path(tempfile.mkdtemp(prefix="jarvis-learning-"))
        return self

    def __exit__(self, *_) -> None:
        if self.directory is not None:
            shutil.rmtree(self.directory, ignore_errors=True)
            self.directory = None

    # --- paths ----------------------------------------------------------------

    @staticmethod
    def _segments_match(pattern: str, path: str) -> bool:
        """Glob one path against one pattern, **segment by segment**.

        Not `fnmatch` on the whole string, and the difference is a security hole
        rather than a nicety: `fnmatch`'s `*` matches `/` as happily as any other
        character, so the pattern `/proc/net/*` matches
        `/proc/net/../../etc/passwd`. The first security probe of this module
        found exactly that. Here `*` and `?` are confined within one segment and
        `**` is the only thing that spans them, which is what everybody already
        assumes a path glob means."""
        import fnmatch as _fn

        parts = [part for part in pattern.split("/") if part != ""]
        actual = [part for part in path.split("/") if part != ""]

        def walk(pi: int, ai: int) -> bool:
            while pi < len(parts):
                if parts[pi] == "**":
                    if pi + 1 == len(parts):
                        return True
                    for skip in range(ai, len(actual) + 1):
                        if walk(pi + 1, skip):
                            return True
                    return False
                if ai >= len(actual):
                    return False
                if not _fn.fnmatch(actual[ai], parts[pi]):
                    return False
                pi += 1
                ai += 1
            return ai == len(actual)

        return walk(0, 0)

    def _permitted(self, path: str) -> Path:
        """The path, if a recipe may read it. Raises `SandboxRefusal` otherwise.

        Three checks, and each one closed a hole the first security probe of
        this module found:

        1. **Normalise before matching.** `os.path.normpath` collapses `..`, so
           a traversal is compared against the allow-list in the form it
           actually refers to rather than the form it was written in.
        2. **Match the normalised path, not the resolved one.** `/proc/net` is a
           symlink to `/proc/self/net`, so resolving first turns `/proc/net/tcp`
           into `/proc/<pid>/net/tcp` and the declared pattern stops matching
           the thing it was written for.
        3. **Then check the resolved path too**, unless it is under `/proc`.
           That closes the other direction: a symlink planted in the project's
           own `logs/` or `docs/` could otherwise point anywhere. `/proc` is
           exempt because its symlinks pointing outside themselves is the whole
           reason the first exercise can map a socket to a process, and the
           kernel rather than this system decides what they say."""
        absent = _platform_surface_for(path)
        if absent is not None:
            raise SandboxUnavailable(
                f"{path} is a {absent['on']} surface and this machine is "
                f"{os.name}. It is not forbidden - it is not there. Do not "
                f"propose a boundary for it: {absent['instead']}.")

        raw = os.path.abspath(os.path.normpath(str(path)))

        if self.directory is not None:
            try:
                Path(raw).relative_to(self.directory)
                return Path(raw)
            except ValueError:
                pass

        for denied in DENIED_PATTERNS:
            if self._segments_match(denied, raw):
                raise SandboxRefusal(
                    f"reading {raw} is refused by the deny-list. It is a "
                    f"credential, a process's memory or another system's store, "
                    f"and no learning exercise needs it.")

        if not any(self._segments_match(pattern, raw) for pattern in READ_PATTERNS):
            raise SandboxRefusal(
                f"reading {raw} is not permitted. The sandbox reads only "
                f"{len(READ_PATTERNS)} declared path patterns, and this is not one "
                f"of them. If a skill genuinely needs it, propose the boundary "
                f"(app/boundaries.py) rather than working around it - I cannot "
                f"widen my own allow-list.")

        if not raw.startswith("/proc/"):
            real = os.path.realpath(raw)
            if real != raw and not any(
                    self._segments_match(pattern, real) for pattern in READ_PATTERNS):
                raise SandboxRefusal(
                    f"{raw} is a link to {real}, which is outside the permitted "
                    f"paths. Refused on the target rather than the name.")
        return Path(raw)

    def read_file(self, path: str) -> str:
        raw = os.path.abspath(os.path.normpath(str(path)))
        if any(self._segments_match(pattern, raw)
               for pattern in LINK_ONLY_PATTERNS):
            raise SandboxRefusal(
                f"{raw} is a file descriptor, and its contents are whatever it "
                f"points at - which is how a deny-listed file gets read through a "
                f"descriptor that is not deny-listed. Follow it with a link read "
                f"instead; that is what the socket mapping needs and all it needs.")
        target = self._permitted(path)
        try:
            with target.open("rb") as handle:
                raw = handle.read(MAX_OUTPUT + 1)
        except OSError as bad:
            # An unreadable path is a finding, not a crash: half of learning to
            # read /proc is discovering which entries disappear between the
            # listing and the read.
            self.trace.append({"op": "read_file", "path": str(target),
                               "ok": False, "error": str(bad)})
            raise SandboxRefusal(f"{target} could not be read: {bad}") from bad
        truncated = len(raw) > MAX_OUTPUT
        text = raw[:MAX_OUTPUT].decode("utf-8", "replace")
        self.trace.append({"op": "read_file", "path": str(target), "ok": True,
                           "bytes": len(text), "truncated": truncated})
        return text

    def glob(self, pattern: str) -> list[str]:
        """Paths matching a pattern, filtered to what is readable.

        Filtered rather than refused: `/proc/[0-9]*/fd/*` legitimately spans
        thousands of entries of which some vanish mid-listing, and a refusal on
        the first unreadable one would make the primitive useless for the thing
        it exists to do."""
        absent = _platform_surface_for(pattern)
        if absent is not None:
            raise SandboxUnavailable(
                f"{pattern} is a {absent['on']} surface and this machine is "
                f"{os.name}. {absent['instead']}.")

        # The pattern itself is checked against the allow-list the same way a
        # concrete path is, so `/etc/*` is refused before anything is listed -
        # and every result is checked again below, because a pattern that
        # overlaps a permitted prefix can still match unpermitted entries.
        if not any(self._segments_match(allowed, os.path.abspath(
                os.path.normpath(pattern))) or self._segments_match(
                os.path.abspath(os.path.normpath(pattern)), allowed)
                for allowed in READ_PATTERNS + LINK_ONLY_PATTERNS):
            raise SandboxRefusal(
                f"listing {pattern} is not permitted: it does not overlap any of "
                f"the declared readable path patterns.")
        root = Path(pattern).anchor or "/"
        relative = pattern[len(root):] if pattern.startswith(root) else pattern
        try:
            found = sorted(str(p) for p in Path(root).glob(relative))
        except OSError as bad:  # pragma: no cover - permission-denied roots
            raise SandboxRefusal(f"{pattern} could not be listed: {bad}") from bad
        kept = []
        for candidate in found:
            try:
                self._permitted_link(candidate)
            except SandboxRefusal:
                continue
            kept.append(candidate)
        self.trace.append({"op": "glob", "pattern": pattern, "ok": True,
                           "matched": len(kept)})
        return kept

    def _permitted_link(self, path: str) -> Path:
        """A link whose target may be *named*, though not read.

        Separate from `_permitted` because the two permit different things: this
        admits the descriptor patterns above, and `_permitted` deliberately does
        not."""
        raw = os.path.abspath(os.path.normpath(str(path)))
        if any(self._segments_match(pattern, raw)
               for pattern in LINK_ONLY_PATTERNS):
            return Path(raw)
        return self._permitted(path)

    def read_link(self, path: str) -> str | None:
        """A symlink's target, or None when it is not one or has gone.

        None rather than an exception because `/proc/<pid>/fd` is full of links
        belonging to processes that exit while you are reading, and that is the
        normal case rather than an error."""
        target = self._permitted_link(path)
        try:
            return os.readlink(target)
        except OSError:
            return None

    # --- commands ---------------------------------------------------------------

    def run(self, argv: list[str]) -> str:
        if not self.allow_commands:
            raise SandboxRefusal(
                "this sandbox was opened without command execution. A recipe "
                "that needs to run a program must declare it, so that the "
                "decision to allow one is taken once and visibly.")
        if not argv or not isinstance(argv, list):
            raise SandboxRefusal("a command is an argv list, never a string - "
                                 "there is no shell here to split one.")
        requested = str(argv[0])
        if os.sep in requested or (os.altsep and os.altsep in requested):
            # A REVIEW OF THIS MODULE FOUND THIS EXACT HOLE. The allow-list
            # checked `basename(argv[0])` and then executed the path as given,
            # so `run(["/tmp/anywhere/ss"])` ran a planted script and returned
            # its output - the "read-only programs only" guarantee defeated by
            # naming a file after one of them.
            #
            # A bare name only, resolved through PATH below and executed as the
            # absolute path that resolution produced. There is no legitimate
            # recipe that needs to name a directory.
            raise SandboxRefusal(
                f"{requested!r} names a path. A recipe may run a program by bare "
                f"name only - the name is what is allow-listed, and executing a "
                f"path the caller chose would let any file named after an "
                f"allowed program run instead of it.")
        program = requested.lower()
        program = program[:-4] if program.endswith(".exe") else program
        if program not in COMMANDS:
            raise SandboxRefusal(
                f"{program!r} is not one of the {len(COMMANDS)} read-only "
                f"programs this sandbox may run ({', '.join(COMMANDS)}). Widening "
                f"that list is a boundary proposal, not something a recipe may "
                f"do for itself.")
        for argument in argv[1:]:
            lowered = str(argument).lower()
            if any(lowered.startswith(bad) for bad in FORBIDDEN_ARGUMENT_PREFIXES):
                raise SandboxRefusal(
                    f"{argument!r} is refused: it is how a read-only program "
                    f"stops being one.")
        resolved = shutil.which(requested)
        if resolved is None:
            raise SandboxRefusal(
                f"{requested!r} is permitted but is not installed on this "
                f"machine. That is a fact about the environment rather than a "
                f"policy refusal, and a skill that needs it should say so.")
        try:
            completed = subprocess.run(  # noqa: S603 - argv, no shell, allow-listed
                # The RESOLVED absolute path, not what the caller wrote.
                [resolved] + [str(part) for part in argv[1:]],
                capture_output=True, text=True, timeout=self.timeout,
                shell=False, cwd=str(self.directory) if self.directory else None,
            )
        except subprocess.TimeoutExpired as bad:
            self.trace.append({"op": "run", "argv": argv, "ok": False,
                               "error": f"timed out after {self.timeout}s"})
            raise SandboxRefusal(
                f"{program} did not finish within {self.timeout}s and was "
                f"stopped.") from bad
        except OSError as bad:  # pragma: no cover - defensive
            raise SandboxRefusal(f"{program} could not be started: {bad}") from bad

        self.trace.append({"op": "run", "argv": argv, "ok": completed.returncode == 0,
                           "exit_code": completed.returncode,
                           "bytes": len(completed.stdout)})
        if completed.returncode != 0:
            raise SandboxRefusal(
                f"{program} exited {completed.returncode}. First 300 characters "
                f"of stderr: {completed.stderr[:300]!r}")
        return completed.stdout[:MAX_OUTPUT]


def describe() -> dict:
    """What the sandbox permits, for the learning plan and for a tool result."""
    return {
        "read_patterns": list(READ_PATTERNS),
        "link_only_patterns": list(LINK_ONLY_PATTERNS),
        "denied_patterns": list(DENIED_PATTERNS),
        "commands": list(COMMANDS),
        "timeout_seconds": DEFAULT_TIMEOUT,
        "max_output_bytes": MAX_OUTPUT,
        "shell": False,
        "network": False,
        "platform": os.name,
        "platform_surfaces_absent_here": {
            root: meta["instead"] for root, meta in PLATFORM_SURFACES.items()
            if _platform_surface_for(root + "/x") is not None},
        "note": ("Both lists are fixed in app/learning/sandbox.py. Jarvis "
                 "composes primitives and cannot extend either; a skill that "
                 "needs more files a boundary proposal."),
    }
