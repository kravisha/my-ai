"""What an agent has demonstrated it can do, and what follows from that.

Pure functions over evidence someone else gathered - the same split as
`backend/novelty.py` and `backend/triage.py`, where `fi_db` runs the queries and
the judgment lives here where it can be tested without a database.

Four rules govern everything below, and each exists because of a specific way
this kind of system goes wrong.

**Absent is not zero.** A dimension with too little evidence is reported as not
stated, never as a low score. "Not yet known" and "poor" are different answers
and collapsing them would let a new agent look incompetent and a quiet one look
worse than a bad one. `source_reliability` already refuses to state a standing
below a minimum, for the same reason.

**Earned, never assigned.** Nothing here takes a prior. Every number is computed
from recorded outcomes, so the model can be wrong in a way that shows up.

**No universal score.** Dimensions are reported separately and ranking is always
*per dimension*. A single "best agent" number would hide that agents are good at
different things, and would be the first thing gamed.

**Commendations never decide anything.** They are historical memory, and the
functions that decide qualification and rank do not accept them as an argument
at all - the separation is in the signature, not in a convention someone has to
remember.

Internal rationale: INT-PHIL-0020
"""

from __future__ import annotations

# Every dimension computable from evidence the organization already records.
#
# Deliberately five rather than the fourteen an ideal competency matrix would
# carry. Communication, handoff quality, learning velocity and the rest need
# mechanisms that do not exist, and declaring a dimension that is never
# populated is the "table nothing writes to" error at column granularity - it
# reads as a capability.
#
# min_samples is the evidence floor below which the dimension is not stated at
# all. These are starting values to be replaced by measurement: the false-
# promotion curve says what they should be, and setting them by plausibility is
# precisely the mistake that made three timing constants wrong.
DIMENSIONS = {
    "analytical_quality": {
        "source": "mean overall_score of grades on this agent's work",
        "min_samples": 10,
    },
    "evidence_discipline": {
        "source": "mean evidence_quality_score",
        "min_samples": 10,
    },
    "novelty_contribution": {
        "source": "mean novelty_score",
        "min_samples": 10,
    },
    "uncertainty_calibration": {
        # Noisier than the others: it compares a stated confidence against an
        # observed outcome, so a handful of samples says almost nothing.
        "source": "agreement between stated confidence and observed correctness",
        "min_samples": 20,
    },
    "operational_reliability": {
        "source": "sessions that ended cleanly rather than in a crash",
        "min_samples": 3,
    },
}

UNSTATED_REASON = "not enough evidence yet"


def profile(evidence: dict) -> dict:
    """The competency profile: one entry per dimension, stated or not.

    `evidence` is what `fi_db.competency_evidence` gathered:
        grades       - list of dicts with the four grade scores
        calibration  - list of (stated_confidence, was_correct) pairs
        sessions     - how many times this agent has been spawned
        crashes      - how many of those ended without a clean exit
        window_days  - the recency window the evidence was drawn from, or None

    Every entry carries its sample count as well as its score, because a 0.62
    from twelve observations and a 0.62 from four hundred are different claims
    and a consumer that cannot tell them apart will treat them alike."""
    grades = evidence.get("grades") or []
    calibration = evidence.get("calibration") or []

    dimensions = {
        "analytical_quality": _mean_of(grades, "overall_score"),
        "evidence_discipline": _mean_of(grades, "evidence_quality_score"),
        "novelty_contribution": _mean_of(grades, "novelty_score"),
        "uncertainty_calibration": _calibration(calibration),
        "operational_reliability": _reliability(evidence.get("sessions"), evidence.get("crashes")),
    }

    return {
        "dimensions": {
            name: _state(name, *measured) for name, measured in dimensions.items()
        },
        "window_days": evidence.get("window_days"),
        # Said explicitly so a caller cannot mistake an empty profile for a
        # complete one full of low scores.
        "stated_dimensions": sorted(
            name for name, (value, samples, _) in dimensions.items()
            if samples >= DIMENSIONS[name]["min_samples"] and value is not None
        ),
    }


def _mean_of(rows: list[dict], key: str) -> tuple[float | None, int, float | None]:
    values = [row[key] for row in rows if row.get(key) is not None]
    return _summarise(values)


def _summarise(values: list[float]) -> tuple[float | None, int, float | None]:
    """Mean, count, and spread.

    **Spread is not decoration.** Two agents can both be scored from sixty
    observations and one of the estimates be ten times less precise than the
    other - a consistent agent and a wildly inconsistent one produce the same
    sample count and completely different certainty. Measured on generated
    populations: a steady agent's score landed within 0.004 of its true
    competence while an erratic one was out by 0.075, and nothing in the profile
    distinguished them. Ranking those two adjacent positions apart would have
    been reporting noise as a finding."""
    if not values:
        return None, 0, None
    mean = sum(values) / len(values)
    if len(values) < 2:
        return mean, len(values), None
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return mean, len(values), variance ** 0.5


