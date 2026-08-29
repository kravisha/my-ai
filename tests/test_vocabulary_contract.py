"""The Database Vocabulary Contract and its audits (TQ-105; addendum 53 §3.3,
§7.2, §7.3, §7.4, §7.6, §7.7, §8, §9; docs/SPEC_RECONCILIATION.md §147, §149, §150).

Addendum 53 §5.3 sets the standard these are written to:

> *Every tripwire must be demonstrated to fail under a deliberately constructed
> bad state. A tripwire is not accepted merely because it has historically
> passed.*

And asks five questions of every important tripwire. For this one:

1. **What failure is it detecting?** A domain value written by hand into a query
   that nothing can ever have written to that column.
2. **What data triggers it?** `test_the_audit_catches_both_defects_that_shipped`
   reconstructs the two literals that actually shipped.
3. **Has it been observed failing?** Yes — that test is the observation, and it
   fails if the audit stops finding them.
4. **Can it pass because the query matched nothing?** No:
   `test_a_scan_that_resolved_nothing_is_not_a_pass` forces exactly that.
5. **Is the test vocabulary independent of the implementation?** §7.5's demand.
   `test_the_contract_matches_the_values_the_code_actually_writes` derives the
   expected values from the **database**, not from the contract being tested.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from backend import fi_db, vocabulary


@pytest.fixture
def tree():
    """A throwaway source tree the audit can be pointed at."""
    root = Path(tempfile.mkdtemp())
    (root / "backend").mkdir()
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _source(tree, text):
    (tree / "backend" / "queries.py").write_text(text, encoding="utf-8")


# --- the tripwire is proven to fail, on the exact defects that shipped -------------------

def test_the_audit_catches_both_defects_that_shipped(tree):
    """**The observation §5.3 question 3 asks for.**

    Both literals are reconstructed as they were actually written. If this test
    ever passes with zero findings, the safeguard has stopped working and the
    two defects could ship again unnoticed."""
    _source(tree, (
        "A = \"SELECT COUNT(*) AS n FROM cross_check_requests WHERE status = 'open'\"\n"
        "B = \"SELECT * FROM cross_check_requests WHERE outcome = 'answered'\"\n"))

    findings = vocabulary.audit_literals(tree)["findings"]
    caught = {(f["column"], f["literal"]) for f in findings}
    assert ("status", "open") in caught, "the metrics.open_at_end defect would ship again"
    assert ("outcome", "answered") in caught, "the schema-comment defect would ship again"


def test_a_valid_literal_is_not_flagged(tree):
    """A tripwire that fired on everything would be turned off within a week."""
    _source(tree, (
        "A = \"SELECT * FROM cross_check_requests WHERE outcome = 'evidence'\"\n"
        "B = \"SELECT * FROM cross_check_requests WHERE status = 'pending'\"\n"))
    assert vocabulary.audit_literals(tree)["findings"] == []


def test_the_in_form_is_caught_too(tree):
    """`IN ('a','b')` hides a bad value beside good ones, which is how one
    survives review."""
    _source(tree, (
        "A = \"SELECT * FROM cross_check_requests WHERE outcome IN "
        "('evidence', 'answered')\"\n"))
    findings = vocabulary.audit_literals(tree)["findings"]
    assert [f["literal"] for f in findings] == ["answered"]


def test_the_live_codebase_has_no_contracted_literal_violations():
    """The audit run against this repository. It passes today **because §147 and
    §149 fixed the two it would have caught** — which is why the test above
    exists: a clean result here is only meaningful if the scan can still fail."""
    result = vocabulary.audit_literals()
    assert result["findings"] == [], (
        f"hand-written literals outside the contract: {result['findings']}")
    assert result["literals_checked"] > 0, (
        "the scan resolved no literals at all, so a clean result says nothing")


# --- an empty scan is not a pass (§3.3, §9 rules 1-3) ------------------------------------

def test_a_scan_that_resolved_nothing_is_not_a_pass(conn, tree):
    """*"A check that passes merely because a query returned nothing is not
    considered a valid health check."* (§3.3)

    An empty source tree and an empty database produce no findings, and the
    verdict is `INCONCLUSIVE` rather than `PASS`."""
    _source(tree, "X = 1\n")
    result = vocabulary.check(conn, tree)

    assert result["findings"] == []
    assert result["literals_checked"] == 0
    assert result["verdict"] == "INCONCLUSIVE", (
        "a check that examined nothing reported itself healthy")


def test_a_check_over_real_rows_reports_what_it_examined(conn):
    """§9 rule 3: a PASS must carry enough evidence to say what was checked.
    *Nothing wrong in 400 rows* and *nothing wrong in one column and none of the
    other five* are different claims, so the count is per column."""
    fi_db.register_agent(conn, "explorer-1", "explorer", pid=1)
    result = vocabulary.check(conn)

    assert result["verdict"] == "PASS"
    assert result["rows_examined"]["agent_registry.lifecycle_state"] == 1
    assert set(result["rows_examined"]) >= {
        "cross_check_requests.outcome", "knowledge_records.status"}


def test_the_check_names_what_the_contract_does_not_cover(conn):
    """A short contract is honest; a silent one implies the columns it skips have
    been checked (47 §17)."""
    result = vocabulary.check(conn)
    assert result["not_covered"], "the contract claims total coverage"
    assert any("intelligence_artifacts" in line for line in result["not_covered"])


# --- the write side cannot invent a value (§7.2, §9 rule 5) -------------------------------

def test_an_outcome_outside_the_contract_is_refused_at_the_write(conn):
    """**The regression test §7.2 asks for**, and the direction that was missing.
    A value that can only be got wrong at read time is one the write side is free
    to invent — and `'answered'` survived in a comment for months precisely
    because nothing would have rejected it."""
    request = fi_db.open_cross_check(
        conn, "speculator-1", "t0", "speculator", "explorer", "SYN1",
        question="q", requester_finding={})

    for invented in ("answered", "open", "maybe", "ANSWERED"):
        with pytest.raises(vocabulary.VocabularyViolation) as refusal:
            fi_db.answer_cross_check(conn, request, "explorer-1", "t0", invented,
                                     responder_finding={})
        assert "does not take" in str(refusal.value)

    fi_db.answer_cross_check(conn, request, "explorer-1", "t0",
                             fi_db.CROSS_CHECK_EVIDENCE, responder_finding={})
    assert conn.fetchone("SELECT outcome FROM cross_check_requests")["outcome"] == "evidence"


def test_an_uncontracted_column_is_not_policed(conn):
    """`None` and `()` are different answers. *Not contracted* is a gap; *contracted
    as empty* would be a column nothing may be written to, and validating an
    uncontracted column against nothing would refuse every write."""
    assert vocabulary.allowed("intelligence_artifacts", "status") is None
    vocabulary.validate("intelligence_artifacts", "status", "anything at all")


def test_a_value_already_in_the_database_outside_the_contract_is_found(conn):
    """The other direction: a write that got in before the contract existed, or
    through a path that does not validate. Written directly, because the
    production path now refuses it — which is what makes this the *audit's* job."""
    conn.execute(
        "INSERT INTO cross_check_requests (created_at, requester_identity,"
        " requester_spawned_at, requester_role, responder_role, security, question,"
        " requester_finding, status, outcome, schema_version)"
        " VALUES ('t', 'a', 't', 'speculator', 'explorer', 'SYN1', 'q', '{}',"
        " 'consumed', 'answered', 1)")

    result = vocabulary.audit_stored_values(conn)
    assert [(f["column"], f["value"]) for f in result["findings"]] == [("outcome", "answered")]
    assert result["rows_examined"]["cross_check_requests.outcome"] == 1
    assert vocabulary.check(conn)["verdict"] == "FAIL"


