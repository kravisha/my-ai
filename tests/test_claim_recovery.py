"""Every claim must be recoverable, and the registry that keeps it that way
(docs/SPEC_RECONCILIATION.md §154, §155; ARCHITECTURE_READINESS_REVIEW.md B6).

A claim is how this system makes two workers safe: a guarded UPDATE, so a loser
sees rowcount zero instead of duplicating work. It also creates a way to lose
work that did not exist before it. An agent that dies between claiming and
completing leaves the row in its in-progress state, naming a process that is
gone, and the queue's own "what is waiting?" query stops returning it. Nothing
fails. Nothing is logged. The work simply stops.

`discovery_reports` learned this and grew `release_stale_claims`.
`engineering_directives` had `claimed_by` and no `claimed_at` for two increments
after that, and the readiness review did not find it either - it named the wrong
table.

So the fix that lasts is not another sweep function. It is this: **the schema is
scanned for claim-shaped columns, and every one of them must be declared here
with the thing that recovers it.** A future table that grows a `claimed_*` column
fails this file until somebody says how an abandoned claim comes back.

Two channels deliberately have no claim, and are recorded here so their absence
reads as a decision rather than an omission:

- `coo_directives` goes pending -> completed with nothing in between. The
  Controller is a single consumer and completes in the same cycle it fetches, so
  a death leaves the row `pending`, which is the safe resting state.
- `software_issues` moves open -> reviewed -> corrected -> closed. Each
  transition is a completed step, not an ownership claim; a death leaves the
  issue at its last finished state and anyone may pick it up.
"""

import ast
import inspect
import re

import pytest

from agents import coo
from backend import engineering, fi_db

# Table -> how an abandoned claim on it comes back.
#
# `sweep` is the callable that returns claims to the queue, or None when the
# recovery is something else entirely - which is only allowed with a reason.
CLAIM_RECOVERY = {
    "discovery_reports": {
        "sweep": fi_db.release_stale_claims,
        "timeout": fi_db.CLAIM_TIMEOUT_SECONDS,
        "why": "Measured against a judgment cycle: ~19.5s of model call with an "
               "observed 42s outlier.",
    },
    "engineering_directives": {
        "sweep": engineering.release_stale_claims,
        "timeout": engineering.CLAIM_TIMEOUT_SECONDS,
        "why": "Sized against database work, because handle() makes no model call. "
               "The only unbounded wait is SQLite lock contention, capped at 5s.",
    },
    "portfolio_analysis_requests": {
        "sweep": None,
        "timeout": None,
        "why": "Recovered by row expiry rather than claim expiry. The whole request "
               "carries a TTL and `purge_expired` deletes it - correct here, because "
               "a client's request that outlived its session must not be resurrected "
               "and served. §111: the database is a transport, not a store.",
    },
}

# Columns that mean "somebody has taken this and is working on it".
_CLAIM_COLUMN = re.compile(r"^claimed_")


def _tables_with_claim_columns() -> set[str]:
    """Every table in the schema carrying a claim-shaped column.

    Read from the DDL rather than from a live database, so a table nobody has
    created yet is still covered.

    The schema sources come from `fi_db.apply_additive_migrations`' own tuple
    rather than a list maintained here. That list is already the canonical answer
    to *every module that owns tables*, and it is kept correct by a different
    pressure - a module missing from it silently loses column migrations. A second
    hand-maintained copy would drift, and drift in this one is a table whose claim
    nobody checks."""
    found = set()
    for schema in fi_db.SCHEMA_SOURCES:
        for block in re.finditer(
                r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\n\);", schema, re.S):
            table, body = block.group(1), block.group(2)
            for line in body.splitlines():
                column = line.strip().split(" ")[0].rstrip(",")
                if _CLAIM_COLUMN.match(column):
                    found.add(table)
    return found


def test_every_claimed_table_declares_how_its_claims_are_recovered():
    """The tripwire the readiness review asked for, and the one that would have
    caught this defect two increments earlier.

    A new table with a `claimed_*` column fails here until its recovery is
    declared. That is the whole point: the failure mode is silent, so the guard
    has to fire at the moment the claim is introduced rather than the moment
    somebody notices the queue went quiet."""
    undeclared = _tables_with_claim_columns() - set(CLAIM_RECOVERY)
    assert not undeclared, (
        f"tables carry a claim with no declared recovery: {sorted(undeclared)}. "
        "An agent that dies holding one of these strands the work silently - the "
        "queue's pending query stops seeing it and nothing fails. Declare the sweep "
        "in CLAIM_RECOVERY, or say why the claim recovers some other way."
    )


def test_the_registry_does_not_name_tables_that_have_no_claim():
    """The other side of it. A registry that accumulated dead entries would keep
    passing while describing a system that no longer exists - which is §149's
    shape, and this file exists to prevent that shape, not to add one."""
    stale = set(CLAIM_RECOVERY) - _tables_with_claim_columns()
    assert not stale, (
        f"CLAIM_RECOVERY names tables with no claim column: {sorted(stale)}. "
        "Either the column was removed and the entry should go, or the schema "
        "source it lives in is missing from _tables_with_claim_columns."
    )


def test_every_declared_sweep_has_a_justified_timeout():
    """A timeout below the real hold time steals a working agent's claim, which
    reintroduces the duplication the claim exists to prevent. Three timing
    constants in this project have been wrong that way, so each one states what
    it was sized against."""
    for table, entry in CLAIM_RECOVERY.items():
        assert entry["why"].strip(), f"{table} declares no justification for its recovery"
        if entry["sweep"] is not None:
            assert entry["timeout"] and entry["timeout"] > 0, (
                f"{table} declares a sweep with no timeout")


def _calls(module, name: str) -> bool:
    tree = ast.parse(inspect.getsource(module))
    return any(
        (node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", ""))
        == name
        for node in ast.walk(tree) if isinstance(node, ast.Call))


@pytest.mark.parametrize("sweep_name", ["release_stale_claims"])
def test_the_coo_runs_the_sweeps(sweep_name):
    """Declared and never called is the same as absent (§134).

    Both sweeps are named `release_stale_claims` on different modules, so one
    assertion over the COO's source covers both - and the count matters, because
    dropping one call while keeping the other would still satisfy a bare `in`
    check."""
    tree = ast.parse(inspect.getsource(coo))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == sweep_name
    ]
    modules = {node.func.value.id for node in calls if isinstance(node.func.value, ast.Name)}
    assert modules == {"fi_db", "engineering"}, (
        f"the COO cycle sweeps {sorted(modules)}; it must sweep both claimed queues. "
        "The recovery of a queue must not depend on a worker of that queue (§154), "
        "which is why this is asserted on the COO and not on the agents themselves."
    )