def _calibration(samples: list) -> tuple[float | None, int, float | None]:
    """How closely stated confidence tracked what actually happened.

    Mean absolute error between a confidence and a 0/1 outcome, inverted so
    higher is better like every other dimension. An agent that says 0.9 and is
    right, and says 0.2 and is wrong, scores well; one that says 0.9 about
    everything scores badly however often it happens to be right.

    Deliberately not accuracy. An agent can be accurate and badly calibrated,
    and it is the calibration that says whether its confidence can be trusted as
    an input to anything else."""
    if not samples:
        return None, 0, None
    agreements = [1.0 - abs(confidence - (1.0 if correct else 0.0)) for confidence, correct in samples]
    return _summarise(agreements)


def _reliability(sessions: int | None, crashes: int | None) -> tuple[float | None, int, float | None]:
    """A proportion, so its spread is determined by the proportion itself rather
    than by a separate sample of values - the binomial standard deviation."""
    if not sessions:
        return None, 0, None
    rate = 1.0 - ((crashes or 0) / sessions)
    return rate, sessions, (rate * (1.0 - rate)) ** 0.5


def _state(name: str, value: float | None, samples: int, spread: float | None) -> dict:
    minimum = DIMENSIONS[name]["min_samples"]
    if value is None or samples < minimum:
        return {
            "stated": False,
            "score": None,
            "samples": samples,
            "needs": minimum,
            "spread": None,
            "standard_error": None,
            "reason": UNSTATED_REASON,
        }
    # How far the score itself could reasonably be off, which is what a caller
    # comparing two agents actually needs - the spread describes the agent, the
    # standard error describes the estimate.
    standard_error = (spread / (samples ** 0.5)) if spread is not None and samples else None
    return {
        "stated": True,
        "score": round(value, 4),
        "samples": samples,
        "needs": minimum,
        "spread": round(spread, 4) if spread is not None else None,
        "standard_error": round(standard_error, 4) if standard_error is not None else None,
    }


# --- qualification ----------------------------------------------------------

def evaluate_qualification(agent_profile: dict, requirements: dict) -> dict:
    """Whether this agent meets a named standard, and precisely why or why not.

    `requirements` maps dimension -> minimum score.

    An unstated dimension does **not** qualify, and is reported as unknown
    rather than as a failure. The distinction matters when it is read back: a
    new agent that has not been observed enough is in a different position from
    one that has been observed and found wanting, and remediation would be the
    wrong response to the first."""
    met, failed, unknown = [], [], []

    for dimension, minimum in sorted(requirements.items()):
        entry = agent_profile["dimensions"].get(dimension)
        if entry is None:
            unknown.append(f"{dimension} is not a dimension this system measures")
        elif not entry["stated"]:
            unknown.append(
                f"{dimension} not yet known ({entry['samples']}/{entry['needs']} observations)"
            )
        elif entry["score"] >= minimum:
            met.append(f"{dimension} {entry['score']} >= {minimum}")
        else:
            failed.append(f"{dimension} {entry['score']} < {minimum}")

    return {
        "qualified": not failed and not unknown,
        "met": met,
        "failed": failed,
        "unknown": unknown,
        # A caller deciding what to do next needs these apart: 'failed' argues
        # for development, 'unknown' argues only for more observation.
        "blocked_by": "evidence" if unknown and not failed else ("performance" if failed else None),
    }


# --- ranking ----------------------------------------------------------------

# Scores are compared at this precision when deciding ties. Without it two
# agents differing in the twelfth decimal place would swap rank on noise, and a
# rank that flickers is one nobody can act on.
TIE_PRECISION = 3


def rank(profiles: dict[str, dict], dimension: str) -> list[dict]:
    """Rank agents on one dimension, highest first.

    Always per dimension, never overall (§5 of the owner decision). Agents
    whose dimension is unstated are returned unranked with the reason, rather
    than omitted - an agent missing from a ranking looks like an agent that does
    not exist.

    **A single candidate is unranked, not first.** "Ranked #1" among one agent
    is a true statement that will be read as a false one, and every consumer of
    a ranking is looking for a comparison."""
    rankable, unranked = [], []
    for name, agent_profile in sorted(profiles.items()):
        entry = (agent_profile.get("dimensions") or {}).get(dimension)
        if entry is None or not entry["stated"]:
            unranked.append({
                "name": name, "rank": None, "score": None,
                "reason": entry["reason"] if entry else f"{dimension} is not measured",
            })
        else:
            rankable.append({
                "name": name, "score": entry["score"], "samples": entry["samples"],
                "standard_error": entry["standard_error"],
            })

    if len(rankable) < 2:
        return [
            {**row, "rank": None, "reason": "only candidate - a ranking of one compares nothing"}
            for row in rankable
        ] + unranked

    rankable.sort(key=lambda row: (-row["score"], row["name"]))

    results = []
    position = 0
    previous = None
    for index, row in enumerate(rankable):
        rounded = round(row["score"], TIE_PRECISION)
        if previous is None or rounded != previous:
            position = index + 1          # standard competition ranking: 1, 2, 2, 4
            previous = rounded
        results.append({**row, "rank": position})

    for index, row in enumerate(results):
        row["tied_with"] = sorted(
            other["name"] for other in results
            if other["rank"] == row["rank"] and other["name"] != row["name"]
        )
        row.update(_separation(row, results[index + 1] if index + 1 < len(results) else None))
    return results + unranked


