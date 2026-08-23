"""Tests for backend/missions.py - mission control's backend registry (this
increment; addendum 25 SS4/SS22/SS23; docs/SPEC_RECONCILIATION.md SS39).

Module-level tests drive the registry directly against the shared `conn`
fixture, the same idiom tests/test_parity_evaluation.py and
tests/test_reference_data.py use. Route-level tests drive the same registry
through backend/main.py's /admin/mission* routes, using panel_client/
panel_conn (an authenticated admin, tests/conftest.py) for the feature tests
and backend_client (unauthenticated, no override) for the auth gate itself -
the same split tests/test_admin_auth.py documents its own reason for."""

import json
from pathlib import Path

import pytest

from agents.explorer import _file_cross_checked_reports, _parity_work
from backend import fi_db, missions
from backend import reference_data as rd
from simulation import parity_world as pw

MISSION_KWARGS = {"run_mode": "simulation", "strategy": "put_call_parity_arbitrage"}


def _config(mission_id, seed, **overrides):
    return {"mission_id": mission_id, "seed": seed, **MISSION_KWARGS, **overrides}


def _answer_all_cross_checks(conn):
    while True:
        request = fi_db.fetch_next_pending_cross_check(conn, "speculator")
        if request is None:
            break
        fi_db.answer_cross_check(
            conn, request["id"], "speculator-1", "T0", fi_db.CROSS_CHECK_NO_EVIDENCE, {"posts": 0},
        )


def _complete_all_reports_with_analysis(conn):
    for report in fi_db.list_pending_reports(conn):
        fi_db.complete_report(conn, report["id"], "analyzed", "analysis-1", "T0", detail="ok")
        fi_db.record_analysis_result(
            conn, "analysis-1", "T0", report["id"], report["security"],
            thesis="t", evidence_summary="e", confidence=0.8, uncertainty="u",
            peer_classification="not_applicable",
        )


def _run_full_chain(conn):
    """Detected -> escalated -> cross-checked -> reported -> analyzed, the
    same completion loop tests/test_parity_evaluation.py drives."""
    _parity_work(conn, "explorer-1", "T0")
    _answer_all_cross_checks(conn)
    _file_cross_checked_reports(conn, "explorer-1", "T0")
    _complete_all_reports_with_analysis(conn)


# --- start_mission: reference ready -------------------------------------------


def test_start_mission_reference_ready_stores_world(conn, tmp_path):
    rd.run_reference_engine(conn)

    result = missions.start_mission(
        conn, _config("m-start-ok", seed=1, n_scenarios=2, scenario_mix={"genuine": 1.0}), runs_dir=tmp_path,
    )

    assert result["status"] == missions.AGENTS_RUNNING
    assert result["note"] is None
    assert result["summary_path"]
    assert Path(result["summary_path"]).exists()
    assert result["stored"]["scenarios"] == 2
    assert conn.fetchone("SELECT COUNT(*) AS n FROM observations")["n"] > 0

    # config JSON round-trips through the row exactly as submitted.
    stored = missions.get_mission(conn, "m-start-ok")
    assert stored["config"]["mission_id"] == "m-start-ok"
    assert stored["config"]["seed"] == 1
    assert stored["config"]["strategy"] == "put_call_parity_arbitrage"
    assert stored["config"]["run_mode"] == "simulation"


# --- start_mission: reference not ready, then a real retry ---------------------


def test_start_mission_reference_not_ready_then_retries(conn, tmp_path):
    config = _config("m-start-wait", seed=2, n_scenarios=2, scenario_mix={"genuine": 1.0})

    result = missions.start_mission(conn, config, runs_dir=tmp_path)

    assert result["status"] == missions.WAITING_FOR_REFERENCE_DATA
    assert result["note"]
    assert result["summary_path"] is None
    assert result["stored"] is None
    assert conn.fetchone("SELECT COUNT(*) AS n FROM observations")["n"] == 0

    rd.run_reference_engine(conn)
    retried = missions.start_mission(conn, config, runs_dir=tmp_path)

    assert retried["status"] == missions.AGENTS_RUNNING
    assert retried["summary_path"]
    assert retried["stored"]["scenarios"] == 2
    # requested_at survives the retry - one mission, one original request time.
    assert retried["requested_at"] == result["requested_at"]


# --- start_mission: run_mode refusal --------------------------------------------


def test_start_mission_historical_run_mode_is_refused_with_no_row(conn, tmp_path):
    config = _config("m-start-historical", seed=3, run_mode="historical")

    with pytest.raises(missions.ActivationRefused) as exc_info:
        missions.start_mission(conn, config, runs_dir=tmp_path)

    assert "Simulation" in str(exc_info.value)
    assert "historical" in str(exc_info.value)
    assert missions.get_mission(conn, "m-start-historical") is None


