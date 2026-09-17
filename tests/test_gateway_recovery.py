"""Recovering another machine, which is the first thing here that changes one.

Krish's plan made diagnosis Phase 1 and recovery Phase 3, and the gap between
them cost a week: on 2026-09-15 the engineer session on the development PC
stopped answering while he was on another continent, every surrounding component
reported healthy, and nothing in the system could start it again.

So the interesting assertions are not "does the command run". They are about the
five things that stop it running, because a recovery capability that is merely
*effective* is a remote shell with a good reason. In the order the module
applies them:

**It cannot be aimed.** No command parameter, no host parameter. The machine and
the action are both names out of a file a person wrote.

**It will not confirm itself.** The same guard `publish_document` uses for a
public commit. A model reasoning its way to "he would obviously want this
restarted" is exactly the reasoning that must not be sufficient.

**It obeys the diagnosis.** A service that is answering is not restarted, a
machine that is unreachable is not acted on, and an action whose subject nobody
probed cannot be justified by a report that never looked at it.

**It refuses on low confidence.** This is the agent case and it is the one that
would cost something irreplaceable. `remote.assess` will never call a quiet
agent hung, because from outside an idle session and a dead one are identical.
Recovery inherits that with teeth.

**It is bounded and recorded.** A cooldown, a daily ceiling, and a journal that
both are counted from - so an unwritable journal refuses rather than acting
without a limit.

And one that is about honesty rather than safety: `recovered` is a fresh probe
after the fact, never the exit code. A restart command can succeed and leave the
service exactly as dead as it was, and reporting the first as the second is this
fleet's signature failure - every component green, the system silent.
"""

import json
import socket
from datetime import datetime, timedelta

import pytest

import conftest

from gateway import recovery, remote, roles, tools


COMMAND = "restart-the-thing --now"


@pytest.fixture
def fleet(tmp_path, monkeypatch):
    """A machine list and a journal, both temporary, and no real tailnet."""
    targets = tmp_path / "remote-targets.json"
    journal = tmp_path / "journal.jsonl"
    monkeypatch.setenv(remote.TARGETS_FILE_ENV, str(targets))
    monkeypatch.setenv(recovery.JOURNAL_FILE_ENV, str(journal))
    monkeypatch.setattr(remote, "_tailscale_exe", lambda configured=None: None)
    return {"targets": targets, "journal": journal}


@pytest.fixture
def listening_port():
    """A real socket. The TCP probe is measured, not mocked."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    # A generous backlog, because nothing here ever calls accept(). One
    # `recover` makes two full diagnoses - before and after - so a backlog of 1
    # fills and the host starts reading as unreachable halfway through a test.
    sock.listen(128)
    yield sock.getsockname()[1]
    sock.close()


@pytest.fixture
def closed_port():
    """A port nothing is on: bound to learn the number, then released."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def write_fleet(path, *, services, actions, ssh=True, channels=None):
    target = {
        "name": "dev",
        "label": "the development PC",
        "host": "127.0.0.1",
        "services": services,
        "recovery": {"actions": actions},
    }
    if channels:
        target["channels"] = channels
    if ssh:
        target["ssh"] = {"user": "someone", "key": "/nowhere/key", "checks": []}
    path.write_text(json.dumps({"targets": [target]}), encoding="utf-8")


def runner_for(command=COMMAND, *, ok=True, output="done"):
    """A runner that records what it was asked to do.

    Injected rather than patched for the reason `remote.ssh_probe` gives: a test
    that monkeypatches subprocess ends up asserting how the module calls SSH
    instead of what it does with the answer."""
    calls = []

    def run(argv):
        calls.append(argv)
        if argv and argv[-1] == command:
            return {"ok": ok, "exit_code": 0 if ok else 1, "output": output, "error": ""}
        return {"ok": True, "exit_code": 0, "output": "", "error": ""}

    run.calls = calls
    run.ran_the_command = lambda: any(c and c[-1] == command for c in calls)
    return run


def healthy_and_broken(listening_port, closed_port, *, states=("not listening",)):
    """Two services: one up, so the machine reads as reachable; one down.

    A single dead service on a host with no tailnet reads as `unreachable` - the
    machine, not the service - and that is correct. Recovery of a *service*
    therefore needs evidence the host is up, which is what the live one is."""
    services = [
        {"name": "sentinel", "port": listening_port},
        {"name": "gateway", "port": closed_port},
    ]
    actions = [{
        "name": "restart the gateway",
        "description": "Restarts just the gateway.",
        "command": COMMAND,
        "when": {"service": "gateway", "states": list(states)},
    }]
    return services, actions


