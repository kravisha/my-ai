"""Acting on a machine, once the evidence says acting is warranted.

Krish, 2026-09-16 18:12, by phone from abroad: *"Jarvis must eventually be able
to diagnose services and agents running on other authorized machines, not only
its own machine ... For this phase, build the diagnostic capability first.
Prefer read-only inspection ... Report findings before taking corrective
action."* His attached plan made diagnosis Phase 1 and named recovery as Phase 3,
a separate thing to be built later. This is that thing.

## Why it was worth building, stated as the failure it prevents

On 2026-09-15 the engineer session on the development PC stopped answering while
its owner was on another continent. Every piece of machinery around it was
healthy - the Gateway self-healed every twenty seconds, the tunnel republished
itself, the channel queued his messages safely and refused to mark them read.
The one thing nothing could do was start the process again. `gateway/remote.py`
could see it was gone and say so in four different ways, and then the report
ended with a recommended action that only a person at that keyboard could take.
A system that can perfectly describe a problem it is forbidden to fix has moved
the outage from the machine into the paperwork.

## The line this module is on the far side of

`gateway/tools.py` wrote the rule before there was anything to apply it to:
*"When recovery is built it will NOT reuse this - acting on another machine is
a different authority from looking at one."* So `system:recover` is its own
capability, held by the operator alone. `internal` may watch a service die and
may not bounce it, and that is deliberate rather than an oversight: the role
that sees is not thereby the role that acts.

## Five gates, and every one of them can only refuse

Recovery is the first thing in this Gateway that changes another machine, so the
question is not "does it work" but "what stops it". In order:

  1. **It cannot be aimed.** Like `remote_diagnose`, the arguments are a
     configured *target name* and a configured *action name*. There is no host
     parameter and no command parameter, so no sentence in a conversation can
     turn this into a remote shell. Every command run here was written by a
     person into the machine list, exactly as `ssh.checks` are.
  2. **It will not act without a confirmation it cannot infer.** The same guard
     `publish_document` uses for a public commit, for the same reason: a model
     reasoning its way to "he would obviously want this restarted" is precisely
     the reasoning that should not be sufficient.
  3. **It diagnoses first, every time, and obeys the verdict.** This is Krish's
     own sentence - *report findings before taking corrective action* - turned
     into control flow rather than left as advice. An action declares the
     service states it answers, and a service that is `answering` is not
     restarted however insistently it is asked for.
  4. **It refuses on low confidence, and that is mostly about agents.**
     `remote.assess` will never call a quiet agent hung, because from outside an
     idle session and a dead one are identical and *"the wrong word there gets a
     working session killed"*. Recovery inherits that with teeth: where the
     evidence is a file that has not moved, confidence is `low`, and low
     confidence refuses. Killing a working session to fix an imagined outage is
     the one outcome strictly worse than the outage.
  5. **It is rate limited, and the ceiling is per action.** A restart loop is
     the dangerous shape here - the same shape `gateway/devchannel.py` bounds
     with `MAX_PER_WINDOW`, and worse, because each iteration kills a process. A
     cooldown stops the loop and a daily ceiling stops a slow one.

## No journal, no action

The cooldown and the ceiling are both computed from the journal, so a journal
that cannot be written is not a missing nicety - it is the loop protection
gone. This module therefore refuses to act when it cannot record, and says so
with the path it tried. That is the unusual direction to fail in: it means a
full disk stops a recovery. It is still right. An unbounded restart loop nobody
can reconstruct afterwards is a worse Tuesday than a service that stayed down
with a clear reason in the reply.

## What it honestly cannot do

It needs SSH to the far end, and on this deployment today no target has an `ssh`
block, because the outbound key and the account to use it are Krish's to
authorise and not this system's to create. Until one exists, every call here
refuses with that as the reason. That is stated plainly and early rather than
discovered at the moment of an outage: a capability that reports `configured:
false` on the night it is needed has not helped anybody.

It also cannot reach a machine that is off. Nothing can, from here. When the
diagnosis says `unreachable`, recovery says so and stops, rather than running an
SSH command into a void and reporting the timeout as though it were a finding.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from gateway import remote

# Where attempts are recorded. Beside the machine list by default, because the
# two describe the same fleet and a deployment that moves one moves the other.
JOURNAL_FILE_ENV = "REMOTE_RECOVERY_JOURNAL"
DEFAULT_JOURNAL_NAME = "remote-recovery-journal.jsonl"

# A restart is allowed to take longer than a read-only check, and not much
# longer. The caller is a person on a phone; `remote.SSH_TIMEOUT` would be too
# tight for a service that stops slowly, and five minutes would be a hang.
RECOVERY_TIMEOUT = 60

# Defaults for an action that does not state its own. Deliberately conservative:
# the cost of a cooldown that is too long is a person waiting, and the cost of
# one that is too short is a loop that kills a process every minute all night.
DEFAULT_COOLDOWN_MINUTES = 15
DEFAULT_MAX_PER_DAY = 4

# Confidences this module will act on. `low` is excluded by construction - see
# gate 4 in the module docstring; it is the agent case, and it is the one that
# would cost a working session.
ACTING_CONFIDENCES = ("high", "medium")

OUTPUT_SNIPPET = 2000


class RecoveryRefused(Exception):
    """A recovery this module will not perform, carried to the model as a string.

    The same shape as `devchannel.ChannelRefused` and for the same reason: the
    model is expected to read the refusal and tell the operator what it says,
    which it can only do if the refusal is a sentence rather than a traceback
    that ends the turn."""


# ------------------------------------------------------------------- journal


def journal_path() -> Path:
    """Resolved per call, never at import - so the suite can point it at tmp."""
    configured = os.environ.get(JOURNAL_FILE_ENV, "").strip()
    if configured:
        return Path(configured)
    return remote.targets_file().parent / DEFAULT_JOURNAL_NAME


def read_journal() -> list[dict]:
    """Every recorded attempt, oldest first.

    A malformed line is skipped rather than fatal. The journal is append-only
    and machine-written, but it lives on a disk a person can edit, and one bad
    line should not make a rate limit unenforceable - which, since the limit
    fails closed, would otherwise mean no recovery at all until someone tidied
    a file by hand on a machine nobody can reach."""
    path = journal_path()
    if not path.exists():
        return []
    entries = []
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def record(entry: dict) -> dict:
    """Append one attempt, or say why it could not be recorded.

    Returns a result rather than raising, because the caller's next move differs
    by which half failed: a write that fails *before* the command runs refuses
    the recovery, and there is no case where one fails after, since this is
    called first on purpose."""
    path = journal_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        return {"recorded": False, "path": str(path), "reason": str(exc)}
    return {"recorded": True, "path": str(path)}


def attempts_for(target: str, action: str, *, entries: list[dict] | None = None) -> list[dict]:
    """This action's attempts on this machine, oldest first."""
    records = entries if entries is not None else read_journal()
    return [
        entry for entry in records
        if entry.get("target") == target and entry.get("action") == action
    ]


