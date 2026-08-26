"""What the assistant can actually do, and the one place it is done.

Addendum 16 §10's one-hop requirement applied to the Scoreboard: *"Create the
final specification and send it to the project" should be ONE interaction.* The
Super User saying "put that on the board as urgent, it's blocking" must file the
item - not produce a description of an item for the Super User to then file
somewhere. The transport the human is supposed to stop being (§26) includes the
short hop between deciding something and recording it.

Eleven tools: five Scoreboard, three Git, two for the running Jarvis system, one
for the Technology and Architecture review. The
system ones are **read-only** - `gateway/jarvis.py` issues GETs and nothing else,
because retiring or resuming an agent is a lifecycle action the Controller alone
executes (addendum 11 §15) and a conversational model is not the right holder of
that authority. Nothing here can push, either.

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
from gateway import roles
from gateway import jarvis, repositories, scoreboard, technology

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

JARVIS_TOOLS = [
    {
        "name": "jarvis_status",
        "description": (
            "The running Jarvis organization: which agents exist, their lifecycle "
            "state (active or dormant) and process state (running, stopped or "
            "crashed), and how stale each heartbeat is. Read-only. If the backend "
            "is not running this returns available=false with a reason - report "
            "that plainly rather than guessing at the state."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "jarvis_agent",
        "description": (
            "One agent in detail, by identity such as 'explorer-1' - its record, "
            "health and history. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"identity": {"type": "string"}},
            "required": ["identity"],
        },
    },
]

TECHNOLOGY_TOOLS = [
    {
        "name": "technology_review",
        "description": (
            "Run the Technology and Architecture review (addendum 17 §7-§9): the "
            "suitability of the databases, runtime, dependencies, capacity and "
            "external tools, each with the evidence behind it. Read-only, and safe "
            "to run whenever asked. Use it for questions like 'should we move to "
            "PostgreSQL' - answer from its evidence, and say plainly when a verdict "
            "is 'no_evidence' rather than filling the gap."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_findings": {
                    "type": "boolean",
                    "description": (
                        "Also file anything needing a decision onto the Scoreboard. "
                        "Repeat findings are not duplicated."
                    ),
                }
            },
            "required": [],
        },
    },
]

TOOLS = TOOLS + JARVIS_TOOLS + TECHNOLOGY_TOOLS


# The client's holdings tools are withdrawn (TQ-72, §111, §115).
#
# There were five - record, list, forget, balances, analyse - and they were built
# on §96's answer to "where do a client's holdings come from": *the client tells
# you, and you remember.* Owner direction retired both halves of that sentence.
# The client does not dictate positions (they name a source and supply
# credentials), and nothing is remembered (§115: fetched per session, discarded
# on disconnect).
#
# So they are **removed rather than left refusing**. `gateway/skills.py`'s
# declared-and-unbuilt pattern is right when a capability is specified and not
# yet built; it is wrong here, because the shape changes. Declaring
# `record_holding` as "coming soon" would be promising a tool this system has
# decided not to have, and a client agent offered it would keep trying.
#
# What replaces them is TQ-73's: one request that names sources, and an analysis
# that comes back. It is deliberately not sketched here - a tool schema written
# before the pipeline exists is a guess that later has to be honoured.

TOOL_NAMES = {tool["name"] for tool in TOOLS}


# Which capability each tool requires (TQ-34, §92).
#
# This map is the sharpest thing in the Gateway's authorization story, because
# without it every route check is theatre: a client who may only "talk to the
# agent" would simply *ask the agent* to read a repository file, and the agent
# would do it. Addendum 40 §14's rule - the presentation layer must never
# bypass backend authorization - applies with more force to a tool list than to
# a dashboard, since a model will happily reach for anything it is offered.
#
# Enforced in two places on purpose. `for_role` filters what the model is
# *offered*, which is presentation and stops it attempting refusals; `execute`
# checks again, which is the boundary, because a model can name a tool nobody
# offered it.
TOOL_CAPABILITY = {
    "file_scoreboard_item": roles.CAP_SCOREBOARD_WRITE,
    "list_scoreboard_items": roles.CAP_SCOREBOARD_READ,
    "get_scoreboard_item": roles.CAP_SCOREBOARD_READ,
    "add_scoreboard_note": roles.CAP_SCOREBOARD_WRITE,
    "resolve_scoreboard_item": roles.CAP_SCOREBOARD_WRITE,
    "list_repository_files": roles.CAP_REPOSITORY_READ,
    "read_repository_file": roles.CAP_REPOSITORY_READ,
    "publish_document": roles.CAP_PUBLISH,
    "jarvis_status": roles.CAP_SYSTEM_STATUS,
    "jarvis_agent": roles.CAP_SYSTEM_STATUS,
    "technology_review": roles.CAP_TECHNOLOGY_READ,
    # `CAP_HOLDINGS` itself is deliberately left declared in gateway/roles.py
    # with no tool mapped to it (TQ-72). The capability is real and the role
    # matrix around it is correct; what is gone is this build's answer to it.
    # Removing the capability as well would mean re-deciding who may reach
    # holdings when TQ-73 rebuilds the tools, and that decision was made
    # carefully in §92 and should not be made twice.
}


class ToolNotPermitted(PermissionError):
    """A role reached for a tool it does not hold the capability for."""


def for_role(role: str) -> list[dict]:
    """The tools this role may actually use.

    A client holds only `converse`, so this returns **nothing** for them - which
    is the correct shape of the personal agent today: it answers from what it
    knows and has no reach into the organization. When a client agent gains real
    skills (portfolio analysis, trade ideas), each arrives as its own capability
    and its own entry above, rather than by widening what `converse` means."""
    granted = roles.capabilities(role)
    return [tool for tool in TOOLS
            if TOOL_CAPABILITY.get(tool["name"]) in granted]


def permitted(role: str, name: str) -> bool:
    required = TOOL_CAPABILITY.get(name)
    if required is None:
        # An unmapped tool is refused rather than allowed. A tool added without
        # a capability is a mistake, and the safe reading of a mistake here is
        # "nobody", not "everybody".
        return False
    return roles.allows(role, required)


def execute(conn: Database, name: str, arguments: dict, *, role: str,
            subject: str | None = None) -> dict:
    """Runs one tool call. Returns `{"error": ...}` rather than raising, for every
    failure the model could plausibly cause.

    The role is required, not optional. A default would mean a caller that forgot
    to pass one silently got the most permissive behaviour, which is the failure
    mode an authorization check least survives.

    `subject` is who the caller is, and it is where the holdings tools get their
    client id (TQ-42, §96). It comes from the session and never from an argument
    the model supplied, so there is no shape of tool call that reads another
    client's positions - the model cannot name a client because it is never
    asked to.