# --- start_mission: too many scenarios ------------------------------------------


def test_start_mission_too_many_scenarios_fails_with_note(conn, tmp_path):
    rd.run_reference_engine(conn)
    focus_assets = rd.list_focus_assets(conn)

    result = missions.start_mission(
        conn, _config("m-start-toomany", seed=4, n_scenarios=len(focus_assets) + 1), runs_dir=tmp_path,
    )

    assert result["status"] == missions.FAILED
    assert result["note"]
    assert "n_scenarios" in result["note"] or "focus asset" in result["note"]
    assert result["summary_path"] is None
    assert result["stored"] is None


# --- start_mission: conflict on a running mission -------------------------------


def test_start_mission_conflict_on_running_mission_leaves_row_unchanged(conn, tmp_path):
    rd.run_reference_engine(conn)
    config = _config("m-start-conflict", seed=5, n_scenarios=2, scenario_mix={"genuine": 1.0})
    missions.start_mission(conn, config, runs_dir=tmp_path)
    before = missions.get_mission(conn, "m-start-conflict")

    with pytest.raises(missions.MissionConflict):
        missions.start_mission(conn, config, runs_dir=tmp_path)

    after = missions.get_mission(conn, "m-start-conflict")
    assert after == before


# --- pipeline_counts -------------------------------------------------------------


def test_pipeline_counts_matches_organizational_records(conn, tmp_path):
    rd.run_reference_engine(conn)
    result = missions.start_mission(
        conn, _config("m-counts", seed=6, n_scenarios=3, scenario_mix={"genuine": 1.0}), runs_dir=tmp_path,
    )
    mission_id = result["mission_id"]
    _run_full_chain(conn)

    counts = missions.pipeline_counts(conn, mission_id)

    expected_detections = conn.fetchone(
        "SELECT COUNT(*) AS n FROM parity_events WHERE run_id = ?", (mission_id,)
    )["n"]
    expected_scenarios = conn.fetchone(
        "SELECT COUNT(DISTINCT scenario_id) AS n FROM parity_events WHERE run_id = ?", (mission_id,)
    )["n"]
    expected_completed_reports = conn.fetchone(
        "SELECT COUNT(*) AS n FROM discovery_reports_completed drc "
        "JOIN parity_events pe ON drc.parity_event_id = pe.id WHERE pe.run_id = ?", (mission_id,)
    )["n"]
    expected_analyses = conn.fetchone("SELECT COUNT(*) AS n FROM analysis_results")["n"]

    assert counts["detections"] == expected_detections > 0
    assert counts["scenarios_with_detections"] == expected_scenarios > 0
    assert counts["reports_pending"] == 0
    assert counts["reports_completed"] == expected_completed_reports > 0
    assert counts["analyses"] == expected_analyses > 0


# --- evaluate ---------------------------------------------------------------------


def test_evaluate_full_chain_completes_and_caches_metrics(conn, tmp_path):
    rd.run_reference_engine(conn)
    result = missions.start_mission(
        conn, _config("m-eval-complete", seed=7, n_scenarios=2, scenario_mix={"genuine": 1.0}), runs_dir=tmp_path,
    )
    mission_id = result["mission_id"]
    _run_full_chain(conn)

    outcome = missions.evaluate(conn, mission_id)

    assert outcome["diagnosis"]["mission_certified_complete"] is True
    assert outcome["mission"]["status"] == missions.COMPLETED
    assert outcome["mission"]["metrics"] == outcome["evaluation"]["metrics"]
    assert outcome["mission"]["evaluation_path"] == outcome["evaluation"]["evaluation_path"]
    assert outcome["mission"]["diagnosis_path"] == outcome["diagnosis"]["diagnosis_path"]

    # the cache survives a fresh read of the row.
    reloaded = missions.get_mission(conn, mission_id)
    assert reloaded["status"] == missions.COMPLETED
    assert reloaded["metrics"]["strategy_exercised"] is True


def test_evaluate_stored_but_unworked_mission_is_retry_required(conn, tmp_path):
    """store_world only, nothing drives the agents afterward: the same fixed
    deterministic seed/mix tests/test_parity_evaluation.py uses for this
    shape (5 genuine + 1 none), so every genuine scenario is a missed
    detection - real corrective work outstanding, so RETRY_REQUIRED."""
    rd.run_reference_engine(conn)
    result = missions.start_mission(
        conn,
        _config("m-eval-retry", seed=13, n_scenarios=6, scenario_mix={"genuine": 1.0, "none": 1.0}),
        runs_dir=tmp_path,
    )
    mission_id = result["mission_id"]

    outcome = missions.evaluate(conn, mission_id)

    assert outcome["diagnosis"]["retry_recommended"] is True
    assert outcome["mission"]["status"] == missions.RETRY_REQUIRED


