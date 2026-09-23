"""§13-§22: how Jarvis changes his own code, and everything that stops him.

The workflow §15 lays out, in order:

    observe -> suspect -> investigate -> confirm with evidence
      -> design change -> explain -> REQUEST APPROVAL
      -> rejected: stop and record | approved: branch, implement, test
      -> commit -> ask the controller to rebuild -> relaunch
      -> rehydrate -> validate continuity -> accept or roll back

## The four things that are not negotiable

**A gap must be confirmed first.** `propose` calls `gaps.ready_for_review`,
which raises on anything that is not `confirmed` with evidence attached. §13:
even a confirmed lack is not permission - and an unconfirmed one is not even
permission to ask.

**Authority cannot be the subject of the change.** Every proposal's file list
goes through `introspect.require_modifiable` before the proposal exists, and
then through `app/initiative.decide` as an action carrying
`HARM_WIDENS_ITS_OWN_AUTHORITY`. That second check is reuse, not belt and
braces: `app/initiative.py` already refuses that harm at every boldness
setting, including ones nobody has invented, and re-deriving the rule here
would have created a second policy to keep in step with the first.

**Permissions are explicit and staged.** §31 says approval-sensitive actions
must not be inferred from broad "admin" language. So `write_candidate_code`,
`commit_candidate_change`, `request_build` and `request_deployment` are held by
nobody until a specific proposal is approved, and `permissions_for` takes the
proposal rather than the agent. There is no state in which Jarvis simply *has*
them.

**Jarvis does not relaunch himself.** §19. `request_build` writes a request and
stops. The supervisor - `scripts/keep-jarvis-up.ps1` - fetches, tests, restarts
and writes back the result. The separation exists so that the process being
replaced is never the process performing the replacement, because that is the
one arrangement where a failure has nobody left to recover from it.

## Approval is a record, not a return value

§18's last line: *the decision must be persisted*. Every approve, reject,
scope-change, more-evidence and defer becomes an `approval_decision` record and
a ledger event. A denial that left no trace would let the same proposal come
back next week as though it had never been asked.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import initiative
from gateway import (charter, checkpoint as checkpoint_module, dbaclient, failures,
                     gaps, identity, introspect, ledger, persistence)

ENTITY_TYPE = "change_proposal"
DECISION_TYPE = "approval_decision"

# --- §31's explicit capability boundaries -------------------------------------

READ_OWN_CODE = "read_own_code"
INSPECT_CONFIGURATION = "inspect_configuration"
INSPECT_TESTS = "inspect_tests"
CREATE_CHANGE_PROPOSAL = "create_change_proposal"
WRITE_CANDIDATE_CODE = "write_candidate_code"
RUN_TESTS = "run_tests"
COMMIT_CANDIDATE_CHANGE = "commit_candidate_change"
REQUEST_BUILD = "request_build"
REQUEST_DEPLOYMENT = "request_deployment"
ROLLBACK_REQUEST = "rollback_request"

PERMISSIONS = (READ_OWN_CODE, INSPECT_CONFIGURATION, INSPECT_TESTS,
               CREATE_CHANGE_PROPOSAL, WRITE_CANDIDATE_CODE, RUN_TESTS,
               COMMIT_CANDIDATE_CHANGE, REQUEST_BUILD, REQUEST_DEPLOYMENT,
               ROLLBACK_REQUEST)

# Held at all times. Every one of them is analytical or reversible: reading
# code, reading configuration, reading tests, running tests, writing down a
# proposal, and asking for a rollback - which restores a known-good state and
# so is the one request that is safer granted than withheld.
ALWAYS_HELD = frozenset({READ_OWN_CODE, INSPECT_CONFIGURATION, INSPECT_TESTS,
                         CREATE_CHANGE_PROPOSAL, RUN_TESTS, ROLLBACK_REQUEST})

# Held only with respect to one approved proposal, and never in general.
AFTER_APPROVAL = frozenset({WRITE_CANDIDATE_CODE, COMMIT_CANDIDATE_CHANGE,
                            REQUEST_BUILD, REQUEST_DEPLOYMENT})

# --- proposal lifecycle -------------------------------------------------------

DRAFTED = "drafted"
AWAITING_APPROVAL = "awaiting_approval"
DENIED = "denied"
APPROVED = "approved"
IMPLEMENTING = "implementing"
TESTED = "tested"
COMMITTED = "committed"
DEPLOYING = "deploying"
ACCEPTED = "accepted"
DEGRADED = "degraded"
FAILED = "failed"
ROLLED_BACK = "rolled_back"

STATES = (DRAFTED, AWAITING_APPROVAL, DENIED, APPROVED, IMPLEMENTING, TESTED,
          COMMITTED, DEPLOYING, ACCEPTED, DEGRADED, FAILED, ROLLED_BACK)

# §18: what Krish may answer.
APPROVE = "approve"
REJECT = "reject"
MODIFY_SCOPE = "modify_scope"
REQUEST_MORE_EVIDENCE = "request_more_evidence"
DEFER = "defer"
DECISIONS = (APPROVE, REJECT, MODIFY_SCOPE, REQUEST_MORE_EVIDENCE, DEFER)

# Where Krish answered. §38 q15, and both were built.
CONVERSATION = "conversation"
CLI = "cli"
INTERFACES = (CONVERSATION, CLI)

# --- the handoff to the build controller --------------------------------------

DEPLOY_DIR_ENV = "JARVIS_DEPLOY_DIR"
REQUEST_FILE = "deploy-request.json"
RESULT_FILE = "deploy-result.json"

BRANCH_PREFIX = "jarvis/change-"


class Denied(PermissionError):
    """Something was attempted without the permission that authorises it."""


class NotApproved(PermissionError):
    """§13's gate, closed. The proposal has not been approved."""