# --- the contract is derived, not restated (§7.5, §7.7) -----------------------------------

def test_the_contract_points_at_the_constants_rather_than_copying_them():
    """§7.7's order of authority. A contract that spelled the values again would
    be a fourth place for them to drift — the disease presenting as the cure."""
    assert vocabulary.CONTRACT[("cross_check_requests", "outcome")] == (
        fi_db.CROSS_CHECK_EVIDENCE, fi_db.CROSS_CHECK_NO_EVIDENCE,
        fi_db.CROSS_CHECK_UNANSWERED)

    source = (Path(vocabulary.__file__)).read_text(encoding="utf-8")
    contract = source[source.index("CONTRACT:"):source.index("# Columns with a closed")]
    for spelled in ("'evidence'", '"evidence"', "'pending'", '"pending"'):
        assert spelled not in contract, (
            f"the contract spells {spelled} literally instead of naming the constant")


def test_the_contract_matches_the_values_the_code_actually_writes(conn):
    """**§7.5's rule: the expected values come from somewhere other than the thing
    under test.**

    Derived from the *database* after exercising the real production paths, not
    from `CONTRACT`. If both were read from the contract, this would confirm the
    contract against itself — which is exactly how the tests that missed §147's
    defect were built."""
    fi_db.register_agent(conn, "explorer-1", "explorer", pid=1)
    request = fi_db.open_cross_check(
        conn, "speculator-1", "t0", "speculator", "explorer", "SYN1",
        question="q", requester_finding={})
    fi_db.answer_cross_check(conn, request, "explorer-1", "t0",
                             fi_db.CROSS_CHECK_NO_EVIDENCE, responder_finding={})
    fi_db.record_knowledge(conn, record_kind="open_question", subject="SYN1",
                           statement="s", recorded_by="explorer-1")

    for table, column in (("cross_check_requests", "outcome"),
                          ("cross_check_requests", "status"),
                          ("agent_registry", "lifecycle_state"),
                          ("agent_registry", "process_state"),
                          ("knowledge_records", "record_kind"),
                          ("knowledge_records", "status")):
        written = {row["v"] for row in conn.fetchall(
            f"SELECT DISTINCT {column} AS v FROM {table} WHERE {column} IS NOT NULL")}
        assert written <= set(vocabulary.CONTRACT[(table, column)]), (
            f"{table}.{column} holds {written - set(vocabulary.CONTRACT[(table, column)])}, "
            f"which the contract does not allow — the contract is wrong, not the data")
