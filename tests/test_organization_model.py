"""docs/organization.yaml must describe the organization that actually exists.

An org chart maintained by hand drifts, and a drifted chart is worse than none
because it is still believed. These tests make the chart an assertion: a role
declared but not implemented, a role implemented but not declared, or a role
whose spawn path disagrees with the model, all fail here.

The check that earns the file's keep is `known_gap`. Every flow must declare
either the flow that closes it, why closure is unnecessary, or that the loop is
knowingly open - and the number of knowingly-open loops is pinned. Adding an
outbound flow with no return path fails until someone raises the count on
purpose, which turns "we should really close that loop someday" from a good
intention into a recorded decision.

Internal rationale: INT-PHIL-0017
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

from agents import coo
from backend import fi_db

MODEL_PATH = Path(__file__).resolve().parent.parent / "docs" / "organization.yaml"

VALID_KINDS = {"authority", "lifecycle", "work", "feedback", "evaluation", "knowledge"}
CLOSURE_KEYS = ("return_path", "no_feedback_required", "known_gap")


@pytest.fixture(scope="module")
def model():
    return yaml.safe_load(MODEL_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def roles(model):
    return {role["id"]: role for role in model["roles"]}


@pytest.fixture(scope="module")
def flows(model):
    return {flow["id"]: flow for flow in model["flows"]}


def test_model_parses_and_has_both_sections(model):
    assert model["version"] == 1
    assert model["roles"], "an organization with no roles is not a model of this one"
    assert model["flows"]


def test_every_declared_role_is_implemented(roles):
    """A role in the chart that does not exist in code is the drift this file exists to catch."""
    for role_id, role in roles.items():
        assert role["status"] == "implemented", (
            f"{role_id} is declared with status {role['status']!r}. This file models only what "
            "runs; planned roles belong in the private organization model."
        )
        assert role_id in fi_db.ROLE_CHARTERS, f"{role_id} is declared here but has no charter in fi_db"


def test_every_implemented_role_is_declared(roles):
    """The reverse direction: a role added to the code without being modelled."""
    undeclared = set(fi_db.ROLE_CHARTERS) - set(roles)
    assert not undeclared, f"roles exist in ROLE_CHARTERS but are absent from the org model: {sorted(undeclared)}"


def test_spawn_paths_agree_with_coo(roles):
    """`spawned_by_coo` must match BASELINE_ROLES in both directions.

    The Controller is the running server, so a COO that tried to respawn it would
    ask the Controller to launch an agents/controller.py that deliberately does
    not exist. That invariant is guarded in tests/test_controller.py; this
    catches it from the other side, as a modelling error rather than a crash.

    **`spawned_by_coo` means "in the baseline workforce", not "COO can spawn
    it".** Those were the same thing until TQ-79 added an on-demand role, and
    this test is how the difference surfaced: `portfolio_analyst` is spawned by
    COO like every other subprocess and is *not* baseline, because it is created
    when a client asks and produces nothing when nobody has (§115). A baseline
    analyst would sit idle forever waiting for work that arrives from outside
    the organization rather than from inside it."""
    declared_spawned = {role_id for role_id, role in roles.items() if role["spawned_by_coo"]}
    assert declared_spawned == set(coo.BASELINE_ROLES), (
        f"model says COO spawns {sorted(declared_spawned)}, BASELINE_ROLES says {sorted(coo.BASELINE_ROLES)}"
    )


def test_an_on_demand_role_is_not_in_the_baseline_workforce(roles):
    """The other side of the distinction above, so that neither can drift.

    An on-demand role added to `BASELINE_ROLES` would be started at every server
    boot and would idle forever - and nothing else in the model would object,
    because "COO spawns it" would still be true."""
    on_demand = {role_id for role_id, role in roles.items() if role.get("on_demand")}
    assert on_demand, "the model no longer describes any on-demand role"
    overlap = on_demand & set(coo.BASELINE_ROLES)
    assert not overlap, (
        f"{sorted(overlap)} are on-demand but in the baseline workforce; they would be "
        "started at boot and idle forever")


def test_controller_is_in_process_and_reports_to_nobody(roles):
    assert roles["controller"]["process"] == "in_process"
    assert roles["controller"]["reports_to"] is None


def test_flow_endpoints_are_real_roles(flows, roles):
    for flow_id, flow in flows.items():
        for end in ("from", "to"):
            assert flow[end] in roles, f"flow {flow_id} names unknown role {flow[end]!r} as {end}"


def test_flow_kinds_are_known(flows):
    for flow_id, flow in flows.items():
        assert flow["kind"] in VALID_KINDS, f"flow {flow_id} has unrecognised kind {flow['kind']!r}"


def test_flow_media_are_real_tables(flows):
    """A flow travels over a table. If the table is gone, the flow is fiction."""
    tables = set(fi_db.list_tables_in_schema())
    for flow_id, flow in flows.items():
        assert flow["medium"] in tables, f"flow {flow_id} travels over {flow['medium']!r}, which is not a table"


def test_every_flow_declares_exactly_one_closure(flows):
    for flow_id, flow in flows.items():
        declared = [key for key in CLOSURE_KEYS if key in flow]
        assert len(declared) == 1, (
            f"flow {flow_id} declares {declared or 'no'} closure. Exactly one of "
            f"{CLOSURE_KEYS} is required - an outbound flow with no stated return path is the "
            "one-way dependency this model exists to surface."
        )


def test_return_paths_point_at_real_flows(flows):
    for flow_id, flow in flows.items():
        target = flow.get("return_path")
        if target is not None:
            assert target in flows, f"flow {flow_id} returns via {target!r}, which is not a flow"
            assert target != flow_id, f"flow {flow_id} closes itself, which closes nothing"


def test_known_gap_count_is_pinned(model, flows):
    """The ratchet.

    Every knowingly-unclosed loop is counted. A new one fails this test until the
    count is raised deliberately, and closing one fails it until the count is
    lowered - so the number can only move when somebody means it to."""
    gaps = sorted(flow_id for flow_id, flow in flows.items() if "known_gap" in flow)
    assert len(gaps) == model["known_gap_count"], (
        f"model pins known_gap_count={model['known_gap_count']} but {len(gaps)} flows declare a "
        f"known gap: {gaps}"
    )


def test_known_gaps_explain_themselves(flows):
    for flow_id, flow in flows.items():
        gap = flow.get("known_gap")
        if gap is not None:
            assert len(gap.split()) >= 15, (
                f"flow {flow_id}'s known_gap is too short to be a diagnosis. An unclosed loop is "
                "recorded so it can be argued about later, which needs the reason, not the label."
            )


def test_the_acting_ceo_capacity_is_bounded_in_the_charter():
    """Owner decision, 2026-08-17: COO acts for the CEO while that office is vacant.

    The bound is the part worth guarding. COO manages the specialists, so a COO
    that also inherited the CEO's job of challenging their assumptions would be
    checking its own reports - which is not a check. The charter records the
    capacity and its limit together, and this fails if either is dropped or the
    capacity is silently widened."""
    charter = fi_db.ROLE_CHARTERS["coo"]

    acting = [entry for entry in charter["allowed"] if "Act for the CEO" in entry]
    assert len(acting) == 1
    assert "structural and staffing" in acting[0]

    limits = " ".join(charter["not_allowed"])
    assert "judgment role" in limits, "the acting capacity has no stated limit"
    assert "once the office is filled" in limits, "nothing says when the capacity ends"