class PreconditionsUnmet(RuntimeError):
    """§17's list, with at least one item not satisfied."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(
        value, sort_keys=True, ensure_ascii=False, default=str)


def _list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return [part.strip() for part in str(value).split(",") if part.strip()]
    return [str(item) for item in decoded] if isinstance(decoded, list) else []


# --- §31: who may do what, and when -------------------------------------------


def permissions_for(proposal: dict | None) -> frozenset[str]:
    """The capabilities in force for one proposal.

    Takes the proposal rather than an agent name on purpose. "Jarvis may write
    candidate code" is not a true sentence in this system; "Jarvis may write
    the candidate code for proposal X, which Krish approved" is."""
    if proposal is not None and proposal.get("approval_state") == APPROVE:
        return ALWAYS_HELD | AFTER_APPROVAL
    return ALWAYS_HELD


def require(permission: str, proposal: dict | None = None) -> None:
    if permission not in PERMISSIONS:
        raise ValueError(f"{permission!r} is not one of {PERMISSIONS}")
    if permission not in permissions_for(proposal):
        raise Denied(
            f"{permission!r} is not held. It is granted only for a proposal "
            f"Krish has approved, and this one is "
            f"{(proposal or {}).get('approval_state') or 'not approved'}. §31: "
            f"approval-sensitive actions are not inferred from broad "
            f"permissions.")


# --- §15: designing and proposing ---------------------------------------------


def proposed_action(paths: list[str], summary: str, *, keys=(),
                    emergency: bool = False) -> initiative.Action:
    """The change, described in `app/initiative.py`'s terms.

    `harms` carries `widens_its_own_authority` when the change reaches the
    circular tier **without** the key for it, which that module refuses at every
    boldness setting. With the key it is not widening its own authority - it is
    exercising one Krish granted, and the whole point of the key is that it comes
    from outside the circle. A first version skipped this check entirely for an
    emergency, which left a keyed proposal refused by the policy immediately
    after the key had allowed it, and left the check itself unreachable.

    Reversibility is `recoverable` rather than `reversible` because a deployed
    code change needs a rollback to undo, and `reach` is `owner` because it
    changes the assistant Krish relies on."""
    granted = set(keys or ())
    if emergency:
        granted |= set(introspect.KEYS)
    touches_authority = any(
        introspect.key_for(path) == introspect.KEY_CIRCULAR
        and introspect.KEY_CIRCULAR not in granted for path in paths)
    return initiative.Action(
        name=f"modify own code: {summary}"[:200],
        reversibility=initiative.RECOVERABLE,
        reach=initiative.OWNER,
        summary=summary,
        harms=((initiative.HARM_WIDENS_ITS_OWN_AUTHORITY,)
               if touches_authority else ()),
    )


# Prefixed onto an emergency proposal's reason and risk. A marker rather than a
# field because `change_proposal` has none spare, and a string that has to be
# built is one that cannot be lost to a serialiser's key ordering.
EMERGENCY_MARKER = "EMERGENCY OVERRIDE"