# ------------------------------------------------- it cannot be aimed anywhere


def test_neither_tool_lets_the_model_supply_a_command_or_an_address():
    """The guard that matters most, and it is a property of the schema.

    A command parameter would make this a remote shell wearing a recovery's
    name. A host parameter would let a sentence in a conversation point it at
    any machine on the network."""
    for name in ("remote_recover", "remote_recovery_options"):
        tool = next(t for t in tools.TOOLS if t["name"] == name)
        properties = set(tool["input_schema"]["properties"])
        for forbidden in ("host", "hostname", "address", "ip", "url", "port",
                          "command", "cmd", "script", "shell"):
            assert forbidden not in properties, f"{name} lets the model supply {forbidden}"

    recover = next(t for t in tools.TOOLS if t["name"] == "remote_recover")
    assert set(recover["input_schema"]["properties"]) == {"target", "action", "confirm"}


def test_an_unconfigured_machine_or_action_is_refused_by_name(fleet, closed_port):
    """Refused and told what exists - never attempted against a guess."""
    services, actions = healthy_and_broken(closed_port, closed_port)
    write_fleet(fleet["targets"], services=services, actions=actions)

    with pytest.raises(recovery.RecoveryRefused) as unknown_machine:
        recovery.recover("some-other-box", "restart the gateway", confirm=True)
    assert "no configured machine" in str(unknown_machine.value)

    with pytest.raises(recovery.RecoveryRefused) as unknown_action:
        recovery.recover("dev", "rm -rf /", confirm=True)
    assert "no recovery action called" in str(unknown_action.value)
    assert "restart the gateway" in str(unknown_action.value)


def test_a_refusal_reaches_the_model_as_a_sentence_not_a_traceback(fleet, gateway_conn,
                                                                   closed_port):
    """Same contract as `devchannel.ChannelRefused`: the model is expected to
    read the refusal and repeat it, which it cannot do with a stack trace."""
    services, actions = healthy_and_broken(closed_port, closed_port)
    write_fleet(fleet["targets"], services=services, actions=actions)

    result = tools.execute(gateway_conn, "remote_recover",
                           {"target": "nope", "action": "restart the gateway",
                            "confirm": True},
                           role=roles.ROLE_OPERATOR)

    assert "error" in result
    assert "no configured machine" in result["error"]


# ------------------------------------------------ acting is its own authority


def test_recovery_does_not_reuse_the_capability_that_only_looks(gateway_conn):
    """`gateway/tools.py` wrote this rule down before there was anything to hold
    to it: acting on another machine is a different authority from looking at
    one. Diagnosis keeps `system:status`; recovery gets its own."""
    assert tools.TOOL_CAPABILITY["remote_diagnose"] == roles.CAP_SYSTEM_STATUS
    assert tools.TOOL_CAPABILITY["remote_recover"] == roles.CAP_SYSTEM_RECOVER
    assert tools.TOOL_CAPABILITY["remote_recovery_options"] == roles.CAP_SYSTEM_RECOVER
    assert roles.CAP_SYSTEM_RECOVER != roles.CAP_SYSTEM_STATUS


def test_only_the_operator_holds_it(gateway_conn):
    """`internal` may watch a service die and may not bounce it. A role that can
    see is not thereby a role that may act."""
    assert roles.allows(roles.ROLE_OPERATOR, roles.CAP_SYSTEM_RECOVER)
    assert not roles.allows(roles.ROLE_INTERNAL, roles.CAP_SYSTEM_RECOVER)
    assert not roles.allows(roles.ROLE_CLIENT, roles.CAP_SYSTEM_RECOVER)

    # And the boundary refuses, not merely the menu.
    assert roles.allows(roles.ROLE_INTERNAL, roles.CAP_SYSTEM_STATUS)
    for role in (roles.ROLE_INTERNAL, roles.ROLE_CLIENT):
        refusal = tools.execute(gateway_conn, "remote_recover",
                                {"target": "dev", "action": "x"}, role=role)
        assert "error" in refusal and "Not permitted" in refusal["error"]

    offered = {t["name"] for t in tools.for_role(roles.ROLE_INTERNAL)}
    assert "remote_diagnose" in offered
    assert "remote_recover" not in offered


# ------------------------------------------------- it will not confirm itself


def test_without_confirmation_nothing_runs_and_it_says_what_would(fleet, listening_port,
                                                                  closed_port):
    """The `publish_document` guard, applied to a change on another machine."""
    services, actions = healthy_and_broken(listening_port, closed_port)
    write_fleet(fleet["targets"], services=services, actions=actions)
    runner = runner_for()

    result = recovery.recover("dev", "restart the gateway", confirm=False,
                              ssh_runner=runner)

    assert result["attempted"] is False
    assert not runner.ran_the_command()
    assert "Not confirmed" in result["reason"]
    assert "the development PC" in result["reason"]
    assert not fleet["journal"].exists()


