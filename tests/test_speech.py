"""A real voice for the agents (gateway/speech.py; docs/VOICE_AND_PRESENCE.md).

Krish, 2026-11-21, with a recording of an AI host on a live stream: *"This is
how any of our agents should talk... This is how realistically they should
talk."* Until this release every reply was read by the browser's own
synthesiser. Now the page asks the Gateway for the reply as audio and plays
what comes back, and the turn itself is written for the ear when it arrived by
voice.

What is worth a suite, and the direction each fails in:

**The adapter sends exactly what the pure code decided.** The request a test
can read (`request_for`) and the request the network receives must be the same
object. If they drift, every assertion here is about a request nobody sends.

**No key means the old behaviour, not an error.** A Gateway without a provider
is every Gateway there was until today. 204 and the browser voice is the right
answer; a 500 would take the voice away from a deployment that never asked for
a new one.

**The script does not read the screen aloud.** Headings, bullets, fences, URLs:
each is asserted individually, because the first version of a cleaner always
handles the case its author thought of.

**A turn that arrived by voice is told so, and one that did not is not.** The
delivery paragraph changes how the model writes; applied to typed turns it
would strip a list from an answer that needed one.

**The voice is the same tomorrow.** Derived from the name and nothing else.

There is no JavaScript runtime in this suite, so the page's half is asserted
against its source, as test_gateway_attachments does: weaker than executing it,
and it catches the page posting to a route that moved or forgetting the flag.
"""

import json

import pytest

from app import model_gateway
from gateway import client_agent, conversation, roles, speech, store

# A key that is obviously not real, for environments the tests build.
FAKE_KEY = "test-key-not-real"


def _env(**keys):
    """An environment with only what the test names, so a developer's real key
    in os.environ cannot make a test pass by accident."""
    return dict(keys)


# --- which provider, which voice ------------------------------------------


def test_no_key_means_no_provider_and_that_is_not_an_error():
    assert speech.provider_in_force(_env()) is None
    assert speech.speak("Hello.", env=_env()) is None


def test_the_first_configured_provider_in_table_order_wins():
    assert speech.provider_in_force(_env(ELEVENLABS_API_KEY=FAKE_KEY)) == "elevenlabs"
    assert speech.provider_in_force(_env(OPENAI_API_KEY=FAKE_KEY)) == "openai"
    both = _env(ELEVENLABS_API_KEY=FAKE_KEY, OPENAI_API_KEY=FAKE_KEY)
    assert speech.provider_in_force(both) == "elevenlabs"
    assert list(speech.PROVIDERS) == ["elevenlabs", "openai"], (
        "table order is the tie-break, so the order is part of the contract")


def test_an_explicit_choice_is_honoured_only_with_its_key():
    both = _env(ELEVENLABS_API_KEY=FAKE_KEY, OPENAI_API_KEY=FAKE_KEY,
                JARVIS_VOICE_PROVIDER="openai")
    assert speech.provider_in_force(both) == "openai"
    # Named but keyless is a configuration error, and the honest outcome is
    # "no provider", not a 401 on every reply from the other one.
    assert speech.provider_in_force(
        _env(ELEVENLABS_API_KEY=FAKE_KEY, JARVIS_VOICE_PROVIDER="openai")) is None
    assert speech.provider_in_force(
        _env(ELEVENLABS_API_KEY=FAKE_KEY, JARVIS_VOICE_PROVIDER="nonsuch")) is None


def test_every_provider_row_has_a_voice_for_every_persona():
    """A persona with no id on one provider would fall silently to the
    operator's voice on that provider - two agents sharing a voice is the
    thing `voice_for` exists to prevent."""
    for name, row in speech.PROVIDERS.items():
        assert set(row["voices"]) == set(speech.PERSONAS), name
        assert row["key_env"] and row["url"] and row["model"]


def test_an_agent_keeps_the_same_voice_and_different_agents_differ():
    assert speech.voice_for("Ada") == speech.voice_for("Ada")
    assert speech.voice_for("Ada")["persona"] in speech.PERSONAS
    personas = {speech.voice_for(name)["persona"] for name in client_agent.NAME_POOL}
    assert len(personas) > 1, "the pool must not collapse onto one voice"


