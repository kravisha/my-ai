"""Governance established before a run (TQ-88; docs/SPEC_RECONCILIATION.md §128).

The property worth defending hardest is the one that sounds like a style
preference: **a seed goes through the organization's own API and never through
SQL.** A fixture able to build states the organization cannot reach measures the
fixture rather than the system, and every property asserted against such a state
is a claim about something that does not exist.
"""

from __future__ import annotations

import inspect

import pytest

from backend import governed_knowledge as governed, parliament
from simulation import harness, scenario as scenario_module, seeding

ROLL = {"broad": ["coo", "explorer", "speculator", "analysis"],
        "representative": ["coo", "analysis"]}

FULL_SEED = [
    {"adopt_articles": {"roll": ROLL, "quorum": "1/2", "ordinary_threshold": "1/2"}},
    {"enact": {"title": "Reports carry a summary", "affects": "organization_policy",
               "proposed_by": "analysis", "votes": {"coo": "for", "analysis": "for"}}},
    {"adopt_instrument": {"under": 1, "subject": "discovery_reports",
                          "level": "organization_policy", "text": "A summary is required.",
                          "binds": "*",
                          "requires": {"kind": "required_fields", "fields": ["summary"]}}},
]


# --- what a seed produces -----------------------------------------------------------

def test_a_seed_establishes_governance_the_organization_could_have_reached(conn):
    produced = seeding.apply(conn, FULL_SEED)

    assert parliament.current_articles(conn)["version"] == 1
    resolution = parliament.get_resolution(conn, produced[1]["resolution_id"])
    assert resolution["status"] == parliament.STATUS_ENACTED
    assert resolution["approved_by"], "it carries the tally that carried it"

    item = governed.effective_item(conn, "discovery_reports")
    assert item["id"] == produced[2]["instrument_id"]
    assert item["resolution_id"] == resolution["id"]


def test_the_owner_adopts_the_articles_and_not_the_organization(conn):
    """§120: only the owner can. A run whose organization voted itself an
    instrument would be simulating a system this one refuses to be."""
    seeding.apply(conn, FULL_SEED[:1])
    assert parliament.current_articles(conn)["adopted_by"] == "krish"
    assert parliament.current_articles(conn)["adopted_via"] == "genesis"


def test_a_resolution_that_does_not_carry_stops_the_run_being_set_up(conn):
    """A scenario that meant to run under a rule and quietly did not would
    produce properties describing an ungoverned organization under a governed
    name."""
    seed = [FULL_SEED[0],
            {"enact": {"title": "x", "affects": "organization_policy", "proposed_by": "coo",
                       "votes": {"coo": "against", "analysis": "against"}}}]
    with pytest.raises(seeding.SeedError) as refusal:
        seeding.apply(conn, seed)
    assert "did not carry" in str(refusal.value)


def test_an_instrument_must_point_at_a_resolution(conn):
    seed = [FULL_SEED[0],
            {"adopt_instrument": {"under": 0, "subject": "s", "level": "organization_policy",
                                  "text": "t", "binds": "*"}}]
    with pytest.raises(seeding.SeedError) as refusal:
        seeding.apply(conn, seed)
    assert "not an enacted resolution" in str(refusal.value)


def test_the_store_still_refuses_what_it_always_refused(conn):
    """The seed is not a back door. An instrument at a governing level with no
    authority behind it is refused by `governed_knowledge`, not by anything
    here — which is the point of routing through the production API."""
    seed = [FULL_SEED[0],
            {"enact": {"title": "A procedure", "affects": "procedure", "proposed_by": "coo",
                       "votes": {"coo": "for", "analysis": "for"}}},
            {"adopt_instrument": {"under": 1, "subject": "s", "level": "law",
                                  "text": "t", "binds": "*"}}]
    with pytest.raises(governed.AdoptionRefused) as refusal:
        seeding.apply(conn, seed)
    assert "cannot be spent" in str(refusal.value)


# --- refused before the run rather than during it -----------------------------------

@pytest.mark.parametrize("seed,reason", [
    ("not a list", "list of steps"),
    ([{"enact": {}, "adopt_articles": {}}], "single-key"),
    ([{"convene": {}}], "unknown step"),
    ([{"enact": "words"}], "must be a mapping"),
    ([{"enact": {"title": "x", "affects": "law"}}], "votes"),
    ([{"adopt_instrument": {"subject": "s"}}], "under"),
])
def test_a_seed_that_could_never_run_is_refused_at_load(seed, reason):
    """A malformed seed costs a load error, not five minutes of simulation and a
    summary nobody can trust — the same reasoning behind validating faults and
    config keys at load."""
    with pytest.raises(seeding.SeedError) as refusal:
        seeding.validate(seed)
    assert reason in str(refusal.value)


def test_a_scenario_carrying_a_bad_seed_will_not_load(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "id: bad\nversion: 1\nlifecycle: active\ndescription: x\n"
        "duration_seconds: 60\nconfig: {}\nseed:\n  - convene: {}\n",
        encoding="utf-8")
    with pytest.raises(scenario_module.ScenarioError) as refusal:
        scenario_module.load(bad)
    assert "unknown step" in str(refusal.value)


# --- the structural guarantee -------------------------------------------------------

def test_a_seed_cannot_write_sql():
    """The temptation is an `sql:` step and it would be three lines. It would
    also let a scenario construct an instrument with no resolution behind it, a
    resolution enacted without a quorum, or Articles with an empty roll — and
    every property asserted against such a state would describe a system that
    does not exist."""
    source = inspect.getsource(seeding)
    for statement in ("INSERT ", "UPDATE ", "DELETE ", "execute("):
        assert statement not in source, f"seeding writes SQL: {statement!r}"
    assert "sql" not in seeding.STEPS


def test_the_harness_seeds_before_the_controller_starts():
    """An agent that came up ungoverned and was governed a second later would
    have done a cycle of work under rules nobody could see, which is the state a
    governed run exists to rule out."""
    source = inspect.getsource(harness.SimulationRun.start)
    seeded_at = source.index("seeding.apply")
    started_at = source.index("subprocess.Popen")
    assert seeded_at < started_at, "the organization starts before it is governed"


def test_a_scenario_without_a_seed_is_unchanged():
    """Every existing scenario runs an ungoverned organization and must keep
    doing so — this addition must not have quietly governed the control run."""
    baseline = scenario_module.load("simulation/scenarios/baseline_steady_state.yaml")
    assert baseline.seed == []


def test_the_governed_scenario_says_what_it_does_not_measure():
    """No agent proposes or votes, so a scenario cannot exercise deliberation.
    Stated in the file rather than left for a reader to infer from something that
    looks like a parliament and is a fixture."""
    governed_scenario = scenario_module.load(
        "simulation/scenarios/governed_organization.yaml")
    assert governed_scenario.seed
    assert "does not measure" in governed_scenario.description.lower()
    assert "no agent in this system proposes or votes" in governed_scenario.description.lower()
