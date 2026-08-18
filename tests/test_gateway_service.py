"""The Gateway as a running service: the boundary, the login, and one turn of
conversation over the WebSocket.

The model is always a stand-in here. What is real is everything else - the
routes, the session checks, the transport protocol and the persistence - which is
where every defect these tests are meant to catch would live.
"""

import pytest
from starlette.websockets import WebSocketDisconnect

from app import model_gateway
from conftest import GATEWAY_TEST_PASSWORD, GATEWAY_TEST_USER
from gateway import auth, store


class FakeProvider:
    """Streams a fixed reply and records what it was asked.

    `complete` deliberately raises: the Gateway conversation is streaming-only,
    and a silent fallback to a blocking call would hide a wiring mistake that
    matters (a non-streaming Gateway fails addendum 16 §9 while still returning
    text).

    `tool_calls` queues turns that ask for a tool before answering, so a test can
    drive the whole loop without a real model."""

    def __init__(self, fragments=("Specification ", "leads ", "the code."), tool_calls=()):
        self.fragments = list(fragments)
        self.tool_calls = list(tool_calls)
        self.calls = []

    def complete(self, system, messages, tools, max_tokens=2048):
        raise AssertionError("the Gateway conversation must stream, not complete")

    def stream(self, system, messages, tools, max_tokens=2048):
        self.calls.append({
            "system": system,
            # A copy, because run_turn appends the assistant's turn to this same
            # list once the stream ends - a stored reference would read back the
            # mutated version and quietly assert nothing about what was sent.
            "messages": [dict(message) for message in messages],
            "tools": tools,
            "max_tokens": max_tokens,
        })
        if self.tool_calls:
            name, arguments = self.tool_calls.pop(0)
            block = {"type": "tool_use", "id": f"tu_{len(self.calls)}", "name": name, "input": arguments}
            yield {"type": "final", "content": [block], "stop_reason": "tool_use"}
            return
        for fragment in self.fragments:
            yield {"type": "text", "text": fragment}
        yield {
            "type": "final",
            "content": [{"type": "text", "text": "".join(self.fragments)}],
            "stop_reason": "end_turn",
        }


class FailingProvider:
    def complete(self, *args, **kwargs):
        raise AssertionError("not used")

    def stream(self, system, messages, tools, max_tokens=2048):
        yield {"type": "text", "text": "I can start "}
        raise RuntimeError("upstream refused")


@pytest.fixture
def fake_model():
    provider = FakeProvider()
    model_gateway.set_provider(provider)
    try:
        yield provider
    finally:
        model_gateway.set_provider(None)


def authenticated_socket(client, token):
    """Opens a socket and completes the handshake, returning it and the ready
    frame. Every conversation test needs both, and doing it by hand each time
    would bury the thing under test."""
    socket = client.websocket_connect("/ws")
    socket.__enter__()
    socket.send_json({"type": "auth", "token": token})
    return socket, socket.receive_json()


# --- The boundary itself ---


def test_health_says_nothing_about_jarvis(gateway_client):
    """An unauthenticated caller learns that a Gateway is here and whether its
    operator finished configuring it. Not what is behind it - addendum 16 §7
    makes this the only externally exposed service, so its unauthenticated
    surface is the one an unknown caller sees."""
    response = gateway_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "configured": True}


def test_the_client_page_is_served(gateway_client):
    response = gateway_client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Jarvis Gateway" in response.text


def test_the_page_fetches_nothing_from_a_third_party(gateway_client):
    """A page that loads a script from a CDN can leak a session token to whoever
    controls that CDN. This service is specified as the external boundary, so
    'no external requests' is a property worth asserting rather than intending."""
    body = gateway_client.get("/").text

    for marker in ("http://", "https://", "//cdn", "integrity="):
        assert marker not in body, f"the client page references something external: {marker}"


# --- Login ---


