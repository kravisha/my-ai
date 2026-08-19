"""The Risk Engine's first slice (addendum 20 §2E).

Four factors, each reading one thing the organization already records, each
able to say "I don't know" instead of guessing; an overall level that is the
worst factor rather than an average; a COO cycle step that assesses what
Analysis produced, because the producer of an opportunity must not be the
judge of its risk (addendum 11 §8); and a compliance rule with teeth, so a
stopped assessment step is visible rather than silent.
"""

import inspect
import json
from datetime import datetime, timedelta, timezone

import pytest

from backend import compliance, fi_db, risk
from providers import historical


# --- Planting helpers: the real functions, not hand-rolled INSERTs, so these ---
# --- tests exercise the same lifecycle production code goes through. ---


def _plant_report_and_result(
    conn,
    security="SYN1",
    lens_artifact_id=None,
    cross_check_id=None,
    producer="explorer-1",
):
    """A completed, analysed report and its analysis result - the pair every
    risk factor reads from (regime keys off the result's security, lens and
    corroboration key off the report the result points to)."""
    report_id = fi_db.enqueue_report(
        conn, producer, "2026-01-01T00:00:00+00:00", "explorer", security,
        lens_artifact_id=lens_artifact_id, cross_check_id=cross_check_id,
    )
    fi_db.complete_report(
        conn, report_id, "analyzed",
        handled_by_identity="analysis-1", handled_by_spawned_at="2026-01-01T00:01:00+00:00",
    )
    result_id = fi_db.record_analysis_result(
        conn, "analysis-1", "2026-01-01T00:01:00+00:00", report_id, security,
        thesis="t", evidence_summary="e", confidence=0.5, uncertainty="u",
    )
    return report_id, result_id


def _grade(conn, report_id, result_id):
    fi_db.record_grade(
        conn, "analysis-1", "2026-01-01T00:01:00+00:00", report_id, result_id,
        relevance_score=0.5, novelty_score=0.5, evidence_quality_score=0.5,
        worth_the_compute=1, overall_score=0.5, rationale="r",
    )


def _set_regime(conn, security, mean_iv, iv_dispersion, observation_count):
    """Inserted directly rather than through fi_db.update_market_regime, which
    blends via an EWMA - these tests need exact cv values at the boundaries,
    not whatever a sequence of blended updates happens to converge to."""
    conn.execute(
        "INSERT INTO market_regime (security, mean_iv, iv_dispersion, observation_count, updated_at, schema_version) "
        "VALUES (?, ?, ?, ?, '2026-01-01T00:00:00+00:00', 1)",
        (security, mean_iv, iv_dispersion, observation_count),
    )


# --- 1. regime_factor: deterministic thresholds, and an honest no_evidence ---


def test_regime_factor_below_minimum_observations_is_no_evidence(conn):
    _set_regime(conn, "SYN1", mean_iv=1.0, iv_dispersion=0.05, observation_count=risk.MIN_REGIME_OBSERVATIONS - 1)

    result = risk.regime_factor(conn, "SYN1")

    assert result["level"] == "no_evidence"
    assert "too few observations" in result["why"]


def test_regime_factor_with_no_row_at_all_is_no_evidence(conn):
    result = risk.regime_factor(conn, "SYN1")
    assert result["level"] == "no_evidence"


def test_regime_factor_low_below_the_first_threshold(conn):
    _set_regime(conn, "SYN1", mean_iv=1.0, iv_dispersion=0.05, observation_count=10)  # cv = 0.05
    result = risk.regime_factor(conn, "SYN1")
    assert result["level"] == "low"
    assert result["evidence"]["cv"] == pytest.approx(0.05)


def test_regime_factor_elevated_at_the_low_boundary(conn):
    """cv == REGIME_CV_LOW is not < the threshold, so it falls into elevated -
    a boundary belongs to the band above it, not the one below."""
    _set_regime(conn, "SYN1", mean_iv=1.0, iv_dispersion=risk.REGIME_CV_LOW, observation_count=10)  # cv = 0.10
    result = risk.regime_factor(conn, "SYN1")
    assert result["level"] == "elevated"


