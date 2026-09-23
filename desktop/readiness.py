"""Whether Jarvis can actually run on Krish's PC, check by check.

Every subsystem built in the last two days was tested in a Linux container and
none of it has ever started on the machine it is for. Two of them broke there
the first time Windows saw them. So the question *"does it run on my PC"* needs
an answer that is a list rather than a yes, and this is the list.

## Three rules this is built on, each from something that already went wrong

**An unchecked thing is never green.** `tests/test_real_machine.py` once had a
log check that passed on a machine with no log, because scanning nothing returns
nothing. So a check whose precondition failed is reported as `BLOCKED` and names
what blocked it. There is no path here from "could not look" to "fine".

**Order is by dependency, not by importance.** Telling Krish the constitution is
not installed, when the real cause is that the DBA is not running, is telling him
about a symptom. `blocked_by` makes that computable rather than a judgement -
the same arrangement `gateway/taskrun.py` uses, for the same reason.

**Every red says what to do about it.** Whoever reads this output is alone with
it, possibly on a phone, possibly on holiday. `assert x` tells him nothing, and
so does *"constitution: FAILED"*.

## The split

This module decides and holds no I/O at all: it takes a `Machine` - a bag of
facts somebody else looked up - and returns results. `desktop/machine.py` is the
part that looks them up, one effect per function, and it is the part that cannot
be tested from here. That is why every branch below is reachable from a test on
a machine that has none of the things it asks about.
"""

from __future__ import annotations

from dataclasses import dataclass, field

GREEN = "green"
YELLOW = "yellow"
RED = "red"
BLOCKED = "blocked"
STATUSES = (GREEN, YELLOW, RED, BLOCKED)

# Krish, 2026-09-23: *"Red - yellow - green - simple status replies like this is
# best."* `BLOCKED` is the fourth because the three-colour version would have to
# call an unchecked thing something, and each of the three would be a lie.
ORDER = {RED: 0, BLOCKED: 1, YELLOW: 2, GREEN: 3}


# Checks whose failure means Jarvis does not run at all, as opposed to runs
# with something missing. Named here rather than decided per check, so that the
# difference between "broken" and "incomplete" is one list somebody can read.
BLOCKING = (
    "python", "packages", "state_directory", "jarvis_token", "dba", "gateway",
    "gateway_reaches_dba", "keystore",
)


@dataclass(frozen=True)
class Machine:
    """What somebody looked up about the PC. Facts only, no judgement.

    Defaults are the *worst* case rather than the convenient one: a fact nobody
    supplied must not read as working. A `Machine()` with nothing filled in
    describes a machine where nothing is running, which is the honest reading of
    "we did not look"."""

    python_version: tuple[int, int] = (0, 0)
    missing_packages: tuple[str, ...] = ()
    state_directory_writable: bool = False
    jarvis_token: bool = False
    operator_token: bool = False
    dba_answering: bool = False
    gateway_answering: bool = False
    gateway_reaches_dba: bool = False
    keystore_state: str = "absent"
    keystore_because: str = "nobody looked"
    keystore_next_step: str = "run this on the Windows machine"
    constitution_installed: bool = False
    constitution_intact: bool | None = None
    constitution_report: str = ""
    ledger_intact: bool | None = None
    checkpoint_age_hours: float | None = None
    supervisor_registered: bool = False
    log_written_within_hours: float | None = None
    windows: bool = False


@dataclass(frozen=True)
class Result:
    name: str
    means: str
    status: str
    because: str
    fix: str = ""
    blocked_by: str = ""

    @property
    def blocking(self) -> bool:
        """Whether failing this means he does not run, as opposed to runs with
        something missing."""
        return self.name in BLOCKING


@dataclass
class Report:
    results: list[Result] = field(default_factory=list)

    @property
    def status(self) -> str:
        """The worst thing in it. A report is as good as its worst line."""
        if not self.results:
            return RED
        return min((one.status for one in self.results), key=lambda s: ORDER[s])

    @property
    def runnable(self) -> bool:
        """Whether Jarvis can be started at all, which is not the same as well."""
        return not [one for one in self.results
                    if one.status in (RED, BLOCKED) and one.blocking]

    def worst_first(self) -> list[Result]:
        return sorted(self.results,
                      key=lambda one: (ORDER[one.status], one.name))

    def of(self, name: str) -> Result:
        for one in self.results:
            if one.name == name:
                return one
        raise KeyError(name)