def test_login_issues_a_session(gateway_client, gateway_conn):
    response = gateway_client.post(
        "/auth/login", json={"username": GATEWAY_TEST_USER, "password": GATEWAY_TEST_PASSWORD}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token"]
    assert store.session_is_valid(gateway_conn, body["token"]) is True


def test_a_wrong_password_is_refused(gateway_client, gateway_conn):
    response = gateway_client.post(
        "/auth/login", json={"username": GATEWAY_TEST_USER, "password": "wrong"}
    )

    assert response.status_code == 401
    assert gateway_conn.fetchall("SELECT 1 FROM sessions") == []


def test_an_unconfigured_gateway_says_so_rather_than_rejecting_the_password(
    gateway_client, monkeypatch
):
    """503 and 401 are different situations. An operator who has not set the
    environment variables would otherwise spend the evening retyping a correct
    password."""
    monkeypatch.delenv(auth.SUPER_USER_ENV, raising=False)
    monkeypatch.delenv(auth.PASSWORD_HASH_ENV, raising=False)

    response = gateway_client.post(
        "/auth/login", json={"username": GATEWAY_TEST_USER, "password": GATEWAY_TEST_PASSWORD}
    )

    assert response.status_code == 503
    assert auth.SUPER_USER_ENV in response.json()["detail"]
    assert gateway_client.get("/health").json()["configured"] is False


def test_logout_ends_the_session(gateway_client, gateway_token, gateway_conn):
    response = gateway_client.post(
        "/auth/logout", headers={"Authorization": f"Bearer {gateway_token}"}
    )

    assert response.status_code == 200
    assert store.session_is_valid(gateway_conn, gateway_token) is False


def test_logout_without_a_token_is_refused(gateway_client):
    assert gateway_client.post("/auth/logout").status_code == 401
    assert gateway_client.post(
        "/auth/logout", headers={"Authorization": "Bearer nonsense"}
    ).status_code == 401


# --- The conversation socket ---


def test_the_socket_refuses_an_unauthenticated_opening_frame(gateway_client):
    with gateway_client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "message", "text": "let me in"})

        assert socket.receive_json() == {"type": "error", "error": "unauthorized"}
        with pytest.raises(WebSocketDisconnect) as disconnected:
            socket.receive_json()
    assert disconnected.value.code == 4401


def test_the_socket_refuses_an_unknown_token(gateway_client):
    with gateway_client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "auth", "token": "not-a-real-token"})

        assert socket.receive_json()["error"] == "unauthorized"


def test_a_valid_token_opens_the_conversation(gateway_client, gateway_token):
    socket, ready = authenticated_socket(gateway_client, gateway_token)
    try:
        assert ready["type"] == "ready"
        assert ready["messages"] == []
        assert ready["conversation_id"] > 0
    finally:
        socket.__exit__(None, None, None)


def test_a_turn_streams_and_is_recorded(gateway_client, gateway_token, gateway_conn, fake_model):
    socket, ready = authenticated_socket(gateway_client, gateway_token)
    try:
        socket.send_json({"type": "message", "text": "what leads, the spec or the code?"})

        deltas = []
        while True:
            frame = socket.receive_json()
            if frame["type"] == "done":
                break
            assert frame["type"] == "delta", frame
            deltas.append(frame["text"])
    finally:
        socket.__exit__(None, None, None)

    # Arriving in pieces is the requirement (§9), not merely arriving.
    assert deltas == ["Specification ", "leads ", "the code."]

    turns = store.history(gateway_conn, ready["conversation_id"])
    assert [(turn["role"], turn["text"]) for turn in turns] == [
        ("user", "what leads, the spec or the code?"),
        ("assistant", "Specification leads the code."),
    ]


def test_the_model_is_given_the_conversation_so_far(gateway_client, gateway_token, fake_model):
    """Context is the difference between a conversation and a series of
    questions, and it is the thing a persistence bug quietly breaks."""
    socket, _ = authenticated_socket(gateway_client, gateway_token)
    try:
        socket.send_json({"type": "message", "text": "first"})
        while socket.receive_json()["type"] != "done":
            pass
        socket.send_json({"type": "message", "text": "second"})
        while socket.receive_json()["type"] != "done":
            pass
    finally:
        socket.__exit__(None, None, None)

    assert [message["content"] for message in fake_model.calls[1]["messages"]] == [
        "first",
        "Specification leads the code.",
        "second",
    ]
    assert fake_model.calls[1]["messages"][1]["role"] == "assistant"


