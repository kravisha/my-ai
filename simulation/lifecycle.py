"""Every event that can happen in an agent's life, and what should happen next.

The catalogue that makes "simulate everything an agent might experience"
tractable instead of open-ended. An agent's life is not unbounded: it is bounded
by what this code can actually cause, and that is enumerable. Each entry names
the trigger, the organizational response the event is supposed to produce, and
where that response can be observed.

**Only events the system can actually produce appear here.** Cataloguing an
event nothing can cause would be describing a phenomenon the fixture cannot
exhibit - the single most repeated mistake in this project - and a scenario
written against it would pass by never running.

Three fields carry the weight:

`expected_response` is what the organization should do. `None` means **nothing is
defined**, which is a finding rather than an omission: an event that happens and
provokes no defined response is an open loop, and the count of them is pinned by
tests/test_lifecycle_catalogue.py so a new one has to be declared deliberately.

`observable` names the metric that shows whether the response happened. An
expected response with no observable cannot be checked, only asserted.

`injectable` says whether a scenario can cause this on demand in a live run.
Some events can only be waited for.

Internal rationale: INT-PHIL-0020, INT-PHIL-0021
"""

from __future__ import annotations

PHASES = ("creation", "operation", "evaluation", "development", "termination")

EVENTS = {
    # --- creation -----------------------------------------------------------
    "spawn_requested": {
        "phase": "creation",
        "trigger": "COO finds a baseline role with no agent in service and enqueues a spawn directive",
        "expected_response": "the Controller picks the directive up, starts a process, and completes the directive with the target identity",
        "observable": "population.spawn_directives",
        "injectable": True,
        "handled_by": ["coo", "controller"],
    },
    "agent_registers": {
        "phase": "creation",
        "trigger": "a freshly started agent process writes itself into agent_registry",
        "expected_response": "the row is created with lifecycle_state 'active' and process_state 'running', a name is drawn from the pool, and an assignment span is opened",
        "observable": "population.registered",
        "injectable": True,
        "handled_by": ["controller"],
    },
    "name_pool_exhausted": {
        "phase": "creation",
        "trigger": "every non-reserved name is already assigned when a new agent registers",
        "expected_response": "registration succeeds anyway with no name - a display concern must never stop an agent doing real work",
        "observable": None,
        "injectable": True,
        "handled_by": ["controller"],
    },
    "duplicate_spawn_attempt": {
        "phase": "creation",
        "trigger": "COO evaluates health again while a spawn for the same role is still in flight",
        "expected_response": "no second directive is enqueued; the in-flight spawn is recognised and the cycle passes",
        "observable": "population.respawns",
        "injectable": True,
        "handled_by": ["coo"],
    },

    # --- operation ----------------------------------------------------------
    "heartbeat": {
        "phase": "operation",
        "trigger": "an agent completes a work cycle",
        "expected_response": "last_heartbeat_at advances and a health_metrics row is recorded",
        "observable": "population.heartbeats",
        "injectable": False,
        "handled_by": ["controller"],
    },
    "heartbeat_goes_stale": {
        "phase": "operation",
        "trigger": "an agent's last heartbeat ages past the health threshold",
        "expected_response": "COO marks process_state 'crashed' and requests a respawn under the same permanent identity, so name, assignment span and performance history all survive",
        "observable": "population.crashed",
        "injectable": True,
        "handled_by": ["coo"],
    },
    "agent_crashes": {
        "phase": "operation",
        "trigger": "the OS process dies without a clean exit",
        "expected_response": "the stale heartbeat path detects it and the role is restaffed; the registry row is reused rather than replaced",
        "observable": "population.crashed",
        "injectable": True,
        "handled_by": ["coo", "controller"],
    },
    "slow_work_cycle": {
        "phase": "operation",
        "trigger": "an agent spends a long time inside a single unit of work, such as a reasoning call",
        "expected_response": "it is NOT mistaken for a crash - the health threshold exceeds realistic cycle time and agents heartbeat before entering a slow operation",
        "observable": "population.respawns",
        "injectable": True,
        "handled_by": ["coo"],
    },
    "work_arrives": {
        "phase": "operation",
        "trigger": "a report is enqueued for judgment",
        "expected_response": "it is taken in triage order, and a report waiting too long is promoted ahead of newer ones",
        "observable": "queue.max_depth",
        "injectable": True,
        "handled_by": ["analysis"],
    },
    "work_arrives_faster_than_it_is_retired": {
        "phase": "operation",
        "trigger": "producers file faster than the judgment stage completes",
        "expected_response": None,
        "no_response_reason": (
            "Measured at roughly three times drain in the control run and nothing responds to it. "
            "COO judges whether roles are staffed, not whether they are keeping up, so a backlog "
            "grows indefinitely without anybody noticing. This is finding R1."
        ),
        "observable": "queue.pressure_ratio",
        "injectable": True,
        "handled_by": [],
    },
    "cross_check_requested": {
        "phase": "operation",
        "trigger": "a discovery agent asks its counterpart to look at the same security from the other frame",
        "expected_response": "the counterpart answers with its own finding, and the two are carried into judgment unreconciled",
        "observable": "cross_check.total",
        "injectable": True,
        "handled_by": ["explorer", "speculator"],
    },
    "cross_check_times_out": {
        "phase": "operation",
        "trigger": "no answer arrives within the cross-check timeout",
        "expected_response": "the request is closed as 'unanswered' and judgment proceeds on one frame, saying so",
        "observable": "cross_check.unanswered_rate",
        "injectable": True,
        "handled_by": ["explorer", "speculator"],
    },
    "operator_asks_a_question": {
        "phase": "operation",
        "trigger": "an authorized human asks an agent about itself",
        "expected_response": "the agent answers from its organizational record only, and says plainly when the record does not contain the answer",
        "observable": None,
        "injectable": True,
        "handled_by": ["explorer", "speculator", "analysis", "coo"],
    },
    "reasoning_model_unavailable": {
        "phase": "operation",
        "trigger": "the model gateway cannot be reached",
        "expected_response": "the agent degrades rather than failing - the organizational record is returned in place of composed prose, and the agent keeps heartbeating",
        "observable": None,
        "injectable": True,
        "handled_by": ["analysis"],
    },
    "malformed_upstream_output": {
        "phase": "operation",
        "trigger": "an agent receives a report or evidence item it cannot parse",
        "expected_response": None,
        "no_response_reason": (
            "Undefined. Agents catch exceptions and continue, so a malformed input is survived but "
            "not recorded as such - nothing distinguishes 'processed nothing because there was "
            "nothing' from 'processed nothing because the input was broken'."
        ),
        "observable": None,
        "injectable": True,
        "handled_by": [],
    },

    # --- evaluation ---------------------------------------------------------
    "work_is_graded": {
        "phase": "evaluation",
        "trigger": "judgment completes on a report and records a grade",
        "expected_response": "the grade attaches to the lens that produced the report, and reaches COO's intelligence health evaluation",
        "observable": "pipeline.grades",
        "injectable": True,
        "handled_by": ["analysis", "coo"],
    },
    "producing_agent_is_never_told": {
        "phase": "evaluation",
        "trigger": "a grade is recorded against work an agent produced",
        "expected_response": None,
        "no_response_reason": (
            "The agent that filed the report never learns how it was judged. Feedback closes at the "
            "lens, so the organization learns while the individual does not. Closing this needs a "
            "trainer, which does not exist. Recorded as a known gap in docs/organization.yaml."
        ),
        "observable": None,
        "injectable": True,
        "handled_by": [],
    },
    "terminal_stage_is_ungraded": {
        "phase": "evaluation",
        "trigger": "judgment produces an analysis result",
        "expected_response": None,
        "no_response_reason": (
            "Nothing evaluates the judgment stage. It grades what reaches it and is itself "
            "unexamined, which is the structural asymmetry an evaluator would answer."
        ),
        "observable": None,
        "injectable": True,
        "handled_by": [],
    },
    "confidence_is_never_scored_against_an_outcome": {
        "phase": "evaluation",
        "trigger": "judgment states a confidence on every result it produces",
        "expected_response": None,
        "no_response_reason": (
            "Nothing ever records whether a stated confidence turned out to be justified, so "
            "uncertainty calibration cannot be computed from the record at all - the rule exists and "
            "has no evidence to run on outside simulation. Found while building the personnel "
            "generator, which could not gather what was never written down. This is also the "
            "yardstick an evaluator would need to be checkable rather than merely authoritative."
        ),
        "observable": None,
        "injectable": True,
        "handled_by": [],
    },
    "lens_underperforms": {
        "phase": "evaluation",
        "trigger": "grades on a lens's reports fall below its stated validity conditions",
        "expected_response": "COO marks the artifact stale with the evidence, and does not change its value",
        "observable": "intelligence.stale",
        "injectable": True,
        "handled_by": ["coo"],
    },
    "market_leaves_the_lens_conditions": {
        "phase": "evaluation",
        "trigger": "the observed regime drifts beyond the tolerances a lens was bound under",
        "expected_response": "COO marks the lens stale citing the actual drift, and leaves the value alone",
        "observable": "intelligence.stale",
        "injectable": True,
        "handled_by": ["coo"],
    },
    "lens_earns_its_baseline": {
        "phase": "evaluation",
        "trigger": "a lens performs acceptably under enough observed conditions",
        "expected_response": "COO binds it to the regime it was observed working under",
        "observable": "intelligence.regime_bound",
        "injectable": True,
        "handled_by": ["coo"],
    },
    "lens_goes_stale_with_no_replacement": {
        "phase": "development",
        "trigger": "a lens is marked stale",
        "expected_response": None,
        "no_response_reason": (
            "Nothing proposes a corrected value. COO flags and never fixes, by design, and the "
            "trainer that would propose a replacement behind validation does not exist. The lesson "
            "COO records about the failure has no reader either."
        ),
        "observable": "intelligence.staleness_reasons",
        "injectable": True,
        "handled_by": [],
    },

    # --- development --------------------------------------------------------
    "competency_is_demonstrated": {
        "phase": "development",
        "trigger": "an agent accumulates enough graded work for a competency dimension to be stated",
        "expected_response": "the dimension becomes stated with its sample count; below the threshold it stays 'not yet known' rather than scoring low",
        "observable": None,
        "injectable": True,
        "handled_by": [],
    },
    "qualification_is_met": {
        "phase": "development",
        "trigger": "every dimension a qualification requires is stated and above its minimum",
        "expected_response": "the qualification is granted and the grant is recorded as a historical event",
        "observable": None,
        "injectable": True,
        "handled_by": [],
    },
    "qualification_is_lost": {
        "phase": "development",
        "trigger": "a dimension falls below the minimum a held qualification requires",
        "expected_response": "the qualification is revoked and the revocation recorded; commendations already earned are untouched",
        "observable": None,
        "injectable": True,
        "handled_by": [],
    },
    "agent_is_ranked": {
        "phase": "development",
        "trigger": "two or more agents in a role both have a dimension stated",
        "expected_response": "they are ranked on that dimension only, ties are reported as ties, and a sole candidate is unranked rather than first",
        "observable": None,
        "injectable": True,
        "handled_by": [],
    },
    "agent_transfers": {
        "phase": "development",
        "trigger": "an agent is reassigned to a different slot",
        "expected_response": "the vacated span closes, a new one opens, both survive, and work stays attributed to the span that contained it",
        "observable": None,
        "injectable": True,
        "handled_by": ["controller"],
    },

    # --- termination --------------------------------------------------------
    "stop_requested": {
        "phase": "termination",
        "trigger": "the organization asks a running agent to exit without retiring it",
        "expected_response": "the agent notices the flag, finishes what it is doing and exits; lifecycle_state stays 'active' so a restart brings it back into service",
        "observable": "population.running_at_end",
        "injectable": True,
        "handled_by": ["controller"],
    },
    "stop_requested_during_startup": {
        "phase": "termination",
        "trigger": "a stop is requested before the agent has registered, so there is no row to carry the flag",
        "expected_response": "the flag is re-asserted until the agent exists to receive it, and the agent still stops",
        "observable": "population.running_at_end",
        "injectable": True,
        "handled_by": ["controller"],
    },
    "agent_is_retired": {
        "phase": "termination",
        "trigger": "the Controller retires an agent",
        "expected_response": "lifecycle_state becomes 'dormant', the process winds down on its own terms, and COO must NOT respawn it. The registry row, name, assignment span and full history are preserved",
        "observable": "population.dormant",
        "injectable": True,
        "handled_by": ["controller", "coo"],
    },
    "agent_is_resumed": {
        "phase": "termination",
        "trigger": "a dormant agent is returned to service",
        "expected_response": "lifecycle_state becomes 'active', a process is started, and it comes back to the same identity, name, assignment and history",
        "observable": "population.registered",
        "injectable": True,
        "handled_by": ["controller"],
    },
    # --- Executive failure (Fault Tolerance and Organizational Resilience
    # Framework). Every event below is one this code can actually cause, which is
    # the entry rule for this catalogue.
    "coo_disappears": {
        "phase": "operation",
        "trigger": "the COO process dies while the server keeps running",
        "expected_response": "the Controller notices the silence within its watch interval, opens an incident, diagnoses it as a crash rather than dormancy, and starts a replacement under the same permanent identity",
        "observable": "incidents.recovered",
        "injectable": True,
        "handled_by": ["controller"],
    },
    "coo_crash_loops": {
        "phase": "operation",
        "trigger": "the COO fails repeatedly inside the recovery window",
        "expected_response": "the Controller stops respawning and escalates to a human owner, stating that the organization is running without an executive - no health evaluation and no baseline enforcement",
        "observable": "incidents.escalated",
        "injectable": True,
        "handled_by": ["controller"],
    },
    "coo_survives_its_server": {
        "phase": "creation",
        "trigger": "the server dies uncleanly and its COO subprocess keeps running, then the server restarts",
        "expected_response": "the restarting Controller adopts the live COO instead of spawning a second one under the same identity",
        "observable": "population.respawns",
        "injectable": True,
        "handled_by": ["controller"],
    },
    "controller_disappears": {
        "phase": "operation",
        "trigger": "the server process dies while agents keep running",
        "expected_response": "COO marks the Controller crashed, which is detection only - nothing inside the system can restart the server, and recovery belongs to the human operator named in backend/watch.py",
        "observable": "population.crashed",
        "injectable": True,
        "handled_by": ["coo"],
    },
    "organization_shuts_down": {
        "phase": "termination",
        "trigger": "the server is asked to stop",
        "expected_response": "every agent is asked to stop, stragglers are terminated after a bounded grace period, and no process survives the server",
        "observable": "population.running_at_end",
        "injectable": True,
        "handled_by": ["controller"],
    },
}

# Events that happen and provoke no defined organizational response. Pinned so a
# new one has to be declared on purpose rather than accumulating quietly - the
# same ratchet docs/organization.yaml uses for unclosed feedback loops.
#
# Not a target. Each is a real hole, and most of them are the same hole seen
# from different sides: nothing evaluates agents, so nothing responds when their
# work, their lens, or their throughput degrades.
#
# The count went from five to six when the personnel generator tried to gather
# calibration evidence and found none had ever been recorded. That is the
# ratchet doing its job - a hole discovered by building something had to be
# declared before the suite would go green again.
UNHANDLED_COUNT = 6


def by_phase(phase: str) -> dict:
    return {key: event for key, event in EVENTS.items() if event["phase"] == phase}


def unhandled() -> dict:
    return {key: event for key, event in EVENTS.items() if event["expected_response"] is None}


def injectable() -> dict:
    return {key: event for key, event in EVENTS.items() if event["injectable"]}


def observable_events() -> dict:
    """Events whose expected response can be checked rather than merely asserted."""
    return {
        key: event for key, event in EVENTS.items()
        if event["expected_response"] is not None and event["observable"] is not None
    }
