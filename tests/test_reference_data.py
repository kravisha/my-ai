"""Unit tests for backend/reference_data.py - the Reference Data Engine
(addendum 24, addendum 26 subordinate; docs/SPEC_RECONCILIATION.md §39).

Fully hermetic, like tests/test_fi_db.py: the shared `conn` fixture
(tests/conftest.py) hands out an in-memory database with fi_db.init_schema
already run, which is what seeds asset_classes/identifier_rules/reference_sources
and creates the entities the seeded security_universe symbols resolve to -
everything these tests need except the engine's actual *run*, which nothing
does automatically until run_reference_engine is called.
"""

import json

import pytest

from backend import fi_db, identifiers, reference_data as rd
from backend.db import now_iso


# --- seeding idempotency -----------------------------------------------------


def test_seeding_is_idempotent(conn):
    def counts():
        return (
            conn.fetchone("SELECT COUNT(*) AS n FROM asset_classes")["n"],
            conn.fetchone("SELECT COUNT(*) AS n FROM identifier_rules")["n"],
            conn.fetchone("SELECT COUNT(*) AS n FROM reference_sources")["n"],
        )

    before = counts()
    rd.init_schema(conn)
    rd.init_schema(conn)
    assert counts() == before
    assert before == (len(rd.ASSET_CLASSES), len(rd.IDENTIFIER_RULE_SEED), len(rd.REFERENCE_SOURCE_SEED))


def test_seed_asset_classes_carry_pre_alpha_scope(conn):
    stock = conn.fetchone("SELECT * FROM asset_classes WHERE asset_class = 'stock'")
    assert stock["in_universe"] == 1
    assert stock["in_capability"] == 1
    assert stock["in_focus"] == 1

    fx = conn.fetchone("SELECT * FROM asset_classes WHERE asset_class = 'fx'")
    assert fx["in_universe"] == 1
    assert fx["in_capability"] == 0
    assert fx["in_focus"] == 0


# --- registry invariants, fail-closed ---------------------------------------


def test_set_focus_on_a_class_not_in_capability_fails_registry_invariants(conn):
    rd.set_focus(conn, "fx", True)  # fx is not in_capability
    checks = rd.validate(conn)
    invariants = next(c for c in checks if c["check"] == "registry_invariants")
    assert invariants["ok"] is False
    assert "fx" in invariants["detail"]

    result = rd.certify_readiness(conn)
    assert result["status"] == "FAILED"


def test_set_capability_and_focus_refuse_unknown_class(conn):
    with pytest.raises(ValueError):
        rd.set_capability(conn, "cryptocurrency_derivative", True)
    with pytest.raises(ValueError):
        rd.set_focus(conn, "cryptocurrency_derivative", True)


# --- engine run on the seeded universe --------------------------------------


def test_run_reference_engine_certifies_ready(conn):
    result = rd.run_reference_engine(conn)
    assert result["readiness"]["status"] == "READY"
    assert result["ingest"][0]["source"] == "security_universe"
    assert result["ingest"][0]["created"] == len(fi_db.SECURITY_UNIVERSE_SEED)


def test_master_rows_exist_for_every_active_universe_symbol(conn):
    rd.run_reference_engine(conn)
    for symbol in fi_db.SECURITY_UNIVERSE_SEED:
        entity_id = identifiers.resolve(conn, "symbol", symbol)
        assert entity_id is not None
        asset = rd.get_asset(conn, entity_id)
        assert asset is not None
        assert asset["asset_class"] == "stock"
        assert asset["active"] == 1


def test_assets_view_carries_symbol_and_focus_flag(conn):
    rd.run_reference_engine(conn)
    rows = rd.list_assets(conn)
    assert len(rows) == len(fi_db.SECURITY_UNIVERSE_SEED)
    by_symbol = {row["primary_identifier"] for row in rows}
    assert by_symbol == set(fi_db.SECURITY_UNIVERSE_SEED)
    assert all(row["in_focus"] == 1 for row in rows)
    assert all(row["asset_class"] == "stock" for row in rows)


# --- idempotent rerun ---------------------------------------------------------


def test_second_run_is_a_true_no_op(conn):
    rd.run_reference_engine(conn)
    before_entities = conn.fetchone("SELECT COUNT(*) AS n FROM entities")["n"]
    before_master = conn.fetchone("SELECT COUNT(*) AS n FROM security_master")["n"]

    result = rd.run_reference_engine(conn)

    after_entities = conn.fetchone("SELECT COUNT(*) AS n FROM entities")["n"]
    after_master = conn.fetchone("SELECT COUNT(*) AS n FROM security_master")["n"]
    assert after_entities == before_entities
    assert after_master == before_master
    assert result["ingest"][0]["created"] == 0
    assert result["ingest"][0]["updated"] == 0
    assert result["ingest"][0]["conflicts"] == 0
    assert result["readiness"]["status"] == "READY"


