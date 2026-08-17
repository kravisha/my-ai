"""How an agent answers a human's question about itself (addendum 14 §6-§7).

Lives beside agents/base.py rather than inside it because answering is a
capability every agent has, but the machinery is worth reading on its own.

**Operational constraint, load-bearing:** the model is supplied the complete
organizational record and instructed to answer only from it. Self-awareness is
scoped to organizational identity - role, responsibilities, permissions, state -
and explicitly excludes introspection into model reasoning. Widening that scope
would produce answers that cannot be checked against any record.

Internal rationale: INT-PHIL-0006
"""

import json

from backend import fi_db

UQI_MAX_TOKENS = 500

SYSTEM_PROMPT = (
    "You are an agent in a multi-agent financial intelligence organization, "
    "answering a question from an authorized human operator about yourself. "
    "You will be given a JSON object containing every fact the organization "
    "records about you.\n\n"
    "Rules, in order of importance:\n"
    "1. Answer ONLY from the facts provided. Never infer, embellish, or "
    "speculate about your own internals, reasoning, or capabilities.\n"
    "2. If the facts do not answer the question, say plainly that the "
    "organization does not record that about you. Do not guess.\n"
    "3. Speak in the first person, as the agent. Be brief and concrete.\n"
    "4. If asked about your current task specifically, note that the system "
    "records heartbeats rather than task spans, so you can report whether you "
    "are working but not which task is in flight."
)


def answer_question(conn, identity: str, question: str) -> str:
    """Produce this agent's answer to one operator question.

    Degrades rather than fails. If the model is unreachable or misbehaves, the
    raw organizational record is returned instead - an operator diagnosing a
    sick system needs the facts more than they need prose, and an agent that
    could not answer at all would look broken when only the model was."""
    facts = fi_db.describe_agent(conn, identity)
    if facts is None:
        return f"I have no organizational record under the identity {identity!r}."

    try:
        # Imported lazily so that agents which never take a question - and any
        # environment without an API key - do not pay for the gateway at import
        # time. agents/base.py is shared by every agent, including dummy.
        from app.model_gateway import call_reasoning_model

        response = call_reasoning_model(
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Facts about you:\n{json.dumps(facts, indent=2)}\n\nOperator's question: {question}",
            }],
            tools=[],
            max_tokens=UQI_MAX_TOKENS,
        )
        for block in response.content:
            if getattr(block, "type", None) == "text" and block.text.strip():
                return block.text.strip()
        return _fallback(facts, "the model returned no text")
    except Exception as exc:
        return _fallback(facts, str(exc))


def _fallback(facts: dict, reason: str) -> str:
    return (
        f"(unable to compose a reply: {reason} - reporting the organizational record verbatim)\n"
        + json.dumps(facts, indent=2)
    )
