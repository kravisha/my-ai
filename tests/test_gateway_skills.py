"""What the client's agent can do, and what it says when it cannot
(gateway/skills.py + gateway/conversation.py; owner direction 2026-08-25;
TQ-40, SPEC_RECONCILIATION §95).

Two things are held here.

**Scope.** The reason portfolio analysis cannot ship turned out not to be the
expected one — there *is* a portfolio producer, and it reads one file that
belongs to the operator. Wiring it to a Gateway client would hand an external
person somebody else's holdings: §93's leak arriving by a different route and
wearing a feature's clothes. So every skill declares whose data it touches, and
a skill a client can invoke must be subject-scoped. That is checked at import,
because a registry mistake is a permissions mistake.

**Honesty about the unbuilt.** "I am not allowed to" and "that does not exist
yet" are different answers, and an agent with no registry gives neither — it
improvises. Every unbuilt skill carries a specific reason, and the agent's own
prompt is generated from the registry so what it claims and what the Gateway
permits cannot drift.
"""

import pytest

from gateway import conversation, roles, skills


# --- the invariant worth the file ------------------------------------------------


def test_no_skill_a_client_can_invoke_reads_organization_data():
    """The line that stops portfolio analysis from being wired to the operator's
    holdings by somebody acting in good faith."""
    for skill in skills.for_role(roles.ROLE_CLIENT):
        assert skill.scope == skills.SCOPE_SUBJECT, (
            f"{skill.name!r} is reachable by a client but reads {skill.scope} data"
        )


def test_the_registry_refuses_a_client_reachable_organization_skill():
    """Asserted by construction rather than by inspection: the validator is what
    runs at import, so this proves the guard fires rather than that today's
    registry happens to be clean."""
    import dataclasses

    bad = dataclasses.replace(
        skills.SKILLS[0], name="leaky", scope=skills.SCOPE_ORGANIZATION)
    with pytest.raises(skills.ScopeViolation, match="leaky"):
        _validate_with(bad)


def _validate_with(*extra):
    """Run the registry validator over a substituted set."""
    import unittest.mock

    with unittest.mock.patch.object(skills, "SKILLS", tuple(extra)):
        skills._validate()


def test_an_unknown_scope_is_refused(monkeypatch):
    """Fail closed: an unrecognised scope cannot be checked, and a check that
    cannot run is worse than no check because it looks like one."""
    import dataclasses

    with pytest.raises(skills.UnknownScope):
        _validate_with(dataclasses.replace(skills.SKILLS[0], scope="whatever"))


def test_an_unbuilt_skill_must_say_why(monkeypatch):
    """"Not implemented" tells a client nothing they can act on."""
    import dataclasses

    with pytest.raises(ValueError, match="without a reason"):
        _validate_with(dataclasses.replace(
            skills.SKILLS[0], status=skills.STATUS_UNBUILT, blocked_reason=""))


def test_a_skill_cannot_require_a_capability_that_does_not_exist():
    import dataclasses

    with pytest.raises(roles.UnknownCapability):
        _validate_with(dataclasses.replace(skills.SKILLS[0], capability="magic"))


def test_duplicate_skills_are_refused():
    with pytest.raises(ValueError, match="duplicate"):
        _validate_with(skills.SKILLS[0], skills.SKILLS[0])


# --- what a client actually has today ----------------------------------------------


def test_a_client_can_converse_and_keep_its_own_holdings():
    """This asserted `== {"conversation"}` under the owner's "initially this will
    be limited to giving info". TQ-41 delivered the first real skill, so the
    assertion moves - and the thing it was protecting is now held by
    `test_no_skill_a_client_can_invoke_reads_organization_data` above, which is
    the invariant rather than the snapshot."""
    available = {s.name for s in skills.available_for(roles.ROLE_CLIENT)}
    assert available == {"conversation", "portfolio_analysis"}


def test_what_is_still_unbuilt_is_declared_rather_than_absent():
    """Declared rather than absent, so the agent answers the question a client
    will actually ask instead of improvising.

    `portfolio_analysis` left this set when TQ-41 built it, and
    `portfolio_valuation` joined it - which is the more precise blocker that
    building the first one exposed: holdings can be weighted by what somebody
    paid without any price at all, but they cannot be valued."""
    unbuilt = {s.name for s in skills.unbuilt_for(roles.ROLE_CLIENT)}
    assert unbuilt == {"portfolio_valuation", "trade_ideas"}