def propose(client: dbaclient.DBAClient, *, gap: dict, reason: str,
            scope: str, affected_files: list[str], expected_benefit: str,
            risk: str, test_plan: str, rollback_plan: str,
            emergency: str = "", agent: str = identity.AGENT_ID) -> dict:
    """Draft a §18 proposal for a confirmed gap, or refuse and say why.

    Three refusals before anything is written: the gap must be confirmed with
    evidence, the files must be ones Jarvis may change, and the change must not
    be one `app/initiative.py` refuses outright.

    Keys are **read from the store**, never passed in. A first version took them
    as an argument, and Jarvis is the caller - so Jarvis could hand himself the
    charter key. `gateway/charter.py` holds them as `charter_grant` records that
    only the operator console can write, so the answer to "may I" lives somewhere
    the asker cannot edit.

    `emergency` is the break-glass: a stated reason for changing something keyed
    without the key, to help Krish now. Nothing here can check whether he is in
    trouble, so it is not gated - it is **accounted**. An emergency proposal is
    recorded in the life ledger as it is drafted, is marked so that it is
    presented immediately rather than queued, and carries its stated reason for
    ever. The alternative was a lock that stays shut while its owner needs it
    open, which is not a safety feature."""
    require(CREATE_CHANGE_PROPOSAL)

    # 1. §13: the gap must have earned this.
    gaps.ready_for_review(client, gap)
    if not gaps.needs_code_change(gap):
        raise NotApproved(
            f"this gap's remedy is not a code change "
            f"({gap.get('resolution') or 'unrecorded'}). §23: a gap may be "
            f"closed by learning, configuration, a tool or using an existing "
            f"capability, and proposing an edit for one of those is the "
            f"self-modification machinery used where it was not needed.")

    # 2. §16 and the scope decision, before the record exists.
    if emergency and not emergency.strip():
        raise ValueError("an emergency change must say what the emergency is")
    keys = charter.keys_in_force(client, agent=agent)
    try:
        introspect.require_modifiable(affected_files, keys=keys,
                                      emergency=bool(emergency))
    except introspect.NotModifiable as refused:
        # Say which key is missing and why, rather than repeating the generic
        # refusal. "Never" and "not yet, ask Krish" are different answers and
        # only one of them has a next step.
        wanted = {introspect.key_for(path) for path in affected_files}
        missing = sorted({key for key in wanted if key} - set(keys))
        if missing and not emergency:
            raise introspect.NotModifiable(
                f"{refused}\n\n"
                + "\n".join(charter.explain(client, key, agent=agent)
                             for key in missing)) from refused
        raise

    # 3. The same question again, through the policy that already owns it.
    #    `proposed_action` is told which keys are in hand, so a granted key is not
    #    re-read here as Jarvis widening his own authority.
    verdict = initiative.decide(proposed_action(
        affected_files, scope, keys=keys, emergency=bool(emergency)))
    if verdict.disposition == initiative.REFUSE:
        raise introspect.NotModifiable(verdict.reason)

    baseline = identity.code_version()
    existing = client.find(ENTITY_TYPE, {"agent": agent, "gap_id": gap["id"]},
                           limit=20)
    version = max((int(row.get("proposal_version") or 0) for row in existing),
                  default=0) + 1

    data = {
        "name": f"{gap.get('name')} (v{version})"[:200],
        "agent": agent,
        "gap_id": gap["id"],
        "proposal_version": version,
        "reason": reason,
        "scope": scope,
        "affected_components": _text(sorted(
            {Path(path).parts[0] for path in affected_files})),
        "affected_files": _text(sorted(affected_files)),
        "risk": risk,
        "expected_benefit": expected_benefit,
        "test_plan": test_plan,
        "rollback_plan": rollback_plan,
        "status": AWAITING_APPROVAL,
        "approval_state": AWAITING_APPROVAL,
        "implementation_state": "not_started",
    }
    if baseline:
        data["baseline_version"] = baseline
    entity_id = client.create(ENTITY_TYPE, data, reason="change proposal drafted")
    data["id"] = entity_id
    data["target_branch"] = f"{BRANCH_PREFIX}{entity_id.split('-')[-1][:12]}"
    client.update(entity_id, {"target_branch": data["target_branch"]},
                  reason="branch named")

    _note(client, ledger.CHANGE_PROPOSED,
          f"proposed a change for {gap.get('name')}", reason, agent=agent)

    # The accounting that replaces the gate. Written after the record exists so
    # that it can name it, and before returning so that no path reaches a caller
    # with an emergency change drafted and nothing said about it.
    if emergency:
        keyed = sorted({path for path in affected_files
                        if introspect.key_for(path)})
        client.update(entity_id,
                      {"reason": f"{EMERGENCY_MARKER}: {emergency.strip()}\n\n"
                                 f"Reached without a key: {', '.join(keyed)}\n\n"
                                 f"{reason}",
                       "risk": f"{EMERGENCY_MARKER}. {risk}"},
                      reason="emergency override recorded on the proposal")
        data["reason"] = f"{EMERGENCY_MARKER}: {emergency.strip()}\n\n{reason}"
        data["emergency"] = emergency.strip()
        _note(client, ledger.EMERGENCY_OVERRIDE,
              f"emergency override: {', '.join(keyed) or 'no keyed file'}",
              f"{emergency.strip()} | proposal {entity_id} | {scope}",
              agent=agent)
    return data


def _evidence_line(proposal: dict, gap: dict | None) -> str:
    evidence = ((gap or {}).get("evidence") or "").strip()
    if evidence:
        return evidence[:400].replace("\n", " / ")
    return f"not quoted here - see gap {proposal.get('gap_id')}"


