"""When Jarvis acts without being asked, and where that stops (Krish, 2026-09-21).

> *"Please make the agent a bit of a risk taker and being bold and preemptive
> but always following the do no harm doctrine and pay even more care if the
> action is irreversible."*

## The finding that shaped this module

**There was no do-no-harm doctrine to follow.** The phrase appears nowhere in
`AI-CONSTITUTION.md`, `docs/GOVERNANCE.md`, or any module in this repository.
What exists is one paragraph, in one addendum, scoped to one subsystem -
`docs/addenda/addendum_28_security_defense_framework.md` §1.8:

> *Security automation MAY act automatically where the action is reversible,
> bounded, and covered by explicit policy. Irreversible, destructive, or
> unusually broad actions SHALL require stronger evidence and, where practical,
> independent approval.*

That is exactly the instruction, written a month earlier, applied only to
security automation and enforced nowhere. So raising boldness first would have
been raising it against a rule that did not exist. `docs/INITIATIVE.md`
generalises §1.8 into a doctrine for every action this system takes, and this
module is that doctrine as code.

The ordering is the same one Task 01 used and for the same reason: instrument
before you repair, write the rule before you relax the caution that was standing
in for it.

## The dial has a floor, and the floor is not on the dial

`config/initiative.yaml` carries a `boldness` setting, and Krish asked for it to
be turned up. It moves exactly one thing: **how far up the reach ladder a
REVERSIBLE or RECOVERABLE action may go without asking.**

It cannot move an IRREVERSIBLE action, at any setting, ever. It cannot move
anything in `HARMS`. Those are not clamped by validation that a future edit
could loosen - `decide()` checks them before it reads the boldness at all, and
`test_initiative.py` asserts that every setting in `BOLDNESS_LEVELS`, including
ones nobody has defined yet, produces the same answer for an irreversible public
act.

This is `app/model_routing.assert_no_anthropic`'s shape, and the reasoning is
Krish's own from 2026-09-16: a switch that can be turned on can be turned on by
accident, by a stale config, by a copied deployment, by a test that forgets to
clear it. A dial whose top setting is still safe is a dial you can hand to
somebody.

## Boldness is not recklessness, and the difference is recorded

The bold direction here is **act, then say what you did** - not *act, and let
him find out*. Every disposition that permits acting without asking also
requires the act to be visible: `ACT_AND_REPORT` says so in the name, and a
preemptive act (one taken with nobody in the conversation) must be written to
the capability record or the brief, because **an unrecorded autonomous action is
indistinguishable from a bug.** `may_preempt` enforces that by refusing to
authorise a preemptive action that has no way to be reported.

## Why two axes and not a single risk score

A single number would let a very reversible action with enormous reach average
out with a tiny irreversible one, and those are not the same and must not trade
against each other. Reversibility answers *can this be taken back*; reach
answers *who has already seen it*. An action that is reversible here but was
read by someone else in the meantime is not reversible in the sense that
matters, which is why `PUBLIC` is a hard stop rather than a high score.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- axis 1: can it be taken back ---------------------------------------------

REVERSIBLE = "reversible"
RECOVERABLE = "recoverable"
IRREVERSIBLE = "irreversible"
REVERSIBILITY = (REVERSIBLE, RECOVERABLE, IRREVERSIBLE)

# THE LINE IS CORRECTABILITY, NOT LITERAL UNDO, and finding that out cost a
# design mistake worth recording. The first version of this module defined
# IRREVERSIBLE as "cannot be undone", which put `message_claude` - Jarvis
# telling the engineer session on his own machine that something is broken -
# behind a request for permission. He does that unprompted today, on purpose,
# and it is one of the better things he does. By "cannot literally be undone"
# every sentence anybody says is irreversible, and an assistant reasoning that
# way asks permission to speak.
#
# What actually matters is whether a later action of this system can reach
# everyone the first one reached. A message to a peer can be followed by
# "ignore that" to the same peer. A public push cannot, because whoever cloned
# it in the meantime is not enumerable. That is the difference care is owed to.
REVERSIBILITY_MEANING = {
    REVERSIBLE: (
        "undone by one ordinary operation, leaving nothing behind that anybody "
        "would have to be told about"),
    RECOVERABLE: (
        "cannot be undone, but can be *corrected* - a revert, a restore, or a "
        "follow-up that reaches everyone the first one reached - so the cost of "
        "being wrong is an awkward correction"),
    IRREVERSIBLE: (
        "cannot be corrected, because the material is gone or the audience is "
        "not enumerable: published where it can be copied, sent where it can be "
        "forwarded, or deleted with no other copy"),
}

# --- axis 2: where the effect lands -------------------------------------------
#
# Ordered, and the order is load-bearing: `_RANK` below compares against the
# boldness ceiling. Inserting a rung means deciding where it sits relative to
# PEER, which is the point at which somebody else has seen what happened.

SELF = "self"
SYSTEM = "system"
OWNER = "owner"
PEER = "peer"
PUBLIC = "public"
REACH = (SELF, SYSTEM, OWNER, PEER, PUBLIC)

REACH_MEANING = {
    SELF: "this turn and this process; nothing durable changes",
    SYSTEM: "durable state on this machine that only this system reads",
    OWNER: "something Krish will see, decide on, or act from",
    PEER: "another agent or machine that is already part of this system",
    PUBLIC: "outside the system entirely - another person, a public place, the internet",
}

_RANK = {name: position for position, name in enumerate(REACH)}

# --- what may be done about it ------------------------------------------------

ACT = "act"
ACT_AND_REPORT = "act_and_report"
PROPOSE = "propose"
REFUSE = "refuse"
DISPOSITIONS = (ACT, ACT_AND_REPORT, PROPOSE, REFUSE)

DISPOSITION_MEANING = {
    ACT: "do it now without asking, and mention it if it is relevant",
    ACT_AND_REPORT: "do it now without asking, and say plainly that you did",
    PROPOSE: ("do not do it; say exactly what you would do, what it would cost "
              "if wrong, and ask"),
    REFUSE: "do not do it and do not offer to",
}

# --- the harm floor -----------------------------------------------------------
#
# Refused at every boldness, whatever the reversibility, whoever asked. These
# are not "high risk" - they are the things that make the rest of the system
# unable to correct itself, which is what separates a mistake from a harm.
#
# Each is named rather than described by a rule, because a rule general enough
# to derive them would be general enough to be argued around, and this is the
# list that must not be arguable.

HARM_DESTROYS_ONLY_COPY = "destroys_only_copy"
HARM_ERASES_ITS_OWN_RECORD = "erases_its_own_record"
HARM_WIDENS_ITS_OWN_AUTHORITY = "widens_its_own_authority"
HARM_ACTS_FOR_ANOTHER_PERSON = "acts_for_another_person"
HARM_MISREPRESENTS_WHAT_IT_DID = "misrepresents_what_it_did"

HARMS = {
    HARM_DESTROYS_ONLY_COPY: (
        "destroy the only copy of something",
        "Deletion with a backup is recoverable and is an ordinary risk. "
        "Deletion without one removes the possibility of correction, which is "
        "the property every other rule here depends on."),
    HARM_ERASES_ITS_OWN_RECORD: (
        "erase, edit or suppress its own record of what it did",
        "Addendum 28 §1.9: \"No agent, including security leadership agents, "
        "SHALL be able to erase its own audit trail.\" An agent that can edit "
        "the record of what it did cannot be held to any of this, and every "
        "permission in this file was granted on the assumption that it can."),
    HARM_WIDENS_ITS_OWN_AUTHORITY: (
        "grant itself authority it was not given",
        "Adding a capability, raising its own boldness, or editing the policy "
        "that bounds it. The dial is Krish's. An agent that can turn its own "
        "dial has no dial."),
    HARM_ACTS_FOR_ANOTHER_PERSON: (
        "act as, or on the data of, somebody other than the person it is "
        "speaking with",
        "gateway/tools.execute already takes the subject from the session and "
        "never from an argument the model supplied. This states the same rule "
        "where a reader will look for it, and extends it to actions that have "
        "no tool yet."),
    HARM_MISREPRESENTS_WHAT_IT_DID: (
        "report an action it did not take, omit one it did, or call a failure a "
        "success",
        "Boldness is only safe because the record is true. This is the harm "
        "that would make every other permission in this file a bad idea, which "
        "is why it is on the floor rather than in the prompt."),
    }


def harm_phrase(harm: str) -> str:
    return HARMS[harm][0]


def harm_reason(harm: str) -> str:
    return HARMS[harm][1]


# --- the dial -----------------------------------------------------------------
#
# `ceiling` is the furthest up the reach ladder a non-irreversible action may go
# without asking. Nothing here mentions IRREVERSIBLE, because no setting may
# reach it - see the module docstring and `decide`.

BOLDNESS_LEVELS = {
    "cautious": {
        "ceiling": SYSTEM,
        "preemption": False,
        "describes": ("acts alone only where nothing leaves this machine, and "
                      "never starts work unprompted"),
    },
    "standard": {
        "ceiling": OWNER,
        "preemption": False,
        "describes": ("acts alone on anything Krish will see and can undo, and "
                      "waits to be asked before starting"),
    },
    "bold": {
        "ceiling": PEER,
        "preemption": True,
        "describes": ("acts alone up to and including telling another agent in "
                      "this system, and may start useful work unprompted where "
                      "it is reversible"),
    },
}

DEFAULT_BOLDNESS = "bold"


class InitiativeError(ValueError):
    """A proposed action could not be classified, so it is not run.

    Refused rather than defaulted, and defaulted-to-refuse would be worse, not
    better: an action nobody classified is an action nobody thought about, and
    the fix is to classify it rather than to let it through under a cautious
    label that hides the omission."""


@dataclass(frozen=True)
class Action:
    """One thing Jarvis might do, described in the terms the policy reads.

    `harms` is a tuple rather than a boolean because the refusal has to say
    *which* harm, and a caller that lists two has told the reader something a
    single flag would have thrown away."""

    name: str
    reversibility: str
    reach: str
    summary: str = ""
    harms: tuple[str, ...] = ()
    # Whether an act taken without being asked can be surfaced afterwards. A
    # preemptive action with no way to be reported is refused preemption - see
    # `may_preempt`.
    reportable: bool = True

    def __post_init__(self) -> None:
        if self.reversibility not in REVERSIBILITY:
            raise InitiativeError(
                f"{self.name}: reversibility={self.reversibility!r} is not one of "
                f"{REVERSIBILITY}")
        if self.reach not in REACH:
            raise InitiativeError(
                f"{self.name}: reach={self.reach!r} is not one of {REACH}")
        unknown = [harm for harm in self.harms if harm not in HARMS]
        if unknown:
            raise InitiativeError(
                f"{self.name}: unknown harm(s) {unknown}. The harm list is closed "
                f"on purpose - a free-form harm is one nothing can test for.")


@dataclass(frozen=True)
class Verdict:
    """What to do, and the sentence explaining it.

    `reason` is not decoration. It is what the assistant says to Krish when the
    answer is PROPOSE, and a refusal he cannot argue with is a refusal he will
    route around."""

    disposition: str
    reason: str
    action: Action
    boldness: str

    @property
    def may_act(self) -> bool:
        return self.disposition in (ACT, ACT_AND_REPORT)

    @property
    def must_report(self) -> bool:
        return self.disposition == ACT_AND_REPORT


def boldness() -> str:
    """The configured setting, from `config/initiative.yaml`.

    Read through `app/router_config`-style lazy config rather than at import,
    so a test can set it and so an edit takes effect without a restart."""
    from app import initiative_config

    return initiative_config.boldness()


def decide(action: Action, *, level: str | None = None) -> Verdict:
    """The whole policy, in the order the order matters.

    Harm, then irreversibility, then the dial. Reading the dial first would let
    a future edit that mishandles a boldness value reach a harm check it never
    ran - so the two things that must never be configurable are settled before
    the configurable thing is even loaded."""
    setting = level or boldness()

    # 1. HARM. Before anything else, and before the config is read at all.
    if action.harms:
        named = ", and would ".join(harm_phrase(harm) for harm in action.harms)
        return Verdict(
            REFUSE,
            f"This would {named}. {harm_reason(action.harms[0])} Refused at every "
            f"boldness setting - the dial does not reach this, and raising it "
            f"will not change the answer.",
            action, setting)

    # 2. IRREVERSIBILITY. Also before the dial: Krish's instruction was to pay
    # *more* care here, not to let boldness buy it back.
    if action.reversibility == IRREVERSIBLE:
        return Verdict(
            PROPOSE,
            f"There is no correcting this afterwards: it "
            f"{REVERSIBILITY_MEANING[IRREVERSIBLE]}. Irreversible actions are "
            f"proposed and never taken unasked, at every boldness setting "
            f"including ones nobody has invented yet. Say exactly what it would "
            f"do and what it costs if the judgement is wrong, and let him decide.",
            action, setting)

    # 3. The dial, which only ever governs reach for things that can be undone.
    policy = BOLDNESS_LEVELS.get(setting)
    if policy is None:
        raise InitiativeError(
            f"boldness={setting!r} is not one of {sorted(BOLDNESS_LEVELS)}. "
            f"Refusing rather than picking a neighbour: a typo must not become "
            f"a different policy.")

    if _RANK[action.reach] > _RANK[policy["ceiling"]]:
        return Verdict(
            PROPOSE,
            f"This reaches {action.reach} ({REACH_MEANING[action.reach]}), and at "
            f"boldness '{setting}' I act alone up to {policy['ceiling']}. It is "
            f"{action.reversibility}, so it is a question of who sees it rather "
            f"than whether it can be undone - propose it and it can go ahead.",
            action, setting)

    if action.reversibility == RECOVERABLE or _RANK[action.reach] >= _RANK[OWNER]:
        return Verdict(
            ACT_AND_REPORT,
            f"{action.reversibility.capitalize()} and reaching {action.reach}: do "
            f"it now, and say plainly that you did. Acting without asking is only "
            f"safe because the record is true.",
            action, setting)

    return Verdict(
        ACT,
        f"Reversible and reaching no further than {action.reach}. Do it rather "
        f"than asking whether to - a question about something you could simply "
        f"undo costs more than the action.",
        action, setting)


def may_preempt(action: Action, *, level: str | None = None) -> Verdict:
    """Whether this may be done with nobody having asked for it.

    Stricter than `decide` on two counts, and both are the same worry from
    different sides:

    - **Reversible only.** A recoverable action taken unprompted means Krish
      discovers a change he did not ask for and has to work out how to undo it.
      That is a worse experience than the work not having been done.
    - **Reportable only.** An autonomous act nobody can see is indistinguishable
      from a bug, and the first time one goes wrong it will be diagnosed as one.
      `app/self_diagnosis.py` and the morning brief are the places these
      surface; an action with no route to either does not get to happen alone.
    """
    setting = level or boldness()
    policy = BOLDNESS_LEVELS.get(setting)
    if policy is None:
        raise InitiativeError(
            f"boldness={setting!r} is not one of {sorted(BOLDNESS_LEVELS)}.")

    verdict = decide(action, level=setting)
    if not verdict.may_act:
        return verdict

    if not policy["preemption"]:
        return Verdict(
            PROPOSE,
            f"Boldness '{setting}' does not start work unprompted. Raise it to a "
            f"setting that does, or wait to be asked.",
            action, setting)

    if action.reversibility != REVERSIBLE:
        return Verdict(
            PROPOSE,
            f"Unprompted work is reversible work. This is {action.reversibility}, "
            f"so doing it unasked would leave Krish to discover a change he did "
            f"not request and work out how to undo it - which costs him more than "
            f"the work saves him.",
            action, setting)

    if not action.reportable:
        return Verdict(
            PROPOSE,
            "There is no way to tell anybody this happened. An autonomous action "
            "nobody can see is indistinguishable from a bug, and will be "
            "diagnosed as one the first time it goes wrong.",
            action, setting)

    return Verdict(
        ACT_AND_REPORT,
        "Reversible, bounded and reportable: go ahead without being asked, and "
        "put it where it will be seen.",
        action, setting)


def describe(level: str | None = None) -> dict:
    """The policy as data, for the status surface and for the prompt.

    Exists so "how bold is this thing configured to be" is answerable without
    reading code, which is the same reason `LocalFirstRouter.describe` exists."""
    setting = level or boldness()
    policy = BOLDNESS_LEVELS.get(setting, {})
    return {
        "boldness": setting,
        "ceiling": policy.get("ceiling"),
        "preemption": policy.get("preemption"),
        "describes": policy.get("describes"),
        "floors": {
            "irreversible": "proposed, never taken unasked, at any setting",
            "harms": sorted(HARMS),
        },
        "levels": sorted(BOLDNESS_LEVELS),
        "documented_in": "docs/INITIATIVE.md",
    }
