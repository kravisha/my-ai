"""The Strategy Store: the third stage of Data -> Knowledge -> Strategy
(addendum 20 §4). Knowledge is descriptive; strategy is prescriptive - what
the organization does, versioned, with the one rule this module enforces:
an active strategy resting on knowledge that is no longer active is a
finding, routed through corrective actions exactly like any other
compliance finding.
"""

import ast
import inspect

import pytest

from agents.coo import _strategy_corrective_items
from backend import fi_db, remediation, strategy


def test_the_store_opens_with_the_playbook_the_organization_executes(conn):
    """The seeded strategy is the discovery pipeline the organization already
    executes, reverse-documented rather than aspired to - the store must
    never open empty."""
    baseline = strategy.get_active(conn, strategy.BASELINE_NAME)

    assert baseline is not None
    assert baseline["status"] == "active"
    names = {ref["name"] for ref in baseline["knowledge_refs"]}
    assert names == {fi_db.LENS_IV_RATIO_NAME, fi_db.LENS_SPECULATOR_CONFIDENCE_NAME}
    for name in names:
        assert fi_db.get_active_artifact(conn, name) is not None


def test_create_validates_its_premises(conn):
    """Every refusal a strategy's premises can fail on: no statement, no
    named knowledge, knowledge that does not exist, and a second active
    version competing with the first."""
    with pytest.raises(ValueError):
        strategy.create_strategy(conn, "new_playbook", "   ", "r", [
            {"kind": "detection_lens", "name": fi_db.LENS_IV_RATIO_NAME},
        ], adopted_by="owner")

    with pytest.raises(ValueError):
        strategy.create_strategy(conn, "new_playbook", "do the thing", "r", [], adopted_by="owner")

    with pytest.raises(ValueError):
        strategy.create_strategy(conn, "new_playbook", "do the thing", "r", [
            {"kind": "detection_lens", "name": "no_such_lens"},
        ], adopted_by="owner")

    strategy_id = strategy.create_strategy(conn, "new_playbook", "do the thing", "r", [
        {"kind": "detection_lens", "name": fi_db.LENS_IV_RATIO_NAME},
    ], adopted_by="owner")
    assert strategy_id is not None

    with pytest.raises(ValueError):
        strategy.create_strategy(conn, "new_playbook", "do it again", "r", [
            {"kind": "detection_lens", "name": fi_db.LENS_IV_RATIO_NAME},
        ], adopted_by="owner")


def test_supersession_is_the_adoption_act(conn):
    """The record shows who adopted what over what, and the old text
    survives - the old row is not overwritten, it is superseded."""
    old_id = strategy.create_strategy(conn, "new_playbook", "v1 statement", "r", [
        {"kind": "detection_lens", "name": fi_db.LENS_IV_RATIO_NAME},
    ], adopted_by="owner")

    new_id = strategy.supersede_strategy(
        conn, old_id, "v2 statement", "revised rationale",
        [{"kind": "detection_lens", "name": fi_db.LENS_SPECULATOR_CONFIDENCE_NAME}],
        adopted_by="owner",
    )

    old = conn.fetchone("SELECT * FROM strategies WHERE id = ?", (old_id,))
    assert old["status"] == "superseded"
    assert old["superseded_by"] == new_id
    assert old["statement"] == "v1 statement"

    active = strategy.get_active(conn, "new_playbook")
    assert active["id"] == new_id
    assert active["version"] == 2
    assert active["status"] == "active"


def test_retirement_has_no_successor(conn):
    """Retiring is different from doing the thing differently: the
    organization stopped doing it, full stop, and the reason is on record."""
    strategy_id = strategy.create_strategy(conn, "new_playbook", "v1 statement", "r", [
        {"kind": "detection_lens", "name": fi_db.LENS_IV_RATIO_NAME},
    ], adopted_by="owner")

    strategy.retire_strategy(conn, strategy_id, "no longer relevant")

    row = conn.fetchone("SELECT * FROM strategies WHERE id = ?", (strategy_id,))
    assert row["status"] == "retired"
    assert row["retired_reason"] == "no longer relevant"
    assert strategy.get_active(conn, "new_playbook") is None