def _dated(entry: dict) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(entry.get("at", "")))
    except ValueError:
        return None
    return when if when.tzinfo else when.astimezone()


def _setting(action: dict, key: str, default: int) -> int:
    """One numeric setting off an action, honouring an explicit zero.

    `int(action.get(key) or default)` reads 0 as absent and substitutes the
    default, so an operator who wrote `"cooldown_minutes": 0` to mean *no
    cooldown* would silently get fifteen minutes. A configuration value quietly
    replaced by a different one is the failure this project keeps naming: it
    looks exactly like working."""
    value = action.get(key)
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def rate_check(target: str, action: dict, *, now: datetime | None = None,
               entries: list[dict] | None = None) -> str | None:
    """The reason this attempt is refused by the ceiling, or None.

    Two limits and they answer different questions. The cooldown answers "has
    the last one had time to work" - restarting a service twice in ninety
    seconds is not persistence, it is a loop with a longer stride. The daily
    ceiling answers "is this still recovery" - the fourth restart in a day is
    evidence of a problem a restart does not fix, and continuing to restart is
    how a symptom gets hidden until it is an incident.

    An attempt whose timestamp cannot be parsed is counted toward the ceiling
    but cannot satisfy the cooldown, which is the cautious reading of both: a
    line nobody can date should not unlock an immediate retry, and should not be
    invisible to the count either."""
    now = now or datetime.now().astimezone()
    name = str(action.get("name"))
    cooldown = _setting(action, "cooldown_minutes", DEFAULT_COOLDOWN_MINUTES)
    ceiling = _setting(action, "max_per_day", DEFAULT_MAX_PER_DAY)
    past = attempts_for(target, name, entries=entries)

    day_ago = now - timedelta(days=1)
    recent_day = [e for e in past if (_dated(e) or now) >= day_ago]
    if len(recent_day) >= ceiling:
        return (
            f"'{name}' has already been run {len(recent_day)} times on {target} in "
            f"the last 24 hours, which is its limit of {ceiling}. A service that "
            "needs restarting this often has a problem a restart does not fix, and "
            "continuing would hide it. Report that, and say the ceiling is what "
            "stopped this rather than that it failed."
        )

    if past:
        last = _dated(past[-1])
        if last is not None:
            elapsed = now - last
            if elapsed < timedelta(minutes=cooldown):
                wait = cooldown - int(elapsed.total_seconds() // 60)
                return (
                    f"'{name}' was last run on {target} {int(elapsed.total_seconds() // 60)} "
                    f"minutes ago and its cooldown is {cooldown} minutes. Wait about "
                    f"{wait} more minutes and diagnose again first - a restart that has "
                    "not been given time to take effect looks exactly like one that did "
                    "not work."
                )
    return None


# -------------------------------------------------------------------- lookup


def actions_for(target: dict) -> list[dict]:
    """The recovery actions a person wrote for this machine.

    An entry without both a name and a command is dropped rather than repaired.
    Guessing at a half-written action is how a configuration typo becomes a
    command nobody intended to authorise."""
    config = target.get("recovery")
    if not isinstance(config, dict):
        return []
    listed = config.get("actions")
    if not isinstance(listed, list):
        return []
    actions = []
    for entry in listed:
        if not isinstance(entry, dict):
            continue
        if not str(entry.get("name", "")).strip():
            continue
        if not str(entry.get("command", "")).strip():
            continue
        actions.append(entry)
    return actions


def describe_actions(target: dict) -> list[dict]:
    """What may be done to this machine, without doing any of it.

    The half of this capability that is safe to call freely, and the half an
    operator actually wants first: "what can you do about it" is the question
    that follows every diagnosis."""
    described = []
    for action in actions_for(target):
        when = action.get("when") if isinstance(action.get("when"), dict) else {}
        described.append({
            "name": action.get("name"),
            "what_it_does": action.get("description"),
            "applies_to_service": when.get("service"),
            "runs_when_state_is": list(when.get("states") or []),
            "cooldown_minutes": _setting(action, "cooldown_minutes", DEFAULT_COOLDOWN_MINUTES),
            "max_per_day": _setting(action, "max_per_day", DEFAULT_MAX_PER_DAY),
        })
    return described


# ---------------------------------------------------------------- the gates


def precondition(action: dict, diagnosis: dict) -> dict:
    """Whether the evidence supports running this action. Fail closed.

    An action with no `when` block can never run. That is the important default
    and it is the opposite of the convenient one: an unconditional recovery
    action is a command that fires whenever asked, which is the property the
    whole module exists to withhold. A person who genuinely wants one writes the
    states out.

    The service named in `when` must also exist in the diagnosis. A `when` that
    points at a service nobody probed would otherwise be satisfied by silence,
    and silence is what this project has repeatedly mistaken for health."""
    when = action.get("when")
    if not isinstance(when, dict):
        return {
            "met": False,
            "why": (
                f"'{action.get('name')}' has no 'when' block, so there is no state "
                "in which it is defined to run. An action that can fire at any time "
                "is a remote command rather than a recovery, and this refuses to "
                "treat it as one. Add a 'when' naming the service and the states it "
                "answers."
            ),
        }

    wanted_states = [str(s) for s in (when.get("states") or [])]
    if not wanted_states:
        return {
            "met": False,
            "why": (
                f"'{action.get('name')}' names no states in its 'when' block, so "
                "there is nothing to compare the diagnosis against."
            ),
        }

    service_name = when.get("service")
    report = diagnosis.get("report") or {}
    services = report.get("services") or []

    if service_name:
        matching = [s for s in services if s.get("service") == service_name]
        if not matching:
            configured = [s.get("service") for s in services]
            return {
                "met": False,
                "why": (
                    f"'{action.get('name')}' applies to the service {service_name!r}, "
                    f"which was not probed on this machine. Probed: "
                    f"{', '.join(str(c) for c in configured) or 'nothing'}. An action "
                    "whose subject nobody looked at cannot be justified by the "
                    "diagnosis."
                ),
            }
        state = matching[0].get("state")
        if state not in wanted_states:
            return {
                "met": False,
                "why": (
                    f"{service_name} is '{state}', and '{action.get('name')}' only runs "
                    f"when it is one of: {', '.join(wanted_states)}. "
                    f"{matching[0].get('why', '')} Nothing was done, and nothing needs "
                    "doing on this evidence."
                ),
                "observed_state": state,
            }
        return {"met": True, "why": f"{service_name} is '{state}'", "observed_state": state}

    # No service named: the action is about the machine, so connectivity is the
    # state it is judged on.
    connectivity = report.get("connectivity")
    if connectivity not in wanted_states:
        return {
            "met": False,
            "why": (
                f"this machine is '{connectivity}', and '{action.get('name')}' only "
                f"runs when it is one of: {', '.join(wanted_states)}. "
                f"{report.get('connectivity_why', '')}"
            ),
            "observed_state": connectivity,
        }
    return {"met": True, "why": f"this machine is '{connectivity}'",
            "observed_state": connectivity}


def confidence_gate(diagnosis: dict) -> str | None:
    """The reason this diagnosis is too weak to act on, or None.

    `remote.assess` computes `low` exactly where the evidence cannot tell a
    stopped thing from an idle one - most often an agent judged only by a file
    that has not moved. Its own recommended action in that case is to get
    evidence from inside the machine first, and this is that recommendation
    enforced rather than printed."""
    report = diagnosis.get("report") or {}
    confidence = report.get("confidence")
    if confidence in ACTING_CONFIDENCES:
        return None
    return (
        f"The diagnosis is {confidence!r} confidence, and recovery acts only on "
        f"{' or '.join(ACTING_CONFIDENCES)}. {report.get('probable_cause', '')} "
        f"The diagnosis' own recommendation is: {report.get('recommended_next_action', '')} "
        "Quiet is not the same as stopped, and a restart decided on this evidence "
        "could kill a session that was working."
    )


# ------------------------------------------------------------------- the act


def _run(command: list[str], *, runner=None) -> dict:
    if runner is not None:
        return runner(command)
    try:
        proc = subprocess.run(
            command, capture_output=True, text=True, timeout=RECOVERY_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": None,
                "error": f"the recovery command did not finish within {RECOVERY_TIMEOUT}s"}
    except OSError as exc:
        return {"ok": False, "exit_code": None, "error": f"ssh could not run: {exc}"}
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "output": (proc.stdout or "").strip()[:OUTPUT_SNIPPET],
        "error": (proc.stderr or "").strip()[:400],
    }