def test_the_operator_assistant_has_one_fixed_voice():
    assert speech.voice_for(None)["persona"] == "steady"
    assert speech.voice_for("")["persona"] == "steady"


# --- the spoken form ------------------------------------------------------


def test_the_script_keeps_the_words_and_drops_the_markup():
    text = ("## Summary\n\n"
            "- **First** thing\n"
            "- Second `thing`\n\n"
            "See [the docs](https://example.com/docs) or https://example.com/raw now.\n")
    spoken = speech.script(text)
    assert spoken == ("Summary. First thing. Second thing. "
                      "See the docs or a link now.")


def test_a_code_block_is_replaced_by_a_sentence_saying_so():
    spoken = speech.script("Run this:\n```sh\npytest -q\n```\nThen tell me.")
    assert "pytest" not in spoken
    assert "There is a block of code on the screen." in spoken
    assert spoken.startswith("Run this:") and spoken.endswith("Then tell me.")


def test_a_table_is_spoken_a_row_at_a_time():
    spoken = speech.script("| Name | Role |\n|---|---|\n| Ada | lead |")
    assert spoken == "Name, Role. Ada, lead."


def test_an_unpunctuated_line_gets_a_full_stop_so_the_voice_pauses():
    assert speech.script("One thought\nAnother thought") == "One thought. Another thought."


def test_an_empty_or_markup_only_reply_is_not_sent_anywhere():
    calls = []
    env = _env(OPENAI_API_KEY=FAKE_KEY)
    assert speech.speak("", env=env, adapter=calls.append) is None
    assert speech.speak("---\n\n", env=env, adapter=calls.append) is None
    assert calls == []


def test_a_long_reply_is_cut_at_a_sentence_and_the_cut_is_declared():
    sentence = "This is one sentence of the answer. "
    text = sentence * 200
    spoken, truncated = speech.cut(speech.script(text))
    assert truncated is True
    assert len(spoken) <= speech.MAX_SPEECH_CHARS + len(" The rest is on the screen.")
    assert spoken.endswith("of the answer. The rest is on the screen.")
    short, kept = speech.cut("Short.")
    assert (short, kept) == ("Short.", False)


def test_the_speech_limit_is_what_it_is():
    """2,400 characters is about two minutes of speech. Written as a literal
    because the number is the policy: the point at which a reply read aloud
    stops being an answer and starts being a bill (CLAUDE.md, the constant
    rule)."""
    assert speech.MAX_SPEECH_CHARS == 2400
    assert speech.TIMEOUT_SECONDS == 20


# --- the request, and the adapter that sends it ------------------------------


def test_the_request_for_each_provider_carries_key_voice_model_and_text():
    env = _env(ELEVENLABS_API_KEY="eleven-key", OPENAI_API_KEY="openai-key")

    eleven = speech.request_for("elevenlabs", "Hello there.", "warm", env)
    assert eleven["url"] == "https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM"
    assert eleven["headers"]["xi-api-key"] == "eleven-key"
    assert eleven["json"]["text"] == "Hello there."
    assert eleven["json"]["model_id"] == "eleven_turbo_v2_5"

    openai = speech.request_for("openai", "Hello there.", "low", env)
    assert openai["url"] == "https://api.openai.com/v1/audio/speech"
    assert openai["headers"]["Authorization"] == "Bearer openai-key"
    assert openai["json"] == {"model": "gpt-4o-mini-tts", "voice": "onyx",
                              "input": "Hello there.", "response_format": "mp3",
                              "speed": 1.0}