def test_unhealthy_names_every_broken_premise(conn):
    """A healthy store reports nothing. Once a linked lens goes stale, the
    finding names exactly that lens - and not the sibling lens that is still
    fine - so the adjudication addresses the real gap, not the whole
    strategy blindly."""
    assert strategy.unhealthy(conn) == []

    iv_lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    fi_db.mark_artifact_stale(conn, iv_lens["id"], "regime diverged")

    findings = strategy.unhealthy(conn)

    assert len(findings) == 1
    finding = findings[0]
    assert finding["name"] == strategy.BASELINE_NAME
    broken_names = {ref["name"] for ref in finding["broken_refs"]}
    assert broken_names == {fi_db.LENS_IV_RATIO_NAME}
    assert finding["broken_refs"][0]["status"] == "stale"


def test_the_coo_cycle_raises_the_finding_once(conn):
    """The finding becomes an ordinary corrective-action record through the
    same idempotent path every other finding uses - raising it twice must
    not double the record, per raise_corrective_actions' per-statement
    guard."""
    iv_lens = fi_db.get_active_artifact(conn, fi_db.LENS_IV_RATIO_NAME)
    fi_db.mark_artifact_stale(conn, iv_lens["id"], "regime diverged")

    items = _strategy_corrective_items(conn)
    assert len(items) == 1
    item = items[0]
    assert item.classification == remediation.SYSTEMIC
    assert item.assigned_to == remediation.OWNER
    assert strategy.BASELINE_NAME in item.statement

    fi_db.raise_corrective_actions(conn, items)
    fi_db.raise_corrective_actions(conn, _strategy_corrective_items(conn))

    corrective_rows = [
        row for row in fi_db.list_corrective_actions(conn)
        if strategy.BASELINE_NAME in row["statement"]
    ]
    assert len(corrective_rows) == 1


def test_migrations_walk_the_strategy_schema(conn):
    """strategy.SCHEMA joined apply_additive_migrations' tuple the same way
    identifiers.SCHEMA, observations.SCHEMA and risk.SCHEMA did (fi_db's own
    docstring says so) - verified the same way test_report_claiming.py
    verifies it for the base SCHEMA: drop a real strategies column from an
    existing database and confirm apply_additive_migrations puts it back,
    which is only possible if strategy.SCHEMA is part of the tuple the
    walker reads."""
    conn.execute("ALTER TABLE strategies DROP COLUMN retired_reason")
    assert "retired_reason" not in {row["name"] for row in conn.fetchall("PRAGMA table_info(strategies)")}

    applied = fi_db.apply_additive_migrations(conn)

    assert "strategies.retired_reason" in applied
    assert "retired_reason" in {row["name"] for row in conn.fetchall("PRAGMA table_info(strategies)")}


def test_strategy_does_not_import_fi_db():
    """Fourth instance of the layering rule (module docstring): fi_db.init_schema
    creates the strategies table, so strategy.py importing fi_db would close
    a cycle. No existing layering test covers risk.py (the third instance)
    to mirror, so this takes the spec's fallback form: a source-level
    assertion rather than a sys.modules dance in a subprocess.

    Parsed with `ast` rather than a plain substring search: the module's own
    docstring explains this very rule in prose ("must not import fi_db"),
    and a naive `"import fi_db" not in source` check fails against its own
    explanation. Only actual `import`/`import from` statement nodes count."""
    tree = ast.parse(inspect.getsource(strategy))
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module)
            imported_modules.update(alias.name for alias in node.names)
    assert "fi_db" not in imported_modules
    assert "backend.fi_db" not in imported_modules


def test_admin_strategies_route(panel_client, panel_conn):
    response = panel_client.get("/admin/strategies")
    body = response.json()

    assert response.status_code == 200
    assert len(body["strategies"]) >= 1
    assert any(s["name"] == strategy.BASELINE_NAME for s in body["strategies"])
    assert body["unhealthy"] == []
