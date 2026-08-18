"""Git as the durable artifact exchange (addendum 16 §3, §14, §20).

§3 is unambiguous: *"No approved specification should exist only inside an AI
conversation."* §20 wants "that's approved, publish the specification" to become a
real commit without the Super User downloading and re-uploading anything.

Three rules shape everything here, and each of them cost something to honour.

## 1. The working tree is never touched

The repositories this reaches are the ones the owner is actively working in. A
service that ran `git checkout -b` in the background - sweeping up whatever was
half-edited, moving HEAD under a running test - would be hostile no matter how
correct its commit was.

So a publish never checks anything out. It writes a blob, builds a tree in a
*temporary index outside the repository*, commits it against the current HEAD,
and points a new ref at the result:

    git hash-object -w --stdin      the content becomes an object
    git read-tree HEAD              a temporary index, GIT_INDEX_FILE elsewhere
    git update-index --add          the one path being published
    git write-tree / commit-tree    a real commit, parented on HEAD
    git update-ref refs/heads/...   a new branch, nothing else moved

Uncommitted work stays uncommitted, the checked-out branch stays checked out, and
the result is a branch the owner can inspect, merge, or delete.

## 2. Nothing is pushed

A commit on a local branch is reversible; a push to a public remote is not -
anything cloned in that window is outside anyone's control. Addendum 16 §19
requires human review before significant changes land, and pushing on a spoken
sentence would put the Gateway on the far side of that gate. The publish reports
the branch; a person pushes it.

## 3. The public repository is defended, not merely flagged

`docs/PUBLIC_PRIVATE_BOUNDARY.md` splits this project: what the system does and
the technical how are public; the organizational philosophy and strategic
rationale are private. §20 does not know that, because it was written before the
split - so a model choosing a destination from a spoken sentence is one wrong
inference away from publishing philosophy to a public repository, irreversibly.

Therefore: the private repository is the default; a public target must be
confirmed explicitly by the caller; and a screen runs over the content first.

**The screen is a tripwire, not a classifier.** It cannot judge whether text is
philosophy - nothing here can - so it looks for the vocabulary that philosophy in
this project actually uses, and refuses when it finds it. It will be wrong in
both directions: a spec that merely mentions the constitution will be stopped, and
a philosophical passage phrased in ordinary words will pass. It is set to fail
toward the private repository, because that failure is a person retyping a
destination and the other one is not undoable.
"""

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

PRIVATE_REPO_ENV = "GATEWAY_PRIVATE_REPO"
PUBLIC_REPO_ENV = "GATEWAY_PUBLIC_REPO"

# Enough for a long specification; small enough that a runaway generation does
# not write a gigabyte into somebody's object store.
MAX_PUBLISH_BYTES = 1_000_000
MAX_READ_BYTES = 200_000
MAX_LISTED_FILES = 400

GIT_TIMEOUT_SECONDS = 30

# The vocabulary this project's private material actually uses - taken from the
# documents that were separated out (the constitution, the charter, the
# rationality monitoring design) and from the identifier scheme public code uses
# to point at them. Matched case-insensitively on word boundaries.
PHILOSOPHY_SIGNALS = (
    "constitution",
    "constitutional",
    "charter",
    "axiom",
    "axioms",
    "manifesto",
    "philosophy",
    "philosophical",
    "doctrine",
    "organizational rationale",
    "guiding principle",
    "guiding principles",
    "int-phil",
)


class RepositoryError(ValueError):
    """A refusal, phrased for whoever asked - including the model, which reads it
    as a tool result and is expected to correct itself or stop."""


@dataclass(frozen=True)
class Repository:
    name: str
    path: Path
    visibility: str  # "private" | "public"


