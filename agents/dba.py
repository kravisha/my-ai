"""The Database Administrator: continuous database health, and what it does when
a check fails (TASK_QUEUE TQ-106; addendum 53 §3, §3.3, §11;
docs/SPEC_RECONCILIATION.md §151).

Addendum 53 §11: *"The DBA specifically runs continuous or scheduled
database-health monitoring."* Unlike the Software Engineer and QA Engineer, which
§11 allows to idle until there is work, the DBA's work **is** the monitoring.

## The loop, and why it opens an issue rather than printing

`backend/vocabulary.py` and `backend/compliance.py` already answer *is the
database's vocabulary intact* and *is the work being evaluated properly*. Before
this agent, nothing ran them on a schedule and nothing read the answer - which is
the failure §149 recorded about the cooperation report and §126 about the governed
store: a mechanism that exists and changes nothing.

So a failing check **opens a software issue** (addendum 53 §6 step 1), and the
issue cannot be closed without a prevention and an adversarial proof. A check that
only printed would leave the organization exactly as informed as it was when
`compliance.self_evaluated` was flagging every grade and nobody read it.

## Idempotent by signature, not by cycle

The DBA runs every cycle and would otherwise file the same defect forever. Each
finding carries a stable signature, and `software_department.open_issue` returns
the existing issue's id when one is already open for it.

That is why `open_issue` returns rather than raises on a duplicate: a scheduled
caller that had to catch an exception to make progress would eventually have that
exception widened, and then a real refusal would be swallowed too.

## What it does not do

**It does not fix anything**, and it does not review its own findings. §53 §2's
triad investigates from three perspectives and the DBA supplies one; the root
cause is gated on all three coming from three identities, so a DBA that opened
and closed its own issues would be the silo §2 forbids.
"""

from __future__ import annotations

import sys

from agents.base import run_agent
from backend import compliance, fi_db, software_department, vocabulary

ROLE = "dba"


def _finding_signature(kind: str, detail: str) -> str:
    """A stable name for *this same finding again*.

    Deliberately built from what the finding **is** rather than from when it was
    seen: a signature containing a timestamp would make every cycle a new issue,
    which is the flood the uniqueness index exists to prevent."""
    return f"{kind}:{detail}"


def health_check(conn) -> list[dict]:
    """Run the checks addendum 53 §3.3 asks for, and return what they found.

    Returns findings **and** is expected to be read alongside the checks' own
    evidence: `vocabulary.check` reports an `INCONCLUSIVE` verdict when it
    examined nothing, and a DBA that treated that as health would be doing what
    §3.3 forbids in terms - *"A check that passes merely because a query returned
    nothing is not considered a valid health check."*"""
    findings = []

    vocab = vocabulary.check(conn)
    if vocab["verdict"] == "FAIL":
        for item in vocab["findings"]:
            where = item.get("file") or f"{item['table']}.{item['column']}"
            findings.append({
                "kind": "vocabulary",
                "signature": _finding_signature(
                    "vocabulary", f"{where}:{item.get('line', item.get('value'))}"),
                "observed": (
                    f"{item['table']}.{item['column']} is used with "
                    f"{item.get('literal', item.get('value'))!r}, which the vocabulary "
                    f"contract does not allow."),
                "evidence": str(item),
                "component": where,
                "expected": f"one of {item['allowed']}",
                "classification": "database_schema",
                "severity": software_department.SEVERITY_HIGH,
            })
    elif vocab["verdict"] == "INCONCLUSIVE":
        # Not a pass and not a failure. §3.3: a check that verified nothing has
        # not reported health, and saying so is the point of the third value.
        findings.append({
            "kind": "vocabulary_inconclusive",
            "signature": _finding_signature("vocabulary", "inconclusive"),
            "observed": "The vocabulary check examined no literals and no rows.",
            "evidence": str({k: vocab[k] for k in ("literals_checked", "rows_examined")}),
            "component": "backend/vocabulary.py",
            "expected": "a check that verified a meaningful population",
            "classification": "observability",
            "severity": software_department.SEVERITY_NORMAL,
        })

    for row in compliance.self_evaluated(conn):
        findings.append({
            "kind": "self_evaluated",
            "signature": _finding_signature("self_evaluated", str(row["item"])),
            "observed": (
                f"Report {row['item']} was graded by {row['grader']}, which filed it. "
                f"The grade carries no independent information."),
            "evidence": str(dict(row)),
            "component": "backend/compliance.py",
            "expected": "a grade written by the consumer of the work, not its producer",
            "classification": "software_logic",
            "severity": software_department.SEVERITY_HIGH,
        })
    return findings


def _dba_work(conn, identity: str) -> None:
    findings = health_check(conn)
    if not findings:
        return
    for finding in findings:
        issue = software_department.open_issue(
            conn,
            observed=finding["observed"], evidence=finding["evidence"],
            component=finding["component"], expected=finding["expected"],
            signature=finding["signature"], classification=finding["classification"],
            severity=finding["severity"], opened_by=identity)
        print(f"[dba] {finding['kind']}: issue {issue} - {finding['observed'][:90]}")


def main() -> None:  # pragma: no cover - process entry point
    if len(sys.argv) != 2:
        print("usage: python -m agents.dba <identity>", file=sys.stderr)
        raise SystemExit(1)
    identity = sys.argv[1]

    def work_fn(conn) -> None:
        _dba_work(conn, identity)

    run_agent(identity=identity, role=ROLE, work_fn=work_fn)


if __name__ == "__main__":  # pragma: no cover
    main()
