"""How much refinement a piece of work is owed, and where that lives.

The Iterative Excellence directive's §10 is the requirement these tests exist for:
it must not be implemented "solely as a Claude prompt or a creative-agent
behavior". A sentence in one system prompt would satisfy the principle and fail
the directive, so what is asserted here is that the budget is a property of the
organization - inheritable, queryable, and attached to roles rather than to
whoever happens to be writing.
"""

import pytest

from backend import fi_db, iteration


def test_every_role_that_exists_has_a_declared_budget():
    """A role with no budget would silently fall to the conservative default and
    nobody would notice it had never been classified."""
    from agents import coo as coo_module

    live_roles = set(coo_module.BASELINE_ROLES) | {"coo", "controller"}

    unclassified = live_roles - set(iteration.ROLE_WORK_KIND)
    assert unclassified == set(), f"roles with no declared work kind: {sorted(unclassified)}"


def test_the_budget_follows_the_directive_s_own_ordering():
    """§5 orders the kinds: conversational under routine under analytical under
    architectural under high-risk. The numbers are conventions, but the ordering
    is the directive's and must not be reversed by a careless edit."""
    passes = {kind: spec["passes"] for kind, spec in iteration.WORK_KINDS.items()}

    assert passes["conversational"] <= passes["operational"] < passes["analytical"]
    assert passes["analytical"] < passes["architectural"] < passes["high_risk"]


def test_judgment_work_is_owed_more_than_routine_work():
    """The one distinction with a consequence in this organization today: Analysis
    reasons, Explorer detects."""
    assert iteration.work_kind_for("analysis") == "analytical"
    assert iteration.work_kind_for("explorer") == "operational"
    assert iteration.budget_for("analysis")["passes"] > iteration.budget_for("explorer")["passes"]


def test_an_unclassified_role_gets_the_conservative_answer():
    """Operational promises the least, so an unknown role cannot inflate its own
    budget by being unknown."""
    assert iteration.work_kind_for("some-future-role") == "operational"


def test_the_budget_carries_its_stance_not_just_a_number():
    """A count without its reasoning is a quota, and the directive is explicit
    that the goal is not maximum computation."""
    budget = iteration.budget_for("analysis")

    assert budget["passes"] == 3
    assert budget["stance"].strip()
    assert "negligible gain" in budget["stopping_rule"], "§8's stopping rule travels with it"


def test_the_budget_is_declared_as_unmeasured():
    """TIMING_CONSTANTS.md exists because this project separates measured
    constants from assumed ones. Nothing has measured the quality gain from a
    second analysis pass, and the record says so rather than implying otherwise."""
    assert iteration.budget_for("analysis")["measured"] is False


def test_an_agent_can_state_its_own_standard(conn):
    """§10's "agents inherit it by default", asked of the mechanism that answers
    an agent's questions about itself. If the UQI can report it, the budget is
    organizational rather than a habit of whoever wrote a prompt."""
    fi_db.register_agent(conn, "analysis-1", "analysis", 4242)

    description = fi_db.describe_agent(conn, "analysis-1")

    assert description["iteration"]["work_kind"] == "analytical"
    assert description["iteration"]["passes"] == 3
    assert description["iteration"]["stance"]


def test_the_gateway_assistant_is_told_the_same_thing_the_agents_are():
    """The conversational surface is subject to the principle too - and gets the
    small budget, because latency is part of the quality of a spoken reply."""
    from gateway.conversation import SYSTEM_PROMPT

    assert "one good answer" in SYSTEM_PROMPT
    assert "discarded alternatives" in SYSTEM_PROMPT, (
        "design work through the Gateway is not conversational work and must not inherit its budget"
    )
    assert iteration.GATEWAY_DEFAULT_KIND == "conversational"


def test_an_unknown_work_kind_is_refused_rather_than_defaulted():
    with pytest.raises(iteration.IterationError, match="unknown work kind"):
        iteration.stance_for_kind("vibes")


def test_the_thresholds_are_named():
    """§7 asks for two conceptual thresholds. A threshold nobody stated is one
    nobody can be held to."""
    assert set(iteration.THRESHOLDS) == {"acceptable", "exceptional"}
