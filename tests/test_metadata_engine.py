"""The Metadata Engine (backend/metadata_engine.py, addendum 39 §7/§12/§13/§14;
TQ-23, SPEC_RECONCILIATION §72).

Three things this suite holds. **Idempotency** (39 §13) is the loudest: running
startup repeatedly must not duplicate anything, must not overwrite a name
assignment, and must not reset agent identity — a fresh developer run, a crash
restart and a clean restart must all be safe. **The gate** (39 §14): the
Reference Data Engine must not begin work before METADATA_READY, which is the
one strict ordering constraint the specification has. And **honest failure**
(38 §12): a failed metadata pass must be visible and must not let dependents
report success.
"""

import json

import pytest

from backend import boot_config, fi_db, metadata_engine, reference_data

VALID = {
    "lifecycle_stage": "PRE_ALPHA",
    "global_asset_classes": ["stock", "stock_option", "etf"],
    "implemented_asset_classes": ["stock", "stock_option"],
    "current_focus": ["PRE_ALPHA_STARTUP_OBSERVABILITY"],
    "simulation_focus": ["OPTIONS_ON_EQUITIES_PRICING"],
}


def _config(tmp_path, **overrides):
    data = {**VALID, **overrides}
    path = tmp_path / "boot_config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return boot_config.load(path)


def _messages(report):
    return " | ".join(event["message"] for event in report["events"])


def _types(report):
    return [event["event_type"] for event in report["events"]]


# --- 39 §12's algorithm, in order -------------------------------------------------


def test_run_publishes_the_required_sequence(conn, tmp_path):
    """39 §12: starting → boot config → four datasets → summary → ready →
    idle. The order is the spec's, not an implementation detail: an operator
    reading the feed is watching a startup narrated in sequence."""
    report = metadata_engine.run(conn, _config(tmp_path))
    types = _types(report)

    assert types[0] == metadata_engine.STATE_STARTING
    assert types[1] == "boot_config_loaded"
    assert types[-3] == "metadata_summary"
    assert types[-2] == metadata_engine.STATE_READY
    assert types[-1] == metadata_engine.STATE_IDLE
    assert report["ready"] is True
    assert report["state"] == metadata_engine.STATE_IDLE


def test_all_four_required_datasets_are_verified(conn, tmp_path):
    """39 §7's four datasets, each named as the specification names it so a
    reader holding the spec can find its verification."""
    report = metadata_engine.run(conn, _config(tmp_path))
    verified = {e.get("dataset") for e in report["events"] if e.get("dataset")}
    assert verified == set(metadata_engine.REQUIRED_DATASETS)


def test_summary_carries_the_four_counts(conn, tmp_path):
    """39 §12 step 8, verbatim field names."""
    report = metadata_engine.run(conn, _config(tmp_path))
    assert set(report["counts"]) == {
        "names_available", "global_asset_classes", "implemented_items", "active_focus_items",
    }
    summary = next(e for e in report["events"] if e["event_type"] == "metadata_summary")
    for field in report["counts"]:
        assert f"{field}=" in summary["message"]
    # Real numbers, not zeros dressed up as a report.
    assert report["counts"]["names_available"] > 0
    assert report["counts"]["global_asset_classes"] >= 2


def test_lifecycle_stage_is_published(conn, tmp_path):
    """38 §2: the stage must be observable at startup."""
    report = metadata_engine.run(conn, _config(tmp_path))
    assert report["lifecycle_stage"] == "PRE_ALPHA"
    assert any(e.get("lifecycle_stage") == "PRE_ALPHA" for e in report["events"])
    assert "PRE_ALPHA" in _messages(report)


# --- 39 §13 idempotency -----------------------------------------------------------


def test_repeated_runs_change_nothing(conn, tmp_path):
    """"Running startup multiple times must NOT duplicate asset classes,
    duplicate names, ... duplicate focus rows unnecessarily." Counted rather
    than assumed."""
    config = _config(tmp_path)
    first = metadata_engine.run(conn, config)
    rows_before = conn.fetchone("SELECT COUNT(*) AS n FROM asset_classes")["n"]
    names_before = conn.fetchone("SELECT COUNT(*) AS n FROM agent_names")["n"]

    for _ in range(3):
        again = metadata_engine.run(conn, config)
        assert again["counts"] == first["counts"]

    assert conn.fetchone("SELECT COUNT(*) AS n FROM asset_classes")["n"] == rows_before
    assert conn.fetchone("SELECT COUNT(*) AS n FROM agent_names")["n"] == names_before


def test_a_second_run_reports_no_corrections(conn, tmp_path):
    """The reconciliation is announced only when it actually does something -
    a startup that corrected nothing must not claim it did."""
    config = _config(tmp_path)
    metadata_engine.run(conn, config)
    second = metadata_engine.run(conn, config)
    assert not [e for e in second["events"] if e["event_type"] == "dataset_reconciled"]
    assert all(e["severity"] == metadata_engine.SEVERITY_INFO for e in second["events"])


def test_existing_agent_name_assignments_survive(conn, tmp_path):
    """39 §13's sharpest clause: metadata startup must not "overwrite
    existing name assignments" or "reset agent identity". A named agent must
    come back with the same name after any number of restarts."""
    fi_db.register_agent(conn, "explorer-1", "explorer", 100)
    name = fi_db.get_agent_name(conn, "explorer-1")
    assert name

    config = _config(tmp_path)
    for _ in range(3):
        metadata_engine.run(conn, config)

    assert fi_db.get_agent_name(conn, "explorer-1") == name
    assert conn.fetchone(
        "SELECT COUNT(*) AS n FROM agent_names WHERE assigned_to_identity = ?", ("explorer-1",)
    )["n"] == 1


