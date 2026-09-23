"""The periodic half of §9, and the two things nothing else was going to do.

Three jobs, one loop:

1. **Checkpoints on a cadence.** §9's checkpoint layer asks for "a complete
   restorable snapshot at major safe milestones", and before this the only
   checkpoint anything took was §20's pre-self-modification one. A system whose
   only known-good point is the one before a code change has no known-good
   point at all on the ordinary days.

2. **A checkpoint before a controlled shutdown**, which is §9's own second
   bullet and is called from the Gateway's lifespan rather than from here.

3. **Promoting detected capability gaps.** `app/capability_gaps.py` has been
   writing to `capability_gaps.jsonl` on the failure paths for some time and
   nothing read it into the §11 lifecycle, so no gap Krish's own usage produced
   ever reached him as a finding. `gaps.suspect_from_detector` is that bridge
   and this is what calls it.

## What "periodic" means here, said plainly

It does **not** mean buffered. Every `persistence.put` is written the moment it
happens, whatever tier its kind is declared at - buffering the periodic ones
would add a loss window in exchange for nothing, since each write is a single
small record rather than the whole-system serialisation §9 is warning against.

So `persistence.TIER` earns its keep a different way, and this is where: an
**immediate**-tier write since the last checkpoint forces the next sweep to
take one. A correction, a commitment, an approval or an identity change is
therefore never more than one sweep away from a validated recovery point,
while a task-state update - written just as promptly - does not cost a
checkpoint on its own. That is §9's distinction with something actually
hanging on it.

## Failing is allowed; failing silently is not

Every job is guarded individually, because a DBA that is briefly down must not
stop the loop for good - and the loop is the thing that would never be noticed
missing. `state()` reports what ran, what failed and when, and the last failure
is kept rather than overwritten by the next success.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from gateway import checkpoint as checkpoint_module
from gateway import dbaclient, gaps, identity, logscan, persistence

logger = logging.getLogger("gateway.upkeep")

ENABLED_ENV = "JARVIS_UPKEEP"
INTERVAL_ENV = "JARVIS_UPKEEP_MINUTES"

# How often the loop wakes. It acts rarely - both jobs decide for themselves
# whether they are due - so this is a polling interval and not a schedule.
DEFAULT_INTERVAL_MINUTES = 30

# A milestone checkpoint at least this often, even with nothing important
# written. Six hours rather than daily because the thing it bounds is how much
# of a day's work has no validated recovery point, and a day is too much.
CHECKPOINT_EVERY_HOURS = 6

# Gaps are promoted at most this often. Daily rather than hourly because the
# detector's threshold is about recurrence, and asking more often than the
# thing recurs produces no new information.
PROMOTE_GAPS_EVERY_HOURS = 24

# How often Jarvis reads his own log. More often than gap promotion, because a
# fault recurring right now is the thing most worth noticing early - and the
# scan is cheap: it reads a bounded window of one file.
SCAN_LOGS_EVERY_HOURS = 6

_LAST_CHECKPOINT = "upkeep:last_checkpoint"
_LAST_PROMOTION = "upkeep:last_gap_promotion"
_LAST_LOG_SCAN = "upkeep:last_log_scan"


def enabled() -> bool:
    """On unless switched off. The test suite switches it off.

    A background thread taking checkpoints underneath a test that counts them
    is nondeterminism nobody asked for - the same reason, and the same
    spelling, as the DBA's own backup scheduler."""
    return (os.environ.get(ENABLED_ENV, "1") or "1").strip() not in ("0", "false", "no")


def interval_seconds() -> int:
    try:
        minutes = int(os.environ.get(INTERVAL_ENV) or DEFAULT_INTERVAL_MINUTES)
    except ValueError:
        minutes = DEFAULT_INTERVAL_MINUTES
    return max(60, minutes * 60)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# --- deciding whether to act --------------------------------------------------


def checkpoint_due(client: dbaclient.DBAClient, *,
                   agent: str = identity.AGENT_ID,
                   now: datetime | None = None) -> tuple[bool, str]:
    """Whether a milestone checkpoint is owed, and why.

    Returns the reason as well as the answer, because "no checkpoint has been
    taken for nine hours" and "a commitment was recorded since the last one"
    are different facts and the second is the one §9 cares about."""
    now = now or _now()
    latest = checkpoint_module.latest_valid(client, agent=agent)
    if latest is None:
        return True, "no valid checkpoint exists"

    taken = _parse(latest.get("taken_at"))
    if taken is None:
        return True, f"{latest.get('name')} records no time it was taken"
    if now - taken >= timedelta(hours=CHECKPOINT_EVERY_HOURS):
        return True, (f"the last checkpoint was {int((now - taken).total_seconds() // 3600)}"
                      f"h ago, and the interval is {CHECKPOINT_EVERY_HOURS}h")

    # The part that gives `persistence.TIER` something to do.
    for row in persistence.current(client, agent=agent, limit=500):
        if persistence.tier(row.get("kind") or "") != persistence.IMMEDIATE:
            continue
        written = _parse(row.get("effective_from"))
        if written is not None and written > taken:
            return True, (f"{row.get('kind')}/{row.get('name')} was written "
                          f"after the last checkpoint, and {row.get('kind')} is "
                          f"on the immediate tier")
    return False, "nothing important has changed since the last checkpoint"