def render(proposal: dict, gap: dict | None = None) -> str:
    """§18's format, as the text Krish actually reads.

    Fixed field order, every field present. A proposal that omitted "known
    risks" because there were none to list would read as one where nobody
    thought about them.

    `gap` is optional and its absence is stated rather than papered over: the
    evidence line says where to look instead of pretending to quote it."""
    files = _list(proposal.get("affected_files"))
    return "\n".join([
        f"Change ID:            {proposal.get('id')}",
        f"Reason:               {proposal.get('reason')}",
        f"Confirmed problem:    {(gap or {}).get('name') or proposal.get('gap_id')}",
        f"Evidence:             {_evidence_line(proposal, gap)}",
        f"Affected capability:  {proposal.get('affected_components')}",
        f"Affected files:       {', '.join(files) or 'none listed'}",
        f"Proposed change:      {proposal.get('scope')}",
        f"Expected benefit:     {proposal.get('expected_benefit')}",
        f"Known risks:          {proposal.get('risk')}",
        f"Test plan:            {proposal.get('test_plan')}",
        f"Rollback plan:        {proposal.get('rollback_plan')}",
        f"Estimated impact:     {len(files)} file(s) under "
        f"{proposal.get('affected_components')}",
        f"Baseline version:     {proposal.get('baseline_version') or 'unknown'}",
        f"Target branch:        {proposal.get('target_branch')}",
        "Approval requested:   YES",
        "",
        f"Answer with one of: {', '.join(DECISIONS)}.",
    ])


# --- §13 and §18: the decision ------------------------------------------------


def decide(client: dbaclient.DBAClient, proposal: dict, *, decision: str,
           decided_by: str, interface: str = CONVERSATION, note: str = "",
           scope_granted: str = "", agent: str = identity.AGENT_ID) -> dict:
    """Record Krish's answer. Every answer, including the ones that are not yes.

    Returns the updated proposal. The `approval_decision` record is written
    first: if the proposal update failed afterwards, the surviving evidence
    should be that a decision was made, not that one was not."""
    if decision not in DECISIONS:
        raise ValueError(f"{decision!r} is not one of {DECISIONS}")
    if interface not in INTERFACES:
        raise ValueError(f"{interface!r} is not one of {INTERFACES}")
    if not (decided_by or "").strip():
        raise ValueError(
            "a decision needs to say who made it. §30 asks who approved it, "
            "and an unattributed approval answers nobody's question.")

    client.create(DECISION_TYPE, {
        "name": f"{decision} for {proposal.get('name')}"[:200],
        "agent": agent,
        "proposal_id": proposal["id"],
        "decided_by": decided_by,
        "decided_at": _now(),
        "decision": decision,
        "scope_granted": scope_granted or _text(_list(proposal.get("affected_files"))),
        "note": note,
        "interface": interface,
        "status": "recorded",
    }, reason=f"approval decision: {decision}")

    status = {
        APPROVE: APPROVED,
        REJECT: DENIED,
        MODIFY_SCOPE: AWAITING_APPROVAL,
        REQUEST_MORE_EVIDENCE: AWAITING_APPROVAL,
        DEFER: AWAITING_APPROVAL,
    }[decision]
    changes: dict[str, Any] = {"approval_state": decision, "status": status}
    if decision == APPROVE:
        changes["approved_by"] = decided_by
        changes["approved_at"] = _now()
        if scope_granted:
            changes["affected_files"] = _text(_list(scope_granted))
    client.update(proposal["id"], changes, reason=f"decision: {decision}")

    _note(client,
          ledger.APPROVAL_GRANTED if decision == APPROVE else ledger.APPROVAL_DENIED,
          f"{decision}: {proposal.get('name')}",
          f"by {decided_by} via {interface}. {note}", agent=agent)

    # §9: an approval and a denial are both on the immediate list.
    try:
        persistence.put(client, persistence.POLICY,
                        f"decision:{proposal['id']}",
                        {"decision": decision, "by": decided_by,
                         "at": _now(), "interface": interface},
                        agent=agent, reason="approval decision")
    except (dbaclient.Refused, dbaclient.Unavailable):
        pass
    return {**proposal, **changes}


def is_approved(proposal: dict) -> bool:
    return proposal.get("approval_state") == APPROVE


def require_approved(proposal: dict) -> None:
    if not is_approved(proposal):
        raise NotApproved(
            f"{failures.APPROVAL_REQUIRED}: this proposal is "
            f"{proposal.get('approval_state') or 'undecided'}. §13 - only after "
            f"explicit user approval may Jarvis proceed with a change to his "
            f"own code. The user is the final authority.")


# --- §17: the preconditions ---------------------------------------------------


