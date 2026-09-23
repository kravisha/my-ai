"""§11 and §12: a suspected weakness is not a confirmed weakness.

    SUSPECTED -> INVESTIGATION -> EVIDENCE -> VALIDATION
        -> CONFIRMED or REJECTED -> USER REVIEW -> REMEDIATION

The specification is blunt about why this is a lifecycle and not a flag:
*"JARVIS must not pursue every feeling of inadequacy. He must investigate
first."* So nothing here can move a gap to `confirmed` without evidence
attached, and `propose_remediation` refuses a gap that is not confirmed.

## What this adds to what already existed

`app/capability_gaps.py` already detects gaps and ranks them by how often Krish
actually asked - it has been writing `capability_gaps.jsonl` on the failure
paths for some time. That module is the **detector**, and it stays exactly as
it is. This module is the **governor**: it promotes a detected pattern into a
`capability_gap` record in the DBA, carries it through §12's states, and holds
the approval gate shut.

The two were deliberately not merged. The detector runs inside a handler for a
turn that has already failed and must never raise; the governor runs
deliberately, can talk to the DBA, and *should* raise when something is wrong.
Putting them in one module would have meant one of those two properties losing.

## `investigating` is a state that investigates

It was not. A gap entered `investigating` and left it for `confirmed` because
somebody called `confirm`, and §12's list of confirmation methods was a list in
a document. `investigate` now opens a `gateway.inquiry.Inquiry` and `settle`
demands it back concluded - and an inquiry refuses to conclude when the shape of
its own reasoning is bad. That is the whole of what the two functions add: the
lifecycle can no longer be walked without something having been reasoned about.

`investigate` seeds no hypotheses. Pre-loading *"maybe there is no gap"* was
tempting and would even be useful, but a framework that writes the first
hypothesis has chosen the anchor, and `inquiry.ANCHORED` - the check for exactly
that - could then never fire against a real explanation. The investigator says
what the candidates are.

## Evidence is kept, including the evidence against

§12 asks that the evidence which caused a classification be preserved, and a
rejected gap keeps its `counter_evidence` - the record of *why* Jarvis decided
he could do the thing after all. Without it the same suspicion returns next
month with nothing to answer it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app import capability_gaps as detector
from gateway import dbaclient, failures, identity, inquiry, ledger

ENTITY_TYPE = "capability_gap"

# §12's list, in the order a gap moves through them.
SUSPECTED = "suspected"
INVESTIGATING = "investigating"
UNSUPPORTED = "unsupported"
CONFIRMED = "confirmed"
REJECTED = "rejected"
DEFERRED = "deferred"
APPROVED_FOR_REMEDIATION = "approved_for_remediation"
REMEDIATING = "remediating"
RESOLVED = "resolved"
UNRESOLVED = "unresolved"

STATES = (SUSPECTED, INVESTIGATING, UNSUPPORTED, CONFIRMED, REJECTED, DEFERRED,
          APPROVED_FOR_REMEDIATION, REMEDIATING, RESOLVED, UNRESOLVED)

# Which moves are legal. Declared rather than checked ad hoc, because the one
# transition this module exists to forbid - suspected straight to
# approved_for_remediation - is exactly the one a convenience shortcut would
# add without anybody noticing.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    SUSPECTED: (INVESTIGATING, DEFERRED, REJECTED),
    INVESTIGATING: (CONFIRMED, REJECTED, UNSUPPORTED, DEFERRED),
    UNSUPPORTED: (INVESTIGATING, REJECTED, DEFERRED),
    CONFIRMED: (APPROVED_FOR_REMEDIATION, REJECTED, DEFERRED, UNRESOLVED),
    DEFERRED: (INVESTIGATING, CONFIRMED, REJECTED),
    APPROVED_FOR_REMEDIATION: (REMEDIATING, REJECTED, UNRESOLVED),
    REMEDIATING: (RESOLVED, UNRESOLVED),
    # Final. A resolved gap that comes back is a new suspicion with its own
    # evidence, not a reopened old one - otherwise the frequency count that
    # drives the ranking would merge two separate episodes into one.
    RESOLVED: (),
    REJECTED: (INVESTIGATING,),
    UNRESOLVED: (INVESTIGATING, DEFERRED),
}

# §23: a gap does not automatically mean a code change. Jarvis must decide
# which of these applies *before* proposing one, and the list is declared so
# that "change the code" cannot be the only option anybody remembers.
REMEDY_KNOWLEDGE = "learn_knowledge"
REMEDY_SKILL = "improve_skill"
REMEDY_CONFIGURATION = "add_configuration"
REMEDY_TOOL = "add_tool"
REMEDY_WORKFLOW = "change_workflow"
REMEDY_USE_EXISTING = "use_existing_capability"
REMEDY_CODE = "change_code"
REMEDIES = (REMEDY_KNOWLEDGE, REMEDY_SKILL, REMEDY_CONFIGURATION, REMEDY_TOOL,
            REMEDY_WORKFLOW, REMEDY_USE_EXISTING, REMEDY_CODE)

# The only remedy that needs the self-modification machinery. Everything else
# Jarvis may simply do.
NEEDS_CODE_CHANGE = (REMEDY_CODE,)


class IllegalTransition(ValueError):
    """A move the lifecycle does not allow, refused by name.

    The message says which moves *are* allowed, because the caller that tried
    to jump the queue is usually a caller that did not know the queue existed."""


class NotConfirmed(RuntimeError):
    """§34's `GAP_UNCONFIRMED`. Something asked for remediation too early."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(
        value, sort_keys=True, ensure_ascii=False, default=str)


