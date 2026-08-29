"""How much refinement a piece of work is owed before it is delivered.

The Iterative Excellence directive (owner, 2026-08-18) states the principle:
*explore broadly, treat the first coherent solution as raw material, refine where
refinement matters, stop at diminishing returns.* Its §10 says something sharper
than the principle itself:

> Claude, while implementing Jarvis, should therefore avoid implementing iterative
> excellence solely as a Claude prompt or a creative-agent behavior. It should
> become part of the broader organizational operating philosophy.

That rules out the easy implementation. A sentence in the Gateway's system prompt
would change how one assistant writes and nothing else; this module puts the
budget where every agent already reads its own definition, so an agent can state
what it owes a task without anybody having told it.

## The principle is universal, the budget is contextual

§5 is explicit that not every task deserves the same number of passes, and the
budgets below are read directly from it. What the directive gives as a list of
work kinds, this gives as a property of a role - because a role in this
organization *is* a kind of work, and an agent asking "how many passes do I owe
this" is really asking "what kind of work am I".

## Why the numbers are small, and honest about being conventions

A pass here is a deliberate re-examination, not a token of effort. The counts are
the directive's own ordering made concrete - conversational under routine under
analytical under architectural - and they are **conventions rather than
measurements**. Nothing has yet measured the quality gain from a second analysis
pass in this system, which is exactly what §8's stopping rule would need to be
enforceable rather than aspirational. `TIMING_CONSTANTS.md` exists because this
project distinguishes measured constants from assumed ones; these are assumed, and
this paragraph is the disclosure.

## What is deliberately not built

**Nothing here makes an agent iterate.** Analysis performs one deep call per
report today; giving it the "multiple evaluation and challenge passes" §5 assigns
to analytical work would multiply model spend per cycle and change what the
pipeline costs to run. That is a behavioural change with a price, and it belongs
to a decision rather than to a constant - filed on the Scoreboard instead of
smuggled in behind a policy module.

What this does is make the budget *stated*, *inheritable* and *queryable*, so the
change is a matter of honouring a declared standard rather than inventing one.
"""

# The directive's §5, as data. Each entry is a kind of work and what it owes.
WORK_KINDS = {
    "conversational": {
        "passes": 1,
        "stance": (
            "Answer once, well. Latency is part of the quality of a spoken reply, and a second "
            "pass the listener waits through is not an improvement to them."
        ),
    },
    "operational": {
        "passes": 1,
        "stance": (
            "Do the work and verify it happened. Refinement here means checking the outcome, "
            "not producing a better-phrased version of it."
        ),
    },
    "analytical": {
        "passes": 3,
        "stance": (
            "Reach a conclusion, then challenge it: what would make this wrong, what evidence is "
            "missing, what alternative reading fits the same facts. Deliver the conclusion that "
            "survived."
        ),
    },
    "architectural": {
        "passes": 4,
        "stance": (
            "Explore alternatives before choosing one, and say what was rejected and why. A design "
            "presented without its discarded alternatives is a first draft wearing a decision's "
            "clothes."
        ),
    },
    "high_risk": {
        "passes": 5,
        "stance": (
            "Independent challenge and evidence review before acting. The cost of another pass is "
            "always smaller than the cost of the failure it was meant to catch."
        ),
    },
}

# Which kind of work each role does. A role is a kind of work in this
# organization, so an agent asking what it owes a task is asking what it is.
ROLE_WORK_KIND = {
    "controller": "operational",
    "coo": "operational",
    "dummy": "operational",
    "explorer": "operational",
    "speculator": "operational",
    "analysis": "analytical",
    # Reporting is operational: look, and verify that what you filed is what you
    # found. Deliberately not "analytical" - the Speaker's value is that somebody
    # whose job it is looked, not that it reached a conclusion about what it saw.
    # A spokesperson given an analytical budget starts interpreting the body it
    # speaks for.
    "speaker": "operational",
    # Architectural, and the fit is exact: §8's ladder IS "explore alternatives
    # before choosing one, and say what was rejected and why". An engineer that
    # reported a data solution without having considered whether the mechanism
    # exists would be the first-draft-wearing-a-decision's-clothes this budget
    # names.
    "software_engineer": "architectural",
    # Operational, deliberately, and NOT analytical. The DBA runs the same
    # checks every cycle and reports what they found; interpreting a finding is
    # the three-way review's job (addendum 53 §2), and a DBA given an analytical
    # budget would reach a conclusion before the other two perspectives exist -
    # which is the silo §2 forbids, arriving through a budget.
    "dba": "operational",
    # Architectural, for the same reason the engineer's is: §5.3 asks QA to
    # establish what test data would trigger a failure and whether the tripwire
    # has been observed failing. That is exploring alternatives and saying what
    # was rejected, not executing a checklist.
    "qa_engineer": "architectural",
}

# What the Gateway's assistant does. Not a role in agent_registry - it is the
# conversational surface - but it is subject to the same principle, and its budget
# depends on what is being asked rather than on what it is.
GATEWAY_DEFAULT_KIND = "conversational"

# §8's stopping rule, in the words a working agent needs rather than the words a
# principle is stated in.
STOPPING_RULE = (
    "Stop when the result meets the required threshold, when the remaining weaknesses are "
    "immaterial, or when another pass would produce negligible gain. Both premature stopping and "
    "pointless perfectionism are failures; the second is more expensive and easier to mistake for "
    "diligence."
)

# §7's two thresholds. Named because "good enough" is a judgment somebody has to
# make out loud, and a threshold nobody stated is one nobody can be held to.
THRESHOLDS = {
    "acceptable": "safe, correct, useful, and fit for purpose",
    "exceptional": "substantially refined, robust, elegant, or insightful beyond the merely acceptable",
}


class IterationError(ValueError):
    pass


def work_kind_for(role: str) -> str:
    """What kind of work this role does. Unknown roles are operational, which is
    the conservative answer: it promises the least and cannot inflate a budget for
    a role nobody has classified."""
    return ROLE_WORK_KIND.get(role, "operational")


def budget_for(role: str) -> dict:
    """The iteration budget a role owes its work, as a charter fragment.

    Returned as a dict rather than an int because a number without its stance is
    a quota, and the directive is explicit that the point is not maximum
    computation - §3's "improve selectively" and §8's stopping rule are as much
    the principle as the count is."""
    kind = work_kind_for(role)
    spec = WORK_KINDS[kind]
    return {
        "work_kind": kind,
        "passes": spec["passes"],
        "stance": spec["stance"],
        "stopping_rule": STOPPING_RULE,
        "measured": False,
    }


def stance_for_kind(kind: str) -> str:
    if kind not in WORK_KINDS:
        raise IterationError(
            f"unknown work kind {kind!r}; this organization recognises {', '.join(sorted(WORK_KINDS))}"
        )
    return WORK_KINDS[kind]["stance"]
