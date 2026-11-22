# Voice and presence: how an agent should talk, and the order of work to get there

A maintained document (see `README.md` for the verbatim/maintained distinction).

Owner instruction, 2026-11-21, with a three-and-a-half-minute phone recording
of an AI host on a TikTok LIVE: *"This is the kind of FX I am looking for...
This is the kind of interaction I'm looking for our AI agents to have. This is
what our final goal has to be. I want you to get me here. This is how any of
our agents should talk. Either it is Kali or Tara. This is how realistically
they should talk. Please make this happen."*

This document is the study of that recording, the gap between it and the
Gateway, and the milestones that close the gap. Each milestone is one PR and
is listed here before it is built, so the order can be argued with.

---

## 1. What the recording shows

Studied on 2026-11-21 from a contact sheet (one frame every six seconds), a
two-second burst at four frames a second, a silence map of the audio, and a
rough transcript. The transcript is rough because the container the study ran
in could not reach any speech model; the pacing numbers come from the silence
map and are solid.

**The host.** A photoreal talking head, framed from the shoulders up against a
plain grey wall, in a black top. She is on screen the whole time. Nothing
else is: no captions, no graphics, no scene changes. The only "FX" in the
frame are TikTok's own live-chat overlay and gift banners. The effect the
owner is pointing at is not an overlay. It is that she looks and sounds like
a person.

**The face.** Mouth shapes track the speech closely enough that the burst
frames read as speech. The head moves a little while she talks and keeps
moving a little while she listens; she blinks; her eyebrows and eyes move
with emphasis. When a comment arrives she looks as if she is reading it. The
quality is "video call", not "game character". The window shows the TikTok
LIVE player on a laptop, with a camera-style preview panel in the corner.

**The voice.** A natural neural voice with breath, pitch movement and
emphasis. Nothing about it says synthesiser. It has a consistent character for
the whole stream: warm, unhurried, slightly amused.

**The interaction.** Viewers type; she reads and answers. The owner typed, in
order: "Hello", "I guess you are talking to AI", "She is smooth", "I am trying
to create an Emma myself", "I love AI", "We are also AI only", "We just don't
know that yet", "Humans think they are not AI because of the human quality
called Ego". She answers each within a second or two, addresses the viewer
by name, and builds on what was said rather than restarting. The transcript
has her talking about a companion AI called Emma, a Discord server, a
TikTok community around AI companions, and what she is "currently working on
right now"; she talks about herself as a person with a life and projects, and
treats the viewer as someone she already knows.

**The pacing**, from the silence map (threshold −30 dB, gaps of 0.6 s or
more):

| Measure | Value |
|---|---|
| Length | 3 min 34 s |
| Gaps of 0.6 s or longer | 33 |
| Typical gap | 1.0 to 1.5 s |
| Longest gap | 2.3 s |
| Typical stretch of continuous speech | 4 to 10 s |
| Longest stretch | about 29 s |

So: short thoughts, a real pause between them, and never more than a few
seconds of silence. She speaks in sentences of ten to twenty words, with
fillers ("honestly", "yeah", "like"), occasional laughs, and a question back
to the viewer every so often. She does not list, does not preface, and does
not sign off.

**What "realistic" means, written down, so it can be tested against:**

1. A human-sounding voice with one stable character per agent.
2. Short spoken sentences, answer first, one thought at a time, no screen
   markup read aloud.
3. A pause of about a second between thoughts, and a reply that starts within
   a second or two of the question.
4. The viewer addressed by name and the thread of the conversation kept.
5. A face that speaks the words, keeps moving while listening, and looks
   like a person on a video call.
6. Interruptible: the viewer can talk over her and she stops.

---

## 2. Where the Gateway was on 2026-11-21

| Requirement | State before this document |
|---|---|
| 1. Human voice | The page handed each reply to the browser's `speechSynthesis`. The voice of a satnav. |
| 2. Spoken sentences | The model was told "be brief" and nothing else. Replies carried headings, bullets and paths, which the browser read aloud as written. |
| 3. Pacing | None. The reply was spoken when the turn finished, as one utterance. |
| 4. Name and thread | Done: `gateway/client_agent.py` gives a client a stable representative, and the conversation is kept per subject. |
| 5. Face | None. The agent record carries a `visual` slot that says so (`DEFAULT_VISUAL`). Addendum 41 §3 rules out a still portrait standing in for a presenter. |
| 6. Interruptible | Done: barge-in on an echo-cancelled stream, `gateway/static/index.html`. |

Kali and Tara are not names in this repository. The Gateway's client agents
are drawn from `client_agent.NAME_POOL`, and the operator's assistant is
Jarvis. Where Kali and Tara live, and whether the voice work lands here or
beside them, is an open question put to the owner on 2026-11-21.

---

## 3. Milestones

### M1 — A real voice (`gateway/speech.py`) — built 2026-11-21

Requirements 1 and 2, and the groundwork for 3.

