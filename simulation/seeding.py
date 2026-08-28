"""Establishing governance before a run, through the organization's own doors
(TASK_QUEUE TQ-88; docs/SPEC_RECONCILIATION.md §128).

A scenario has always been a set of `FI_*` environment variables, because
everything a scenario needed to vary lived in the environment. Governance does
not: the Articles, a carried resolution and an instrument in force are rows, and
there was no way for a scenario to say *"run the organization under this rule."*

So a scenario may now declare a `seed` — a short, closed vocabulary of governance
facts established in the run's fresh database before the Controller starts.

## Every step goes through the production API, and that is the whole design

Nothing here writes SQL. Articles are adopted through
`parliament.adopt_genesis_articles`, a resolution is carried through
`propose` / `cast_vote` / `close`, and an instrument is adopted through
`governed_knowledge.adopt`.

The temptation is an `sql:` step, and it would be three lines. It would also let
a scenario construct states the organization cannot reach — an instrument with no
resolution behind it, a resolution enacted without a quorum, Articles with an
empty roll — and **every property asserted against such a state would be a claim
about a system that does not exist.** A simulation that can create impossible
conditions does not measure the organization; it measures the fixture.

The same argument `simulation/harness.py` makes about isolation, one layer along:
the fixture must be constrained by the real thing, not beside it.

## Seeding is not the organization governing itself

A seeded resolution was not debated by anybody. **No agent in this system
proposes or votes**, so a scenario cannot exercise deliberation and this module
does not pretend to. What it exercises is what happens *after* a decision: an
instrument in force, and agents that have to read it.

That limit is stated here rather than left for a reader to infer from a scenario
that looks like a parliament and is a fixture.
"""

from __future__ import annotations

from backend import governed_knowledge, parliament, portfolios, release
from backend.db import Database

# A release candidate can be *prepared* before a run and applied during it, which
# is addendum 46 §16's shape exactly: Version N runs while N+1 is prepared. The
# applying is `simulation/governance_events.py`, because a release is an event and
# not a starting condition.
STEPS = ("adopt_articles", "enact", "adopt_instrument", "prepare_release", "stage_change")


class SeedError(ValueError):
    """A seed a scenario cannot mean, refused before a run starts.

    Raised at parse time where possible, so a malformed seed costs a syntax error
    rather than five minutes of simulation and a summary nobody can trust."""


def validate(seed: list) -> list:
    """Check a scenario's seed without a database.

    Called by `scenario.load`, so `python -m simulation list` refuses a scenario
    whose seed could never run - the same reasoning behind validating config keys
    at load rather than at spawn."""
    if seed is None:
        return []
    if not isinstance(seed, list):
        raise SeedError("a seed is a list of steps")
    for index, step in enumerate(seed):
        if not isinstance(step, dict) or len(step) != 1:
            raise SeedError(f"seed step {index} must be a single-key mapping, one of {list(STEPS)}")
        (name, body), = step.items()
        if name not in STEPS:
            raise SeedError(f"seed step {index}: unknown step {name!r}; known are {list(STEPS)}")
        if not isinstance(body, dict):
            raise SeedError(f"seed step {index} ({name}): its body must be a mapping")
        if name == "enact" and not isinstance(body.get("votes"), dict):
            raise SeedError(
                f"seed step {index} (enact): needs a 'votes' mapping of voter to for/against/"
                "abstain. A resolution with no votes is not carried, it is open.")
        if name in ("adopt_instrument", "prepare_release") and "under" not in body:
            raise SeedError(
                f"seed step {index} ({name}): needs 'under', the index of the enact step "
                "whose resolution authorizes it. An instrument with no authority behind it is a "
                "state the organization cannot reach - and for a release, the resolution is "
                "also the authority the way back is spent under (addendum 30 §27).")
        if name == "stage_change" and "into" not in body:
            raise SeedError(
                f"seed step {index} (stage_change): needs 'into', the index of the "
                "prepare_release step it belongs to. A change staged into no set is a change "
                "that cannot be reversed with one.")
    return seed