def test_reconnecting_resumes_the_same_conversation(
    gateway_client, gateway_token, fake_model
):
    """Addendum 16 §9's conversation continuity, end to end: the transcript is
    server-side, so closing the tab is not the end of the conversation."""
    socket, first_ready = authenticated_socket(gateway_client, gateway_token)
    try:
        socket.send_json({"type": "message", "text": "remember this"})
        while socket.receive_json()["type"] != "done":
            pass
    finally:
        socket.__exit__(None, None, None)

    socket, second_ready = authenticated_socket(gateway_client, gateway_token)
    try:
        assert second_ready["conversation_id"] == first_ready["conversation_id"]
        assert [message["text"] for message in second_ready["messages"]] == [
            "remember this",
            "Specification leads the code.",
        ]
    finally:
        socket.__exit__(None, None, None)


def test_an_empty_or_oversized_message_is_refused(gateway_client, gateway_token, gateway_conn):
    socket, ready = authenticated_socket(gateway_client, gateway_token)
    try:
        socket.send_json({"type": "message", "text": "   "})
        assert socket.receive_json() == {"type": "error", "error": "empty message"}

        socket.send_json({"type": "message", "text": "x" * 20_001})
        assert socket.receive_json() == {"type": "error", "error": "message too long"}

        socket.send_json({"type": "nonsense"})
        assert socket.receive_json() == {"type": "error", "error": "unknown message type"}

        socket.send_text("{not json")
        assert socket.receive_json() == {"type": "error", "error": "malformed message"}
    finally:
        socket.__exit__(None, None, None)

    assert store.history(gateway_conn, ready["conversation_id"]) == [], (
        "a refused frame must not reach the transcript, or the next model call "
        "is given a turn that was never answered"
    )


def test_a_socket_survives_a_refused_frame(gateway_client, gateway_token, fake_model):
    """The refusals above must not be fatal - a phone client that has to
    reconnect after every typo is unusable."""
    socket, _ = authenticated_socket(gateway_client, gateway_token)
    try:
        socket.send_json({"type": "message", "text": ""})
        socket.receive_json()
        socket.send_json({"type": "message", "text": "still here?"})

        assert socket.receive_json()["type"] == "delta"
    finally:
        socket.__exit__(None, None, None)


def test_a_revoked_session_cannot_keep_talking(
    gateway_client, gateway_token, gateway_conn, fake_model
):
    """The session is re-checked every turn. A socket opened before logout would
    otherwise stay privileged for as long as it was held open, which is the same
    defect as a session that never expires."""
    socket, _ = authenticated_socket(gateway_client, gateway_token)
    try:
        store.delete_session(gateway_conn, gateway_token)
        socket.send_json({"type": "message", "text": "still allowed?"})

        assert socket.receive_json() == {"type": "error", "error": "unauthorized"}
        with pytest.raises(WebSocketDisconnect) as disconnected:
            socket.receive_json()
    finally:
        socket.__exit__(None, None, None)

    assert disconnected.value.code == 4401


def test_a_model_failure_is_reported_and_the_partial_reply_kept(
    gateway_client, gateway_token, gateway_conn
):
    """What the user sees when the model errors mid-reply: an explanation, a
    socket that still works, and no user turn left dangling without a response."""
    model_gateway.set_provider(FailingProvider())
    try:
        socket, ready = authenticated_socket(gateway_client, gateway_token)
        try:
            socket.send_json({"type": "message", "text": "trigger the failure"})

            assert socket.receive_json() == {"type": "delta", "text": "I can start "}
            failure = socket.receive_json()
            assert failure["type"] == "error"
            assert "upstream refused" in failure["error"]
        finally:
            socket.__exit__(None, None, None)
    finally:
        model_gateway.set_provider(None)

    turns = store.history(gateway_conn, ready["conversation_id"])
    assert [(turn["role"], turn["text"]) for turn in turns] == [
        ("user", "trigger the failure"),
        ("assistant", "I can start "),
    ]