- `POST /speech` returns a reply as audio from a configured provider.
  `gateway/speech.py` holds a provider table (ElevenLabs, OpenAI) keyed by
  which API key is present, or `JARVIS_VOICE_PROVIDER` to choose. No key means
  204 and the browser voice, which is what every Gateway had before and is
  not a fault.
- One stable voice per agent: `voice_for(name)` derives a persona from the
  name, and each provider row maps the persona to one of its voices. Jarvis
  has one fixed voice.
- `script()` turns the screen form of a reply into the spoken form: fenced
  code becomes a sentence saying code is on the screen, links keep their
  words and lose their address, headings and bullets lose their marks, table
  rows become sentences. A reply over 2,400 characters is cut at a sentence
  and says the rest is on the screen.
- A turn that arrived by voice carries `spoken: true` on the socket frame,
  and the model is told to write for the ear: short sentences, answer first,
  no markdown, under about eighty words, no sign-off
  (`speech.DELIVERY_PARAGRAPH`). A typed turn is answered as before.
- The page asks `/speech` first and plays what comes back; barge-in still
  wins, including against audio still being fetched.
- Decisions are pure and tested; the one network call, `synthesize`, has no
  branches and the suite asserts that over its AST. `tests/test_speech.py`,
  mutated by `tests/probes/speech_probes.py`.

Not in M1: streaming audio (the reply is synthesised whole, so a long answer
starts late), a local model on the PC, and the relay page `voice.html`,
which still uses the browser voice.

### M2 — Pacing and first-word latency

Requirement 3. Synthesise sentence by sentence as the deltas arrive, play
the first sentence while the second is being made, and insert the recording's
one-second pause between thoughts rather than between sentences. Measure
time-to-first-audio and keep it under two seconds. This changes
`gateway/speech.py` (a `segments()` splitter), the route (a streaming
response or a sequence of requests), and the page's player (a queue).

### M3 — The host's register

Requirement 4, beyond the name. The recording's host has a life: projects she
is working on, a community, opinions. The Gateway's agents have a record and
a role. The next step is what an agent is *allowed* to say about itself and
its day, grounded in the record rather than invented, which is a
Constitution question (addendum 43 §16, addendum 53 §7.9's freeze on
personas) before it is a prompt. Not started; needs the owner.

### M4 — A face

Requirement 5.

**A second sample, 2026-11-21 23:59.** Krish sent a 24-second clip: a
stylised 3D character (big eyes, doll proportions, a saree, a living-room
background), labelled AI-generated, animated from what is plainly one still
image. What it does: lip shapes track the speech; eyebrows frown, lift and
soften with the sense of the words; the eyes dart and settle; the head tilts
and nods; one hand gestures briefly. Framing is fixed, the background is
still, and the clip is a single take with no cuts. The audio is a casual
spoken voice; the silence map has two pauses of about half a second in 20
seconds of speech, so the pacing lesson from the first recording holds.
*"If this can be done on a phone, I'm sure it can be done on this computer...
Please give something like this at least."*

So the target for M4's first delivery is narrower than the first recording and
reachable: **one still image plus one reply's audio, rendered into a short
talking clip with blinks, eyebrows and head motion, on the PC.** Not photoreal,
not yet real time. The still image is the agent's stable face (addendum 43
§16), and it answers the "static portrait" objection in `DEFAULT_VISUAL`
because the portrait is the input, not the output.

Three routes, in rising order of cost and fidelity:

1. **A rendered avatar driven by the audio** on the page: a 2D or 3D head
   with visemes from the audio stream, moving while idle. Works today in a
   browser with no GPU and no vendor; looks like a character, not a person.
2. **A hosted talking-head service** (HeyGen, D-ID, Tavus and the like)
   streamed into the page: photoreal, lip-synced, low effort, and every
   word leaves the machine - the same disclosure the README makes about
   speech recognition, made larger.
3. **A local talking-head model** on the PC (MuseTalk, SadTalker, LivePortrait
   or a successor) driven by M1's audio: photoreal, nothing leaves, needs a
   GPU and a real-time pipeline. The only one that honours "what runs on the
   PC must stay local" (CLAUDE.md, 2026-10-19) without a disclosure.

The first recording is route 2 or 3; the second sample is what route 3
produces from a still image. **M4a, started 2026-11-22:** route 3 on the PC,
offline first - an audio-driven talking-portrait model (SadTalker, then
EchoMimic or Hallo if the GPU allows) rendering one reply at a time to a clip
the page plays. M4b is the same thing fast enough to feel live, which is a
different model class (MuseTalk, LivePortrait with an audio driver) and is
not promised until M4a has a render time to reason from. The `visual` slot on
the agent record is where the chosen portrait is written.

---

## 4. Open questions, 2026-11-21

1. Which voice provider is in force: ElevenLabs, OpenAI, or a local model on
   the PC so that nothing leaves? M1 takes either cloud key; local is a third
   row in the table and an adapter.
2. Where do Kali and Tara live? They are not in this repository.
3. ~~Face: route 2 (hosted, words leave) or route 3 (local, needs a GPU)?~~ Answered by the second sample and "on this computer": route 3, local.
