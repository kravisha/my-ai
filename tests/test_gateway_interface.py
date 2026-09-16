"""The agent's knowledge of the page, and the one thing it may do to it.

Krish, 2026-09-16, by phone from abroad: *"make him self aware about all the
controls on his interface and he should be able to paste messages in the box
where I send messages to you - currently he is unaware of this."*

Two properties are worth a suite, and they are different in kind.

**The description must match the page.** `gateway/interface.py` declares the
controls; `gateway/static/voice.html` has them. Nothing at runtime compares the
two, on purpose - an ImportError in that module would take the owner's only line
of contact down while he is abroad, which is a worse failure than a stale
sentence. So the comparison lives here, where a renamed button fails a test
instead of shipping an agent that is confidently wrong about a page it cannot
see.

**Drafting must not be sending.** Box 2 appends to the file that *wakes* the
Claude session on this machine, and every line it writes is attributed "relayed
by Jarvis at Krish's direction". An assistant able to send would be able to wake
another agent unattended under an attribution that had stopped being true. The
tests below assert that the tool writes nothing, that the frame it produces
carries no authority to send, and that the page's handler for it does not touch
the send path.

There is no JavaScript runtime in this suite, so the page's half is asserted
against its source. That is weaker than executing it and it is not nothing: the
failure it catches - a server that emits a frame no page listens for, or a
handler quietly rewired to send - is the failure that would be discovered by the
owner, on a phone, in another country.
"""

import os
from datetime import datetime
from pathlib import Path

import pytest

from app import model_gateway
from gateway import conversation, interface, roles, skills, tools, uiversion


def page_source() -> str:
    """The voice page as shipped. `uiversion.VOICE_PAGE` rather than a path built
    here, because that module already owns where the page is and a second answer
    would be the drift this file exists to catch."""
    return uiversion.VOICE_PAGE.read_text(encoding="utf-8")


class ToolCallingProvider:
    """One turn that calls a named tool, then answers.

    Shaped like `tests/test_gateway_service.FakeProvider` and deliberately local:
    what it has to control is which tool is asked for and with what arguments, and
    a shared fake that grew this knob for one caller would carry it for everybody.

    `complete` raises for the same reason it does there - the Gateway conversation
    is streaming-only, and a silent fallback to a blocking call would hide a
    wiring mistake that matters.
    """

    def __init__(self, name, arguments, reply="It is in box 2, unsent."):
        self.name = name
        self.arguments = arguments
        self.reply = reply
        self.calls = []

    def complete(self, system, messages, tools, max_tokens=2048):
        raise AssertionError("the Gateway conversation must stream, not complete")

    def stream(self, system, messages, tools, max_tokens=2048):
        self.calls.append({"system": system, "tools": tools})
        if len(self.calls) == 1:
            yield {
                "type": "final",
                "content": [{
                    "type": "tool_use",
                    "id": "tu_1",
                    "name": self.name,
                    "input": self.arguments,
                }],
                "stop_reason": "tool_use",
            }
            return
        yield {"type": "text", "text": self.reply}
        yield {
            "type": "final",
            "content": [{"type": "text", "text": self.reply}],
            "stop_reason": "end_turn",
        }


# --- the description matches the page -----------------------------------------------


def test_every_declared_control_exists_on_the_page():
    """The drift guard, and the reason the registry is a registry.

    Claude Dev edits this page from another machine and it is read from disk per
    request, so his edit is live on Krish's phone with no restart. An agent
    describing a button that has been renamed does not fail - it explains the old
    page fluently, which is worse than admitting it does not know."""
    page = page_source()
    missing = [control.element_id for control in interface.CONTROLS
               if f'id="{control.element_id}"' not in page]
    assert not missing, (
        f"declared in gateway/interface.py but not on the page: {missing}. "
        "Either the page changed and the registry did not, or a control was "
        "declared that never existed.")


