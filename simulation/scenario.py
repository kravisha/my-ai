"""A scenario: the conditions one simulation run is executed under.

A scenario is deliberately thin. Every knob the organization has is already an
`FI_*` environment variable, and `backend/controller.py` already propagates the
environment to every agent process it spawns - so a scenario is a set of those
values, a duration, and the properties the run is expected to satisfy.

Nothing here generates data. The synthetic providers already produce seeded,
realistic market surfaces and social streams; a scenario selects among them
rather than replacing them.

**Properties, not transcripts.** A scenario states what must hold across repeats
of the run, never what the run should output. `agents/analysis.py` calls a
language model, so anything downstream of that call differs between two runs of
the same seed. Asserting on model prose would produce a regression suite that
fails for reasons nobody can act on, and an organization learns quickly to
ignore a suite like that. See `expected_properties`.

Internal rationale: INT-PHIL-0016, INT-PHIL-0018
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from simulation import faults as faults_module, governance_events, seeding

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"

# DRAFT -> ACTIVE -> REGRESSION -> ARCHIVED. The proposal's VALIDATED and
# DEPRECATED states are omitted: no distinct actor validates a scenario, so
# VALIDATED would be a label nobody applies, and ARCHIVED already covers a
# scenario that has been retired.
LIFECYCLE_STATES = ("draft", "active", "regression", "archived")

# A scenario may only set FI_* variables, and never FI_DB_PATH. The database
# location is the isolation boundary and belongs to the harness; a scenario able
# to set it could point a run at the production database, which is the one thing
# the whole design exists to prevent.
CONFIG_KEY_PATTERN = re.compile(r"^FI_[A-Z0-9_]+$")
FORBIDDEN_CONFIG_KEYS = frozenset({"FI_DB_PATH"})

# Long enough that no scenario finishes before the organization has finished
# coming up. The baseline population is spawned through the directive queue and
# needs several poll cycles to establish itself.
MIN_DURATION_SECONDS = 15.0


class ScenarioError(ValueError):
    """A scenario file that cannot be trusted to describe a run."""


@dataclass(frozen=True)
class Scenario:
    id: str
    version: int
    description: str
    duration_seconds: float
    lifecycle: str
    config: dict[str, str]
    expected_properties: list[dict] = field(default_factory=list)
    requires_model: bool = False
    # What goes wrong during the run, and when. Empty for every scenario
    # that is about ordinary operation - see simulation/faults.py for why
    # the actions are as few as they are.
    faults: faults_module.FaultSchedule = field(default_factory=faults_module.FaultSchedule)
    # Governance established in the run's database before the Controller starts
    # (TQ-88). Empty for every scenario about an ungoverned organization, which
    # is all of them until one is about a governed one. See simulation/seeding.py
    # for why this is a closed vocabulary over the production API rather than SQL.
    seed: list = field(default_factory=list)

    # Governance that happens *during* the run rather than before it: a release
    # applied, judged and reversed while agents are working. See
    # simulation/governance_events.py for why this is not a fault.
    governance_schedule: governance_events.GovernanceSchedule = field(
        default_factory=governance_events.GovernanceSchedule)
    source_path: Path | None = None

    @property
    def is_runnable(self) -> bool:
        return self.lifecycle in ("active", "regression")


def load(path: str | Path) -> Scenario:
    path = Path(path)
    if not path.exists():
        raise ScenarioError(f"no scenario file at {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ScenarioError(f"{path.name} is not valid YAML: {exc}") from exc
    return from_dict(raw, source_path=path)


def load_all(directory: str | Path = SCENARIOS_DIR) -> dict[str, Scenario]:
    """Every scenario in a directory, keyed by id.

    Raises on a duplicate id rather than letting one silently win. Two scenarios
    claiming the same id would make a run directory's manifest ambiguous about
    which conditions produced it, and provenance is the point of the manifest."""
    scenarios: dict[str, Scenario] = {}
    for candidate in sorted(Path(directory).glob("*.yaml")):
        scenario = load(candidate)
        if scenario.id in scenarios:
            raise ScenarioError(
                f"scenario id {scenario.id!r} is claimed by both "
                f"{scenarios[scenario.id].source_path.name} and {candidate.name}"
            )
        scenarios[scenario.id] = scenario
    return scenarios


def from_dict(raw: dict, source_path: Path | None = None) -> Scenario:
    where = source_path.name if source_path else "scenario"
    if not isinstance(raw, dict):
        raise ScenarioError(f"{where} must be a mapping at the top level")

    missing = {"id", "version", "description", "duration_seconds", "lifecycle"} - set(raw)
    if missing:
        raise ScenarioError(f"{where} is missing required keys: {sorted(missing)}")

    scenario_id = raw["id"]
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise ScenarioError(f"{where} has an empty id")
    if source_path is not None and source_path.stem != scenario_id:
        raise ScenarioError(
            f"{where} declares id {scenario_id!r} but is filed as {source_path.stem!r}. "
            "The filename is how a run manifest is traced back to its scenario, so the two must agree."
        )

    lifecycle = raw["lifecycle"]
    if lifecycle not in LIFECYCLE_STATES:
        raise ScenarioError(f"{where} has lifecycle {lifecycle!r}, not one of {LIFECYCLE_STATES}")

    duration = float(raw["duration_seconds"])
    if duration < MIN_DURATION_SECONDS:
        raise ScenarioError(
            f"{where} runs for {duration}s, below the {MIN_DURATION_SECONDS}s minimum. A run that "
            "ends before the baseline population has established itself measures startup, not the "
            "organization."
        )

    config = _validated_config(raw.get("config") or {}, where)
    properties = _validated_properties(raw.get("expected_properties") or [], where)
    # Parsed at load time so an unspellable fault is refused now rather than at
    # second 40 of a five-minute run that has already been wasted.
    try:
        schedule = faults_module.parse(raw.get("faults"))
    except faults_module.FaultError as bad:
        raise ScenarioError(f"{where}: {bad}") from bad
    # Same reasoning as the faults above: a seed that could never run costs a
    # load error now rather than five minutes and an untrustworthy summary.
    try:
        seed = seeding.validate(raw.get("seed"))
    except seeding.SeedError as bad:
        raise ScenarioError(f"{where}: {bad}") from bad
    # And again for the governance schedule: a release event nobody can spell is
    # a run that goes green having done nothing (§136).
    try:
        governance = governance_events.parse(raw.get("governance_schedule"))
    except governance_events.GovernanceEventError as bad:
        raise ScenarioError(f"{where}: {bad}") from bad

    return Scenario(
        id=scenario_id,
        version=int(raw["version"]),
        description=str(raw["description"]).strip(),
        duration_seconds=duration,
        lifecycle=lifecycle,
        config=config,
        expected_properties=properties,
        requires_model=bool(raw.get("requires_model", False)),
        faults=schedule,
        seed=seed,
        governance_schedule=governance,
        source_path=source_path,
    )


def _validated_config(config: dict, where: str) -> dict[str, str]:
    if not isinstance(config, dict):
        raise ScenarioError(f"{where}'s config must be a mapping")
    validated = {}
    for key, value in config.items():
        if key in FORBIDDEN_CONFIG_KEYS:
            raise ScenarioError(
                f"{where} sets {key}, which belongs to the harness. The run database is the "
                "isolation boundary and a scenario must not be able to move it."
            )
        if not CONFIG_KEY_PATTERN.match(str(key)):
            raise ScenarioError(
                f"{where} sets {key!r}. A scenario may only set FI_* variables - anything else "
                "would change the process environment in ways the manifest does not record."
            )
        # Coerced to str because this becomes a subprocess environment, where
        # every value is a string. Doing it here means the manifest records
        # exactly what the processes received, not what the YAML parser inferred.
        validated[str(key)] = str(value)
    return validated


def _validated_properties(properties: list, where: str) -> list[dict]:
    """Shape-checked here; evaluated by the metrics layer.

    Kept permissive on `assert`/`value` so new property kinds can be added
    without a schema change, but strict on `name` and `metric`, because an
    unnamed property produces a pass/fail nobody can interpret."""
    if not isinstance(properties, list):
        raise ScenarioError(f"{where}'s expected_properties must be a list")
    validated = []
    for index, prop in enumerate(properties):
        if not isinstance(prop, dict):
            raise ScenarioError(f"{where} property #{index} is not a mapping")
        for required in ("name", "metric"):
            if not prop.get(required):
                raise ScenarioError(f"{where} property #{index} has no {required}")
        validated.append(dict(prop))
    return validated
