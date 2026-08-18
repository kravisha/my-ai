"""What the assistant can actually do, and the one place it is done.

Addendum 16 §10's one-hop requirement applied to the Scoreboard: *"Create the
final specification and send it to the project" should be ONE interaction.* The
Super User saying "put that on the board as urgent, it's blocking" must file the
item - not produce a description of an item for the Super User to then file
somewhere. The transport the human is supposed to stop being (§26) includes the
short hop between deciding something and recording it.

Five tools, all Scoreboard. Git and system status are not here because they are
not built; the system prompt says so, and an assistant with no tool for a thing
cannot quietly pretend otherwise.

**Every failure comes back as a tool result, not an exception.** The model reads
these strings and is expected to correct itself from them - "importance must be
one of urgent, important, informational" is actionable, and a stack trace ending
the turn is not. `gateway/scoreboard.py` raises ScoreboardError with messages
written for that reader.

**Source is set here, never by the model.** `file_scoreboard_item` has no source
parameter: an item filed through this conversation is attributed to the
conversation, and a model that could name its own provenance could file an item
as though a monitoring agent had raised it. Addendum 17 §6 has agents publishing
findings with their own attribution when that path exists; until then, one
truthful value.
"""

from backend.db import Database
from gateway import scoreboard

# Who filed it, when it came through the Super User's conversation. Agents get
# their own attribution when addendum 17 §6's ingestion path is built (G7).
CONVERSATION_SOURCE = "super-user-conversation"

TOOLS = [
    {
        "name": "file_scoreboard_item",
        "description": (
            "Record a question, concern, ambiguity or observation on the Project "
            "Scoreboard so it is not lost and does not have to interrupt work now. "
            "File one whenever something surfaces that deserves a decision later; "
            "do not ask permission first unless the user's intent is unclear."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question or concern, stated so it is still clear in a week.",
                },
                "importance": {
                    "type": "string",
                    "enum": list(scoreboard.IMPORTANCE_LEVELS),
                    "description": (
                        "urgent: a serious operational, architectural, security, data-integrity "
                        "or availability concern. important: deserves attention but need not "
                        "interrupt. informational: useful, review later. Default informational."
                    ),
                },
                "blocking": {
                    "type": "boolean",
                    "description": (
                        "Whether work is actually stopped by it. Separate from importance: an "
                        "urgent question can be non-blocking, and a trivial one can block."
                    ),
                },
                "related_spec": {
                    "type": "string",
                    "description": "The specification it concerns, e.g. 'addendum 16 §16'.",
                },
                "related_component": {
                    "type": "string",
                    "description": "The code it concerns, e.g. 'gateway/store.py'.",
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "list_scoreboard_items",
        "description": (
            "The Scoreboard, most pressing first. Use it when asked what is open, "
            "what is outstanding, or what needs a decision."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": list(scoreboard.STATUSES)},
                "importance": {"type": "string", "enum": list(scoreboard.IMPORTANCE_LEVELS)},
                "limit": {"type": "integer"},
            },
            "required": [],
        },
    },
    {
        "name": "get_scoreboard_item",
        "description": "One item in full, including its discussion so far.",
        "input_schema": {
            "type": "object",
            "properties": {"item_id": {"type": "integer"}},
            "required": ["item_id"],
        },
    },
    {
        "name": "add_scoreboard_note",
        "description": (
            "Append to an item's discussion - a consideration, a piece of evidence, "
            "a partial answer. Notes are permanent and are never edited."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "integer"},
                "note": {"type": "string"},
            },
            "required": ["item_id", "note"],
        },
    },
    {
        "name": "resolve_scoreboard_item",
        "description": (
            "Close an item, stating what was decided. Only when the user has "
            "actually decided - the resolution is the durable record of the "
            "decision, so it must say what it was, not that it happened."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "integer"},
                "resolution": {"type": "string"},
            },
            "required": ["item_id", "resolution"],
        },
    },
]

TOOL_NAMES = {tool["name"] for tool in TOOLS}


def execute(conn: Database, name: str, arguments: dict) -> dict:
    """Runs one tool call. Returns `{"error": ...}` rather than raising, for every
    failure the model could plausibly cause."""
    try:
        if name == "file_scoreboard_item":
            item_id = scoreboard.file_item(
                conn,
                source=CONVERSATION_SOURCE,
                question=arguments.get("question", ""),
                importance=arguments.get("importance") or "informational",
                blocking=bool(arguments.get("blocking", False)),
                related_spec=arguments.get("related_spec"),
                related_component=arguments.get("related_component"),
            )
            return {"filed": scoreboard.get_item(conn, item_id)}

        if name == "list_scoreboard_items":
            items = scoreboard.list_items(
                conn,
                status=arguments.get("status"),
                importance=arguments.get("importance"),
                limit=int(arguments.get("limit") or 50),
            )
            return {"items": items, "open_counts": scoreboard.open_counts(conn)}

        if name == "get_scoreboard_item":
            item = scoreboard.get_item(conn, int(arguments["item_id"]))
            if item is None:
                return {"error": f"No Scoreboard item {arguments['item_id']}."}
            return {"item": item}

        if name == "add_scoreboard_note":
            note_id = scoreboard.add_note(
                conn,
                int(arguments["item_id"]),
                author=CONVERSATION_SOURCE,
                note=arguments.get("note", ""),
            )
            return {"note_id": note_id, "item": scoreboard.get_item(conn, int(arguments["item_id"]))}

        if name == "resolve_scoreboard_item":
            return {
                "resolved": scoreboard.resolve_item(
                    conn, int(arguments["item_id"]), arguments.get("resolution", "")
                )
            }

    except scoreboard.ScoreboardError as refusal:
        return {"error": str(refusal)}
    except (KeyError, TypeError, ValueError) as malformed:
        # A tool call with a missing or unusable argument. Reported the same way
        # so the model can retry with a correct one instead of the turn dying.
        return {"error": f"Bad arguments for {name}: {malformed}"}

    return {"error": f"Unknown tool {name!r}."}