def available(name: str | None = None) -> dict:
    """What recovery is possible, and on what. Changes nothing.

    Deliberately a separate call from `recover`. "What could you do" must be
    answerable without a confirmation and without the risk of answering it by
    doing it."""
    catalogue = remote.load_targets()
    if not catalogue["available"]:
        return {"available": False, "reason": catalogue["reason"], "path": catalogue["path"]}

    targets = catalogue["targets"]
    if name:
        wanted = str(name).strip().lower()
        targets = [t for t in targets if str(t["name"]).lower() == wanted]
        if not targets:
            return {
                "available": False,
                "reason": (
                    f"There is no configured machine called {name!r}. "
                    f"Configured: {', '.join(catalogue['names'])}."
                ),
                "configured": catalogue["names"],
            }

    machines = []
    for target in targets:
        described = describe_actions(target)
        machines.append({
            "target": target.get("name"),
            "machine": target.get("label") or target.get("name"),
            "ssh_configured": remote.ssh_base_command(target) is not None,
            "actions": described,
            "reason": None if described else (
                "No recovery actions are configured for this machine. Nothing is "
                "wrong - the machine list simply does not describe any, and none "
                "are built in, because a built-in one would assume what is running "
                "on the far end."
            ),
        })
    return {"available": True, "machines": machines, "read_only": True}


