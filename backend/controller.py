"""The Controller is the sole thing that ever spawns or retires an agent
process ("all agents will be spawned only by the controller... the COO...
is officer who will be directing the controller to spawn an agent on demand
and also... to retire an agent... in a controlled and smooth manner").
Mechanics only - it never invents policy, it only executes directives the
COO has placed in the coo_directives table.

**The Controller is the backend server's own agent identity** (owner
clarification, 2026-08-15): the server does not *contain* a Controller, it
comes up *as* one. So unlike every other agent it is not a spawned
subprocess - it lives inside backend/main.py's event loop - but it is
otherwise a first-class agent: it registers itself in agent_registry
(bootstrap_self), heartbeats, and marks itself gone on clean shutdown,
satisfying "every agent has a defined role, identity, state... health
state, and durable organizational record" (Org Addendum §2). It is the
first agent to exist, and it then creates COO - the startup order the specs
give literally (Consolidated §2, Org Addendum §13).

The authority split this implements (Org Addendum §15): the COO decides
operational need and *requests*; the Controller is the exclusive executor.
COO never touches a process directly - it only ever enqueues directives.

Critically, role "controller" must never appear in agents/coo.py's
BASELINE_ROLES: the Controller is the running server, so a COO that tried
to "respawn" it would be asking the Controller to Popen an agents/
controller.py that deliberately does not exist. tests/test_controller.py
guards this invariant explicitly.

Retirement is never a kill: it only ever sets a flag (fi_db.request_
retirement) that the target agent's own run loop notices and acts on
(agents/base.py) - "controlled and smooth" in the literal sense of the
agent finishing on its own terms.
"""

import os
import subprocess
import time
import sys
from pathlib import Path

from backend import fi_db, watch
from backend.version import code_version

# Environment every spawned agent gets on top of the Controller's own.
#
# PYTHONUNBUFFERED matters more than it looks. Agents inherit the backend's
# stdout, which in any real run is redirected to a log file - and Python
# block-buffers stdout when it is not a terminal. Without this, an agent's
# prints sit in a 4-8KB buffer and never reach the log, so the one place an
# agent explains its own reasoning ("[analysis] taking report #7: cross-check
# answered...") is invisible during exactly the manual verification runs that
# have found every timing defect in this project.
AGENT_ENV = {"PYTHONUNBUFFERED": "1"}

# How long a shutdown waits for agents to exit on their own before terminating
# the stragglers. Agents poll roughly every second, but Analysis can sit inside a
# deep-reasoning call for ~20s, and a server stop should not wait that long - so
# this is deliberately shorter than the slowest cycle. Most agents exit within a
# second; the rest are terminated, which is a worse exit than they would have
# chosen and a much better one than being orphaned.
AGENT_STOP_GRACE_SECONDS = float(os.environ.get("FI_AGENT_STOP_GRACE_SECONDS", "5"))

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# How long the COO may go silent before the Controller treats it as failed rather
# than busy. The same measured threshold the COO applies to everyone else - see
# agents/coo.py, where it was raised to 45s after a real incident in which slow
# model calls were mistaken for crashes and duplicates were spawned. Imported
# lazily inside the watch to avoid a circular import at module level.
COO_SILENCE_THRESHOLD_SECONDS = 45.0

# How often the watch actually runs. The poll loop ticks about once a second, and
# a registry read per tick would be work for nothing: silence is measured in tens
# of seconds, so checking for it five times a minute is enough to notice within
# one threshold.
WATCH_INTERVAL_SECONDS = 12.0

# A crash loop is not a failure to recover from; it is a failure to keep trying
# at. Beyond this many incidents in the window, the Controller stops respawning
# and escalates, which is the framework's §13 degraded state entered
# deliberately rather than by exhaustion.
MAX_RECOVERIES = 3
RECOVERY_WINDOW_SECONDS = 600.0

