"""Diagnosing another machine, read-only.

Krish, 2026-09-16 18:12, by phone from abroad: *"Jarvis must eventually be able
to diagnose services and agents running on other authorized machines, not only
its own machine ... Prefer read-only inspection ... Report findings before
taking corrective action."*

The interesting failures of a remote diagnostic are not crashes. They are
sentences: a confident report about a process nobody looked at, an agent called
"hung" because it was quiet, a machine diagnosed that nobody authorised. So most
of what is asserted here is about what the report *says* and what the tool
*cannot be asked to do*, which is where the harm would actually come from.

Four groups:

**It cannot be aimed.** `remote_diagnose` takes a configured name and has no
address parameter at all. A model that could supply a host could point the
Gateway at any machine it can reach, and a read-only port scan of somebody
else's network is still a port scan.

**It never guesses.** No configuration, bad configuration, an unknown name, an
unreachable host - each returns a stated reason. The four things that genuinely
cannot be seen without a credential come back inside `not_measured` rather than
being left out, because an omitted measurement reads as a clean one.

**Quiet is not hung.** From outside, an idle session and a dead one are
identical. The verdict vocabulary has no word that would get a working session
killed, and that is asserted rather than trusted to the wording of a docstring.

**It changes nothing.** Phase 1 is diagnosis; recovery is Phase 3 and is not
built. The tool's own result says so, and the module has no write in it.
"""

import json
import socket
from pathlib import Path

import pytest

import conftest

from gateway import remote, roles, tools


@pytest.fixture
def targets(tmp_path, monkeypatch):
    """Point the module at a temporary machine list, and away from the tailnet.

    `_tailscale_exe` is stubbed to None in every test that runs a whole
    diagnosis. Without it the suite shells out to the real `tailscale status` on
    whatever machine it is running on - slow, and an assertion whose result
    depends on whether a laptop is online is not an assertion."""
    path = tmp_path / "remote-targets.json"
    monkeypatch.setenv(remote.TARGETS_FILE_ENV, str(path))
    monkeypatch.setattr(remote, "_tailscale_exe", lambda configured=None: None)
    return path


def write_targets(path, targets, **top):
    path.write_text(json.dumps({"targets": targets, **top}), encoding="utf-8")


