"""Scenario validation and the run harness.

The unit tests here check the parts a unit test can honestly check: parsing,
validation, environment construction, manifest contents. They deliberately do
not simulate a run - a mocked run would assert that the mock behaves like the
mock, which is the exact defect this whole subsystem exists to stop repeating.

The one test that proves the harness works is `test_real_run_*`, which launches
a real backend, a real agent population and a real database. It is marked
`simulation` and excluded from the default suite because it takes tens of
seconds.
"""

import json
import os
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

import conftest

from backend import fi_db
from simulation import harness
from simulation import scenario as scenario_module
from simulation.scenario import Scenario, ScenarioError

VALID = {
    "id": "sample",
    "version": 1,
    "lifecycle": "active",
    "description": "a scenario",
    "duration_seconds": 30,
    "config": {"FI_MARKET_PROVIDER_SEED": 42},
}


def write_scenario(directory: Path, name: str, **overrides) -> Path:
    body = {**VALID, "id": name, **overrides}
    path = directory / f"{name}.yaml"
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    return path


# -- parsing and validation --------------------------------------------------

def test_valid_scenario_loads(tmp_path):
    scenario = scenario_module.load(write_scenario(tmp_path, "sample"))
    assert scenario.id == "sample"
    assert scenario.duration_seconds == 30
    assert scenario.is_runnable


@pytest.mark.parametrize("missing", ["id", "version", "description", "duration_seconds", "lifecycle"])
def test_missing_required_key_is_refused(tmp_path, missing):
    body = {k: v for k, v in VALID.items() if k != missing}
    path = tmp_path / "sample.yaml"
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    with pytest.raises(ScenarioError, match="missing required keys"):
        scenario_module.load(path)


def test_unknown_lifecycle_is_refused(tmp_path):
    with pytest.raises(ScenarioError, match="lifecycle"):
        scenario_module.load(write_scenario(tmp_path, "sample", lifecycle="validated"))


def test_archived_and_draft_scenarios_are_not_runnable(tmp_path):
    assert not scenario_module.load(write_scenario(tmp_path, "a", lifecycle="draft")).is_runnable
    assert not scenario_module.load(write_scenario(tmp_path, "b", lifecycle="archived")).is_runnable
    assert scenario_module.load(write_scenario(tmp_path, "c", lifecycle="regression")).is_runnable


def test_scenario_shorter_than_startup_is_refused(tmp_path):
    """A run that ends before the population establishes itself measures startup."""
    with pytest.raises(ScenarioError, match="below the"):
        scenario_module.load(write_scenario(tmp_path, "sample", duration_seconds=5))


def test_filename_must_match_id(tmp_path):
    path = tmp_path / "filed_under_this.yaml"
    path.write_text(yaml.safe_dump({**VALID, "id": "declared_as_that"}), encoding="utf-8")
    with pytest.raises(ScenarioError, match="filed as"):
        scenario_module.load(path)


def test_scenario_may_not_set_the_database_path(tmp_path):
    """The isolation boundary is not a scenario's to move."""
    with pytest.raises(ScenarioError, match="isolation boundary"):
        scenario_module.load(write_scenario(tmp_path, "sample", config={"FI_DB_PATH": "/tmp/x.db"}))


def test_scenario_may_only_set_fi_variables(tmp_path):
    with pytest.raises(ScenarioError, match="only set FI_"):
        scenario_module.load(write_scenario(tmp_path, "sample", config={"PATH": "/evil"}))


def test_config_values_become_strings(tmp_path):
    """The manifest must record what the processes received, not what YAML inferred."""
    scenario = scenario_module.load(
        write_scenario(tmp_path, "sample", config={"FI_MARKET_PROVIDER_SEED": 42, "FI_REGIME_EWMA_ALPHA": 0.05})
    )
    assert scenario.config == {"FI_MARKET_PROVIDER_SEED": "42", "FI_REGIME_EWMA_ALPHA": "0.05"}


