"""Orchestrate a demonstration of the real system.

The specification's rule, which shapes every decision here:

> *"The Demo Engine itself must not become a second implementation of the system.
> Use real interfaces, real databases, real agent processes, real engines, real
> task systems, real messages, real recovery, real persistence."*

So this module starts nothing itself. It calls `simulation.harness.execute`, which
is what `verify` already uses, and reads the runs back through
`simulation.metrics`, which is what every scenario property already uses. An act
that could not be performed by machinery that already existed is an act this
engine does not perform.

## The acts, and why these

A demonstration is a sequence of acts. Each act names a capability from the
registry, runs one real scenario, and reads the result out of that run's own
database. The default sequence is chosen to tell one story rather than to
maximise coverage:

    the organization starts, staffs itself, and works
    a rule carried by vote changes what it does
    it loses its executive and carries on
    it is stopped, restarted from its own database, and continues

The last act is the specification's *major success criterion*, and it is the only
one that needs two runs: the second inherits the first's database, so identity and
knowledge either survive or visibly do not.

## Honesty is enforced, not intended

`OUTCOME_NOT_OBSERVED` exists because a scenario can pass every property while the
thing the act set out to show did not happen - a run with no cross-checks
demonstrates nothing about collaboration, however green it is. So each act
declares a **witness**: a question asked of the run's own metrics whose answer is
the demonstration. No witness, no claim.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from backend import demonstration as record
from backend import fi_db, migrations, version
from backend.db import Database
from demonstration import capabilities as registry
from simulation import harness, metrics
from simulation import scenario as scenario_module


@dataclass(frozen=True)
class Act:
    """One thing the demonstration sets out to show.

    `witness` is asked of the finished run's metrics and returns (observed, note).
    Observed false means the act ran and the thing did not happen, which is
    reported as such rather than as a pass - the specification is explicit that a
    demo must report failure honestly and never alter output to look better."""

    capability: str
    title: str
    scenario: str | None
    witness: Callable[[dict], tuple[bool, str]] | None = None
    # For an act whose claim is about *continuity*, one run's metrics cannot
    # answer it: the question is whether what was in the first database is still
    # in the second. This witness is handed both databases instead.
    continuity_witness: Callable[[str, str], tuple[bool, str]] | None = None
    inherit_from_previous: bool = False


def _plural(n: int, thing: str) -> str:
    return f"{n} {thing}" + ("" if n == 1 else "s")


# --- the witnesses ------------------------------------------------------------------
#
# Each reads the run's own metrics. Nothing here recomputes anything: these are
# the same numbers the scenario's own properties are asserted against.


def _witness_startup(m: dict) -> tuple[bool, str]:
    roles = m["population"]["registered_by_role"]
    staffed = {r: n for r, n in roles.items() if n}
    return bool(staffed), (
        f"{_plural(m['population']['registered'], 'agent')} registered across "
        f"{_plural(len(staffed), 'role')}: {', '.join(sorted(staffed))}")


def _witness_discovery(m: dict) -> tuple[bool, str]:
    filed = m["pipeline"]["reports_filed"]
    return filed > 0, f"{_plural(filed, 'report')} filed by the discovery agents"


def _witness_collaboration(m: dict) -> tuple[bool, str]:
    c = m["cross_check"]
    asked = c["total"]
    # `outcomes` is a vocabulary, not a score: evidence, no_evidence, unanswered.
    # Reported as it stands, because an honestly empty answer is cooperation and
    # a ranking function over these is what §149 removed.
    breakdown = ", ".join(f"{n} {kind}" for kind, n in sorted(c["outcomes"].items())) or "none"
    return asked > 0, (
        f"{_plural(asked, 'cross-check')} asked ({breakdown}); the asker's own finding "
        f"was recorded before each question. Unanswered rate: {c['unanswered_rate']}")


def _witness_judgment(m: dict) -> tuple[bool, str]:
    graded = m["pipeline"]["grades"]
    return graded > 0, f"{_plural(graded, 'grade')} recorded, each carrying a rationale"


def _witness_governance(m: dict) -> tuple[bool, str]:
    g = m["governance"]
    in_force = g["instruments_in_force"]
    governed = g["work_governed"]
    ungoverned = g["work_ungoverned"]
    return in_force > 0 and governed > 0, (
        f"{_plural(in_force, 'instrument')} in force; {governed} of "
        f"{governed + ungoverned} reports carried the authority they were filed under")


def _witness_executive_recovery(m: dict) -> tuple[bool, str]:
    i = m["incidents"]
    total, recovered = i["total"], i["recovered"]
    subjects = ", ".join(i["subjects"]) or "none"
    # Recovery, not merely detection. An incident raised and never recovered is
    # the organization noticing and not surviving, which is a different result.
    return total > 0 and recovered > 0, (
        f"{_plural(total, 'incident')} raised, {recovered} recovered (subject: {subjects}); "
        f"{_plural(m['population']['registered'], 'agent')} registered by the end")


def _witness_continuity(before_db: str, after_db: str) -> tuple[bool, str]:
    """The specification's major success criterion, asked of two real databases.

    The second run is started from the first one's database, so this is not a
    simulated restart: the organization was stopped, its processes ended, and a
    new set was started against the state the old one left. Continuity either
    survived that or it did not.

    Three things are checked, and the first is the one that matters. An identity
    that changed would mean a restart created a new person - directive §13's
    *"a restart should not create a new person merely because the Python process
    is new"* - and it is checked on `coo_id`, never the display name, because
    the durable thing being the name is exactly the defect TQ-97 corrected."""
    before = fi_db.get_connection(before_db)
    after = fi_db.get_connection(after_db)
    try:
        def coo(conn):
            # `coo_id`, not a display name and not a row id. The COO has had a
            # persisted identity since §88, and TQ-97 established that the
            # durable thing is never the name - renaming a name-keyed agent
            # either breaks every join or hands its history to whoever holds the
            # name next.
            return conn.fetchone(
                "SELECT coo_id, name, created_at, identity_version FROM coo_identity LIMIT 1")

        before_coo, after_coo = coo(before), coo(after)
        before_knowledge = before.fetchone(
            "SELECT COUNT(*) AS n FROM knowledge_records")["n"]
        after_knowledge = after.fetchone(
            "SELECT COUNT(*) AS n FROM knowledge_records")["n"]
        before_ids = {r["agent_id"] for r in before.fetchall(
            "SELECT agent_id FROM agent_identities")}
        after_ids = {r["agent_id"] for r in after.fetchall(
            "SELECT agent_id FROM agent_identities")}
    finally:
        before.close()
        after.close()

    if before_coo is None or after_coo is None:
        return False, "no COO identity was persisted, so there was nothing to continue"

    same_identity = before_coo["coo_id"] == after_coo["coo_id"]
    same_birth = before_coo["created_at"] == after_coo["created_at"]
    kept_ids = before_ids <= after_ids
    kept_knowledge = after_knowledge >= before_knowledge

    note = (
        f"COO {after_coo['name']!r} coo_id {'unchanged' if same_identity else 'CHANGED'}, "
        f"created_at {'unchanged' if same_birth else 'CHANGED'}; "
        f"{len(before_ids)} agent identities before, {len(after_ids)} after "
        f"({'none lost' if kept_ids else 'IDENTITIES LOST'}); "
        f"knowledge records {before_knowledge} -> {after_knowledge}")
    return (same_identity and same_birth and kept_ids and kept_knowledge), note


def run_metrics(result: harness.RunResult) -> dict:
    """The finished run's own numbers, read from its own database."""
    return metrics.collect(result.db_path)