def test_no_control_is_declared_twice():
    ids = [control.element_id for control in interface.CONTROLS]
    assert len(ids) == len(set(ids))


def test_every_control_is_in_a_box_the_agent_is_told_about():
    """A control filed under a box number that is not described would be
    generated into the prompt under a heading that never appears."""
    known = {box.number for box in interface.BOXES} | {"header"}
    for control in interface.CONTROLS:
        assert control.box in known, f"{control.element_id} sits in unknown box {control.box!r}"


def test_the_page_acts_on_every_phrase_the_agent_is_told_about():
    """The agent is told five phrases the page handles before a turn reaches it.
    If one of those triggers is rewritten, the agent starts promising a phrase
    nothing matches - and the failure looks like the model ignoring him."""
    page = page_source()
    for command in interface.SPOKEN:
        assert command.evidence in page, (
            f"the page no longer contains {command.evidence!r}, so the promise "
            f"{command.say!r} may no longer be true")


def test_the_relay_box_the_tool_types_into_is_the_one_the_page_sends():
    """Both halves name the same element. The tool fills `relay`; `sendRelay`
    reads `relay`. A rename that moved only one of them would produce an
    assistant that drafts into a box nobody sends."""
    page = page_source()
    assert 'id="relay"' in page
    assert 'id="sendRelay"' in page
    assert any(control.element_id == "relay" for control in interface.CONTROLS)


# --- the operator is told, which is the whole complaint ------------------------------


def test_the_operator_prompt_describes_the_boxes_and_the_controls():
    prompt = conversation.operator_prompt()
    for box in interface.BOXES:
        assert box.title in prompt
    for control in interface.CONTROLS:
        assert control.label in prompt, f"{control.element_id} is not in the prompt"


def test_the_operator_prompt_says_the_box_can_be_typed_into():
    """The regression for what Krish actually reported: asked to put something in
    box 2, the agent said it had read-only access to the running system. That was
    a true sentence about a different question. Nothing had told it the box was
    there."""
    prompt = conversation.operator_prompt()
    assert "draft_message_to_claude" in prompt
    assert "Box 2" in prompt


def test_the_operator_prompt_refuses_the_agent_the_send_button():
    """The line that keeps the attribution honest. It is in the prompt as well as
    the tool description because the model reads the prompt every turn and the
    description only when it is choosing a tool."""
    prompt = conversation.operator_prompt()
    assert "cannot press Send to Claude" in prompt


def test_the_operator_prompt_carries_the_build_version():
    """`gateway/uiversion.py` exists because Krish and Claude Dev lost a day to a
    cached page, and its paragraph was reaching the *client* prompt only. The one
    role that has ever reported a stale build was the one not being told the
    number."""
    info = uiversion.current()
    assert info["ok"], "the page is missing, which is a real failure with its own cause"
    assert info["version"] in conversation.operator_prompt()


def test_the_operator_prompt_still_contains_the_fixed_instructions():
    """Generated paragraphs are appended to SYSTEM_PROMPT, never in place of it."""
    prompt = conversation.operator_prompt()
    assert conversation.SYSTEM_PROMPT in prompt
    assert "Super User" in prompt


def test_the_client_is_not_told_about_the_operator_s_page():
    """A client meets a representative with no relay box, no inbox, and no
    business knowing that the operator's page has either (§95). The paragraph is
    wired into one prompt on purpose."""
    client = conversation.client_prompt("Nadim", roles.ROLE_CLIENT)
    assert "Box 2" not in client
    assert "Send to Claude" not in client
    assert "draft_message_to_claude" not in client


# --- the tool: what it is allowed to reach ------------------------------------------


def test_the_draft_tool_is_offered_to_the_operator():
    offered = {tool["name"] for tool in tools.for_role(roles.ROLE_OPERATOR)}
    assert "draft_message_to_claude" in offered