def test_the_assistant_is_told_what_it_cannot_do(gateway_client, gateway_token, fake_model):
    """It has Scoreboard tools and nothing else. An assistant that implied it had
    pushed to Git or queried the running system would be inventing the rest of
    the roadmap, so the prompt says so and this asserts it keeps saying so."""
    socket, _ = authenticated_socket(gateway_client, gateway_token)
    try:
        socket.send_json({"type": "message", "text": "publish the spec"})
        while socket.receive_json()["type"] != "done":
            pass
    finally:
        socket.__exit__(None, None, None)

    system = fake_model.calls[0]["system"]
    assert "not built" in system
    assert "Git" in system

    offered = {tool["name"] for tool in fake_model.calls[0]["tools"]}
    assert offered == {
        "file_scoreboard_item",
        "list_scoreboard_items",
        "get_scoreboard_item",
        "add_scoreboard_note",
        "resolve_scoreboard_item",
        "list_repository_files",
        "read_repository_file",
        "publish_document",
        "jarvis_status",
        "jarvis_agent",
        "technology_review",
    }, "the assistant must not be handed a tool for something that is not built"

    assert not any(
        name in offered
        for name in ("retire_agent", "resume_agent", "spawn_agent", "push_branch")
    ), "the system tools are read-only and the Git tools do not push; neither may grow an action"


# --- Voice (G6) ---
#
# The Web Speech API cannot be driven from a Python test, so what is asserted
# here is what the page ships: the controls exist, the disclosure is present, and
# the "no external requests" property survived a feature that could easily have
# reached for a speech service. The behaviour itself is verified in a real
# browser - see the increment's verification notes.


def test_the_page_offers_voice_and_a_way_to_interrupt(gateway_client):
    body = gateway_client.get("/").text

    assert 'id="mic"' in body, "addendum 16 §9 makes voice a primary interface"
    assert 'id="interrupt"' in body, "§9 requires interruption while the assistant speaks"
    assert 'id="input"' in body, "§9 also requires text when the user wants it"


def test_voice_uses_the_browsers_own_speech_and_says_where_the_audio_goes(gateway_client):
    """The disclosure is the point of this test. Chrome's SpeechRecognition sends
    audio to Google; a project whose purpose is controlling what leaves does not
    get to leave that implicit."""
    body = gateway_client.get("/").text

    assert "webkitSpeechRecognition" in body
    assert "speechSynthesis" in body
    assert "Google" in body and "Apple" in body, "the disclosure must stay in the page"


def test_barge_in_listens_on_an_echo_cancelled_stream(gateway_client):
    """The line the whole feature rests on. SpeechRecognition cannot be handed a
    MediaStream, so its capture hears the phone speaker whatever else is done -
    the trigger has to be a second capture the browser will echo-cancel."""
    body = gateway_client.get("/").text

    assert "echoCancellation: true" in body
    assert "getUserMedia" in body


def test_the_barge_in_threshold_is_measured_rather_than_guessed(gateway_client):
    """Echo cancellation is uneven across phones and browsers. A fixed threshold
    would be too deaf on one device and too jumpy on the next, so the trigger is
    set from the residual each reply actually leaks."""
    body = gateway_client.get("/").text

    for knob in ("CALIBRATION_MS", "SUSTAIN_MS", "TRIGGER_MARGIN", "TRIGGER_FLOOR"):
        assert knob in body, f"{knob} is part of the barge-in contract"


def test_the_transcript_filter_is_independent_of_the_trigger(gateway_client):
    """Two guards, not one: even where echo cancellation is poor and the trigger
    never fires, a transcript that repeats what is being spoken must not be sent
    to the model as though the user had said it."""
    body = gateway_client.get("/").text

    assert "function isEcho" in body
    assert "ECHO_OVERLAP" in body


def test_the_fallback_is_kept_and_declared(gateway_client):
    """Without a microphone stream there is no trigger, and the old tap-only
    behaviour is what remains. A user who believes barge-in is armed when it is
    not will talk over the assistant and be ignored, so the page says which mode
    is in force."""
    body = gateway_client.get("/").text

    assert 'id="interrupt"' in body, "the manual control stays as the fallback"
    assert "Barge-in is off" in body
    assert "speaking - tap Stop to interrupt" in body


def test_adding_voice_did_not_add_an_external_request(gateway_client):
    """The property the page has held since G1, re-checked against the feature
    most likely to break it."""
    body = gateway_client.get("/").text

    for marker in ("http://", "https://", "//cdn", "integrity="):
        assert marker not in body
