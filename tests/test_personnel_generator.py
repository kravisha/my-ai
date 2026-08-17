"""The personnel generator, and what the competency rules recover from it.

The generator exists so the rules can be checked against an answer. A competency
profile with no ground truth to compare against can only be inspected for
plausibility, and a scoring system with no skill at all passes that inspection
easily.

Everything here runs through the production schema - real registry rows, real
names, real assignment spans, real graded reports - so `competency_evidence`
executes the same joins it would in production. A generator handing dictionaries
straight to the pure functions would only prove the pure functions agree with a
mock of its own shape.
"""

import pytest

from backend import competency, fi_db
from simulation import personnel

STEADY = ("steady_strong", "steady_weak")


@pytest.fixture
def db(conn):
    fi_db.init_schema(conn)
    return conn


def population(conn, archetypes, **kwargs):
    return personnel.generate(conn, [("analysis", a) for a in archetypes], **kwargs)


# -- the generator produces real records -------------------------------------

def test_generated_agents_are_real_registry_entries(db):
    pop = population(db, ["steady_strong", "steady_weak"], items_per_agent=20)

    assert len(pop.agents) == 2
    for agent in pop.agents:
        assert fi_db.get_agent(db, agent.identity) is not None
        assert fi_db.get_agent_name(db, agent.identity) == agent.name
        assert fi_db.current_assignment(db, name=agent.name) is not None


def test_generated_work_is_attributed_through_assignment_spans(db):
    """The evidence path that matters: grades reach the agent only via the span."""
    pop = population(db, ["steady_strong"], items_per_agent=25)
    agent = pop.agents[0]

    assert fi_db.attributed_work(db, agent.name)["discovery_reports_completed"] == 25
    assert len(fi_db.competency_evidence(db, agent.name)["grades"]) == 25


def test_several_agents_can_share_a_role(db):
    """Production cannot do this yet - the slot allocator issues only role-1 - so
    the generator is what makes ranking exercisable at all."""
    pop = population(db, ["steady_strong", "steady_weak", "erratic"], items_per_agent=15)
    identities = {agent.identity for agent in pop.agents}
    assert identities == {"analysis-1", "analysis-2", "analysis-3"}


def test_the_same_seed_produces_the_same_scores(db):
    first = population(db, ["erratic"], items_per_agent=30, seed=7)
    scores_a = fi_db.competency_profile(db, first.agents[0].name)["dimensions"]["analytical_quality"]

    other = fi_db.get_connection(":memory:")
    fi_db.init_schema(other)
    try:
        second = population(other, ["erratic"], items_per_agent=30, seed=7)
        scores_b = fi_db.competency_profile(other, second.agents[0].name)["dimensions"]["analytical_quality"]
    finally:
        other.close()

    assert scores_a["score"] == scores_b["score"]


def test_a_different_seed_produces_different_scores(db):
    first = population(db, ["erratic"], items_per_agent=30, seed=1)
    a = fi_db.competency_profile(db, first.agents[0].name)["dimensions"]["analytical_quality"]["score"]

    other = fi_db.get_connection(":memory:")
    fi_db.init_schema(other)
    try:
        second = population(other, ["erratic"], items_per_agent=30, seed=2)
        b = fi_db.competency_profile(other, second.agents[0].name)["dimensions"]["analytical_quality"]["score"]
    finally:
        other.close()

    assert a != b


def test_an_unknown_archetype_is_refused(db):
    with pytest.raises(ValueError, match="unknown archetype"):
        population(db, ["exemplary"])


# -- the rules recover what the generator hid ---------------------------------

@pytest.mark.parametrize("archetype", STEADY)
def test_a_steady_agents_score_lands_near_its_true_competence(db, archetype):
    """The skill check.

    A profile that could not recover a constant competence from sixty clean
    observations would not be measuring anything."""
    pop = population(db, [archetype], items_per_agent=60)
    agent = pop.agents[0]
    entry = fi_db.competency_profile(db, agent.name)["dimensions"]["analytical_quality"]

    assert abs(entry["score"] - agent.mean_true_competence) < 0.05


def test_a_strong_agent_outscores_a_weak_one(db):
    pop = population(db, ["steady_strong", "steady_weak"], items_per_agent=40)
    scores = {
        agent.archetype: fi_db.competency_profile(db, agent.name)["dimensions"]["analytical_quality"]["score"]
        for agent in pop.agents
    }
    assert scores["steady_strong"] > scores["steady_weak"]


def test_an_erratic_agent_is_less_precisely_measured_at_the_same_sample_count(db):
    """The finding that put spread into the profile.

    Both agents are scored from the same number of observations. Without spread,
    nothing in the profile said one estimate was several times less certain than
    the other."""
    pop = population(db, ["steady_strong", "erratic"], items_per_agent=60)
    entries = {
        agent.archetype: fi_db.competency_profile(db, agent.name)["dimensions"]["analytical_quality"]
        for agent in pop.agents
    }

    assert entries["steady_strong"]["samples"] == entries["erratic"]["samples"]
    assert entries["erratic"]["standard_error"] > 2 * entries["steady_strong"]["standard_error"]