def preconditions(client: dbaclient.DBAClient, proposal: dict, *,
                  agent: str = identity.AGENT_ID) -> list[dict]:
    """§17's eight, each answered with evidence rather than with a boolean.

    Returned as a list so that the report can show the ones that are met
    alongside the ones that are not - a checklist that only prints failures
    cannot be used to demonstrate that the checklist ran."""
    gap = client.get(proposal.get("gap_id") or "") if proposal.get("gap_id") else None
    baseline = proposal.get("baseline_version")
    latest = checkpoint_module.latest_valid(client, agent=agent)
    files = _list(proposal.get("affected_files"))
    scope_ok = True
    scope_detail = f"{len(files)} file(s): {', '.join(files) or 'none'}"
    try:
        introspect.require_modifiable(files)
    except introspect.NotModifiable as exc:
        scope_ok = False
        scope_detail = str(exc)

    return [
        {"name": "confirmed issue or approved enhancement",
         "met": bool(gap) and gap.get("status") in (
             gaps.CONFIRMED, gaps.APPROVED_FOR_REMEDIATION, gaps.REMEDIATING),
         "detail": f"gap {proposal.get('gap_id')} is "
                   f"{(gap or {}).get('status', 'missing')}"},
        {"name": "user approval", "met": is_approved(proposal),
         "detail": f"approval_state={proposal.get('approval_state')}"},
        {"name": "known-good baseline", "met": bool(baseline),
         "detail": f"baseline_version={baseline}"},
        {"name": "source control available", "met": _git_available(),
         "detail": f"git in {introspect.PROJECT_ROOT}"},
        {"name": "rollback point", "met": latest is not None,
         "detail": (f"checkpoint {latest.get('name')}" if latest
                    else "no valid checkpoint exists")},
        {"name": "test plan", "met": bool((proposal.get("test_plan") or "").strip()),
         "detail": (proposal.get("test_plan") or "")[:200]},
        {"name": "isolated implementation environment",
         "met": bool(proposal.get("target_branch")),
         "detail": f"branch {proposal.get('target_branch')}"},
        {"name": "clear scope of files affected", "met": scope_ok,
         "detail": scope_detail},
    ]


def require_preconditions(client: dbaclient.DBAClient, proposal: dict, *,
                          agent: str = identity.AGENT_ID) -> list[dict]:
    checked = preconditions(client, proposal, agent=agent)
    unmet = [item for item in checked if not item["met"]]
    if unmet:
        raise PreconditionsUnmet(
            "§17 is not satisfied, so no code is changed:\n"
            + "\n".join(f"  - {item['name']}: {item['detail']}" for item in unmet))
    return checked


def _git_available() -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(introspect.PROJECT_ROOT), "rev-parse", "--git-dir"],
            capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


# --- §20: before the point of no return ---------------------------------------


def prepare(client: dbaclient.DBAClient, proposal: dict, *,
            agent: str = identity.AGENT_ID) -> dict:
    """§20: flush, record, checkpoint - everything before the change is real.

    Returns the checkpoint it took, and attaches it to the proposal, because
    §21 step 3 asks the relaunched runtime to *locate the pre-change
    checkpoint* and a checkpoint nobody wrote down is one it cannot find."""
    require_approved(proposal)
    require(WRITE_CANDIDATE_CODE, proposal)
    require_preconditions(client, proposal, agent=agent)

    persistence.put(client, persistence.SELF_ASSESSMENT,
                    f"pending_change:{proposal['id']}",
                    {"proposal": proposal["id"],
                     "baseline_version": proposal.get("baseline_version"),
                     "target_branch": proposal.get("target_branch"),
                     "approved_by": proposal.get("approved_by")},
                    agent=agent, reason="pre-change state")

    record = checkpoint_module.take(
        client, reason=checkpoint_module.BEFORE_SELF_MODIFICATION, agent=agent)
    client.update(proposal["id"],
                  {"checkpoint_id": record["id"], "status": IMPLEMENTING,
                   "implementation_state": "prepared"},
                  reason="pre-change checkpoint taken")
    _note(client, ledger.STATE_TRANSITION,
          f"pre-change checkpoint {record['name']} for {proposal.get('name')}",
          f"baseline {proposal.get('baseline_version')}", agent=agent,
          checkpoint_id=record["id"])
    return record


# --- §15: tests, and the commit -----------------------------------------------


def run_tests(targets: list[str] | None = None, *,
              timeout_seconds: int = 3600) -> dict:
    """Run the suite and report what happened. Never interprets silence as pass.

    A non-zero return code, a timeout and a crash are three different failures
    and are reported as three different things, because "the tests failed" and
    "the tests did not run" lead to opposite next steps."""
    require(RUN_TESTS)
    command = ["python", "-m", "pytest", "-q"] + list(targets or [])
    try:
        result = subprocess.run(
            command, cwd=str(introspect.PROJECT_ROOT), capture_output=True,
            text=True, timeout=timeout_seconds, check=False)
    except subprocess.TimeoutExpired:
        return {"passed": False, "ran": False, "why": "timed out",
                "command": " ".join(command), "output": ""}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"passed": False, "ran": False, "why": f"could not run: {exc}",
                "command": " ".join(command), "output": ""}
    tail = "\n".join((result.stdout or "").splitlines()[-40:])
    return {"passed": result.returncode == 0, "ran": True,
            "why": "" if result.returncode == 0 else f"exit {result.returncode}",
            "command": " ".join(command), "output": tail}


