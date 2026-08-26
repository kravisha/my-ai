"""Can this be done without a model, and if not, is local enough?
(TASK_QUEUE TQ-59, docs/SPEC_RECONCILIATION.md §108).

Source: addendum 45 §2 (the execution hierarchy), §3 (two decisions), §16 (agent
self-assessment), §17 (the escalation decision has its own leaderboard),
§19 (deterministic-first), §24 (the flow), §36 (privacy), §45 Phase D.

## The first of two decisions, and they are not conflated

§3 is explicit that there are two, and that *"these decisions must not be
conflated"*:

1. **Can this be handled by deterministic logic or local intelligence?** — a
   capability and escalation decision. This module.
2. **Which model should handle it?** — a model-selection decision. TQ-60's.

So nothing here names a model, reads a leaderboard, or ranks anything. It answers
*which of the three execution paths this work belongs on*, and a test asserts it
cannot do more.

## §19 comes first, and it is not a formality

> *"AI should not be used merely because AI is available."*

The deterministic check runs before anything else, and it is a **declared
registry** rather than a judgement made per call. `DETERMINISTIC_CAPABILITIES`
lists what this system can already do without a model, each entry naming the code
that does it and why that code is reliable.

This is not aspirational. Every entry describes something already built and
already preferred over a model — `holdings.concentration` computes portfolio
weights because *"a model asked to percentage-weight a portfolio produces
something shaped like arithmetic"*; `agents/explorer.py` runs a deterministic
IV-surface detector and only then lets a model gate the candidate. The registry
writes down a discipline this project already practises, and
`test_every_declared_capability_points_at_code_that_exists` keeps it honest — a
registry claiming a deterministic solution that is not there would route work to
nothing.

**An unregistered operation is `unknown`, not `needs a model`.** §19 asks a
question a person answers at design time; this records the answers given, and
silence means nobody has asked yet. Treating silence as "use AI" would be exactly
the reflex §19 exists to interrupt.

## Privacy is not a tiebreaker

The case that matters most today, because it is live: a `LOCAL_ONLY` task, no
local model installed, and therefore **no way to do the work at all**.

That is not an escalation. §36 is unambiguous that sensitive data does not leave
because the external model is better, and it does not leave because the local one
is missing either. The honest answer is a refusal saying so, and
`PATH_REFUSED` exists to carry it rather than having this module quietly return
`external` and let something downstream notice.

Every model call on this machine goes to an external provider right now
(`local_ai.available()` is False), so any `LOCAL_ONLY` work that needs
intelligence is currently undoable. Saying that out loud is more useful than a
path that cannot be walked.

## The rules here are provisional, and §17 says so

§17: *"'Can this be done locally, or should we escalate?' is itself an
intelligent task"*, with its own leaderboard —
`CAPABILITY_AND_ESCALATION_DECISION`, seeded in §105 — and the model best at
making that call need not be the one best at the work.

So this module's rules are the **seed**, in the same sense §12 means it: a
hand-authored starting point that evidence should later overtake. They are
written down, tunable, and each carries its reason, so that when a model does
make this decision there is something to compare it against. `RULE_VERSION`
exists so a routing record can say which ruleset produced a decision.

What is *not* provisional is the privacy rule. That one is a constraint, not a
heuristic, and no evidence overturns it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app import local_ai
from app.task_signature import (COMPLEXITY_COMPLEX, COMPLEXITY_HIGH_STAKES,
                                COMPLEXITY_SPECIALIZED, ERROR_COST_HIGH,
                                JUDGEMENT_HIGH, PRIVACY_EXTERNAL_REQUIRED,
                                PRIVACY_LOCAL_ONLY, PRIVACY_LOCAL_PREFERRED,
                                TaskSignature)

# Bumped when the rules below change, so a routing record can say which ruleset
# produced its decision - and so a ranking gathered under one set is not silently
# compared against another.
RULE_VERSION = 1

# --- the paths this module chooses between ------------------------------------------
#
# The first three are `routing_decisions.EXECUTION_PATHS`, deliberately the same
# strings so a decision flows into the log without translation. The fourth is not
# a path at all.

PATH_DETERMINISTIC = "deterministic"
PATH_LOCAL = "local"
PATH_EXTERNAL = "external"

# Not an execution path: an answer that the work cannot be done. It exists so
# this module never has to return a path it knows cannot be walked - see the
# module docstring on privacy.
PATH_REFUSED = "refused"

DECISIONS = (PATH_DETERMINISTIC, PATH_LOCAL, PATH_EXTERNAL, PATH_REFUSED)


@dataclass(frozen=True)
class DeterministicCapability:
    """Something this system can do without a model, declared rather than
    inferred.

    `code_ref` is asserted against the filesystem by the tests, the same way
    `model_registry.yaml`'s profiles are: a registry that drifts is worse than no
    registry, because a router would believe it."""

    operation: str
    summary: str
    code_ref: str
    why_reliable: str


# What this system already does without a model. Each entry describes code that
# exists and is already preferred over asking a model - §19 written down rather
# than newly imposed.
DETERMINISTIC_CAPABILITIES: tuple[DeterministicCapability, ...] = (
    DeterministicCapability(
        operation="portfolio_concentration",
        summary="weights and concentration across a client's holdings, by stated cost",
        code_ref="backend/holdings.py::concentration",
        why_reliable=(
            "It is arithmetic over numbers the client supplied. A model asked to "
            "percentage-weight a portfolio produces something shaped like arithmetic, "
            "and somebody's money is the last place a plausible-looking number "
            "belongs (§96)."),
    ),
    DeterministicCapability(
        operation="iv_surface_detection",
        summary="peak IV over local baseline, per security, across the peer group",
        code_ref="agents/explorer.py",
        why_reliable=(
            "A threshold comparison on measured surface data. This is already §19 in "
            "practice: the deterministic detector produces the candidate and only "
            "then does a lightweight model gate it (addendum 7 §2)."),
    ),
    DeterministicCapability(
        operation="arbitrage_detection",
        summary="executable put-call parity and related arbitrage detectors (ARB-*)",
        code_ref="backend/arbitrage.py",
        why_reliable=(
            "Parity relationships are identities, not opinions. A detector either "
            "clears its cost model and hard stops or it does not, and a model's view "
            "of that would add nothing but doubt."),
    ),
    DeterministicCapability(
        operation="agent_slot_allocation",
        summary="which identity fills a role slot",
        code_ref="backend/fi_db.py::allocate_slot",
        why_reliable=(
            "A deterministic assignment, and deliberately so: two callers must reach "
            "the same answer for the same role or the population forks."),
    ),
)

_BY_OPERATION = {c.operation: c for c in DETERMINISTIC_CAPABILITIES}


@dataclass(frozen=True)
class CapabilityDecision:
    """§3's first decision, with its reasoning attached.

    Carries no model and no rank. `path` is what
    `routing_decisions.record_decision` takes as `execution_path`, and
    `deterministic_possible` / `local_sufficient` are §26's two fields — so a
    decision made here flows into the log without anything having to be
    re-derived or guessed at."""

    path: str
    reason: str
    deterministic_possible: bool
    local_sufficient: bool | None
    rule_version: int = RULE_VERSION
    capability: DeterministicCapability | None = None
    # True when this decision was forced by a constraint rather than chosen by a
    # heuristic. §36's privacy rule is the only such constraint today, and no
    # amount of leaderboard evidence overturns it.
    forced: bool = False

    def __post_init__(self) -> None:
        if self.path not in DECISIONS:
            raise ValueError(f"unknown decision {self.path!r}; known are {list(DECISIONS)}")
        if not (self.reason or "").strip():
            raise ValueError("a capability decision without a reason is not one")


def deterministic_capability_for(operation: str | None) -> DeterministicCapability | None:
    """The declared deterministic solution for this operation, or None.

    None means **nobody has recorded one**, which is not the same as "this needs
    a model". §19 asks a question a person answers at design time; this reports
    the answers given so far."""
    if not operation:
        return None
    return _BY_OPERATION.get(operation)


def decide(signature: TaskSignature, *, operation: str | None = None,
           local_available: bool | None = None) -> CapabilityDecision:
    """§24's flow, as far as §3's first decision goes.

    Deterministic check → privacy constraint → local sufficiency → escalate.
    Returns the path and the reasoning; **never a model** (§3, TQ-60).

    `local_available` is injected so a caller can ask "what would we decide if a
    local model existed" without one existing. Defaults to the truth."""
    available = local_ai.available() if local_available is None else local_available

    # 1. §19, first and unconditionally. AI is not used merely because AI is
    #    available, and the check that enforces that must not be reachable only
    #    after some other condition passed.
    capability = deterministic_capability_for(operation)
    if capability is not None:
        return CapabilityDecision(
            path=PATH_DETERMINISTIC,
            reason=(f"{capability.operation} has a deterministic solution "
                    f"({capability.code_ref}). {capability.why_reliable}"),
            deterministic_possible=True, local_sufficient=None,
            capability=capability)

    # 2. Privacy, before anything about capability. §36: sensitive work does not
    #    leave because the external model ranks higher - and it does not leave
    #    because the local one is missing either.
    if signature.privacy_level == PRIVACY_LOCAL_ONLY and not available:
        return CapabilityDecision(
            path=PATH_REFUSED,
            reason=("This task is LOCAL_ONLY and no local model is available, so it "
                    "cannot be done at all. Sending it to an external provider is not "
                    "a fallback - it is the thing LOCAL_ONLY forbids (§36). Local "
                    "intelligence arrives in TQ-57."),
            deterministic_possible=False, local_sufficient=False, forced=True)

    if signature.privacy_level == PRIVACY_LOCAL_ONLY:
        return CapabilityDecision(
            path=PATH_LOCAL,
            reason="LOCAL_ONLY: this work stays on the machine whatever the rankings say.",
            deterministic_possible=False, local_sufficient=True, forced=True)

    if signature.privacy_level == PRIVACY_EXTERNAL_REQUIRED:
        return CapabilityDecision(
            path=PATH_EXTERNAL,
            reason="EXTERNAL_REQUIRED: this work is designated for an external provider.",
            deterministic_possible=False, local_sufficient=False, forced=True)

    # 3. No local model, no choice to make. Said plainly rather than dressed up
    #    as a capability judgement - the reason matters, because it changes the
    #    day TQ-57 lands and a ranking gathered under it should not be read as
    #    evidence about local capability.
    if not available:
        return CapabilityDecision(
            path=PATH_EXTERNAL,
            reason=("No local model is installed, so there is nothing to be sufficient "
                    "(TQ-57). This is an availability fact, not a judgement about what "
                    "local intelligence could have handled."),
            deterministic_possible=False, local_sufficient=False)

    # 4. §16's self-assessment, as seeded rules. Provisional in §12's sense -
    #    written down so that when §17's leaderboard picks a model to make this
    #    call, there is something to compare it against.
    demanding = _too_demanding_for_local(signature)
    if demanding:
        return CapabilityDecision(
            path=PATH_EXTERNAL,
            reason=f"Escalating: {demanding} (ruleset v{RULE_VERSION}, provisional).",
            deterministic_possible=False, local_sufficient=False)

    return CapabilityDecision(
        path=PATH_LOCAL,
        reason=(f"Local intelligence is sufficient for this task "
                f"(ruleset v{RULE_VERSION}, provisional)."
                + (" LOCAL_PREFERRED reinforces it."
                   if signature.privacy_level == PRIVACY_LOCAL_PREFERRED else "")),
        deterministic_possible=False, local_sufficient=True)