@pytest.fixture
def listening_port():
    """A real socket, so the TCP probe is measured rather than mocked."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    yield sock.getsockname()[1]
    sock.close()


# ------------------------------------------------- it cannot be aimed anywhere


def test_the_tool_has_no_way_to_name_a_machine_that_is_not_configured():
    """The guard that matters most, and it is a property of the schema.

    A `host` or `address` parameter would mean a sentence in a conversation
    could aim this Gateway at anything on the network. The authorised machines
    are a decision somebody made in a file; the model chooses among them and
    cannot add to them."""
    tool = next(t for t in tools.TOOLS if t["name"] == "remote_diagnose")
    properties = set(tool["input_schema"]["properties"])
    assert properties == {"target"}
    for forbidden in ("host", "hostname", "address", "ip", "url", "port", "command"):
        assert forbidden not in properties, (
            f"remote_diagnose lets the model supply {forbidden}")


def test_an_unconfigured_name_is_refused_and_says_what_is_configured(targets):
    """Refused, not "unreachable". The two are opposite findings and reporting
    the wrong one would send somebody to look at a healthy machine."""
    write_targets(targets, [{"name": "dev", "host": "10.0.0.1"}])

    result = remote.diagnose("some-other-box")

    assert result["available"] is False
    assert "no configured machine" in result["reason"]
    assert result["configured"] == ["dev"]


def test_it_requires_the_operator_capability(gateway_conn):
    """Same capability as machine_status: observe infrastructure, change
    nothing. A client asking the agent to look at another machine is the §14
    breach in its remote costume."""
    assert tools.TOOL_CAPABILITY["remote_diagnose"] == roles.CAP_SYSTEM_STATUS

    refusal = tools.execute(gateway_conn, "remote_diagnose", {},
                            role=roles.ROLE_CLIENT)
    assert "error" in refusal and "Not permitted" in refusal["error"]


# ------------------------------------------------------------ it never guesses


def test_no_machine_list_is_reported_not_invented(tmp_path, monkeypatch):
    """The failure `gateway/main.py`'s relay fallbacks already demonstrated on
    this project: a built-in default that looks exactly like working. Here it
    would mean reporting on a machine nobody authorised."""
    missing = tmp_path / "nothing-here.json"
    monkeypatch.setenv(remote.TARGETS_FILE_ENV, str(missing))

    result = remote.diagnose()

    assert result["available"] is False
    assert str(missing) in result["reason"]
    assert remote.TARGETS_FILE_ENV in result["reason"]


def test_an_unreadable_machine_list_reports_the_parser_complaint(targets):
    """"Your JSON has a trailing comma" is actionable; "no targets" is not."""
    targets.write_text("{ this is not json", encoding="utf-8")

    result = remote.diagnose()

    assert result["available"] is False
    assert str(targets) in result["reason"]


def test_an_entry_with_no_name_is_dropped_and_recorded(targets):
    """Dropped, because a target that cannot be named cannot be asked for - and
    recorded, because silently ignoring a line somebody wrote is how a machine
    goes unmonitored while the file says it is covered."""
    write_targets(targets, [{"host": "10.0.0.9"}, {"name": "dev", "host": "10.0.0.1"}])

    catalogue = remote.load_targets()

    assert catalogue["names"] == ["dev"]
    assert catalogue["problems"] == ["entry 0 has no name"]


def test_what_cannot_be_seen_without_a_credential_is_named(targets):
    """The four items on Krish's plan that no outside probe reaches. Present as
    fields with reasons, never absent - an absent measurement reads as a clean
    one to a model and to a person, and that is the specific way this would
    lie."""
    write_targets(targets, [{"name": "dev", "host": "127.0.0.1", "services": []}])

    one = remote.diagnose("dev")["diagnosed"][0]

    assert set(one["not_measured"]) >= {
        "process_table", "pid", "directory_structure",
        "remote_log_locations_and_freshness",
    }
    for field in ("process_table", "pid", "directory_structure"):
        assert "ssh" in one["not_measured"][field].lower()


def test_measurements_stop_being_named_once_ssh_actually_ran(targets):
    """The other half of the same property. If the checks ran, the report must
    not keep claiming those fields were not measured."""
    write_targets(targets, [{
        "name": "dev", "host": "127.0.0.1",
        "ssh": {"user": "someone", "host": "127.0.0.1",
                "checks": [{"name": "who", "command": "hostname"}]},
    }])

    one = remote.diagnose_target(
        remote.load_targets()["targets"][0],
        ssh_runner=lambda argv: {"ok": True, "exit_code": 0, "output": "krish-dev", "error": ""},
    )

    assert one["not_measured"] == {}
    assert one["evidence"]["ssh"]["checks"][0]["output"] == "krish-dev"


def test_a_machine_with_nothing_configured_to_probe_says_so(targets):
    """Not "healthy". A target nobody gave a port or a file to is a target that
    was never looked at, and the verdict has to be the honest one."""
    write_targets(targets, [{"name": "dev", "host": "10.255.255.1"}])

    report = remote.diagnose("dev")["diagnosed"][0]["report"]

    assert report["connectivity"] == "unknown"
    assert "no services and no channels" in report["connectivity_why"]


# ------------------------------------------------------------------ the probes


def test_the_tcp_probe_measures_a_real_listener(listening_port):
    assert remote.tcp_probe("127.0.0.1", listening_port)["open"] is True


def test_the_tcp_probe_reports_a_closed_port_with_the_reason(listening_port):
    """The port is closed by binding one and releasing it, so the number is
    certainly not in use rather than probably not."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    closed = sock.getsockname()[1]
    sock.close()

    result = remote.tcp_probe("127.0.0.1", closed, timeout=1.0)

    assert result["open"] is False
    assert result["error"]


def test_an_http_probe_that_cannot_connect_is_unreachable_not_an_exception():
    """Every failure is data. A diagnosis that raises tells Krish nothing, and
    the thing being diagnosed is usually broken - so the error path is the path
    that matters."""
    result = remote.http_probe("http://127.0.0.1:1/health", timeout=1.0)

    assert result["reachable"] is False
    assert result["status"] is None
    assert result["error"]


def test_a_file_an_agent_writes_is_fresh_then_stale(tmp_path):
    path = tmp_path / "conversation.md"
    path.write_text("something", encoding="utf-8")

    fresh = remote.file_activity(str(path), stale_minutes=60)
    stale = remote.file_activity(str(path), stale_minutes=0)

    assert fresh["state"] == "fresh"
    assert stale["state"] == "stale"


def test_a_missing_file_is_missing_rather_than_stale(tmp_path):
    activity = remote.file_activity(str(tmp_path / "never-written.md"))

    assert activity["state"] == "missing"
    assert activity["exists"] is False