# How long a COO that has been started is still considered to be starting up.
#
# **A spawn in flight is not a failure**, and this constant is the difference
# between a watcher and a fork bomb. The first version of this watch had no such
# notion: the poll loop's first tick ran microseconds after bootstrap_coo, found
# no registry row for a process that had existed for less than a millisecond,
# declared it missing and started a second one. Verified against a real server, it
# produced six COO processes under one permanent identity in under two minutes -
# the exact duplicate-executive hazard this watch was written to prevent, caused
# by the watch.
#
# The same value and the same reasoning as agents/coo.py's
# SPAWN_IN_FLIGHT_WINDOW_SECONDS, which solves this problem for every agent COO
# spawns. That precedent existed and was not applied here, which is the whole
# lesson.
COO_SPAWN_GRACE_SECONDS = 30.0

CONTROLLER_ROLE = "controller"


def _slot_identity(role: str) -> str:
    """Slot 1 of a role, for the two agents that are never allocated.

    The Controller and COO bootstrap themselves before any allocation policy
    could run - the Controller *is* the server process, and COO is spawned
    directly because there is no COO yet to have asked for one. Both are
    singletons by construction.

    Every other role goes through fi_db.allocate_slot, which reuses the slot of
    an agent that needs its process back and opens a new one only when the role
    genuinely needs more agents than it has. Identity stays permanent either way
    (addendum 5 §4): a slot outlives every process that runs under it, so a
    respawn keeps the name, assignment span and performance record rather than
    starting over."""
    return f"{role}-1"


# Who the Controller is, available without a Controller.
#
# The identity is fixed by the role, not discovered from any instance's state, so
# a caller that only needs to recognize the Controller in a roster should not have
# to construct one - constructing one opens a database. backend/main.py's retire
# route is exactly that caller: it must refuse to retire controller-1, and that is
# a name comparison, not a question about a live object.
CONTROLLER_IDENTITY = _slot_identity(CONTROLLER_ROLE)