def recover(name: str, action_name: str, *, confirm: bool = False,
            ssh_runner=None, now: datetime | None = None) -> dict:
    """Run one configured recovery action on one configured machine.

    Every refusal below returns rather than raises, except the ones that come
    from the caller getting the shape wrong - an unknown machine or an unknown
    action - which raise `RecoveryRefused` so `gateway/tools.py` reports them
    the same way it reports a rate-limited channel message.

    The order is the reasoning, and it is the same order Krish wrote: find out
    what is true, decide whether acting is warranted, then act."""
    now = now or datetime.now().astimezone()

    catalogue = remote.load_targets()
    if not catalogue["available"]:
        raise RecoveryRefused(catalogue["reason"])

    wanted = str(name).strip().lower()
    chosen = [t for t in catalogue["targets"] if str(t["name"]).lower() == wanted]
    if not chosen:
        raise RecoveryRefused(
            f"There is no configured machine called {name!r}. Configured: "
            f"{', '.join(catalogue['names'])}. Only these can be acted on, and that "
            "is deliberate."
        )
    target = chosen[0]

    actions = actions_for(target)
    if not actions:
        raise RecoveryRefused(
            f"No recovery actions are configured for {target.get('name')}. Nothing "
            "is built in, because a built-in restart command would assume what is "
            "running on the far end and which operating system it is running on."
        )

    matching = [a for a in actions if str(a.get("name")).lower() == str(action_name).strip().lower()]
    if not matching:
        raise RecoveryRefused(
            f"There is no recovery action called {action_name!r} for "
            f"{target.get('name')}. Configured: "
            f"{', '.join(str(a.get('name')) for a in actions)}."
        )
    action = matching[0]

    base = remote.ssh_base_command(target)
    if base is None:
        return {
            "attempted": False,
            "target": target.get("name"),
            "action": action.get("name"),
            "reason": (
                f"{target.get('name')} has no usable SSH block, so there is no way to "
                "run anything on it from here. Recovery needs a user, a host and a key "
                "that this machine may use. Diagnosis works without one; acting does "
                "not."
            ),
        }

    # Gate 2, before any probing: a confirmation the model cannot reason its way
    # into. Placed here rather than last so that an unconfirmed call is cheap and
    # tells the operator exactly what it would have done.
    if not confirm:
        return {
            "attempted": False,
            "target": target.get("name"),
            "machine": target.get("label") or target.get("name"),
            "action": action.get("name"),
            "would_run": action.get("description") or action.get("name"),
            "reason": (
                "Not confirmed. This would run a configured command on "
                f"{target.get('label') or target.get('name')}, which is a change to "
                "another machine rather than a look at one. Tell him exactly what it "
                "would do and ask him to confirm; do not confirm on his behalf or "
                "infer it from him having asked about the problem."
            ),
        }

    # Gate 3: diagnose first, always. Krish's sentence as control flow.
    diagnosis = remote.diagnose_target(
        target, tailscale_exe=catalogue.get("tailscale_exe"), ssh_runner=ssh_runner,
    )
    report = diagnosis.get("report") or {}

    if report.get("connectivity") == "unreachable":
        return {
            "attempted": False,
            "target": target.get("name"),
            "action": action.get("name"),
            "diagnosis": report,
            "reason": (
                f"{target.get('label') or target.get('name')} is not reachable from "
                f"here: {report.get('connectivity_why')}. Nothing on it can be "
                "started remotely while that is true, and running an SSH command into "
                "a machine that is off would report a timeout as though it were a "
                "finding. It needs to be powered on and connected first, and nothing "
                "here can do that."
            ),
        }

    # Gate 4: the confidence floor, which is mostly the agent case.
    weak = confidence_gate(diagnosis)
    if weak:
        return {
            "attempted": False,
            "target": target.get("name"),
            "action": action.get("name"),
            "diagnosis": report,
            "reason": weak,
        }

    # Gate 3, second half: this action, against this evidence.
    precheck = precondition(action, diagnosis)
    if not precheck["met"]:
        return {
            "attempted": False,
            "target": target.get("name"),
            "action": action.get("name"),
            "diagnosis": report,
            "reason": precheck["why"],
        }

    # Gate 5: the ceiling.
    limited = rate_check(target.get("name"), action, now=now)
    if limited:
        return {
            "attempted": False,
            "target": target.get("name"),
            "action": action.get("name"),
            "diagnosis": report,
            "reason": limited,
        }

    # The journal is written BEFORE the command runs, and a failure to write
    # refuses the recovery. See the module docstring: the cooldown and the
    # ceiling are computed from this file, so an unwritable journal is the loop
    # protection gone, not a missing convenience.
    entry = {
        "at": now.isoformat(timespec="seconds"),
        "target": target.get("name"),
        "action": action.get("name"),
        "command": action.get("command"),
        "observed_state": precheck.get("observed_state"),
        "confidence": report.get("confidence"),
        "decided_by": "gateway.recovery",
    }
    written = record(entry)
    if not written["recorded"]:
        return {
            "attempted": False,
            "target": target.get("name"),
            "action": action.get("name"),
            "diagnosis": report,
            "reason": (
                f"The recovery journal at {written['path']} could not be written: "
                f"{written['reason']}. Nothing was run. The cooldown and the daily "
                "ceiling are both counted from that file, so acting without it would "
                "be acting with no limit and no record - which is the one way a "
                "recovery becomes worse than the outage."
            ),
        }

    outcome = _run(base + [str(action["command"])], runner=ssh_runner)

    # Verify rather than assume. An exit code of zero from a restart command
    # means the command ran, not that the service came back, and reporting the
    # first as the second is exactly the "every component green, the system
    # silent" failure this fleet has produced before.
    after = remote.diagnose_target(
        target, tailscale_exe=catalogue.get("tailscale_exe"), ssh_runner=ssh_runner,
    )
    after_report = after.get("report") or {}
    verified = precondition(action, after)

    return {
        "attempted": True,
        "target": target.get("name"),
        "machine": target.get("label") or target.get("name"),
        "action": action.get("name"),
        "at": entry["at"],
        "command_ran": outcome.get("ok"),
        "exit_code": outcome.get("exit_code"),
        "output": outcome.get("output"),
        "error": outcome.get("error"),
        "before": {"state": precheck.get("observed_state"), "why": precheck.get("why")},
        "after": {"state": verified.get("observed_state"),
                  "confidence": after_report.get("confidence")},
        # `met` is True when the action's trigger states STILL hold, which means
        # the thing is still broken. Inverted here so the field says what a
        # person means by it.
        "recovered": bool(outcome.get("ok")) and not verified.get("met", False),
        "journal": written["path"],
        "note": (
            "The 'recovered' field is the re-probe, not the exit code. A restart "
            "command can succeed and leave the service exactly as dead as it was; "
            "say what the re-probe found rather than that the command worked."
        ),
    }