def test_file_evidence_says_it_was_read_on_this_host(tmp_path):
    """The honesty that makes this evidence usable at all. Stat'ing a synced
    file here is not inspecting the remote disk, and a report that blurred the
    two would be worse than no report."""
    path = tmp_path / "conversation.md"
    path.write_text("x", encoding="utf-8")

    assert remote.file_activity(str(path))["observed_on"] == "this host"
    assert remote.file_activity(str(tmp_path / "gone.md"))["observed_on"] == "this host"


# ---------------------------------------------------------------- the verdicts


def test_an_offline_peer_is_unreachable_whatever_the_ports_said():
    """Rule 1. Listing four dead services underneath a machine that is switched
    off is noise that buries the one sentence that matters."""
    verdict = remote.assess(
        {"name": "dev", "label": "the dev PC"},
        {"peer": {"available": True, "found": True, "online": False,
                  "last_seen": "2026-09-14T21:00:00Z"},
         "services": [{"name": "gateway", "tcp": {"open": False, "port": 8100},
                       "verdict": {"state": "not listening", "why": "refused"}}],
         "channels": [], "ssh": {"configured": False, "reason": "no ssh"}},
    )

    assert verdict["connectivity"] == "unreachable"
    assert "offline" in verdict["connectivity_why"]
    assert "not reachable" in verdict["probable_cause"]


def test_a_live_connection_outranks_the_tailnets_opinion():
    """Rule 2. The coordination plane can lag; a socket that just accepted a
    connection cannot."""
    verdict = remote.assess(
        {"name": "dev"},
        {"peer": {"available": True, "found": True, "online": False},
         "services": [{"name": "gateway", "tcp": {"open": True, "port": 8100},
                       "verdict": {"state": "answering", "why": "HTTP 200"}}],
         "channels": [], "ssh": {"configured": False}},
    )

    assert verdict["connectivity"] == "reachable"


def test_a_quiet_agent_is_never_called_hung():
    """The word that would get a working session killed. An idle agent and a
    dead one are indistinguishable from outside, so the vocabulary does not
    contain the guess."""
    verdict = remote.assess(
        {"name": "dev"},
        {"peer": {"available": False, "reason": "no tailscale"},
         "services": [],
         "channels": [{"name": "the conversation",
                       "activity": {"state": "stale", "age_minutes": 2400.0,
                                    "stale_after_minutes": 240}}],
         "ssh": {"configured": False, "reason": "no ssh"}},
    )

    states = {agent["state"] for agent in verdict["agents"]}
    assert states == {"quiet"}
    # The explanation may use the word - it says quiet is not the same as hung -
    # but no agent may ever be *labelled* with it, here or in any other branch.
    assert "hung" not in states
    assert verdict["confidence"] == "low"
    assert "before acting" in verdict["recommended_next_action"]


def test_a_healthy_service_with_a_quiet_agent_points_at_the_agent():
    """The diagnosis Krish actually needs: the host is fine, so do not go
    looking at the host."""
    verdict = remote.assess(
        {"name": "dev"},
        {"peer": {"available": True, "found": True, "online": True},
         "services": [{"name": "gateway", "tcp": {"open": True, "port": 8100},
                       "verdict": {"state": "answering", "why": "HTTP 200"}}],
         "channels": [{"name": "the conversation",
                       "activity": {"state": "stale", "age_minutes": 900.0,
                                    "stale_after_minutes": 240}}],
         "ssh": {"configured": False}},
    )

    assert "only the agent is quiet" in verdict["probable_cause"]
    assert verdict["connectivity"] == "reachable"


def test_a_listening_port_that_will_not_answer_is_not_the_same_as_a_dead_one():
    """Three distinguishable states for one service, because the action differs:
    a dead port is probably a stopped service, and a listening one that will not
    answer is a service in trouble."""
    service = {"name": "gateway", "health_path": "/health"}

    answering = remote._service_state(service, {"open": True, "port": 1},
                                      {"reachable": True, "status": 200})
    wedged = remote._service_state(service, {"open": True, "port": 1},
                                   {"reachable": False, "error": "timed out"})
    absent = remote._service_state(service, {"open": False, "port": 1, "error": "refused"}, None)

    assert answering["state"] == "answering"
    assert wedged["state"] == "listening but not answering"
    assert absent["state"] == "not listening"


def test_an_error_status_still_proves_the_service_is_running():
    """A 401 is a pass for liveness. `ship-attachments.ps1` learned this the
    same way: being refused proves the door exists."""
    state = remote._service_state({"name": "g", "health_path": "/health"},
                                  {"open": True, "port": 1},
                                  {"reachable": True, "status": 401})

    assert state["state"] == "answering"


# ------------------------------------------------------------------------ ssh