def test_property_without_a_name_is_refused(tmp_path):
    with pytest.raises(ScenarioError, match="has no name"):
        scenario_module.load(
            write_scenario(tmp_path, "sample", expected_properties=[{"metric": "queue_depth"}])
        )


def test_duplicate_scenario_ids_are_refused(tmp_path):
    write_scenario(tmp_path, "one")
    duplicate = tmp_path / "two.yaml"
    duplicate.write_text(yaml.safe_dump({**VALID, "id": "one"}), encoding="utf-8")
    # Caught by the filename check first, which is the same protection reached
    # earlier; either way two files cannot both answer to one id.
    with pytest.raises(ScenarioError):
        scenario_module.load_all(tmp_path)


def test_shipped_scenario_library_is_valid():
    """The library on disk must load, or `python -m simulation run` is broken."""
    scenarios = scenario_module.load_all()
    assert scenarios, "the scenario library is empty"
    assert "baseline_steady_state" in scenarios


# -- harness environment and manifest ----------------------------------------

def make_scenario(**overrides) -> Scenario:
    base = dict(
        id="unit", version=1, description="d", duration_seconds=30.0,
        lifecycle="active", config={}, expected_properties=[],
    )
    return Scenario(**{**base, **overrides})


def test_run_database_is_inside_the_run_directory(tmp_path):
    run = harness.SimulationRun(make_scenario(), runs_dir=tmp_path)
    assert run.db_path.parent == run.directory
    assert tmp_path in run.db_path.parents


def test_scenario_config_reaches_the_environment(tmp_path):
    run = harness.SimulationRun(make_scenario(config={"FI_MARKET_PROVIDER_SEED": "99"}), runs_dir=tmp_path)
    env = run.build_env()
    assert env["FI_MARKET_PROVIDER_SEED"] == "99"


def test_db_path_overrides_the_scenario_even_if_validation_is_bypassed(tmp_path):
    """Belt and braces.

    `scenario.py` refuses FI_DB_PATH, and the harness applies its own afterwards
    regardless. The isolation boundary should not depend on a check living
    somewhere else."""
    run = harness.SimulationRun(
        make_scenario(config={"FI_DB_PATH": "financial_intelligence.db"}), runs_dir=tmp_path
    )
    assert run.build_env()["FI_DB_PATH"] == str(run.db_path)


def test_two_runs_get_different_directories_and_ports(tmp_path):
    first = harness.SimulationRun(make_scenario(), runs_dir=tmp_path)
    second = harness.SimulationRun(make_scenario(), runs_dir=tmp_path)
    assert first.directory != second.directory
    assert first.port != second.port


def test_manifest_records_provenance(tmp_path):
    scenario = make_scenario(config={"FI_MARKET_PROVIDER_SEED": "42"}, version=3)
    run = harness.SimulationRun(scenario, runs_dir=tmp_path)
    run.directory.mkdir(parents=True)
    manifest = run.write_manifest()

    assert manifest["scenario_id"] == "unit"
    assert manifest["scenario_version"] == 3
    assert manifest["config"] == {"FI_MARKET_PROVIDER_SEED": "42"}
    assert manifest["code_version"], "a run with no recorded code version cannot be replayed"
    assert manifest["db_path"] == str(run.db_path)
    assert "model_available" in manifest
    assert json.loads(run.manifest_path.read_text(encoding="utf-8")) == manifest