def test_agents_of_equal_true_competence_are_not_reported_as_separated(db):
    """Ranking must not present noise as a finding.

    'improving', 'declining' and 'erratic' all average 0.5 by construction, so
    whatever order they land in, the gaps between them are not real."""
    pop = population(db, ["improving", "declining", "erratic"], items_per_agent=60)
    ranked = [row for row in fi_db.rank_role(db, "analysis", "analytical_quality") if row["rank"]]

    assert len(ranked) == 3
    assert not any(row["separated"] for row in ranked if row["separated"] is not None), (
        f"equal-competence agents reported as separated: {[(r['name'], r['gap_to_next']) for r in ranked]}"
    )
    assert pop  # the population is the fixture under test


def test_a_genuinely_better_agent_is_reported_as_separated(db):
    """The other half - a separation flag that is never True says nothing."""
    pop = population(db, ["steady_strong", "steady_weak"], items_per_agent=60)
    ranked = [row for row in fi_db.rank_role(db, "analysis", "analytical_quality") if row["rank"]]

    assert ranked[0]["separated"] is True
    assert pop


# -- recency ------------------------------------------------------------------

def test_a_recency_window_excludes_older_work(db):
    pop = population(db, ["steady_strong"], items_per_agent=60, period_days=30)
    name = pop.agents[0].name

    everything = fi_db.competency_evidence(db, name)
    recent = fi_db.competency_evidence(db, name, window_days=10)

    assert len(recent["grades"]) < len(everything["grades"])
    assert recent["window_days"] == 10


def test_a_declining_agent_looks_worse_through_a_recent_window(db):
    """Recency is what makes a competency profile a statement about now.

    Without it, an agent that was strong six months ago and weak since would
    carry the average of the two forever."""
    pop = population(db, ["declining"], items_per_agent=80, period_days=30)
    name = pop.agents[0].name

    lifetime = competency.profile(fi_db.competency_evidence(db, name))
    recent = competency.profile(fi_db.competency_evidence(db, name, window_days=8))

    lifetime_score = lifetime["dimensions"]["analytical_quality"]["score"]
    recent_score = recent["dimensions"]["analytical_quality"]["score"]
    assert recent_score < lifetime_score, (
        f"a declining agent scored {recent_score} recently and {lifetime_score} over its lifetime; "
        "the recent window should be the harsher of the two"
    )


# -- operational reliability --------------------------------------------------

def test_crashes_lower_operational_reliability(db):
    pop = population(db, ["steady_strong"], items_per_agent=15)
    agent = pop.agents[0]
    personnel.record_sessions(db, agent.identity, agent.role, 10)
    personnel.inject_crashes(db, agent.identity, 3)

    entry = fi_db.competency_profile(db, agent.name)["dimensions"]["operational_reliability"]
    assert entry["stated"] is True
    assert entry["score"] == pytest.approx(0.7)


def test_a_crash_leaves_a_historical_trace_not_only_a_current_state(db):
    """Regression: process_state is overwritten by the next respawn, so a crash
    that only changed it left no evidence an agent had ever crashed."""
    pop = population(db, ["steady_strong"], items_per_agent=5)
    identity = pop.agents[0].identity

    personnel.inject_crashes(db, identity, 2)
    fi_db.register_agent(db, identity, "analysis", 999)   # respawn overwrites process_state

    crashes = db.fetchone(
        "SELECT COUNT(*) AS n FROM health_metrics WHERE identity = ? AND metric = 'crash'", (identity,)
    )["n"]
    assert crashes == 2


# -- ground truth stays out of the database -----------------------------------

def test_ground_truth_is_returned_and_never_written(db):
    """A table holding the answer is a table something can accidentally read.

    Scans every table in the schema for any archetype name; the generator must
    leave no trace of what it knew."""
    pop = population(db, ["steady_strong", "lucky_streak"], items_per_agent=10)
    assert set(pop.ground_truth()) == set(pop.names())
    assert pop.ground_truth()[pop.agents[0].name]["archetype"] == "steady_strong"

    for table in fi_db.list_tables_in_schema():
        columns = [row["name"] for row in db.fetchall(f"PRAGMA table_info({table})")]
        text_columns = [c for c in columns if c not in ("id", "schema_version")]
        if not text_columns:
            continue
        clause = " OR ".join(f"CAST({c} AS TEXT) LIKE ?" for c in text_columns)
        for archetype in personnel.ARCHETYPES:
            hit = db.fetchone(
                f"SELECT COUNT(*) AS n FROM {table} WHERE {clause}",
                tuple(f"%{archetype}%" for _ in text_columns),
            )
            assert hit["n"] == 0, f"{table} contains the archetype {archetype!r}"
