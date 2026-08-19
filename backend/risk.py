"""The Risk Engine's first slice (addendum 20 §2E): every opportunity carries
an attached risk assessment, and the producer of the opportunity is not the
one who attaches it. Deterministic and evidence-based - each factor reads
something the organization actually records, carries the numbers it read, and
returns a level it can defend. The thresholds are conventions, not
measurements, and say so (measured: False in every assessment) - the same
disclosure discipline as backend/iteration.py's budgets and
TIMING_CONSTANTS.md.

What this is not: a probability model. A weighted score over four judgments
would be arithmetic wearing authority it has not earned; the overall level is
the worst factor, because a chain is its weakest link and pretending
otherwise requires evidence nobody has.

## Four factors, four different silences

Each factor reads one thing the organization already keeps a record of, and
each has its own honest way of saying "I don't know":

- **regime** - how calm or turbulent the market has looked, from
  `market_regime`. Too few observations and it says so rather than guessing.
- **lens** - whether the intelligence that spotted this was a proven,
  actively-maintained lens or a fallback seed constant with nothing behind
  it.
- **corroboration** - whether a peer agent looked for independent evidence
  and found any, per addendum 12 §14's cross-check contract.
- **stress** - whether the broader macro backdrop (proxied by the 10-year
  Treasury yield, the deepest series this system holds) has been moving.

No factor is required to have an opinion. `no_evidence` is a fifth, honest
answer distinct from `low` - an organization that has not looked cannot
claim what it would have seen.

## Why this sits below fi_db rather than importing it

fi_db.init_schema creates this module's table (risk_assessments), so this
module must not import fi_db - that would close a cycle. Where a factor needs
something fi_db already computes for another purpose (lens_performance's
grades join, current_market_characterization's aggregate), the query is
re-stated here directly against the tables rather than imported. See the
comments on lens_factor and regime_factor for exactly which fi_db logic each
one mirrors and why the mirror is deliberate, not accidental duplication.

## Why the producer never assesses

Placed in the COO cycle (agents/coo.py's _coo_work), not in Analysis where
the opportunity is produced, for the same reason source standings and lens
health are COO's rather than Speculator's or Explorer's own: the producer of
an opportunity must not be the judge of its risk (addendum 11 §8).
"""

from __future__ import annotations

import json
from datetime import timedelta

from backend import identifiers, observations
from backend.db import Database, now_iso, parse_timestamp

# One assessment per result (UNIQUE) - re-assessment under changed conditions
# is a future design with its own reason; silently overwriting a judgment
# would destroy the record of what was believed when the opportunity was
# fresh. "Not yet assessed" is the absence of this row, the same idiom grades
# uses - no marker column on analysis_results.
SCHEMA = """
CREATE TABLE IF NOT EXISTS risk_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_result_id INTEGER NOT NULL UNIQUE,
    security TEXT NOT NULL,
    overall TEXT NOT NULL,
    factors TEXT NOT NULL,
    assessed_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS risk_assessments_by_security ON risk_assessments (security, id);
"""

SCHEMA_VERSION = 1

# The overall level an assessment can carry. Per-factor levels are a superset
# of this - "no_evidence" is a legitimate factor answer but never an honest
# *overall* answer for a system that assessed anything at all (see
# overall_level).
LEVELS = ("low", "elevated", "high")
_RANK = {"low": 0, "elevated": 1, "high": 2}

# A convention, unmeasured; below it the characterization is an anecdote, not
# a description of the regime. Five observations is roughly a trading week at
# the pace market_regime is folded (see fi_db.update_market_regime) - enough
# that the EWMA has actually moved off its seed, not enough to claim anything
# statistical.
MIN_REGIME_OBSERVATIONS = 5

# Coefficient-of-variation bands for the regime factor. Below 0.10 the spread
# of implied vol around its mean is tight relative to the mean itself; above
# 0.25 the mean is barely describing the market any more. Conventions, like
# every threshold in this module - nobody has back-tested where a regime
# factor should flip, and this module says so rather than implying otherwise.
REGIME_CV_LOW = 0.10
REGIME_CV_ELEVATED = 0.25