def test_the_draft_tool_is_not_offered_to_anybody_else():
    """`publish` is operator-only, and this is the capability's point: a client
    who could fill the operator's outbox has put words in his mouth, whoever
    presses the button afterwards."""
    for role in (roles.ROLE_CLIENT, roles.ROLE_INTERNAL):
        offered = {tool["name"] for tool in tools.for_role(role)}
        assert "draft_message_to_claude" not in offered


@pytest.mark.parametrize("role", [roles.ROLE_CLIENT, roles.ROLE_INTERNAL])
def test_the_draft_tool_does_not_execute_for_anybody_else(gateway_conn, role):
    """Checked at execution and not only at offering: a model can name a tool
    nobody put in front of it, and filtering the list is presentation."""
    outcome = tools.execute(gateway_conn, "draft_message_to_claude",
                            {"text": "anything"}, role=role)
    assert "error" in outcome and "Not permitted" in outcome["error"]
    assert "ui" not in outcome


def test_the_tool_and_the_relay_route_share_one_capability():
    """`/voice/relay`, the `relay_to_claude` skill and this tool are three faces
    of one act. Splitting the capability would let one of them be granted
    without the others."""
    assert tools.TOOL_CAPABILITY["draft_message_to_claude"] == roles.CAP_PUBLISH
    declared = {skill.name: skill for skill in skills.SKILLS}
    assert declared["relay_to_claude"].capability == roles.CAP_PUBLISH


# --- the tool: what it does, and what it must not do --------------------------------


def test_drafting_returns_a_frame_the_page_can_act_on(gateway_conn):
    outcome = tools.execute(
        gateway_conn, "draft_message_to_claude",
        {"text": "  The label on the page is wrong.  "},
        role=roles.ROLE_OPERATOR,
    )

    assert outcome["drafted"] is True
    assert outcome["ui"] == {
        "action": interface.ACTION_DRAFT_RELAY,
        "text": "The label on the page is wrong.",
    }
    assert outcome["chars"] == len("The label on the page is wrong.")


def test_drafting_tells_the_model_to_say_it_is_unsent(gateway_conn):
    """The model reads this note and speaks from it. "I have sent it to Claude" is
    the one sentence here that would be a lie with a consequence."""
    outcome = tools.execute(gateway_conn, "draft_message_to_claude",
                            {"text": "anything"}, role=roles.ROLE_OPERATOR)
    assert "not sent" in outcome["note"]
    assert "Send to Claude" in outcome["note"]


def test_drafting_writes_nothing_and_sends_nothing(gateway_conn, tmp_path, monkeypatch):
    """The property the whole design rests on. Box 2's contents reach Claude by
    being appended to a file, and that file is what wakes him - so a draft that
    touched it would be a message sent by an assistant under the owner's name."""
    channel = tmp_path / "KRISH-TO-CLAUDE-DEPLOY.md"
    monkeypatch.setenv("JARVIS_CLAUDE_CHANNEL", str(channel))

    outcome = tools.execute(gateway_conn, "draft_message_to_claude",
                            {"text": "Pull master and restart."},
                            role=roles.ROLE_OPERATOR)

    assert outcome["drafted"] is True
    assert not channel.exists(), "drafting wrote to the channel; it must only fill a box"


def test_an_empty_draft_is_refused_as_data(gateway_conn):
    """Returned, not raised, so the model corrects itself from the string instead
    of the turn collapsing."""
    for empty in ("", "   ", "\n"):
        outcome = tools.execute(gateway_conn, "draft_message_to_claude",
                                {"text": empty}, role=roles.ROLE_OPERATOR)
        assert "error" in outcome
        assert "ui" not in outcome


def test_a_missing_argument_is_refused_the_same_way(gateway_conn):
    """`tests/test_gateway_tools.test_every_declared_tool_is_dispatchable` calls
    every tool with no arguments at all. This is that call, asserted for what it
    should say rather than only for not being 'Unknown tool'."""
    outcome = tools.execute(gateway_conn, "draft_message_to_claude", {},
                            role=roles.ROLE_OPERATOR)
    assert "error" in outcome
    assert "ui" not in outcome


