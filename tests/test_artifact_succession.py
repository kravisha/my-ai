"""Artifact succession: the proposal/adoption path that renews a lens.

The expiry cycle (agents/coo.py's _evaluate_intelligence_health) already
gets active -> stale right - it flags a lens whose evidence has turned
against it. What did not exist was any way *back* to active: a stale lens
stayed stale forever, and get_active_artifact returning None for it meant
agents/explorer.py fell to the hardcoded seed permanently, not just until
someone looked at it. propose_artifact_revision, adopt_artifact_revision
and reject_artifact_revision are that other half - the Trainer's act, with
a human in the Trainer's seat until Phase D builds one.

Also covers wiring corrective actions into the live COO cycle
(agents/coo.py's _coo_work) and the three /admin/intelligence routes that
put the succession path in front of an operator.
"""

import inspect

import pytest

import agents.coo as coo
import backend.remediation as remediation
from backend import fi_db


# --- propose / adopt: the succession path itself -----------------------------

def test_a_revision_can_be_proposed_and_adopted(conn):
    old = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)

    revision_id = fi_db.propose_artifact_revision(
        conn, fi_db.LENS_IV_RATIO_NAME, 2.75,
        rationale="grades over the last 40 reports favor a tighter threshold",
        proposed_by="operator",
    )
    fi_db.adopt_artifact_revision(conn, revision_id, adopted_by="operator")

    active = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    assert active["id"] == revision_id
    assert active["value"] == "2.75"

    row = conn.fetchone("SELECT * FROM intelligence_artifacts WHERE id = ?", (old["id"],))
    assert row["status"] == "superseded"
    assert row["superseded_by"] == revision_id


def test_the_cycle_expiry_started_is_completed(conn):
    """The hole this closes: before succession, a stale lens dropped the
    organization to the hardcoded seed forever."""
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    fi_db.mark_artifact_stale(conn, lens["id"], "grades say otherwise")
    assert fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME) is None  # the seed-fallback era

    revision_id = fi_db.propose_artifact_revision(
        conn, fi_db.LENS_IV_RATIO_NAME, 3.1,
        rationale="regime drifted; new threshold observed to work", proposed_by="operator",
    )
    fi_db.adopt_artifact_revision(conn, revision_id, adopted_by="operator")

    active = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    assert active is not None
    assert active["id"] == revision_id
    assert active["value"] == "3.1"


def test_a_proposal_needs_a_rationale(conn):
    for empty in ("", "   "):
        with pytest.raises(ValueError, match="rationale"):
            fi_db.propose_artifact_revision(
                conn, fi_db.LENS_IV_RATIO_NAME, 2.75, rationale=empty, proposed_by="operator",
            )
    assert fi_db.list_artifact_revisions(conn, fi_db.LENS_IV_RATIO_NAME) == [
        fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    ]


def test_a_revision_revises_something(conn):
    with pytest.raises(ValueError, match="ever existed"):
        fi_db.propose_artifact_revision(
            conn, "no-such-lens", 1.0, rationale="a new idea", proposed_by="operator",
        )


def test_one_open_proposal_per_name(conn):
    first_id = fi_db.propose_artifact_revision(
        conn, fi_db.LENS_IV_RATIO_NAME, 2.5, rationale="first candidate", proposed_by="operator",
    )
    with pytest.raises(ValueError, match=str(first_id)):
        fi_db.propose_artifact_revision(
            conn, fi_db.LENS_IV_RATIO_NAME, 2.6, rationale="second candidate", proposed_by="operator",
        )


def test_only_a_proposed_revision_can_be_adopted(conn):
    active = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    with pytest.raises(ValueError, match="active"):
        fi_db.adopt_artifact_revision(conn, active["id"], adopted_by="operator")

    revision_id = fi_db.propose_artifact_revision(
        conn, fi_db.LENS_IV_RATIO_NAME, 2.5, rationale="candidate", proposed_by="operator",
    )
    fi_db.reject_artifact_revision(conn, revision_id, rejected_by="operator", reason="not enough evidence")
    with pytest.raises(ValueError, match="rejected"):
        fi_db.adopt_artifact_revision(conn, revision_id, adopted_by="operator")


def test_rejection_keeps_the_record(conn):
    revision_id = fi_db.propose_artifact_revision(
        conn, fi_db.LENS_IV_RATIO_NAME, 2.5, rationale="candidate", proposed_by="operator",
    )
    fi_db.reject_artifact_revision(conn, revision_id, rejected_by="operator", reason="not enough evidence yet")

    rejected = conn.fetchone("SELECT * FROM intelligence_artifacts WHERE id = ?", (revision_id,))
    assert rejected["status"] == "rejected"
    assert "not enough evidence yet" in rejected["rationale"]

    # get_active_artifact is unchanged - a rejection is not an adoption.
    active = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    assert active["value"] == fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)["value"]
    assert active["id"] != revision_id

    # the one-open rule frees once the open proposal is adjudicated
    second_id = fi_db.propose_artifact_revision(
        conn, fi_db.LENS_IV_RATIO_NAME, 2.6, rationale="second candidate", proposed_by="operator",
    )
    assert second_id != revision_id