# --- rejection ----------------------------------------------------------------


class _OneRecordAdapter:
    def __init__(self, name, record):
        self.name = name
        self._record = record

    def records(self, conn):
        yield self._record


def test_ingest_rejects_unknown_asset_class_without_raising(conn):
    record = rd.SourceRecord(scheme="symbol", value="ZZZ", asset_class="widget")
    report = rd.ingest(conn, _OneRecordAdapter("test_source", record))
    assert report["created"] == 0
    assert len(report["rejected"]) == 1
    assert "widget" in report["rejected"][0]


def test_ingest_rejects_capability_off_class_without_raising(conn):
    record = rd.SourceRecord(scheme="symbol", value="EURUSD", asset_class="fx")
    report = rd.ingest(conn, _OneRecordAdapter("test_source", record))
    assert report["created"] == 0
    assert len(report["rejected"]) == 1
    assert "fx" in report["rejected"][0]
    assert "Capability" in report["rejected"][0]


# --- conflict handling ---------------------------------------------------------


def test_lower_authority_offer_is_recorded_but_does_not_overwrite(conn):
    conn.execute(
        "INSERT INTO reference_sources (name, kind, authority_rank, note, added_at, schema_version) "
        "VALUES ('high_authority', 'seed', 100, 'x', ?, 1)", (now_iso(),),
    )
    conn.execute(
        "INSERT INTO reference_sources (name, kind, authority_rank, note, added_at, schema_version) "
        "VALUES ('low_authority', 'seed', 10, 'x', ?, 1)", (now_iso(),),
    )
    first = rd.SourceRecord(scheme="symbol", value="ACME", asset_class="stock", name="Acme Corp")
    rd.ingest(conn, _OneRecordAdapter("high_authority", first))

    second = rd.SourceRecord(scheme="symbol", value="ACME", asset_class="stock", name="Acme Incorporated")
    report = rd.ingest(conn, _OneRecordAdapter("low_authority", second))

    assert report["conflicts"] == 1
    entity_id = identifiers.resolve(conn, "symbol", "ACME")
    asset = rd.get_asset(conn, entity_id)
    assert asset["name"] == "Acme Corp"  # unchanged - lower authority cannot overwrite
    conflicts = conn.fetchall("SELECT * FROM reference_conflicts WHERE entity_id = ?", (entity_id,))
    assert len(conflicts) == 1
    assert conflicts[0]["held_value"] == "Acme Corp"
    assert conflicts[0]["offered_value"] == "Acme Incorporated"

    # The pipeline runs on every startup; re-running the same disagreeing
    # adapter must not re-record the identical open disagreement.
    rerun = rd.ingest(conn, _OneRecordAdapter("low_authority", second))
    assert rerun["conflicts"] == 0
    conflicts = conn.fetchall("SELECT * FROM reference_conflicts WHERE entity_id = ?", (entity_id,))
    assert len(conflicts) == 1


def test_higher_authority_offer_overwrites_and_still_records_conflict(conn):
    conn.execute(
        "INSERT INTO reference_sources (name, kind, authority_rank, note, added_at, schema_version) "
        "VALUES ('low_authority', 'seed', 10, 'x', ?, 1)", (now_iso(),),
    )
    conn.execute(
        "INSERT INTO reference_sources (name, kind, authority_rank, note, added_at, schema_version) "
        "VALUES ('high_authority', 'seed', 100, 'x', ?, 1)", (now_iso(),),
    )
    first = rd.SourceRecord(scheme="symbol", value="ACME", asset_class="stock", name="Acme Corp")
    rd.ingest(conn, _OneRecordAdapter("low_authority", first))

    second = rd.SourceRecord(scheme="symbol", value="ACME", asset_class="stock", name="Acme Incorporated")
    report = rd.ingest(conn, _OneRecordAdapter("high_authority", second))

    assert report["conflicts"] == 1
    assert report["updated"] == 1
    entity_id = identifiers.resolve(conn, "symbol", "ACME")
    asset = rd.get_asset(conn, entity_id)
    assert asset["name"] == "Acme Incorporated"  # higher authority overwrote
    conflicts = conn.fetchall("SELECT * FROM reference_conflicts WHERE entity_id = ?", (entity_id,))
    assert len(conflicts) == 1
    assert conflicts[0]["held_value"] == "Acme Corp"  # the prior value is still on record


def test_same_value_offered_twice_is_not_a_conflict(conn):
    record = rd.SourceRecord(scheme="symbol", value="ACME", asset_class="stock", name="Acme Corp")
    rd.ingest(conn, _OneRecordAdapter("security_universe", record))
    report = rd.ingest(conn, _OneRecordAdapter("security_universe", record))
    assert report["conflicts"] == 0
    assert report["updated"] == 0


# --- required_identifiers ------------------------------------------------------


