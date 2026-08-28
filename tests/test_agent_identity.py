"""Persistent agent identity (TQ-97; addendum 51 §2, §3, §5, §6;
docs/SPEC_RECONCILIATION.md §140).

Addendum 51 §3 asks for an identifier that is *"unique, persistent, never
reused, independent of display name, independent of current role."* This system
already had a durable agent separate from its job - the owner decision of
2026-08-17 - and the durable thing was the **display name**, which fails §3's
fourth clause by construction.

So the tests that matter here are the two that could not have passed before:
an agent that is renamed is still the same agent, and a name that has been used
is never given to somebody else.
"""

from __future__ import annotations

import pytest

from backend import agent_identity as identity


def test_an_agent_id_is_independent_of_the_name(conn):
    """§3's fourth clause, and the reason this module exists. Before it, the
    durable identity was the word a human reads, so a rename either broke every
    join or handed one agent's history to whoever held the name next."""
    agent = identity.create(conn, first_name="Amara")
    identity.rename(conn, agent, first_name="Bilal", reason="the owner asked")

    assert identity.get(conn, agent)["first_name"] == "Bilal"
    assert identity.by_name(conn, "Bilal")["agent_id"] == agent
    assert identity.by_name(conn, "Amara") is None
    # Same agent throughout. This is the whole claim.
    assert [row["first_name"] for row in identity.names_of(conn, agent)] == ["Amara", "Bilal"]


def test_a_name_that_has_been_held_is_never_given_to_another_agent(conn):
    """§3's *never reused*. The pool is forty names and nothing today releases
    one, so this has never happened - but that is an absent function rather than
    a guarantee, and a name that changes hands makes every older sentence about
    it ambiguous."""
    first = identity.create(conn, first_name="Amara")
    identity.rename(conn, first, first_name="Bilal", reason="r")

    with pytest.raises(identity.IdentityRefused) as refusal:
        identity.create(conn, first_name="Amara")
    assert "not reusable" in str(refusal.value)
    assert first in str(refusal.value), "the refusal does not say who holds it"


def test_a_freed_name_is_not_reusable_by_rename_either(conn):
    """The other door into the same room. A guard on `create` alone would be
    walked around by creating an agent and renaming it into the freed name."""
    first = identity.create(conn, first_name="Amara")
    identity.rename(conn, first, first_name="Bilal", reason="r")
    other = identity.create(conn, first_name="Chen")

    with pytest.raises(identity.IdentityRefused):
        identity.rename(conn, other, first_name="Amara", reason="r")


def test_two_agents_cannot_hold_one_name_at_the_same_time(conn):
    identity.create(conn, first_name="Amara")
    with pytest.raises(identity.IdentityRefused):
        identity.create(conn, first_name="Amara")


def test_a_rename_needs_its_reason(conn):
    """`coo_identity.rename` set the standard: explicit, reasoned and recorded,
    so that redeploying can never look like a new person (§88)."""
    agent = identity.create(conn, first_name="Amara")
    with pytest.raises(identity.IdentityRefused) as refusal:
        identity.rename(conn, agent, first_name="Bilal", reason="  ")
    assert "reason" in str(refusal.value)


def test_renaming_to_the_same_name_records_nothing(conn):
    """A no-op must not open a second span. A history showing Amara handing over
    to Amara would read as a change nobody made."""
    agent = identity.create(conn, first_name="Amara")
    identity.rename(conn, agent, first_name="Amara", reason="r")
    assert len(identity.names_of(conn, agent)) == 1


def test_a_parent_that_does_not_exist_is_refused(conn):
    """An unresolvable lineage is worse than none: it asserts a parent nobody
    can follow, which is the fabricated-fact shape §88 refuses."""
    with pytest.raises(identity.IdentityRefused) as refusal:
        identity.create(conn, first_name="Amara", parent_agent_id="nobody")
    assert "lineage" in str(refusal.value)


# --- the last name is derived, and a career move is not a new agent ----------------------

def test_the_display_name_is_the_first_name_and_the_desk(conn):
    """Addendum 51 §2's human-facing identity."""
    agent = identity.create(conn, first_name="Amara")
    assert identity.display_name(conn, agent, identity="explorer-1") == "Amara Explorer Agent 1"


def test_an_agent_at_no_desk_has_no_last_name(conn):
    """Not a placeholder and not a stale previous role. There is nothing to say,
    so nothing is said (§100, §104, §118)."""
    agent = identity.create(conn, first_name="Amara")
    assert identity.display_name(conn, agent) == "Amara"
    assert identity.role_designation(None) is None
    assert identity.role_designation("not-a-desk-shape") is None


