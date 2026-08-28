"""The living documentation, kept honest by the suite (addendum 47;
docs/SPEC_RECONCILIATION.md §121, §122).

Addendum 47 §3 requires that the documentation change when the system changes,
and §6 says maintenance is part of development rather than something postponed.
**A requirement of that shape kept as a discipline is a requirement that decays**
- the previous handoff document went stale describing tables that had been
deleted, and nothing noticed for a week.

So the parts of `docs/JARVIS.md` that can be checked mechanically are checked
here: every file it points at, every record section it cites, every task it
names, every status word it uses, and every role it calls implemented. When the
system moves and the document does not, this fails.

What cannot be checked mechanically is whether the prose is *true*. These tests
catch a document describing components that no longer exist; they cannot catch
one describing existing components wrongly. That limit is worth stating rather
than letting a green suite imply more than it means.

## Custody

Owner directive 2026-08-27: one writer, and no tampering. The custody tests below
assert the three layers `JARVIS.md` claims - the guard at the only write path
into the repository, agreement between that guard and the manifest, and the
digest that makes an edit outside the custodian's hand visible.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import re
from pathlib import Path

import pytest

from gateway import repositories

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
LIVING = DOCS / "JARVIS.md"
MANIFEST = DOCS / "document_custody.yaml"
RUNTIME_PACKAGES = ("agents", "app", "backend", "gateway", "simulation")

TEXT = LIVING.read_text(encoding="utf-8")

# Addendum 47 §10's status model, verbatim. A status not on this list is either a
# typo or a vocabulary change nobody recorded.
STATUSES = {
    "TO BE DEVELOPED", "IN DESIGN", "IN DEVELOPMENT", "IMPLEMENTED", "TESTING",
    "SIMULATION", "HISTORICAL VALIDATION", "PRE-ALPHA READY", "ALPHA READY",
    "BETA READY", "QA", "UAT", "PRODUCTION READY", "LIVE", "DEPRECATED",
    "RETIRED", "BLOCKED",
}


# --- custody -----------------------------------------------------------------------

def _manifest() -> dict:
    """The manifest, parsed without a YAML dependency.

    Deliberately a few lines of parsing rather than an import: this file must be
    readable by the test that guards it even in an environment that has not
    installed anything."""
    data: dict = {"documents": {}}
    current = None
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- path:"):
            current = stripped.split(":", 1)[1].strip().strip('"')
            data["documents"][current] = None
        elif stripped.startswith("sha256:") and current:
            value = stripped.split(":", 1)[1].strip().strip('"')
            data["documents"][current] = None if value == "self" else value
        elif stripped.startswith("id:"):
            data.setdefault("custodian", stripped.split(":", 1)[1].strip())
    return data


def test_the_living_document_matches_the_digest_recorded_for_it():
    """Tamper-evidence, and only that.

    An edit made without the custodian's update step leaves the file and the
    manifest disagreeing, and the suite says so. This does not *prevent* an edit -
    whoever changes the text can change the digest - and `JARVIS.md` says so in
    the same breath as claiming it. Prevention needs signed commits, which is an
    owner action and is queued rather than implied."""
    recorded = _manifest()["documents"].get("docs/JARVIS.md")
    assert recorded, "the manifest records no digest for the living document"
    actual = hashlib.sha256(LIVING.read_bytes()).hexdigest()
    assert actual == recorded, (
        "docs/JARVIS.md has changed without its custody manifest being updated. "
        "If this was your edit, update docs/document_custody.yaml in the same "
        "commit. If it was not, somebody wrote to a document under custody."
    )


def test_the_guard_in_code_and_the_manifest_name_the_same_documents():
    """The guard keeps its own list on purpose - it must hold when the manifest is
    missing, unreadable, or edited to say something more convenient. Two lists
    that must agree drift apart unless something checks, so this checks."""
    assert set(repositories.CUSTODIAL_PATHS) == set(_manifest()["documents"])


def test_the_only_write_path_into_the_repository_refuses_a_custodial_document():
    for path in repositories.CUSTODIAL_PATHS:
        with pytest.raises(repositories.RepositoryError) as refusal:
            repositories._refuse_custodial(path)
        assert "custody" in str(refusal.value)
    # And an ordinary document still goes through.
    repositories._refuse_custodial("docs/specs/whatever.md")


def test_publish_actually_calls_the_guard():
    """A refusal function nothing calls is a comment.

    Asserted structurally rather than by publishing, because reaching `publish`
    needs a real repository and this is the property that matters: the guard runs
    on the way in, before any content is examined."""
    source = inspect.getsource(repositories.publish)
    assert "_refuse_custodial(relative)" in source


def test_reading_a_custodial_document_is_still_allowed():
    """Custody restricts writing, not reading. A document nobody may read is
    useless to the agents addendum 47 §9 wrote it for, and a read path that
    started refusing would be a silent regression of the document's purpose."""
    assert "_refuse_custodial" not in inspect.getsource(repositories.read_file)
    assert "_refuse_custodial" not in inspect.getsource(repositories.tracked_files)


