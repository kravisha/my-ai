"""What the owner's page actually has on it, so the agent knows what he is looking at.

Krish, 2026-09-16 04:53, from abroad and by phone: *"make him self aware about
all the controls on his interface and he should be able to paste messages in the
box where I send messages to you - currently he is unaware of this."*

Both halves of that were true, and the second was a consequence of the first.
`gateway/static/voice.html` is a three-box page with seven buttons and five
phrases it acts on before the model is ever asked; the operator's prompt in
`gateway/conversation.py` mentioned none of it. Asked to put something in the box
he sends from, the agent reached for the nearest true sentence it had - *"I only
have read access to the running Jarvis system, and lifecycle actions like waking
or resuming an agent are the Controller's job alone"* - which is the correct
answer to a different question. It was not refusing. It had never been told the
box exists.

## Why a registry rather than a paragraph typed into the prompt

The same reason `gateway/skills.py` generates the capability paragraph instead of
stating it: a hand-written description of the page is a second source of truth
about the page, and it is wrong the first time somebody moves a button.

Here that drift is unusually cheap to cause and expensive to have. This page is
edited from a second machine, it is read from disk per request, so an edit is
live on his phone with no restart - and an agent describing the page from memory
would go on sounding right. So each control is declared once, next to the element
id it actually has, and `tests/test_gateway_interface.py` asserts every declared
id exists in the page. A renamed button fails the suite rather than turning the
agent into a confident guide to a page that has changed underneath it.

## Why this one does not raise at import

Every other registry in this Gateway validates at import and fails loudly;
`skills._validate` is the pattern and it is a good one. This module deliberately
does not, and the reason is what being wrong would cost. It is imported by the
conversation behind the page the owner is holding, and while he is abroad that
page is the only way he can be reached at all. A stale control description gives
him a worse answer; an ImportError gives him no answer, for a week. The check
belongs in the suite, which stops the mistake before it ships, not in the process
that would carry it.
"""

from __future__ import annotations

from dataclasses import dataclass

# The relay's own ceiling, enforced by `gateway/main.py`'s /voice/relay route.
# Declared here because the draft tool has to refuse what the route would refuse:
# an agent that cheerfully fills the box with 30,000 characters has produced a
# message that cannot be sent, and the owner finds that out by pressing send.
RELAY_MAX_CHARS = 20_000

# The one UI effect a tool may ask the page for, by name. `gateway/conversation`
# forwards nothing outside this set, so a tool cannot invent a frame: the page
# receives instructions from a list written here, not from a model's imagination.
ACTION_DRAFT_RELAY = "draft_relay"
UI_ACTIONS = frozenset({ACTION_DRAFT_RELAY})


@dataclass(frozen=True)
class Box:
    number: str
    title: str
    purpose: str


@dataclass(frozen=True)
class Control:
    # The element's real id in voice.html. Asserted by the suite, which is the
    # whole point of writing it down.
    element_id: str
    # What it says on the page, as he would read it out to you.
    label: str
    does: str
    box: str


@dataclass(frozen=True)
class SpokenCommand:
    say: str
    does: str
    # A literal fragment of voice.html that proves the page acts on this phrase.
    # The suite looks for it, so rewriting the trigger without rewriting this
    # fails rather than leaving the agent promising a phrase nothing matches.
    evidence: str


BOXES: tuple[Box, ...] = (
    Box(
        number="1",
        title="Talk to Jarvis",
        purpose=(
            "where this conversation comes from. What he speaks or types lands in it, "
            "editable, and is sent to you when he presses the send button - never "
            "automatically, so the microphone mishearing him is a typo rather than a "
            "message"
        ),
    ),
    Box(
        number="2",
        title="Message to Claude",
        purpose=(
            "the box he sends messages to Claude from - Claude being the engineer "
            "session working on this machine. You can type into this box; only he can "
            "send it. Sending appends the text to a file Claude reads on his next "
            "check, minutes later, and executes nothing"
        ),
    ),
    Box(
        number="3",
        title="From Claude",
        purpose=(
            "Claude's replies to him, polled every thirty seconds and read aloud when "
            "they arrive. You do not write here - it is the other direction"
        ),
    ),
)

CONTROLS: tuple[Control, ...] = (
    Control(
        element_id="text",
        label="the box 1 text area",
        does="holds what he said or typed, for him to correct before it reaches you",
        box="1",
    ),
    Control(
        element_id="mic",
        label="Tap to speak",
        does="starts and stops the microphone; what it hears goes into box 1, not to you",
        box="1",
    ),
    Control(
        element_id="send",
        label="Send to Jarvis",
        does="sends box 1 to you. This is how everything you hear from him arrives",
        box="1",
    ),
    Control(
        element_id="relay",
        label="the box 2 text area",
        does=(
            "holds the message bound for Claude. This is the box you can type into, "
            "with draft_message_to_claude"
        ),
        box="2",
    ),
    Control(
        element_id="draftRelay",
        label="Jarvis, draft it",
        does=(
            "asks you to turn whatever is in box 1 into a message for Claude and puts "
            "your answer in box 2. The same result you get by calling "
            "draft_message_to_claude yourself, which is the better route because it "
            "leaves the conversation in the log"
        ),
        box="2",
    ),
    Control(
        element_id="sendRelay",
        label="Send to Claude",
        does=(
            "sends box 2. His press, never yours - you have no way to press it and "
            "must not say you have sent anything"
        ),
        box="2",
    ),
    Control(
        element_id="checkInbox",
        label="Check now",
        does="asks for anything new from Claude immediately instead of waiting for the poll",
        box="3",
    ),
    Control(
        element_id="readInbox",
        label="Read aloud",
        does="re-reads the last three messages from Claude out loud",
        box="3",
    ),
    Control(
        element_id="stopSpeak",
        label="stop talking",
        does="stops the page speaking mid-sentence, at the top of the page",
        box="header",
    ),
    Control(
        element_id="enableAudio",
        label="tap to enable voice",
        does=(
            "the tap a phone browser requires before it will speak at all. If he says "
            "he cannot hear you, this is the first thing to ask about"
        ),
        box="header",
    ),
)