`subject` currently reaches no tool - the holdings tools that used it were
    withdrawn with the portfolio store (TQ-72, §111). It stays in the signature
    because TQ-73's analysis tools need exactly the same property, and the
    property is the interesting part: **the subject comes from the session and
    never from an argument the model supplied**, so there is no shape of tool
    call that acts for somebody else."""
    if not permitted(role, name):
        # Refused as data, like every other tool failure, so the model can tell
        # the user plainly instead of the turn collapsing.
        return {"error": f"Not permitted: your role ({role}) cannot use {name}."}
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

        if name == "jarvis_status":
            return jarvis.JarvisClient().status()

        if name == "jarvis_agent":
            return jarvis.JarvisClient().agent(str(arguments["identity"]))

        if name == "technology_review":
            report = technology.review()
            if arguments.get("file_findings"):
                report["filed"] = technology.file_findings(conn, report)
            return report

    except (scoreboard.ScoreboardError, repositories.RepositoryError) as refusal:
        return {"error": str(refusal)}
    except (KeyError, TypeError, ValueError) as malformed:
        # A tool call with a missing or unusable argument. Reported the same way
        # so the model can retry with a correct one instead of the turn dying.
        return {"error": f"Bad arguments for {name}: {malformed}"}

    return {"error": f"Unknown tool {name!r}."}