def test_no_ssh_configured_is_stated_rather_than_skipped(targets):
    probe = remote.ssh_probe({"name": "dev", "host": "10.0.0.1"})

    assert probe["configured"] is False
    assert "reachable" in probe["reason"]


def test_ssh_is_configured_but_carries_no_commands_of_its_own():
    """None are built in, and the reason is in the message: a default like
    `Get-Process` assumes Windows and `ps aux` assumes it is not. A diagnostic
    that guesses the remote operating system reports confidently about a machine
    it never understood."""
    probe = remote.ssh_probe({"name": "dev", "ssh": {"user": "a", "host": "b"}})

    assert probe["configured"] is True
    assert probe["ran"] == 0
    assert "no checks are listed" in probe["reason"]


def test_ssh_never_prompts_for_a_password():
    """There is nobody at this keyboard. Without BatchMode a host that has lost
    its key prompts, and every probe hangs until its timeout."""
    seen = []

    remote.ssh_probe(
        {"name": "dev", "ssh": {"user": "someone", "host": "10.0.0.1", "port": 2222,
                                "key": "C:\\k", "checks": [{"name": "who", "command": "hostname"}]}},
        runner=lambda argv: seen.append(argv) or {"ok": True, "exit_code": 0, "output": ""},
    )

    argv = seen[0]
    assert "BatchMode=yes" in argv
    assert any(a.startswith("ConnectTimeout=") for a in argv)
    assert "someone@10.0.0.1" in argv
    assert argv[-1] == "hostname", "the command must be passed through unaltered"


def test_an_ssh_block_without_a_user_is_refused_rather_than_guessed():
    probe = remote.ssh_probe({"name": "dev", "host": "10.0.0.1",
                              "ssh": {"checks": [{"name": "who", "command": "hostname"}]}})

    assert probe["ran"] == 0
    assert "user" in probe["reason"]


# ------------------------------------------------------- it changes nothing


def test_the_result_says_it_changed_nothing(targets):
    """Said in the payload the model reads, not only in a docstring. Krish asked
    twice that nothing act on another machine before a person reads the
    evidence, and the assistant is the thing that would offer to."""
    write_targets(targets, [{"name": "dev", "host": "127.0.0.1"}])

    result = remote.diagnose()

    assert "Nothing was started, stopped, written or deleted" in result["read_only"]
    assert result["diagnosed"][0]["report"]["corrective_action_taken"].startswith("none")


def test_the_module_contains_no_way_to_change_anything():
    """Phase 1 is diagnosis. Recovery is Phase 3 of the plan Krish sent and it
    is deliberately absent - not declared and refusing, because a capability the
    assistant can see is one it will reach for.

    A source-level assertion because that is the only place the guarantee is
    actually enforceable: the module's safety is that these calls are not in it,
    and a behavioural test can only prove the paths it happens to walk."""
    source = conftest.executable_source(remote.__file__)

    # Lower-cased and with every string literal stripped by the helper, so this
    # cannot be tripped by the module's own prose about what it does not do.
    for forbidden in ("os.remove", "os.unlink", "shutil.rmtree", "os.rename",
                      ".write_text(", ".write_bytes(", ".unlink(", ".mkdir("):
        assert forbidden not in source, (
            f"{forbidden} appears in gateway/remote.py, which is read-only by design")


def test_the_example_configuration_is_tracked_and_parses():
    """The real list is not in the repository - it names hosts and paths - so
    the example is the only documentation of the shape, and a broken one would
    be discovered by whoever is trying to configure this in a hurry."""
    example = Path(remote.__file__).resolve().parent.parent / "config" / "remote-targets.example.json"

    assert example.exists(), "remote-targets.example.json is how anyone learns the shape"
    parsed = json.loads(example.read_text(encoding="utf-8"))
    assert isinstance(parsed["targets"], list) and parsed["targets"]
    assert parsed["targets"][0]["name"]


def test_a_whole_diagnosis_comes_back_in_the_shape_the_plan_asked_for(targets, listening_port):
    """Phase 2 of Krish's plan, as a shape: machine, connectivity, service
    state, channel state, probable cause, confidence, recommended next action."""
    write_targets(targets, [{
        "name": "here", "label": "this machine", "host": "127.0.0.1",
        "services": [{"name": "something", "port": listening_port}],
    }])

    report = remote.diagnose("here")["diagnosed"][0]["report"]

    assert report["machine"] == "this machine"
    assert report["connectivity"] == "reachable"
    assert report["services"][0]["state"] == "listening"
    for field in ("probable_cause", "confidence", "recommended_next_action"):
        assert report[field]