def test_model_availability_falls_back_to_the_dotenv_file(monkeypatch):
    """Regression: the first real run recorded `model_available: false` for a run
    whose Analysis was making real model calls the whole time.

    `app/model_gateway.py` calls `load_dotenv()` at import, so an agent subprocess
    finds a key in `.env` that the harness's own environment does not have.
    Reading `os.environ` alone therefore describes the wrong organization."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(harness, "dotenv_values", lambda _: {"ANTHROPIC_API_KEY": "from-dotenv"})
    assert harness.model_is_available() is True


def test_model_availability_is_false_when_neither_source_has_a_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(harness, "dotenv_values", lambda _: {})
    assert harness.model_is_available() is False


def test_environment_key_alone_is_enough(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    monkeypatch.setattr(harness, "dotenv_values", lambda _: {})
    assert harness.model_is_available() is True


def test_run_requiring_a_model_refuses_to_start_without_a_key(tmp_path, monkeypatch):
    """Better to refuse than to produce a summary describing a different organization."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(harness, "dotenv_values", lambda _: {})
    run = harness.SimulationRun(make_scenario(requires_model=True), runs_dir=tmp_path)
    with pytest.raises(harness.HarnessError, match="requires_model"):
        run.start()


def test_stop_before_start_is_reported_not_raised(tmp_path):
    graceful, detail = harness.SimulationRun(make_scenario(), runs_dir=tmp_path).stop()
    assert graceful is False
    assert "never started" in detail


def test_expected_population_covers_every_baseline_role():
    """If a role is added to BASELINE_ROLES, readiness must wait for it too.

    Otherwise a run would begin measuring while part of the organization was
    still being spawned, and the first seconds of every scenario would describe
    a workforce that does not exist yet."""
    from agents import coo

    expected = harness._expected_population()
    assert set(coo.BASELINE_ROLES) <= expected
    assert "controller" in expected and "coo" in expected


# -- the real thing ----------------------------------------------------------

@pytest.mark.simulation
def test_real_run_starts_stops_and_leaves_nothing_behind(tmp_path):
    """A full run: real server, real agent processes, real database.

    Asserts the three things S1 exists to guarantee - the organization comes up,
    it shuts down through the path that stops its agents, and nothing is left
    running afterwards. The last is the one that matters most: an agent process
    surviving a run keeps writing to a database nobody is reading, and this
    project has already accumulated twelve of those."""
    scenario = make_scenario(
        id="harness_smoke",
        duration_seconds=scenario_module.MIN_DURATION_SECONDS,
        config={"FI_MARKET_PROVIDER_SEED": "42", "FI_SOCIAL_PROVIDER_SEED": "7"},
    )
    result = harness.execute(scenario, runs_dir=tmp_path)

    assert result.graceful, f"shutdown was not clean: {result.shutdown_detail}"
    assert result.db_path.exists(), "the run produced no database"
    assert result.ready_after_seconds is not None

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["finished_at"] and manifest["graceful_shutdown"] is True

    conn = fi_db.get_connection(result.db_path)
    try:
        rows = conn.fetchall("SELECT identity, role, process_state FROM agent_registry")
        roles = {row["role"] for row in rows}
        assert harness._expected_population() <= roles, f"population incomplete: {sorted(roles)}"

        still_running = [row["identity"] for row in rows if row["process_state"] == "running"]
        assert not still_running, f"agents left running after shutdown: {still_running}"

        # One row per role: the permanent slot identity means a respawn reuses
        # the row rather than adding one, so a duplicate here is a real defect.
        identities = [row["identity"] for row in rows]
        assert len(identities) == len(set(identities)), f"duplicate registry rows: {identities}"
    finally:
        conn.close()


@pytest.mark.simulation
def test_real_run_does_not_touch_the_production_database(tmp_path):
    """The isolation claim, checked rather than asserted in a comment.

    Reads the path from conftest rather than fi_db.DB_PATH, which the suite now
    redirects to a temp file for the whole session. Against DB_PATH this test
    would still pass and would no longer be testing anything: the file it
    watched would be one no simulation run was ever going to touch."""
    production = conftest.REAL_DB_PATH
    before = production.stat().st_mtime if production.exists() else None

    scenario = make_scenario(id="isolation_check", duration_seconds=scenario_module.MIN_DURATION_SECONDS)
    result = harness.execute(scenario, runs_dir=tmp_path)

    assert result.db_path.exists()
    after = production.stat().st_mtime if production.exists() else None
    assert before == after, "the production database was modified by a simulation run"
