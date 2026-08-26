"""Running the curriculum: an exercise, end to end (TASK_QUEUE TQ-76; addendum
36 §3, §6; docs/SPEC_RECONCILIATION.md §114, §115).

Addendum 36 §3's lifecycle, at the point where it becomes code:

> *Curriculum Architect defines competency → Simulation requirements identified
> → Simulation Engine produces exercises/data → Curriculum finalized → Relevant
> agents trained → Agents evaluated → Results reported to Education → Curriculum
> refined*

`backend/curriculum.py` holds the first two — the competency and the simulation
requirement, as data. This is the engine producing the exercise and the agent
being evaluated.

## Why the runner is here and the curriculum is not

The curriculum is organizational data: what is being taught and why. It must be
readable by anything that wants to know what the organization trains on,
including things with no simulation engine.

The runner needs the engine. So it lives in `simulation/`, and the dependency
runs one way — `simulation` imports `backend`, never the reverse. The curriculum
declares its world as strings (`("avery-secondary", "unreachable")`) and this
module turns them into an exchange, which is what keeps that direction intact.

## The exercise is the production workflow with invented inputs

§114, and §115's correction of it. The analyst is not called differently here: it
claims a request from the ordinary queue, fetches through the ordinary provider
lookup, and delivers to the ordinary transport. What this module supplies is the
*world* — a client who asks and an exchange that answers — and both are at the
boundary.

There is nothing in `agents/` that knows an exercise is running, and
`test_no_agent_can_tell_it_is_in_a_simulation` fails if that changes.

## Nothing survives an exercise except the grade

`client_sessions.run_session` disconnects in a `finally`, so a client's report is
discarded whether the exercise passed, failed or fell over. What is written down
is the verdict and its complaint *codes* — never a position (§111,
`backend/curriculum.py`).
"""

from __future__ import annotations

from backend import curriculum as curriculum_module
from backend import portfolio_providers
from simulation import client_sessions, exchange


def _world_for(exercise) -> exchange.SimulatedExchange:
    """The exchange this exercise runs against.

    Built from the exercise's declared behaviours, which means an unknown
    behaviour is refused **here**, when the exercise is set up, rather than
    halfway through it."""
    return exchange.SimulatedExchange.from_scenario(
        [{"source": source, "behaviour": behaviour}
         for source, behaviour in exercise.world])


def _sources_for(exercise) -> list:
    """The source descriptors the client will name.

    `owner_hint` is the client, so every source of one client's returns that
    client's fixture - which is what makes a two-source exercise a *consolidation*
    exercise rather than two unrelated portfolios."""
    return [{"provider_type": exchange.PROVIDER_TYPE, "name": name,
             "owner_hint": exercise.client}
            for name in exercise.sources]


def build_client(exercise, world) -> client_sessions.SimulatedClient:
    """The imaginary client for this exercise, holding its own ground truth.

    The truth comes from the exchange rather than from the exercise, so a
    scenario cannot declare a client who believes something the world does not
    contain - which would produce a disappointment that is the exercise's fault
    rather than the analyst's."""
    sources = _sources_for(exercise)
    truth = {}
    for descriptor in sources:
        source = portfolio_providers.Source(**descriptor)
        truth[descriptor["name"]] = world.truth_for(source)
    return client_sessions.SimulatedClient(
        client_id=exercise.client,
        session_id=f"exercise-{exercise.exercise_id}",
        sources=sources,
        truth=truth,
    )


def run_exercise(conn, exercise, analyst_cycle, *, curriculum=None,
                 trained_agent: str | None = None) -> dict:
    """One exercise, and the grade it produced.

    Returns the verdict with the curriculum's own judgement attached: whether the
    analyst met the bar, and whether the *curriculum* was wrong about it - a
    known gap that passed means somebody built the capability and the curriculum
    owes an update (addendum 36 §11)."""
    curriculum = curriculum or curriculum_module.PORTFOLIO_ANALYSIS_V1
    world = _world_for(exercise)
    client = build_client(exercise, world)

    with _exchange_serving(world):
        verdict = client_sessions.run_session(
            conn, client, analyst_cycle, requested=exercise.requested)

    result_id = curriculum_module.record_result(
        conn, curriculum, exercise, verdict, trained_agent=trained_agent)
    row = conn.fetchone(
        "SELECT passed, unexpected FROM curriculum_results WHERE id = ?", (result_id,))
    return {**verdict,
            "exercise_id": exercise.exercise_id,
            "competency": exercise.competency,
            "kind": exercise.kind,
            "expectation": exercise.expectation,
            "passed": bool(row["passed"]),
            "curriculum_out_of_date": bool(row["unexpected"])}


def run_curriculum(conn, analyst_cycle, *, curriculum=None,
                   trained_agent: str | None = None) -> dict:
    """Every exercise, then the report Education reads (addendum 36 §3).

    Runs them all rather than stopping at the first failure, because a curriculum
    that reported only its first problem would hide the shape of what an agent is
    weak at - and the shape is what §11's adaptation acts on."""
    curriculum = curriculum or curriculum_module.PORTFOLIO_ANALYSIS_V1
    outcomes = [run_exercise(conn, exercise, analyst_cycle, curriculum=curriculum,
                             trained_agent=trained_agent)
                for exercise in curriculum.exercises]
    return {"outcomes": outcomes,
            "report": curriculum_module.report(conn, curriculum)}


class _exchange_serving:
    """Point `for_source` at this exercise's exchange for the length of a run.

    **The one piece of machinery in this file, and it is deliberately here rather
    than in the analyst.** The analyst chooses a provider from the source the
    request names; what an exercise changes is which provider serves that type,
    which is the substitution at the boundary §115 describes.

    A context manager rather than a permanent registration, so two exercises with
    different faults can run in one process and neither can reach into the
    other's world - the same isolation `simulation/harness.py` gets from a
    per-run database."""

    def __init__(self, world):
        self.world = world
        self._previous = None

    def __enter__(self):
        self._previous = portfolio_providers._PROVIDERS.get(exchange.PROVIDER_TYPE)
        portfolio_providers._PROVIDERS[exchange.PROVIDER_TYPE] = self.world
        return self.world

    def __exit__(self, *exc_info):
        if self._previous is not None:
            portfolio_providers._PROVIDERS[exchange.PROVIDER_TYPE] = self._previous
        else:  # pragma: no cover - the fixture provider is always registered
            portfolio_providers._PROVIDERS.pop(exchange.PROVIDER_TYPE, None)
        return False