def test_moving_desk_changes_the_name_and_not_the_agent(conn):
    """Addendum 50 §12's career path, which is why the last name is derived
    rather than stored. **Jack Explore Agent 1 becomes Jack Reporter Agent 1
    without becoming a second agent** - and it costs nothing, because the last
    name was never a fact about the agent."""
    agent = identity.create(conn, first_name="Amara")
    was = identity.display_name(conn, agent, identity="explorer-1")
    now = identity.display_name(conn, agent, identity="reporter-1")

    assert was == "Amara Explorer Agent 1"
    assert now == "Amara Reporter Agent 1"
    assert len(identity.names_of(conn, agent)) == 1, (
        "moving desk opened a name span; the role is not the name")


def test_the_coo_designation_comes_from_the_specification_not_a_rule(conn):
    """Addendum 51 §2's own example is *"Kumbhakarnan COO"* - no slot number,
    because numbering a singleton implies a second. Taken as data rather than
    inferred, so the one role the spec names explicitly is not reverse-engineered
    into a stemming rule that would mangle every other role."""
    assert identity.role_designation("coo-1") == "COO"
    assert identity.role_designation("speculator-2") == "Speculator Agent 2"
    assert identity.role_designation("portfolio_analyst-1") == "Portfolio Analyst Agent 1"


# --- lifecycle: only what something can produce ------------------------------------------

def test_a_specified_state_nothing_can_produce_is_refused_by_name(conn):
    """§49's rule. A row reading `training` in an organization with no path into
    training asserts a capability by having a column - and the refusal says the
    state is *specified and unreachable* rather than unknown, because those are
    different facts and a caller is entitled to both."""
    agent = identity.create(conn, first_name="Amara")
    with pytest.raises(identity.IdentityRefused) as refusal:
        identity.set_lifecycle(conn, agent, identity.STATE_TRAINING)
    assert "addendum 51 §6" in str(refusal.value)
    assert "nothing in this system produces it" in str(refusal.value)

    with pytest.raises(identity.IdentityRefused) as unknown:
        identity.set_lifecycle(conn, agent, "flourishing")
    assert "unknown lifecycle state" in str(unknown.value)


def test_every_specified_state_is_named_even_where_it_is_unreachable():
    """The specified vocabulary is visible in full, and what is reachable is a
    strict subset of it. A module that only listed what it could do would make
    the gap invisible - 47 §17's rule: an unfinished idea is never written as if
    it were built, and never quietly dropped either."""
    assert set(identity.REACHABLE_STATES) < set(identity.SPECIFIED_STATES)
    for state in ("training", "evolving", "archived"):
        assert state in identity.SPECIFIED_STATES
        assert state not in identity.REACHABLE_STATES


def test_activation_records_when_the_working_life_began_and_not_the_last_resume(conn):
    """An agent that pauses and resumes was activated once. Overwriting it would
    lose the fact addendum 51 §5 asks `activated_at` to carry."""
    agent = identity.create(conn, first_name="Amara")
    identity.set_lifecycle(conn, agent, identity.STATE_ACTIVE)
    first = identity.get(conn, agent)["activated_at"]

    identity.set_lifecycle(conn, agent, identity.STATE_PAUSED)
    identity.set_lifecycle(conn, agent, identity.STATE_ACTIVE)
    assert identity.get(conn, agent)["activated_at"] == first


def test_a_retired_agent_keeps_its_name_and_stops_answering_to_it(conn):
    """Two different questions. The caller asking *by name* wants whoever is
    working under it; the record of who has ever held it is what makes the
    organization's history readable, and it is never cleared."""
    agent = identity.create(conn, first_name="Amara")
    identity.set_lifecycle(conn, agent, identity.STATE_RETIRED)

    assert identity.by_name(conn, "Amara") is None
    assert [row["agent_id"] for row in identity.history_of_name(conn, "Amara")] == [agent]
    assert identity.get(conn, agent)["retired_at"] is not None
    assert agent not in [row["agent_id"] for row in identity.roster(conn)]


def test_a_retired_agents_name_is_still_not_reusable(conn):
    """The case a *current-holder* check would miss, and the one that matters
    most: retirement is exactly when a name looks free."""
    agent = identity.create(conn, first_name="Amara")
    identity.set_lifecycle(conn, agent, identity.STATE_RETIRED)
    with pytest.raises(identity.IdentityRefused):
        identity.create(conn, first_name="Amara")


def test_the_id_is_not_derived_from_anything_about_the_agent(conn):
    """§3 asks for an identifier independent of everything. An id derived from
    the name, the role or the creation moment is a fact about that thing, and
    would be parsed by somebody eventually."""
    first = identity.create(conn, first_name="Amara")
    second = identity.create(conn, first_name="Bilal")
    assert first != second
    for agent in (first, second):
        assert "Amara" not in agent and "Bilal" not in agent