def test_evaluate_before_store_refuses(conn, tmp_path):
    """A mission blocked on reference data has no summary_path - a known row
    with nothing to grade, distinct from an unknown mission_id."""
    result = missions.start_mission(
        conn, _config("m-eval-noworld", seed=8, n_scenarios=1), runs_dir=tmp_path,
    )
    assert result["status"] == missions.WAITING_FOR_REFERENCE_DATA

    with pytest.raises(missions.MissionNotStored):
        missions.evaluate(conn, "m-eval-noworld")


def test_evaluate_unknown_mission_returns_none(conn):
    assert missions.evaluate(conn, "m-does-not-exist") is None


# --- mission_options ---------------------------------------------------------------


def test_mission_options_lists_offered_run_modes_and_capabilities(conn):
    options = missions.mission_options(conn)

    assert options["run_modes"] == ["simulation", "historical", "live"]
    assert "put_call_parity_arbitrage" in options["strategies"]

    asset_class_codes = {row["asset_class"] for row in options["asset_classes"]}
    assert {"stock", "stock_option"} <= asset_class_codes


# --- route level ---------------------------------------------------------------------


def test_post_historical_mission_returns_400(panel_client, panel_conn):
    response = panel_client.post(
        "/admin/mission", json=_config("m-route-historical", seed=9, run_mode="historical"),
    )
    assert response.status_code == 400
    assert "Simulation" in response.json()["detail"]
    assert missions.get_mission(panel_conn, "m-route-historical") is None


def test_post_simulation_mission_and_list_shows_it_with_counts(panel_client, panel_conn):
    rd.run_reference_engine(panel_conn)

    response = panel_client.post(
        "/admin/mission",
        json=_config("m-route-ok", seed=10, n_scenarios=2, scenario_mix={"genuine": 1.0}),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == missions.AGENTS_RUNNING
    assert body["summary_path"]

    listing = panel_client.get("/admin/missions")
    assert listing.status_code == 200
    rows = {row["mission_id"]: row for row in listing.json()["missions"]}
    assert "m-route-ok" in rows
    assert rows["m-route-ok"]["status"] == missions.AGENTS_RUNNING
    assert "pipeline" in rows["m-route-ok"]
    assert rows["m-route-ok"]["pipeline"]["detections"] == 0


def test_post_evaluate_route_returns_diagnosis(panel_client, panel_conn):
    rd.run_reference_engine(panel_conn)
    panel_client.post(
        "/admin/mission",
        json=_config("m-route-eval", seed=11, n_scenarios=2, scenario_mix={"genuine": 1.0}),
    )
    _run_full_chain(panel_conn)

    response = panel_client.post("/admin/mission/m-route-eval/evaluate")

    assert response.status_code == 200
    body = response.json()
    assert "diagnosis" in body
    assert body["diagnosis"]["mission_certified_complete"] is True
    assert body["mission"]["status"] == missions.COMPLETED

    detail = panel_client.get("/admin/mission/m-route-eval")
    assert detail.status_code == 200
    assert detail.json()["mission"]["status"] == missions.COMPLETED
    assert detail.json()["evaluation_scenarios"] is not None


def test_evaluate_route_404_for_unknown_mission(panel_client):
    response = panel_client.post("/admin/mission/m-does-not-exist/evaluate")
    assert response.status_code == 404


def test_evaluate_route_409_when_no_world_stored(panel_client, panel_conn):
    panel_client.post("/admin/mission", json=_config("m-route-noworld", seed=12, n_scenarios=1))
    assert missions.get_mission(panel_conn, "m-route-noworld")["status"] == missions.WAITING_FOR_REFERENCE_DATA

    response = panel_client.post("/admin/mission/m-route-noworld/evaluate")
    assert response.status_code == 409


def test_mission_routes_require_admin(backend_client, monkeypatch):
    from app import admin_auth

    monkeypatch.setenv(admin_auth.ADMIN_USERS_ENV, "root")
    assert backend_client.get("/admin/mission-options").status_code == 401
    assert backend_client.get("/admin/missions").status_code == 401
    assert backend_client.post("/admin/mission", json=_config("m-noauth", seed=1)).status_code == 401
    assert backend_client.post("/admin/mission/m-noauth/evaluate").status_code == 401

    token = backend_client.post(
        "/auth/register", json={"username": "not-an-admin", "password": "hunter2"}
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert backend_client.get("/admin/mission-options", headers=headers).status_code == 403
