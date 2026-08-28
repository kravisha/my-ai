"""Documents held privately stay out of this repository
(docs/PUBLIC_PRIVATE_BOUNDARY.md; docs/SPEC_RECONCILIATION.md §141).

The boundary has been a written practice since 2026-08-16 and had nothing
enforcing it. On 2026-08-28 that cost something: addendum 49 — the Constitution
— was assimilated into `docs/addenda/` in the ordinary way, because *assimilate
the supplied documents verbatim* is the intake rule and nothing asked whether
this one belonged in a public repository. It reached exactly one local commit
and was removed from history before any push.

**A rule that is only prose gets followed until somebody is busy.** This is the
mechanism, on the same argument §120 makes about the safest write path being one
that does not exist, and the same shape as the import tripwire that keeps
portfolio storage from returning.

## What this does not claim

It is not a security control, and `PUBLIC_PRIVATE_BOUNDARY.md` says so about the
boundary itself: it protects intellectual property, never credentials or customer
data. This test catches the *accident* — a private document assimilated by habit —
and nothing here would stop somebody who meant it.
"""

from __future__ import annotations

import re
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"

# Held privately, and named here by the identifier the public documents use.
# From `PUBLIC_PRIVATE_BOUNDARY.md` and README's index: the philosophy is
# private, the technical what-and-how is public (owner direction 2026-08-28).
PRIVATE_ADDENDA = (5, 11, 15, 22, 49)

# The Constitution's filename across both its versions. v1 was separated from
# history when the boundary was adopted; v2 is addendum 49.
PRIVATE_FILES = ("JARVIS_CONSTITUTION.md",)


def test_no_privately_held_addendum_is_in_the_repository():
    """The accident this exists for, in the exact shape it happened."""
    present = {
        int(match.group(1)): path.name
        for path in (DOCS / "addenda").glob("*.md")
        if (match := re.match(r"addendum_(\d+)_", path.name))
    }
    leaked = {n: present[n] for n in PRIVATE_ADDENDA if n in present}
    assert not leaked, (
        f"privately-held addenda are in this public repository: {leaked}. "
        f"They are referenced by identifier and never by file - see "
        f"docs/PUBLIC_PRIVATE_BOUNDARY.md."
    )


def test_no_privately_held_document_is_in_docs():
    found = [name for name in PRIVATE_FILES if (DOCS / name).exists()]
    assert not found, f"privately-held documents are in this public repository: {found}"


def test_the_public_documents_reference_the_private_ones_without_a_link():
    """*A reference you cannot follow means the document is private, not
    missing.* A markdown link to a file that is not here is worse than a bare
    identifier: it reads as a broken repository rather than a deliberate
    boundary, and the next person 'fixes' it by adding the file back."""
    broken = []
    for path in DOCS.rglob("*.md"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for target in re.findall(r"\]\(([^)]+\.md)\)", text):
            if target.startswith(("http://", "https://", "#")):
                continue
            if not (path.parent / target).resolve().exists():
                broken.append(f"{path.relative_to(DOCS)} -> {target}")
    assert not broken, (
        f"links to documents that are not in this repository: {broken}. If the target is "
        f"held privately, name it without a link."
    )
