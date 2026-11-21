"""Mutations that `tests/test_speech.py` must notice.

Krish, 2026-09-23: *"Tests working fine initially is not good testing at all."*
`tests/test_speech.py` went green on its first full run, which per CLAUDE.md
proves nothing yet. These are the ways the voice can be quietly wrong - the
wrong provider, the wrong voice, a URL read aloud, a typed turn given the
spoken register, an interruption that loses the race to a fetch - each applied
to the source with the test that must object named beside it.

Run it directly, never under pytest:

    python tests/probes/speech_probes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

TESTS = Path(__file__).resolve().parents[1]

SPEECH = "gateway/speech.py"
MAIN = "gateway/main.py"
CONVERSATION = "gateway/conversation.py"
PAGE = "gateway/static/index.html"
SUITES = {SPEECH: TESTS / "test_speech.py", MAIN: TESTS / "test_speech.py",
          CONVERSATION: TESTS / "test_speech.py", PAGE: TESTS / "test_speech.py"}

PROBES: list[harness.Probe] = [
    # --- which provider ---------------------------------------------------------
    (
        SPEECH,
        "a named provider without its key is still chosen",
        '        return explicit if row and env.get(row["key_env"]) else None',
        '        return explicit if row else None',
        ("test_an_explicit_choice_is_honoured_only_with_its_key",),
    ),
    (
        SPEECH,
        "the last configured provider wins instead of the first",
        '    for name, row in PROVIDERS.items():\n        if env.get(row["key_env"]):\n            return name\n    return None',
        '    chosen = None\n    for name, row in PROVIDERS.items():\n        if env.get(row["key_env"]):\n            chosen = name\n    return chosen',
        ("test_the_first_configured_provider_in_table_order_wins",),
    ),
    (
        SPEECH,
        "a Gateway with no key still tries to speak",
        "    if provider is None:\n        return None\n    spoken, truncated",
        "    if provider is None:\n        provider = 'openai'\n    spoken, truncated",
        ("test_no_key_means_no_provider_and_that_is_not_an_error",
         "test_without_a_provider_the_route_says_204_and_the_page_keeps_its_voice"),
    ),
    # --- which voice ------------------------------------------------------------
    (
        SPEECH,
        "every agent gets the operator's voice",
        "    persona = PERSONAS[int(digest, 16) % len(PERSONAS)]",
        "    persona = OPERATOR_PERSONA",
        ("test_an_agent_keeps_the_same_voice_and_different_agents_differ",),
    ),
    (
        SPEECH,
        "the operator's voice drifts with whatever persona sorts first",
        '        return {"persona": OPERATOR_PERSONA, "source": "operator assistant"}',
        '        return {"persona": PERSONAS[1], "source": "operator assistant"}',
        ("test_the_operator_assistant_has_one_fixed_voice",),
    ),
    (
        SPEECH,
        "a persona the provider lacks falls to the first voice rather than the operator's",
        '    voice = row["voices"].get(persona) or row["voices"][OPERATOR_PERSONA]',
        '    voice = row["voices"]["warm"]',
        ("test_the_request_for_each_provider_carries_key_voice_model_and_text",
         "test_a_client_hears_their_own_representative"),
    ),
    (
        SPEECH,
        "the OpenAI table loses a persona",
        '"voices": {"warm": "nova", "bright": "shimmer", "steady": "alloy", "low": "onyx"},',
        '"voices": {"warm": "nova", "bright": "shimmer", "steady": "alloy"},',
        ("test_every_provider_row_has_a_voice_for_every_persona",),
    ),
    # --- the spoken form --------------------------------------------------------
    (
        SPEECH,
        "a bare URL is read aloud",
        '    s = _BARE_URL.sub("a link", s)',
        '    pass',
        ("test_the_script_keeps_the_words_and_drops_the_markup",),
    ),
    (
        SPEECH,
        "a code block is read aloud",
        '    s = _FENCE.sub(" There is a block of code on the screen. ", s)',
        '    pass',
        ("test_a_code_block_is_replaced_by_a_sentence_saying_so",),
    ),
    (
        SPEECH,
        "heading marks are read aloud",
        '    s = _HEADING.sub("", s)',
        '    pass',
        ("test_the_script_keeps_the_words_and_drops_the_markup",),
    ),
    (
        SPEECH,
        "a bare line runs into the next with no pause",
        "            line += \".\"",
        "            pass",
        ("test_an_unpunctuated_line_gets_a_full_stop_so_the_voice_pauses",),
    ),
    (
        SPEECH,
        "a long reply is cut mid-word",
        "    if ends:\n        head = head[: ends[-1]]",
        "    if False:\n        head = head[: ends[-1]]",
        ("test_a_long_reply_is_cut_at_a_sentence_and_the_cut_is_declared",),
    ),
    (
        SPEECH,
        "a reply is never cut",
        "MAX_SPEECH_CHARS = 2_400",
        "MAX_SPEECH_CHARS = 2_400_000",
        ("test_the_speech_limit_is_what_it_is",),
    ),
    (
        SPEECH,
        "an empty script is still sent to the provider",
        "    if not spoken:\n        return None",
        "    if False:\n        return None",
        ("test_an_empty_or_markup_only_reply_is_not_sent_anywhere",),
    ),
    # --- the request and the adapter -------------------------------------------
    (
        SPEECH,
        "the key is not sent",
        '        "headers": {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},',
        '        "headers": {"Content-Type": "application/json"},',
        ("test_the_request_for_each_provider_carries_key_voice_model_and_text",),
    ),
    (
        SPEECH,
        "the adapter sends a request of its own rather than the one it was handed",
        '        response = requests.post(request["url"], headers=request["headers"],\n                                 json=request["json"], timeout=TIMEOUT_SECONDS)',
        '        response = requests.post(request["url"], headers=request["headers"],\n                                 json=dict(request["json"], speed=1.5), timeout=TIMEOUT_SECONDS)',
        ("test_the_adapter_posts_the_request_as_is_and_returns_the_bytes",),
    ),
    (
        SPEECH,
        "a refusal from the provider is returned as audio",
        '    if response.status_code != 200:\n        raise SpeechUnavailable',
        '    if False:\n        raise SpeechUnavailable',
        ("test_a_provider_that_fails_raises_rather_than_returning_an_error_page",),
    ),
    (
        SPEECH,
        "the adapter grows a decision",
        '    return response.content\n',
        '    if len(response.content) < 100:\n        return b""\n    return response.content\n',
        ("test_the_adapter_has_no_branches",),
    ),
    # --- the route --------------------------------------------------------------
    (
        MAIN,
        "a client hears Jarvis instead of their representative",
        '            agent_name = client_agent.ensure(conn, subject)["name"]',
        '            agent_name = None',
        ("test_a_client_hears_their_own_representative",),
    ),
    (
        MAIN,
        "a provider that is down is reported as 'no provider'",
        '        raise HTTPException(status_code=503, detail="The voice did not answer.")',
        '        return Response(status_code=204)',
        ("test_a_configured_provider_that_fails_is_a_503_not_a_silent_204",),
    ),
    (
        MAIN,
        "the ready frame drops the persona",
        '            "voice": {**agent["voice"], **speech.voice_for(agent["name"])},',
        '            "voice": agent["voice"],',
        ("test_the_ready_frame_carries_the_agents_persona",),
    ),
    (
        MAIN,
        "any truthy value on the frame counts as spoken",
        '        spoken_turn = message.get("spoken") is True',
        '        spoken_turn = bool(message.get("spoken"))',
        ("test_a_spoken_turn_is_answered_for_the_ear_and_a_typed_one_is_not",),
    ),
    (
        MAIN,
        "the flag is read and never passed on",
        '                                              spoken=spoken_turn)',
        '                                              spoken=False)',
        ("test_a_spoken_turn_is_answered_for_the_ear_and_a_typed_one_is_not",),
    ),
    # --- the turn ---------------------------------------------------------------
    (
        CONVERSATION,
        "every turn is answered for the ear",
        "    if spoken:\n        system += speech.DELIVERY_PARAGRAPH",
        "    if True:\n        system += speech.DELIVERY_PARAGRAPH",
        ("test_a_spoken_turn_is_answered_for_the_ear_and_a_typed_one_is_not",
         "test_run_turn_takes_the_flag_and_defaults_to_typed"),
    ),
    (
        CONVERSATION,
        "the spoken register defaults on",
        "    recorder=None, spoken: bool = False,",
        "    recorder=None, spoken: bool = True,",
        ("test_run_turn_takes_the_flag_and_defaults_to_typed",),
    ),
    # --- the page ---------------------------------------------------------------
    (
        PAGE,
        "the page sends every turn as typed",
        'socket.send(JSON.stringify({ type: "message", text, spoken: voice.enabled }));',
        'socket.send(JSON.stringify({ type: "message", text }));',
        ("test_the_page_sends_the_spoken_flag_from_the_microphone_state",),
    ),
    (
        PAGE,
        "a fetch that lands after an interruption plays anyway",
        "      if (generation !== voice.generation || !voice.speaking) {",
        "      if (false) {",
        ("test_an_interruption_also_stops_audio_still_being_fetched",),
    ),
    (
        PAGE,
        "the page plays whatever status it gets",
        "      if (response.status !== 200) return null;",
        "      if (!response.ok) return null;",
        ("test_the_page_asks_the_gateway_for_the_voice_before_the_browser",),
    ),
]


if __name__ == "__main__":
    raise SystemExit(harness.run_probes(PROBES, SUITES))
