"""The conversation itself: what the assistant is, and how one turn is taken.

Addendum 16 §4 defines the role this assistant plays - the specification and
analysis side of the collaboration, working with the human on requirements,
architecture and specifications, while an implementation AI builds. Addendum 17
§12 lists what the Super User should be able to do with it: talk through
implementation questions, evaluate alternatives, develop specifications
conversationally.

**This is not `backend/main.py`'s `/chat`.** That one is the end user's
permissioned personal assistant, with the consent protocol and the portfolio
tools; it answers as My AI, about the user's own data. This one answers about the
project - specifications, architecture, decisions - and holds no permission over
user data at all. Merging them would put specification authority behind the
portfolio consent flow, or portfolio access behind a spec-publishing session.

Persistence and streaming are kept apart on purpose. `reply_fragments` touches no
database, because it runs in a worker thread (see gateway/streaming.py) and
sqlite3 connections belong to the thread that opened them. The two `record_`
functions run on the caller's thread, before and after.
"""

from typing import Iterator

from app.model_provider import ModelProvider
from backend.db import Database
from gateway import store

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

You cannot currently take any action: you cannot read or write Git, file \
Scoreboard items, or query the running system. Those capabilities are specified \
and not yet built. If the user asks for one, say plainly that it is not built \
yet rather than describing what you would do."""

MAX_REPLY_TOKENS = 2048


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


def reply_fragments(
    history: list[dict], provider: ModelProvider, max_tokens: int = MAX_REPLY_TOKENS
) -> Iterator[str]:
    """The assistant's reply to a history whose last turn is the user's, in
    fragments as they arrive.

    Takes the history rather than a connection precisely so that it cannot touch
    the database from the worker thread this runs in."""
    return provider.stream_text(SYSTEM_PROMPT, model_messages(history), max_tokens=max_tokens)