# Treasury yields as the stress proxy because they are the deepest series
# held (1962-) and flight-to-safety moves are regime news for every asset
# class; SP500 drawdown joins when someone needs it. Thresholds in
# percentage points, conventions, unmeasured.
STRESS_ENTITY_SCHEME = "symbol"
STRESS_ENTITY_VALUE = "DGS10"
STRESS_DATA_CLASS = "government_yield"
STRESS_WINDOW_DAYS = 30
STRESS_MOVE_HIGH = 0.50
STRESS_MOVE_ELEVATED = 0.25


def init_schema(conn: Database) -> None:
    conn.executescript(SCHEMA)


def _factor(name: str, level: str, evidence: dict, why: str) -> dict:
    return {"factor": name, "level": level, "evidence": evidence, "why": why}


def regime_factor(conn: Database, security: str) -> dict:
    """How calm or turbulent this security's implied-vol regime has looked.

    Reimplemented inline against `market_regime` rather than calling
    fi_db.current_market_characterization: that function aggregates *across*
    securities for the lens-drift check it was built for, and averaging in
    other names would answer a different question than "what is this
    security's own regime". For one security the row *is* the
    characterization, so this is simpler than the aggregate it would
    otherwise call, not a partial copy of it."""
    row = conn.fetchone(
        "SELECT mean_iv, iv_dispersion, observation_count FROM market_regime WHERE security = ?",
        (security,),
    )
    mean_iv = row["mean_iv"] if row else None
    iv_dispersion = row["iv_dispersion"] if row else None
    observation_count = row["observation_count"] if row else 0
    evidence = {
        "mean_iv": mean_iv,
        "iv_dispersion": iv_dispersion,
        "observation_count": observation_count,
    }

    if observation_count < MIN_REGIME_OBSERVATIONS:
        return _factor(
            "regime", "no_evidence", evidence,
            "too few observations to characterize the regime",
        )
    if not mean_iv:
        # Guards a division that would otherwise raise or, worse, silently
        # produce inf/nan - a zero or unset mean_iv is itself a sign nothing
        # real has been observed yet, whatever observation_count says.
        return _factor(
            "regime", "no_evidence", evidence,
            "mean_iv is zero or unset, so a dispersion ratio cannot be computed",
        )

    cv = iv_dispersion / mean_iv
    evidence["cv"] = cv
    if cv < REGIME_CV_LOW:
        level = "low"
        why = f"dispersion/mean ratio {cv:.4f} is below {REGIME_CV_LOW}, a tight regime"
    elif cv < REGIME_CV_ELEVATED:
        level = "elevated"
        why = f"dispersion/mean ratio {cv:.4f} is between {REGIME_CV_LOW} and {REGIME_CV_ELEVATED}"
    else:
        level = "high"
        why = f"dispersion/mean ratio {cv:.4f} is at or above {REGIME_CV_ELEVATED}, a scattered regime"
    return _factor("regime", level, evidence, why)


def lens_factor(conn: Database, report_id: int) -> dict:
    """Whether the intelligence that spotted this had earned any trust yet.

    graded_reports is computed by a query that mirrors fi_db.lens_performance
    (~2703) - grades joined through discovery_reports_completed to the
    artifact - re-stated here rather than imported because risk sits below
    fi_db in the module order: fi_db.init_schema creates this module's table,
    so this module must not import fi_db."""
    report = conn.fetchone(
        "SELECT lens_artifact_id FROM discovery_reports_completed WHERE id = ?", (report_id,)
    )
    if report is None:
        return _factor(
            "lens", "no_evidence", {"report_id": report_id},
            "the underlying report is not in the completed record",
        )

    if report["lens_artifact_id"] is None:
        return _factor(
            "lens", "high", {"report_id": report_id},
            "the detection fired on a fallback seed constant with no performance history - "
            "the seed-era window succession exists to shorten",
        )

    artifact_id = report["lens_artifact_id"]
    artifact = conn.fetchone(
        "SELECT status FROM intelligence_artifacts WHERE id = ?", (artifact_id,)
    )
    if artifact is None or artifact["status"] != "active":
        return _factor(
            "lens", "elevated",
            {"artifact_id": artifact_id, "status": artifact["status"] if artifact else None},
            "the lens has been marked stale since this detection",
        )

    # The join fi_db.lens_performance uses, minus the score aggregates this
    # factor has no use for - graded_reports alone answers "has this lens
    # earned any trust", which is all a risk factor needs.
    graded = conn.fetchone(
        "SELECT COUNT(*) AS graded_reports FROM grades g "
        "JOIN discovery_reports_completed r ON g.report_id = r.id "
        "WHERE r.lens_artifact_id = ?",
        (artifact_id,),
    )
    graded_reports = graded["graded_reports"] if graded else 0
    if graded_reports == 0:
        return _factor(
            "lens", "elevated", {"artifact_id": artifact_id, "graded_reports": 0},
            "an unproven lens: no graded history behind the threshold",
        )
    return _factor(
        "lens", "low", {"artifact_id": artifact_id, "graded_reports": graded_reports},
        "an active lens with graded history behind it",
    )


