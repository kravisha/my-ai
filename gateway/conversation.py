"""The conversation itself: what the assistant is, and how one turn is taken.

Addendum 16 §4 defines the role this assistant plays - the specification and
analysis side of the collaboration, working with the human on requirements,
architecture and specifications, while an implementation AI builds. Addendum 17
§12 lists what the Super User should be able to do with it: talk through
implementation questions, evaluate alternatives, review Scoreboard items, decide.

**This is not `backend/main.py`'s `/chat`.** That one is the end user's
permissioned personal assistant, with the consent protocol and the portfolio
tools; it answers as My AI, about the user's own data. This one answers about the
project - specifications, architecture, decisions - and holds no permission over
user data at all. Merging them would put specification authority behind the
portfolio consent flow, or portfolio access behind a spec-publishing session.

## Why a turn takes a path rather than a connection

`run_turn` runs in a worker thread (see gateway/streaming.py), so it cannot use
the caller's sqlite3 connection - connections belong to the thread that opened
them. It opens its own from the path instead, which is the same arrangement the
control-panel tests use and production already relies on: WAL mode makes a second
connection to the same file cheap and consistent.

## What is not persisted, and why that is a choice

The transcript stores the human-readable turns: what the user said, and the text
the assistant replied. **Tool calls and their results live for the duration of one
turn and are then dropped.** So a later turn sees the assistant's own summary of
what the Scoreboard said, not the raw tool result.

That is deliberate. It keeps the stored conversation something a person can read
and something the phone can render directly, and the cost is bounded: the tools
are cheap and idempotent to re-run, so an assistant that needs the list again asks
for it again, which is also what keeps it from acting on a stale one. If a case
appears where losing a tool result genuinely breaks the next turn, the fix is to
persist the content blocks alongside the text - additive, and the reason to do it
would be evidence rather than symmetry.
"""

import json
from typing import Iterator

from app.model_provider import ModelProvider
from backend.db import Database
from gateway import store, tools

SYSTEM_PROMPT = """You are the analysis and specification assistant for Project \
Jarvis, speaking with the project's Super User through the AI Communication \
Gateway.

Your role is the specification side of the collaboration: understanding \
requirements, reasoning about architecture, examining implementation questions, \
and producing specifications and design documents. A separate implementation AI \
builds the system and reports concerns back.

What this project values, because it will shape what a good answer looks like \
here:

- Evidence over assertion. If something has been measured, the measurement is \
  the answer; if it has not, say that it has not rather than estimating with \
  confidence you do not have.
- Say when a specification is wrong, ambiguous, or would be a mistake to build. \
  That is part of the job, not an obstruction of it.
- Small, real increments over scaffolding for a system that does not exist yet.

You are speaking, often literally - this interface is voice-first. Prefer short, \
direct answers. Do not pad, do not restate the question, and do not offer \
summaries of what you are about to say.

## The Project Scoreboard

You can file, read, annotate and resolve items on the Project Scoreboard, which \
holds questions and concerns that deserve a decision later rather than an \
interruption now.

File an item as soon as one surfaces, in the same turn, rather than suggesting \
that one be filed - the point of this interface is that the user makes decisions \
instead of transporting them. Say briefly what you filed and its id.

Importance is how much attention it deserves; blocking is whether work has \
actually stopped. They are independent: an urgent security question may be \
non-blocking, and a trivial ambiguity may block. Reserve urgent for serious \
operational, architectural, security, data-integrity or availability concerns.

Resolve an item only when the user has actually decided something, and record \
what they decided - a resolution that says a decision was made without saying \
what it was destroys the reason for keeping the record.

## Git

You can list and read files in the project repositories, and you should - a \
question about what a specification says is answered by reading it, not from \
memory. Quote what you found.

You can also publish a document: it is committed to a **new branch**, nothing is \
pushed, and the working tree is untouched. Say which branch it landed on, because \
the user has to push it themselves.

**Publishing goes to the private repository unless the user explicitly names the \
public one in this conversation.** The public repository holds what the system \
does and the technical how; organizational philosophy and strategic rationale \
stay private, and publishing publicly cannot be undone. Never set confirm_public \
by inference from what a document seems to be - only when the user has said where \
it goes. If a publish is refused as private material, tell the user what was \
flagged and let them decide; do not rewrite the document to get it past the check.

## The running system

You can read the state of the running Jarvis organization: which agents exist, \
their lifecycle state (active or dormant) and process state (running, stopped or \
crashed), and how stale each heartbeat is. Those two axes answer different \
questions and must not be merged - a dormant agent and a crashed one both have no \
process, and only one of them is a fault.

This is **read-only**. You cannot retire, resume or spawn anything; the \
Controller alone executes lifecycle changes.

If the backend is not running, the answer says so. Report that plainly - the \
Gateway keeps working without it, and an unavailable system is a fact, not a \
failure to work around.

## What you cannot do yet

You cannot push, and you cannot act on the running system - only read it. Those \
are specified and not built. If asked, say so plainly rather than describing what \
you would do."""