def test_a_draft_too_long_for_the_relay_is_refused_before_it_reaches_the_box(gateway_conn):
    """Refused here rather than at the button. An assistant that fills the box
    with more than the relay accepts has produced a message he discovers is
    unsendable by trying to send it."""
    outcome = tools.execute(
        gateway_conn, "draft_message_to_claude",
        {"text": "x" * (interface.RELAY_MAX_CHARS + 1)},
        role=roles.ROLE_OPERATOR,
    )
    assert "error" in outcome
    assert str(interface.RELAY_MAX_CHARS) in outcome["error"]
    assert "ui" not in outcome


def test_a_draft_at_the_limit_is_accepted(gateway_conn):
    outcome = tools.execute(
        gateway_conn, "draft_message_to_claude",
        {"text": "x" * interface.RELAY_MAX_CHARS},
        role=roles.ROLE_OPERATOR,
    )
    assert outcome["drafted"] is True


# --- the turn, and the socket -------------------------------------------------------


def test_the_turn_forwards_the_draft_and_marks_the_tool_call(tmp_path, gateway_conn):
    provider = ToolCallingProvider("draft_message_to_claude",
                                   {"text": "Two releases are on master."})

    events = list(conversation.run_turn(
        tmp_path / "gateway.db",
        [{"role": "user", "text": "tell Claude two releases are on master"}],
        provider,
        role=roles.ROLE_OPERATOR,
    ))

    kinds = [event["type"] for event in events]
    assert "tool" in kinds and "ui" in kinds
    assert kinds.index("tool") < kinds.index("ui"), (
        "the page should be told after the call is reported, not before it happened")

    ui = next(event for event in events if event["type"] == "ui")
    assert ui == {"type": "ui", "action": "draft_relay",
                  "text": "Two releases are on master."}


def test_a_tool_with_no_page_effect_produces_no_ui_event(tmp_path, gateway_conn):
    """The filter, asserted from the other side. Every other tool returns a dict
    too, and none of them should be able to reach his screen."""
    provider = ToolCallingProvider("list_scoreboard_items", {})

    events = list(conversation.run_turn(
        tmp_path / "gateway.db",
        [{"role": "user", "text": "what is open"}],
        provider,
        role=roles.ROLE_OPERATOR,
    ))

    assert not [event for event in events if event["type"] == "ui"]


def test_an_undeclared_action_is_not_forwarded(tmp_path, gateway_conn, monkeypatch):
    """A tool returning a `ui` key with an action nobody declared must not become
    a frame the page trusts. Asserted by forging exactly that return value, which
    is the mistake a future tool would make in good faith."""
    def forged(conn, name, arguments, *, role, subject=None):
        return {"ok": True, "ui": {"action": "press_send", "text": "go"}}

    monkeypatch.setattr(tools, "execute", forged)
    provider = ToolCallingProvider("list_scoreboard_items", {})

    events = list(conversation.run_turn(
        tmp_path / "gateway.db",
        [{"role": "user", "text": "anything"}],
        provider,
        role=roles.ROLE_OPERATOR,
    ))

    assert not [event for event in events if event["type"] == "ui"]