def test_a_string_is_not_a_confirmation(fleet, gateway_conn, listening_port, closed_port):
    """`confirm` is read strictly at the dispatch boundary. A model that passed
    "yes" as a string has not been told yes by anybody."""
    services, actions = healthy_and_broken(listening_port, closed_port)
    write_fleet(fleet["targets"], services=services, actions=actions)

    for truthy in ("yes", "true", 1, "confirm"):
        result = tools.execute(gateway_conn, "remote_recover",
                               {"target": "dev", "action": "restart the gateway",
                                "confirm": truthy},
                               role=roles.ROLE_OPERATOR)
        assert result["attempted"] is False, f"{truthy!r} was taken as a confirmation"
        assert "Not confirmed" in result["reason"]


# ------------------------------------------------------- it obeys the verdict


def test_a_healthy_service_is_not_restarted(fleet, listening_port, closed_port):
    """The diagnosis outranks the request. Somebody asking for a restart is not
    evidence that anything is down."""
    services, actions = healthy_and_broken(listening_port, closed_port)
    # Point the action at the service that is actually up.
    actions[0]["when"] = {"service": "sentinel", "states": ["not listening"]}
    write_fleet(fleet["targets"], services=services, actions=actions)
    runner = runner_for()

    result = recovery.recover("dev", "restart the gateway", confirm=True,
                              ssh_runner=runner)

    assert result["attempted"] is False
    assert not runner.ran_the_command()
    assert "listening" in result["reason"]
    assert "nothing needs" in result["reason"]


def test_an_unreachable_machine_is_not_acted_on(fleet, closed_port):
    """Running an SSH command into a machine that is off would report a timeout
    as though it were a finding."""
    services, actions = healthy_and_broken(closed_port, closed_port)
    write_fleet(fleet["targets"], services=services, actions=actions)
    runner = runner_for()

    result = recovery.recover("dev", "restart the gateway", confirm=True,
                              ssh_runner=runner)

    assert result["attempted"] is False
    assert not runner.ran_the_command()
    assert "not reachable" in result["reason"]
    assert "nothing here can do that" in result["reason"]


def test_an_action_with_no_when_block_can_never_run(fleet, listening_port, closed_port):
    """Fail closed, and it is the opposite of the convenient default. An
    unconditional action is a command that fires whenever asked."""
    services, _ = healthy_and_broken(listening_port, closed_port)
    actions = [{"name": "do the thing", "command": COMMAND}]
    write_fleet(fleet["targets"], services=services, actions=actions)
    runner = runner_for()

    result = recovery.recover("dev", "do the thing", confirm=True, ssh_runner=runner)

    assert result["attempted"] is False
    assert not runner.ran_the_command()
    assert "no 'when' block" in result["reason"]


def test_an_action_aimed_at_a_service_nobody_probed_is_refused(fleet, listening_port,
                                                               closed_port):
    """A `when` pointing at an unprobed service would otherwise be satisfied by
    silence, and silence is what this project keeps mistaking for health."""
    services, actions = healthy_and_broken(listening_port, closed_port)
    actions[0]["when"] = {"service": "database", "states": ["not listening"]}
    write_fleet(fleet["targets"], services=services, actions=actions)
    runner = runner_for()

    result = recovery.recover("dev", "restart the gateway", confirm=True,
                              ssh_runner=runner)

    assert result["attempted"] is False
    assert not runner.ran_the_command()
    assert "not probed" in result["reason"]


def test_a_quiet_agent_alone_is_never_enough(fleet):
    """The gate that protects something irreplaceable.

    Judged only by a file that has not moved, `remote.assess` returns low
    confidence and recommends getting evidence from inside the machine. This is
    that recommendation enforced rather than printed: a restart on this evidence
    could kill a session that was working perfectly."""
    stale = fleet["targets"].parent / "channel.md"
    stale.write_text("nothing new", encoding="utf-8")
    import os
    old = (datetime.now() - timedelta(hours=9)).timestamp()
    os.utime(stale, (old, old))

    actions = [{
        "name": "restart the session",
        "command": COMMAND,
        "when": {"states": ["reachable", "unknown"]},
    }]
    write_fleet(fleet["targets"], services=[], actions=actions,
                channels=[{"name": "the channel", "path": str(stale),
                           "stale_minutes": 60}])
    runner = runner_for()

    result = recovery.recover("dev", "restart the session", confirm=True,
                              ssh_runner=runner)

    assert result["attempted"] is False
    assert not runner.ran_the_command()
    assert "low" in result["reason"]
    assert "could kill a session that was working" in result["reason"]