def repositories() -> dict[str, Repository]:
    """What this Gateway may reach, from the environment.

    Read at call time rather than import, like every other configuration here.
    Unset means the Git tools have nothing to work on and say so - the same
    default-closed rule the Super User credential follows."""
    found: dict[str, Repository] = {}
    for variable, visibility in ((PRIVATE_REPO_ENV, "private"), (PUBLIC_REPO_ENV, "public")):
        raw = os.environ.get(variable, "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        found[path.name] = Repository(name=path.name, path=path, visibility=visibility)
    return found


def default_repository() -> Repository | None:
    """Where a publish goes when nobody said. The private one, always: a wrong
    default that keeps something private is recoverable."""
    for repo in repositories().values():
        if repo.visibility == "private":
            return repo
    return None


def resolve(name: str | None) -> Repository:
    available = repositories()
    if not available:
        raise RepositoryError(
            f"No repositories are configured. Set {PRIVATE_REPO_ENV} (and optionally "
            f"{PUBLIC_REPO_ENV}) and restart the Gateway."
        )
    if name is None:
        repo = default_repository()
        if repo is None:
            raise RepositoryError(
                f"No private repository is configured, and a publish will not default to a "
                f"public one. Set {PRIVATE_REPO_ENV}."
            )
        return repo
    if name not in available:
        raise RepositoryError(
            f"Unknown repository {name!r}. Configured: {', '.join(sorted(available)) or 'none'}."
        )
    return available[name]


def _git(repo: Repository, *arguments: str, stdin: bytes | None = None, env: dict | None = None) -> str:
    """One git invocation, never through a shell.

    Failures carry git's own stderr, because "fatal: not a git repository" is a
    better answer than anything this module could invent."""
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo.path,
        input=stdin,
        capture_output=True,
        timeout=GIT_TIMEOUT_SECONDS,
        env={**os.environ, **(env or {})},
    )
    if result.returncode != 0:
        raise RepositoryError(
            f"git {arguments[0]} failed in {repo.name}: "
            f"{result.stderr.decode('utf-8', 'replace').strip()}"
        )
    return result.stdout.decode("utf-8", "replace")


def _safe_relative_path(path: str) -> str:
    """A repository-relative path, or a refusal.

    Absolute paths, traversal and `.git` are all rejected here rather than
    anywhere later: this is the only place a caller's string becomes a location
    on disk."""
    cleaned = (path or "").strip().replace("\\", "/").lstrip("/")
    if not cleaned:
        raise RepositoryError("A path is required.")
    if ".." in Path(cleaned).parts:
        raise RepositoryError(f"Refusing a path that escapes the repository: {path!r}")
    if Path(cleaned).is_absolute() or re.match(r"^[a-zA-Z]:", cleaned):
        raise RepositoryError(f"Paths must be relative to the repository: {path!r}")
    if Path(cleaned).parts[0] == ".git":
        raise RepositoryError("Refusing to touch .git.")
    return cleaned


def tracked_files(repo: Repository, prefix: str | None = None) -> list[str]:
    """Every file git is tracking, optionally under a prefix.

    Tracked, not "present on disk", and that is the access rule rather than a
    convenience: `.env`, `gateway.db` and every other ignored file is invisible to
    this Gateway because git is not tracking it. One rule, already maintained by
    the repository itself, doing the work a hand-written denylist would do
    worse."""
    output = _git(repo, "ls-files", "-z")
    files = [name for name in output.split("\0") if name]
    if prefix:
        wanted = _safe_relative_path(prefix).rstrip("/")
        files = [name for name in files if name == wanted or name.startswith(wanted + "/")]
    return sorted(files)[:MAX_LISTED_FILES]


def read_file(repo: Repository, path: str) -> str:
    """The contents of a tracked file, as text.

    Read from the working tree rather than from HEAD, so the assistant sees what
    the developer sees - including edits not yet committed, which are usually the
    ones being discussed."""
    relative = _safe_relative_path(path)
    if relative not in set(tracked_files(repo)):
        raise RepositoryError(
            f"{relative} is not tracked in {repo.name}. Only files under version control "
            "can be read."
        )

    location = repo.path / relative
    size = location.stat().st_size
    if size > MAX_READ_BYTES:
        raise RepositoryError(
            f"{relative} is {size} bytes, over the {MAX_READ_BYTES}-byte read limit."
        )

    data = location.read_bytes()
    if b"\0" in data:
        raise RepositoryError(f"{relative} is not a text file.")
    return data.decode("utf-8", "replace")