def test_no_other_component_writes_into_docs():
    """The claim `JARVIS.md` makes is that the running system has exactly one
    write path into the repository and it refuses custodial documents. A second
    one - a module that opens a docs path for writing - would make that claim
    false without anybody editing the sentence."""
    offenders = []
    writers = {"write_text", "write_bytes", "writelines", "unlink", "rename", "replace"}
    for package in RUNTIME_PACKAGES:
        for source_file in (ROOT / package).rglob("*.py"):
            tree = ast.parse(source_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                literals = [a.value for a in ast.walk(node)
                            if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                touches_docs = any("docs/" in text or "docs\\" in text for text in literals)
                if not touches_docs:
                    continue
                if name in writers or (name == "open" and any(
                        "w" in text or "a" in text for text in literals[1:])):
                    offenders.append(f"{source_file.relative_to(ROOT)}:{node.lineno}")
    assert not offenders, f"components writing into docs/: {offenders}"


# --- the document describes a system that still looks like this ---------------------

def test_every_file_it_points_at_exists():
    missing = []
    for target in re.findall(r"\]\((?!http)([^)#]+)\)", TEXT):
        resolved = (DOCS / target).resolve()
        if not resolved.exists():
            missing.append(target)
    assert not missing, f"the living document links to files that do not exist: {missing}"


def _record_references() -> set[int]:
    """`§N` where N is a section of the change record.

    Addendum references are written `addendum 32 §19` or `47 §10` - a number, a
    space, then the section - so a `§` preceded by a number belongs to an
    addendum and not to the record."""
    found = set()
    for match in re.finditer(r"§(\d+)", TEXT):
        before = TEXT[max(0, match.start() - 12):match.start()]
        if re.search(r"\d\s$", before):
            continue
        found.add(int(match.group(1)))
    return found


def test_every_record_section_it_cites_exists():
    record = (DOCS / "SPEC_RECONCILIATION.md").read_text(encoding="utf-8")
    present = {int(n) for n in re.findall(r"^## §(\d+)", record, re.MULTILINE)}
    cited = _record_references()
    assert cited, "no record references found - the extraction is broken, not the document"
    assert cited <= present, f"cites sections that do not exist: {sorted(cited - present)}"


def test_every_task_it_names_is_in_the_queue():
    queue = (DOCS / "TASK_QUEUE.md").read_text(encoding="utf-8")
    named = set(re.findall(r"\bTQ-\d+\b", TEXT))
    missing = sorted(t for t in named if t not in queue)
    assert not missing, f"names tasks the queue does not have: {missing}"


def test_every_status_word_it_uses_is_addendum_47_vocabulary():
    """Backticked upper-case words in status positions. A status the standard does
    not define is either a typo or a vocabulary change nobody wrote down."""
    # Only where a status can appear: a table cell, or a line that says so.
    # Backticked capitals elsewhere are prose - `AAPL` in the market-data section
    # is a ticker, not a claim about readiness.
    lines = [line for line in TEXT.splitlines()
             if line.startswith("|") or "tatus" in line]
    used = {word for line in lines
            for word in re.findall(r"`([A-Z][A-Z \-]{2,})`", line)}
    unknown = used - STATUSES
    assert not unknown, f"status words addendum 47 §10 does not define: {sorted(unknown)}"


def test_it_still_claims_nothing_is_live():
    """The document states that nothing in the system is LIVE. The day something
    is, that sentence is wrong - so a status cell saying LIVE fails until the
    prose is corrected too."""
    assert "Nothing in this system is `LIVE`." in TEXT
    assert "| `LIVE` |" not in TEXT


def test_every_implemented_role_is_described():
    """A role added to the organization without a line in the map is a system the
    documentation no longer describes."""
    model = (DOCS / "organization.yaml").read_text(encoding="utf-8")
    # Roles only. `flows:` uses the same `- id:` shape one block down, and a flow
    # is not something the map is expected to name.
    block = model.split("roles:", 1)[1].split("\nflows:", 1)[0]
    roles = re.findall(r"^  - id: (\w+)", block, re.MULTILINE)
    assert roles, "no roles parsed from the organization model"
    lowered = TEXT.lower()
    missing = [r for r in roles
               if r.lower() not in lowered and r.replace("_", " ").lower() not in lowered]
    assert not missing, f"roles the living document does not mention: {missing}"


def test_the_number_of_addenda_it_states_is_the_number_on_disk():
    """It says how many supplied specifications there are. Assimilating one
    without updating the count is the small kind of drift addendum 47 §5 is
    about."""
    words = {41: "Forty-one", 42: "Forty-two", 43: "Forty-three", 44: "Forty-four",
             45: "Forty-five", 46: "Forty-six", 47: "Forty-seven", 48: "Forty-eight",
             49: "Forty-nine", 50: "Fifty", 51: "Fifty-one", 52: "Fifty-two"}
    count = len(list((DOCS / "addenda").glob("*.md")))
    assert words.get(count, "?") + " supplied specifications" in TEXT, (
        f"{count} addenda on disk; the living document says otherwise"
    )