def test_regime_factor_high_at_the_elevated_boundary(conn):
    _set_regime(conn, "SYN1", mean_iv=1.0, iv_dispersion=risk.REGIME_CV_ELEVATED, observation_count=10)  # cv = 0.25
    result = risk.regime_factor(conn, "SYN1")
    assert result["level"] == "high"


def test_regime_factor_zero_mean_iv_is_no_evidence_not_a_crash(conn):
    _set_regime(conn, "SYN1", mean_iv=0.0, iv_dispersion=0.05, observation_count=10)
    result = risk.regime_factor(conn, "SYN1")
    assert result["level"] == "no_evidence"


# --- 2. lens_factor: seed constants, staleness, and unproven vs. proven ---


def test_lens_factor_null_artifact_is_high_risk_seed_era(conn):
    report_id, _ = _plant_report_and_result(conn, lens_artifact_id=None)
    result = risk.lens_factor(conn, report_id)
    assert result["level"] == "high"
    assert "seed" in result["why"]


def test_lens_factor_stale_artifact_is_elevated(conn):
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    fi_db.mark_artifact_stale(conn, lens["id"], "regime diverged")
    report_id, _ = _plant_report_and_result(conn, lens_artifact_id=lens["id"])

    result = risk.lens_factor(conn, report_id)

    assert result["level"] == "elevated"
    assert "stale" in result["why"]


def test_lens_factor_active_but_ungraded_is_elevated(conn):
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_SPECULATOR_CONFIDENCE_NAME)
    report_id, _ = _plant_report_and_result(conn, lens_artifact_id=lens["id"])

    result = risk.lens_factor(conn, report_id)

    assert result["level"] == "elevated"
    assert "unproven" in result["why"]


def test_lens_factor_active_and_graded_is_low(conn):
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_SPECULATOR_CONFIDENCE_NAME)
    report_id, result_id = _plant_report_and_result(conn, lens_artifact_id=lens["id"])
    _grade(conn, report_id, result_id)

    result = risk.lens_factor(conn, report_id)

    assert result["level"] == "low"
    assert result["evidence"]["graded_reports"] == 1


def test_lens_factor_unknown_report_is_no_evidence(conn):
    result = risk.lens_factor(conn, 999999)
    assert result["level"] == "no_evidence"


# --- 3. corroboration_factor: the actual outcome vocabulary ---
#
# cross_check_requests.outcome is 'evidence' | 'no_evidence' | 'unanswered'
# (fi_db.CROSS_CHECK_EVIDENCE and neighbours), not 'answered' - this factor's
# mapping is written against the real column, not an assumed one.


def _cross_check_with_outcome(conn, outcome):
    request_id = fi_db.open_cross_check(
        conn, "explorer-1", "2026-01-01T00:00:00+00:00", "explorer", "speculator", "SYN1",
        question="q?", requester_finding={"x": 1},
    )
    if outcome is not None:
        fi_db.answer_cross_check(
            conn, request_id, "speculator-1", "2026-01-01T00:00:30+00:00", outcome,
            {"y": 2},
        )
    return request_id


def test_corroboration_factor_no_cross_check_id_is_no_evidence(conn):
    report_id, _ = _plant_report_and_result(conn, cross_check_id=None)
    result = risk.corroboration_factor(conn, report_id)
    assert result["level"] == "no_evidence"
    assert "does not cross-check" in result["why"]


def test_corroboration_factor_evidence_outcome_is_low(conn):
    cc_id = _cross_check_with_outcome(conn, fi_db.CROSS_CHECK_EVIDENCE)
    report_id, _ = _plant_report_and_result(conn, cross_check_id=cc_id)
    result = risk.corroboration_factor(conn, report_id)
    assert result["level"] == "low"