# --- the default demonstration ------------------------------------------------------

FULL_DEMO = (
    Act("startup", "The organization starts and staffs itself",
        "baseline_steady_state", _witness_startup),
    Act("discovery", "Explorer and Speculator go looking",
        None, _witness_discovery),          # read from the same run as startup
    Act("collaboration", "One agent asks another and waits",
        None, _witness_collaboration),
    Act("judgment", "Analysis grades what the others produced",
        None, _witness_judgment),
    Act("governance", "A rule carried by vote changes what agents do",
        "governed_organization", _witness_governance),
    Act("executive_recovery", "The organization loses its executive and carries on",
        "executive_failure", _witness_executive_recovery),
    # The specification's major success criterion. Runs the baseline a second
    # time *from the first run's database*, so the organization is genuinely
    # restarted against its own prior state rather than started fresh.
    Act("persistence", "It is stopped, restarted from its own state, and continues",
        "baseline_steady_state", continuity_witness=_witness_continuity,
        inherit_from_previous=True),
)


def demo_id_for(started: datetime) -> str:
    return "demo-" + started.strftime("%Y%m%dT%H%M%S")


class Demonstration:
    """One demonstration, start to summary."""

    def __init__(self, acts=FULL_DEMO, *, mode: str = "full", db_path: str | None = None):
        self.acts = acts
        self.mode = mode
        self.db_path = db_path or str(fi_db.DB_PATH)
        self.started = datetime.now(timezone.utc)
        self.demo_id = demo_id_for(self.started)
        self.results: list[dict] = []
        self._runs: dict[str, harness.RunResult] = {}

    # -- the report the specification requires *before* a demo -----------------

    @staticmethod
    def capability_report() -> dict:
        """What can and cannot be shown, before anything runs.

        Directive item 19: *"Produce a current-capability report before running
        the demo."* Read rather than asserted - roles, stores and scenarios come
        from the system's own registries."""
        scenarios = registry.discovered_scenarios()
        return {
            "code_version": version.code_version(),
            "roles_implemented": [r["id"] for r in registry.discovered_roles()],
            "stores_governed": registry.discovered_stores(),
            "scenarios_available": sorted(scenarios),
            "demonstrable": [
                {"id": c.id, "name": c.name, "scenario": c.scenario,
                 "evidence": c.evidence, "client_safe": c.client_safe}
                for c in registry.DEMONSTRABLE
            ],
            "absent": [
                {"id": a.id, "name": a.name, "why": a.why} for a in registry.ABSENT
            ],
        }

    # -- running ---------------------------------------------------------------

    def run(self, *, log=print) -> dict:
        conn = fi_db.get_connection(self.db_path)
        try:
            fi_db.init_schema(conn)
            record.open_demo(conn, demo_id=self.demo_id, mode=self.mode,
                             code_version=version.code_version())
            log(f"\n  demonstration {self.demo_id}  ({self.mode})")
            log(f"  code {version.code_version()}   data: synthetic, every price (§113)\n")

            scenarios = scenario_module.load_all()
            previous: harness.RunResult | None = None
            last_metrics: dict | None = None

            for sequence, act in enumerate(self.acts, start=1):
                result = previous
                inherited_from: harness.RunResult | None = None

                if act.scenario:
                    scenario = scenarios.get(act.scenario)
                    if scenario is None:
                        self._record(conn, sequence, act, record.OUTCOME_UNAVAILABLE,
                                     f"scenario {act.scenario!r} is not in the library")
                        log(f"  {sequence}. {act.title}")
                        log(f"     UNAVAILABLE - no scenario named {act.scenario!r}")
                        continue
                    log(f"  {sequence}. {act.title}")
                    if act.inherit_from_previous and previous is not None:
                        inherited_from = previous
                        log(f"     restarting from {previous.run_id}'s own database")
                    log(f"     running {scenario.id} for {scenario.duration_seconds:.0f}s ...")
                    try:
                        result = harness.execute(
                            scenario,
                            inherit_from=inherited_from.db_path if inherited_from else None)
                    except Exception as exc:  # noqa: BLE001
                        # An act that could not run is recorded and the
                        # demonstration continues. A demo that dies on its sixth
                        # act has shown five things and reported none of them,
                        # and the specification is explicit that failure is valid
                        # output - a run that crashes instead of reporting is the
                        # one shape of dishonesty it cannot tolerate, because it
                        # withholds the finding rather than dressing it up.
                        log(f"     FAILED - {exc}")
                        self._record(conn, sequence, act, record.OUTCOME_FAILED, str(exc))
                        continue
                    last_metrics = run_metrics(result)
                    self._runs[act.capability] = result
                    previous = result
                elif last_metrics is None:
                    self._record(conn, sequence, act, record.OUTCOME_UNAVAILABLE,
                                 "no run to read; this act reads a previous act's run")
                    log(f"  {sequence}. {act.title}")
                    log("     UNAVAILABLE - nothing has run yet")
                    continue
                else:
                    log(f"  {sequence}. {act.title}")

                try:
                    if act.continuity_witness is not None:
                        if inherited_from is None:
                            observed, note = False, (
                                "nothing to continue from: this act needs a previous run "
                                "to restart against")
                        else:
                            observed, note = act.continuity_witness(
                                str(inherited_from.db_path), str(result.db_path))
                    else:
                        observed, note = act.witness(last_metrics)
                except Exception as exc:  # noqa: BLE001
                    # A witness that cannot be evaluated has not disproved
                    # anything, and must not be read as either outcome. The run
                    # happened; what failed is the question asked about it.
                    log(f"     FAILED - the witness could not be evaluated: {exc}")
                    self._record(conn, sequence, act, record.OUTCOME_FAILED,
                                 f"witness raised: {exc}",
                                 run=result if act.scenario else None)
                    continue

                outcome = record.OUTCOME_SHOWN if observed else record.OUTCOME_NOT_OBSERVED
                log(f"     {'SHOWN' if observed else 'NOT OBSERVED'} - {note}")
                self._record(conn, sequence, act, outcome, note,
                             run=result if act.scenario else None)

            status = (record.STATUS_COMPLETE
                      if all(r["outcome"] == record.OUTCOME_SHOWN for r in self.results)
                      else record.STATUS_COMPLETE)
            record.close_demo(conn, self.demo_id, status=status)
            return self.summary(conn)
        except Exception as exc:  # noqa: BLE001 - a broken demo is reported, not swallowed
            record.close_demo(conn, self.demo_id, status=record.STATUS_FAILED, detail=str(exc))
            raise
        finally:
            conn.close()

    def _record(self, conn, sequence: int, act: Act, outcome: str, detail: str,
                run: harness.RunResult | None = None) -> None:
        record.record_act(
            conn, demo_id=self.demo_id, sequence=sequence, capability=act.capability,
            title=act.title, outcome=outcome, scenario_id=act.scenario,
            run_id=run.run_id if run else None,
            run_directory=str(run.directory) if run else None, detail=detail)
        self.results.append({
            "sequence": sequence, "capability": act.capability, "title": act.title,
            "outcome": outcome, "detail": detail,
            "scenario": act.scenario,
            "run_id": run.run_id if run else None,
        })

    def summary(self, conn: Database) -> dict:
        shown = [r for r in self.results if r["outcome"] == record.OUTCOME_SHOWN]
        return {
            "demo_id": self.demo_id,
            "mode": self.mode,
            "code_version": version.code_version(),
            "data_mode": record.DATA_MODE_SYNTHETIC,
            "started_at": self.started.isoformat(),
            "acts": self.results,
            "capabilities_shown": [r["capability"] for r in shown],
            "capabilities_not_observed": [
                r["capability"] for r in self.results
                if r["outcome"] == record.OUTCOME_NOT_OBSERVED],
            "not_implemented": [
                {"id": a.id, "name": a.name, "why": a.why} for a in registry.ABSENT],
            "runs": {c: str(r.directory) for c, r in self._runs.items()},
        }


def write_summary(summary: dict, path: str | Path) -> Path:
    path = Path(path)
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return path
