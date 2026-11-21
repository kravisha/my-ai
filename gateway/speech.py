"""A real voice for the agents (Krish, 2026-11-21; docs/VOICE_AND_PRESENCE.md).

Krish, 2026-11-21, with a recording of an AI host on a TikTok LIVE: *"This is
the kind of effects I'm looking for. This is the kind of interaction I'm looking
for our AI agents to have... This is how any of our agents should talk. Either
it is Kali or Tara. This is how realistically they should talk."*

What the recording has and this Gateway did not, in the order they are heard:

1. **A human voice.** Until now every reply was read by the browser's own
   `speechSynthesis`, which is the voice of a satnav. The host in the recording
   is a neural voice with breath and intonation. That is this module's first job.
2. **Spoken sentences.** A reply written for a screen - headings, bullets, a
   code block, a URL - is a different thing from one written to be heard. The
   host speaks in short sentences, one thought each, and pauses between them.
   `script()` turns the screen form into the spoken form, and
   `DELIVERY_PARAGRAPH` tells the model to write the spoken form in the first
   place when the turn arrived by voice.
3. **The same voice every time.** The record a client meets (`gateway/
   client_agent.py`) already promises a stable voice and carries a slot for one;
   nothing filled it. `voice_for()` fills it: the same name always gets the same
   voice, with no row to write.

The face - lip-sync, the head that moves while she listens - is the next
milestone and is deliberately not here. docs/VOICE_AND_PRESENCE.md has the order.

## The split, because the adapter cannot be tested here (CLAUDE.md, JARVIS_SHELL §0)

Everything that can be decided is decided in pure functions: which provider is
in force (`provider_in_force`), which voice an agent has (`voice_for`), what the
request looks like (`request_for`), what text is sent (`script`). The one
function that touches the network, `synthesize`, is a single HTTP call with no
branching - it is handed a finished request and returns bytes or raises. A
judgement inside it would be a judgement nothing in the suite can see.

## Why two cloud providers and a table, rather than one and a class

The owner has not yet said which key he holds, and the honest answer to "which
provider" is *whichever one is configured*. A table keyed by name, with one row
per provider, lets that be a deployment fact rather than a code change - and
lets a local model on the PC be added as a third row without touching a caller.
`JARVIS_VOICE_PROVIDER` picks explicitly; absent that, the first row whose key
is present wins, in table order; absent any key, there is no provider and the
page keeps using the browser's voice, which is the behaviour this release
replaces and not a failure.
"""

from __future__ import annotations

import hashlib
import os
import re

import requests

# The spoken form is sent in one request. A reply longer than this is cut at a
# sentence boundary and the page says so - a provider bill for a ten-page answer
# read aloud is not what anyone meant by "say that".
MAX_SPEECH_CHARS = 2_400

# Seconds. A synthesis that has not answered by then is treated as absent and
# the browser voice takes over; the reply is already on the screen either way.
TIMEOUT_SECONDS = 20

# The register the owner pointed at: short, warm, one thought per sentence,
# nothing that only makes sense on a screen. Appended to the system prompt for
# a turn that arrived by voice (gateway/conversation.run_turn, `spoken=True`)
# and only then - a typed question still deserves a list when a list is the
# answer.
DELIVERY_PARAGRAPH = """

This turn arrived by voice and your reply will be read aloud by a synthesised voice, so write for the ear:

- Short sentences, one thought each. Pause between thoughts with a full stop, not a comma.
- Answer first, in the first sentence. Then the reason, if one is wanted.
- Talk like a person in the room: contractions, plain words, the occasional "right" or "okay". Never read out a heading, a bullet, a URL, a file path or code.
- No markdown of any kind. No lists. If three things must be named, name them in a sentence.
- Keep it under about eighty words unless asked for more. A listener cannot skim.
- Do not announce what you are about to say, and do not sign off."""


class SpeechUnavailable(Exception):
    """No provider answered. The page falls back to the browser's voice."""


# --------------------------------------------------------------- the providers
#
# One row per provider. `key_env` is the environment variable holding its key,
# `voices` the ids a persona maps to, in persona order (see PERSONAS). The ids
# are the providers' own published premade voices.

PERSONAS = ("warm", "bright", "steady", "low")

PROVIDERS = {
    "elevenlabs": {
        "key_env": "ELEVENLABS_API_KEY",
        "url": "https://api.elevenlabs.io/v1/text-to-speech/{voice}",
        "model": "eleven_turbo_v2_5",
        "content_type": "audio/mpeg",
        # Rachel, Domi, Antoni, Adam - ElevenLabs' premade set.
        "voices": {"warm": "21m00Tcm4TlvDq8ikWAM", "bright": "AZnzlk1XvdvUeBnXmlld",
                   "steady": "ErXwobaYiN019PkySvjV", "low": "pNInz6obpgDQGcFmaJgB"},
    },
    "openai": {
        "key_env": "OPENAI_API_KEY",
        "url": "https://api.openai.com/v1/audio/speech",
        "model": "gpt-4o-mini-tts",
        "content_type": "audio/mpeg",
        "voices": {"warm": "nova", "bright": "shimmer", "steady": "alloy", "low": "onyx"},
    },
}

# The operator's assistant has one voice, not one per name: Jarvis is the same
# Jarvis on both Gateways.
OPERATOR_PERSONA = "steady"


def provider_in_force(env: dict | None = None) -> str | None:
    """Which provider row applies, or None when the browser voice stays.

    `JARVIS_VOICE_PROVIDER` names one explicitly and is honoured only if its key
    is actually present - naming a provider whose key is missing is a
    configuration error, and the honest outcome is "no provider", not a 401 on
    every reply. Without it, the first row in table order with a key wins.
    """
    env = os.environ if env is None else env
    explicit = (env.get("JARVIS_VOICE_PROVIDER") or "").strip().lower()
    if explicit:
        row = PROVIDERS.get(explicit)
        return explicit if row and env.get(row["key_env"]) else None
    for name, row in PROVIDERS.items():
        if env.get(row["key_env"]):
            return name
    return None


