"""Governance that happens *during* a run, on a schedule
(TASK_QUEUE TQ-96; addendum 46 §16, §18; docs/SPEC_RECONCILIATION.md §136, §139).

`simulation/seeding.py` establishes governance **before** the Controller starts:
Articles, a carried resolution, an instrument in force. That is the right shape
for a rule the organization runs under, and the wrong shape for a release.

**A release is an event, not a starting condition.** What TQ-96 has to show is
that the organization's behaviour changes while it is running, that the way back
works while it is running, and that neither costs a restart. Seeding a
rolled-back release before startup would assert on a database and prove nothing
about a live organization - §136's lesson, which is that a green run over a
condition that never occurred is not evidence about the condition.

So a scenario may declare a `governance_schedule`, and the harness fires it from
the same poll loop that fires faults.

## Why this is not a fault

`simulation/faults.py` is *"making things fail on purpose"*, and its entry rule is
that it implements only what it can really cause. A release is not a failure -
it is the organization doing something it is supposed to do, which may then turn
out to be wrong. Filing it under faults would put a normal operation in the
catalogue of things that go wrong, and the first person reading a fault manifest
would find a release in it and mis-read the run.

The two schedules are separate for that reason and share only the clock.

## Every event goes through the production API

The same rule seeding keeps, for the same reason. An event opens the run's
database and calls `backend.release`; nothing here writes SQL. A schedule able to
mark a release rolled back without reversing anything would produce a run whose
metrics describe a system that does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from backend import fi_db, release

# What a scheduled governance event may be. A closed vocabulary, refused at parse
# time: a scenario that silently does nothing at second 40 has wasted the run.
ACTIONS = ("apply_release", "judge_release", "roll_back_release")


class GovernanceEventError(ValueError):
    """An event a scenario cannot mean, refused before the run starts."""


@dataclass
class GovernanceEvent:
    """One governance action, and when it happens."""

    at_seconds: float
    action: str
    release_name: str
    actor: str = "coo"
    health: str | None = None
    evidence: str | None = None
    reason: str | None = None
    fired_at: str | None = None
    outcome: str | None = None

    def describe(self) -> str:
        return f"{self.action} {self.release_name!r} at +{self.at_seconds:g}s"


@dataclass
class GovernanceSchedule:
    events: list[GovernanceEvent] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.events)

    def due(self, elapsed: float) -> list[GovernanceEvent]:
        return [e for e in self.events if e.fired_at is None and elapsed >= e.at_seconds]

    def record(self) -> list[dict]:
        """What actually happened, for the run manifest.

        An event that never fired is reported as such rather than omitted, on
        `faults.record`'s reasoning: a run whose release never applied proved
        nothing, and the manifest is where that has to be visible."""
        return [
            {"at_seconds": event.at_seconds, "action": event.action,
             "release": event.release_name, "fired_at": event.fired_at,
             "outcome": event.outcome}
            for event in self.events
        ]


def parse(raw) -> GovernanceSchedule:
    """Read a scenario's `governance_schedule:` block, at load time."""
    if raw is None:
        return GovernanceSchedule()
    if not isinstance(raw, list):
        raise GovernanceEventError("governance_schedule must be a list")
    events = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise GovernanceEventError(f"governance event {index} must be a mapping")
        action = item.get("action")
        if action not in ACTIONS:
            raise GovernanceEventError(
                f"governance event {index}: unknown action {action!r}; known are {list(ACTIONS)}")
        if not item.get("release"):
            raise GovernanceEventError(
                f"governance event {index}: needs the 'release' it acts on, by name.")
        if "at_seconds" not in item:
            raise GovernanceEventError(f"governance event {index}: needs 'at_seconds'.")
        if action == "judge_release":
            if item.get("health") not in (release.HEALTH_HEALTHY, release.HEALTH_UNHEALTHY):
                raise GovernanceEventError(
                    f"governance event {index}: judge_release needs health "
                    f"{release.HEALTH_HEALTHY!r} or {release.HEALTH_UNHEALTHY!r}. "
                    f"{release.HEALTH_UNKNOWN!r} is what a release is before anybody looked.")
            if not (item.get("evidence") or "").strip():
                raise GovernanceEventError(
                    f"governance event {index}: a health verdict needs its evidence (§118).")
        if action == "roll_back_release" and not (item.get("reason") or "").strip():
            raise GovernanceEventError(
                f"governance event {index}: a rollback needs its reason; addendum 46 §18 step 6 "
                f"preserves the failure.")
        events.append(GovernanceEvent(
            at_seconds=float(item["at_seconds"]), action=action,
            release_name=item["release"], actor=item.get("actor", "coo"),
            health=item.get("health"), evidence=item.get("evidence"),
            reason=item.get("reason")))
    return GovernanceSchedule(sorted(events, key=lambda e: e.at_seconds))


def fire(event: GovernanceEvent, db_path: str | Path) -> str:
    """Carry out one event against the running organization's database.

    Never raises, for `faults.fire`'s reason: an event that could not be carried
    out is an ordinary thing to find during a run, and the manifest recording
    *what happened* is worth more than the harness ending on it. The outcome
    string is the record, and a scenario asserting on the resulting state will
    fail if the event did not land - which is the check that matters."""
    conn = fi_db.get_connection(db_path)
    try:
        row = conn.fetchone("SELECT id FROM releases WHERE name = ?", (event.release_name,))
        if row is None:
            return f"no release named {event.release_name!r}"
        release_id = row["id"]
        if event.action == "apply_release":
            adopted = release.apply(conn, release_id, applied_by=event.actor)
            return f"applied, adopting instruments {adopted}"
        if event.action == "judge_release":
            release.judge(conn, release_id, health=event.health, judged_by=event.actor,
                          evidence=event.evidence)
            return f"judged {event.health}"
        result = release.roll_back(conn, release_id, rolled_back_by=event.actor,
                                   reason=event.reason)
        return (f"rolled back: restored {result['restored']}, withdrew {result['withdrawn']}, "
                f"code version matched {result['code_version_matched']}")
    except Exception as failure:  # noqa: BLE001 - see the docstring
        return f"{type(failure).__name__}: {failure}"
    finally:
        conn.close()