def test_corroboration_factor_no_evidence_outcome_is_elevated(conn):
    cc_id = _cross_check_with_outcome(conn, fi_db.CROSS_CHECK_NO_EVIDENCE)
    report_id, _ = _plant_report_and_result(conn, cross_check_id=cc_id)
    result = risk.corroboration_factor(conn, report_id)
    assert result["level"] == "elevated"
    assert "sought and not obtained" in result["why"]


def test_corroboration_factor_unanswered_outcome_is_elevated(conn):
    cc_id = _cross_check_with_outcome(conn, fi_db.CROSS_CHECK_UNANSWERED)
    report_id, _ = _plant_report_and_result(conn, cross_check_id=cc_id)
    result = risk.corroboration_factor(conn, report_id)
    assert result["level"] == "elevated"
    assert "silence is not corroboration" in result["why"]


def test_corroboration_factor_still_pending_is_no_evidence(conn):
    cc_id = _cross_check_with_outcome(conn, None)  # never answered yet
    report_id, _ = _plant_report_and_result(conn, cross_check_id=cc_id)
    result = risk.corroboration_factor(conn, report_id)
    assert result["level"] == "no_evidence"


# --- 4. stress_factor: DGS10 as the macro proxy, ingested through the real ---
# --- FRED adapter so this exercises the actual Data Store, not a shortcut ---


def _fred_csv(moves):
    """FRED's two-column shape, dates anchored to "today" so the factor's
    30-day replay window always catches them regardless of when the suite
    runs. `moves` is [(days_ago, value), ...]."""
    lines = ["observation_date,DGS10"]
    today = datetime.now(timezone.utc).date()
    for days_ago, value in moves:
        date = today - timedelta(days=days_ago)
        lines.append(f"{date.isoformat()},{value}")
    return "\n".join(lines) + "\n"


def test_stress_factor_with_no_corpus_is_no_evidence(conn):
    result = risk.stress_factor(conn)
    assert result["level"] == "no_evidence"
    assert "ingest DGS10" in result["why"]


def test_stress_factor_large_move_is_high(conn):
    csv_text = _fred_csv([(20, 4.00), (1, 4.60)])  # 0.60 point move, within 30 days
    historical.ingest_fred_series(conn, csv_text, "DGS10", source="fred:DGS10")

    result = risk.stress_factor(conn)

    assert result["level"] == "high"
    assert result["evidence"]["move"] == pytest.approx(0.60)


def test_stress_factor_small_move_is_low(conn):
    csv_text = _fred_csv([(20, 4.00), (1, 4.10)])  # 0.10 point move
    historical.ingest_fred_series(conn, csv_text, "DGS10", source="fred:DGS10")

    result = risk.stress_factor(conn)

    assert result["level"] == "low"
    assert result["evidence"]["move"] == pytest.approx(0.10)


# --- 5. overall_level: worst factor wins, never an average ---


def test_overall_level_is_the_worst_non_abstaining_factor():
    factors = [
        {"factor": "a", "level": "low"},
        {"factor": "b", "level": "high"},
        {"factor": "c", "level": "elevated"},
        {"factor": "d", "level": "no_evidence"},
    ]
    assert risk.overall_level(factors) == "high"


def test_overall_level_all_no_evidence_is_no_evidence_not_low():
    factors = [
        {"factor": "a", "level": "no_evidence"},
        {"factor": "b", "level": "no_evidence"},
    ]
    assert risk.overall_level(factors) == "no_evidence"


# --- 6. assess_unassessed: idempotent, deterministic, UNIQUE-guarded ---


