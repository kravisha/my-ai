"""The market-implied cross-check (backend/reference_data.py, TQ-15,
SPEC_RECONCILIATION §62): reference-data validation's first check against
something other than this database's own consistency - the declared carry
inputs tested against the executable bands ARB-015/016 imply from stored
option quotes, with disagreements recorded as reference_conflicts under the
registered 'market_implied' source.

The load-bearing properties: agreement is silent, disagreement is recorded
once per distinct fact (idempotent across re-certifications), a changed
market is a new fact, and NOTHING here ever blocks readiness or flips a
validation_status - a diagnostic is a disagreement between two sources, not
proof the declaration is wrong ("difference alone is not arbitrage" cuts
both ways)."""

import pytest

from backend import observations as observation_store
from backend import reference_data as rd
from simulation import parity_world as pw


def _check(readiness, name="market_implied_consistency"):
    matches = [c for c in readiness["checks"] if c["check"] == name]
    assert len(matches) == 1
    return matches[0]


def _store_chain(conn, seed=1, base_time=pw.BASE_TIME_DEFAULT, mutate=None):
    """One clean ('none'-variant) scenario's option-chain observation for a
    focus asset, optionally payload-mutated before storing - the mutation IS
    the misdeclaration under test, since the world's own chains agree with
    their own carry by construction."""
    config = pw.MissionConfig(
        mission_id=f"m-refval-{seed}", run_mode="simulation",
        strategy=pw.STRATEGY_PARITY, seed=seed, n_scenarios=1,
        scenario_mix={pw.VARIANT_NONE: 1.0}, base_time=base_time,
    )
    scenario = pw._build_scenario(config, rd.list_focus_assets(conn), 0)
    observation = pw.build_option_chain_observation(scenario, config)
    if mutate is not None:
        mutate(observation.payload)
    assert observation_store.store(conn, observation) is True
    return scenario


def _bump_pv_div(amount, expiry_days=30):
    def mutate(payload):
        for row in payload["carry"]["pv_div_by_expiry"]:
            if row["expiry_days"] == expiry_days:
                row["pv_div"] += amount
    return mutate


def test_no_stored_chains_is_nothing_to_cross_check(conn):
    readiness = rd.run_reference_engine(conn)["readiness"]
    check = _check(readiness)
    assert check["ok"] is True
    assert "no stored chain" in check["detail"]
    assert "no disagreements" in check["detail"]
    assert rd.market_implied_conflicts(conn) == []


def test_agreeing_declaration_records_nothing(conn):
    """The world's own chains carry the very inputs they were priced from:
    every declaration sits inside its executable band, and the cross-check
    has nothing to say - the clean-world control."""
    rd.run_reference_engine(conn)
    _store_chain(conn, seed=3)
    readiness = rd.certify_readiness(conn)
    check = _check(readiness)
    assert "1 asset(s) cross-checked" in check["detail"]
    assert "no disagreements" in check["detail"]
    assert rd.market_implied_conflicts(conn) == []


def test_misdeclared_dividend_is_found_recorded_and_deduplicated(conn):
    rd.run_reference_engine(conn)
    scenario = _store_chain(conn, seed=5, mutate=_bump_pv_div(3.0))

    readiness = rd.certify_readiness(conn)
    check = _check(readiness)
    assert f"{scenario.symbol} pv_div@30d" in check["detail"]

    conflicts = rd.market_implied_conflicts(conn, scenario.entity_id)
    pv_rows = [c for c in conflicts if c["field"] == "pv_div"]
    assert len(pv_rows) == 1  # one disagreement, per (asset, field, expiry) - not per strike
    row = pv_rows[0]
    assert row["offering_source"] == "market_implied"
    assert row["offered_value"]["detector_id"] == "ARB-015"
    assert row["offered_value"]["expiry_days"] == 30
    assert row["offered_value"]["n_strikes"] >= 1
    # The declared value sits above the recorded band by construction.
    assert float(row["held_value"]) > row["offered_value"]["implied_high"]

    # Idempotent: the same certification against the same observation adds
    # nothing - the row already says these two sources disagree.
    before = len(rd.market_implied_conflicts(conn))
    rd.certify_readiness(conn)
    assert len(rd.market_implied_conflicts(conn)) == before


def test_misdeclared_rate_is_found_under_its_own_field(conn):
    rd.run_reference_engine(conn)

    def bump_r(payload):
        payload["carry"]["r"] += 0.5

    scenario = _store_chain(conn, seed=7, mutate=bump_r)
    rd.certify_readiness(conn)
    fields = {c["field"] for c in rd.market_implied_conflicts(conn, scenario.entity_id)}
    assert "r" in fields
    r_rows = [c for c in rd.market_implied_conflicts(conn, scenario.entity_id) if c["field"] == "r"]
    assert all(c["offered_value"]["detector_id"] == "ARB-016" for c in r_rows)


def test_disagreement_never_blocks_readiness_or_validity(conn):
    """The discipline the whole check hangs on: a market disagreement is
    data. Readiness stays READY, the check stays ok, and the asset's
    validation_status stays 'valid' - 'invalid' means structurally broken,
    which a healthy record with a contested dividend is not."""
    rd.run_reference_engine(conn)
    scenario = _store_chain(conn, seed=9, mutate=_bump_pv_div(3.0))
    readiness = rd.certify_readiness(conn)
    assert readiness["status"] == "READY"
    assert _check(readiness)["ok"] is True
    assert rd.get_validation_status(conn, scenario.entity_id) == "valid"


def test_a_changed_band_is_a_new_fact(conn):
    """Dedup is per distinct disagreement, not per (asset, field): a later
    observation whose market moved records a new row rather than being
    swallowed by the old one - append-only history, the reference_conflicts
    contract."""
    rd.run_reference_engine(conn)
    scenario = _store_chain(conn, seed=11, mutate=_bump_pv_div(3.0))
    rd.certify_readiness(conn)
    first = len(rd.market_implied_conflicts(conn, scenario.entity_id))
    assert first >= 1

    _store_chain(conn, seed=11, base_time="2026-01-06T14:30:00+00:00", mutate=_bump_pv_div(4.0))
    rd.certify_readiness(conn)
    assert len(rd.market_implied_conflicts(conn, scenario.entity_id)) > first


def test_undiagnosable_observation_is_named_not_fatal(conn):
    """One malformed stored chain must not take down certification: the
    asset's error is named in the check detail, the check stays ok, and the
    engine still certifies READY - blocking the whole organization on one
    broken observation would be the outage the guard exists to prevent."""
    rd.run_reference_engine(conn)
    _store_chain(conn, seed=13, mutate=lambda payload: payload.pop("carry"))
    readiness = rd.certify_readiness(conn)
    assert readiness["status"] == "READY"
    check = _check(readiness)
    assert check["ok"] is True
    assert "cross-check error" in check["detail"]
    assert rd.market_implied_conflicts(conn) == []


def test_market_implied_is_a_registered_source_ranked_below_declarers(conn):
    rd.run_reference_engine(conn)
    row = conn.fetchone("SELECT * FROM reference_sources WHERE name = 'market_implied'")
    assert row is not None
    assert row["kind"] == "derived"
    others = conn.fetchall("SELECT authority_rank FROM reference_sources WHERE name != 'market_implied'")
    assert all(row["authority_rank"] < other["authority_rank"] for other in others)