class Controller:
    # What this role executes. Named rather than implied by the dispatch chain,
    # so an objection on jurisdiction grounds can state the scope it is objecting
    # against instead of just reporting that a branch fell through.
    HANDLED_DIRECTIVE_TYPES = ("spawn", "retire", "resume")

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(fi_db.DB_PATH)
        self.conn = fi_db.get_connection(self.db_path)
        fi_db.init_schema(self.conn)
        # Popen handles this Controller instance has itself spawned - only the
        # spawning process can hold/control these; not the same as everyone
        # in agent_registry, which also reflects agents from a prior run.
        self._processes: dict[str, subprocess.Popen] = {}
        self.identity = CONTROLLER_IDENTITY
        # When the COO watch last ran. None means never, so the first poll tick
        # checks immediately rather than waiting out an interval.
        self._last_watch_at: float | None = None
        # When this process last started a COO, so the watch can tell "coming up"
        # from "gone". Per-process by nature; the registry's spawned_at covers the
        # case where another process did the spawning.
        self._coo_spawn_at: float | None = None

    def bootstrap_self(self) -> str:
        """Registers the Controller as an agent in its own right - the first
        agent to exist, before it creates COO (Consolidated §2: "server
        starts; Controller Agent starts; Controller creates COO as the first
        executive agent").

        Reuses fi_db.register_agent unchanged: its ON CONFLICT path already
        handles a permanent identity coming back to life under a new pid,
        which here is exactly what a server restart is. No subprocess is
        spawned - the Controller *is* this process (os.getpid() is the
        server's own pid), which is what makes it different from every other
        agent and why it must never be in BASELINE_ROLES.

        Also records a first heartbeat immediately, so the row is never
        momentarily stale-looking to a COO health check that happens to run
        between registration and the first poll-loop tick."""
        fi_db.register_agent(
            self.conn, self.identity, CONTROLLER_ROLE, os.getpid(),
            behavior_version=code_version(),
        )
        fi_db.record_heartbeat(self.conn, self.identity)
        self._establish_world_clock()
        return self.identity

    def _establish_world_clock(self) -> None:
        """Fix what time it is in the simulated world, before anything is spawned.

        Written once by the first process to exist, because a clock each agent
        derived for itself would be one clock per process: they would agree on
        the rate and disagree about when the run started, which is the same thing
        as disagreeing about the date.

        Absent config leaves no row, and no row means real time - scale 1 with
        the epoch at start, which is the same arithmetic rather than a special
        case. So an ordinary server is completely unaffected by this."""
        epoch = os.environ.get("FI_SIM_EPOCH")
        scale = os.environ.get("FI_SIM_TIME_SCALE")
        if not epoch and not scale:
            return

        from simulation.clock import DEFAULT_EPOCH

        fi_db.set_simulation_clock(
            self.conn,
            epoch=epoch or DEFAULT_EPOCH,
            scale=float(scale or 1.0),
            enforce_sessions=os.environ.get("FI_SIM_ENFORCE_SESSIONS", "0") not in ("0", "", "false"),
        )

    def record_self_heartbeat(self) -> None:
        """Called once per poll-loop tick by backend/main.py. The loop
        already runs every ~1s, far inside agents/coo.py's 45s
        HEALTH_STALE_THRESHOLD_SECONDS, so this needs no timer of its own.

        If the server dies while COO (a separate surviving subprocess) keeps
        running, this heartbeat stops advancing and COO's health evaluation
        correctly marks the Controller 'crashed' - a real signal that did
        not exist before, and one nothing will try to auto-respawn, which is
        right: a dead server cannot restart itself from the inside."""
        fi_db.record_heartbeat(self.conn, self.identity)

    def shutdown_agents(self, grace_seconds: float = AGENT_STOP_GRACE_SECONDS) -> dict:
        """Stop every agent this Controller spawned, before the server goes away.

        Without this they are orphaned. `subprocess.Popen` children outlive the
        parent, so stopping the backend left a full agent population running,
        still heartbeating, still writing to the database - and a later backend
        started against the same database would find them healthy and never
        respawn, so two generations of agents ran concurrently. Found while
        verifying something else entirely: twelve orphaned processes from earlier
        runs were still alive and producing detector events.

        Asked, not killed, wherever possible. The flag is a database row the
        agent polls, exactly as retirement is, so an agent finishes the cycle it
        is in rather than being cut off mid-write. Force-terminating is the
        fallback for stragglers only, because a bounded shutdown matters more
        than the last cycle of an agent that is not responding - Analysis can sit
        inside a deep-reasoning call for 20 seconds, and a server stop should not
        wait that long.

        Returns what happened to each, so shutdown is auditable rather than
        silent."""
        stopped, terminated = [], []
        deadline = time.monotonic() + grace_seconds
        pending = dict(self._processes)

        # The stop flag is re-asserted on every pass, not set once. An agent
        # spawned moments before shutdown may not have registered yet, so its
        # row does not exist and the first UPDATE touches nothing - and the
        # agent then INSERTs a fresh row defaulting to "no stop requested",
        # erasing a signal that was sent before it existed. No amount of
        # pre-setting wins that race; re-asserting until the process is gone
        # does, whatever order startup and shutdown happen to interleave in.
        while pending and time.monotonic() < deadline:
            for identity, process in list(pending.items()):
                if process.poll() is not None:
                    stopped.append(identity)
                    del pending[identity]
                    continue
                fi_db.request_process_stop(self.conn, identity)
            if pending:
                time.sleep(0.25)

        for identity, process in pending.items():
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
            terminated.append(identity)

        for identity in stopped + terminated:
            # The agent's own finally block reports this when it exits cleanly;
            # doing it here too covers the terminated case, where it never got
            # the chance. Idempotent either way.
            fi_db.mark_process_stopped(self.conn, identity)

        self._processes.clear()
        return {"stopped": stopped, "terminated": terminated}

    def shutdown_self(self) -> None:
        """Clean server shutdown reads as a clean process stop, not a crash -
        the same distinction agents/base.py's finally block makes for
        subprocess agents.

        Note it reports process_state only: a stopped server is *not* a
        retired Controller. The Controller stays organizationally active, so
        restarting the server brings it straight back into service rather
        than requiring a resume."""
        fi_db.mark_process_stopped(self.conn, self.identity)

    def bootstrap_coo(self) -> str:
        """The one spawn that bypasses the directive queue entirely - there's no
        COO yet to have placed a directive, so the Controller spawns it directly
        as its first action on server startup (addendum 6 §2 step 3: "the
        controller spawns the COO privileged client as the first managed
        process"). Every other agent, including the baseline population COO
        itself will ask for once running, goes through the normal directive queue
        in process_next_directive.

        Now goes through respawn_coo, so startup cannot create a second COO
        beside one that survived an unclean shutdown. A live COO is adopted
        rather than duplicated, and the reconciliation is recorded rather than
        assumed - see reconcile_on_start."""
        identity = _slot_identity(watch.COO_ROLE)
        try:
            return self.respawn_coo(identity)
        except RuntimeError:
            # A COO is already alive and heartbeating. Adopting it is the correct
            # outcome, not a failure: the organization has the executive it needs
            # and this process simply did not start it.
            return identity

    # --- Duty of care toward the COO ------------------------------------
    #
    # The Fault Tolerance Framework's §4: management is not only authority over
    # work, it is being able to notice when a subordinate stops producing it.
    # The Controller is COO's manager (docs/organization.yaml) and the only thing
    # that may start a process (addendum 11 §15), so detection and the authority
    # to act sit on the same entity and no new authority had to be invented.
    #
    # Before this, nothing watched the COO at all. It was spawned once at startup
    # and is deliberately not in BASELINE_POPULATION, so if it died the health
    # evaluation that notices every *other* agent's silence died with it: crashed
    # agents stayed marked 'running' forever, the baseline stopped being enforced,
    # and nothing reported any of it.

    def watch_coo(self, now: float | None = None) -> dict | None:
        """One pass of the framework's DETECTION -> DIAGNOSIS -> RECOVERY cycle
        over the one subordinate this Controller is responsible for.

        Returns what it did, or None if the watch was not due yet. Rate-limited
        internally rather than by the caller, so the poll loop stays a loop and
        the cadence lives next to the threshold it is derived from."""
        now = time.monotonic() if now is None else now
        if self._last_watch_at is not None and now - self._last_watch_at < WATCH_INTERVAL_SECONDS:
            return None
        self._last_watch_at = now

        identity = _slot_identity(watch.COO_ROLE)
        agent = fi_db.get_agent(self.conn, identity)

        # A spawn that has not landed yet is not a failure. Checked before
        # anything else, because every other branch below reads a registry row
        # that a starting process has not written yet.
        if self._coo_spawn_in_flight(agent, now):
            return {"action": "none", "reason": "a COO spawn is still coming up"}

        if agent is None:
            # Never registered, and long enough ago that it should have. The
            # spawn either failed or the process died before its first heartbeat.
            return self._recover_coo(
                identity, symptom="COO has no registry row", last_healthy=None, now=now
            )

        # §7: intentional inactivity is not failure, and asking first is the
        # whole difference between a watcher and a nuisance.
        if agent["lifecycle_state"] == fi_db.LIFECYCLE_DORMANT:
            return {"action": "none", "reason": "COO is dormant, which is a decision rather than a fault"}

        age = fi_db.heartbeat_age_seconds(agent)
        threshold = watch.silence_threshold_seconds(watch.COO_ROLE, COO_SILENCE_THRESHOLD_SECONDS)

        if age is not None and age < threshold:
            # Healthy. If this Controller had an incident open on it, the
            # capability is back and the incident is closed - the other half of
            # the lifecycle, and the half a watcher that only ever files is
            # missing.
            incident = fi_db.open_incident_for(self.conn, identity)
            if incident is not None:
                fi_db.record_recovery(
                    self.conn, incident["id"], f"heartbeat resumed ({round(age, 1)}s old)"
                )
                return {"action": "recovered", "incident": incident["id"]}
            return {"action": "none", "reason": "COO is heartbeating"}

        return self._recover_coo(
            identity,
            now=now,
            symptom=(
                "COO has never heartbeated"
                if age is None
                else f"COO heartbeat is {round(age, 1)}s old, past the {threshold}s threshold"
            ),
            last_healthy=agent["last_heartbeat_at"],
            agent=agent,
        )

    def _coo_spawn_in_flight(self, agent, now: float) -> bool:
        """Whether a COO is between "started" and "signalling".

        Two sources, because one process's memory is not the whole truth. This
        process knows what it started (`_coo_spawn_at`); the registry's
        `spawned_at` covers a COO some other process started, which is exactly the
        server-restart case. An agent that has already heartbeated is not coming
        up any more, whichever source claimed it was."""
        if self._coo_spawn_at is not None and now - self._coo_spawn_at < COO_SPAWN_GRACE_SECONDS:
            if agent is None or agent["last_heartbeat_at"] is None:
                return True

        if agent is not None and agent["last_heartbeat_at"] is None:
            age = fi_db.seconds_since(agent["spawned_at"])
            if age is not None and age < COO_SPAWN_GRACE_SECONDS:
                return True

        return False

    def _recover_coo(self, identity, symptom, last_healthy, agent=None, now=None) -> dict:
        """Detection, diagnosis, and either recovery or escalation."""
        # The Day Zero gate, consulted by the watcher too. When the startup
        # reference certification is not READY, backend/main.py deliberately
        # never bootstraps the COO - and a watcher that "recovered" it would
        # wake the exact workforce the gate exists to keep blocked (found
        # live: a FAILED-certification run came up fully staffed because this
        # branch treated the missing COO as a fault). Intentional inactivity
        # is not failure - the same §7 reasoning as the dormancy branch in
        # watch_coo - so this asks the same authority the gate asked, not a
        # separate flag that could drift from it.
        from backend import reference_data  # lazy: main.py imports this module first
        if not reference_data.is_ready(self.conn):
            return {
                "action": "none",
                "reason": "reference data is not READY - the workforce is deliberately blocked, "
                          "not failed (Day Zero rule; see backend/main.py's startup gate)",
            }
        incident = fi_db.open_incident_for(self.conn, identity)
        if incident is None:
            incident_id = fi_db.open_incident(
                self.conn,
                subject_identity=identity,
                subject_role=watch.COO_ROLE,
                detected_by=self.identity,
                symptom=symptom,
                last_healthy_at=last_healthy,
                evidence={"process_state": (agent or {}).get("process_state")},
            )
        else:
            incident_id = incident["id"]

        # §8 Diagnosis: what does the silence mean? A clean stop is a different
        # event from a crash, and the framework is explicit that recovery should
        # not be disruptive until the difference has been established.
        process_state = (agent or {}).get("process_state")
        if process_state == fi_db.PROCESS_STOPPED:
            diagnosis = "process stopped cleanly without being retired; the role is unstaffed"
        elif agent is None:
            diagnosis = "no registry row; the spawn never established itself"
        else:
            diagnosis = "process claims to be running but has stopped signalling; treating as crashed"
        fi_db.record_diagnosis(self.conn, incident_id, diagnosis)

        # A crash loop is not something to keep answering with another spawn.
        recent = fi_db.count_incidents_since(self.conn, identity, RECOVERY_WINDOW_SECONDS)
        if recent > MAX_RECOVERIES:
            fi_db.escalate_incident(
                self.conn,
                incident_id,
                escalated_to="human operator",
                reason=(
                    f"{recent} COO failures within {int(RECOVERY_WINDOW_SECONDS)}s; refusing to "
                    f"respawn again. The organization is running without an executive: no agent "
                    f"health evaluation and no baseline enforcement until this is resolved."
                ),
            )
            return {"action": "escalated", "incident": incident_id, "failures": recent}

        try:
            self.respawn_coo(identity, now=now)
        except Exception as failure:  # noqa: BLE001 - recorded, not swallowed
            fi_db.escalate_incident(
                self.conn,
                incident_id,
                escalated_to="human operator",
                reason=f"respawn failed: {failure}",
            )
            return {"action": "escalated", "incident": incident_id, "error": str(failure)}

        fi_db.record_action(self.conn, incident_id, "respawned COO")
        return {"action": "respawned", "incident": incident_id}

    def respawn_coo(self, identity: str | None = None, now: float | None = None) -> str:
        """Start a COO process, having first established that one is not already
        running.

        The check is the point. `bootstrap_coo` used to spawn unconditionally,
        which was harmless while it only ran at startup and catastrophic the
        moment anything could call it twice: an unclean server death leaves the
        COO subprocess alive - subprocess children outlive their parent - so a
        restart produced *two* live processes under one permanent identity, both
        evaluating health and both filing directives, with the registry showing
        one pid.

        Liveness is judged by heartbeat rather than by a Popen handle, because a
        handle is per-process and the case that matters is precisely the one
        where this process did not start the survivor."""
        identity = identity or _slot_identity(watch.COO_ROLE)
        agent = fi_db.get_agent(self.conn, identity)

        # Two ways a second process would be one too many, and both refuse here
        # rather than at the call site. A guard that lives in the caller is a
        # guard the next caller does not have: the runaway that made this
        # necessary came from a path where the *incident* was deduplicated and
        # the *spawn* was not.
        # `now` is threaded from the watch rather than read here, so the two
        # cannot disagree about what time it is. They are the same clock in
        # production and were not under test, which is how a caller that had
        # already waited out the grace period was refused by a guard that had
        # not.
        if self._coo_spawn_in_flight(agent, time.monotonic() if now is None else now):
            raise RuntimeError(
                f"refusing to spawn a second {identity}: one was started less than "
                f"{COO_SPAWN_GRACE_SECONDS}s ago and has not reported yet"
            )

        if agent is not None:
            age = fi_db.heartbeat_age_seconds(agent)
            threshold = watch.silence_threshold_seconds(watch.COO_ROLE, COO_SILENCE_THRESHOLD_SECONDS)
            if age is not None and age < threshold:
                raise RuntimeError(
                    f"refusing to spawn a second {identity}: one is alive with a "
                    f"{round(age, 1)}s-old heartbeat"
                )
            # Believed to be running, not signalling, and this process does not
            # own it. Record what is true before replacing it.
            if agent["process_state"] == fi_db.PROCESS_RUNNING:
                fi_db.mark_process_crashed(self.conn, identity)

        fi_db.clear_process_stop(self.conn, identity)
        env = {**os.environ, "FI_DB_PATH": self.db_path, **AGENT_ENV}
        process = subprocess.Popen(
            [sys.executable, "-m", "agents.coo", identity],
            cwd=PROJECT_ROOT,
            env=env,
        )
        self._processes[identity] = process
        self._coo_spawn_at = time.monotonic()
        return identity

    def reconcile_on_start(self) -> dict:
        """§10: a restarted process must not assume the world stayed frozen while
        it was away.

        The one question this Controller can answer cheaply and must not get
        wrong: is there already a COO? An unclean shutdown leaves one running, and
        the old unconditional spawn would have created a second."""
        identity = _slot_identity(watch.COO_ROLE)
        agent = fi_db.get_agent(self.conn, identity)
        if agent is None:
            return {"coo": "absent"}

        age = fi_db.heartbeat_age_seconds(agent)
        threshold = watch.silence_threshold_seconds(watch.COO_ROLE, COO_SILENCE_THRESHOLD_SECONDS)
        if age is not None and age < threshold:
            return {"coo": "adopted", "heartbeat_age_seconds": round(age, 1)}
        if agent["lifecycle_state"] == fi_db.LIFECYCLE_DORMANT:
            return {"coo": "dormant"}
        return {"coo": "stale", "heartbeat_age_seconds": None if age is None else round(age, 1)}

    def process_next_directive(self) -> bool:
        """Processes one pending directive if any exist. Returns True if a
        directive was processed, False if the queue was empty - lets the
        caller (a polling loop) decide cadence rather than baking a sleep
        in here."""
        directive = fi_db.fetch_next_pending_directive(self.conn)
        if directive is None:
            return False

        if directive["directive_type"] == "spawn":
            self._handle_spawn(directive)
        elif directive["directive_type"] == "retire":
            self._handle_retire(directive)
        elif directive["directive_type"] == "resume":
            self._handle_resume(directive)
        else:
            # An objection, not a failure. Nothing broke here - the Controller
            # was asked to do something it has no charter to do, and saying so is
            # a correct outcome rather than a malfunction.
            fi_db.file_objection(
                self.conn, directive["id"], self.identity,
                ground="jurisdiction mismatch",
                evidence=(
                    f"directive_type {directive['directive_type']!r} has no handler; the Controller "
                    f"executes {', '.join(sorted(self.HANDLED_DIRECTIVE_TYPES))}"
                ),
                remedy=(
                    "route this to a role that holds the capability, or - if no role does - treat it "
                    "as a capability the organization is missing and decide whether to build it"
                ),
            )
        return True

    def _handle_spawn(self, directive: dict) -> None:
        role = directive["target_role"]
        # Which slot this process runs under is the Controller's call, not the
        # directive's: COO decides that a role is short, the Controller decides
        # whether that means refilling an existing slot or opening a new one.
        # See fi_db.allocate_slot - refilling comes first, so an agent that
        # crashed returns under its own identity with its history intact.
        identity = fi_db.allocate_slot(self.conn, role)
        fi_db.clear_process_stop(self.conn, identity)
        env = {**os.environ, "FI_DB_PATH": self.db_path, **AGENT_ENV}
        try:
            process = subprocess.Popen(
                [sys.executable, "-m", f"agents.{role}", identity],
                cwd=PROJECT_ROOT,
                env=env,
            )
        except OSError as exc:
            fi_db.complete_directive(self.conn, directive["id"], "failure", detail=str(exc))
            return
        self._processes[identity] = process
        fi_db.complete_directive(self.conn, directive["id"], "success", detail=identity)

    def _object_missing_identity(self, directive: dict, identity: str, action: str) -> None:
        """Ordered to act on an agent that does not exist.

        Recorded as a failure before G5, which read a correct refusal as a
        malfunction: the Controller worked exactly as intended, and the order
        named something absent. The ground is verifiable - `settle_objection`
        re-checks the registry rather than taking this claim on trust."""
        fi_db.file_objection(
            self.conn, directive["id"], self.identity,
            ground="missing dependency",
            evidence=f"no agent is registered as {identity}, so there is nothing to {action}",
            remedy=(
                f"spawn {identity} first if it should exist, or withdraw the directive if the "
                "identity was a mistake"
            ),
        )

    def _handle_retire(self, directive: dict) -> None:
        """Retirement moves the agent to dormant and asks its process to wind
        down. It never deletes anything: the identity, name, and full history
        survive, and _handle_resume is the exact inverse (addendum 11 §9,
        "retirement is non-destructive and reversible")."""
        identity = directive["target_identity"]
        if fi_db.get_agent(self.conn, identity) is None:
            self._object_missing_identity(directive, identity, "retire")
            return
        fi_db.request_retirement(self.conn, identity)
        fi_db.complete_directive(self.conn, directive["id"], "success", detail=f"retirement requested for {identity}")

    def _handle_resume(self, directive: dict) -> None:
        """Brings a dormant agent back into service. Only restores its
        organizational standing - COO's normal baseline check then sees an
        in-service role with no process running and requests the spawn, so
        the agent returns under the same permanent identity with its name and
        history intact."""
        identity = directive["target_identity"]
        agent = fi_db.get_agent(self.conn, identity)
        if agent is None:
            self._object_missing_identity(directive, identity, "resume")
            return
        fi_db.resume_agent(self.conn, identity)
        fi_db.complete_directive(self.conn, directive["id"], "success", detail=f"resumed {identity}")

    def known_process_identities(self) -> list[str]:
        """Identities this Controller instance has itself spawned (has a
        live Popen handle for)."""
        return list(self._processes.keys())

    def close(self) -> None:
        self.conn.close()