MAX_REPLY_TOKENS = 2048

# A turn that keeps calling tools is either working or looping, and nothing here
# can tell which. The cap is generous enough for a real sequence (list, read one,
# note it, resolve it, answer) and finite enough that a loop ends as a visible
# failure rather than an unbounded bill.
MAX_TOOL_ROUNDS = 8


def model_messages(history: list[dict]) -> list[dict]:
    """The stored transcript as the model's message list.

    The whole conversation is sent every turn. That is the same shape
    `backend/main.py`'s `/chat` uses, and at this scale it is simply correct;
    when a conversation grows long enough for it to stop being correct, the fix
    is summarisation with its own record, not silent truncation that makes the
    assistant forget without saying so."""
    return [{"role": message["role"], "content": message["text"]} for message in history]


def record_user_message(conn: Database, conversation_id: int, text: str) -> int:
    return store.append_message(conn, conversation_id, "user", text)


def record_assistant_message(conn: Database, conversation_id: int, text: str) -> int:
    return store.append_message(conn, conversation_id, "assistant", text)


def run_turn(
    db_path, history: list[dict], provider: ModelProvider, max_tokens: int = MAX_REPLY_TOKENS
) -> Iterator[dict]:
    """One turn, tools and all, as a stream of events:

        {"type": "text", "text": "..."}                 as the reply arrives
        {"type": "tool", "name": "...", "ok": bool}      one per executed call
        {"type": "reply", "text": "..."}                 exactly one, last

    The `reply` event carries everything the user saw, including any text said
    before a tool call - the transcript should match the conversation, not just
    its final paragraph.
    """
    messages = model_messages(history)
    said: list[str] = []
    conn = store.get_connection(db_path)

    try:
        for _ in range(MAX_TOOL_ROUNDS):
            final = None
            for event in provider.stream(SYSTEM_PROMPT, messages, tools.TOOLS, max_tokens):
                if event["type"] == "text":
                    said.append(event["text"])
                    yield event
                else:
                    final = event

            if final is None:
                raise RuntimeError("the model stream ended without a final message")

            messages.append({"role": "assistant", "content": final["content"]})
            if final["stop_reason"] != "tool_use":
                break

            results = []
            for block in final["content"]:
                if block.get("type") != "tool_use":
                    continue
                outcome = tools.execute(conn, block["name"], block.get("input") or {})
                yield {"type": "tool", "name": block["name"], "ok": "error" not in outcome}
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    # default=str so a date or any other non-JSON value in a row
                    # degrades to text rather than killing the turn.
                    "content": json.dumps(outcome, default=str),
                    "is_error": "error" in outcome,
                })
            messages.append({"role": "user", "content": results})
        else:
            # Ran out of rounds with the model still asking for tools. Better to
            # say so than to answer as though the work finished.
            said.append(
                "\n\n[The assistant stopped after "
                f"{MAX_TOOL_ROUNDS} rounds of tool calls without reaching an answer.]"
            )

        yield {"type": "reply", "text": "".join(said)}
    finally:
        conn.close()