def test_assess_unassessed_assesses_every_result_once(conn):
    _, result_id_1 = _plant_report_and_result(conn, security="SYN1")
    _, result_id_2 = _plant_report_and_result(conn, security="SYN2")

    assessed = risk.assess_unassessed(conn, "coo-1")

    assert assessed == 2
    for result_id in (result_id_1, result_id_2):
        assessment = risk.get_assessment(conn, result_id)
        assert assessment is not None
        assert assessment["assessed_by"] == "coo-1"
        assert assessment["overall"] in risk.LEVELS + ("no_evidence",)
        assert assessment["factors"]["measured"] is False
        assert len(assessment["factors"]["factors"]) == 4


def test_assess_unassessed_is_idempotent(conn):
    _plant_report_and_result(conn, security="SYN1")
    first = risk.assess_unassessed(conn, "coo-1")
    second = risk.assess_unassessed(conn, "coo-1")
    assert first == 1
    assert second == 0


def test_assess_refuses_to_double_assess(conn):
    _, result_id = _plant_report_and_result(conn, security="SYN1")
    row = conn.fetchone("SELECT * FROM analysis_results WHERE id = ?", (result_id,))
    risk.assess(conn, row, "coo-1")

    with pytest.raises(ValueError):
        risk.assess(conn, row, "coo-1")


def test_risk_assessments_unique_constraint_backs_the_refusal(conn):
    """The Python-level check in assess() is belt; the UNIQUE index is
    suspenders - a second insert must fail at the database even if some
    future caller bypassed assess()'s own guard."""
    import sqlite3

    _, result_id = _plant_report_and_result(conn, security="SYN1")
    risk.assess_unassessed(conn, "coo-1")

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO risk_assessments (analysis_result_id, security, overall, factors, "
            "assessed_by, created_at, schema_version) VALUES (?, 'SYN1', 'low', '{}', 'coo-1', "
            "'2026-01-01T00:00:00+00:00', 1)",
            (result_id,),
        )


# --- 7. compliance: the rule with teeth ---


def test_compliance_reports_an_unassessed_result_and_clears_after_assessment(conn):
    _plant_report_and_result(conn, security="SYN1")

    before = compliance.check(conn)
    violations_before = [f for f in before["unevaluated"] if f["rule"] == "analysis result (risk-assessed)"]
    assert len(violations_before) == 1

    risk.assess_unassessed(conn, "coo-1")

    after = compliance.check(conn)
    violations_after = [f for f in after["unevaluated"] if f["rule"] == "analysis result (risk-assessed)"]
    assert violations_after == []
    assert "analysis result (risk-assessed)" in after["passing"]


# --- 8. COO ordering: assessed before the compliance-adjacent sweep runs ---


def test_coo_assesses_risk_before_raising_corrective_actions():
    """Source order, not runtime behaviour - the docstring on the call site
    in agents/coo.py explains why the ordering itself is the grace period
    that keeps a same-cycle result from being counted unassessed."""
    from agents.coo import _coo_work

    source = inspect.getsource(_coo_work)
    assert source.index("assess_unassessed") < source.index("raise_corrective_actions")


def test_coo_work_actually_assesses_risk(conn):
    from agents.coo import _coo_work

    _plant_report_and_result(conn, security="SYN1")
    _coo_work(conn)

    rows = conn.fetchall("SELECT * FROM risk_assessments")
    assert len(rows) == 1
    assert rows[0]["assessed_by"] == "coo-1"


# --- 9. admin route: risk surfaces in the discovery panel ---


def test_admin_discovery_route_includes_risk_overall(panel_client, panel_conn):
    _, result_id = _plant_report_and_result(panel_conn, security="SYN1")
    risk.assess_unassessed(panel_conn, "coo-1")

    body = panel_client.get("/admin/discovery").json()
    row = next(r for r in body["recent_analyses"] if r["id"] == result_id)

    assert row["risk_overall"] in risk.LEVELS + ("no_evidence",)
    # Consistent with how this route returns every other field on the row:
    # raw, not JSON-parsed - recent_analyses is not among the routes that
    # parse JSON columns before returning them.
    parsed = json.loads(row["risk_factors"])
    assert len(parsed["factors"]) == 4