def test_speak_hands_the_adapter_the_request_the_pure_code_built():
    """The property the split rests on: what `request_for` decides is what
    goes on the wire, with nothing added on the way."""
    sent = []

    def adapter(request):
        sent.append(request)
        return b"MP3"

    result = speech.speak("- **Hi** Ada", agent_name="Ada",
                          env=_env(OPENAI_API_KEY=FAKE_KEY), adapter=adapter)
    assert result["audio"] == b"MP3"
    assert result["provider"] == "openai"
    assert result["spoken"] == "Hi Ada."
    assert result["truncated"] is False
    assert sent == [speech.request_for("openai", "Hi Ada.",
                                       speech.voice_for("Ada")["persona"],
                                       _env(OPENAI_API_KEY=FAKE_KEY))]


def test_the_adapter_posts_the_request_as_is_and_returns_the_bytes(monkeypatch):
    posted = {}

    class Response:
        status_code = 200
        content = b"audio-bytes"

    def post(url, headers=None, json=None, timeout=None):
        posted.update(url=url, headers=headers, json=json, timeout=timeout)
        return Response()

    monkeypatch.setattr(speech.requests, "post", post)
    request = speech.request_for("openai", "Hi.", "warm", _env(OPENAI_API_KEY=FAKE_KEY))
    assert speech.synthesize(request) == b"audio-bytes"
    assert posted == {"url": request["url"], "headers": request["headers"],
                      "json": request["json"], "timeout": speech.TIMEOUT_SECONDS}


def test_a_provider_that_fails_raises_rather_than_returning_an_error_page(monkeypatch):
    class Refused:
        status_code = 401
        content = b'{"error": "bad key"}'

    monkeypatch.setattr(speech.requests, "post", lambda *a, **k: Refused())
    request = speech.request_for("openai", "Hi.", "warm", _env(OPENAI_API_KEY=FAKE_KEY))
    with pytest.raises(speech.SpeechUnavailable):
        speech.synthesize(request)

    def unreachable(*a, **k):
        raise speech.requests.ConnectionError("no route")

    monkeypatch.setattr(speech.requests, "post", unreachable)
    with pytest.raises(speech.SpeechUnavailable):
        speech.synthesize(request)