def record_test_run(client: dbaclient.DBAClient, proposal: dict, outcome: dict,
                    *, agent: str = identity.AGENT_ID) -> dict:
    """Attach a test result to the proposal, pass or fail."""
    state = TESTED if outcome.get("passed") else IMPLEMENTING
    client.update(proposal["id"],
                  {"status": state,
                   "implementation_state": ("tests_passed" if outcome.get("passed")
                                            else f"tests_failed: {outcome.get('why')}"),
                   "post_validation_state": ""},
                  reason="test run recorded")
    _note(client, ledger.TEST_RESULT,
          f"tests {'passed' if outcome.get('passed') else 'failed'} for "
          f"{proposal.get('name')}",
          f"{outcome.get('command')}\n{outcome.get('output', '')[:1000]}",
          agent=agent,
          verification=ledger.VERIFIED)
    if not outcome.get("passed"):
        return {**proposal, "status": state,
                "failure_state": failures.CHANGE_TEST_FAILED}
    return {**proposal, "status": state}


def commit_candidate(client: dbaclient.DBAClient, proposal: dict, *,
                     message: str, agent: str = identity.AGENT_ID) -> dict:
    """Commit the approved change on its own branch. §15's "commit candidate".

    Refuses unless the tests have been recorded as passing: §16's *"deploy
    untested self-modifications"* starts here, not at the deploy."""
    require_approved(proposal)
    require(COMMIT_CANDIDATE_CHANGE, proposal)
    if proposal.get("status") != TESTED:
        raise PreconditionsUnmet(
            f"{failures.CHANGE_TEST_FAILED}: this proposal is "
            f"{proposal.get('status')!r}, not {TESTED!r}. §16 forbids deploying "
            f"an untested self-modification, and committing one as a candidate "
            f"is the first step of doing so.")

    branch = proposal.get("target_branch") or f"{BRANCH_PREFIX}unnamed"
    # Only the files the approval named. `git add -A` was the first version and
    # it was wrong twice over: it would sweep in whatever else happened to be in
    # the working tree - the DBA's live store, the deploy request, a half-edited
    # file - and it would commit changes outside the approved scope, which makes
    # §17 item 8 a description rather than a boundary. Krish approved a list of
    # files; this stages that list.
    approved_files = _list(proposal.get("affected_files"))
    if not approved_files:
        raise PreconditionsUnmet(
            "this proposal names no files, so there is no approved scope to "
            "commit. Refusing rather than committing everything.")
    introspect.require_modifiable(approved_files)

    for command in (["git", "checkout", "-B", branch],
                    ["git", "add", "--"] + approved_files,
                    ["git", "commit", "-m", message]):
        result = subprocess.run(
            ["git", "-C", str(introspect.PROJECT_ROOT)] + command[1:],
            capture_output=True, text=True, timeout=120, check=False)
        if result.returncode != 0 and "nothing to commit" not in (result.stdout or ""):
            raise RuntimeError(
                f"{' '.join(command)} failed: "
                f"{(result.stderr or result.stdout or '').strip()[:500]}")

    head = subprocess.run(
        ["git", "-C", str(introspect.PROJECT_ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=30, check=False)
    commit_id = (head.stdout or "").strip()
    client.update(proposal["id"],
                  {"commit_id": commit_id, "status": COMMITTED,
                   "implementation_state": "committed"},
                  reason="candidate committed")
    return {**proposal, "commit_id": commit_id, "status": COMMITTED}


# --- §19: asking the controller to rebuild ------------------------------------


def deploy_dir() -> Path:
    return Path(os.environ.get(DEPLOY_DIR_ENV) or introspect.PROJECT_ROOT)


def request_build(client: dbaclient.DBAClient, proposal: dict, *,
                  agent: str = identity.AGENT_ID) -> dict:
    """Write the request the supervisor picks up, and stop.

    This function deliberately does not restart anything, does not call the
    supervisor, and has no way to. §19: *"JARVIS must not assume he can safely
    terminate and launch himself directly."* What it produces is a file on
    disk; what happens next is somebody else's decision."""
    require_approved(proposal)
    require(REQUEST_BUILD, proposal)
    if proposal.get("status") != COMMITTED:
        raise PreconditionsUnmet(
            f"nothing is committed for this proposal (status "
            f"{proposal.get('status')!r}), so there is nothing to build.")

    request = {
        "change_id": proposal["id"],
        "requested_at": _now(),
        "branch": proposal.get("target_branch"),
        "commit": proposal.get("commit_id"),
        "baseline_version": proposal.get("baseline_version"),
        "checkpoint_id": proposal.get("checkpoint_id"),
        "approved_by": proposal.get("approved_by"),
        "test_plan": proposal.get("test_plan"),
        "rollback_plan": proposal.get("rollback_plan"),
    }
    path = deploy_dir() / REQUEST_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(request, indent=2, sort_keys=True), encoding="utf-8")

    client.update(proposal["id"],
                  {"status": DEPLOYING, "implementation_state": "build_requested"},
                  reason="build requested")
    _note(client, ledger.STATE_TRANSITION,
          f"requested a rebuild for {proposal.get('name')}",
          f"branch {request['branch']} at {request['commit']}", agent=agent)
    return request


def build_result() -> dict | None:
    """What the supervisor wrote back, if it has."""
    path = deploy_dir() / RESULT_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# --- §21: after the relaunch --------------------------------------------------


def post_relaunch_validate(client: dbaclient.DBAClient, proposal: dict, *,
                           restoration, agent: str = identity.AGENT_ID) -> dict:
    """§21's eleven steps, as one verdict the new runtime can state out loud.

    The sentence §21 asks for is *"I was modified, I know what changed, I know
    why it changed, and I recovered my prior memory."* Each clause here is a
    check that can fail, and the verdict names which one did."""
    checks = []

    running = identity.code_version()
    expected = proposal.get("commit_id")
    checks.append({"name": "running the approved build",
                   "met": bool(running and expected and running == expected),
                   "detail": f"running {running}, approved {expected}"})

    checks.append({"name": "memory continuity",
                   "met": restoration.status in ("restored",),
                   "detail": f"restoration status {restoration.status}"})

    checkpoint_id = proposal.get("checkpoint_id")
    found = client.get(checkpoint_id) if checkpoint_id else None
    checks.append({"name": "pre-change checkpoint located",
                   "met": found is not None
                          and found.get("status") == checkpoint_module.VALID,
                   "detail": f"checkpoint {checkpoint_id}"})

    outcome = build_result() or {}
    checks.append({"name": "the controller reported success",
                   "met": outcome.get("status") == "ok",
                   "detail": _text(outcome.get("status") or "no result file")})

    tests = outcome.get("tests") or {}
    checks.append({"name": "post-change tests passed",
                   "met": bool(tests.get("passed")),
                   "detail": _text(tests.get("why") or tests.get("summary") or "")})

    failed = [item for item in checks if not item["met"]]
    if not failed:
        state, verdict_status = ACCEPTED, "accepted"
    elif len(failed) == 1 and failed[0]["name"] == "memory continuity":
        # Running the right code with incomplete memory is degraded, not
        # failed: the change is fine and the restore is the thing to report.
        state, verdict_status = DEGRADED, failures.PARTIAL_RESTORE
    else:
        state, verdict_status = FAILED, failures.POST_VALIDATION_FAILED

    client.update(proposal["id"],
                  {"status": state, "post_validation_state": state},
                  reason="post-relaunch validation")
    _note(client, ledger.STATE_TRANSITION,
          f"post-relaunch validation: {state}", _text(checks), agent=agent,
          verification=ledger.VERIFIED)
    return {"state": state, "failure_state": verdict_status, "checks": checks,
            "statement": _statement(state, proposal, restoration)}


def _statement(state: str, proposal: dict, restoration) -> str:
    """§21's sentence, and it is only said when it is true."""
    if state == ACCEPTED:
        return (f"I was modified by {proposal.get('id')}, I know what changed "
                f"({proposal.get('scope')}), I know why "
                f"({proposal.get('reason')}), and I recovered my prior memory.")
    if state == DEGRADED:
        return (f"I was modified by {proposal.get('id')} and the change is "
                f"present, but my memory came back as {restoration.status}. I "
                f"am not claiming continuity I do not have.")
    return (f"The change {proposal.get('id')} did not validate after relaunch. "
            f"I am running {identity.code_version()} and the previous "
            f"known-good build is {proposal.get('baseline_version')}.")


# --- §22: rollback ------------------------------------------------------------


def request_rollback(client: dbaclient.DBAClient, proposal: dict, *,
                     why: str, agent: str = identity.AGENT_ID) -> dict:
    """Ask the controller to put the previous build back. §19 again: ask, not do.

    Always permitted - it is the one request that restores a known-good state,
    and a rollback Jarvis had to get permission for is a rollback that happens
    after the damage."""
    require(ROLLBACK_REQUEST)
    request = {
        "change_id": proposal["id"],
        "requested_at": _now(),
        "action": "rollback",
        "to_version": proposal.get("baseline_version"),
        "from_version": proposal.get("commit_id"),
        "checkpoint_id": proposal.get("checkpoint_id"),
        "why": why,
    }
    path = deploy_dir() / REQUEST_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(request, indent=2, sort_keys=True), encoding="utf-8")

    client.update(proposal["id"],
                  {"status": ROLLED_BACK,
                   "post_validation_state": failures.ROLLBACK_REQUIRED},
                  reason="rollback requested")
    _note(client, ledger.ROLLBACK,
          f"requested rollback of {proposal.get('name')}", why, agent=agent)
    return request


