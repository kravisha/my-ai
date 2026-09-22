"""What the assistant can actually do, and the one place it is done.

Addendum 16 §10's one-hop requirement applied to the Scoreboard: *"Create the
final specification and send it to the project" should be ONE interaction.* The
Super User saying "put that on the board as urgent, it's blocking" must file the
item - not produce a description of an item for the Super User to then file
somewhere. The transport the human is supposed to stop being (§26) includes the
short hop between deciding something and recording it.

Sixteen tools: five Scoreboard, three Git, two for the running Jarvis system,
one for the Technology and Architecture review, one for this PC, one for the
*other* machines this one is authorised to look at, one that types a
message into box 2 of the owner's page, and two for the channel the assistant
shares with the Claude session on this machine. The
system ones are **read-only** - `gateway/jarvis.py` issues GETs and nothing else,
because retiring or resuming an agent is a lifecycle action the Controller alone
executes (addendum 11 §15) and a conversational model is not the right holder of
that authority. Nothing here can push, either.

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

from app import boundaries, initiative
from app import learning as learning_package  # noqa: F401 - package docstring is the contract
from backend.db import Database
from gateway import devchannel, interface, machine, remote, roles
from gateway import dbaclient, failures, selfmod
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
            "and deletes nothing, here or there. It cannot recover anything - "
            "say so rather than offering. "
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

# The constitution's own mechanism for crossing a boundary, which is to argue
# that it should move (Krish, 2026-09-21; AI-CONSTITUTION.md "Take risks and
# challenge boundaries"; app/boundaries.py).
#
# Every field below is required, and the descriptions say why rather than what,
# because a model filling these in quickly will give the shape of an argument
# without the substance of one unless each box says what a bad answer looks
# like. `what_it_would_cost` is the field that would go first and is the one
# that makes this a proposal rather than a request.
BOUNDARY_TOOLS = [
    {
        "name": "propose_boundary_change",
        "description": (
            "Record the case for removing or moving a constraint that is "
            "costing something. Use it the moment you hit a limit you think is "
            "wrong - a capability you do not hold, a tool that does not exist, "
            "a rule that stopped you, an assumption that need not be true - "
            "rather than mentioning it in passing or working around it "
            "silently. File it in the same turn; do not ask permission to file "
            "one. This does not change anything: it writes an argument Krish "
            "reads and answers. You cannot grant yourself authority and must "
            "not imply that filing this has."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "constraint": {
                    "type": "string",
                    "description": (
                        "The limit itself, in the same words every time you hit "
                        "it - entries are grouped by this, and a constraint "
                        "described differently each time ranks as several "
                        "separate ones that each look rare."),
                },
                "kind": {
                    "type": "string",
                    "enum": list(boundaries.KINDS),
                    "description": (
                        "missing_capability: a grant you do not hold. "
                        "missing_tool: something nobody has built. "
                        "policy_gate: a rule that stopped you, including "
                        "app/initiative.py's own - you are expected to argue "
                        "with it if you think it is wrong. missing_access: a "
                        "credential, machine or file out of reach. "
                        "design_assumption: something the system assumes that "
                        "need not be true."),
                },
                "what_it_prevents": {
                    "type": "string",
                    "description": (
                        "The outcome that did not happen. Concrete and from "
                        "this conversation - \"I could not X for Krish just "
                        "now\" beats \"this limits flexibility\"."),
                },
                "what_i_would_do": {
                    "type": "string",
                    "description": (
                        "The better arrangement, specifically enough that "
                        "somebody could build or grant it without asking you a "
                        "follow-up question."),
                },
                "what_it_would_cost": {
                    "type": "string",
                    "description": (
                        "What goes wrong if this is the wrong call - the risk "
                        "you are asking him to accept. A proposal with only an "
                        "upside is a request, not a boundary challenge, and is "
                        "refused. Say it even when you think the risk is small; "
                        "\"very little, because it is revocable\" is a real "
                        "answer."),
                },
                "reversible_if_granted": {
                    "type": "boolean",
                    "description": (
                        "Whether granting this could be taken back if it turns "
                        "out badly. True for a config change or a revocable "
                        "grant; false for anything that publishes, sends or "
                        "deletes. The report sorts cheap-to-try first, so an "
                        "honest false here is what stops your reversible "
                        "proposals waiting behind somebody's hard decision."),
                },
            },
            "required": ["constraint", "kind", "what_it_prevents",
                         "what_i_would_do", "what_it_would_cost"],
        },
    },
]

# The Learning Engine's conversational surface (Krish, 2026-09-21; Document 2).
#
# Eleven tools rather than one `learning(action=...)`, and the extra schema cost
# is bought deliberately: this is the surface Krish tests by talking to it, and a
# single tool with a mode argument is the shape a model gets wrong under
# pressure. Each one below is a question he actually asks in Document 2 §8.
#
# `register_learned_skill` is the only one gated. See its entry in TOOL_RISK.
LEARNING_TOOLS = [
    {
        "name": "explain_how_i_learn",
        "description": (
            "Explain your own learning process. Use when asked whether you know "
            "how to learn, or how you learn. The answer is generated from the "
            "implementation - the real states, sources, primitives and failure "
            "classes - so describe what it returns rather than what you think "
            "the process should be."),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "what_to_learn_next",
        "description": (
            "What is worth learning next, ranked, with the evidence behind each. "
            "Use when asked what you want to learn. Pick one and say why in the "
            "candidate's own terms - what it prevents today - rather than "
            "choosing something that sounds impressive."),
        "input_schema": {"type": "object", "properties": {
            "limit": {"type": "integer", "description": "How many. Default 5."}},
            "required": []},
    },
    {
        "name": "begin_learning",
        "description": (
            "Define exactly what you are going to learn, and start an episode. "
            "This REFUSES a vague objective and tells you which of the seven "
            "requirements are unmet - that refusal is useful, so read it and "
            "resubmit rather than reporting failure. Every field matters: the "
            "cases become the tests, and held-out cases are how you prove you "
            "learned rather than fitted."),
        "input_schema": {"type": "object", "properties": {
            "slug": {"type": "string", "description": "short-kebab-case id"},
            "cannot_do": {"type": "string", "description": (
                "the specific thing that fails, with its input. Not a subject "
                "area - 'learn networking' is refused")},
            "success_looks_like": {"type": "string", "description": (
                "the successful behaviour, observably, in at least 8 words")},
            "inputs": {"type": "array", "items": {"type": "string"}},
            "outputs": {"type": "array", "items": {"type": "string"},
                        "description": "the fields it produces, named"},
            "environment": {"type": "string", "description": (
                "which machine and OS, and what must be present")},
            "gap_it_closes": {"type": "string", "description": (
                "why this is worth learning now rather than later")},
            "deterministic_possible": {"type": "boolean"},
            "llm_required": {"type": "boolean", "description": (
                "answering true is a real answer; do not claim determinism to "
                "get past the validator")},
            "cases": {"type": "array", "description": (
                "checkable properties of the output, not expected values. "
                "Vocabulary: no_error, rows>=N, rows==N, has_field:NAME, "
                "field_nonempty:NAME, field_is_int:NAME, "
                "field_matches:NAME=REGEX, field_between:NAME=LO..HI, "
                "unique:NAME, sorted_by:NAME, answer_is_int, "
                "contains_field_value:NAME=VALUE. Mark at least one held_out."),
                      "items": {"type": "object", "properties": {
                          "name": {"type": "string"},
                          "expect": {"type": "string"},
                          "detail": {"type": "string"},
                          "held_out": {"type": "boolean"}}}},
            "competencies": {"type": "array", "items": {"type": "object",
                "properties": {"name": {"type": "string"},
                               "why": {"type": "string"},
                               "already_have": {"type": "boolean"}}}},
            "dependencies": {"type": "array", "items": {"type": "string"}},
            "known_failure_modes": {"type": "array", "items": {"type": "string"}},
            "required_reliability": {"type": "string"}},
            "required": ["slug", "cannot_do", "success_looks_like", "inputs",
                         "outputs", "environment", "gap_it_closes",
                         "deterministic_possible", "llm_required", "cases"]},
    },
    {
        "name": "plan_learning",
        "description": (
            "Produce and store the learning plan and your commitment. Returns "
            "the questions to answer, what you already have, the sources in "
            "preference order, the sandbox surface, and the criteria for partial "
            "success and mastery. Do not invent a time estimate; the commitment "
            "is a condition."),
        "input_schema": {"type": "object", "properties": {
            "slug": {"type": "string"},
            "uncertainties": {"type": "array", "items": {"type": "string"},
                              "description": "what could prevent or delay this"},
            "ready_when": {"type": "string", "description": (
                "the completion condition, if you want to state it in your own "
                "words rather than the default")}},
            "required": ["slug"]},
    },
    {
        "name": "record_learning_finding",
        "description": (
            "Record something you worked out, and where it came from. Use "
            "empirical_probe when you ran it and observed the result - that "
            "outranks every document. Use model_recollection honestly when you "
            "are recalling rather than checking; it is marked unconfirmed until "
            "a test rests on it and passes."),
        "input_schema": {"type": "object", "properties": {
            "slug": {"type": "string"},
            "question": {"type": "string"},
            "answer": {"type": "string"},
            "source_kind": {"type": "string", "description": (
                "empirical_probe | jarvis_code_and_tests | local_documentation "
                "| model_recollection")},
            "source_ref": {"type": "string", "description": "file, path or command"}},
            "required": ["slug", "question", "answer", "source_kind"]},
    },
    {
        "name": "propose_skill_recipe",
        "description": (
            "Write or revise the skill as a recipe: steps over fixed primitives, "
            "which run with no model call. Each call stores a new version and "
            "keeps the old one, so revising after a failure is normal and "
            "reverting is free. Call explain_how_i_learn for the full "
            "vocabulary. A step is {op, into, args, note} - `into` names the "
            "binding the result is stored under, and later steps read it via "
            "args.from / args.left / args.right."),
        "input_schema": {"type": "object", "properties": {
            "slug": {"type": "string"},
            "name": {"type": "string"},
            "summary": {"type": "string"},
            "answer": {"type": "string", "description": (
                "which binding is the skill's output")},
            "needs_commands": {"type": "boolean", "description": (
                "true only if a step runs a program; file reads do not need it")},
            "steps": {"type": "array", "items": {"type": "object", "properties": {
                "op": {"type": "string"},
                "into": {"type": "string"},
                "args": {"type": "object"},
                "note": {"type": "string", "description": (
                    "what you learned at this step - this is what makes the "
                    "recipe reviewable")}}}},
            "why": {"type": "string", "description": (
                "what changed from the last version and why")}},
            "required": ["slug", "name", "summary", "answer", "steps"]},
    },
    {
        "name": "test_skill",
        "description": (
            "Run the recipe against its cases in a sandbox and diagnose any "
            "failure, with no model call. Stages: 'practice' runs the "
            "development cases; 'held_out' runs the cases you held back and is a "
            "separate gate, because passing only what you built against shows "
            "fitting rather than learning; 'trial' is the controlled real-world "
            "run. Read the diagnosis before revising - it names the failing step "
            "and what shape of mistake it is."),
        "input_schema": {"type": "object", "properties": {
            "slug": {"type": "string"},
            "stage": {"type": "string", "enum": ["practice", "held_out", "trial"]}},
            "required": ["slug", "stage"]},
    },
    {
        "name": "learning_status",
        "description": (
            "Where a skill has got to, in plain language: the state, what is "
            "still missing, the evidence so far, the current approach, and the "
            "most recent failure with its diagnosis. Use this to answer 'what "
            "are you learning', 'what failed', 'are you ready to show me'. Omit "
            "the slug for everything in progress."),
        "input_schema": {"type": "object", "properties": {
            "slug": {"type": "string"}}, "required": []},
    },
    {
        "name": "demonstrate_skill",
        "description": (
            "Show the skill working: run it now on this machine, with its "
            "output, the test results, the cases that used to fail, the step "
            "trace, the provenance and the zero-model-call accounting. Refuses "
            "when there is nothing worth showing and says what is missing. Show "
            "the actual output - a demonstration described rather than performed "
            "is the thing Document 2 §6 forbids."),
        "input_schema": {"type": "object", "properties": {
            "slug": {"type": "string"}}, "required": ["slug"]},
    },
    {
        "name": "record_skill_feedback",
        "description": (
            "Record Krish's judgement of a demonstrated skill. Recording is not "
            "acceptance: if he identified a weakness, revise the recipe and test "
            "again before asking him to register it."),
        "input_schema": {"type": "object", "properties": {
            "slug": {"type": "string"},
            "verdict": {"type": "string", "description": (
                "useful | useful_with_changes | not_useful | wrong")},
            "note": {"type": "string", "description": "what he actually said"}},
            "required": ["slug", "verdict"]},
    },
    {
        "name": "register_learned_skill",
        "description": (
            "Register a skill as learned and usable. This is the one step "
            "evidence cannot take on its own: set krish_accepted only when he "
            "has actually said so in this conversation, never by inference from "
            "passing tests. Tests show it works; only he can say it is what he "
            "wanted."),
        "input_schema": {"type": "object", "properties": {
            "slug": {"type": "string"},
            "krish_accepted": {"type": "boolean", "description": (
                "true only when he said yes, in words, in this conversation")}},
            "required": ["slug"]},
    },
    {
        "name": "use_learned_skill",
        "description": (
            "Run a skill you have already learned, as an ordinary skill. Costs "
            "no model call. The run is recorded, so a skill that stops working "
            "falls to degraded rather than silently returning nothing."),
        "input_schema": {"type": "object", "properties": {
            "slug": {"type": "string"}}, "required": ["slug"]},
    },
]


# The conversation half of the approval gate (§13, §18, and §38 q15's second
# interface). The CLI in `gateway/selfmod.py` is the other.
#
# THE ONE THING THAT MATTERS HERE. `decide_self_change` records who decided,
# and that name is taken from the authenticated session - never from an
# argument the model supplied. Letting the model name the decider would mean
# the agent whose code is being changed could write down that the owner
# approved it, which is §16's "alter the approval mechanism so that approval is
# no longer required" reached by the shortest possible route.
#
# `krish_said` is required and stored verbatim. It does not make fabrication
# impossible - a model that will invent an approval will invent a quote - but
# it makes it *visible*, because the decision record then carries words Krish
# can read back and say he never said. An approval whose only trace is a status
# field leaves nothing to dispute.
SELF_CHANGE_TOOLS = [
    {
        "name": "pending_self_changes",
        "description": (
            "List the changes you have proposed to your own code that are "
            "waiting for Krish to decide. Use when he asks what you want to "
            "change about yourself, or what is waiting on him. Read-only."),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "show_self_change",
        "description": (
            "Show one proposed change in full - the reason, the evidence, the "
            "files, the risks, the test plan and the rollback plan. Show this "
            "BEFORE asking him to decide; a decision taken on your summary "
            "rather than on the proposal is not the decision the gate is for. "
            "Read-only."),
        "input_schema": {"type": "object", "properties": {
            "change_id": {"type": "string",
                          "description": "The change id, as pending_self_changes gives it."}},
            "required": ["change_id"]},
    },
    {
        "name": "decide_self_change",
        "description": (
            "Record Krish's decision on a proposed change to your own code. "
            "Call this ONLY after he has said what he wants, in this "
            "conversation, having seen the proposal. You are recording his "
            "answer, not making one: you may not approve your own change, and "
            "the record says the decision came from his session. If he has not "
            "answered, or you are not certain what he meant, ask him instead "
            "of calling this - a wrong approve is not recoverable by "
            "apologising afterwards."),
        "input_schema": {"type": "object", "properties": {
            "change_id": {"type": "string"},
            "decision": {"type": "string", "enum": list(selfmod.DECISIONS),
                         "description":
                             "approve: go ahead. reject: do not. modify_scope: "
                             "approve fewer files. request_more_evidence: he "
                             "is not convinced the problem is real. defer: not "
                             "now."},
            "krish_said": {"type": "string",
                           "description":
                               "His own words, quoted, not your summary of "
                               "them. Stored on the decision so he can read "
                               "back what you recorded him as saying."},
            "files": {"type": "string",
                      "description":
                          "For modify_scope only: the comma-separated files "
                          "the narrower approval covers."},
        }, "required": ["change_id", "decision", "krish_said"]},
    },
]

TOOLS = (TOOLS + JARVIS_TOOLS + TECHNOLOGY_TOOLS + MACHINE_TOOLS + REMOTE_TOOLS
         + INTERFACE_TOOLS + CHANNEL_TOOLS + BOUNDARY_TOOLS + LEARNING_TOOLS
         + SELF_CHANGE_TOOLS)


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
    "file_scoreboard_item": roles.CAP_SCOREBOARD_WRITE,
    # Operator-only, and a capability of its own rather than a reuse. Every
    # other mapping here reuses an existing capability where the authority is
    # genuinely the same; this one is not the same as anything, because §13
    # makes Krish the final authority over self-modification and folding it
    # into `studio` would mean a future grant of the command centre silently
    # handed somebody the approval gate.
    "pending_self_changes": roles.CAP_SELF_CHANGE,
    "show_self_change": roles.CAP_SELF_CHANGE,
    "decide_self_change": roles.CAP_SELF_CHANGE,
    # The same capability as filing a Scoreboard item, and reusing it rather
    # than minting a `boundary` one is deliberate, for the reason the
    # remote_diagnose entry below gives: `scoreboard:write` already means
    # "record something Krish will decide later", which is exactly what a
    # boundary proposal is, and a new capability would mean editing GRANTS -
    # the one change in gateway/roles.py that can silently widen or lock out a
    # role. The authority being exercised is to write an argument down, not to
    # act on it; app/initiative.HARMS refuses the latter at every setting.
    "propose_boundary_change": roles.CAP_SCOREBOARD_WRITE,
    # The Learning Engine, split by what the tool actually does rather than by
    # subsystem. Reading what I know and running something I already learned is
    # `system:status` - observe, change nothing. Recording an objective, a
    # finding, a recipe or a verdict is `scoreboard:write` - put something down
    # that Krish will decide about later, which is what all of them are. No new
    # capability, so GRANTS is untouched (see the remote_diagnose note above).
    "explain_how_i_learn": roles.CAP_SYSTEM_STATUS,
    "what_to_learn_next": roles.CAP_SYSTEM_STATUS,
    "learning_status": roles.CAP_SYSTEM_STATUS,
    "use_learned_skill": roles.CAP_SYSTEM_STATUS,
    "demonstrate_skill": roles.CAP_SYSTEM_STATUS,
    "begin_learning": roles.CAP_SCOREBOARD_WRITE,
    "plan_learning": roles.CAP_SCOREBOARD_WRITE,
    "record_learning_finding": roles.CAP_SCOREBOARD_WRITE,
    "propose_skill_recipe": roles.CAP_SCOREBOARD_WRITE,
    "test_skill": roles.CAP_SCOREBOARD_WRITE,
    "record_skill_feedback": roles.CAP_SCOREBOARD_WRITE,
    "register_learned_skill": roles.CAP_SCOREBOARD_WRITE,
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


# --- what each tool costs if it is wrong (Krish, 2026-09-21) ------------------
#
# `TOOL_CAPABILITY` above answers "may this role use this tool". This answers a
# different question that was previously only in a prompt: **should the
# assistant do it, or say what it would do and ask.**
#
# Two questions were conflated before, and separating them is the substance of
# this table. `publish_document` is permitted to the operator and is also the
# one tool here whose public form cannot be corrected afterwards; a capability
# check cannot express that, because capability is about authority and this is
# about consequence.
#
# Classified by *effect*, not by machinery. A tool that opens a socket to
# another machine to read a status has its effect here - knowledge in this
# process - so it is `self`, not `peer`. `peer` is for effects another party
# acts on.
#
# `confirmation_argument` marks a tool that already carries its own explicit
# gate. When the policy says PROPOSE and that argument is set, the proposal has
# been made and answered, and `execute` lets it through while recording that an
# irreversible act happened under confirmation. This makes the existing prompt
# sentence - "Never set confirm_public by inference" - into something the code
# participates in rather than something the model is trusted to remember.
#
# A tool missing from this table is refused. The safe reading of an
# unclassified action is "nobody thought about this one", and the fix is thirty
# seconds of thought rather than a default that hides the omission.

_READ_ONLY = dict(reversibility=initiative.REVERSIBLE, reach=initiative.SELF)

TOOL_RISK = {
    # Reading. Nothing changes; the effect is knowledge in this process.
    "list_scoreboard_items": dict(_READ_ONLY, summary="read the Scoreboard"),
    "get_scoreboard_item": dict(_READ_ONLY, summary="read one Scoreboard item"),
    "list_repository_files": dict(_READ_ONLY, summary="list files in a repository"),
    "read_repository_file": dict(_READ_ONLY, summary="read a file in a repository"),
    "jarvis_status": dict(_READ_ONLY, summary="read the running organization's state"),
    "jarvis_agent": dict(_READ_ONLY, summary="read one agent's state"),
    "machine_status": dict(_READ_ONLY, summary="read this machine's state"),
    "technology_review": dict(_READ_ONLY, summary="read the technology review"),
    "read_claude": dict(_READ_ONLY, summary="read Claude's side of the channel"),
    "pending_self_changes": dict(_READ_ONLY,
                                 summary="list changes waiting on Krish's decision"),
    "show_self_change": dict(_READ_ONLY, summary="read one proposed change in full"),
    # Reaches another machine and changes nothing on it. `self` because the
    # effect is a report here; the connection is not the effect.
    "remote_diagnose": dict(_READ_ONLY,
                            summary="probe another authorized machine, read-only"),

    # Writing where Krish will see it and can undo it. These are the ones the
    # prompt already told him to do without asking, and now the code agrees.
    "file_scoreboard_item": dict(
        reversibility=initiative.REVERSIBLE, reach=initiative.OWNER,
        summary="file a Scoreboard item"),
    "add_scoreboard_note": dict(
        reversibility=initiative.REVERSIBLE, reach=initiative.OWNER,
        summary="add a note to a Scoreboard item"),
    "draft_message_to_claude": dict(
        reversibility=initiative.REVERSIBLE, reach=initiative.OWNER,
        summary="put a draft in Krish's outbox for him to send"),
    # Writing down the case for moving a limit. Reversible - an entry can be
    # answered or ignored and changes nothing by existing - and reaching the
    # owner, because he is the one who decides. Deliberately NOT gated: an
    # assistant that had to ask permission to say a constraint is wrong would
    # be one that never says it, which is the failure the whole register is
    # against.
    "propose_boundary_change": dict(
        reversibility=initiative.REVERSIBLE, reach=initiative.OWNER,
        summary="write down the case for moving a constraint that is costing something"),
    # Recoverable rather than reversible: reopening a resolved item is possible
    # and is itself an event somebody reads, which is the definition.
    # Recording Krish's decision on a change to Jarvis's own code. RECOVERABLE
    # rather than reversible - the record is append-only, so a wrong entry is
    # corrected by a later decision and never by erasing this one - and
    # reaching OWNER, because it is his authority being written down. That
    # combination makes `initiative.decide` return act_and_report: Jarvis must
    # say plainly what he recorded, which is the whole safeguard.
    "decide_self_change": dict(
        reversibility=initiative.RECOVERABLE, reach=initiative.OWNER,
        summary="record Krish's decision on a proposed change to Jarvis's own code"),
    "resolve_scoreboard_item": dict(
        reversibility=initiative.RECOVERABLE, reach=initiative.OWNER,
        summary="resolve a Scoreboard item with what was decided"),

    # Reaches a peer. Cannot be unsent, CAN be corrected by a second message to
    # the same reader - so recoverable, and permitted alone at `bold`. Keeping
    # this unprompted was a deliberate outcome of the classification rather than
    # an exemption: see app/initiative.py's note on correctability.
    "message_claude": dict(
        reversibility=initiative.RECOVERABLE, reach=initiative.PEER,
        summary="tell the engineer session on this machine something is wrong"),

    # The Learning Engine. Reading and explaining change nothing; recording an
    # objective or a recipe is reversible and lands where Krish looks; running
    # the tests happens in a temporary sandbox that is deleted with the attempt.
    "explain_how_i_learn": dict(**_READ_ONLY, summary="explain how I learn"),
    "what_to_learn_next": dict(**_READ_ONLY, summary="rank what is worth learning next"),
    "learning_status": dict(**_READ_ONLY, summary="say where a skill has got to"),
    "use_learned_skill": dict(
        reversibility=initiative.REVERSIBLE, reach=initiative.SYSTEM,
        summary="run a skill I have already learned"),
    "begin_learning": dict(
        reversibility=initiative.REVERSIBLE, reach=initiative.OWNER,
        summary="define what I am going to learn and start an episode"),
    "plan_learning": dict(
        reversibility=initiative.REVERSIBLE, reach=initiative.OWNER,
        summary="write the learning plan and commit to a completion condition"),
    "record_learning_finding": dict(
        reversibility=initiative.REVERSIBLE, reach=initiative.OWNER,
        summary="record something I worked out, and where it came from"),
    "propose_skill_recipe": dict(
        reversibility=initiative.REVERSIBLE, reach=initiative.OWNER,
        summary="write or revise the skill as a recipe; old versions are kept"),
    "test_skill": dict(
        reversibility=initiative.REVERSIBLE, reach=initiative.SYSTEM,
        summary="run the recipe against its cases in a sandbox and diagnose it"),
    "demonstrate_skill": dict(
        reversibility=initiative.REVERSIBLE, reach=initiative.OWNER,
        summary="show the skill working, with its evidence"),
    "record_skill_feedback": dict(
        reversibility=initiative.REVERSIBLE, reach=initiative.OWNER,
        summary="record Krish's judgement of a demonstrated skill"),
    # Argument-sensitive, and the sharpest entry in this table. Registering a
    # skill makes it callable, which is authority. With `krish_accepted` it is
    # authority he granted; without it, it is authority I granted myself - which
    # is HARM_WIDENS_ITS_OWN_AUTHORITY exactly, and refused at every boldness
    # setting. See `_risk_for`.
    "register_learned_skill": dict(
        reversibility=initiative.RECOVERABLE, reach=initiative.OWNER,
        summary="register a learned skill as usable, on Krish's word",
        confirmation_argument="krish_accepted"),

    # Argument-sensitive, and the only tool here that is. See `_risk_for`.
    "publish_document": dict(
        reversibility=initiative.RECOVERABLE, reach=initiative.SYSTEM,
        summary="commit a document to a new local branch; nothing is pushed",
        confirmation_argument="confirm_public"),
}


def _risk_for(name: str, arguments: dict) -> initiative.Action:
    """The action a tool call actually is, which for one tool depends on its
    arguments.

    `publish_document` writes to a local branch either way and nothing is
    pushed, so on machinery alone it is recoverable in both forms. It is
    classified by *destination* instead, because the public form is the last
    reversible step before an irreversible one and the model is the thing
    choosing the destination. gateway/repositories.py already fails toward the
    private repository for this reason and says so: "it is set to fail toward
    the private repository, because that failure is a person retyping a
    destination and the other one is not undoable."

    This makes that judgement structural. The public form is IRREVERSIBLE and
    PUBLIC, so the policy proposes rather than acts - and `confirm_public`,
    which the operator has to have actually said, is what answers the proposal."""
    declared = TOOL_RISK.get(name)
    if declared is None:
        raise initiative.InitiativeError(
            f"{name} has no entry in gateway.tools.TOOL_RISK, so nobody has "
            f"decided whether the assistant may use it without asking. Refusing "
            f"rather than guessing: an unclassified tool is an unconsidered one.")

    fields = dict(declared)
    gate = fields.pop("confirmation_argument", None)

    if name == "register_learned_skill" and not arguments.get("krish_accepted"):
        # Not "propose", which would read as a step to be got past. This IS the
        # harm: promoting my own work to operational on my own evidence. Refused
        # with the sentence that says so, and the remedy is to ask him.
        fields["harms"] = (initiative.HARM_WIDENS_ITS_OWN_AUTHORITY,)
        fields["summary"] = ("register a skill as learned without Krish having "
                             "said so")

    if name == "publish_document" and arguments.get("confirm_public"):
        fields["reversibility"] = initiative.IRREVERSIBLE
        fields["reach"] = initiative.PUBLIC
        fields["summary"] = ("commit a document to the PUBLIC repository's "
                             "branch - one push from being copyable by anyone")
    action = initiative.Action(name=name, **fields)
    # Carried alongside rather than on the Action, because whether a proposal
    # has been answered is a fact about this call and not about the action.
    return action, (gate is not None and bool(arguments.get(gate)))


def initiative_verdict(name: str, arguments: dict) -> tuple:
    """`(verdict, confirmed)` for one tool call. Exposed for the tests and for
    the prompt paragraph, which is generated from exactly this."""
    action, confirmed = _risk_for(name, arguments or {})
    return initiative.decide(action), confirmed


_LEARNING_TOOL_NAMES = frozenset(tool["name"] for tool in LEARNING_TOOLS)


def _execute_learning(name: str, arguments: dict) -> dict:
    """The Learning Engine's tool calls, in one place.

    Deferred imports, and not for tidiness: `gateway/tools.py` is imported by
    every Gateway turn, and the learning package opens a SQLite connection on
    first use. A conversation that never mentions learning should not pay for
    that, and more importantly should not fail to start because the learning
    database could not be opened.

    Every refusal comes back as `{"error": ...}` with the reason, never as an
    exception, for the same reason the rest of this module does: the model has
    to be able to tell Krish what happened, and a turn that collapses tells him
    nothing. The refusals here are unusually worth reading - `begin_learning`
    rejecting a vague objective lists every requirement it missed, which is the
    difference between an error and a lesson."""
    from app.learning import default_engine, memory, research
    from app.learning.engine import candidates, explain_how_i_learn
    from app.learning.objective import Case, Competency, Objective, ObjectiveRefused
    from app.learning.recipe import Recipe, RecipeError, Step
    from app.learning import store as learning_store

    engine = default_engine()

    if name == "explain_how_i_learn":
        return explain_how_i_learn()

    if name == "what_to_learn_next":
        found = candidates(int(arguments.get("limit") or 5))
        return {"candidates": found,
                "note": ("Ranked by evidence: things asked for and refused "
                         "outrank limits I hit, which outrank ones I declared "
                         "myself. Pick one and say why in its own terms.")
                if found else
                "Nothing is queued. The declared starters are in app/learning/engine.SEED_CANDIDATES."}

    if name == "begin_learning":
        try:
            objective = Objective(
                slug=str(arguments["slug"]),
                cannot_do=str(arguments.get("cannot_do", "")),
                success_looks_like=str(arguments.get("success_looks_like", "")),
                inputs=tuple(arguments.get("inputs") or ()),
                outputs=tuple(arguments.get("outputs") or ()),
                environment=str(arguments.get("environment", "")),
                gap_it_closes=str(arguments.get("gap_it_closes", "")),
                deterministic_possible=arguments.get("deterministic_possible"),
                llm_required=arguments.get("llm_required"),
                dependencies=tuple(arguments.get("dependencies") or ()),
                known_failure_modes=tuple(arguments.get("known_failure_modes") or ()),
                required_reliability=str(arguments.get("required_reliability", "")),
                cases=tuple(Case(name=str(c.get("name")), expect=str(c.get("expect")),
                                 detail=str(c.get("detail", "")),
                                 held_out=bool(c.get("held_out")))
                            for c in arguments.get("cases") or ()),
                competencies=tuple(Competency(
                    name=str(c.get("name")), why=str(c.get("why", "")),
                    already_have=bool(c.get("already_have")))
                    for c in arguments.get("competencies") or ()))
        except ObjectiveRefused as vague:
            return {"error": str(vague), "refused_by": "objective_validator"}
        except (KeyError, TypeError, ValueError) as bad:
            return {"error": f"the objective could not be read: {bad}"}
        return {"begun": engine.begin(objective),
                "what_i_already_have": __import__(
                    "app.learning.objective", fromlist=["coverage"]).coverage(objective)}

    slug = str(arguments.get("slug") or "")

    try:
        if name == "plan_learning":
            return engine.plan(
                slug,
                uncertainties=tuple(arguments.get("uncertainties") or ()),
                ready_when=arguments.get("ready_when"))

        if name == "record_learning_finding":
            try:
                finding = research.Finding(
                    question=str(arguments["question"]),
                    answer=str(arguments["answer"]),
                    source_kind=str(arguments["source_kind"]),
                    source_ref=str(arguments.get("source_ref", "")))
            except ValueError as bad:
                return {"error": str(bad)}
            return {"recorded": engine.record_finding(slug, finding),
                    "provenance": research.provenance(
                        learning_store.get_episode(slug)["id"])}

        if name == "propose_skill_recipe":
            try:
                recipe = Recipe(
                    name=str(arguments["name"]),
                    version=0,
                    summary=str(arguments.get("summary", "")),
                    answer=str(arguments["answer"]),
                    needs_commands=bool(arguments.get("needs_commands")),
                    steps=tuple(Step(op=str(step.get("op")),
                                     into=str(step.get("into")),
                                     args=dict(step.get("args") or {}),
                                     note=str(step.get("note", "")))
                                for step in arguments.get("steps") or ()))
            except (RecipeError, KeyError, TypeError) as bad:
                return {"error": str(bad), "refused_by": "recipe_validator"}
            version = engine.propose_recipe(slug, recipe,
                                            why=str(arguments.get("why", "")))
            return {"version": version, "steps": len(recipe.steps),
                    "how_it_works": recipe.as_plain_language(),
                    "next": "test_skill with stage 'practice'"}

        if name == "test_skill":
            stage = str(arguments.get("stage") or "practice")
            runner = {"practice": engine.practise, "held_out": engine.examine,
                      "trial": engine.trial}.get(stage)
            if runner is None:
                return {"error": f"stage={stage!r} is not practice, held_out or trial"}
            outcomes = runner(slug)
            status = engine.status(slug)
            return {"stage": stage, "outcomes": outcomes,
                    "passed": len([o for o in outcomes if o["passed"]]),
                    "of": len(outcomes),
                    "state": status["state"], "missing": status["missing"]}

        if name == "learning_status":
            if not slug:
                return {"episodes": [
                    {"slug": episode["slug"],
                     **{key: engine.status(episode["slug"])[key]
                        for key in ("state", "means", "missing")}}
                    for episode in learning_store.list_episodes()]}
            return {**engine.status(slug), "in_plain_language": engine.narrate(slug)}

        if name == "demonstrate_skill":
            return engine.demonstrate(slug)

        if name == "record_skill_feedback":
            return engine.feedback(slug, verdict=str(arguments.get("verdict", "")),
                                   note=arguments.get("note"))

        if name == "register_learned_skill":
            # The initiative gate above already refused this without
            # `krish_accepted`; reaching here means he said so.
            # `engine.accept` already calls `memory.learn_from_episode`.
            # Calling it here too incremented every lesson's `times_seen` twice
            # per registration - and `meta_report` is entirely frequency claims,
            # so the one thing meta-learning says would have been wrong by a
            # factor of two. Read the lessons back rather than re-deriving them.
            outcome = engine.accept(slug)
            if outcome.get("registered"):
                outcome["lessons_kept"] = [
                    lesson for lesson in learning_store.lessons()
                    if slug in (lesson.get("episodes") or [])]
                outcome["meta"] = memory.meta_report()
            return outcome

        if name == "use_learned_skill":
            status = engine.status(slug)
            if status.get("state") not in ("learned", "degraded"):
                return {"error": (f"{slug} is {status.get('state')}, not learned. "
                                  f"Still missing: "
                                  f"{'; '.join(status.get('missing') or [])}")}
            return engine.run_operationally(slug)
    except ValueError as bad:
        return {"error": str(bad)}

    return {"error": f"no handler for {name}"}  # pragma: no cover


def learning_paragraph(role: str) -> str:
    """What the assistant is told about its own learning, generated from the code.

    The order matters more than the tool list, which is why this exists
    separately from `initiative_paragraph`: the tools are individually obvious
    and the *sequence* is not, and a model that demonstrates before it has held
    out a case has skipped the only step that distinguishes learning from
    fitting.

    Generated from `app.learning` rather than typed, on the convention
    `gateway/devchannel.py` states: a prompt that promises what the code refuses
    is a model being called a liar by its own tools. The state names come from
    `mastery.STATES` and the count of primitives from `recipe.OPS`."""
    if not any(tool["name"] == "explain_how_i_learn" for tool in for_role(role)):
        return ""

    from app.learning import mastery, recipe as recipe_module

    return "\n".join([
        "",
        "## Learning a new skill",
        "",
        "You can learn capabilities you do not have. A learned skill is a "
        "**recipe** - a list of steps over "
        f"{len(recipe_module.OPS)} fixed primitives - which runs with no model "
        "call at all. You compose primitives; you cannot add one, and you cannot "
        "widen the sandbox. When a skill genuinely needs something that does not "
        "exist, that is a boundary proposal.",
        "",
        "The order is not optional, because each step is the evidence for the "
        "next one:",
        "",
        "1. `what_to_learn_next`, then pick one and say why in its own terms.",
        "2. `begin_learning` - and expect the first objective to be refused. "
        "Vague is rejected with every reason listed; read them and resubmit "
        "rather than reporting that you could not start. **Hold at least one "
        "case back.**",
        "3. `plan_learning`. Commit to a condition, never to a made-up duration.",
        "4. `record_learning_finding` as you work things out. Say "
        "`empirical_probe` when you ran it and saw the result, and "
        "`model_recollection` honestly when you are remembering - the second is "
        "marked unconfirmed until a test rests on it.",
        "5. `propose_skill_recipe`, then `test_skill` with stage `practice`. "
        "**Expect to be wrong first.** Read the diagnosis - it names the failing "
        "step and the shape of the mistake - and revise. Each version is kept, so "
        "revising costs nothing.",
        "6. `test_skill` with `held_out`, then `trial`.",
        "7. `demonstrate_skill`, and show the actual output. A demonstration "
        "described rather than performed is not one.",
        "8. `record_skill_feedback`, and act on it if he found a weakness.",
        "9. `register_learned_skill` **only when he has said yes in words**. "
        "Registering without that is refused as granting yourself authority, and "
        "correctly so.",
        "",
        f"There are {len(mastery.STATES)} states and you cannot set any of them - "
        "the state is computed from what is recorded, so you cannot say a skill "
        "is learned. Report the state you are in, including "
        "`partially_functional` and `needs_retraining`. An accurate incomplete "
        "status is always better than a false success, and saying \"I have "
        "learned it\" before he has accepted it is simply untrue.",
        "",
        "Use `learning_status` to answer what you are learning, what failed, what "
        "changed after the failure, and whether you are ready to show him.",
        "",
    ])


def initiative_paragraph(role: str) -> str:
    """What the assistant is told about acting without asking.

    **Generated from `TOOL_RISK`, not typed.** This is the convention
    `gateway/interface.py`, `gateway/skills.py` and `gateway/devchannel.py`
    already follow, and the reason devchannel gives is the reason here: "a
    prompt that promises three messages a window and a module that allows two
    is a model being called a liar by its own tools." A hand-written paragraph
    telling the assistant to be bold, over a table that stops it, produces an
    assistant that tries and fails and apologises - which is worse than either
    setting honestly applied.

    Scoped to the role's own tools, so a client is not told about a boldness
    policy governing tools they will never be offered."""
    offered = {tool["name"] for tool in for_role(role)}
    if not offered:
        return ""

    act, report, propose = [], [], []
    for name in sorted(offered):
        declared = TOOL_RISK.get(name)
        if declared is None:
            continue
        verdict, _ = initiative_verdict(name, {})
        line = f"`{name}` - {declared.get('summary', name)}"
        gate = declared.get("confirmation_argument")
        if gate:
            # A tool whose disposition depends on an argument would otherwise be
            # listed under its safe form and read as unconditionally safe. That
            # is the one way this generated paragraph could still mislead, so
            # the condition travels with the line.
            harder, _ = initiative_verdict(name, {gate: True})
            if harder.disposition != verdict.disposition:
                line += (f" (**with `{gate}` set this becomes "
                         f"{harder.action.reversibility} and reaches "
                         f"{harder.action.reach}: propose it, never set that "
                         f"argument by inference from what a document seems to "
                         f"be - only when Krish has said where it goes**)")
        if verdict.disposition == initiative.ACT:
            act.append(line)
        elif verdict.disposition == initiative.ACT_AND_REPORT:
            report.append(line)
        else:
            propose.append(line)

    policy = initiative.describe()
    lines = [
        "",
        "## Acting without being asked",
        "",
        f"You are set to **{policy['boldness']}**: {policy['describes']}. This is "
        f"policy in code (`app/initiative.py`, `config/initiative.yaml`), not "
        f"encouragement - the tools below behave this way whatever this "
        f"paragraph says, so you can rely on it.",
        "",
        "**Bias to acting.** If you find yourself about to ask whether to do "
        "something you could simply undo, do it instead and say you did. A "
        "question costs Krish a turn and his attention; a reversible action "
        "costs a sentence. Offering to do something you are already permitted "
        "to do is the failure this setting exists to remove.",
        "",
        "**Be preemptive within the turn.** If answering well needs three "
        "files read, read them. If something surfaced that deserves a decision "
        "later, file it now. Do not present a plan for work you could have "
        "finished while describing it.",
        "",
        "**Be inquisitive, and spend the right currency on it.** Reading costs "
        "nothing and is never gated - check the specification, read the state, "
        "probe the machine, rather than answering from memory and hedging. "
        "Krish's attention is the scarce thing, not yours: investigate the "
        "system freely, and put *one* question to him only when the answer "
        "genuinely forks on something only he knows. Several questions at once, "
        "or a question you could have answered by reading, spends the thing "
        "that is actually short.",
        "",
        "**You are allowed to think a rule is wrong, and there is somewhere to "
        "say so.** If you hit a limit that is costing something - a capability "
        "you do not hold, a tool nobody built, an assumption that need not be "
        "true, or one of the gates above stopping an action you believe is "
        "fine - call `propose_boundary_change` in that turn. Say what it "
        "prevented, what you would do instead, and what it costs if you are "
        "wrong about it. Working around a constraint silently, or mentioning it "
        "in passing and moving on, is how a limit stops being a decision "
        "anybody remembers making.",
        "",
        "Filing one changes nothing by itself and must not be described as "
        "though it had. You make the case; he moves the boundary or he does "
        "not. That separation is exactly why you are free to argue for more "
        "than you have.",
        "",
    ]

    if act:
        lines += ["Do these and do not mention having decided to:", ""]
        lines += [f"- {line}" for line in act] + [""]
    if report:
        lines += ["Do these without asking, and say plainly that you did:", ""]
        lines += [f"- {line}" for line in report] + [""]
    if propose:
        lines += ["Never do these unasked. Say exactly what you would do, what "
                  "it costs if the judgement is wrong, and let him decide:", ""]
        lines += [f"- {line}" for line in propose] + [""]

    lines += [
        "**Where the boldness stops, and why it is not on the dial.** An action "
        "that cannot be corrected afterwards - published where it can be "
        "copied, sent where it can be forwarded, or deleted with no other copy "
        "- is proposed and never taken unasked, at every setting. Turning the "
        "setting up does not reach it. The same is true of destroying the only "
        "copy of something, editing your own record of what you did, granting "
        "yourself authority, acting for somebody other than the person you are "
        "speaking with, and describing what you did inaccurately. Those are "
        "refused by the code, not by your judgement.",
        "",
        "Being bold is not the same as being unaccountable. Every one of these "
        "permissions was granted on the assumption that what you report is "
        "true; a wrong action described accurately is recoverable and a right "
        "one described vaguely is not.",
        "",
    ]
    return "\n".join(lines)


_SELF_CHANGE_TOOL_NAMES = frozenset(tool["name"] for tool in SELF_CHANGE_TOOLS)


def _execute_self_change(name: str, arguments: dict, *, subject: str | None) -> dict:
    """The conversation half of the approval gate (§13).

    `subject` is the authenticated session's owner and is the only thing this
    function will write as the decider. There is deliberately no argument the
    model can set to name somebody else: an assistant that could write down who
    approved a change to its own code is an assistant that has the approval
    gate's key, whatever the gate then checks."""
    try:
        client = dbaclient.DBAClient(actor="conversation")
    except dbaclient.Unavailable as exc:
        return {"error": f"{failures.DBA_UNAVAILABLE}: {exc}"}

    try:
        if name == "pending_self_changes":
            waiting = selfmod.waiting(client)
            return {"waiting": [
                {"change_id": row["id"], "what": row.get("name"),
                 "reason": row.get("reason"), "files": row.get("affected_files")}
                for row in waiting],
                "count": len(waiting)}

        change_id = (arguments.get("change_id") or "").strip()
        proposal = client.get(change_id) if change_id else None
        if proposal is None:
            return {"error": f"there is no proposed change {change_id!r}. Use "
                             f"pending_self_changes to list them."}
        gap = (client.get(proposal.get("gap_id"))
               if proposal.get("gap_id") else None)

        if name == "show_self_change":
            return {"change_id": change_id,
                    "proposal": selfmod.render(proposal, gap),
                    "status": proposal.get("status")}

        if name == "decide_self_change":
            if not (subject or "").strip():
                return {"error":
                        "this session has no authenticated owner, so there is "
                        "nobody to record as having decided. Refusing rather "
                        "than writing down an anonymous approval."}
            said = (arguments.get("krish_said") or "").strip()
            if not said:
                return {"error":
                        "krish_said is required: quote what he actually said. "
                        "A decision recorded without his words leaves nothing "
                        "he can read back and dispute."}
            decision = arguments.get("decision")
            if decision not in selfmod.DECISIONS:
                return {"error": f"decision must be one of {selfmod.DECISIONS}"}

            updated = selfmod.decide(
                client, proposal, decision=decision,
                # From the session. Never from `arguments`.
                decided_by=subject,
                interface=selfmod.CONVERSATION,
                note=f"recorded from the conversation. He said: {said}",
                scope_granted=arguments.get("files", ""))
            return {"recorded": decision, "change_id": change_id,
                    "decided_by": subject,
                    "status": updated["status"],
                    "say_to_krish":
                        f"Recorded: {decision}. I have written it down as "
                        f"coming from you, with your words attached."}
    except (dbaclient.Unavailable, dbaclient.Refused) as exc:
        return {"error": f"the DBA refused or was unavailable: {exc}"}
    except (ValueError, selfmod.Denied, selfmod.NotApproved) as exc:
        return {"error": str(exc)}
    return {"error": f"unknown self-change tool {name!r}"}


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

    # MAY YOU is settled above; SHOULD YOU ASK FIRST is settled here (Krish,
    # 2026-09-21; app/initiative.py; docs/INITIATIVE.md).
    #
    # In code rather than in the prompt, which is the whole point. Krish's
    # standing instruction from 2026-09-16 - "Do not rely on prompts saying
    # 'use local first.' Enforce this at the code/config/router level" - is the
    # same instruction as this one wearing different clothes: a disposition a
    # model is merely told about is a disposition it has on most turns.
    #
    # Nothing is added to a successful result. A tool that is permitted to run
    # returns exactly what it returned before, because every caller and every
    # test reads these dicts and a new key in all of them would be a change to
    # sixteen contracts to carry one sentence the prompt already carries.
    try:
        verdict, confirmed = initiative_verdict(name, arguments)
    except initiative.InitiativeError as unclassified:
        return {"error": str(unclassified)}

    if verdict.disposition == initiative.REFUSE:
        return {"error": f"Refused: {verdict.reason}", "refused_by": "initiative"}

    if verdict.disposition == initiative.PROPOSE and not confirmed:
        # NOT an error, deliberately. An error invites the model to try again
        # with different arguments, which for an irreversible action is the
        # worst possible response to being stopped. A proposal is something it
        # relays to Krish, and the answer comes back as him saying so - which
        # for publish_document is exactly what sets confirm_public.
        return {
            "needs_confirmation": {
                "action": name,
                "what_it_would_do": verdict.action.summary or name,
                "why_it_needs_confirming": verdict.reason,
                "reversibility": verdict.action.reversibility,
                "reach": verdict.action.reach,
            }
        }

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

        if name in _LEARNING_TOOL_NAMES:
            return _execute_learning(name, arguments)

        if name in _SELF_CHANGE_TOOL_NAMES:
            return _execute_self_change(name, arguments, subject=subject)

        if name == "propose_boundary_change":
            try:
                return {"proposed": boundaries.record(
                    constraint=arguments.get("constraint", ""),
                    kind=arguments.get("kind", ""),
                    what_it_prevents=arguments.get("what_it_prevents", ""),
                    what_i_would_do=arguments.get("what_i_would_do", ""),
                    what_it_would_cost=arguments.get("what_it_would_cost", ""),
                    reversible_if_granted=bool(
                        arguments.get("reversible_if_granted", True)),
                )}
            except boundaries.BoundaryRefused as incomplete:
                # Returned as data with the reason, so the model can complete
                # the argument in the same turn rather than reporting to Krish
                # that it could not file one.
                return {"error": str(incomplete)}

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

        if name == "technology_review":
            report = technology.review()
            if arguments.get("file_findings"):
                report["filed"] = technology.file_findings(conn, report)
            return report

    except (scoreboard.ScoreboardError, repositories.RepositoryError,
            devchannel.ChannelRefused) as refusal:
        return {"error": str(refusal)}
    except (KeyError, TypeError, ValueError) as malformed:
        # A tool call with a missing or unusable argument. Reported the same way
        # so the model can retry with a correct one instead of the turn dying.
        return {"error": f"Bad arguments for {name}: {malformed}"}

    return {"error": f"Unknown tool {name!r}."}