def voice_for(agent_name: str | None) -> dict:
    """The stable voice record for an agent: a persona, derived from the name.

    Deterministic for the same reason client_agent draws the name from the id:
    a representative with a different voice each morning is not the one the
    client met. No provider id is stored here - the persona is the stable fact,
    and each provider's id for it lives in the table, so switching provider
    changes the timbre but keeps every agent's relative register.
    """
    if not agent_name:
        return {"persona": OPERATOR_PERSONA, "source": "operator assistant"}
    digest = hashlib.sha256(agent_name.encode("utf-8")).hexdigest()
    persona = PERSONAS[int(digest, 16) % len(PERSONAS)]
    return {"persona": persona, "source": "derived from the agent's name"}


# ------------------------------------------------------------ the spoken form

_FENCE = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_BARE_URL = re.compile(r"https?://\S+")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", re.M)
_EMPHASIS = re.compile(r"(\*\*|__|\*|_)(?=\S)(.+?)(?<=\S)\1")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$", re.M)
_PIPE = re.compile(r"\s*\|\s*")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def script(text: str) -> str:
    """The screen form of a reply as the thing a voice should say.

    What goes: fenced code (replaced by a sentence saying it was left out, so
    the listener knows there is something on the screen), inline backticks,
    link syntax (keeps the words, drops the address), bare URLs, heading marks,
    bullet marks, emphasis marks and table rules. Table cells become a
    sentence per row. Everything else is the author's own words, untouched.

    Deliberately not a summary and not a rewrite: the words the listener hears
    are the words on the screen, minus what cannot be spoken.
    """
    s = text or ""
    s = _FENCE.sub(" There is a block of code on the screen. ", s)
    s = _INLINE_CODE.sub(r"\1", s)
    s = _LINK.sub(r"\1", s)
    s = _BARE_URL.sub("a link", s)
    s = _TABLE_RULE.sub("", s)
    s = _HEADING.sub("", s)
    s = _BULLET.sub("", s)
    s = _EMPHASIS.sub(r"\2", s)
    lines = []
    for line in s.splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            cells = [c.strip() for c in _PIPE.split(line.strip("|")) if c.strip()]
            line = ", ".join(cells) + "."
        elif line[-1] not in ".!?:;,":
            # A heading or a bullet that was never punctuated is one thought;
            # ending it stops the voice running it into the next.
            line += "."
        lines.append(line)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def cut(spoken: str, limit: int = MAX_SPEECH_CHARS) -> tuple[str, bool]:
    """`spoken` within `limit`, cut at the last sentence end before it, and
    whether anything was cut. A cut mid-word is worse than a shorter answer."""
    if len(spoken) <= limit:
        return spoken, False
    head = spoken[:limit]
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s)", head)]
    if ends:
        head = head[: ends[-1]]
    return head.rstrip() + " The rest is on the screen.", True


# -------------------------------------------------------------- the request

def request_for(provider: str, text: str, persona: str, env: dict | None = None) -> dict:
    """The complete HTTP request for one synthesis, as data.

    Everything the adapter will send, decided here where a test can read it:
    the url with the voice in it, the key in the header, the model and the
    text in the body. `synthesize` adds nothing.
    """
    env = os.environ if env is None else env
    row = PROVIDERS[provider]
    voice = row["voices"].get(persona) or row["voices"][OPERATOR_PERSONA]
    key = env.get(row["key_env"]) or ""
    if provider == "elevenlabs":
        return {
            "url": row["url"].format(voice=voice),
            "headers": {"xi-api-key": key, "Accept": row["content_type"],
                        "Content-Type": "application/json"},
            "json": {"text": text, "model_id": row["model"],
                     "voice_settings": {"stability": 0.45, "similarity_boost": 0.8,
                                        "style": 0.35, "use_speaker_boost": True}},
            "content_type": row["content_type"],
        }
    return {
        "url": row["url"],
        "headers": {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        "json": {"model": row["model"], "voice": voice, "input": text,
                 "response_format": "mp3", "speed": 1.0},
        "content_type": row["content_type"],
    }


def synthesize(request: dict) -> bytes:
    """THE ADAPTER. One call, no decisions. Raises SpeechUnavailable on any
    failure so the route can let the browser voice take over."""
    try:
        response = requests.post(request["url"], headers=request["headers"],
                                 json=request["json"], timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise SpeechUnavailable(f"voice provider unreachable: {exc.__class__.__name__}") from exc
    if response.status_code != 200:
        raise SpeechUnavailable(f"voice provider answered {response.status_code}")
    return response.content


def speak(text: str, agent_name: str | None = None, env: dict | None = None,
          adapter=None) -> dict | None:
    """The whole path for one reply: provider, voice, script, request, bytes.

    Returns None when no provider is configured - the page keeps the browser
    voice - and raises SpeechUnavailable when one is configured and failed.
    `adapter` is a parameter so the suite can watch the request that would
    have been sent without sending it.
    """
    provider = provider_in_force(env)
    if provider is None:
        return None
    spoken, truncated = cut(script(text))
    if not spoken:
        return None
    request = request_for(provider, spoken, voice_for(agent_name)["persona"], env)
    # Resolved at call time, not bound as a default, so a test that replaces
    # `synthesize` on the module replaces it here too.
    audio = (adapter or synthesize)(request)
    return {"audio": audio, "content_type": request["content_type"],
            "provider": provider, "spoken": spoken, "truncated": truncated}
