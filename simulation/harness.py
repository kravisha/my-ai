"""Runs the real organization, in its own database, under chosen conditions.

The harness starts `backend.main:app` exactly the way an operator does. It does
not import agents, stub providers, or drive the pipeline: the Controller spawns
real OS processes, those processes coordinate through a real SQLite database,
and the harness only chooses the environment they come up in and reads the
result afterwards.

**Isolation is the database, not a flag.** Each run gets its own directory and
its own `financial_intelligence.db`, pointed at by `FI_DB_PATH` - which
`backend/fi_db.py` honours and `backend/controller.py` already injects into every
spawned agent's environment. Nothing existing changes, no reader needs to filter,
concurrent runs cannot collide, and reset is deleting a directory.

A tag in a shared table would not have worked. `market_regime`,
`source_reliability` and a lens's bound `validity_conditions` are current-state
rows revised in place, so a simulated regime would permanently displace the real
estimate with no superseded row to discard.

**Shutdown is verified, not assumed.** A run that leaves agent processes behind
poisons every later run and eventually produces results from an organization
nobody is watching - this project has already accumulated twelve orphans that
way, and found them only by chasing a result an orphan was still producing. So
`stop()` checks the database and the log for evidence that the Controller's own
teardown actually ran, and reports `graceful=False` rather than assuming success.

Note on Windows: `terminate()` and `SIGTERM` bypass uvicorn's signal handling, so
the lifespan teardown - and with it `Controller.shutdown_agents` - never runs.
The process group plus `CTRL_BREAK_EVENT` below is what makes a clean stop
actually clean, and using anything else here silently reintroduces the orphans.

Internal rationale: INT-PHIL-0018, INT-PHIL-0019
"""

from __future__ import annotations

import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

from agents import coo
from backend import fi_db
from backend import version as backend_version
from simulation import metrics as metrics_module
from simulation import properties as properties_module
from simulation import faults as faults_module
from simulation import seeding
from simulation.scenario import Scenario

# How often the hold checks whether a fault is due. Fine enough that a
# fault lands within a heartbeat of its declared moment, coarse enough to
# cost nothing across a long run.
FAULT_POLL_SECONDS = 0.25

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = Path(os.environ.get("FI_SIM_RUNS_DIR") or (REPO_ROOT / "simulation" / "runs"))

# How long to wait for the organization to establish itself before giving up.
# The baseline population is spawned through the directive queue, one directive
# per Controller poll, so this must cover several poll cycles plus process
# startup for each role - generously, because a slow machine producing a false
# "never came up" would be indistinguishable from a real startup defect.
STARTUP_TIMEOUT_SECONDS = 60.0
STARTUP_POLL_SECONDS = 0.5

# How long to wait for a graceful stop before force-killing the process tree.
# Must exceed backend/controller.py's AGENT_STOP_GRACE_SECONDS, because the
# server spends that long waiting for its own agents before it can exit; a
# shorter wait here would kill the parent mid-teardown and manufacture the exact
# orphans this is meant to prevent.
SHUTDOWN_TIMEOUT_SECONDS = 30.0

# Written by backend/main.py's lifespan teardown. Its presence in the log is
# direct evidence that the graceful path ran rather than being skipped.
CLEAN_SHUTDOWN_MARKER = "[controller] agents stopped:"


class HarnessError(RuntimeError):
    pass