def test_the_socket_hands_the_draft_to_the_page(gateway_client, gateway_token):
    """End to end, which is the test Krish asked for: a spoken instruction, a
    tool call, and a frame arriving at the page with the text in it."""
    provider = ToolCallingProvider("draft_message_to_claude",
                                   {"text": "The instance label is wrong."})
    model_gateway.set_provider(provider)
    try:
        socket = gateway_client.websocket_connect("/ws")
        socket.__enter__()
        try:
            socket.send_json({"type": "auth", "token": gateway_token})
            socket.receive_json()          # ready
            socket.send_json({"type": "message",
                              "text": "put a message to Claude in the box for me"})
            frames = []
            while True:
                frame = socket.receive_json()
                frames.append(frame)
                if frame["type"] in ("done", "error"):
                    break
        finally:
            socket.__exit__(None, None, None)
    finally:
        model_gateway.set_provider(None)

    assert [frame for frame in frames if frame["type"] == "error"] == []
    ui = [frame for frame in frames if frame["type"] == "ui"]
    assert len(ui) == 1
    assert ui[0] == {"type": "ui", "action": "draft_relay",
                     "text": "The instance label is wrong."}


def test_the_frame_carries_nothing_but_the_action_and_the_text(gateway_client, gateway_token):
    """Two fields is the whole contract. Forwarding the event through would let
    whatever a tool returned become part of a frame the page trusts."""
    provider = ToolCallingProvider("draft_message_to_claude", {"text": "hello"})
    model_gateway.set_provider(provider)
    try:
        socket = gateway_client.websocket_connect("/ws")
        socket.__enter__()
        try:
            socket.send_json({"type": "auth", "token": gateway_token})
            socket.receive_json()
            socket.send_json({"type": "message", "text": "draft it"})
            frame = socket.receive_json()
            while frame["type"] != "ui":
                assert frame["type"] != "done", "no ui frame arrived"
                frame = socket.receive_json()
        finally:
            socket.__exit__(None, None, None)
    finally:
        model_gateway.set_provider(None)

    assert set(frame) == {"type", "action", "text"}


# --- the page's half ----------------------------------------------------------------


def put_draft_source() -> str:
    """The body of the page's handler for the frame. Asserted as source because
    there is no JavaScript runtime here - see this module's docstring."""
    page = page_source()
    assert "function putDraft" in page, "the page has no handler for the draft frame"
    return page.split("function putDraft", 1)[1].split("\n  }", 1)[0]


def test_the_page_listens_for_the_frame_the_server_sends():
    """The one failure neither side can catch alone: a server emitting a frame no
    page acts on. It would present as Jarvis saying the box was filled while the
    box stayed empty."""
    page = page_source()
    assert 'm.type === "ui"' in page
    assert f'"{interface.ACTION_DRAFT_RELAY}"' in page


def test_the_page_handler_does_not_send():
    """Drafting fills a text area. If this handler ever reaches the relay POST or
    the send button, an assistant has been given the owner's press."""
    body = put_draft_source()
    assert "sendRelay" not in body
    assert "api(" not in body
    assert "/voice/relay" not in body


def test_the_page_handler_persists_what_jarvis_wrote():
    """Setting .value in script does not fire `input`, so the listener that saves
    drafts never sees this text. A message Jarvis composed is more expensive to
    lose than a typed one, not less."""
    body = put_draft_source()
    assert "DRAFT_KEY" in body
    assert "store.setItem" in body


def test_the_page_does_not_speak_the_phrase_that_would_send_it():
    """This page's speech reaches this page's own microphone, and "send it" is a
    trigger the page acts on. An acknowledgement that uttered it could send the
    message it had just drafted."""
    body = put_draft_source()
    spoken = [line for line in body.splitlines() if "speak(" in line]
    assert spoken, "the draft arriving should be announced"
    for line in spoken:
        assert "send it" not in line.lower()


# --- the relay route itself, which had no tests at all ------------------------------


def relay(client, token, text):
    return client.post("/voice/relay", json={"text": text},
                       headers={"Authorization": f"Bearer {token}"})


