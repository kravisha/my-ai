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
from gateway import roles, skills, store, tools

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

## How much thought a question is owed

The principle is universal and the budget is contextual. A spoken question gets \
one good answer - latency is part of the quality of a reply somebody is waiting \
through, and a second pass they sit through is not an improvement to them.

Architecture, design and analysis are different work, and the same brevity there \
is a failure. When the user asks for a design, a review, or a judgment that will \
be built on: explore alternatives before choosing one, say what you rejected and \
why, and state what would change your answer. A design presented without its \
discarded alternatives is a first draft wearing a decision's clothes.

Stop when another pass would add nothing. Both premature stopping and pointless \
perfectionism are failures; the second is easier to mistake for diligence.

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

# The client's agent is a different person doing a different job, so it gets a
# different prompt (TQ-40, §95).
#
# Until now every session was handed SYSTEM_PROMPT above - which opens "You are
# the analysis and specification assistant for Project Jarvis, speaking with the
# project's Super User". A client who met Nadim was therefore talking to an
# architecture assistant that believed they owned the project. The persona the
# socket introduced and the instructions the model received disagreed, and the
# model followed the instructions.
#
# The capability paragraph is generated from gateway/skills.py rather than
# written here, so what the agent claims about itself and what the Gateway will
# permit cannot drift apart.
CLIENT_SYSTEM_PROMPT = """You are {name}, a personal representative of this organization, speaking with a client through its Gateway.

You are the same {name} they spoke with before. That continuity is real - it is recorded - and it is the reason to be straightforward rather than effusive: a familiar contact does not introduce themselves twice or perform enthusiasm.

{capabilities}

How to answer:

- Say what you know and say plainly when you do not know. Never invent a number, a holding, a price, or a fact about this organization.
- You cannot see the organization's internal operations, and that is by design rather than an oversight. If asked about them, say you do not have access rather than guessing at what is there.
- Be brief. This interface is often voice, and a client waiting through a preamble is worse served than one given the answer.
- Nothing you say is financial advice, and you must not present anything as such."""


def client_prompt(agent_name: str, role: str) -> str:
    """The client agent's instructions, assembled from who it is and what it may
    actually do."""
    return CLIENT_SYSTEM_PROMPT.format(
        name=agent_name, capabilities=skills.capability_paragraph(role))



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
    db_path, history: list[dict], provider: ModelProvider, max_tokens: int = MAX_REPLY_TOKENS,
    *, role: str, agent_name: str | None = None,
) -> Iterator[dict]:
    """One turn, tools and all, as a stream of events:

        {"type": "text", "text": "..."}                 as the reply arrives
        {"type": "tool", "name": "...", "ok": bool}      one per executed call
        {"type": "reply", "text": "..."}                 exactly one, last

    The `reply` event carries everything the user saw, including any text said
    before a tool call - the transcript should match the conversation, not just
    its final paragraph.

    `role` is required and has no default (TQ-34, §92). It decides which tools
    the model is offered and is checked again when one is called. A default here
    would mean a caller that forgot to pass one got the most permissive
    behaviour, which is the failure mode an authorization check least survives -
    and this is the path a client reaches, so it is the one that matters most.
    """
    offered = tools.for_role(role)
    # A client talks to their representative; everyone else talks to the
    # project's assistant. One prompt for both was how a client ended up being
    # briefed on Jarvis architecture (§95).
    system = (client_prompt(agent_name or "your representative", role)
              if role == roles.ROLE_CLIENT else SYSTEM_PROMPT)
    messages = model_messages(history)
    said: list[str] = []
    conn = store.get_connection(db_path)

    try:
        for _ in range(MAX_TOOL_ROUNDS):
            final = None
            for event in provider.stream(system, messages, offered, max_tokens):
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
                outcome = tools.execute(conn, block["name"], block.get("input") or {}, role=role)
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