def log_scan_due(client: dbaclient.DBAClient, *,
                 agent: str = identity.AGENT_ID,
                 now: datetime | None = None) -> bool:
    now = now or _now()
    last = _parse(persistence.get(client, persistence.SELF_ASSESSMENT,
                                  _LAST_LOG_SCAN, agent=agent))
    return last is None or (now - last) >= timedelta(hours=SCAN_LOGS_EVERY_HOURS)


def promotion_due(client: dbaclient.DBAClient, *,
                  agent: str = identity.AGENT_ID,
                  now: datetime | None = None) -> bool:
    now = now or _now()
    last = _parse(persistence.get(client, persistence.SELF_ASSESSMENT,
                                  _LAST_PROMOTION, agent=agent))
    return last is None or (now - last) >= timedelta(hours=PROMOTE_GAPS_EVERY_HOURS)


# --- doing it -----------------------------------------------------------------


def run_once(client: dbaclient.DBAClient | None = None, *,
             agent: str = identity.AGENT_ID) -> dict:
    """One sweep. Returns what it did, including what it could not do.

    Never raises. The caller is a background loop, and a loop that ends on an
    exception is a maintenance job that stops running and tells nobody."""
    result: dict = {"at": _now().isoformat(timespec="seconds"),
                    "checkpoint": None, "promoted": None, "log_scan": None,
                    "problems": []}

    if not dbaclient.is_configured():
        result["problems"].append("no DBA token is configured; nothing to do")
        return result

    try:
        client = client or dbaclient.DBAClient(actor="upkeep")
    except dbaclient.Unavailable as exc:
        result["problems"].append(str(exc))
        return result

    try:
        due, why = checkpoint_due(client, agent=agent)
        if due:
            record = checkpoint_module.take(
                client, reason=checkpoint_module.MILESTONE, agent=agent)
            result["checkpoint"] = {"name": record["name"], "why": why}
            logger.info("upkeep took %s: %s", record["name"], why)
        else:
            result["checkpoint"] = {"name": None, "why": why}
    except (dbaclient.Unavailable, dbaclient.Refused,
            checkpoint_module.CheckpointInvalid) as exc:
        result["problems"].append(f"checkpoint: {exc}")

    # THE HABIT (Krish, 2026-09-23): read your own log, and turn what recurs
    # into something the lifecycle can investigate. Suspected only - §11's rule
    # that a perceived lack is not a confirmed lack applies to a log line more
    # than to anything else, because a log line is the cheapest evidence there
    # is to produce and the easiest to over-read.
    try:
        if log_scan_due(client, agent=agent):
            findings = logscan.scan()
            raised = logscan.raise_suspicions(client, findings, agent=agent)
            result["log_scan"] = {
                "faults": len(findings),
                "unaccepted": len(logscan.unaccepted(findings)),
                "raised": [row.get("name") for row in raised],
                "patterns": [row.get("kind") for row in logscan.patterns()],
            }
            persistence.put(client, persistence.SELF_ASSESSMENT, _LAST_LOG_SCAN,
                            _now().isoformat(timespec="seconds"), agent=agent,
                            reason="log scan sweep")
            if raised:
                logger.info("log scan raised %d suspected gap(s)", len(raised))
    except (dbaclient.Unavailable, dbaclient.Refused, OSError, ValueError) as exc:
        result["problems"].append(f"log scan: {exc}")

    try:
        if promotion_due(client, agent=agent):
            raised = gaps.suspect_from_detector(client, agent=agent)
            result["promoted"] = [row.get("name") for row in raised]
            persistence.put(client, persistence.SELF_ASSESSMENT, _LAST_PROMOTION,
                            _now().isoformat(timespec="seconds"), agent=agent,
                            reason="gap promotion sweep")
            if raised:
                logger.info("upkeep promoted %d detected gap(s)", len(raised))
    except (dbaclient.Unavailable, dbaclient.Refused, OSError, ValueError) as exc:
        result["problems"].append(f"gap promotion: {exc}")

    return result