def corroboration_factor(conn: Database, report_id: int) -> dict:
    """Whether a peer agent's independent look backs this finding.

    Reads cross_check_requests.outcome, which is 'evidence' | 'no_evidence' |
    'unanswered' (see fi_db.CROSS_CHECK_EVIDENCE and neighbours) - not
    'answered'. 'evidence' is the peer having looked and found something that
    speaks to the question asked, which is what this factor treats as
    corroboration obtained."""
    report = conn.fetchone(
        "SELECT cross_check_id FROM discovery_reports_completed WHERE id = ?", (report_id,)
    )
    if report is None:
        return _factor(
            "corroboration", "no_evidence", {"report_id": report_id},
            "the underlying report is not in the completed record",
        )
    if report["cross_check_id"] is None:
        return _factor(
            "corroboration", "no_evidence", {"report_id": report_id},
            "this report class does not cross-check",
        )

    cross_check_id = report["cross_check_id"]
    cc = conn.fetchone(
        "SELECT outcome FROM cross_check_requests WHERE id = ?", (cross_check_id,)
    )
    outcome = cc["outcome"] if cc else None
    evidence = {"outcome": outcome, "cross_check_id": cross_check_id}

    if outcome == "evidence":
        return _factor("corroboration", "low", evidence,
                        "the peer looked and found evidence that speaks to the question")
    if outcome == "no_evidence":
        return _factor(
            "corroboration", "elevated", evidence,
            "the peer looked and found nothing - corroboration was sought and not obtained",
        )
    if outcome == "unanswered":
        return _factor("corroboration", "elevated", evidence,
                        "the peer never answered; silence is not corroboration")
    return _factor("corroboration", "no_evidence", evidence,
                    "the cross-check has not been resolved yet")


def stress_factor(conn: Database) -> dict:
    """Whether the macro backdrop has been moving, proxied by DGS10.

    Reads the Data Store directly (backend/observations.py), the same store
    the Historical Market Data Engine ingests into - this factor asks nothing
    of providers/historical.py beyond the identifier and observations it
    already wrote."""
    entity_id = identifiers.resolve(conn, STRESS_ENTITY_SCHEME, STRESS_ENTITY_VALUE)
    if entity_id is None:
        return _factor(
            "stress", "no_evidence", {},
            "no historical corpus held; ingest DGS10 to enable this factor",
        )

    coverage = observations.coverage(conn, entity_id, STRESS_DATA_CLASS)
    if not coverage or "historical" not in coverage:
        return _factor(
            "stress", "no_evidence", {},
            "no historical corpus held; ingest DGS10 to enable this factor",
        )

    end = now_iso()
    start = (parse_timestamp(end) - timedelta(days=STRESS_WINDOW_DAYS)).isoformat()
    points = observations.replay(
        conn, entity_id, STRESS_DATA_CLASS, start=start, end=end, origins=("historical",),
    )
    if len(points) < 2:
        return _factor(
            "stress", "no_evidence", {"window_days": STRESS_WINDOW_DAYS},
            "fewer than two observations in the last 30 days",
        )

    first, last = points[0], points[-1]
    move = abs(last.payload["value"] - first.payload["value"])
    evidence = {
        "first_date": first.observed_at,
        "first_value": first.payload["value"],
        "last_date": last.observed_at,
        "last_value": last.payload["value"],
        "move": move,
        "window_days": STRESS_WINDOW_DAYS,
    }
    if move >= STRESS_MOVE_HIGH:
        level = "high"
        why = f"DGS10 moved {move:.2f} points over {STRESS_WINDOW_DAYS} days, at or above {STRESS_MOVE_HIGH}"
    elif move >= STRESS_MOVE_ELEVATED:
        level = "elevated"
        why = f"DGS10 moved {move:.2f} points over {STRESS_WINDOW_DAYS} days, at or above {STRESS_MOVE_ELEVATED}"
    else:
        level = "low"
        why = f"DGS10 moved {move:.2f} points over {STRESS_WINDOW_DAYS} days, below {STRESS_MOVE_ELEVATED}"
    return _factor("stress", level, evidence, why)


