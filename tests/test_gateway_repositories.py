"""Git as the artifact exchange: what it reads, what it refuses, and the promise
that it never disturbs the working tree.

Every test here runs against a real git repository built in tmp_path. Mocking git
would test the argument strings and nothing that matters - the properties worth
asserting (a branch exists, HEAD did not move, an uncommitted file is still
uncommitted) only exist in a real one.
"""

import subprocess

import pytest

from gateway import repositories


def git(path, *arguments, stdin=None):
    result = subprocess.run(
        ["git", *arguments], cwd=path, input=stdin, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


# --- Configuration ---


def test_nothing_configured_means_nothing_reachable(monkeypatch):
    """Default closed, like the Super User credential: an unset variable is not an
    invitation to guess at a repository."""
    monkeypatch.delenv(repositories.PRIVATE_REPO_ENV, raising=False)
    monkeypatch.delenv(repositories.PUBLIC_REPO_ENV, raising=False)

    assert repositories.repositories() == {}
    with pytest.raises(repositories.RepositoryError, match=repositories.PRIVATE_REPO_ENV):
        repositories.resolve(None)


def test_the_default_target_is_the_private_repository(private_repo, public_repo):
    assert repositories.default_repository().visibility == "private"
    assert repositories.resolve(None).name == "jarvis-internal"


def test_a_publish_will_not_default_to_a_public_repository(monkeypatch, public_repo):
    """With only a public repository configured, "publish this" has no safe
    default - so it refuses rather than choosing the irreversible one."""
    monkeypatch.delenv(repositories.PRIVATE_REPO_ENV, raising=False)

    with pytest.raises(repositories.RepositoryError, match="will not default"):
        repositories.resolve(None)


def test_an_unknown_repository_names_the_ones_that_exist(private_repo):
    with pytest.raises(repositories.RepositoryError, match="jarvis-internal"):
        repositories.resolve("some-other-repo")


# --- Reading ---


def test_only_tracked_files_are_listed_or_readable(private_repo):
    """The access rule, and the reason it is git's rather than a denylist:
    `secret.env` is ignored, therefore untracked, therefore invisible. Nothing
    here had to know it holds an API key."""
    files = repositories.tracked_files(private_repo)

    assert "docs/existing.md" in files
    assert "secret.env" not in files
    with pytest.raises(repositories.RepositoryError, match="not tracked"):
        repositories.read_file(private_repo, "secret.env")


def test_reading_returns_what_is_on_disk_including_uncommitted_edits(private_repo):
    """The developer's current text is what a conversation about it means."""
    (private_repo.path / "docs" / "existing.md").write_text("# Edited, not committed\n", encoding="utf-8")

    assert "Edited, not committed" in repositories.read_file(private_repo, "docs/existing.md")


def test_listing_can_be_limited_to_a_directory(private_repo):
    (private_repo.path / "docs" / "second.md").write_text("second\n", encoding="utf-8")
    (private_repo.path / "top.md").write_text("top\n", encoding="utf-8")
    git(private_repo.path, "add", "docs/second.md", "top.md")
    git(private_repo.path, "commit", "-qm", "more")

    assert repositories.tracked_files(private_repo, "docs") == ["docs/existing.md", "docs/second.md"]


def test_paths_that_escape_the_repository_are_refused(private_repo):
    for attempt in ["../outside.md", "docs/../../outside.md", "/etc/passwd", "C:/Windows/x.txt"]:
        with pytest.raises(repositories.RepositoryError):
            repositories.read_file(private_repo, attempt)


def test_git_internals_are_refused(private_repo):
    with pytest.raises(repositories.RepositoryError, match=".git"):
        repositories.read_file(private_repo, ".git/config")


def test_a_binary_file_is_refused_rather_than_mangled(private_repo):
    (private_repo.path / "image.bin").write_bytes(b"\x89PNG\x00\x01\x02")
    git(private_repo.path, "add", "image.bin")
    git(private_repo.path, "commit", "-qm", "binary")

    with pytest.raises(repositories.RepositoryError, match="not a text file"):
        repositories.read_file(private_repo, "image.bin")


def test_an_oversized_file_is_refused(private_repo, monkeypatch):
    monkeypatch.setattr(repositories, "MAX_READ_BYTES", 5)  # docs/existing.md is 26 bytes

    with pytest.raises(repositories.RepositoryError, match="read limit"):
        repositories.read_file(private_repo, "docs/existing.md")


# --- Publishing ---


def test_publishing_creates_a_branch_and_leaves_everything_else_alone(private_repo):
    """The property this module exists for. A service that ran `git checkout -b`
    in a repository somebody is working in would sweep up half-finished edits and
    move HEAD under a running test."""
    (private_repo.path / "work-in-progress.txt").write_text("uncommitted\n", encoding="utf-8")
    (private_repo.path / "docs" / "existing.md").write_text("# Edited, not committed\n", encoding="utf-8")
    head_before = git(private_repo.path, "rev-parse", "HEAD").strip()
    branch_before = git(private_repo.path, "rev-parse", "--abbrev-ref", "HEAD").strip()
    status_before = git(private_repo.path, "status", "--porcelain")

    result = repositories.publish(
        private_repo, "docs/new-spec.md", "# New spec\n\nContent.\n", "Add the new spec"
    )

    assert result["branch"] == "gateway/new-spec"
    assert result["updated_existing"] is False
    assert result["pushed"] is False

    # The commit is real and contains the document.
    assert (
        git(private_repo.path, "show", f"{result['branch']}:docs/new-spec.md")
        == "# New spec\n\nContent.\n"
    )
    # And nothing else moved.
    assert git(private_repo.path, "rev-parse", "HEAD").strip() == head_before
    assert git(private_repo.path, "rev-parse", "--abbrev-ref", "HEAD").strip() == branch_before
    assert git(private_repo.path, "status", "--porcelain") == status_before
    assert (private_repo.path / "work-in-progress.txt").read_text(encoding="utf-8") == "uncommitted\n"
    assert "Edited, not committed" in (private_repo.path / "docs" / "existing.md").read_text(encoding="utf-8")


def test_the_published_branch_keeps_the_rest_of_the_tree(private_repo):
    """Committed against HEAD rather than into an empty tree - a branch holding
    only the new file would look like a deletion of everything else."""
    result = repositories.publish(private_repo, "docs/new.md", "content\n", "Add")

    files = git(private_repo.path, "ls-tree", "-r", "--name-only", result["branch"]).split()
    assert "docs/existing.md" in files
    assert "docs/new.md" in files


def test_publishing_the_same_path_twice_makes_a_second_branch(private_repo):
    """The first branch may already be under review, so it is never moved."""
    first = repositories.publish(private_repo, "docs/spec.md", "one\n", "First")
    second = repositories.publish(private_repo, "docs/spec.md", "two\n", "Second")

    assert first["branch"] == "gateway/spec"
    assert second["branch"] == "gateway/spec-2"
    assert git(private_repo.path, "show", f"{first['branch']}:docs/spec.md") == "one\n"


def test_updating_an_existing_document_says_so(private_repo):
    result = repositories.publish(private_repo, "docs/existing.md", "# Rewritten\n", "Rewrite it")

    assert result["updated_existing"] is True
    assert git(private_repo.path, "show", f"{result['branch']}:docs/existing.md") == "# Rewritten\n"


def test_the_commit_records_that_the_gateway_filed_it(private_repo):
    result = repositories.publish(private_repo, "docs/new.md", "content\n", "Add the thing")

    message = git(private_repo.path, "log", "-1", "--format=%B", result["branch"])
    assert "Add the thing" in message
    assert "Filed-by: AI Communication Gateway" in message


def test_empty_documents_and_empty_messages_are_refused(private_repo):
    with pytest.raises(repositories.RepositoryError, match="empty document"):
        repositories.publish(private_repo, "docs/x.md", "   ", "message")
    with pytest.raises(repositories.RepositoryError, match="message"):
        repositories.publish(private_repo, "docs/x.md", "content", "  ")


def test_an_oversized_document_is_refused(private_repo, monkeypatch):
    monkeypatch.setattr(repositories, "MAX_PUBLISH_BYTES", 20)

    with pytest.raises(repositories.RepositoryError, match="limit"):
        repositories.publish(private_repo, "docs/x.md", "x" * 100, "message")


# --- The public/private boundary ---


def test_publishing_publicly_needs_explicit_confirmation(public_repo):
    """A spoken sentence must not become a public commit through inference."""
    with pytest.raises(repositories.RepositoryError, match="explicit confirmation"):
        repositories.publish(public_repo, "docs/spec.md", "Technical content.\n", "Add")

    result = repositories.publish(
        public_repo, "docs/spec.md", "Technical content.\n", "Add", confirmed_public=True
    )
    assert result["visibility"] == "public"


def test_private_material_is_refused_even_when_confirmed(public_repo):
    """The guard docs/PUBLIC_PRIVATE_BOUNDARY.md asks for. Confirmation says where
    the user meant it to go; it does not certify what the document is."""
    with pytest.raises(repositories.RepositoryError) as refused:
        repositories.publish(
            public_repo,
            "docs/principles.md",
            "The constitution's axioms govern how agents are judged.\n",
            "Add principles",
            confirmed_public=True,
        )

    assert "constitution" in str(refused.value)
    assert "axiom" in str(refused.value)
    assert "do not work around this check" in str(refused.value)
    assert git(public_repo.path, "for-each-ref", "refs/heads").count("gateway/") == 0


def test_the_screen_reads_the_path_and_message_too(public_repo):
    """A document whose body is innocuous but which is filed as the charter is
    still the charter."""
    with pytest.raises(repositories.RepositoryError, match="charter"):
        repositories.publish(
            public_repo,
            "docs/agent_charter.md",
            "Roles and their duties.\n",
            "Add it",
            confirmed_public=True,
        )


def test_the_screen_does_not_run_against_the_private_repository(private_repo):
    """Philosophy belongs there. A guard that blocked it everywhere would make the
    private repository unwritable for exactly the material it exists to hold."""
    result = repositories.publish(
        private_repo,
        "governance/principles.md",
        "The constitution's axioms govern how agents are judged.\n",
        "Add principles",
    )

    assert result["visibility"] == "private"


def test_the_screen_matches_words_not_fragments():
    """'constitutional' should trip it; 'reconstitution' in a sentence about
    databases should not, or the guard becomes noise and gets disabled."""
    assert repositories.philosophy_signals("constitutional limits") == ["constitutional"]
    assert repositories.philosophy_signals("database reconstitution after a restore") == []
    assert repositories.philosophy_signals("see INT-PHIL-0007") == ["int-phil"]
    assert repositories.philosophy_signals("plain technical prose about sockets") == []