# How many combined standard errors two adjacent scores must differ by before
# the ordering between them is worth acting on. Two is the conventional bar and
# is deliberately not tuned here; what matters is that the question is asked at
# all.
SEPARATION_SIGMAS = 2.0


def _separation(row: dict, next_row: dict | None) -> dict:
    """Whether this agent is really ahead of the next one, or only measured ahead.

    An erratic agent and a steady one can be scored from the same number of
    observations with wildly different precision, so a rank gap of 0.07 can be
    decisive in one pair and meaningless in another. Reported rather than acted
    on: the ordering still stands, and a consumer promoting on the strength of
    it now has the means to notice the ordering was noise."""
    if next_row is None:
        return {"gap_to_next": None, "separated": None}

    gap = round(row["score"] - next_row["score"], 4)
    errors = [row.get("standard_error"), next_row.get("standard_error")]
    if any(error is None for error in errors):
        return {"gap_to_next": gap, "separated": None}

    combined = (errors[0] ** 2 + errors[1] ** 2) ** 0.5
    return {
        "gap_to_next": gap,
        "separated": gap >= SEPARATION_SIGMAS * combined if combined else True,
    }


# --- commendations ----------------------------------------------------------

# What a commendation records. Each is a historical fact about a period, and
# none of them is an input to any decision - see the module docstring, and note
# that no function in this module accepts a commendation as an argument.
COMMENDATION_KINDS = {
    "held_top_rank": "held the top rank for a dimension over a sustained period",
    "sustained_qualification": "met a qualification continuously over a sustained period",
    "recovery": "returned to qualification after having lost it",
}

# How long a condition must hold before it becomes a commendation rather than a
# good week.
SUSTAINED_OBSERVATIONS = 30


def commendations_earned(name: str, history: list[dict]) -> list[dict]:
    """Which commendations this agent's recorded history now supports.

    `history` is the append-only `personnel_events` trail. Proposals only: the
    caller records them, and recording is what makes them permanent. A
    commendation is never recomputed away afterwards, because the achievement
    happened even when the standing that produced it has since changed - which
    is the whole distinction between historical and current truth."""
    earned = []

    top_rank_runs = _runs(history, "rank_achieved", lambda event: event.get("detail") == "1")
    for dimension, count, first, last in top_rank_runs:
        if count >= SUSTAINED_OBSERVATIONS:
            earned.append({
                "name": name, "kind": "held_top_rank", "subject": dimension,
                "detail": f"ranked first for {dimension} across {count} consecutive assessments",
                "period_start": first, "period_end": last,
            })

    qualification_runs = _runs(history, "qualification_granted", lambda event: True)
    for subject, count, first, last in qualification_runs:
        if count >= SUSTAINED_OBSERVATIONS:
            earned.append({
                "name": name, "kind": "sustained_qualification", "subject": subject,
                "detail": f"held the {subject} qualification across {count} consecutive assessments",
                "period_start": first, "period_end": last,
            })

    for event in _recoveries(history):
        earned.append({
            "name": name, "kind": "recovery", "subject": event["subject"],
            "detail": f"regained the {event['subject']} qualification after losing it",
            "period_start": event["lost_at"], "period_end": event["regained_at"],
        })

    return earned


def _runs(history: list[dict], kind: str, predicate) -> list[tuple]:
    """Consecutive runs of one event kind per subject, uninterrupted by its loss."""
    runs: dict[str, list] = {}
    closed = []
    for event in history:
        subject = event.get("subject")
        if event.get("event_kind") == kind and predicate(event):
            run = runs.setdefault(subject, [0, event.get("occurred_at"), None])
            run[0] += 1
            run[2] = event.get("occurred_at")
        elif subject in runs:
            count, first, last = runs.pop(subject)
            closed.append((subject, count, first, last))
    for subject, (count, first, last) in runs.items():
        closed.append((subject, count, first, last))
    return closed


def _recoveries(history: list[dict]) -> list[dict]:
    """A qualification granted after having been revoked."""
    lost: dict[str, str] = {}
    found = []
    for event in history:
        subject = event.get("subject")
        if event.get("event_kind") == "qualification_revoked":
            lost[subject] = event.get("occurred_at")
        elif event.get("event_kind") == "qualification_granted" and subject in lost:
            found.append({
                "subject": subject,
                "lost_at": lost.pop(subject),
                "regained_at": event.get("occurred_at"),
            })
    return found