def test_the_adapter_has_no_branches():
    """CLAUDE.md: a judgement inside an adapter is a bug in the split, because
    the adapter is the part the suite cannot test. Asserted over the AST, not
    the text - a docstring saying "no branching" would pass a text search."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(speech.synthesize))
    branches = [node for node in ast.walk(tree)
                if isinstance(node, (ast.If, ast.For, ast.While, ast.Match, ast.IfExp))]
    # One `if`: the status check that turns a refusal into the exception. That
    # is the whole allowance, and it is an allowance rather than a decision.
    assert len(branches) == 1 and isinstance(branches[0], ast.If)


# --- the route ------------------------------------------------------------


def test_without_a_provider_the_route_says_204_and_the_page_keeps_its_voice(
        gateway_client, gateway_token, monkeypatch):
    for key in ("ELEVENLABS_API_KEY", "OPENAI_API_KEY", "JARVIS_VOICE_PROVIDER"):
        monkeypatch.delenv(key, raising=False)
    response = gateway_client.post("/speech", json={"text": "Hello."},
                                   headers={"Authorization": "Bearer " + gateway_token})
    assert response.status_code == 204


def test_the_route_returns_the_audio_with_its_type(gateway_client, gateway_token, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_VOICE_PROVIDER", raising=False)
    sent = []
    monkeypatch.setattr(speech, "synthesize", lambda request: sent.append(request) or b"MP3")

    response = gateway_client.post("/speech", json={"text": "## Hello\n- there"},
                                   headers={"Authorization": "Bearer " + gateway_token})
    assert response.status_code == 200, response.text
    assert response.content == b"MP3"
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert response.headers["x-speech-provider"] == "openai"
    assert response.headers["x-speech-truncated"] == "0"
    assert sent[0]["json"]["input"] == "Hello. there."
    # The operator hears Jarvis, who has one voice.
    assert sent[0]["json"]["voice"] == speech.PROVIDERS["openai"]["voices"]["steady"]


def test_a_client_hears_their_own_representative(gateway_client, gateway_conn, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_VOICE_PROVIDER", raising=False)
    sent = []
    monkeypatch.setattr(speech, "synthesize", lambda request: sent.append(request) or b"MP3")
    token, _ = store.create_session(gateway_conn, 60, roles.ROLE_CLIENT, subject="customer")
    agent = client_agent.ensure(gateway_conn, "customer")

    response = gateway_client.post("/speech", json={"text": "Hello."},
                                   headers={"Authorization": "Bearer " + token})
    assert response.status_code == 200, response.text
    persona = speech.voice_for(agent["name"])["persona"]
    assert sent[0]["json"]["voice"] == speech.PROVIDERS["openai"]["voices"][persona]


def test_a_configured_provider_that_fails_is_a_503_not_a_silent_204(
        gateway_client, gateway_token, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    monkeypatch.delenv("JARVIS_VOICE_PROVIDER", raising=False)

    def down(request):
        raise speech.SpeechUnavailable("provider answered 500")

    monkeypatch.setattr(speech, "synthesize", down)
    response = gateway_client.post("/speech", json={"text": "Hello."},
                                   headers={"Authorization": "Bearer " + gateway_token})
    assert response.status_code == 503
    assert "voice" in response.json()["detail"].lower()


def test_the_route_needs_a_session(gateway_client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    monkeypatch.setattr(speech, "synthesize", lambda request: b"MP3")
    assert gateway_client.post("/speech", json={"text": "Hello."}).status_code == 401


def test_the_ready_frame_carries_the_agents_persona(gateway_client, gateway_conn):
    token, _ = store.create_session(gateway_conn, 60, roles.ROLE_CLIENT, subject="customer")
    with gateway_client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "auth", "token": token})
        ready = socket.receive_json()
    assert ready["agent"]["voice"]["persona"] == speech.voice_for(ready["agent"]["name"])["persona"]


# --- the turn is written for the ear when it arrived by voice -----------------


class _Listening:
    """A provider that records the system prompt it was handed."""

    def __init__(self):
        self.systems = []

    def stream(self, system, messages, tools, max_tokens=2048):
        self.systems.append(system)
        yield {"type": "text", "text": "Right. "}
        yield {"type": "final", "content": [{"type": "text", "text": "Right. "}],
               "stop_reason": "end_turn"}

    def complete(self, system, messages, tools, max_tokens=2048):
        raise AssertionError("the Gateway conversation must stream, not complete")


@pytest.fixture
def listening():
    provider = _Listening()
    model_gateway.set_provider(provider)
    try:
        yield provider
    finally:
        model_gateway.set_provider(None)


def _turn(client, token, frame):
    with client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "auth", "token": token})
        socket.receive_json()
        socket.send_json(frame)
        while socket.receive_json()["type"] != "done":
            pass


def test_a_spoken_turn_is_answered_for_the_ear_and_a_typed_one_is_not(
        gateway_client, gateway_token, listening):
    _turn(gateway_client, gateway_token, {"type": "message", "text": "hello", "spoken": True})
    _turn(gateway_client, gateway_token, {"type": "message", "text": "hello"})
    # A frame is whatever arrived on a socket: only the boolean counts.
    _turn(gateway_client, gateway_token, {"type": "message", "text": "hello", "spoken": "yes"})

    spoken, typed, stringly = listening.systems
    assert speech.DELIVERY_PARAGRAPH in spoken
    assert speech.DELIVERY_PARAGRAPH not in typed
    assert speech.DELIVERY_PARAGRAPH not in stringly
    assert spoken.replace(speech.DELIVERY_PARAGRAPH, "") == typed, (
        "the delivery paragraph is the only difference between the two")


def test_the_delivery_paragraph_asks_for_what_the_recording_has():
    """The register Krish pointed at: short sentences, answer first, nothing
    that only makes sense on a screen, no sign-off."""
    paragraph = speech.DELIVERY_PARAGRAPH
    for ask in ("Short sentences", "Answer first", "No markdown", "URL", "sign off"):
        assert ask in paragraph
    # The third sample (2026-11-22) is a Hindi comedy skit. The agents answer
    # in the language they were spoken to, Hinglish included.
    assert "Hindi" in paragraph and "Hinglish" in paragraph
    assert "answers Hindi in English is wrong" in paragraph


def test_run_turn_takes_the_flag_and_defaults_to_typed(tmp_path):
    """The parameter exists on the function the socket calls, and absent means
    typed - a caller that forgot it must not get the spoken register."""
    provider = _Listening()
    db = tmp_path / "g.db"
    store.get_connection(db).close()
    list(conversation.run_turn(db, [{"role": "user", "text": "hi"}], provider,
                               role=roles.ROLE_OPERATOR))
    list(conversation.run_turn(db, [{"role": "user", "text": "hi"}], provider,
                               role=roles.ROLE_OPERATOR, spoken=True))
    assert speech.DELIVERY_PARAGRAPH not in provider.systems[0]
    assert speech.DELIVERY_PARAGRAPH in provider.systems[1]


# --- the page's half, against its source --------------------------------------


def test_the_page_asks_the_gateway_for_the_voice_before_the_browser(gateway_client):
    body = gateway_client.get("/").text
    assert 'fetch("/speech"' in body
    assert "new Audio(" in body
    # The browser voice stays, as the fallback - and so does its disclosure.
    assert "SpeechSynthesisUtterance" in body
    assert "response.status !== 200" in body, "204 and failures both mean the browser voice"


def test_the_page_sends_the_spoken_flag_from_the_microphone_state(gateway_client):
    body = gateway_client.get("/").text
    assert 'JSON.stringify({ type: "message", text, spoken: voice.enabled })' in body


def test_an_interruption_also_stops_audio_still_being_fetched(gateway_client):
    """Barge-in won against the browser voice because synth.cancel() is
    synchronous. Against a fetch it is a race: the user interrupts, the audio
    lands a second later, and it plays over their next sentence. The generation
    counter is what settles the race, and this is the only line that holds it."""
    body = gateway_client.get("/").text
    assert "const generation = ++voice.generation;" in body
    assert "if (generation !== voice.generation || !voice.speaking)" in body
    assert "voice.audio.pause()" in body


def test_the_voice_record_names_the_derivation_and_the_fallback(gateway_conn):
    """Replaces the test that asserted the record promised nothing: it now
    promises exactly what gateway/speech.py does, and names the browser as
    what happens when no provider is configured."""
    voice = client_agent.ensure(gateway_conn, "customer")["voice"]
    assert "gateway/speech.py" in voice["synthesis"]
    assert "browser voice when none is" in voice["synthesis"]
    json.dumps(voice)


# --- how an agent carries itself (gateway/persona.py, Krish 2026-11-22) -------


def test_both_prompts_carry_the_owners_bearing_rules():
    """One paragraph, both prompts. The rules are about bearing, and Jarvis and
    a client's representative carry themselves the same way; what each may do
    is still the tool tables' decision."""
    from gateway import persona
    assert persona.bearing_paragraph() in conversation.operator_prompt()
    assert persona.bearing_paragraph() in conversation.client_prompt("Ada", roles.ROLE_CLIENT)


def test_the_bearing_rules_say_what_he_said():
    """His points, each as a phrase that must survive a rewrite: the risk
    before the joke, the first useful part first, fillers that are not facts,
    and blame only when it is earned."""
    from gateway import persona
    paragraph = persona.bearing_paragraph()
    for rule in ("Confident and warm", "real risk plainly first", "Never let the joke replace the warning",
                 "first useful part as soon as you have it", "never a made-up fact",
                 "never the same one twice in a row", "draw the worry in",
                 "Own a mistake that was yours", "Do not accept blame for one that was not"):
        assert rule in paragraph, rule


def test_the_bearing_paragraph_grants_no_capability():
    """It is about manner, not permission. A sentence in it that named a tool
    or a capability would be a grant the tables never made."""
    from gateway import persona, skills
    paragraph = persona.bearing_paragraph().lower()
    for word in ("tool", "capability", "you may", "you can now", "allowed to"):
        assert word not in paragraph, word
    for capability in roles.CAPABILITIES:
        assert capability.lower() not in paragraph