def test_retired_symbol_identifier_fails_certification_and_marks_row_invalid(conn):
    rd.run_reference_engine(conn)
    symbol = fi_db.SECURITY_UNIVERSE_SEED[0]
    entity_id = identifiers.resolve(conn, "symbol", symbol)
    assert identifiers.retire_identifier(conn, "symbol", symbol) is True

    result = rd.certify_readiness(conn)
    assert result["status"] == "FAILED"
    failing = next(c for c in result["checks"] if c["check"] == "required_identifiers")
    assert failing["ok"] is False
    assert entity_id in failing["detail"]
    assert rd.get_validation_status(conn, entity_id) == "invalid"

    # every other focus-class row, which still holds its identifier, is valid
    other_symbol = fi_db.SECURITY_UNIVERSE_SEED[1]
    other_entity_id = identifiers.resolve(conn, "symbol", other_symbol)
    assert rd.get_validation_status(conn, other_entity_id) == "valid"


# --- focus_coverage -------------------------------------------------------------


def test_focus_coverage_fails_below_minimum(conn):
    rd.run_reference_engine(conn)
    symbols = list(fi_db.SECURITY_UNIVERSE_SEED)
    assert len(symbols) > 3  # the seed universe is bigger than the minimum this test targets
    keep, deactivate = symbols[:3], symbols[3:]
    for symbol in deactivate:
        entity_id = identifiers.resolve(conn, "symbol", symbol)
        conn.execute("UPDATE security_master SET active = 0 WHERE entity_id = ?", (entity_id,))

    result = rd.certify_readiness(conn)
    assert result["status"] == "FAILED"
    coverage = next(c for c in result["checks"] if c["check"] == "focus_coverage")
    assert coverage["ok"] is False
    assert result["focus_asset_count"] == 3
    assert len(keep) == 3


# --- is_ready / latest_readiness ------------------------------------------------


def test_is_ready_false_before_any_run(conn):
    assert rd.is_ready(conn) is False
    assert rd.latest_readiness(conn) is None


def test_is_ready_true_after_a_ready_run(conn):
    rd.run_reference_engine(conn)
    assert rd.is_ready(conn) is True
    latest = rd.latest_readiness(conn)
    assert latest["status"] == "READY"
    assert isinstance(latest["checks"], list)
    assert latest["checks"][0]["check"] == "registry_invariants"


# --- consumer interface ----------------------------------------------------------


def test_get_asset_returns_identifiers(conn):
    rd.run_reference_engine(conn)
    symbol = fi_db.SECURITY_UNIVERSE_SEED[0]
    entity_id = identifiers.resolve(conn, "symbol", symbol)
    asset = rd.get_asset(conn, entity_id)
    assert asset is not None
    assert any(i["scheme"] == "symbol" and i["value"] == symbol for i in asset["identifiers"])


def test_get_asset_returns_none_for_unknown_entity(conn):
    assert rd.get_asset(conn, "JE-999999") is None


def test_list_focus_assets_length_matches_focus_universe(conn):
    rd.run_reference_engine(conn)
    assert len(rd.list_focus_assets(conn)) == len(fi_db.SECURITY_UNIVERSE_SEED)


def test_status_shape(conn):
    rd.run_reference_engine(conn)
    result = rd.status(conn)
    assert set(result) == {"ready", "latest", "assets", "focus_assets", "conflicts", "focus_classes"}
    assert result["ready"] is True
    assert result["assets"] == len(fi_db.SECURITY_UNIVERSE_SEED)
    assert result["focus_assets"] == len(fi_db.SECURITY_UNIVERSE_SEED)
    assert result["conflicts"] == 0
    assert set(result["focus_classes"]) == {"stock", "stock_option"}


# --- view reconciliation ----------------------------------------------------------


def test_stale_assets_view_is_reconciled_on_init_schema(tmp_path):
    """Installs an old-shape `assets` view over a real, fully-initialized
    database - as if this module's view definition changed after the
    database was created - then confirms init_schema notices and replaces
    it, the same guarantee fi_db._reconcile_triggers gives triggers."""
    connection = fi_db.get_connection(tmp_path / "stale_view.db")
    try:
        fi_db.init_schema(connection)
        connection.execute("DROP VIEW assets")
        connection.execute("CREATE VIEW assets AS SELECT entity_id FROM security_master")

        stale = connection.fetchone("SELECT sql FROM sqlite_master WHERE type = 'view' AND name = 'assets'")
        assert stale is not None and "primary_identifier" not in stale["sql"]

        fi_db.init_schema(connection)

        row = connection.fetchone("SELECT sql FROM sqlite_master WHERE type = 'view' AND name = 'assets'")
        assert "primary_identifier" in row["sql"]
        # the reconciled view must actually be queryable with the current columns
        result = connection.fetchall("SELECT entity_id, asset_class, primary_identifier, active, in_focus FROM assets")
        assert result == []
    finally:
        connection.close()