def apply(conn: Database, seed: list, *, owner_id: str = "krish") -> list[dict]:
    """Establish the seeded governance, returning what each step produced.

    The owner adopts the Articles because §120 says only the owner can: a run
    whose organization voted itself an instrument would be simulating a system
    this one refuses to be."""
    produced: list[dict] = []
    owner = portfolios.for_superuser(owner_id)
    for index, step in enumerate(validate(seed)):
        (name, body), = step.items()
        if name == "adopt_articles":
            version = parliament.adopt_genesis_articles(
                conn, owner=owner,
                text=body.get("text", "The Articles, established for a simulation run."),
                roll=body["roll"], quorum=body.get("quorum", "1/2"),
                ordinary_threshold=body.get("ordinary_threshold", "1/2"))
            produced.append({"step": name, "articles_version": version})
        elif name == "enact":
            resolution = parliament.propose(
                conn, title=body["title"], rationale=body.get("rationale", "seeded for a run"),
                proposed_by=body.get("proposed_by", "coo"), affects=body["affects"],
                evidence=body.get("evidence"))
            for voter, value in body["votes"].items():
                parliament.cast_vote(conn, resolution, voter=voter, value=value)
            result = parliament.close(conn, resolution)
            if not result["carried"]:
                # Refused rather than carried on with: a scenario that meant to
                # run under a rule and quietly did not would produce properties
                # that describe an ungoverned organization under a governed name.
                raise SeedError(
                    f"seed step {index} (enact): {body['title']!r} did not carry "
                    f"({result['for']} for, {result['against']} against, quorum "
                    f"{'met' if result['quorum_met'] else 'not met'}). Fix the votes or the roll.")
            produced.append({"step": name, "resolution_id": resolution, "tally": result})
        elif name == "prepare_release":
            authority = produced[body["under"]]
            if authority.get("step") != "enact":
                raise SeedError(
                    f"seed step {index} (prepare_release): 'under' points at a "
                    f"{authority.get('step')!r} step, not an enacted resolution.")
            candidate = release.prepare(
                conn, name=body["name"], intent=body.get("intent", "seeded for a run"),
                resolution_id=authority["resolution_id"],
                prepared_by=body.get("prepared_by", "coo"))
            produced.append({"step": name, "release_id": candidate})
        elif name == "stage_change":
            candidate = produced[body["into"]]
            if candidate.get("step") != "prepare_release":
                raise SeedError(
                    f"seed step {index} (stage_change): 'into' points at a "
                    f"{candidate.get('step')!r} step, not a prepared release.")
            # The rest of the body *is* the instrument, which keeps the seed
            # vocabulary and `governed_knowledge.adopt`'s one thing rather than two
            # that drift. `resolution_id` and `adopted_by` are absent by
            # construction: `release.stage` refuses a change carrying its own
            # authority, so a seed cannot smuggle one in either.
            instrument = {k: v for k, v in body.items()
                          if k not in ("into", "staged_by", "replaces_step")}
            if "replaces_step" in body:
                # A staged instrument that displaces one an earlier step adopted
                # names the *step*, not the row id. Writing the id would make the
                # seed correct only against an empty database - and the first
                # scenario that inherited a run's state would silently replace
                # somebody else's instrument.
                displaced = produced[body["replaces_step"]]
                if displaced.get("step") != "adopt_instrument":
                    raise SeedError(
                        f"seed step {index} (stage_change): 'replaces_step' points at a "
                        f"{displaced.get('step')!r} step, not an adopted instrument.")
                instrument["replaces"] = displaced["instrument_id"]
            change = release.stage(
                conn, candidate["release_id"],
                instrument=instrument, staged_by=body.get("staged_by", "coo"))
            produced.append({"step": name, "change_id": change})
        else:
            authority = produced[body["under"]]
            if authority.get("step") != "enact":
                raise SeedError(
                    f"seed step {index} (adopt_instrument): 'under' points at a "
                    f"{authority.get('step')!r} step, not an enacted resolution.")
            item = governed_knowledge.adopt(
                conn, subject=body["subject"], level=body["level"], text=body["text"],
                adopted_by=body.get("adopted_by", "coo"),
                resolution_id=authority["resolution_id"],
                binds=body.get("binds"), requires=body.get("requires"))
            produced.append({"step": name, "instrument_id": item})
    return produced
