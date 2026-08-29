"""Which scenario properties have ever been observed failing
(TASK_QUEUE TQ-106; addendum 53 §5.3, §7.4; docs/SPEC_RECONCILIATION.md §149, §151).

Addendum 53 §5.3 asks five questions of every important tripwire, and the third is
the one that can be answered from evidence rather than by survey:

> **3. Has the tripwire actually been observed failing under that condition?**

Every scenario run writes a `summary.json` with a `property_results` block - each
property, what it asserted, what it observed, whether it passed. Eighty-odd runs
of it were on disk before anything read them for this.

## Why this is here and not in `agents/qa_engineer.py`

It was written there first, and `test_no_agent_can_tell_it_is_in_a_simulation`
refused it: *"an agent has one code path, and what changes between training and
production is what answers its call."* An agent that reads `simulation/runs` knows
it is being simulated.

The tripwire was right and the first design was wrong. **The capability is QA's;
the data is the harness's** - so the reader lives here, where scenario runs are
already a first-class idea, and the QA role invokes it when auditing rather than
on an agent's work cycle.

## What it deliberately cannot tell you

**It cannot distinguish *correctly always zero* from *structurally cannot be
non-zero*.** `no agent was respawned` should be zero in every healthy run; so
should a property whose query can never match. From outside they are the same
number.

Only a forced-failure proof separates them, which is why this produces a
**worklist of properties needing a proof**, not a list of findings. Reporting them
as defects would repeat §150 §6's mistake - 37 findings, none real - and a
tripwire that fires on everything is turned off within a week.

The one this would have caught is on the worklist rather than in a findings list:
`no cross-check was left open` passed in every recorded run because its query
filtered on a status that does not exist (§149 §3).
"""

from __future__ import annotations

import json
from pathlib import Path

RUNS = Path(__file__).resolve().parent / "runs"


def observed_failures(runs_dir: Path | None = None) -> dict:
    """Every scenario property, and whether the recorded history has ever seen it
    fail (addendum 53 §5.3 question 3).

    Returns `proven` - properties observed failing at least once - and `unproven`,
    with the number of runs each was observed passing. **The run count matters**:
    a property passing in one run is untested, and one passing in eighty is
    untested in a much more convincing way, which is exactly the trap §5.3's
    *"not accepted merely because it has historically passed"* names."""
    runs_dir = runs_dir or RUNS
    seen: dict[str, dict] = {}
    runs_read = 0
    if not runs_dir.exists():
        return {"proven": [], "unproven": [], "runs_read": 0}

    for summary_path in sorted(runs_dir.glob("*/summary.json")):
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):  # pragma: no cover - a truncated run directory
            continue
        runs_read += 1
        scenario = summary.get("scenario_id", "?")
        for result in summary.get("property_results") or []:
            key = f"{scenario}::{result.get('name')}"
            record = seen.setdefault(key, {
                "scenario": scenario, "property": result.get("name"),
                "metric": result.get("metric"), "passes": 0, "failures": 0,
                "observed_values": set(),
            })
            record["passes" if result.get("passed") else "failures"] += 1
            record["observed_values"].add(repr(result.get("observed")))

    for record in seen.values():
        # Named rather than counted: *this property has only ever seen one value*
        # is the fact that makes an unproven one worth looking at, and a count of
        # distinct values does not say which.
        record["observed_values"] = sorted(record["observed_values"])[:5]

    return {
        "proven": sorted(
            (r for r in seen.values() if r["failures"]),
            key=lambda r: (r["scenario"], r["property"])),
        "unproven": sorted(
            (r for r in seen.values() if not r["failures"]),
            key=lambda r: (-r["passes"], r["scenario"], r["property"])),
        "runs_read": runs_read,
    }


def worklist(runs_dir: Path | None = None) -> dict:
    """What QA owes a forced-failure proof, and what it explicitly is not saying.

    The `caveat` is not decoration. A reader who took `unproven` for a defect list
    would re-derive the mistake this module exists to avoid."""
    history = observed_failures(runs_dir)
    single_valued = [r for r in history["unproven"] if len(r["observed_values"]) == 1]
    return {
        **history,
        # The sharper subset: a property that has never failed AND has only ever
        # observed one value. Still not a defect - `no agent was respawned` lives
        # here too and should.
        "never_varied": single_valued,
        "caveat": (
            "Unproven is not a defect. A property that is correctly always zero and one "
            "whose query can never match look identical from outside; only a forced-failure "
            "proof separates them (addendum 53 §5.3). This is a worklist, not a finding."),
    }


