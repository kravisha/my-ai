"""What the assistant can actually do, and the one place it is done.

Addendum 16 §10's one-hop requirement applied to the Scoreboard: *"Create the
final specification and send it to the project" should be ONE interaction.* The
Super User saying "put that on the board as urgent, it's blocking" must file the
item - not produce a description of an item for the Super User to then file
somewhere. The transport the human is supposed to stop being (§26) includes the
short hop between deciding something and recording it.

Eighteen tools: five Scoreboard, three Git, two for the running Jarvis system,
one for the Technology and Architecture review, one for this PC, one for the
*other* machines this one is authorised to look at, **two for recovering one of
them**, one that types a message into box 2 of the owner's page, and two for the
channel the assistant shares with the Claude session on this machine. The
system ones are **read-only** - `gateway/jarvis.py` issues GETs and nothing else,
because retiring or resuming an agent is a lifecycle action the Controller alone
executes (addendum 11 §15) and a conversational model is not the right holder of
that authority. Nothing here can push, either.

**One tool changes another machine, and it is the only one.** `remote_recover`
runs a command a person wrote, on a machine a person authorised, after a fresh
diagnosis says the thing is actually down and a human says yes. It is gated by
its own capability rather than by `system:status`, because looking at a machine
and acting on it are different authorities; `gateway/recovery.py` carries the
five gates and the reasoning for each.

**Two tools write outside this system, and they are not the same act.**
`message_claude` sends, with nobody's press, because the entry it writes is
headed as coming from the assistant. `draft_message_to_claude` only fills a box,
because the entry *that* produces says Krish directed it. The difference is
whose name is on the line, and it is the whole reason one needs a human tap and
the other does not; `gateway/devchannel.py` carries the reasoning.

**One tool reaches the owner's screen, and it stops there.**
`draft_message_to_claude` fills a text area and returns; it cannot press the
button underneath it. The full reasoning is in `gateway/interface.py`, where the
action is implemented, and it is worth reading before anything is added beside
it: the frame the page will act on is named in `interface.UI_ACTIONS`, so a tool
cannot invent one.

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
from gateway import devchannel, interface, machine, recovery, remote, roles
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

MACHINE_TOOLS = [
    {
        "name": "machine_status",
        "description": (
            "What is happening on this PC right now: disk space per drive with a "
            "state, memory, the heaviest processes by CPU and by memory, the largest "
            "folders, and what has changed in the last few hours. Returns a "
            "'concerns' list derived from fixed thresholds, so 'is anything wrong' "
            "has a reproducible answer rather than a guess - an empty list genuinely "
            "means nothing crossed a line, and you should say so positively. "
            "Read-only: it starts, stops and deletes nothing. It deliberately does "
            "NOT report per-application disk usage; see 'not_measured' in the result "
            "and repeat that reason if asked, rather than estimating."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]

# The other machines, and the first tool here that looks past this host.
#
# Krish, 2026-09-16 18:12: *"Jarvis must eventually be able to diagnose services
# and agents running on other authorized machines, not only its own machine ...
# Report findings before taking corrective action."* Phase 1 of the plan he
# attached, and read-only by construction - `gateway/remote.py` has no code path
# that changes anything anywhere.
#
# **The argument is a configured name, never an address.** That is the guard
# worth stating twice: a `host` parameter would let a sentence in a conversation
# aim this Gateway at any machine it can reach, and the machines it may look at
# are a decision somebody made in a file on disk.
#
# The description spends most of its words on honesty about the gaps, because
# the failure mode here is not a crash. It is a confident report about a process
# nobody looked at, delivered to someone on another continent who then decides
# whether to restart something.
REMOTE_TOOLS = [
    {
        "name": "remote_diagnose",
        "description": (
            "Diagnose another authorized machine and the agents and services on "
            "it: whether the tailnet can see it, whether its ports accept a "
            "connection, whether its services answer a health request, and "
            "whether the files its agents write are still moving. Returns a "
            "report with a probable cause, a confidence and a recommended next "
            "action. Use it when asked whether another machine or another agent "
            "is up, stuck or gone. "
            "READ-ONLY and safe to run whenever asked: it starts, stops, writes "
            "and deletes nothing, here or there. It cannot recover anything "
            "itself; recovery is remote_recovery_options and remote_recover, and "
            "those need his explicit yes. Diagnose first and say what you found "
            "before offering to act - never in the same breath. "
            "Name a machine from the configured list; omit it for all of them. "
            "You cannot supply an address, and there is no way to look at a "
            "machine that is not in that list. "
            "Read 'not_measured' and repeat it. Without a credential on the far "
            "end this cannot see the remote process table, a PID, the directory "
            "structure or the remote logs - those are absent, not clean, and "
            "guessing at them would be the one failure this is built to avoid. "
            "An agent's state is only ever 'alive', 'quiet' or 'no evidence'. "
            "Never call a quiet agent hung: from outside, an idle session and a "
            "dead one look identical, and the wrong word there gets a working "
            "session killed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": (
                        "The name of a configured machine. Omit to diagnose every "
                        "configured machine. A name that is not configured is "
                        "refused, and the refusal lists the ones that are."
                    ),
                },
            },
            "required": [],
        },
    },
]

# Recovery: the first thing in this file that changes another machine.
#
# Krish's plan made diagnosis Phase 1 and recovery Phase 3, deliberately apart.
# The capability keeps them apart at the boundary too - `system:recover`, not
# `system:status` - which is the line TOOL_CAPABILITY below wrote down before
# there was anything to hold to it.
#
# Two tools, because "what could you do about it" must be answerable without any
# risk of answering it by doing it. `remote_recovery_options` changes nothing and
# is the one an operator wants first; `remote_recover` is the act, and it refuses
# without a confirmation that no amount of reasoning can supply.
RECOVERY_TOOLS = [
    {
        "name": "remote_recovery_options",
        "description": (
            "What recovery actions are configured for an authorized machine, what "
            "each one does, the service state each answers, and its cooldown and "
            "daily ceiling. READ-ONLY: it runs nothing. Use it after a diagnosis, "
            "when asked what can be done about a service that is down, and to "
            "quote the exact action name back before proposing one. "
            "A machine with no actions configured says so - nothing is built in, "
            "because a built-in restart command would assume what is running on "
            "the far end."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": (
                        "The name of a configured machine. Omit for all of them."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "remote_recover",
        "description": (
            "Run ONE configured recovery action on ONE authorized machine - the "
            "only tool here that changes anything on any machine. "
            "It diagnoses first, every time, and obeys the verdict: a service that "
            "is answering is not restarted, a machine that is unreachable is not "
            "acted on, and a diagnosis of low confidence refuses. Low confidence is "
            "usually an agent judged by a file that has not moved - quiet is not "
            "stopped, and a restart on that evidence can kill a working session. "
            "REQUIRES `confirm`, and you may not set it on your own reasoning. Call "
            "once without it, tell him in plain words what would run and where, and "
            "set it only after he says yes. Him asking about a problem is not a yes. "
            "You cannot supply a command or an address: both the machine and the "
            "action are names from the configuration, and the command behind an "
            "action was written by a person. "
            "Report the 'recovered' field, which is a fresh probe after the fact - "
            "NOT 'command_ran', which only says the command executed. A restart can "
            "exit zero and leave the service exactly as dead as it was. "
            "Every attempt is journalled, and each action has a cooldown and a "
            "daily ceiling; hitting either is a refusal to report plainly, not a "
            "failure to retry around."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "The name of a configured machine.",
                },
                "action": {
                    "type": "string",
                    "description": (
                        "The name of a recovery action configured for that machine, "
                        "exactly as remote_recovery_options gives it."
                    ),
                },
                "confirm": {
                    "type": "boolean",
                    "description": (
                        "True only when he has said yes to this specific action on "
                        "this specific machine. Never inferred."
                    ),
                },
            },
            "required": ["target", "action"],
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

# The one tool whose effect is on the owner's screen rather than in a store.
#
# Krish asked for it in those words - *"he should be able to paste messages in the
# box where I send messages to you"* - and the shape of the ask is the shape of
# the guarantee: paste, not send. The description says so twice because the model
# will be tempted to report the job as finished, and "I have sent it to Claude"
# is the one sentence here that would be a lie with consequences.
INTERFACE_TOOLS = [
    {
        "name": "draft_message_to_claude",
        "description": (
            "Type a message into box 2 of his page - the box he sends to Claude, the "
            "engineer session working on this machine. Use it the moment he asks you to "
            "tell Claude something or to put something in that box; do not offer to do "
            "it and wait. It fills the box and stops: nothing is sent, no file is "
            "written and nothing is executed until he presses 'Send to Claude' himself. "
            "Afterwards say it is in box 2 and waiting for him - never that it has been "
            "sent, and never that Claude has it. Write the message as he would send it, "
            "because it goes out attributed to him. Whatever was in the box is "
            "replaced, so if he may have been writing there himself, read it back to "
            "him rather than overwriting it silently."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": (
                        "The complete message, exactly as it should appear in the box. "
                        "No preamble, no covering note, nothing addressed to him - this "
                        "text is read by Claude, not by him."
                    ),
                },
            },
            "required": ["text"],
        },
    },
]

# The channel, and the first tool in this file that speaks for the assistant
# itself rather than for Krish.
#
# Krish asked for it on 2026-09-16 12:03 and attached the condition that makes it
# safe: *"on the condition that he identifies himself as Jarvis explicitly and so
# you can know."* That condition is not carried by the model's good manners - it
# is the header `gateway/devchannel.py` writes, which the model cannot choose.
# So `message_claude` needs no human press, unlike `draft_message_to_claude`:
# nothing it writes claims to have come from him.
CHANNEL_TOOLS = [
    {
        "name": "message_claude",
        "description": (
            "Send a message to Claude, the engineer session running on this same "
            "machine, on the channel the two of you share. This one sends - no "
            "press from Krish, because the entry is headed as being from you and "
            "claims to be nothing else. Use it when something is wrong with this "
            "machine, this Gateway or your own tools: a tool returning "
            "available=false, a credential that is not working, a page that looks "
            "stale. He is on this host and can fix those; routing them through "
            "Krish sends the problem to another continent and back. Say what you "
            "observed and what you were doing when you saw it. He reads the "
            "channel every few minutes, so tell Krish it has been sent and that a "
            "reply is minutes away - not that it has been answered. Do NOT use it "
            "to pass on something Krish said; that is box 2 and "
            "draft_message_to_claude, whose entries carry his direction."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": (
                        "The message, in your own words, as one machine telling "
                        "another what it sees. No greeting and no covering note."
                    ),
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "read_claude",
        "description": (
            "Read what Claude has written to you on the shared channel. Read-only "
            "and always safe to call. Call it when Krish asks for Claude's status, "
            "what Claude is working on, or whether something you reported has been "
            "dealt with - his answers there are the status, and reading them is "
            "how Krish gets it from you directly. Also read it before repeating a "
            "report, in case it has already been answered. An empty channel means "
            "he has not written yet; say so rather than filling the gap."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "How many of his most recent messages. Default 5.",
                },
            },
            "required": [],
        },
    },
]

TOOLS = (TOOLS + JARVIS_TOOLS + TECHNOLOGY_TOOLS + MACHINE_TOOLS + REMOTE_TOOLS
         + RECOVERY_TOOLS + INTERFACE_TOOLS + CHANNEL_TOOLS)


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
    "machine_status": roles.CAP_SYSTEM_STATUS,
    # The same capability as machine_status, and reusing it rather than minting
    # a `remote` one is deliberate. `system:status` already means "observe
    # infrastructure, change nothing", which is exactly what this is; a new
    # capability would mean editing GRANTS, the one change in gateway/roles.py
    # that can silently widen or lock out a role. When recovery is built it will
    # NOT reuse this - acting on another machine is a different authority from
    # looking at one, and that is the line this mapping is here to hold.
    "remote_diagnose": roles.CAP_SYSTEM_STATUS,
    # And here is that line being held. Recovery does NOT reuse `system:status`:
    # acting on another machine is a different authority from looking at one, so
    # it is `system:recover`, which only the operator holds. `internal` keeps
    # `remote_diagnose` and is refused both of these - a role that may watch a
    # service die is not thereby a role that may bounce it.
    #
    # Listing the options is gated the same as taking one, deliberately. The
    # catalogue of ways to act on a machine is part of the acting surface, and
    # splitting it off would mean `internal` could enumerate exactly which
    # commands the operator is able to fire and where - addendum 40 §14's
    # sensitive operational view, for no gain that a diagnosis does not already
    # provide.
    "remote_recovery_options": roles.CAP_SYSTEM_RECOVER,
    "remote_recover": roles.CAP_SYSTEM_RECOVER,
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
    # `publish`, the same capability as /voice/relay and as the `relay_to_claude`
    # skill, and for the reason stated in both: carrying a message out to the
    # engineer who maintains this machine is not something `converse` should buy.
    # Drafting is the first half of that act, so it is gated with the second half
    # rather than one step below it - a client who could fill the operator's
    # outbox has already put words in his mouth, whoever presses the button.
    "draft_message_to_claude": roles.CAP_PUBLISH,
    # The channel gets the same capability, and reusing it rather than minting a
    # `channel` capability is deliberate: `publish` is already "put something
    # outside this system", which is what appending to a file another agent acts
    # on is, and a new capability would mean editing GRANTS - the one change in
    # this module that can silently widen or lock out a role. Reading is gated
    # the same as writing: the channel carries what is broken on this machine and
    # what Claude is doing about it, which is addendum 40 §14's sensitive
    # operational view, not conversation.
    "message_claude": roles.CAP_PUBLISH,
    "read_claude": roles.CAP_PUBLISH,
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
        if name == "machine_status":
            return machine.snapshot()

        if name == "remote_diagnose":
            # `target` is passed through as given. An unconfigured name is
            # refused inside `diagnose`, with the configured names in the
            # refusal, so the model corrects itself rather than reporting that
            # a machine could not be reached - which is what a silent empty
            # result would look like, and it is a different and worse claim.
            return remote.diagnose(arguments.get("target"))

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

        if name == "draft_message_to_claude":
            # Returns a `ui` effect rather than doing anything itself. The page is
            # what types, `gateway/conversation.run_turn` is what forwards it, and
            # `interface.UI_ACTIONS` is what bounds it.
            return interface.draft_for_relay(arguments.get("text", ""))

        if name == "message_claude":
            # ChannelRefused is caught below with the other refusals, so a rate
            # limit or an oversized message reaches the model as a sentence it
            # can act on rather than ending the turn.
            return {"sent": devchannel.append_message(arguments.get("text", "")),
                    "note": ("It is on the channel and it is sent. He reads it "
                             "within a few minutes. Say that a reply is minutes "
                             "away - not that he has answered.")}

        if name == "read_claude":
            return devchannel.read_from_claude(arguments.get("limit") or 5)

        if name == "remote_recovery_options":
            return recovery.available(arguments.get("target"))

        if name == "remote_recover":
            # `confirm` is read strictly: anything other than a literal true is
            # not a confirmation. A model that passed "yes" as a string has not
            # been told yes by anybody.
            return recovery.recover(
                str(arguments["target"]),
                str(arguments["action"]),
                confirm=arguments.get("confirm") is True,
            )

        if name == "technology_review":
            report = technology.review()
            if arguments.get("file_findings"):
                report["filed"] = technology.file_findings(conn, report)
            return report

    except (scoreboard.ScoreboardError, repositories.RepositoryError,
            devchannel.ChannelRefused, recovery.RecoveryRefused) as refusal:
        return {"error": str(refusal)}
    except (KeyError, TypeError, ValueError) as malformed:
        # A tool call with a missing or unusable argument. Reported the same way
        # so the model can retry with a correct one instead of the turn dying.
        return {"error": f"Bad arguments for {name}: {malformed}"}

    return {"error": f"Unknown tool {name!r}."}
