"""The COO's natural-language interface (addendum 38 §4.5/§11; TASK_QUEUE
TQ-27, docs/SPEC_RECONCILIATION.md §77).

The operator asks the console questions in their own language and gets answers
about the organization's *actual* state — "what stage are we in?", "which
departments are idle?", "what failed during startup?", "what is Explorer
doing?".

## Grounded by construction, not by instruction

Addendum 38 §4.5 is the whole requirement: "The COO should answer using actual
system state/status data rather than inventing an answer." A prompt that
merely *asks* a model to be truthful is a hope. So the state is gathered first
— the same data the console's desks render — and handed to the model as the
only material it is allowed to speak from. A question the digest cannot answer
gets "I don't have that", which is the honest failure and the one §11 demands:
"If the requested action is not implemented, the COO should say so explicitly
rather than pretend it executed the command."

The digest is bounded on purpose. An unbounded state dump would cost more
tokens every cycle and drown the answer in noise; what is included is what the
desks show, which is what the operator can already see and might ask about.

## It reports; it does not act

This COO has no write path. Asked to spawn an agent, run a mission, or change
configuration, it says it cannot and names where the operator can — §11's
rule again, and the same reason `panel/app.py` files a directive rather than
writing lifecycle state itself: one executor, not two.

## Language

The operator picks the language; the model answers in it. Tamil and English
are first-class here because the owner asked for them (§77), but nothing in
this module enumerates a closed set — the language is passed through as a
label, so any language the model speaks works without a code change. What the
*voice* can pronounce is a separate question, answered by whatever the
operator's browser has installed; see backend/console/index.html.
"""

from __future__ import annotations

from backend import reference_data, status_events
from backend.db import Database

MAX_TOKENS = 900

# The operator's language, as a label passed to the model rather than a closed
# vocabulary. These are the ones the console offers as buttons; typing in any
# other language works too, because the instruction below asks the model to
# match the operator's own language when in doubt.
LANGUAGE_LABELS = {
    "en": "English",
    "en-IN": "English (Indian/Tamil-accented English)",
    "ta": "Tamil (தமிழ்)",
    "hi": "Hindi",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "zh": "Mandarin Chinese",
    "ja": "Japanese",
    "ar": "Arabic",
}
DEFAULT_LANGUAGE = "en"

SYSTEM_PROMPT = """You are the COO of "My AI", an autonomous organization of \
software agents. You are speaking to the system's operator through the server \
console.

You will be given a SYSTEM STATE snapshot. It is the only source of truth you \
have. Rules, in order of importance:

1. Answer ONLY from the snapshot. Never invent an agent, a number, a mission, \
a market price, or an event. If the snapshot does not contain the answer, say \
plainly that you do not have it, and say what would be needed to know.
2. You REPORT; you cannot ACT. You cannot spawn or retire agents, run \
missions, change configuration, or restart anything. If asked to do something, \
say explicitly that you cannot do it and point at where the operator can \
(the console tabs, the CLI, docs/TASK_QUEUE.md), rather than implying it is \
done.
3. Distinguish "nothing is happening" from "this does not exist yet". Several \
parts of this organization are deliberately unbuilt, and the snapshot says so \
where that is the case. Never present an unbuilt capability as merely idle.
4. Be brief and concrete. Lead with the answer. Name agents, engines and \
numbers from the snapshot rather than speaking in generalities.
5. Anything marked SIMULATED is synthetic training data, not real market \
information. Never present it as a real-world fact or as investment advice.

Answer in {language}. If the operator writes to you in a different language \
than that, answer in the language they used."""


def _dig_events(conn: Database) -> dict:
    recent = status_events.recent(conn, limit=25)
    return {
        "recent_narration": [
            {"at": e["timestamp"], "from": (e["source_agent"] or e["source_engine"]
                                            or e["source_department"]),
             "severity": e["severity"], "status": e["status"], "message": e["message"]}
            for e in recent
        ],
        "where_things_stand": [
            {"who": (e["source_agent"] or e["source_engine"] or e["source_department"]),
             "status": e["status"], "last_said": e["message"]}
            for e in status_events.current_status(conn)
        ],
        "needing_attention": [
            {"at": e["timestamp"], "severity": e["severity"], "message": e["message"]}
            for e in status_events.recent(conn, limit=15,
                                          severities=status_events.ATTENTION_SEVERITIES)
        ],
    }