@dataclass
class RunResult:
    run_id: str
    directory: Path
    db_path: Path
    manifest_path: Path
    started_at: str
    finished_at: str
    ready_after_seconds: float | None
    graceful: bool
    shutdown_detail: str
    exit_code: int | None
    summary: dict | None = None

    @property
    def properties_passed(self) -> bool:
        """False if any declared property failed. A run with no properties is not
        a passing run - `asserted` is reported separately so the two are never
        confused."""
        if not self.summary:
            return False
        return self.summary["properties"]["failed"] == 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def model_is_available() -> bool:
    """Whether the agents will find a usable API key - not whether this process has one.

    `app/model_gateway.py` calls `load_dotenv()` at import, so an agent subprocess
    picks the key up from `.env` even when the harness's own environment has
    none. Reading `os.environ` alone got this backwards on the first real run:
    the manifest recorded `model_available: false` for a run whose Analysis was
    making real model calls throughout, which is exactly the provenance error the
    field exists to prevent - a summary that cannot tell a degraded run from a
    full one will compare two unlike runs as though they were alike."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    return bool(dotenv_values(REPO_ROOT / ".env").get("ANTHROPIC_API_KEY"))


def _code_version() -> str:
    """The commit the run executed, or an honest marker that it is unknown.

    A run whose code version is unrecorded cannot be replayed, so this never
    guesses; 'unknown' is a usable answer and a wrong sha is not. The
    implementation moved to backend/version.py when the agent registry needed
    the same fact (Directive E17) — one producer, so the two records can never
    disagree about which code was running."""
    return backend_version.code_version()


def _free_port() -> int:
    """A port the OS says is free, so concurrent runs cannot collide.

    Binding to port 0 and reading back the assignment leaves a small race - the
    port is released before uvicorn claims it - which is acceptable because the
    alternative, a fixed port, collides with the developer's own server every
    time and fails far more often."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def inherit_database(source_db: Path, destination: Path) -> None:
    """Start a run from another run's database, without touching the original.

    **Copied rather than reused.** Mutating the source would make day one
    unrepeatable the moment day two ran, and the whole value of a chain is being
    able to replay any generation from the state that preceded it.

    Uses SQLite's own backup API rather than a file copy: the source may have a
    WAL sidecar holding committed pages that `financial_intelligence.db` does not
    yet contain, so copying the one file can silently produce a database missing
    its most recent writes - which on a simulation chain would be the writes that
    matter most."""
    source_db = Path(source_db)
    if source_db.is_dir():
        source_db = source_db / "financial_intelligence.db"
    if not source_db.exists():
        raise HarnessError(f"cannot inherit from {source_db}: no database there")

    destination.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(source_db)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def latest_run(scenario_id: str | None = None, runs_dir: Path | None = None) -> Path | None:
    """The most recent completed run, optionally of one scenario.

    Completed means it has a summary; a run that crashed halfway is not a state
    anything should inherit."""
    root = Path(runs_dir or RUNS_DIR)
    if not root.exists():
        return None
    candidates = []
    for directory in root.iterdir():
        manifest_path = directory / "manifest.json"
        if not directory.is_dir() or not manifest_path.exists():
            continue
        if not (directory / "summary.json").exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if scenario_id and manifest.get("scenario_id") != scenario_id:
            continue
        candidates.append((manifest.get("started_at") or "", directory))
    return max(candidates)[1] if candidates else None


def _expected_population(config: dict[str, str] | None = None) -> set[str]:
    """Roles that must be running before a run counts as started.

    'controller' is the server process itself and 'coo' is bootstrapped directly
    by it; the rest arrive through the directive queue.

    **The scenario's own config decides the workforce.** `FI_BASELINE_<ROLE>`
    reaches the backend as an environment variable, so a scenario that staffs a
    role at zero gets an organization without it - and a readiness check reading
    this process's defaults would then wait sixty seconds for an agent nobody
    asked for and fail a run that had started correctly. Found by writing the
    first scenario that changes the population: every scenario until now used the
    default, so the harness had never been asked the question."""
    baseline = {}
    for role, default in coo.BASELINE_POPULATION.items():
        raw = (config or {}).get(f"FI_BASELINE_{role.upper()}")
        try:
            baseline[role] = default if raw is None else max(0, int(raw))
        except (TypeError, ValueError):
            baseline[role] = default
    return {"controller", "coo", *(role for role, count in baseline.items() if count > 0)}