# ------------------------------------------------------ bounded, and recorded


def test_it_runs_when_every_gate_is_satisfied(fleet, listening_port, closed_port):
    """The positive case, so the gates above are known to be gates rather than a
    module that refuses everything."""
    services, actions = healthy_and_broken(listening_port, closed_port)
    write_fleet(fleet["targets"], services=services, actions=actions)
    runner = runner_for()

    result = recovery.recover("dev", "restart the gateway", confirm=True,
                              ssh_runner=runner)

    assert result["attempted"] is True
    assert runner.ran_the_command()
    assert result["command_ran"] is True
    assert result["before"]["state"] == "not listening"

    ran = [c for c in runner.calls if c[-1] == COMMAND][0]
    assert ran[0] == "ssh"
    assert "BatchMode=yes" in ran, "a recovery that can prompt for a password hangs"


def test_recovered_is_the_re_probe_and_not_the_exit_code(fleet, listening_port,
                                                         closed_port):
    """This fleet's signature failure, asserted against.

    The command exits zero and the port is still shut. Reporting that as success
    is 'every component green, the system silent' in one field."""
    services, actions = healthy_and_broken(listening_port, closed_port)
    write_fleet(fleet["targets"], services=services, actions=actions)

    result = recovery.recover("dev", "restart the gateway", confirm=True,
                              ssh_runner=runner_for(ok=True))

    assert result["command_ran"] is True
    assert result["recovered"] is False, "a zero exit was read as a working service"
    assert result["after"]["state"] == "not listening"


def test_the_cooldown_refuses_a_second_attempt(fleet, listening_port, closed_port):
    """A restart that has not been given time to take effect looks exactly like
    one that did not work, and retrying is a loop with a longer stride."""
    services, actions = healthy_and_broken(listening_port, closed_port)
    actions[0]["cooldown_minutes"] = 30
    write_fleet(fleet["targets"], services=services, actions=actions)

    first = recovery.recover("dev", "restart the gateway", confirm=True,
                             ssh_runner=runner_for())
    assert first["attempted"] is True

    runner = runner_for()
    second = recovery.recover("dev", "restart the gateway", confirm=True,
                              ssh_runner=runner)

    assert second["attempted"] is False
    assert not runner.ran_the_command()
    assert "cooldown" in second["reason"]


def test_the_daily_ceiling_refuses_and_says_why_retrying_is_wrong(fleet, listening_port,
                                                                 closed_port):
    """A service needing four restarts a day has a problem a restart does not
    fix, and continuing to restart it hides that until it is an incident."""
    services, actions = healthy_and_broken(listening_port, closed_port)
    actions[0]["max_per_day"] = 2
    actions[0]["cooldown_minutes"] = 0
    write_fleet(fleet["targets"], services=services, actions=actions)

    for _ in range(2):
        assert recovery.recover("dev", "restart the gateway", confirm=True,
                                ssh_runner=runner_for())["attempted"] is True

    runner = runner_for()
    blocked = recovery.recover("dev", "restart the gateway", confirm=True,
                               ssh_runner=runner)

    assert blocked["attempted"] is False
    assert not runner.ran_the_command()
    assert "limit" in blocked["reason"]
    assert "does not fix" in blocked["reason"]