def philosophy_signals(*texts: str) -> list[str]:
    """Which private-material terms appear in the given text, if any.

    A tripwire rather than a classifier - see this module's docstring for what
    that means and why it is set to fail toward the private repository."""
    haystack = " ".join(texts).lower()
    return [
        signal
        for signal in PHILOSOPHY_SIGNALS
        if re.search(rf"(?<![a-z0-9-]){re.escape(signal)}(?![a-z0-9])", haystack)
    ]


def _branch_name(path: str) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", Path(path).stem.lower()).strip("-") or "document"
    return f"gateway/{stem}"


def _unique_branch(repo: Repository, base_name: str) -> str:
    """A branch name nothing is using. Publishing the same document twice makes a
    second branch rather than moving the first, because the first may already be
    under review."""
    existing = {
        line.strip()
        for line in _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads").splitlines()
    }
    if base_name not in existing:
        return base_name
    suffix = 2
    while f"{base_name}-{suffix}" in existing:
        suffix += 1
    return f"{base_name}-{suffix}"


def publish(
    repo: Repository,
    path: str,
    content: str,
    message: str,
    confirmed_public: bool = False,
) -> dict:
    """Commit one document to a new branch, touching nothing else.

    Returns the branch, the commit, the branch it was based on, and whether the
    path already existed - the last because updating a specification and adding
    one are different things for a reviewer to be told about.
    """
    relative = _safe_relative_path(path)
    if not (content or "").strip():
        raise RepositoryError("Refusing to publish an empty document.")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_PUBLISH_BYTES:
        raise RepositoryError(
            f"The document is {len(encoded)} bytes, over the {MAX_PUBLISH_BYTES}-byte limit."
        )
    if not (message or "").strip():
        raise RepositoryError("A commit needs a message saying what this is.")

    if repo.visibility == "public":
        if not confirmed_public:
            raise RepositoryError(
                f"{repo.name} is public. Publishing there needs explicit confirmation naming the "
                f"repository, because it cannot be taken back. The private repository is the "
                f"default; say so plainly and ask before publishing publicly."
            )
        signals = philosophy_signals(content, message, relative)
        if signals:
            raise RepositoryError(
                f"Refused: this reads like private material and {repo.name} is public. "
                f"Terms found: {', '.join(sorted(signals))}. docs/PUBLIC_PRIVATE_BOUNDARY.md "
                f"keeps organizational philosophy and strategic rationale out of the public "
                f"repository. Publish it privately, or remove the private reasoning first - do "
                f"not work around this check."
            )

    head = _git(repo, "rev-parse", "HEAD").strip()
    base_branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    existed = relative in set(tracked_files(repo))

    blob = _git(repo, "hash-object", "-w", "--stdin", stdin=encoded).strip()

    # The temporary index lives outside the repository. Inside it, it would show
    # up as an untracked file in the owner's `git status` for as long as the
    # publish takes - a service that makes the working tree look dirty is exactly
    # what rule 1 above exists to avoid.
    with tempfile.TemporaryDirectory(prefix="gateway-index-") as scratch:
        index_env = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}
        _git(repo, "read-tree", head, env=index_env)
        _git(repo, "update-index", "--add", "--cacheinfo", f"100644,{blob},{relative}", env=index_env)
        tree = _git(repo, "write-tree", env=index_env).strip()

    commit = _git(
        repo,
        "commit-tree",
        tree,
        "-p",
        head,
        "-m",
        f"{message.strip()}\n\nFiled-by: AI Communication Gateway",
    ).strip()

    branch = _unique_branch(repo, _branch_name(relative))
    _git(repo, "update-ref", f"refs/heads/{branch}", commit)

    return {
        "repository": repo.name,
        "visibility": repo.visibility,
        "branch": branch,
        "commit": commit[:12],
        "based_on": base_branch,
        "path": relative,
        "updated_existing": existed,
        "pushed": False,
        "note": (
            f"Committed to the local branch {branch} in {repo.name}. Nothing was pushed and the "
            f"working tree was not touched; review it with `git show {branch}` and push when you "
            f"are satisfied."
        ),
    }
