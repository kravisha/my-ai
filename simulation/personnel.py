"""Synthesises agent populations whose true competence is known, so the rules
that judge competence can be checked against an answer.

The same device the market provider uses: the generator holds a ground truth the
system is never told. Explorer infers a regime it is not given; here the
competency rules infer a capability they are not given, and the difference
between the two is measurable. Without that, a competency profile can only be
inspected for plausibility, which is how a scoring system with no skill at all
passes review.

**Real rows, production schema.** Every synthetic agent registers through
`fi_db.register_agent`, draws a name, opens an assignment span, and files reports
that are graded - so `competency_evidence` runs the same joins it would run in
production. A generator that handed dictionaries straight to the pure functions
would be testing the pure functions against a mock of its own shape.

**Ground truth never enters the database.** It is returned to the caller, and the
harness writes it to a file beside the run. A table holding the answer is a table
something can accidentally read.

One thing this can do that production cannot: put several agents in one role.
`fi_db.register_agent` takes any identity, while the Controller's slot allocator
issues only `role-1`. So ranking - which needs candidates to compare - can be
exercised here before multi-instance roles exist anywhere else.

Internal rationale: INT-PHIL-0020
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from backend import fi_db

# Each archetype is a competence trajectory over the run, as a function of
# progress from 0.0 to 1.0, plus how noisy each individual observation is.
#
# `lucky_streak` is the one that matters most. A weak agent whose first stretch
# happens to go well is exactly how a promotion rule produces a false positive,
# and it cannot be constructed by hand often enough to measure the rate.
ARCHETYPES = {
    "steady_strong": {"at": lambda p: 0.78, "noise": 0.08,
                      "describes": "consistently capable"},
    "steady_weak": {"at": lambda p: 0.28, "noise": 0.08,
                    "describes": "consistently below standard"},
    "improving": {"at": lambda p: 0.25 + 0.50 * p, "noise": 0.08,
                  "describes": "starts weak, becomes capable"},
    "declining": {"at": lambda p: 0.75 - 0.50 * p, "noise": 0.08,
                  "describes": "starts capable, degrades"},
    "erratic": {"at": lambda p: 0.50, "noise": 0.30,
                "describes": "average overall, wildly inconsistent"},
    "lucky_streak": {"at": lambda p: 0.80 if p < 0.25 else 0.25, "noise": 0.08,
                     "describes": "weak, but the first quarter went well"},
}

# How the three graded dimensions relate to the latent competence. Offsets keep
# them from being the same number wearing three hats, which would make a test
# that computes them separately pass for the wrong reason.
DIMENSION_OFFSETS = {"overall_score": 0.0, "evidence_quality_score": -0.05, "novelty_score": -0.12}

WORTH_THE_COMPUTE_AT = 0.5


@dataclass
class SyntheticAgent:
    name: str
    identity: str
    role: str
    archetype: str
    mean_true_competence: float
    items: int
    calibration: list = field(default_factory=list)

    def as_ground_truth(self) -> dict:
        return {
            "identity": self.identity,
            "role": self.role,
            "archetype": self.archetype,
            "mean_true_competence": round(self.mean_true_competence, 4),
            "items": self.items,
        }


@dataclass
class Population:
    agents: list[SyntheticAgent]

    def by_name(self, name: str) -> SyntheticAgent | None:
        return next((agent for agent in self.agents if agent.name == name), None)

    def names(self) -> list[str]:
        return [agent.name for agent in self.agents]

    def ground_truth(self) -> dict:
        return {agent.name: agent.as_ground_truth() for agent in self.agents}


def generate(
    conn,
    plan: list[tuple[str, str]],
    items_per_agent: int = 60,
    period_days: float = 30.0,
    seed: int = 20260817,
    grader_identity: str = "evaluator-1",
) -> Population:
    """Build a population and its recorded work.

    `plan` is a list of `(role, archetype)` pairs; a role appearing more than
    once produces several agents in that role, which is what ranking needs.

    Every agent's work is spread evenly backwards from now over `period_days`,
    so a recency window has something to include and something to exclude."""
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    agents: list[SyntheticAgent] = []
    slots: dict[str, int] = {}

    for role, archetype in plan:
        if archetype not in ARCHETYPES:
            raise ValueError(f"unknown archetype {archetype!r}; expected one of {sorted(ARCHETYPES)}")
        slots[role] = slots.get(role, 0) + 1
        identity = f"{role}-{slots[role]}"

        fi_db.register_agent(conn, identity, role, pid=10_000 + len(agents))
        name = fi_db.get_agent_name(conn, identity)
        if name is None:
            raise RuntimeError(
                f"the name pool ran out at {identity}; a population larger than the pool cannot be "
                "generated, because personnel records are keyed by name"
            )

        # The assignment span opened at registration starts now, which would put
        # every backdated report outside it. Widened to cover the whole period so
        # attribution behaves as it would for an agent that had been there all
        # along.
        span = fi_db.current_assignment(conn, name=name)
        conn.execute(
            "UPDATE agent_assignments SET started_at = ? WHERE id = ?",
            ((now - timedelta(days=period_days + 1)).isoformat(), span["id"]),
        )

        agent = _generate_work(
            conn, rng, name, identity, role, archetype,
            items_per_agent, period_days, now, grader_identity,
        )
        agents.append(agent)

    return Population(agents=agents)


def _generate_work(
    conn, rng, name, identity, role, archetype, items, period_days, now, grader_identity,
) -> SyntheticAgent:
    spec = ARCHETYPES[archetype]
    spawned_at = (now - timedelta(days=period_days + 1)).isoformat()
    competences = []
    calibration = []

    for index in range(items):
        progress = index / max(1, items - 1)
        true_competence = spec["at"](progress)
        competences.append(true_competence)

        created_at = (now - timedelta(days=period_days * (1 - progress))).isoformat()
        report_id = conn.execute_returning_id(
            "INSERT INTO discovery_reports_completed (created_at, producer_identity, "
            "producer_spawned_at, report_type, security, summary, completed_at, outcome, schema_version) "
            "VALUES (?, ?, ?, 'synthetic', 'SYN1', 'generated for personnel simulation', ?, 'handled', ?)",
            (created_at, identity, spawned_at, created_at, fi_db.SCHEMA_VERSION),
        )
        analysis_id = conn.execute_returning_id(
            "INSERT INTO analysis_results (created_at, producer_identity, producer_spawned_at, "
            "report_id, security, thesis, evidence_summary, confidence, uncertainty, schema_version) "
            "VALUES (?, ?, ?, ?, 'SYN1', 'generated', 'generated', ?, 'generated', ?)",
            (created_at, grader_identity, spawned_at, report_id,
             round(_observe(rng, true_competence, spec["noise"]), 4), fi_db.SCHEMA_VERSION),
        )

        scores = {
            key: round(_observe(rng, true_competence + offset, spec["noise"]), 4)
            for key, offset in DIMENSION_OFFSETS.items()
        }
        conn.execute(
            "INSERT INTO grades (created_at, grader_identity, grader_spawned_at, report_id, "
            "analysis_result_id, relevance_score, novelty_score, evidence_quality_score, "
            "worth_the_compute, overall_score, rationale, schema_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'generated for personnel simulation', ?)",
            (created_at, grader_identity, spawned_at, report_id, analysis_id,
             scores["overall_score"], scores["novelty_score"], scores["evidence_quality_score"],
             int(scores["overall_score"] >= WORTH_THE_COMPUTE_AT), scores["overall_score"],
             fi_db.SCHEMA_VERSION),
        )

        # Held aside rather than written. Nothing in the schema records whether a
        # stated confidence turned out to be right, so writing these would mean
        # inventing a column production has no producer for. Returned so the
        # calibration rule can still be exercised.
        stated = _observe(rng, true_competence, spec["noise"])
        calibration.append((max(0.0, min(1.0, stated)), rng.random() < true_competence))

    return SyntheticAgent(
        name=name, identity=identity, role=role, archetype=archetype,
        mean_true_competence=sum(competences) / len(competences) if competences else 0.0,
        items=items, calibration=calibration,
    )


def _observe(rng, true_value: float, noise: float) -> float:
    """One noisy observation of a latent value, clipped to the score range.

    Clipping is what makes an extreme archetype behave: without it a strong
    agent's noise produces scores above 1.0 that no real grade could carry, and
    the rules would be tuned against impossible inputs."""
    return max(0.0, min(1.0, rng.gauss(true_value, noise)))


def inject_crashes(conn, identity: str, count: int) -> None:
    """Give an agent a crash history, for the operational reliability dimension."""
    for _ in range(count):
        fi_db.mark_process_crashed(conn, identity)


def record_sessions(conn, identity: str, role: str, count: int) -> None:
    """Give an agent a spawn history, which is the denominator reliability uses."""
    for _ in range(count):
        directive_id = fi_db.enqueue_directive(
            conn, "spawn", requested_by="coo", target_role=role, reason="generated"
        )
        fi_db.complete_directive(conn, directive_id, "success", detail=identity)