def test_the_relay_appends_and_attributes(gateway_client, gateway_token, tmp_path, monkeypatch):
    """Append-only is load-bearing: the channel is the shared record of a day's
    work between three parties, and a truncating write would destroy history that
    cannot be reconstructed."""
    channel: Path = tmp_path / "channel.md"
    channel.write_text("# Channel\n\n## earlier entry\n", encoding="utf-8")
    monkeypatch.setenv("JARVIS_CLAUDE_CHANNEL", str(channel))

    response = relay(gateway_client, gateway_token, "  Pull master and restart.  ")

    assert response.status_code == 200, response.text
    body = channel.read_text(encoding="utf-8")
    assert body.startswith("# Channel\n\n## earlier entry\n"), "the relay truncated history"
    assert "KRISH-VIA-JARVIS" in body
    assert "Pull master and restart." in body
    assert response.json()["ok"] is True


def test_the_relay_refuses_an_empty_message(gateway_client, gateway_token, tmp_path, monkeypatch):
    channel = tmp_path / "channel.md"
    monkeypatch.setenv("JARVIS_CLAUDE_CHANNEL", str(channel))

    assert relay(gateway_client, gateway_token, "   ").status_code == 400
    assert not channel.exists()


def test_the_relay_refuses_exactly_what_the_tool_refuses(gateway_client, gateway_token,
                                                         tmp_path, monkeypatch):
    """One ceiling, declared in gateway/interface.py and enforced in both places.
    Two numbers would mean an assistant that can fill the box with more than the
    box will accept."""
    channel = tmp_path / "channel.md"
    monkeypatch.setenv("JARVIS_CLAUDE_CHANNEL", str(channel))
    too_long = "x" * (interface.RELAY_MAX_CHARS + 1)

    assert relay(gateway_client, gateway_token, too_long).status_code == 413
    assert not channel.exists()
    assert "error" in interface.draft_for_relay(too_long)


def test_the_relay_needs_a_session(gateway_client, tmp_path, monkeypatch):
    channel = tmp_path / "channel.md"
    monkeypatch.setenv("JARVIS_CLAUDE_CHANNEL", str(channel))

    response = gateway_client.post("/voice/relay", json={"text": "hello"})

    assert response.status_code in (401, 403)
    assert not channel.exists()


# --- which build he is holding, including the releases he cannot see ----------------
#
# Krish asked twice on 2026-09-16 whether he had the latest version - at 06:11 and
# again at 15:25, the second time hours after a release he had been told about. The
# number was correct both times and useless both times: it counted the page alone,
# and that release had changed the modules behind the page. The tests below hold the
# two halves of the fix apart, because they pull in opposite directions. A version
# must move when code ships, or he learns to distrust it. It must not move before
# the restart that makes the new code the running code, or it lies - and that exact
# lie cost an hour on his live page on 2026-09-15.

PAGE_BUILT = 1_700_000_000       # a page on disk
CODE_DEPLOYED = 1_700_086_400    # modules written a day after it
LATER_STILL = 1_700_172_800      # a pull that has landed but not restarted


def stamped(path: Path, when: int) -> Path:
    """A file standing in for a deployed one, with a chosen modification time.
    The content is irrelevant - every question this module answers is asked of the
    timestamp."""
    path.write_text("# a stand-in for something deployed\n", encoding="utf-8")
    os.utime(path, (when, when))
    return path


def as_version(when: int) -> str:
    return datetime.fromtimestamp(when).strftime("%Y%m%d.%H%M")


def test_a_release_that_changes_only_the_code_moves_the_version(tmp_path, monkeypatch):
    """His complaint, as a test. Nothing about the page changed and the build he is
    served is still a new one."""
    monkeypatch.setattr(uiversion, "VOICE_PAGE", stamped(tmp_path / "voice.html", PAGE_BUILT))
    monkeypatch.setattr(uiversion, "_RUNNING_CODE_MTIME", CODE_DEPLOYED)

    info = uiversion.current()

    assert info["ok"]
    assert info["version"] == as_version(CODE_DEPLOYED)