def _too_demanding_for_local(signature: TaskSignature) -> str | None:
    """Why local intelligence would not be enough, or None.

    The seeded heuristic, and every clause is a hypothesis rather than a
    measurement (§12, §17). Each returns a *sentence*, because a decision that
    cannot explain itself is one nobody can later judge to have been wrong -
    which is the whole point of giving this its own leaderboard."""
    if signature.complexity in (COMPLEXITY_HIGH_STAKES,):
        return "the task is HIGH_STAKES, and no local model here has earned that yet"
    if signature.complexity in (COMPLEXITY_COMPLEX, COMPLEXITY_SPECIALIZED):
        if signature.error_cost == ERROR_COST_HIGH:
            return (f"{signature.complexity} work with a high error cost is where a "
                    "weaker model is most expensive to be wrong")
    if signature.error_cost == ERROR_COST_HIGH and signature.ambiguity == JUDGEMENT_HIGH:
        return ("high error cost with high ambiguity - the combination that most "
                "rewards a stronger model")
    if signature.tool_use_required:
        return ("the task needs tool use, which no local model here has been shown "
                "to do reliably")
    return None


def summary() -> dict:
    """What this system can do without a model, and what it would decide today.

    For an operator asking the §19 question directly - and honest about the fact
    that with no local model installed there is currently no local path at all."""
    available = local_ai.available()
    return {
        "rule_version": RULE_VERSION,
        "deterministic_operations": sorted(_BY_OPERATION),
        "local_available": available,
        "note": ("No local model is installed, so every task needing intelligence goes "
                 "external - and any LOCAL_ONLY task that needs it cannot be done at "
                 "all (§36). Local intelligence arrives in TQ-57."
                 if not available else
                 "Local intelligence is available; escalation is a judgement rather "
                 "than an availability fact."),
    }