# --- reading ------------------------------------------------------------------


def all_gaps(client: dbaclient.DBAClient, *, status: str | None = None,
             agent: str = identity.AGENT_ID, limit: int = 200) -> list[dict]:
    criteria: dict[str, Any] = {"agent": agent}
    if status is not None:
        criteria["status"] = _check_state(status)
    return client.find(ENTITY_TYPE, criteria, limit=limit)


def find_by_title(client: dbaclient.DBAClient, title: str, *,
                  agent: str = identity.AGENT_ID) -> dict | None:
    found = client.find(ENTITY_TYPE, {"agent": agent, "name": title}, limit=5)
    return found[0] if found else None


def _check_state(state: str) -> str:
    if state not in STATES:
        raise ValueError(f"{state!r} is not one of {STATES}")
    return state


def _check_remedy(remedy: str) -> str:
    if remedy not in REMEDIES:
        raise ValueError(
            f"{remedy!r} is not one of {REMEDIES}. §23 asks which category "
            f"applies before a code change is proposed; an undeclared one "
            f"would let 'change the code' be the default by omission.")
    return remedy


# --- §11: suspecting ----------------------------------------------------------


def suspect(client: dbaclient.DBAClient, *, title: str, description: str,
            detected_by: str, evidence: str | list | dict = "",
            affected_capability: str | None = None,
            severity: str = "unknown", frequency: int = 1,
            agent: str = identity.AGENT_ID) -> dict:
    """Record a suspicion. Deliberately cheap, and deliberately not a finding.

    Suspicion is allowed to be wrong - §11 says Jarvis may notice possible
    limitations. What is not allowed is acting on it, and `suspect` gives it
    the one status from which no remediation is reachable."""
    existing = find_by_title(client, title, agent=agent)
    if existing is not None:
        # Suspecting the same thing again is evidence about frequency, not a
        # second gap. §6.2's ranking rule is frequency of request, and two
        # records would halve the count of the thing most worth fixing.
        client.update(existing["id"],
                      {"frequency": int(existing.get("frequency") or 1) + 1},
                      reason="suspected again")
        return {**existing,
                "frequency": int(existing.get("frequency") or 1) + 1}

    data = {
        "name": title, "agent": agent, "description": description,
        "detected_at": _now(), "detected_by": detected_by,
        "status": SUSPECTED, "evidence": _text(evidence),
        "severity": severity, "frequency": max(1, int(frequency)),
        "user_review_required": True,
    }
    if affected_capability:
        data["affected_capability"] = affected_capability
    entity_id = client.create(ENTITY_TYPE, data, reason="suspected capability gap")

    _note(client, ledger.GAP_SUSPECTED, f"suspected gap: {title}", description,
          agent=agent, verification=ledger.INFERRED, gap_id=entity_id)
    return {**data, "id": entity_id}