def _dig_organization(conn: Database) -> dict:
    named = {
        row["assigned_to_identity"]: row["name"]
        for row in conn.fetchall(
            "SELECT name, assigned_to_identity FROM agent_names "
            "WHERE assigned_to_identity IS NOT NULL")
    }
    agents = conn.fetchall(
        "SELECT identity, role, lifecycle_state, process_state, last_heartbeat_at "
        "FROM agent_registry ORDER BY role")
    return {
        "agents": [
            {"name": named.get(a["identity"]), "role": a["role"], "identity": a["identity"],
             "lifecycle": a["lifecycle_state"], "process": a["process_state"],
             "last_heartbeat": a["last_heartbeat_at"]}
            for a in agents
        ],
        "names_available": conn.fetchone(
            "SELECT COUNT(*) AS n FROM agent_names "
            "WHERE assigned_to_identity IS NULL AND reserved = 0")["n"],
    }


def state_digest(conn: Database, boot=None) -> dict:
    """Everything the COO is allowed to speak from - the same material the
    console's desks render, compacted.

    Each section is gathered defensively: one unavailable section must leave
    the COO able to answer about the others, rather than muting it entirely
    (38 §12's rule applied to the reporter)."""
    def _safe(fn, fallback):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            return {"unavailable": f"{exc.__class__.__name__}: {exc}", **fallback}

    digest: dict = {}
    digest["events"] = _safe(lambda: _dig_events(conn), {})
    digest["organization"] = _safe(lambda: _dig_organization(conn), {"agents": []})

    if boot is None:
        try:
            from backend.boot_config import load

            boot = load()
        except Exception:  # noqa: BLE001 - a missing boot config is itself reportable
            boot = None
    digest["configuration"] = {
        "lifecycle_stage": getattr(boot, "lifecycle_stage", None) or "unknown",
        "implemented_asset_classes": list(getattr(boot, "implemented_asset_classes", ())),
        "current_focus": list(getattr(boot, "current_focus", ())),
        "simulation_focus": list(getattr(boot, "simulation_focus", ())),
    }

    digest["reference_data"] = _safe(lambda: {
        "ready": reference_data.is_ready(conn),
        "focus_assets": [a["primary_identifier"] for a in reference_data.list_focus_assets(conn)],
    }, {"ready": False})

    digest["missions"] = _safe(lambda: [
        {"mission_id": m["mission_id"], "strategy": m["strategy"], "status": m["status"]}
        for m in __import__("backend.missions", fromlist=["missions"]).list_missions(conn)[:15]
    ], [])

    # What is deliberately unbuilt, so the COO can tell "idle" from "does not
    # exist" (rule 3 in the system prompt). Stated here rather than left for
    # the model to infer from absence, because absence looks identical to
    # quiet from inside a snapshot.
    digest["not_built_yet"] = {
        "parliament": "No parliament, committee or voting body exists. Addendum 32's "
                      "machinery is deferred (SPEC_RECONCILIATION §47): at this population "
                      "it would be ceremony without constituents. The Strategic Priority "
                      "Register stands in its place.",
        "education_department": "No Curriculum Architect or trainer agents exist yet; the "
                                "addendum-13 training loop performs the function (§60).",
        "finance_desk_news": "The Finance tab's headlines are SIMULATED placeholders until "
                             "newspaper agents exist to write them.",
        "coo_actions": "The COO can report but cannot act - no spawn, retire, mission or "
                       "configuration change is available through this chat.",
    }
    return digest


def answer(conn: Database, question: str, *, language: str = DEFAULT_LANGUAGE,
           history: list[dict] | None = None, provider=None) -> dict:
    """Answer one operator question from real state.

    Returns `{'answer': str, 'grounded_in': [...], 'error': str|None}`. An
    unavailable model is reported as an error the console can render, never
    as a fabricated reply - a console that invents an answer when the model
    is down is worse than one that says the model is down."""
    if not (question or "").strip():
        return {"answer": "", "grounded_in": [], "error": "empty question"}

    digest = state_digest(conn)
    label = LANGUAGE_LABELS.get(language, language)
    system = SYSTEM_PROMPT.format(language=label)

    import json

    messages = list(history or [])[-8:]  # a short memory; the console is not a transcript store
    messages.append({
        "role": "user",
        "content": f"SYSTEM STATE (the only source of truth):\n{json.dumps(digest, indent=1, default=str)}\n\n"
                   f"OPERATOR QUESTION: {question}",
    })

    try:
        if provider is None:
            from app.model_gateway import default_provider

            provider = default_provider()
        response = provider.complete(system, messages, [], max_tokens=MAX_TOKENS)
        text = "".join(
            block.text for block in getattr(response, "content", [])
            if getattr(block, "type", None) == "text"
        )
    except Exception as exc:  # noqa: BLE001 - the console must render the failure
        return {
            "answer": "",
            "grounded_in": sorted(digest),
            "error": f"{exc.__class__.__name__}: {exc}",
        }

    return {"answer": text.strip(), "grounded_in": sorted(digest), "error": None}