# What each check needs to have passed before its own answer means anything.
NEEDS = {
    "packages": ("python",),
    "dba": ("packages", "jarvis_token"),
    "gateway": ("packages",),
    "gateway_reaches_dba": ("dba", "gateway"),
    "constitution": ("keystore", "state_directory"),
    "constitution_intact": ("constitution", "dba"),
    "ledger": ("dba",),
    "checkpoint": ("dba",),
    "operator_console": ("dba",),
    "logs": ("gateway",),
}

MINIMUM_PYTHON = (3, 11)

# A checkpoint older than this is not a checkpoint, it is a memory of one. Two
# days: long enough that a quiet weekend is not an alarm, short enough that a
# restart would not lose a working week.
CHECKPOINT_STALE_HOURS = 48.0

# Nothing in the log for this long, while the Gateway is answering, means the
# logging stopped rather than that nothing happened.
LOG_SILENT_HOURS = 24.0


def _need_met(name: str, done: dict[str, Result]) -> str:
    """The first unmet precondition of `name`, or "" if it may be judged.

    `done[required]` rather than `.get`: a precondition that has not run yet is
    a bug in `NEEDS` - the checks are declared in dependency order - and it
    should fail loudly here rather than quietly block something for ever. A
    `None` branch would be unreachable, which is a branch nobody tests.
    `test_every_precondition_names_a_check_that_has_already_run` is what holds
    the table to it."""
    for required in NEEDS.get(name, ()):
        if done[required].status in (RED, BLOCKED):
            return required
    return ""


def look(machine: Machine) -> Report:
    """Every check, in dependency order, against one reading of the machine."""
    report = Report()
    done: dict[str, Result] = {}

    def add(name, means, judge, fix=""):
        blocked = _need_met(name, done)
        if blocked:
            result = Result(name, means, BLOCKED,
                            f"not checked: {blocked} has to work first",
                            blocked_by=blocked)
        else:
            status, because, said_fix = judge()
            result = Result(name, means, status, because, said_fix or fix)
        done[name] = result
        report.results.append(result)
        return result

    add("python", "the interpreter is new enough for this code",
        lambda: ((GREEN, f"Python {machine.python_version[0]}."
                         f"{machine.python_version[1]}", "")
                 if machine.python_version >= MINIMUM_PYTHON else
                 (RED, f"Python {machine.python_version[0]}."
                       f"{machine.python_version[1]} is older than "
                       f"{MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]}",
                  "install a newer Python and point keep-jarvis-up.ps1 at it")))

    add("packages", "the libraries this needs are installed",
        lambda: ((GREEN, "everything imports", "")
                 if not machine.missing_packages else
                 (RED, "missing: " + ", ".join(machine.missing_packages),
                  "pip install -r requirements.txt -r requirements-desktop.txt")))

    add("state_directory", "there is somewhere to keep what he remembers",
        lambda: ((GREEN, "writable", "")
                 if machine.state_directory_writable else
                 (RED, "the state folder cannot be written to",
                  "check the folder exists and that this account owns it")))

    add("jarvis_token", "Jarvis can authenticate to his own memory",
        lambda: ((GREEN, "set", "")
                 if machine.jarvis_token else
                 (RED, "DBA_TOKEN_JARVIS is not set, so Jarvis has no memory "
                       "at all: no ledger, no checkpoints, no restore",
                  "set DBA_TOKEN_JARVIS in the environment the supervisor "
                  "starts him in")))

    add("dba", "the service holding his memory is up",
        lambda: ((GREEN, "answering", "")
                 if machine.dba_answering else
                 (RED, "the DBA is not answering",
                  "start it, or let keep-jarvis-up.ps1 start it - it comes up "
                  "before the Gateway on purpose")))

    add("gateway", "Jarvis himself is up",
        lambda: ((GREEN, "answering", "")
                 if machine.gateway_answering else
                 (RED, "the Gateway is not answering",
                  "powershell -File scripts\\keep-jarvis-up.ps1")))

    add("gateway_reaches_dba", "he can actually get at his memory",
        lambda: ((GREEN, "reaches it", "")
                 if machine.gateway_reaches_dba else
                 (RED, "the Gateway is up but cannot reach the DBA, so he is "
                       "running with no memory while looking healthy",
                  "check DBA_TOKEN_JARVIS matches what the DBA expects")))

    add("keystore", "the constitution's key has a home on this machine",
        lambda: ((GREEN, machine.keystore_because, "")
                 if machine.keystore_state == "ready" else
                 (YELLOW if machine.keystore_state == "no_escrow" else RED,
                  machine.keystore_because, machine.keystore_next_step)))

    add("constitution", "the charter he is governed by is installed here",
        lambda: ((GREEN, "installed and sealed", "")
                 if machine.constitution_installed else
                 (RED, "no sealed constitution on this machine, so nothing he "
                       "does is governed by the document he was given",
                  "python -m desktop.bringup --install-constitution")))

    add("constitution_intact", "nobody has altered it since",
        lambda: ((GREEN, "intact", "")
                 if machine.constitution_intact else
                 (RED, machine.constitution_report or "verification failed",
                  "this is the one that should never be red. Do not overwrite "
                  "it - read the report first.")))

    add("ledger", "his record of his own life verifies",
        lambda: ((GREEN, "hash chain verifies", "")
                 if machine.ledger_intact else
                 (RED, "the life ledger does not verify, so his history cannot "
                       "be trusted",
                  "keep the file; a broken chain is evidence, not rubbish")))

    add("checkpoint", "a restart would restore something recent",
        lambda: _checkpoint(machine))

    add("operator_console", "Krish can answer what Jarvis noticed",
        lambda: ((GREEN, "the operator token is set", "")
                 if machine.operator_token else
                 (YELLOW, "DBA_TOKEN_OPERATOR_CONSOLE is not set, so nothing "
                          "can settle a guess and the trust ladder can never "
                          "move - and no deploy can complete",
                  "set DBA_TOKEN_OPERATOR_CONSOLE in your own shell, not in "
                  "the one Jarvis runs in")))

    add("supervisor", "something restarts him when he dies",
        lambda: ((GREEN, "the logon task is registered", "")
                 if machine.supervisor_registered else
                 (YELLOW, "no scheduled task, so nothing brings him back after "
                          "a reboot or a crash",
                  "powershell -File scripts\\register-jarvis-task.ps1")))

    add("logs", "he is writing down what happens to him",
        lambda: _logs(machine))

    return report


