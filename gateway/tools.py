"""What the assistant can actually do, and the one place it is done.

Addendum 16 §10's one-hop requirement applied to the Scoreboard: *"Create the
final specification and send it to the project" should be ONE interaction.* The
Super User saying "put that on the board as urgent, it's blocking" must file the
item - not produce a description of an item for the Super User to then file
somewhere. The transport the human is supposed to stop being (§26) includes the
short hop between deciding something and recording it.

Eight tools: five Scoreboard, three Git. System status is not here because it is
not built; the system prompt says so, and an assistant with no tool for a thing
cannot quietly pretend otherwise.

**Publishing has a confirmation the model cannot supply on its own reasoning.**
`publish_document` takes `confirm_public`, and `gateway/repositories.py` refuses a
public target without it - so a spoken sentence cannot become a public commit
through inference alone. The private repository is the default, and the guard
that stands behind all of this is documented where it acts rather than here.

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
from gateway import repositories, scoreboard

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

GIT_TOOLS = [
    {
        "name": "list_repository_files",
        "description": (
            "List files tracked in a project repository, optionally under a path "
            "prefix such as 'docs/addenda'. Use it to find a document before reading it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repository": {
                    "type": "string",
                    "description": "Which repository. Omit for the private one.",
                },
                "prefix": {"type": "string", "description": "Limit to this directory."},
            },
            "required": [],
        },
    },
    {
        "name": "read_repository_file",
        "description": (
            "Read a tracked text file from a project repository. Use it to answer "
            "questions about what a specification or a module actually says, rather "
            "than from memory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repository-relative path."},
                "repository": {"type": "string"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "publish_document",
        "description": (
            "Commit a document to a project repository on a new branch. Nothing is "
            "pushed and the working tree is not touched; a person reviews the branch "
            "and pushes it. Publishes to the private repository unless told otherwise. "
            "Publishing to the public repository additionally requires confirm_public, "
            "which you may only set when the user has explicitly said to publish there "
            "- never infer it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Repository-relative path, e.g. 'docs/addenda/foo.md'.",
                },
                "content": {"type": "string", "description": "The complete document."},
                "message": {"type": "string", "description": "Commit message."},
                "repository": {"type": "string"},
                "confirm_public": {
                    "type": "boolean",
                    "description": (
                        "Only when the user has explicitly named the public repository as the "
                        "destination in this conversation."
                    ),
                },
            },
            "required": ["path", "content", "message"],
        },
    },
]

TOOLS = TOOLS + GIT_TOOLS

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

        if name == "list_repository_files":
            repo = repositories.resolve(arguments.get("repository"))
            return {
                "repository": repo.name,
                "visibility": repo.visibility,
                "files": repositories.tracked_files(repo, arguments.get("prefix")),
            }

        if name == "read_repository_file":
            repo = repositories.resolve(arguments.get("repository"))
            return {
                "repository": repo.name,
                "path": arguments["path"],
                "content": repositories.read_file(repo, arguments["path"]),
            }

        if name == "publish_document":
            repo = repositories.resolve(arguments.get("repository"))
            return {
                "published": repositories.publish(
                    repo,
                    path=arguments["path"],
                    content=arguments.get("content", ""),
                    message=arguments.get("message", ""),
                    confirmed_public=bool(arguments.get("confirm_public", False)),
                )
            }

    except (scoreboard.ScoreboardError, repositories.RepositoryError) as refusal:
        return {"error": str(refusal)}
    except (KeyError, TypeError, ValueError) as malformed:
        # A tool call with a missing or unusable argument. Reported the same way
        # so the model can retry with a correct one instead of the turn dying.
        return {"error": f"Bad arguments for {name}: {malformed}"}

    return {"error": f"Unknown tool {name!r}."}