def checkpoint_before_shutdown(client: dbaclient.DBAClient | None = None, *,
                               agent: str = identity.AGENT_ID) -> dict | None:
    """§9's "before controlled shutdown". Called from the Gateway's lifespan.

    Returns the checkpoint, or `None` if one could not be taken - and `None` is
    not an error here. A shutdown is not a moment to raise in: the process is
    going away either way, and the next boot's honest account of what it could
    restore is a better place to notice than a traceback nobody reads."""
    if not dbaclient.is_configured():
        return None
    try:
        client = client or dbaclient.DBAClient(actor="shutdown")
        return checkpoint_module.take(
            client, reason=checkpoint_module.BEFORE_SHUTDOWN, agent=agent)
    except (dbaclient.Unavailable, dbaclient.Refused,
            checkpoint_module.CheckpointInvalid) as exc:
        logger.warning("no checkpoint was taken before shutdown: %s", exc)
        return None


# The steps `desktop/escape.py` says are owed before the shell closes. Named
# with the same strings, so the two cannot drift into meaning different things.
PAUSE_TASKS = "pause_running_tasks"
CHECKPOINT = "checkpoint_before_shutdown"
RECORD_EVENT = "record_ledger_event"


def closing_down(client: dbaclient.DBAClient | None = None, *,
                 reason: str = "the shell was closed",
                 agent: str = identity.AGENT_ID) -> dict:
    """Everything owed before Jarvis's window goes away, in order.

    The shell is a separate process and `desktop/` is deliberately ignorant of
    the organization - it knows how to open a window and nothing else. So the
    shell asks for this over HTTP and this is where it actually happens, which
    also means it is testable rather than living inside a pywebview callback
    nobody can run without Windows.

    **Pause before checkpoint, on purpose.** A checkpoint taken while a task is
    mid-step describes a step half-applied, and restoring to it would resume
    from a state that never existed. Pausing first makes the checkpoint describe
    something true - a task stopped at a named next action.

    Returns one entry per step rather than a single boolean: "the window closed
    but the checkpoint failed" is a thing the owner needs told, and a bare
    success or failure cannot say it."""
    result: dict = {"reason": reason, "performed": [], "failed": []}

    if not dbaclient.is_configured():
        result["failed"].append(f"{CHECKPOINT}: no DBA token is configured")
        return result
    try:
        client = client or dbaclient.DBAClient(actor="shell")
    except dbaclient.Unavailable as exc:
        result["failed"].append(f"{CHECKPOINT}: {exc}")
        return result

    # 1. Pause anything running, recording where it got to.
    try:
        paused = []
        for row in persistence.current(client, kind=persistence.TASK, agent=agent,
                                       limit=200):
            value = persistence.decode(row)
            if isinstance(value, dict) and value.get("state") == "running":
                persistence.put(client, persistence.TASK, row["name"],
                                {**value, "state": "paused",
                                 "paused_because": reason},
                                agent=agent, reason="paused by the shell closing")
                paused.append(row["name"])
        result["paused"] = paused
        result["performed"].append(PAUSE_TASKS)
    except (dbaclient.Unavailable, dbaclient.Refused) as exc:
        result["failed"].append(f"{PAUSE_TASKS}: {exc}")

    # 2. The §9 before-shutdown checkpoint.
    try:
        record = checkpoint_module.take(
            client, reason=checkpoint_module.BEFORE_SHUTDOWN, agent=agent)
        result["checkpoint"] = record["name"]
        result["performed"].append(CHECKPOINT)
    except (dbaclient.Unavailable, dbaclient.Refused,
            checkpoint_module.CheckpointInvalid) as exc:
        result["failed"].append(f"{CHECKPOINT}: {exc}")

    # 3. The ledger event, so a restart can explain the gap.
    try:
        from gateway import ledger

        ledger.append(client, event_type=ledger.STATE_TRANSITION,
                      summary=f"shell closed: {reason}",
                      observation=f"paused {len(result.get('paused') or [])} task(s); "
                                  f"checkpoint {result.get('checkpoint')}",
                      actor="shell", verification_state=ledger.VERIFIED,
                      agent=agent)
        result["performed"].append(RECORD_EVENT)
    except Exception as exc:  # noqa: BLE001 - a closing window must not be held
        # open by its own bookkeeping; what changes is that it is not clean.
        result["failed"].append(f"{RECORD_EVENT}: {exc}")

    result["clean"] = not result["failed"]
    return result


def describe() -> dict:
    return {
        "enabled": enabled(),
        "interval_seconds": interval_seconds(),
        "checkpoint_every_hours": CHECKPOINT_EVERY_HOURS,
        "promote_gaps_every_hours": PROMOTE_GAPS_EVERY_HOURS,
        "scan_logs_every_hours": SCAN_LOGS_EVERY_HOURS,
        "accepted_log_noise": len(logscan.baseline()),
        "closing_steps": [PAUSE_TASKS, CHECKPOINT, RECORD_EVENT],
        "forces_a_checkpoint": sorted(
            kind for kind in persistence.KINDS
            if persistence.tier(kind) == persistence.IMMEDIATE),
    }