def test_rejection_refuses_an_empty_reason(conn):
    revision_id = fi_db.propose_artifact_revision(
        conn, fi_db.LENS_IV_RATIO_NAME, 2.5, rationale="candidate", proposed_by="operator",
    )
    with pytest.raises(ValueError, match="reason"):
        fi_db.reject_artifact_revision(conn, revision_id, rejected_by="operator", reason="   ")


def test_the_succession_chain_is_readable(conn):
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    fi_db.mark_artifact_stale(conn, lens["id"], "grades say otherwise")

    first_id = fi_db.propose_artifact_revision(
        conn, fi_db.LENS_IV_RATIO_NAME, 2.5, rationale="first generation", proposed_by="operator",
    )
    fi_db.adopt_artifact_revision(conn, first_id, adopted_by="operator")

    second_id = fi_db.propose_artifact_revision(
        conn, fi_db.LENS_IV_RATIO_NAME, 2.9, rationale="second generation", proposed_by="operator",
    )
    fi_db.adopt_artifact_revision(conn, second_id, adopted_by="operator")

    chain = fi_db.list_artifact_revisions(conn, fi_db.LENS_IV_RATIO_NAME)
    versions = [row["version"] for row in chain]
    assert versions == sorted(versions, reverse=True)  # version DESC

    by_id = {row["id"]: row for row in chain}
    assert by_id[second_id]["status"] == "active"
    assert by_id[first_id]["status"] == "superseded"
    assert by_id[first_id]["superseded_by"] == second_id
    assert by_id[lens["id"]]["status"] == "superseded"
    assert by_id[lens["id"]]["superseded_by"] == first_id


def test_validity_conditions_carry_forward(conn):
    lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    revision_id = fi_db.propose_artifact_revision(
        conn, fi_db.LENS_IV_RATIO_NAME, 2.5, rationale="candidate", proposed_by="operator",
    )
    revision = conn.fetchone("SELECT * FROM intelligence_artifacts WHERE id = ?", (revision_id,))
    assert revision["validity_conditions"] == lens["validity_conditions"]


def test_evidence_ref_is_appended_to_the_rationale(conn):
    """There is no dedicated evidence column, so evidence_ref rides along in
    rationale rather than being silently dropped."""
    revision_id = fi_db.propose_artifact_revision(
        conn, fi_db.LENS_IV_RATIO_NAME, 2.5, rationale="candidate",
        proposed_by="operator", evidence_ref="lens_performance:iv_ratio_threshold",
    )
    revision = conn.fetchone("SELECT * FROM intelligence_artifacts WHERE id = ?", (revision_id,))
    assert "lens_performance:iv_ratio_threshold" in revision["rationale"]


# --- corrective actions now have a production path ---------------------------

def test_corrective_actions_now_have_a_production_path(conn):
    """The remediation findings were computed on every panel request and
    persisted never - raise_corrective_actions had no production caller.
    _coo_work now calls it every cycle, and knowledge_exists makes that
    idempotent per cause rather than noisy."""
    source = inspect.getsource(coo._coo_work)
    assert "raise_corrective_actions" in source

    fi_db.raise_corrective_actions(conn, remediation.corrective_items(conn))
    second = fi_db.raise_corrective_actions(conn, remediation.corrective_items(conn))
    assert second == []


# --- routes: the Trainer's seat, held by a human ------------------------------

def test_route_proposal_appears_in_the_intelligence_panel(panel_client, panel_conn):
    response = panel_client.post(
        f"/admin/intelligence/{fi_db.LENS_IV_RATIO_NAME}/proposals",
        json={"value": 2.75, "rationale": "grades favor a tighter threshold", "evidence_ref": None},
    )
    assert response.status_code == 200
    revision_id = response.json()["id"]

    proposals = panel_client.get("/admin/intelligence").json()["proposals"]
    assert any(p["id"] == revision_id and p["status"] == "proposed" for p in proposals)


def test_route_adoption_changes_the_active_artifact(panel_client, panel_conn):
    revision_id = panel_client.post(
        f"/admin/intelligence/{fi_db.LENS_IV_RATIO_NAME}/proposals",
        json={"value": 2.75, "rationale": "grades favor a tighter threshold"},
    ).json()["id"]

    response = panel_client.post(f"/admin/intelligence/proposals/{revision_id}/adopt")
    assert response.status_code == 200
    assert response.json()["status"] == "active"

    active = fi_db.get_active_artifact(panel_conn, fi_db.LENS_IV_RATIO_NAME)
    assert active["id"] == revision_id
    assert active["value"] == "2.75"


def test_route_rejection_requires_a_reason(panel_client, panel_conn):
    revision_id = panel_client.post(
        f"/admin/intelligence/{fi_db.LENS_IV_RATIO_NAME}/proposals",
        json={"value": 2.75, "rationale": "candidate"},
    ).json()["id"]

    empty_reason = panel_client.post(
        f"/admin/intelligence/proposals/{revision_id}/reject", json={"reason": ""},
    )
    assert empty_reason.status_code == 400

    rejected = panel_client.post(
        f"/admin/intelligence/proposals/{revision_id}/reject", json={"reason": "not convincing yet"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


def test_route_proposing_on_an_unknown_name_is_400(panel_client, panel_conn):
    response = panel_client.post(
        "/admin/intelligence/no-such-lens/proposals",
        json={"value": 1.0, "rationale": "a new idea"},
    )
    assert response.status_code == 400