def suspect_from_detector(client: dbaclient.DBAClient, *,
                          minimum_occurrences: int | None = None,
                          agent: str = identity.AGENT_ID) -> list[dict]:
    """Promote what `app/capability_gaps.py` has been recording into suspicions.

    Frequency is the detector's ranking rule and it is kept: a thing asked for
    once is noise, and the threshold is the detector's own rather than a second
    opinion invented here."""
    threshold = (detector.OFTEN_THRESHOLD if minimum_occurrences is None
                 else minimum_occurrences)
    raised = []
    for row in detector.ranked(detector.entries()):
        if row["count"] < threshold:
            continue
        raised.append(suspect(
            client,
            title=f"{row['gap_type']}: {row['what_was_needed']}"[:200],
            description=(f"Asked for {row['count']} time(s) between "
                         f"{row['first_seen']} and {row['last_seen']}. "
                         f"Outcome for Krish: "
                         f"{'; '.join(row['user_visible_outcomes']) or 'unrecorded'}"),
            detected_by="capability_gaps detector",
            evidence={"occurrences": row["count"],
                      "examples": row.get("examples") or [],
                      "first_seen": row.get("first_seen"),
                      "last_seen": row.get("last_seen")},
            affected_capability=row["gap_type"],
            frequency=row["count"], agent=agent))
    return raised


# --- §12: investigating, confirming, rejecting --------------------------------


def transition(client: dbaclient.DBAClient, gap: dict, to_state: str, *,
               evidence: str | list | dict | None = None,
               counter_evidence: str | list | dict | None = None,
               note: str = "", agent: str = identity.AGENT_ID) -> dict:
    """Move a gap, refusing a move the lifecycle does not allow."""
    was = gap.get("status") or SUSPECTED
    _check_state(to_state)
    if to_state not in TRANSITIONS.get(was, ()):
        raise IllegalTransition(
            f"a gap that is {was!r} cannot become {to_state!r}. From {was!r} "
            f"the allowed moves are: "
            f"{', '.join(TRANSITIONS.get(was, ())) or 'none - it is final'}.")

    changes: dict[str, Any] = {"status": to_state}
    if evidence is not None:
        changes["evidence"] = _merge_evidence(gap.get("evidence"), evidence)
    if counter_evidence is not None:
        changes["counter_evidence"] = _merge_evidence(
            gap.get("counter_evidence"), counter_evidence)
    if to_state in (RESOLVED, REJECTED, UNSUPPORTED):
        changes["resolved_at"] = _now()
    if note:
        changes["resolution"] = note

    client.update(gap["id"], changes, reason=f"{was} -> {to_state}")
    return {**gap, **changes}


def _merge_evidence(existing: Any, addition: Any) -> str:
    """Append, never replace.

    §12 says the evidence that caused a classification must be preserved, and
    a later investigation overwriting an earlier one is how a gap comes to be
    confirmed on grounds nobody can reconstruct."""
    parts = [part for part in (existing, _text(addition)) if part]
    return "\n---\n".join(str(part) for part in parts)


def investigate(client: dbaclient.DBAClient, gap: dict, *, question: str = "",
                agent: str = identity.AGENT_ID
                ) -> tuple[dict, inquiry.Inquiry]:
    """Move a gap into `investigating`, and open the inquiry that will do it.

    Returns the moved gap and an empty `Inquiry`. `settle` wants that inquiry
    back with a conclusion on it, and `Inquiry.conclude` refuses when the
    reasoning's shape does not support one - so the only way out of this state
    is through something that was actually reasoned about."""
    asked = question.strip() or (
        f"is {gap.get('name') or 'this'} a real capability gap, and if so what "
        f"is missing?")
    moved = transition(client, gap, INVESTIGATING,
                       note=f"investigating: {asked}", agent=agent)
    _note(client, ledger.STATE_TRANSITION,
          f"investigating gap: {gap.get('name')}", asked, agent=agent,
          verification=ledger.UNVERIFIED, gap_id=gap["id"])
    return moved, inquiry.Inquiry(asked, opened_by=agent)


# Prefixed onto the evidence when a conclusion was reached over a standing
# objection, so that the fact reaches the top of what Krish reads rather than
# sitting in a nested dictionary under `conclusion`.
OVERRIDDEN_WARNING = "REASONING OBJECTIONS OVERRIDDEN"