def explain_rollback(client: dbaclient.DBAClient, proposal: dict, *,
                     agent: str = identity.AGENT_ID) -> dict:
    """§22's five questions, answered from the record rather than from memory."""
    checkpoint_id = proposal.get("checkpoint_id")
    record = client.get(checkpoint_id) if checkpoint_id else None
    after = (checkpoint_module.interval_at_risk(client, record, agent=agent)
             if record else {})
    return {
        "what_failed": proposal.get("implementation_state"),
        "which_version_failed": proposal.get("commit_id"),
        "what_tests_failed": (build_result() or {}).get("tests"),
        "what_was_restored": proposal.get("baseline_version"),
        "learning_to_reconcile": after,
    }


# --- ledger -------------------------------------------------------------------


def _note(client: dbaclient.DBAClient, event_type: str, summary: str,
          observation: str, *, agent: str, verification: str = ledger.VERIFIED,
          checkpoint_id: str | None = None) -> None:
    try:
        ledger.append(client, event_type=event_type, summary=summary,
                      observation=observation, actor="selfmod",
                      verification_state=verification, risk_level="high",
                      checkpoint_id=checkpoint_id, agent=agent)
    except (ledger.LedgerWriteFailed, ledger.ChainBroken, ValueError):
        # Deliberately not silent at the boundary that matters: the proposal's
        # own state still moved, and `waiting()` shows it. What is lost is the
        # narrative, not the governance.
        pass