def test_available_name_count_reflects_assignment(conn, tmp_path):
    before = metadata_engine.run(conn, _config(tmp_path))["counts"]["names_available"]
    fi_db.register_agent(conn, "explorer-1", "explorer", 100)
    after = metadata_engine.run(conn, _config(tmp_path))["counts"]["names_available"]
    assert after == before - 1


# --- 39 §10: nothing falsely marked implemented -----------------------------------


def test_boot_config_is_the_authority_on_what_is_implemented(conn, tmp_path):
    """Two declarations of one fact is what this codebase refuses; the rule
    is that boot configuration wins, and the correction is announced rather
    than performed silently."""
    reference_data.set_capability(conn, "fx", True)          # falsely implemented
    reference_data.set_capability(conn, "stock_option", False)  # falsely not

    report = metadata_engine.run(conn, _config(tmp_path))

    reconciled = [e for e in report["events"] if e["event_type"] == "dataset_reconciled"]
    assert len(reconciled) == 1
    assert reconciled[0]["severity"] == metadata_engine.SEVERITY_WARNING
    assert "fx=off" in reconciled[0]["message"]
    assert "stock_option=on" in reconciled[0]["message"]

    implemented = {
        row["asset_class"] for row in
        conn.fetchall("SELECT asset_class FROM asset_classes WHERE in_capability = 1")
    }
    assert implemented == {"stock", "stock_option"}


def test_the_two_declarations_of_implemented_scope_agree():
    """`reference_data.CAPABILITY_FOCUS_CLASSES` seeds a fresh database and
    `boot_config.json` declares the same fact for operators. They are pinned
    equal here so they cannot drift apart unnoticed — the drift-guard
    discipline docs/organization.yaml and docs/model_registry.yaml already
    apply to their own claims."""
    shipped = set(boot_config.load().implemented_asset_classes)
    assert shipped == reference_data.CAPABILITY_FOCUS_CLASSES


# --- 38 §12: honest failure -------------------------------------------------------


def test_unloadable_boot_config_fails_visibly_without_raising(conn, tmp_path, monkeypatch):
    """A failed component must be visible, not an exception escaping into
    startup — and `ready=False` is what stops dependents reporting success."""
    monkeypatch.setenv(boot_config.PATH_ENV, str(tmp_path / "absent.json"))
    report = metadata_engine.run(conn)

    assert report["ready"] is False
    assert report["state"] == metadata_engine.STATE_FAILED
    failure = report["events"][-1]
    assert failure["severity"] == metadata_engine.SEVERITY_ERROR
    assert failure["status"] == metadata_engine.STATUS_FAILED
    assert "does not exist" in failure["message"]
    # It failed before claiming any dataset was verified.
    assert not [e for e in report["events"] if e["event_type"] == "dataset_verified"]


def test_exhausted_name_pool_is_a_warning_not_a_silent_pass(conn, tmp_path):
    """The pool running out stops agent creation; it must be visible before
    somebody wonders why no agent can be named."""
    conn.execute("UPDATE agent_names SET reserved = 1")
    report = metadata_engine.run(conn, _config(tmp_path))
    names_event = next(
        e for e in report["events"] if e.get("dataset") == metadata_engine.DATASET_AGENT_NAMES
    )
    assert names_event["severity"] == metadata_engine.SEVERITY_WARNING
    assert "exhausted" in names_event["message"]
    assert report["counts"]["names_available"] == 0


# --- 39 §14: the hard gate --------------------------------------------------------


def test_startup_gates_reference_data_on_metadata_readiness():
    """The one strict ordering constraint in the specification, asserted
    against the startup source rather than by running a server: the
    reference engine call must sit inside the `ready` branch.

    A source assertion because this repository's TestClient has a known
    lifespan-thread quirk (backend/main.py's own lifespan docstring), which
    is why `_reference_allows_bootstrap` was extracted as a pure function in
    the first place."""
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "backend" / "main.py").read_text(
        encoding="utf-8"
    )
    metadata_at = source.index("metadata = metadata_engine.run(")
    gate_at = source.index('if not metadata["ready"]:')
    reference_at = source.index("reference_data.run_reference_engine(")
    assert metadata_at < gate_at < reference_at, (
        "reference data must start only after METADATA_READY (addendum 39 §14)"
    )
    # The reference engine must sit in the else-branch of that gate, not merely
    # after it in the file - "later in the source" is not "only when ready".
    gated_region = source[gate_at:reference_at]
    assert "\n    else:" in gated_region, (
        "run_reference_engine must be inside the not-ready gate's else branch"
    )


def test_format_events_renders_a_feed_line(conn, tmp_path):
    """39 §18's displayable lines; formatting lives in the engine so the
    eventual status stream and today's startup print cannot diverge."""
    report = metadata_engine.run(conn, _config(tmp_path))
    lines = metadata_engine.format_events(report["events"])
    assert len(lines) == len(report["events"])
    assert "Metadata Engine starting" in lines[0]
    assert "[INFO]" in lines[0]
    assert "Metadata ready" in " ".join(lines)
    assert "Metadata Engine idle" in lines[-1]