def settle(client: dbaclient.DBAClient, gap: dict, asking: inquiry.Inquiry, *,
           impact: str = "", remedy: str | None = None,
           agent: str = identity.AGENT_ID) -> dict:
    """Carry a concluded inquiry's outcome into the gap's lifecycle.

    The mapping is deliberately total and deliberately boring - there is one
    destination per outcome and no discretion in it, because discretion here is
    where a `inconclusive` quietly becomes a `confirmed`:

    | inquiry outcome | gap state |
    |---|---|
    | `confirmed` | `confirmed`, with the whole evidence bundle and a remedy |
    | `unsupported` | `unsupported` - looked properly, found nothing |
    | `inconclusive` | `deferred` - not answered, so not closed either |

    The gap's `confidence` is written from `Inquiry.confidence()`, which is
    derived from the record and cannot be set by anybody. §28 declared that
    field and nothing had ever written to it, so until now a gap's confidence
    was whatever a reader assumed - and the only number available to assume
    from would have been a model's estimate of its own certainty, which is the
    least reliable one in the system.

    An unconcluded inquiry is refused rather than defaulted, because every
    default available here is a lie about what was established."""
    if asking.conclusion is None:
        raise ValueError(
            "this inquiry has not concluded, so there is nothing to carry into "
            "the gap. If its shape will not support a conclusion, that is the "
            "finding: observe more, or conclude(accepting=[...]) naming what you "
            "are overriding.")

    said = asking.conclusion
    # Every check before every write. The remedy is only required for one of the
    # three outcomes, so it cannot be checked until the conclusion has been
    # read - but it is still checked before anything is written, or a caller who
    # forgot it would leave a confidence on a gap that never moved.
    if said.outcome == inquiry.CONFIRMED:
        if remedy is None:
            raise ValueError(
                "a confirmed inquiry closes the gap as confirmed, and §23 asks "
                f"which of {REMEDIES} applies before that. Passing no remedy "
                f"would let 'change the code' be the default by omission.")
        _check_remedy(remedy)

    # Serialised here rather than handed on as a dictionary, because the warning
    # below has to be the first line of what Krish reads and a dictionary cannot
    # promise that: `_text` dumps with `sort_keys=True`, so key order is thrown
    # away and a `WARNING` key would sort first only by the accident of being
    # capitalised. §13 takes a confirmed gap to Krish, and that its reasoning
    # was overridden is the most important thing on that page.
    bundle = _text(asking.evidence())
    if said.objections_overridden:
        bundle = (f"{OVERRIDDEN_WARNING}: "
                  f"{', '.join(said.objections_overridden)}. This conclusion "
                  f"was reached over standing objections to the shape of the "
                  f"reasoning behind it.\n\n{bundle}")

    # Written before the transition, so that a `confirm` which then fails still
    # leaves the number that was derived rather than a blank field beside a
    # half-moved gap.
    client.update(gap["id"], {"confidence": said.confidence},
                  reason="confidence derived from the investigation")
    gap = {**gap, "confidence": said.confidence}

    if said.outcome == inquiry.CONFIRMED:
        return confirm(client, gap, evidence=bundle,
                       impact=impact or said.reasoning or said.answer or "",
                       remedy=remedy, agent=agent)

    if said.outcome == inquiry.UNSUPPORTED:
        return transition(client, gap, UNSUPPORTED, evidence=bundle,
                          note=("investigated and found unsupported: "
                                + (said.reasoning or "nothing was found")),
                          agent=agent)

    return transition(client, gap, DEFERRED, evidence=bundle,
                      note=("investigation was inconclusive: "
                            + (said.reasoning or "no answer was established")),
                      agent=agent)