class SimulationRun:
    """One execution of one scenario, in its own directory."""

    def __init__(
        self,
        scenario: Scenario,
        runs_dir: Path | None = None,
        run_id: str | None = None,
        inherit_from: Path | None = None,
    ):
        self.scenario = scenario
        self.inherit_from = Path(inherit_from) if inherit_from else None
        self.run_id = run_id or f"{scenario.id}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
        self.directory = Path(runs_dir or RUNS_DIR) / self.run_id
        self.db_path = self.directory / "financial_intelligence.db"
        # What the seed established, for the manifest. Empty unless the
        # scenario declared one.
        self.seeded: list = []
        self.manifest_path = self.directory / "manifest.json"
        self.log_path = self.directory / "backend.log"
        self.port = _free_port()
        self._process: subprocess.Popen | None = None
        self._log_handle = None
        self._started_at: str | None = None
        self._ready_after: float | None = None

    # -- environment ---------------------------------------------------------

    def _generation(self) -> int:
        """How many runs deep the inherited state is. A fresh run is generation 1."""
        if self.inherit_from is None:
            return 1
        parent = Path(self.inherit_from)
        manifest = parent / "manifest.json" if parent.is_dir() else parent.parent / "manifest.json"
        if not manifest.exists():
            return 2
        return int(json.loads(manifest.read_text(encoding="utf-8")).get("generation", 1)) + 1

    def build_env(self) -> dict[str, str]:
        """The environment the whole organization comes up in.

        `FI_DB_PATH` is applied after the scenario's config so that a scenario
        cannot reach the production database even if validation is ever loosened;
        the isolation boundary should not depend on a check somewhere else."""
        env = {**os.environ, **self.scenario.config}
        env["FI_DB_PATH"] = str(self.db_path)
        env["PYTHONUNBUFFERED"] = "1"
        # Since TQ-25/§74 the workforce waits for an operator login (addendum
        # 38 §3.3), and a harness run has no operator. Declared here rather
        # than left to the scenario config: every harness run is by definition
        # unattended, and a scenario that forgot the flag would come up with a
        # dormant organization and look like a mission that found nothing.
        # The backend records the unattended start in its status stream.
        env["SERVER_AUTOSTART_WORKFORCE"] = "1"
        return env

    # -- manifest ------------------------------------------------------------

    def write_manifest(self, **extra) -> dict:
        manifest = {
            "run_id": self.run_id,
            "scenario_id": self.scenario.id,
            "scenario_version": self.scenario.version,
            "scenario_lifecycle": self.scenario.lifecycle,
            "code_version": _code_version(),
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "port": self.port,
            "duration_seconds": self.scenario.duration_seconds,
            "config": dict(self.scenario.config),
            "db_path": str(self.db_path),
            # Recorded because a run without a reachable model is a materially
            # different organization - Analysis degrades - and a summary that
            # could not tell the two apart would compare unlike runs.
            "model_available": model_is_available(),
            "requires_model": self.scenario.requires_model,
            "expected_properties": list(self.scenario.expected_properties),
            "started_at": self._started_at,
            # Lineage. A run that began from another run's database is a
            # different experiment from one that began empty, and a summary
            # comparing the two without knowing which is which would attribute
            # inherited state to this run's conditions.
            "inherited_from": str(self.inherit_from) if self.inherit_from else None,
            "generation": self._generation(),
            **extra,
        }
        self.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        if self.scenario.requires_model and not model_is_available():
            raise HarnessError(
                f"scenario {self.scenario.id!r} declares requires_model but no ANTHROPIC_API_KEY is "
                "reachable, in this environment or in .env. Running it anyway would produce a "
                "summary describing a different organization than the scenario intends."
            )

        self.directory.mkdir(parents=True, exist_ok=True)
        if self.inherit_from is not None:
            inherit_database(self.inherit_from, self.db_path)
        # Governance before the organization starts (TQ-88). After any inherited
        # database and before the Controller, because an agent that came up
        # ungoverned and was governed a second later would have done one cycle of
        # work under rules nobody could see - which is precisely the state a
        # governed run exists to rule out.
        if self.scenario.seed:
            conn = fi_db.get_connection(self.db_path)
            try:
                fi_db.init_schema(conn)
                self.seeded = seeding.apply(conn, self.scenario.seed)
            finally:
                conn.close()

        self._started_at = _now()
        self.write_manifest()

        self._log_handle = self.log_path.open("w", encoding="utf-8", errors="replace")
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        self._process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.main:app",
             "--host", "127.0.0.1", "--port", str(self.port), "--log-level", "warning"],
            cwd=REPO_ROOT,
            env=self.build_env(),
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
            start_new_session=(sys.platform != "win32"),
        )

    def wait_until_ready(self, timeout: float = STARTUP_TIMEOUT_SECONDS) -> float:
        """Block until the whole baseline population is running.

        Readiness is judged from `agent_registry`, not from the HTTP port. A
        server that answers requests but never spawned its workforce is not a
        started organization, and a run measured from that moment would be
        measuring startup."""
        deadline = time.monotonic() + timeout
        began = time.monotonic()
        expected = _expected_population(self.scenario.config)
        last_seen: set[str] = set()

        while time.monotonic() < deadline:
            if self._process is not None and self._process.poll() is not None:
                raise HarnessError(
                    f"backend exited with code {self._process.returncode} during startup. "
                    f"See {self.log_path}"
                )
            last_seen = self._running_roles()
            if expected <= last_seen:
                self._ready_after = time.monotonic() - began
                return self._ready_after
            time.sleep(STARTUP_POLL_SECONDS)

        raise HarnessError(
            f"organization did not establish itself within {timeout}s. "
            f"Running roles: {sorted(last_seen) or 'none'}; expected {sorted(expected)}. "
            f"See {self.log_path}"
        )

    def _running_roles(self) -> set[str]:
        if not self.db_path.exists():
            return set()
        try:
            conn = fi_db.get_connection(self.db_path)
        except Exception:
            return set()
        try:
            rows = conn.fetchall(
                "SELECT role FROM agent_registry WHERE process_state = 'running' "
                "AND lifecycle_state = 'active'"
            )
            return {row["role"] for row in rows}
        except Exception:
            # The schema may not exist yet on the first poll; that is a normal
            # startup state and not worth distinguishing from "nothing running".
            return set()
        finally:
            conn.close()

    def stop(self, timeout: float = SHUTDOWN_TIMEOUT_SECONDS) -> tuple[bool, str]:
        """Ask the server to shut down cleanly, then verify that it did."""
        if self._process is None:
            return False, "never started"

        if self._process.poll() is not None:
            return False, f"already exited with code {self._process.returncode} before stop was requested"

        self._signal_shutdown()
        try:
            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            detail = self._force_kill()
            return False, detail

        return self._verify_clean_shutdown()

    def _signal_shutdown(self) -> None:
        assert self._process is not None
        if sys.platform == "win32":
            # SIGBREAK is in uvicorn's handled set on Windows; SIGTERM is not
            # delivered meaningfully and terminate() skips the handler entirely.
            self._process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            self._process.send_signal(signal.SIGINT)

    def _force_kill(self) -> str:
        assert self._process is not None
        if sys.platform == "win32":
            # /T because the agents are children of this process and killing only
            # the parent is how orphans are made.
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(self._process.pid)],
                capture_output=True,
            )
        else:
            os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)
        try:
            self._process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        return (
            "graceful shutdown timed out; the process tree was force-killed. Agent processes may "
            "have exited without recording a clean stop, so this run's population metrics are "
            "unreliable."
        )

    def _verify_clean_shutdown(self) -> tuple[bool, str]:
        """Two independent checks, because either alone can be satisfied wrongly.

        The log marker proves the teardown path executed. The registry proves it
        finished - an agent left as 'running' after the server is gone is an
        orphan or a process that died without recording its exit, and both are
        the condition that makes later runs untrustworthy."""
        log_text = self.log_path.read_text(encoding="utf-8", errors="replace") if self.log_path.exists() else ""
        marker_seen = CLEAN_SHUTDOWN_MARKER in log_text

        still_running = sorted(self._running_roles())

        if marker_seen and not still_running:
            return True, "clean: teardown ran and no agent is left running"
        if not marker_seen and still_running:
            return False, (
                f"teardown marker absent and {still_running} still marked running - the shutdown "
                "path did not execute"
            )
        if not marker_seen:
            return False, "teardown marker absent from the log; the shutdown path may not have executed"
        return False, f"teardown ran but {still_running} are still marked running"

    def close(self) -> None:
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None