def overall_level(factors: list[dict]) -> str:
    """The worst factor wins. Not an average, not a vote - a chain is its
    weakest link, and averaging four judgments into one score would be
    arithmetic wearing authority nobody earned.

    Factors that abstained (no_evidence) are excluded from the ranking, not
    treated as a level of their own - but if *every* factor abstained, the
    honest overall answer is also no_evidence: an organization holding no
    evidence cannot honestly rate the risk low."""
    ranked = [f for f in factors if f["level"] != "no_evidence"]
    if not ranked:
        return "no_evidence"
    return max(ranked, key=lambda f: _RANK[f["level"]])["level"]


def assess(conn: Database, analysis_result_row: dict, assessed_by: str) -> int:
    """Run all four factors against one analysis result and record the
    verdict. Refuses to double-assess (risk_assessments.analysis_result_id is
    UNIQUE) - callers that want to skip already-assessed results should use
    assess_unassessed, which pre-filters with the same NOT EXISTS query the
    compliance rule checks."""
    existing = conn.fetchone(
        "SELECT id FROM risk_assessments WHERE analysis_result_id = ?",
        (analysis_result_row["id"],),
    )
    if existing is not None:
        raise ValueError(
            f"analysis result {analysis_result_row['id']} already has a risk assessment "
            f"(id {existing['id']}) - re-assessment under changed conditions is a future design, "
            f"not silent overwrite"
        )

    factors = [
        regime_factor(conn, analysis_result_row["security"]),
        lens_factor(conn, analysis_result_row["report_id"]),
        corroboration_factor(conn, analysis_result_row["report_id"]),
        stress_factor(conn),
    ]
    overall = overall_level(factors)
    record = {"factors": factors, "measured": False}

    return conn.execute_returning_id(
        "INSERT INTO risk_assessments "
        "(analysis_result_id, security, overall, factors, assessed_by, created_at, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            analysis_result_row["id"], analysis_result_row["security"], overall,
            json.dumps(record), assessed_by, now_iso(), SCHEMA_VERSION,
        ),
    )


def assess_unassessed(conn: Database, assessed_by: str) -> int:
    """Every analysis result carrying no risk_assessments row yet, assessed
    in one pass. The NOT EXISTS query this runs is exactly what "not yet
    assessed" means in this module - the same absence-as-idiom grades uses -
    so a result assessed here can never be found by a second call in the same
    or a later cycle. Returns the count assessed, so a caller (agents/coo.py)
    can log what actually happened rather than assuming."""
    rows = conn.fetchall(
        "SELECT a.* FROM analysis_results a "
        "WHERE NOT EXISTS (SELECT 1 FROM risk_assessments r WHERE r.analysis_result_id = a.id) "
        "ORDER BY a.id"
    )
    for row in rows:
        assess(conn, row, assessed_by)
    return len(rows)


def get_assessment(conn: Database, analysis_result_id: int) -> dict | None:
    """One result's risk assessment, if it has one, with `factors` parsed back
    from JSON into the {"factors": [...], "measured": False} record `assess`
    built."""
    row = conn.fetchone(
        "SELECT * FROM risk_assessments WHERE analysis_result_id = ?", (analysis_result_id,)
    )
    if row is None:
        return None
    row = dict(row)
    row["factors"] = json.loads(row["factors"])
    return row