def confirm(client: dbaclient.DBAClient, gap: dict, *,
            evidence: str | list | dict, impact: str,
            remedy: str, agent: str = identity.AGENT_ID) -> dict:
    """Confirm a gap with evidence, and say which kind of remedy it needs.

    `evidence` is required and is checked for being non-empty. §12 lists
    deterministic tests, held-out tests, repeated failures, code inspection -
    all of them produce something to record, and a confirmation with nothing
    behind it is the exact thing §11 forbids."""
    if not _text(evidence).strip():
        raise ValueError(
            "confirming a gap needs evidence. §11: a perceived lack is not a "
            "confirmed lack, and a confirmation with nothing attached cannot "
            "be reviewed, argued with, or re-checked later.")
    _check_remedy(remedy)

    moved = transition(client, gap, CONFIRMED, evidence=evidence, agent=agent)
    client.update(gap["id"],
                  {"impact": impact,
                   "requires_code_change": remedy in NEEDS_CODE_CHANGE,
                   "alternative_remedies": _text(
                       [other for other in REMEDIES if other != remedy]),
                   "resolution": f"remedy: {remedy}"},
                  reason="gap confirmed with evidence")
    _note(client, ledger.GAP_CONFIRMED, f"confirmed gap: {gap.get('name')}",
          f"evidence: {_text(evidence)[:500]}", agent=agent,
          verification=ledger.VERIFIED, gap_id=gap["id"])
    return {**moved, "impact": impact,
            "requires_code_change": remedy in NEEDS_CODE_CHANGE,
            "resolution": f"remedy: {remedy}"}


def reject(client: dbaclient.DBAClient, gap: dict, *,
           counter_evidence: str | list | dict,
           agent: str = identity.AGENT_ID) -> dict:
    """Mark a suspicion unfounded, keeping the evidence against it.

    TEST F. The counter-evidence is required for the same reason the evidence
    is: a suspicion dismissed without a recorded reason comes back."""
    if not _text(counter_evidence).strip():
        raise ValueError(
            "rejecting a gap needs counter-evidence - the demonstration that "
            "the capability is in fact there. Without it the same suspicion "
            "returns next month with nothing to answer it.")
    moved = transition(client, gap, REJECTED, counter_evidence=counter_evidence,
                       note="rejected: the capability was demonstrated to work",
                       agent=agent)
    _note(client, ledger.GAP_REJECTED, f"rejected gap: {gap.get('name')}",
          f"counter-evidence: {_text(counter_evidence)[:500]}", agent=agent,
          verification=ledger.VERIFIED, gap_id=gap["id"])
    return moved


# --- §13: the approval gate ---------------------------------------------------


def ready_for_review(client: dbaclient.DBAClient, gap: dict) -> None:
    """Raise unless this gap may be taken to Krish for a code change.

    Called by `gateway/selfmod.py` before it will draft a proposal. It is a
    function rather than an `if` at the call site so that there is one place
    the rule lives and one place a test can point at."""
    status = gap.get("status")
    if status != CONFIRMED:
        raise NotConfirmed(
            f"{failures.GAP_UNCONFIRMED}: this gap is {status!r}, not "
            f"{CONFIRMED!r}. §13 - even a confirmed lack does not authorise a "
            f"change, and an unconfirmed one does not authorise a proposal.")
    if not _text(gap.get("evidence")).strip():
        raise NotConfirmed(
            f"{failures.GAP_UNCONFIRMED}: this gap is marked confirmed but "
            f"carries no evidence. Something set the status without going "
            f"through `confirm`.")


def needs_code_change(gap: dict) -> bool:
    value = gap.get("requires_code_change")
    return value is True or value == 1


# --- ledger -------------------------------------------------------------------


def _note(client: dbaclient.DBAClient, event_type: str, summary: str,
          observation: str, *, agent: str, verification: str,
          gap_id: str | None = None) -> str | None:
    """Record the lifecycle move in the life ledger; report failing to.

    The gap record is the state; the ledger is the history of how it got there,
    and §25 wants both. A ledger that is down must not stop a gap being
    confirmed - but it must not do so silently either, so the failure is
    written onto the gap's own evidence trail, where the next person to read
    the gap will find it. Returns the message, or `None` on success."""
    try:
        ledger.append(client, event_type=event_type, summary=summary,
                      observation=observation, actor="gap_governor",
                      verification_state=verification, agent=agent)
        return None
    except (ledger.LedgerWriteFailed, ledger.ChainBroken, ValueError) as exc:
        message = (f"[{failures.LEDGER_WRITE_FAILED}] this transition "
                   f"({event_type}) was not recorded in the life ledger: {exc}")
        if gap_id:
            try:
                existing = client.get(gap_id) or {}
                client.update(gap_id, {"evidence": _merge_evidence(
                    existing.get("evidence"), message)},
                    reason="ledger write failed during this transition")
            except (dbaclient.Refused, dbaclient.Unavailable):
                pass
        return message