def test_the_valuation_reason_names_the_real_blocker():
    """Not "not implemented". Weighting holdings needs only what the client
    paid; valuing them needs a price this system does not have, and that
    distinction is what the client is told."""
    reason = next(s for s in skills.SKILLS if s.name == "portfolio_valuation").blocked_reason
    assert "simulated" in reason.lower()
    assert "price" in reason.lower()


def test_the_built_skill_carries_no_blocked_reason():
    """A skill that is available and still explaining why it is not would be
    telling a client two contradictory things."""
    built = next(s for s in skills.SKILLS if s.name == "portfolio_analysis")
    assert built.status == skills.STATUS_AVAILABLE
    assert built.blocked_reason is None


def test_the_trade_ideas_reason_names_the_simulation():
    """Addendum 25's rule, and the finance desk's: simulated output must never
    be presented as real. A trade suggestion is the most dangerous place in this
    system to blur that."""
    reason = next(s for s in skills.SKILLS if s.name == "trade_ideas").blocked_reason
    assert "simulated" in reason.lower()


def test_an_operator_is_not_offered_the_client_agent_s_unbuilt_skills_as_available():
    """Both unbuilt skills are gated on `converse`, which every role holds - so
    this asserts that "unbuilt" wins over "permitted" for everybody, not just
    for clients."""
    for role in roles.ROLES:
        assert not any(s.status == skills.STATUS_UNBUILT
                       for s in skills.available_for(role))


# --- the prompt is generated, not written -------------------------------------------


def test_the_client_prompt_names_the_agent():
    prompt = conversation.client_prompt("Nadim", roles.ROLE_CLIENT)
    assert prompt.count("Nadim") >= 2


def test_the_client_prompt_states_what_cannot_be_done_and_why():
    """The behaviour this whole entry delivers: asked for something unbuilt, the
    agent has a true answer to give instead of a plausible one."""
    prompt = conversation.client_prompt("Nadim", roles.ROLE_CLIENT)
    for skill in skills.unbuilt_for(roles.ROLE_CLIENT):
        assert skill.blocked_reason in prompt


def test_the_client_prompt_forbids_advice_and_invention():
    prompt = conversation.client_prompt("Nadim", roles.ROLE_CLIENT).lower()
    assert "not financial advice" in prompt or "financial advice" in prompt
    assert "never invent" in prompt


def test_the_client_prompt_is_not_the_super_user_s():
    """The mismatch this fixed. Every session was handed a prompt opening "You
    are the analysis and specification assistant for Project Jarvis, speaking
    with the project's Super User" - so a client who met Nadim was talking to an
    architecture assistant that believed they owned the project. The socket's
    introduction and the model's instructions disagreed, and the model followed
    the instructions."""
    client = conversation.client_prompt("Nadim", roles.ROLE_CLIENT)
    assert "Super User" not in client
    assert "Project Jarvis" not in client
    assert "specification assistant" not in client
    # And the operator's prompt is untouched.
    assert "Super User" in conversation.SYSTEM_PROMPT


def test_the_turn_picks_the_prompt_by_role():
    """Asserted at the source: one prompt for both roles is how the mismatch
    happened, and a test on the strings alone would not notice it returning."""
    import inspect

    source = inspect.getsource(conversation.run_turn)
    assert "ROLE_CLIENT" in source
    assert "client_prompt" in source
    assert "SYSTEM_PROMPT" in source


def test_the_capability_paragraph_comes_from_the_registry():
    """Generated rather than written, so what the agent claims about itself and
    what the Gateway permits cannot drift. A hand-written list of abilities is a
    second source of truth about permissions and would be wrong within one
    increment."""
    paragraph = skills.capability_paragraph(roles.ROLE_CLIENT)
    for skill in skills.available_for(roles.ROLE_CLIENT):
        assert skill.summary in paragraph


def test_describe_separates_the_two_kinds_of_no():
    described = skills.describe(roles.ROLE_CLIENT)
    assert [s["name"] for s in described["available"]] == [
        "conversation", "portfolio_analysis"]
    assert all(s["reason"] for s in described["unbuilt"])