def summarise_run(directory: str | Path) -> dict:
    """Read a finished run directory and write `summary.json` beside its manifest.

    Separated from `execute` so a run can be re-summarised after the fact -
    when a metric is added, or when a scenario's properties change and the
    question is whether an old run would still have satisfied them. The run's
    database is the durable record; the summary is a view of it and is always
    safe to regenerate."""
    directory = Path(directory)
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        raise HarnessError(f"no manifest at {manifest_path}; this is not a run directory")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    db_path = Path(manifest.get("db_path") or (directory / "financial_intelligence.db"))
    if not db_path.exists():
        raise HarnessError(f"run {manifest.get('run_id')} has no database at {db_path}")

    # Bounded to when this run started, so an inherited database's history is not
    # reported as this run's activity.
    collected = metrics_module.collect(db_path, since=manifest.get("started_at"))
    results = properties_module.evaluate_all(manifest.get("expected_properties") or [], collected)

    summary = {
        "run_id": manifest.get("run_id"),
        "scenario_id": manifest.get("scenario_id"),
        "scenario_version": manifest.get("scenario_version"),
        "code_version": manifest.get("code_version"),
        # Carried into the summary so a comparison between two runs cannot
        # silently put a degraded Analysis alongside a full one.
        "model_available": manifest.get("model_available"),
        "generation": manifest.get("generation", 1),
        "inherited_from": manifest.get("inherited_from"),
        "graceful_shutdown": manifest.get("graceful_shutdown"),
        "started_at": manifest.get("started_at"),
        "finished_at": manifest.get("finished_at"),
        "metrics": collected,
        "property_results": results,
        "properties": properties_module.summarise(results),
    }
    (directory / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _hold(run: "SimulationRun", scenario: Scenario) -> None:
    """Wait out the run, firing the scenario's faults as their moments arrive.

    A plain sleep when nothing is scheduled, so an ordinary scenario pays nothing
    for a feature it does not use. When faults *are* scheduled the wait becomes a
    poll, because the alternative - sleeping to each fault in turn - drifts by the
    execution time of every fault before it, and a fault that fires late in a
    ninety-second run is a fault aimed at a different organization than the one
    the scenario described.

    Faults never raise. A target that has already died is an ordinary thing to
    find during a fault run, and the manifest records what happened rather than
    the run ending on it."""
    if not scenario.faults:
        time.sleep(scenario.duration_seconds)
        return

    started = time.monotonic()
    while True:
        elapsed = time.monotonic() - started
        for fault in scenario.faults.due(elapsed):
            outcome = faults_module.fire(fault, run.db_path)
            print(f"[harness] fault {fault.describe()}: {outcome}", flush=True)
        if elapsed >= scenario.duration_seconds:
            return
        time.sleep(min(FAULT_POLL_SECONDS, scenario.duration_seconds - elapsed))


def execute(
    scenario: Scenario, runs_dir: Path | None = None, inherit_from: Path | None = None
) -> RunResult:
    """Start, hold for the scenario's duration, stop, and record.

    The stop is in a `finally` so a failure during the run cannot leave the
    organization alive - a harness that leaks the processes it exists to observe
    would be worse than no harness."""
    run = SimulationRun(scenario, runs_dir=runs_dir, inherit_from=inherit_from)
    graceful, detail = False, "not reached"
    try:
        run.start()
        run.wait_until_ready()
        _hold(run, scenario)
    finally:
        graceful, detail = run.stop()
        finished_at = _now()
        run.write_manifest(
            finished_at=finished_at,
            ready_after_seconds=run._ready_after,
            graceful_shutdown=graceful,
            shutdown_detail=detail,
            exit_code=run._process.returncode if run._process else None,
            faults=scenario.faults.record(),
        )
        run.close()

    # After the manifest is final, so the summary records the run as it ended.
    # Outside the `finally` deliberately: if the run itself failed, the exception
    # is what the caller needs, not a summary of a run that did not happen.
    summary = summarise_run(run.directory)

    return RunResult(
        run_id=run.run_id,
        directory=run.directory,
        db_path=run.db_path,
        manifest_path=run.manifest_path,
        started_at=run._started_at or "",
        finished_at=finished_at,
        ready_after_seconds=run._ready_after,
        graceful=graceful,
        shutdown_detail=detail,
        exit_code=run._process.returncode if run._process else None,
        summary=summary,
    )