SPOKEN: tuple[SpokenCommand, ...] = (
    SpokenCommand(
        say='"tell Claude ..." (or ask, message, inform, let Claude know)',
        does=(
            "drafts box 1 into box 2 without him touching the screen. The page acts on "
            "this itself, so you will not see the turn"
        ),
        evidence="(tell|ask|message|inform)",
    ),
    SpokenCommand(
        say='"send it" (or send that, send to Claude, go ahead and send)',
        does=(
            "presses Send to Claude for him. Also handled by the page, so a message you "
            "drafted can be sent without the turn reaching you"
        ),
        evidence="send it jarvis",
    ),
    SpokenCommand(
        say='"just text" / "stop talking" / "be quiet"',
        does="stops the page reading replies aloud; the label at the top becomes voice: off",
        evidence="text mode",
    ),
    SpokenCommand(
        say='"voice mode" / "read it out"',
        does="reads every reply aloud, including ones that read better than they hear",
        evidence="voice mode",
    ),
    SpokenCommand(
        say='"auto mode" / "normal mode"',
        does="back to the default, where you speak unless the answer is better on screen",
        evidence="auto mode",
    ),
)


def controls_in(box: str) -> list[Control]:
    return [control for control in CONTROLS if control.box == box]


def draft_for_relay(text: str) -> dict:
    """Put a message in box 2. Nothing else, and deliberately nothing else.

    The refusals are returned as data, like every other tool failure, so the model
    corrects itself from the string instead of the turn collapsing.

    **This writes nothing and sends nothing.** It hands the page a string to type
    into a text area, and the owner presses the button. That is not timidity about
    a small feature: the file box 2 appends to is the file that *wakes the Claude
    session on this machine*, and every entry in it is attributed "relayed by
    Jarvis at Krish's direction". An agent that could send would be able to wake
    another agent unattended, under an attribution that had stopped being true.
    The owner's press is what makes that line honest, and it costs him one tap.
    """
    body = (text or "").strip()
    if not body:
        return {"error": (
            "Nothing to put in the box. Pass the message itself as `text` - the "
            "complete wording, as it should appear in box 2.")}
    if len(body) > RELAY_MAX_CHARS:
        return {"error": (
            f"That draft is {len(body)} characters and the relay accepts "
            f"{RELAY_MAX_CHARS}. Shorten it before putting it in the box, rather "
            "than leaving him something that cannot be sent.")}
    return {
        "drafted": True,
        "chars": len(body),
        "ui": {"action": ACTION_DRAFT_RELAY, "text": body},
        "note": (
            "It is in box 2 on his page, and it is not sent. Tell him it is waiting "
            "there and that he sends it with the Send to Claude button. Do not say it "
            "has been sent, and do not say Claude has it."
        ),
    }


def prompt_paragraph() -> str:
    """What the agent is told about the page, generated from the declarations above.

    Written for the operator's prompt only. A client meets a representative that
    has no relay box, no inbox and no business knowing the operator's page exists.
    """
    lines = [
        "",
        "## The page he is using, and what is on it",
        "",
        "He is on this Gateway's voice page, usually on his phone. Talk about it the "
        "way the page labels itself - three numbered boxes - because those are the "
        "words printed in front of him:",
        "",
    ]
    for box in BOXES:
        lines.append(f'- **Box {box.number}, "{box.title}"** - {box.purpose}.')
    lines.append("")
    lines.append("The controls, by where they sit:")
    for box in BOXES:
        for control in controls_in(box.number):
            lines.append(f'- Box {box.number}, "{control.label}" - {control.does}.')
    for control in controls_in("header"):
        lines.append(f'- Top of the page, "{control.label}" - {control.does}.')
    lines.append("")
    lines.append(
        "Phrases the page acts on by itself, before the turn reaches you. Know them, "
        "because a message can arrive in box 2, or be sent, without you seeing it "
        "happen:")
    for command in SPOKEN:
        lines.append(f"- {command.say} - {command.does}.")
    lines.append("")
    lines.append(
        "You can type into box 2 with `draft_message_to_claude`. Do it when he asks "
        "you to tell Claude something, or to put something in that box - in the same "
        "turn, rather than offering to. Then say it is in box 2 and unsent. You "
        "cannot press Send to Claude and you must never imply that you have: the "
        "press is his, and it is what makes the line Claude receives - \"relayed by "
        "Jarvis at Krish's direction\" - a true one.")
    lines.append(
        "If he says nothing appeared in box 2, do not assume it worked. Either he is "
        "on a cached copy of the page, and the version below is what he should be "
        "seeing, or he is on the main client page, which has no box 2 at all - that "
        "one is at / and the voice page is at /voice.")
    return "\n".join(lines)