def test_an_unwritable_journal_refuses_rather_than_acting_unbounded(fleet, tmp_path,
                                                                    monkeypatch,
                                                                    listening_port,
                                                                    closed_port):
    """The unusual direction to fail in, and it is the right one.

    The cooldown and the ceiling are both counted from the journal, so acting
    without it is acting with no limit and no record."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("i am a file", encoding="utf-8")
    monkeypatch.setenv(recovery.JOURNAL_FILE_ENV, str(blocker / "journal.jsonl"))

    services, actions = healthy_and_broken(listening_port, closed_port)
    write_fleet(fleet["targets"], services=services, actions=actions)
    runner = runner_for()

    result = recovery.recover("dev", "restart the gateway", confirm=True,
                              ssh_runner=runner)

    assert result["attempted"] is False
    assert not runner.ran_the_command()
    assert "journal" in result["reason"]
    assert "no limit and no record" in result["reason"]


def test_the_attempt_is_recorded_even_when_the_command_fails(fleet, listening_port,
                                                             closed_port):
    """Written before the command runs, on purpose. An attempt that is only
    recorded on success is a ceiling a failing loop never reaches."""
    services, actions = healthy_and_broken(listening_port, closed_port)
    write_fleet(fleet["targets"], services=services, actions=actions)

    result = recovery.recover("dev", "restart the gateway", confirm=True,
                              ssh_runner=runner_for(ok=False))

    assert result["command_ran"] is False
    written = recovery.read_journal()
    assert len(written) == 1
    assert written[0]["target"] == "dev"
    assert written[0]["action"] == "restart the gateway"
    assert written[0]["command"] == COMMAND


# ------------------------------------------------- what it honestly cannot do


def test_without_ssh_it_refuses_and_names_that_as_the_reason(fleet, listening_port,
                                                             closed_port):
    """Today no target on this deployment has an ssh block, because the outbound
    key is Krish's to authorise. That must be legible before an outage, not
    discovered during one."""
    services, actions = healthy_and_broken(listening_port, closed_port)
    write_fleet(fleet["targets"], services=services, actions=actions, ssh=False)
    runner = runner_for()

    result = recovery.recover("dev", "restart the gateway", confirm=True,
                              ssh_runner=runner)

    assert result["attempted"] is False
    assert not runner.ran_the_command()
    assert "no usable SSH block" in result["reason"]
    assert "Diagnosis works without one" in result["reason"]


def test_listing_the_options_changes_nothing(fleet, listening_port, closed_port):
    """"What could you do about it" must be answerable without any risk of
    answering it by doing it."""
    services, actions = healthy_and_broken(listening_port, closed_port)
    write_fleet(fleet["targets"], services=services, actions=actions)

    options = recovery.available("dev")

    assert options["available"] is True
    assert options["read_only"] is True
    machine = options["machines"][0]
    assert machine["ssh_configured"] is True
    assert machine["actions"][0]["name"] == "restart the gateway"
    assert machine["actions"][0]["runs_when_state_is"] == ["not listening"]
    assert recovery.read_journal() == []


def test_a_machine_with_no_actions_says_so_rather_than_inventing_one(fleet, closed_port):
    """None are built in, and none ever will be: a default restart command would
    assume the far end's operating system, service manager and paths."""
    write_fleet(fleet["targets"], services=[{"name": "gateway", "port": closed_port}],
                actions=[])

    machine = recovery.available("dev")["machines"][0]

    assert machine["actions"] == []
    assert "none are built in" in machine["reason"]


def test_the_diagnosis_still_says_it_changed_nothing(fleet, closed_port):
    """Phase 1 stays Phase 1. Building recovery must not quietly make
    `remote_diagnose` a thing that might act."""
    services, actions = healthy_and_broken(closed_port, closed_port)
    write_fleet(fleet["targets"], services=services, actions=actions)

    report = remote.diagnose("dev")

    assert "Nothing was started, stopped, written or deleted" in report["read_only"]
    assert report["diagnosed"][0]["report"]["corrective_action_taken"] == (
        "none - this is a read-only diagnosis")


def test_an_explicit_zero_is_honoured_rather_than_replaced(fleet, listening_port,
                                                           closed_port):
    """An operator who writes `"cooldown_minutes": 0` means no cooldown.

    Written because the first version of this module read that with `or`, which
    treats 0 as absent and substituted fifteen minutes - a configured value
    silently replaced by a different one, which is this project's most-named
    failure shape because it looks exactly like working."""
    services, actions = healthy_and_broken(listening_port, closed_port)
    actions[0]["cooldown_minutes"] = 0
    actions[0]["max_per_day"] = 3
    write_fleet(fleet["targets"], services=services, actions=actions)

    assert recovery.describe_actions(
        {"recovery": {"actions": actions}})[0]["cooldown_minutes"] == 0

    first = recovery.recover("dev", "restart the gateway", confirm=True,
                             ssh_runner=runner_for())
    second = recovery.recover("dev", "restart the gateway", confirm=True,
                              ssh_runner=runner_for())

    assert first["attempted"] is True
    assert second["attempted"] is True, "an explicit zero cooldown was overridden"


def test_a_negative_or_unparseable_setting_falls_back_to_the_default(fleet):
    """Not the same case as zero. A negative cooldown is not a preference, it is
    a mistake, and honouring it would disable the limit silently."""
    action = {"name": "x", "command": COMMAND, "cooldown_minutes": -5,
              "max_per_day": "lots"}
    described = recovery.describe_actions({"recovery": {"actions": [action]}})[0]

    assert described["cooldown_minutes"] == recovery.DEFAULT_COOLDOWN_MINUTES
    assert described["max_per_day"] == recovery.DEFAULT_MAX_PER_DAY