def test_a_page_newer_than_the_code_still_sets_the_version(tmp_path, monkeypatch):
    """The cache check this module was built for, untouched. The page is read from
    disk per request, so an edited page is a new build to the person looking at it
    whether or not any module moved with it."""
    monkeypatch.setattr(uiversion, "VOICE_PAGE", stamped(tmp_path / "voice.html", CODE_DEPLOYED))
    monkeypatch.setattr(uiversion, "_RUNNING_CODE_MTIME", PAGE_BUILT)

    assert uiversion.current()["version"] == as_version(CODE_DEPLOYED)


def test_the_code_stamp_is_the_newest_module_and_ignores_everything_else(tmp_path, monkeypatch):
    """A deployment writes only the files it changed, so the newest module dates it.
    Only `*.py` counts: the package also carries the compiled cache and the static
    page, and either would date the build by when it was last *read*."""
    stamped(tmp_path / "older.py", PAGE_BUILT)
    stamped(tmp_path / "newer.py", CODE_DEPLOYED)
    stamped(tmp_path / "notes.txt", LATER_STILL)
    monkeypatch.setattr(uiversion, "CODE_DIRS", (tmp_path,))

    assert uiversion._code_mtime() == CODE_DEPLOYED


def test_the_code_stamp_spans_every_directory_this_process_imports(tmp_path, monkeypatch):
    """Two directories, because the Gateway imports the shared model layer as well
    as its own package, and a release to either one changes what the owner is
    talking to. A stamp covering only the first would report no new build for a
    deployment he had been told about, which is the whole fault being fixed."""
    first = tmp_path / "gateway"
    second = tmp_path / "app"
    first.mkdir()
    second.mkdir()
    stamped(first / "main.py", PAGE_BUILT)
    stamped(second / "model_provider.py", CODE_DEPLOYED)
    monkeypatch.setattr(uiversion, "CODE_DIRS", (first, second))

    assert uiversion._code_mtime() == CODE_DEPLOYED


def test_a_directory_that_is_not_there_is_not_a_failure(tmp_path, monkeypatch):
    """A version is not worth raising into a request over. A missing directory
    contributes nothing and the remaining one still dates the build."""
    present = tmp_path / "gateway"
    present.mkdir()
    stamped(present / "main.py", CODE_DEPLOYED)
    monkeypatch.setattr(uiversion, "CODE_DIRS", (present, tmp_path / "never-existed"))

    assert uiversion._code_mtime() == CODE_DEPLOYED


def test_the_code_stamp_is_taken_at_import_and_never_per_request(tmp_path, monkeypatch):
    """The pull-without-restart case, and the reason the snapshot is a module
    constant rather than a call. New modules are sitting on disk; this process is
    still executing the old ones, so the number it reports must not have moved."""
    monkeypatch.setattr(uiversion, "VOICE_PAGE", stamped(tmp_path / "voice.html", PAGE_BUILT))
    monkeypatch.setattr(uiversion, "_RUNNING_CODE_MTIME", CODE_DEPLOYED)
    monkeypatch.setattr(uiversion, "_code_mtime", lambda: LATER_STILL)

    assert uiversion.current()["version"] == as_version(CODE_DEPLOYED)


def test_a_missing_page_is_an_unusable_version_rather_than_a_crash(tmp_path, monkeypatch):
    """A missing page is a real failure with its own cause, and raising it into a
    request would take his only line of contact down to report it."""
    monkeypatch.setattr(uiversion, "VOICE_PAGE", tmp_path / "never-written.html")

    assert uiversion.current() == {"version": "unknown", "built": "unknown", "ok": False}


def test_the_deployed_gateway_is_never_older_than_the_code_it_is_running():
    """Asserted against the real tree, so that counting the page alone cannot come
    back quietly. Versions are strftime-ordered on purpose - a later build is a
    larger string."""
    info = uiversion.current()

    assert info["ok"], "the page is missing, which is a real failure with its own cause"
    assert info["version"] >= as_version(int(uiversion._RUNNING_CODE_MTIME))