def _checkpoint(machine: Machine):
    if machine.checkpoint_age_hours is None:
        return (RED, "there is no checkpoint at all, so a restart would start "
                     "from nothing",
                "one is taken on a schedule and before shutdown; if there is "
                "none, the upkeep loop is not running")
    if machine.checkpoint_age_hours > CHECKPOINT_STALE_HOURS:
        return (YELLOW,
                f"the newest checkpoint is "
                f"{machine.checkpoint_age_hours:.0f} hours old",
                "the upkeep loop may have stopped; check the log for a thread "
                "that died")
    return (GREEN, f"{machine.checkpoint_age_hours:.0f} hours old", "")


def _logs(machine: Machine):
    if machine.log_written_within_hours is None:
        return (RED, "there is no log at all. An absent log is not a clean "
                     "one - it is the failure the logging was built to stop",
                "check that the supervisor is redirecting its children's "
                "output, and that logs/ is writable")
    if machine.log_written_within_hours > LOG_SILENT_HOURS:
        return (YELLOW,
                f"nothing written for {machine.log_written_within_hours:.0f} "
                f"hours while he is answering, which means the logging stopped "
                f"rather than that nothing happened",
                "check the log handler is installed in both services")
    return (GREEN, "being written", "")


def summary(report: Report) -> list[str]:
    """What a person reads. Worst first, one line each, fix underneath."""
    lines = []
    for one in report.worst_first():
        mark = {GREEN: "[ok]", YELLOW: "[--]", RED: "[!!]",
                BLOCKED: "[??]"}[one.status]
        lines.append(f"{mark} {one.name}: {one.because}")
        if one.fix:
            lines.append(f"       -> {one.fix}")
    return lines


def describe() -> dict:
    return {
        "statuses": list(STATUSES),
        "unchecked_is_never_green": True,
        "blocking_checks": list(BLOCKING),
        "minimum_python": list(MINIMUM_PYTHON),
    }
