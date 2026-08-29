"""The Database Vocabulary Contract, and the audits that keep it true
(TASK_QUEUE TQ-105; addendum 53 §3.3, §7.2, §7.3, §7.4, §7.6, §7.7, §8, §9;
docs/SPEC_RECONCILIATION.md §147, §149, §150).

Addendum 53 §8 asks for one authoritative definition per closed vocabulary, so
that *"'open', 'answered', 'evidence', 'pending', and similar words cannot drift
independently across code, comments, tests, and database records."*

**Three defects in two days were exactly that drift**, and none of them decayed
into existence - each was wrong on the day it was written and passed every test:

| Written | Reality | How it failed |
|---|---|---|
| `outcome = 'answered'` in a comment | the code writes `'evidence'` | a query built from the comment matched nothing |
| `status = 'open'` in a metric | the vocabulary is `pending`/`resolved`/`consumed` | `open_at_end` was structurally always zero, and a scenario asserted `0 == 0` |
| a join on `analysis_results.producer_identity` | that column equals the grader by construction | `self_evaluated` flagged every grade and could never return false |

§149 §4 named what they share: **a value written by hand into a query, where
nothing checks it corresponds to anything.** A bad constant fails at import; a
bad literal fails by returning nothing, which reads as good news.

This module is the safeguard that turns those three repairs into one rule.

## The contract does not restate the vocabulary. It points at it.

Every entry below takes its allowed values from the constants that already
define them. A contract that spelled the values again would be a fourth place
for them to drift - the disease presenting as the cure, and precisely what §7.7
forbids by ranking *approved domain contract* above *comments*.

## What a passing check means here

Addendum 53 §9 rules 2 and 3: a health check must show it queried a meaningful
population, and a PASS must carry enough evidence to say what was examined.

So `check()` returns what it **looked at** alongside what it found, and
`audit_literals` reports the number of literals it *resolved to a contracted
column* rather than only the violations. A scan that matched nothing would
otherwise be indistinguishable from a clean codebase - which is the same failure
this module exists to prevent, one level up.

## What it deliberately does not cover

The contract is **partial and says so**. It covers the vocabularies involved in
the three defects plus the ones a wrong literal would most damage. Declaring
every closed vocabulary in the system would be a large guess, and a contract
containing entries nobody verified would be worse than a short one: it would make
`audit_literals` confident about columns whose real vocabulary nobody had checked.

`UNCONTRACTED` names what is known to be missing, so absence is a stated gap
rather than an implied all-clear.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from backend import fi_db
from backend.db import Database

ROOT = Path(__file__).resolve().parent.parent
TREES = ("app", "backend", "gateway", "agents", "simulation")


class VocabularyViolation(ValueError):
    """A value outside the contract for the column it was written to."""


# (table, column) -> the values that column may hold.
#
# **Taken from the constants, never spelled again.** This is the whole design:
# one definition, referenced everywhere, so a rename fails at import instead of
# silently matching nothing.
CONTRACT: dict[tuple[str, str], tuple[str, ...]] = {
    ("cross_check_requests", "outcome"): (
        fi_db.CROSS_CHECK_EVIDENCE,
        fi_db.CROSS_CHECK_NO_EVIDENCE,
        fi_db.CROSS_CHECK_UNANSWERED,
    ),
    ("cross_check_requests", "status"): (
        fi_db.CROSS_CHECK_PENDING,
        fi_db.CROSS_CHECK_RESOLVED,
        fi_db.CROSS_CHECK_CONSUMED,
    ),
    ("agent_registry", "lifecycle_state"): (
        fi_db.LIFECYCLE_ACTIVE,
        fi_db.LIFECYCLE_DORMANT,
    ),
    ("agent_registry", "process_state"): (
        fi_db.PROCESS_RUNNING,
        fi_db.PROCESS_STOPPED,
        fi_db.PROCESS_CRASHED,
    ),
    ("knowledge_records", "record_kind"): (
        fi_db.KNOWLEDGE_LESSON,
        fi_db.KNOWLEDGE_OPEN_QUESTION,
        fi_db.KNOWLEDGE_CORRECTIVE,
    ),
    ("knowledge_records", "status"): (
        fi_db.KNOWLEDGE_ACTIVE,
        fi_db.KNOWLEDGE_SUPERSEDED,
        fi_db.KNOWLEDGE_RESOLVED,
    ),
}

# Columns with a closed vocabulary that this contract does **not** yet declare.
# Named rather than omitted: a short contract is honest, and a silent one implies
# the columns it skips have been checked (addendum 53 §9 rule 3, and 47 §17's
# rule that an unfinished thing is never written as if it were built).
UNCONTRACTED = (
    "intelligence_artifacts.status - proposed/active/stale/superseded/rejected, "
    "declared across several call sites rather than one constant block",
    "strategies.status, incidents.status, coo_directives.status, "
    "discovery_reports.status - each closed, none with a single definition to "
    "point at",
    "release and appeal vocabularies - defined as module constants in "
    "backend/release.py and backend/appeal.py and not yet mapped to their columns",
)


def allowed(table: str, column: str) -> tuple[str, ...] | None:
    """The contracted values for a column, or None if it is not contracted.

    None and `()` are different answers and must stay so: *not contracted* is a
    gap, *contracted as empty* would be a column nothing may be written to."""
    return CONTRACT.get((table, column))


def validate(table: str, column: str, value) -> None:
    """Refuse a value the contract does not allow (addendum 53 §7.2, §9 rule 5).

    **Fails loudly**, which is the point. Every defect this module exists for
    failed *quietly* - by matching nothing - and a vocabulary that can only be
    got wrong at read time is one where the write side is free to invent."""
    permitted = allowed(table, column)
    if permitted is None or value is None:
        return
    if value not in permitted:
        raise VocabularyViolation(
            f"{table}.{column} does not take {value!r}. The contract allows "
            f"{list(permitted)} (backend/vocabulary.py). A value outside it would be "
            f"written successfully and never match a query again.")


# --- the audits ------------------------------------------------------------------------

# `column = 'literal'`, and the `IN ('a','b')` form.
_EQUALITY = re.compile(r"(\w+)\s*(?:=|<>|!=)\s*'([a-z_][a-z0-9_]*)'", re.I)
_MEMBERSHIP = re.compile(r"(\w+)\s+IN\s*\(([^)]*'[^)]*)\)", re.I)
_TABLES = re.compile(r"\b(?:FROM|JOIN|UPDATE|INTO)\s+([a-z_][a-z0-9_]*)", re.I)
_IS_SQL = re.compile(r"\b(?:SELECT|UPDATE|DELETE\s+FROM|INSERT\s+INTO)\b", re.I)


def audit_literals(root: Path | None = None) -> dict:
    """Find SQL literals compared against a contracted column that the contract
    does not allow (addendum 53 §7.6, §9 rule 7).

    **This is the check that would have caught all three defects.** It reads the
    source rather than the database on purpose: a value can be absent from a
    database because it has not happened yet, and absent from the *contract*
    because nothing can ever write it. Only the second is a defect, and only the
    contract can tell them apart.

    A query naming more than one table is skipped rather than guessed at, and the
    count of skipped queries is returned - precision over recall, with the recall
    stated so nobody reads a clean result as total coverage.
    """
    root = root or ROOT
    findings, checked, ambiguous = [], 0, 0

    for tree in TREES:
        for path in sorted((root / tree).rglob("*.py")):
            try:
                parsed = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - defensive
                continue
            for node in ast.walk(parsed):
                if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                    continue
                sql = node.value
                if not _IS_SQL.search(sql):
                    continue
                tables = {t.lower() for t in _TABLES.findall(sql)}
                contracted = {t for t, _ in CONTRACT} & tables
                if len(contracted) != 1:
                    if contracted:
                        ambiguous += 1
                    continue
                table = contracted.pop()
                pairs = list(_EQUALITY.findall(sql))
                pairs += [(col, v) for col, vals in _MEMBERSHIP.findall(sql)
                          for v in re.findall(r"'([a-z_][a-z0-9_]*)'", vals)]
                for column, literal in pairs:
                    permitted = allowed(table, column)
                    if permitted is None:
                        continue
                    checked += 1
                    if literal not in permitted:
                        findings.append({
                            "file": str(path.relative_to(root)).replace("\\", "/"),
                            "line": node.lineno,
                            "table": table,
                            "column": column,
                            "literal": literal,
                            "allowed": list(permitted),
                        })
    return {
        "findings": findings,
        # Addendum 53 §9 rule 2. Without this a scan that resolved nothing looks
        # exactly like a clean codebase, which is the failure being guarded
        # against, one level up.
        "literals_checked": checked,
        "queries_skipped_as_ambiguous": ambiguous,
    }


def audit_stored_values(conn: Database) -> dict:
    """Values in the live database that the contract does not allow.

    The other direction. `audit_literals` catches a query that can never match;
    this catches a **write** that got in before the contract existed, or through
    a path that does not validate.

    Reports the population it examined, because a clean result over an empty
    table is not evidence (addendum 53 §9 rules 1 and 2)."""
    findings, examined = [], {}
    for (table, column), permitted in sorted(CONTRACT.items()):
        if conn.fetchone("SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
                         (table,)) is None:
            continue
        rows = conn.fetchall(
            f"SELECT {column} AS value, COUNT(*) AS n FROM {table}"
            f" WHERE {column} IS NOT NULL GROUP BY {column}")
        examined[f"{table}.{column}"] = sum(row["n"] for row in rows)
        for row in rows:
            if row["value"] not in permitted:
                findings.append({
                    "table": table, "column": column, "value": row["value"],
                    "rows": row["n"], "allowed": list(permitted),
                })
    return {
        "findings": findings,
        # A count per column, not a total. "Nothing wrong in 400 rows" and
        # "nothing wrong in 400 rows of one column and none of the other five"
        # are different claims.
        "rows_examined": examined,
    }


def check(conn: Database, root: Path | None = None) -> dict:
    """The DBA's vocabulary health check (addendum 53 §3.3).

    *"A successful health check must mean that something meaningful was actually
    verified. A check that passes merely because a query returned nothing is not
    considered a valid health check."* (§3.3)

    So `healthy` is not simply *no findings*. A run that resolved no literals and
    examined no rows has verified nothing, and says so."""
    literals = audit_literals(root)
    stored = audit_stored_values(conn)
    examined_rows = sum(stored["rows_examined"].values())
    findings = literals["findings"] + stored["findings"]
    return {
        "findings": findings,
        "literals_checked": literals["literals_checked"],
        "queries_skipped_as_ambiguous": literals["queries_skipped_as_ambiguous"],
        "rows_examined": stored["rows_examined"],
        # The three-valued verdict `simulation/verification.py` uses, for the same
        # reason: nothing failed and nothing was asked is not a pass.
        "verdict": (
            "FAIL" if findings
            else "INCONCLUSIVE" if not literals["literals_checked"] and not examined_rows
            else "PASS"),
        "contract_covers": [f"{t}.{c}" for t, c in sorted(CONTRACT)],
        "not_covered": list(UNCONTRACTED),
    }