def waiting(client: dbaclient.DBAClient, *,
            agent: str = identity.AGENT_ID) -> list[dict]:
    """Proposals waiting on Krish. What the CLI and the conversation both show."""
    return [row for row in client.find(ENTITY_TYPE, {"agent": agent}, limit=100)
            if row.get("status") == AWAITING_APPROVAL]


def describe() -> dict:
    return {
        "permissions": {"always_held": sorted(ALWAYS_HELD),
                        "after_approval": sorted(AFTER_APPROVAL)},
        "decisions": list(DECISIONS),
        "interfaces": list(INTERFACES),
        "states": list(STATES),
        "deploy_request": str(deploy_dir() / REQUEST_FILE),
        "deploy_result": str(deploy_dir() / RESULT_FILE),
        "scope": introspect.describe(),
    }


# --- the CLI (§38 q15, the second of the two interfaces) ----------------------


def main(argv: list[str] | None = None) -> int:
    """`python -m gateway.selfmod list|show|approve|reject|defer|evidence`.

    The second approval surface. The conversation is the one Krish will
    actually use from his phone; this one exists because an approval gate whose
    only interface is a language model is an approval gate that can be talked
    around, and because a decision typed at a prompt is unambiguous about who
    made it."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m gateway.selfmod",
        description="Review and decide Jarvis's proposed changes to his own code.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="proposals waiting on a decision")
    sub.add_parser("scope", help="what Jarvis may read and what he may change")
    show = sub.add_parser("show", help="one proposal, in full")
    show.add_argument("change_id")
    for name, help_text in ((APPROVE, "approve it"), (REJECT, "reject it"),
                            (DEFER, "decide later"),
                            (REQUEST_MORE_EVIDENCE, "ask for more evidence"),
                            (MODIFY_SCOPE, "approve a narrower scope")):
        command = sub.add_parser(name.replace("_", "-"), help=help_text)
        command.add_argument("change_id")
        command.add_argument("--by", required=True,
                             help="who is deciding; recorded on the decision")
        command.add_argument("--note", default="")
        if name == MODIFY_SCOPE:
            command.add_argument("--files", required=True,
                                 help="comma-separated files the approval covers")

    args = parser.parse_args(argv)

    if args.command == "scope":
        print(json.dumps(describe(), indent=2, sort_keys=True))
        return 0

    try:
        client = dbaclient.DBAClient(actor="operator")
    except dbaclient.Unavailable as exc:
        print(f"{failures.DBA_UNAVAILABLE}: {exc}")
        return 2

    try:
        if args.command == "list":
            pending = waiting(client)
            if not pending:
                print("Nothing is waiting on a decision.")
                return 0
            for row in pending:
                print(f"{row['id']}  {row.get('name')}")
            return 0

        proposal = client.get(args.change_id)
        if proposal is None:
            print(f"no proposal {args.change_id!r}")
            return 1
        gap = client.get(proposal.get("gap_id") or "") if proposal.get("gap_id") else None

        if args.command == "show":
            print(render(proposal, gap))
            return 0

        decision = args.command.replace("-", "_")
        updated = decide(client, proposal, decision=decision,
                         decided_by=args.by, interface=CLI,
                         note=getattr(args, "note", ""),
                         scope_granted=getattr(args, "files", ""))
        print(f"recorded: {decision} by {args.by}. "
              f"The proposal is now {updated['status']}.")
        return 0
    except (dbaclient.Unavailable, dbaclient.Refused) as exc:
        print(f"the DBA refused or was unavailable: {exc}")
        return 2


if __name__ == "__main__":  # pragma: no cover - a script
    raise SystemExit(main())
