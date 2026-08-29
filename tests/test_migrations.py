"""The migration pipeline and the escape hatches (backend/migrations.py;
addendum 42 §7-§10, §14, §22, §23; TQ-36, SPEC_RECONCILIATION §89).

## Why this suite registers a store that does not exist

Both real stores are at version 1 and declare no migration steps, because
neither has changed shape yet. A suite that only exercised them would prove the
engine can decline to do anything.

So most of what follows registers a `probe` store with genuine 1->2 and 2->3
steps. That is not a mock standing in for the real thing - it is the engine's
first user, and it exists because §23's ordering has to be trusted *before* the
first real migration rather than debugged during it. The day a real store gains
a step, these tests are what says the ladder underneath it works.

The properties being held are the ones that make a migration safe rather than
merely functional: a missing rung stops rather than skips, a failure leaves
nothing applied, state from the future is never reset, and every attempt -
including the failures - is on the record.
"""

import dataclasses
import json

import pytest

from backend import coo_identity, fi_db, migrations, workspace
from backend.migrations import (
    HatchRefused, MissingMigration, OUTCOME_FAILED, OUTCOME_MIGRATED,
    StateFromTheFuture, Store, ValidationFailed,
)


@pytest.fixture
def conn(tmp_path):
    connection = fi_db.get_connection(str(tmp_path / "fi.db"))
    fi_db.init_schema(connection)
    connection.executescript(
        "CREATE TABLE IF NOT EXISTS probe (id INTEGER PRIMARY KEY, value TEXT, "
        "schema_version INTEGER NOT NULL DEFAULT 1);")
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def probe(conn, monkeypatch):
    """A store with a real ladder: 1->2 upper-cases, 2->3 appends a marker.

    Registered into a copy of the registry so the real stores are untouched and
    tests cannot leak into one another."""
    monkeypatch.setattr(migrations, "_REGISTRY", dict(migrations._REGISTRY))

    def step_1_to_2(c):
        for row in c.fetchall("SELECT id, value FROM probe"):
            c.execute("UPDATE probe SET value = ? WHERE id = ?",
                      (row["value"].upper(), row["id"]))

    def step_2_to_3(c):
        for row in c.fetchall("SELECT id, value FROM probe"):
            c.execute("UPDATE probe SET value = ? WHERE id = ?",
                      (row["value"] + "!", row["id"]))

    store = migrations.register(Store(
        name="probe",
        table="probe",
        code_version=3,
        read_version=lambda c: (c.fetchone("SELECT MIN(schema_version) AS v FROM probe") or {}).get("v"),
        write_version=lambda c, v: c.execute("UPDATE probe SET schema_version = ?", (v,)),
        validate=lambda c: [] if c.fetchone("SELECT COUNT(*) AS n FROM probe")["n"] else ["empty"],
        inspect=lambda c: c.fetchall("SELECT * FROM probe"),
        migrations={1: step_1_to_2, 2: step_2_to_3},
    ))
    conn.execute("INSERT INTO probe (id, value, schema_version) VALUES (1, 'hello', 1)")
    return store


def _with(store, **changes):
    """A variant of a registered store, registered in its place.

    `Store` is frozen on purpose - a migration ladder that could be edited at
    runtime is a ladder nobody can reason about - so a test that needs a
    different ladder builds one rather than reaching into this one."""
    return migrations.register(dataclasses.replace(store, **changes))


def _value(conn):
    return conn.fetchone("SELECT value FROM probe WHERE id = 1")["value"]


def _version(conn):
    return conn.fetchone("SELECT schema_version FROM probe WHERE id = 1")["schema_version"]


# --- §8/§9: sequential steps, composed by the runner ------------------------------


def test_the_ladder_is_walked_one_rung_at_a_time(conn, probe):
    """§8's worked example: state at 1, code at 3, so 1->2 then 2->3 - not one
    converter that knows about both."""
    assert migrations.plan(probe, 1) == [(1, 2), (2, 3)]

    results = migrations.migrate(conn, store_name="probe", backup=False)

    assert results[0]["action"] == "migrated"
    assert results[0]["steps"] == [(1, 2), (2, 3)]
    # Both steps ran, in order: upper-cased first, then suffixed.
    assert _value(conn) == "HELLO!"
    assert _version(conn) == 3


def test_a_partial_ladder_starts_where_the_state_is(conn, probe):
    """State already at 2 runs only the remaining rung. A migration that
    re-applied earlier steps would corrupt exactly the data it was given to
    protect."""
    conn.execute("UPDATE probe SET value = 'HELLO', schema_version = 2")
    migrations.migrate(conn, store_name="probe", backup=False)
    assert _value(conn) == "HELLO!", "1->2 must not have run a second time"


def test_a_missing_rung_stops_rather_than_skipping(conn, probe, monkeypatch):
    """The failure mode that matters: skipping 2->3 would hand version-3 code a
    version-2 shape with the version column claiming the conversion happened.
    Refusing is inconvenient; skipping is corruption."""
    partial = _with(probe, migrations={1: probe.migrations[1]})

    with pytest.raises(MissingMigration, match="2 -> 3"):
        migrations.plan(partial, 1)

    results = migrations.migrate(conn, store_name="probe", backup=False)
    assert results[0]["action"] == "refused"
    assert _value(conn) == "hello", "nothing should have been applied"


def test_a_missing_rung_cannot_be_forced(conn, probe, monkeypatch):
    """`--force` re-runs steps a developer has edited. It must not invent one:
    forcing here would corrupt rather than inconvenience."""
    _with(probe, migrations={})
    results = migrations.migrate(conn, store_name="probe", backup=False, force=True)
    assert results[0]["action"] == "refused"


# --- §22: state from the future is never reset -------------------------------------


def test_state_from_a_newer_build_is_left_alone(conn, probe):
    """Not corruption, and the remedy is not a reset. Overwriting a newer
    build's state because this one cannot read it destroys exactly what §22
    says to preserve."""
    conn.execute("UPDATE probe SET schema_version = 9")

    with pytest.raises(StateFromTheFuture):
        migrations.plan(probe, 9)

    results = migrations.migrate(conn, store_name="probe", backup=False, force=True)
    assert results[0]["action"] == "refused"
    assert _version(conn) == 9, "the newer state must be untouched"
    assert _value(conn) == "hello"


# --- §23: nothing is half-applied ---------------------------------------------------


def test_a_failure_mid_ladder_leaves_nothing_applied(conn, probe, monkeypatch):
    """The reason `Database.transaction` was added. Step 1 succeeds, step 2
    raises; without the transaction the first would stand while the version
    column said neither had run."""
    def explodes(_c):
        raise RuntimeError("disk caught fire")

    _with(probe, migrations={1: probe.migrations[1], 2: explodes})

    results = migrations.migrate(conn, store_name="probe", backup=False)

    assert results[0]["action"] == "failed"
    assert _value(conn) == "hello", "step 1 must have been rolled back"
    assert _version(conn) == 1, "the version must still describe the data"


def test_state_that_fails_validation_after_migrating_is_rolled_back(conn, probe, monkeypatch):
    """§23: "Validate migrated state. Only then mark the new state active."
    A migration that produces something unusable must not be activated."""
    _with(probe, validate=lambda c: [] if _value(c) == "hello" else ["ruined it"])

    results = migrations.migrate(conn, store_name="probe", backup=False)

    assert results[0]["action"] == "failed"
    assert "ruined it" in results[0]["reason"]
    assert _value(conn) == "hello" and _version(conn) == 1


def test_source_state_that_does_not_validate_is_refused(conn, probe, monkeypatch):
    """§23 validates the *source* first. A migration is a poor moment to
    discover the input was already broken."""
    _with(probe, validate=lambda c: ["was broken before we started"])
    results = migrations.migrate(conn, store_name="probe", backup=False)
    assert results[0]["action"] == "refused"
    assert "did not validate" in results[0]["reason"]


def test_migrating_without_a_backup_is_refused_by_default(conn, probe, monkeypatch):
    """§23 asks for a pre-migration snapshot. When one cannot be taken the
    default is to stop - a developer who accepts the risk says so explicitly."""
    monkeypatch.setattr(migrations, "_pre_upgrade_backup",
                        lambda: (None, "no destination configured"))
    results = migrations.migrate(conn, store_name="probe")
    assert results[0]["action"] == "refused"
    assert "backup" in results[0]["reason"]
    assert _version(conn) == 1


def test_the_backup_id_is_recorded_against_the_attempt(conn, probe, monkeypatch):
    """So a rollback does not depend on somebody remembering which backup came
    before which attempt."""
    monkeypatch.setattr(migrations, "_pre_upgrade_backup", lambda: ("backup-42", None))
    migrations.migrate(conn, store_name="probe")
    assert all(e["backup_id"] == "backup-42"
               for e in migrations.history(conn, store_name="probe"))


# --- the audit trail records failures too ------------------------------------------


def test_every_attempt_is_on_the_record_including_the_failures(conn, probe, monkeypatch):
    """An audit trail that only records successes cannot answer the question
    anybody actually asks it after an incident."""
    def explodes(_c):
        raise RuntimeError("nope")

    _with(probe, migrations={1: explodes}, code_version=2)
    migrations.migrate(conn, store_name="probe", backup=False)

    outcomes = [e["outcome"] for e in migrations.history(conn, store_name="probe")]
    assert outcomes[-1] == OUTCOME_FAILED
    assert "nope" in migrations.history(conn, store_name="probe")[-1]["detail"]


def test_a_failed_migration_alerts_the_operator(conn, probe, monkeypatch):
    """§22: "Alert the operator when appropriate." A failed migration always
    is - it is the one failure where doing nothing and doing something are both
    potentially destructive."""
    from backend import status_events

    # code_version=2 so the one registered step is the whole ladder. Without it
    # the run refuses for a *missing* rung and never reaches the failure path -
    # which is how the first version of this test passed nothing at all.
    _with(probe, code_version=2,
          migrations={1: lambda _c: (_ for _ in ()).throw(RuntimeError("x"))})
    results = migrations.migrate(conn, store_name="probe", backup=False)
    assert results[0]["action"] == "failed", "the test must reach the failure path"

    events = status_events.recent(conn, limit=20)
    assert any(e["event_type"] == "migration_failed" for e in events)


def test_a_successful_migration_is_recorded_with_its_step_count(conn, probe):
    migrations.migrate(conn, store_name="probe", backup=False)
    latest = migrations.history(conn, store_name="probe")[-1]
    assert latest["outcome"] == OUTCOME_MIGRATED
    assert latest["from_version"] == 1 and latest["to_version"] == 3


def test_a_dry_run_changes_nothing(conn, probe):
    results = migrations.migrate(conn, store_name="probe", dry_run=True, backup=False)
    assert results[0]["action"] == "would_migrate"
    assert results[0]["steps"] == [(1, 2), (2, 3)]
    assert _value(conn) == "hello" and _version(conn) == 1


# --- the real stores, honestly reported --------------------------------------------


def test_the_registered_stores_are_up_to_date_and_say_why(conn):
    """Every store is at version 1 with no steps. "No migrations registered" and
    "migrations forgotten" look identical from an empty dict, so each carries a
    note saying which it is."""
    report = {entry["store"]: entry for entry in migrations.status(conn)}
    assert {"workspace", "coo_identity", "fi_db", "parliament"} <= set(report)
    assert report["coo_identity"]["needs_migration"] is False
    for name, entry in report.items():
        assert entry["note"], f"{name} has no migrations and does not say why"
        assert entry["stored_version"] == migrations.get(name).code_version, (
            f"{name} is not at the version this build expects")
    assert migrations.pending(conn) == []


def test_the_store_version_is_not_the_row_stamp(conn):
    """The distinction §156 exists for, pinned so it cannot quietly collapse.

    `fi_db.SCHEMA_VERSION` is 7 and means *what the code meant when it wrote this
    row* - rows at 2, 3 and 7 coexist deliberately, because a v3 detector_event
    records which lens produced it and a v2 one does not. The store version says
    what shape the tables are in, and they have never been migrated. Registering
    the row stamp as the store version would send the runner looking for six
    rungs that do not exist."""
    assert fi_db.SCHEMA_VERSION > 1, "this test is pointless if the two cannot differ"
    assert migrations.get("fi_db").code_version == 1


def test_every_module_that_owns_tables_is_a_registered_store(conn):
    """The tripwire the readiness review asked for (B3).

    A module that creates tables and is not registered is a body of state the
    engine cannot version, validate, back up or migrate - and nothing would say
    so. It reported a complete picture of two stores out of twenty-two before
    TQ-110, which is the failure mode: a status command that looks comprehensive
    and covers 8% of the database."""
    registered_tables = set()
    for store in migrations.stores():
        registered_tables.update(store.tables or (store.table,))

    declared = set()
    for schema in fi_db.SCHEMA_SOURCES:
        declared.update(migrations.tables_in(schema))

    # The engine's own bookkeeping is deliberately not a store: a migration
    # engine that versioned its own audit trail would need itself working in
    # order to repair itself.
    declared -= set(migrations.tables_in(migrations.SCHEMA))

    assert not declared - registered_tables, (
        f"tables belong to no registered store: {sorted(declared - registered_tables)}. "
        "The migration engine cannot version, validate or back up what it does not "
        "know about, and status() would report a complete picture without them.")


def test_a_migration_does_not_touch_the_row_stamps(conn, probe):
    """The defect the store-version table was introduced to prevent.

    The first two stores kept their version in the same per-row column that
    carries provenance, so writing a version meant `UPDATE ... SET schema_version`
    across every row. On a one-row identity that is harmless; on fi_db's tables it
    would restamp historical rows with today's number and destroy the thing a
    grader reads them for - silently, and only visibly wrong months later.

    So this migrates a store wired the way every registered store now is, over
    rows whose stamps genuinely differ, and asserts the stamps come out untouched
    while the store's own version moves."""
    _with(probe,
          read_version=migrations._recorded_version("probe", ("probe",)),
          write_version=migrations._record_version("probe"))
    conn.execute("UPDATE probe SET schema_version = 3 WHERE id = 1")
    conn.execute("INSERT INTO probe (id, value, schema_version) VALUES (2, 'later', 7)")
    migrations._record_version("probe", source="backfill")(conn, 1)
    before = [r["schema_version"] for r in
              conn.fetchall("SELECT schema_version FROM probe ORDER BY id")]
    assert before == [3, 7], "the fixture must have heterogeneous stamps or this proves nothing"

    results = migrations.migrate(conn, store_name="probe", backup=False)

    assert results[0]["action"] == "migrated"
    after = [r["schema_version"] for r in
             conn.fetchall("SELECT schema_version FROM probe ORDER BY id")]
    assert after == before, "a migration rewrote row stamps that carry provenance"
    assert conn.fetchone(
        "SELECT version FROM store_schema_versions WHERE store = 'probe'")["version"] == 3


def test_a_store_with_no_state_is_not_a_store_that_needs_migrating(conn):
    """No workspace has been saved yet. Absent is not stale."""
    entry = next(e for e in migrations.status(conn) if e["store"] == "workspace")
    assert entry["present"] is False and entry["needs_migration"] is False


def test_status_reports_a_broken_store_rather_than_dying(conn, monkeypatch):
    """This is the command a developer runs *because* something is wrong."""
    monkeypatch.setattr(migrations, "_REGISTRY", dict(migrations._REGISTRY))
    _with(migrations.get("coo_identity"),
          read_version=lambda c: (_ for _ in ()).throw(RuntimeError("table is gone")))
    entry = next(e for e in migrations.status(conn) if e["store"] == "coo_identity")
    assert entry["readable"] is False and "table is gone" in entry["problem"]


def test_the_identity_validator_catches_a_second_kumbhakarnan(conn):
    """The invariant §88 relies on, checked by the thing that gates activation."""
    conn.execute("INSERT INTO coo_identity SELECT 'coo-second', 'other-org', name, role, "
                 "created_at, identity_version, schema_version, software_version_at_creation, "
                 "software_version_last_seen, personality, voice_identity, visual_identity, "
                 "preferences, relationship_history, last_persisted_at FROM coo_identity")
    problems = migrations.get("coo_identity").validate(conn)
    assert any("exactly one" in p for p in problems)


def test_the_workspace_validator_catches_an_unparseable_payload(conn):
    workspace.save(conn, {"activeTab": "newsroom"})
    conn.execute("UPDATE workspace_state SET payload = 'not json'")
    problems = migrations.get("workspace").validate(conn)
    assert any("will not parse" in p for p in problems)


# --- §14's escape hatches ------------------------------------------------------------


def test_inspect_returns_raw_state_not_a_friendly_view(conn):
    """A developer reading this is usually trying to find out why parsing
    failed, and a view that parses for them hides the thing they came to see."""
    raw = migrations.inspect(conn, store_name="coo_identity")["coo_identity"]
    assert raw and isinstance(raw[0]["personality"], str), "JSON columns stay as stored text"
    json.loads(raw[0]["personality"])


def test_disabling_persistence_writes_nothing_and_says_so(conn, monkeypatch):
    """§14's fourth hatch. Silently pretending to save would be worse than not
    offering the hatch: a developer who cannot tell "saved" from "deliberately
    not saved" is exactly who §14 is written for."""
    monkeypatch.setenv(migrations.PERSISTENCE_DISABLED_ENV, "1")
    assert migrations.persistence_disabled() is True

    result = workspace.save(conn, {"activeTab": "finance"})
    assert result["disabled"] is True and result["reason"]
    assert workspace.load(conn)["restored"] is False, "nothing was written"


def test_persistence_is_on_unless_deliberately_turned_off(conn, monkeypatch):
    monkeypatch.delenv(migrations.PERSISTENCE_DISABLED_ENV, raising=False)
    assert migrations.persistence_disabled() is False
    assert workspace.save(conn, {"activeTab": "finance"}).get("disabled") is None


def test_reset_is_refused_outside_a_development_stage(conn, monkeypatch, tmp_path):
    """An escape hatch that can be pulled in production is not a development
    convenience."""
    from backend import boot_config

    monkeypatch.setenv(boot_config.PATH_ENV, str(_boot_config(tmp_path, "PRODUCTION")))

    with pytest.raises(HatchRefused, match="PRODUCTION"):
        migrations.reset(conn, backup=False)
    assert coo_identity.load(conn) is not None, "the COO must still be there"


def test_reset_is_refused_when_the_stage_cannot_be_read(conn, monkeypatch, tmp_path):
    """Fail closed: "I could not tell what stage this is" must not resolve to
    "go ahead and wipe it"."""
    from backend import boot_config

    monkeypatch.setenv(boot_config.PATH_ENV, str(tmp_path / "does-not-exist.json"))
    with pytest.raises(HatchRefused):
        migrations.reset(conn, backup=False)


def test_reset_without_a_backup_is_refused_unless_deliberate(conn, monkeypatch, tmp_path):
    """An escape hatch that destroys the only copy is what §22 forbids, wearing
    a helpful name."""
    _pre_alpha(monkeypatch, tmp_path)
    monkeypatch.setattr(migrations, "_pre_upgrade_backup", lambda: (None, "none configured"))
    with pytest.raises(HatchRefused, match="backup"):
        migrations.reset(conn)


def test_reset_clears_state_at_a_development_stage(conn, monkeypatch, tmp_path):
    """The hatch has to actually work, or a developer trapped in stale state
    stays trapped."""
    _pre_alpha(monkeypatch, tmp_path)
    workspace.save(conn, {"activeTab": "finance"})

    outcome = migrations.reset(conn, backup=False)

    assert {"workspace", "coo_identity"} <= set(outcome["cleared"])
    assert coo_identity.load(conn) is None
    assert workspace.load(conn)["restored"] is False


def test_reset_of_one_store_leaves_the_others(conn, monkeypatch, tmp_path):
    _pre_alpha(monkeypatch, tmp_path)
    workspace.save(conn, {"activeTab": "finance"})

    migrations.reset(conn, store_name="workspace", backup=False)

    assert workspace.load(conn)["restored"] is False
    assert coo_identity.load(conn) is not None, "resetting the workspace must not take the COO"


def test_a_reset_is_announced(conn, monkeypatch, tmp_path):
    """Destroying state silently is how a developer loses an afternoon to
    wondering where it went."""
    from backend import status_events

    _pre_alpha(monkeypatch, tmp_path)
    migrations.reset(conn, backup=False)
    assert any(e["event_type"] == "state_reset" for e in status_events.recent(conn, limit=10))


def test_the_coo_comes_back_after_a_reset(conn, monkeypatch, tmp_path):
    """The point of the hatch: start clean, not stay broken. The next
    init_schema recreates Kumbhakarnan - with a new id and creation moment,
    which is honest, because this genuinely is a new one."""
    _pre_alpha(monkeypatch, tmp_path)
    before = coo_identity.load(conn)["coo_id"]
    migrations.reset(conn, store_name="coo_identity", backup=False)

    fi_db.init_schema(conn)
    after = coo_identity.load(conn)

    assert after is not None and after["name"] == coo_identity.DEFAULT_NAME
    assert after["coo_id"] != before


def _boot_config(tmp_path, stage: str):
    """A complete boot configuration at a given stage.

    Complete rather than minimal: boot_config refuses a partial file, and a
    refusal there is indistinguishable from the stage refusal these tests are
    about - which is exactly how the first version of them passed for the wrong
    reason."""
    config = tmp_path / f"boot-{stage.lower()}.json"
    config.write_text(json.dumps({
        "lifecycle_stage": stage,
        "global_asset_classes": ["stock", "stock_option"],
        "implemented_asset_classes": ["stock", "stock_option"],
        "current_focus": ["REFERENCE_DATA"],
        "simulation_focus": ["OPTIONS_ON_EQUITIES_PRICING"],
    }), encoding="utf-8")
    return config


def _pre_alpha(monkeypatch, tmp_path):
    from backend import boot_config

    monkeypatch.setenv(boot_config.PATH_ENV, str(_boot_config(tmp_path, "PRE_ALPHA")))


# --- the transaction this depends on --------------------------------------------------


def test_a_transaction_rolls_everything_back(conn):
    conn.execute("INSERT INTO probe (id, value) VALUES (7, 'before')")
    with pytest.raises(RuntimeError):
        with conn.transaction():
            conn.execute("UPDATE probe SET value = 'after' WHERE id = 7")
            raise RuntimeError("stop")
    assert conn.fetchone("SELECT value FROM probe WHERE id = 7")["value"] == "before"


def test_a_transaction_commits_together(conn):
    with conn.transaction():
        conn.execute("INSERT INTO probe (id, value) VALUES (8, 'a')")
        conn.execute("INSERT INTO probe (id, value) VALUES (9, 'b')")
    assert conn.fetchone("SELECT COUNT(*) AS n FROM probe WHERE id IN (8, 9)")["n"] == 2


def test_nesting_is_refused_rather_than_silently_joined(conn):
    """A nested block that joined the outer one would believe it had committed
    while an outer rollback could still undo it - and that belief is what a
    caller reaches for a transaction to avoid."""
    with pytest.raises(RuntimeError, match="[Nn]ested"):
        with conn.transaction():
            with conn.transaction():
                pass


def test_executescript_is_refused_inside_a_transaction(conn):
    """sqlite3 commits before running it, which would end the transaction while
    the block still looked atomic - a trap that only shows up when a rollback
    is needed and turns out not to have happened."""
    with pytest.raises(RuntimeError, match="executescript"):
        with conn.transaction():
            conn.executescript("CREATE TABLE nope (id INTEGER);")


def test_ordinary_writes_still_commit_on_their_own(conn):
    """The default this system relies on everywhere else: agents make small
    independent writes and one failing must not discard the last unrelated
    one."""
    conn.execute("INSERT INTO probe (id, value) VALUES (11, 'x')")
    assert conn.fetchone("SELECT value FROM probe WHERE id = 11")["value"] == "x"


def test_a_database_predating_a_store_is_not_a_broken_one(conn):
    """The upgrade case this module exists for, found by running `status`
    against a copy of the real database: it predates `coo_identity`, and the
    first version of this reported "UNREADABLE - no such table".

    That is the wrong answer twice over. It reads as corruption, sending a
    developer hunting for damage that is not there; and it is the *normal*
    state of every database written before a store was added, which is exactly
    the population a migration tool serves."""
    conn.executescript("DROP TABLE coo_identity;")

    entry = next(e for e in migrations.status(conn) if e["store"] == "coo_identity")

    assert entry["readable"] is True, "a store that does not exist yet is not unreadable"
    assert entry["present"] is False
    assert entry["created"] is False
    assert entry["needs_migration"] is False
    assert "does not exist" in entry["problem"]

    # And migrating skips it rather than failing the whole run.
    result = next(r for r in migrations.migrate(conn, backup=False)
                  if r["store"] == "coo_identity")
    assert result["action"] == "skipped"


def test_a_created_but_empty_store_is_distinguishable_from_an_absent_one(conn):
    """Two different "not present" states, and conflating them would hide
    whichever one is actually true."""
    absent = next(e for e in migrations.status(conn) if e["store"] == "workspace")
    assert absent["created"] is True and absent["present"] is False


def test_a_heartbeat_is_one_event_or_none_of_it(conn):
    """A heartbeat is written to two tables and must be readable as one thing.

    The registry says *when* an agent last reported; `health_metrics` says
    *that it did*, and the performance card counts the second. Committed
    separately, a reader on another connection can land between them and see an
    agent that has heartbeated with a heartbeat count of zero.

    That is not hypothetical - it is how CI failed on a slow Windows runner
    while passing on Linux and on every developer machine, in the same pull
    request that introduced the transaction which fixes it. Asserted here by
    forcing the second write to fail and checking the first did not survive."""
    from backend.db import Database

    fi_db.register_agent(conn, "dummy-9", "dummy", pid=7)
    before = conn.fetchone(
        "SELECT last_heartbeat_at FROM agent_registry WHERE identity = 'dummy-9'"
    )["last_heartbeat_at"]

    real_execute = Database.execute

    def fail_on_the_metric(self, sql, params=()):
        if "health_metrics" in sql:
            raise RuntimeError("the second write fails")
        return real_execute(self, sql, params)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Database, "execute", fail_on_the_metric)
        with pytest.raises(RuntimeError):
            fi_db.record_heartbeat(conn, "dummy-9")

    after = conn.fetchone(
        "SELECT last_heartbeat_at FROM agent_registry WHERE identity = 'dummy-9'"
    )["last_heartbeat_at"]
    assert after == before, "the registry timestamp outlived the failed heartbeat"
    assert conn.fetchone(
        "SELECT COUNT(*) AS n FROM health_metrics WHERE identity = 'dummy-9'")["n"] == 0


def test_a_successful_heartbeat_lands_in_both_places(conn):
    """The other half: atomicity must not have been bought by writing less."""
    fi_db.register_agent(conn, "dummy-10", "dummy", pid=8)
    fi_db.record_heartbeat(conn, "dummy-10")

    assert conn.fetchone(
        "SELECT last_heartbeat_at FROM agent_registry WHERE identity = 'dummy-10'"
    )["last_heartbeat_at"] is not None
    card = {row["identity"]: row for row in fi_db.get_performance_card(conn)}
    assert card["dummy-10"]["heartbeat_count"] == 1


# --- backfilling a database that predates version tracking --------------------------


def test_backfill_records_version_one_for_stores_that_already_exist(conn):
    """Every registered store is at code version 1 with no steps, so a database
    that predates this tracking genuinely is at 1 - there has never been a
    migration for it to have missed."""
    conn.execute("DELETE FROM store_schema_versions")

    recorded = migrations.backfill_store_versions(conn)

    assert "fi_db" in recorded and "parliament" in recorded
    rows = conn.fetchall("SELECT store, version, source FROM store_schema_versions")
    assert {r["version"] for r in rows} == {1}
    assert {r["source"] for r in rows} == {"backfill"}


def test_backfill_leaves_a_recorded_version_alone(conn):
    """It runs on every startup. A backfill that overwrote what it found would
    reset a migrated store to 1 on the next boot, which is the corruption this
    whole module exists to prevent."""
    migrations._record_version("fi_db")(conn, 1)
    conn.execute("UPDATE store_schema_versions SET version = 4 WHERE store = 'fi_db'")

    migrations.backfill_store_versions(conn)

    assert conn.fetchone(
        "SELECT version FROM store_schema_versions WHERE store = 'fi_db'")["version"] == 4


def test_backfill_refuses_to_guess_once_a_store_has_moved(conn, probe):
    """The guard that keeps `BACKFILL_VERSION` honest.

    Stamping 1 is only correct while every store is *at* 1. Once a store's code
    version is past the backfill version, an untracked database could be anywhere
    between the two - and either guess corrupts: assume the top and a conversion
    is skipped, assume the bottom and one is re-applied."""
    conn.execute("DELETE FROM store_schema_versions")
    _with(probe,
          read_version=migrations._recorded_version("probe", ("probe",)),
          write_version=migrations._record_version("probe"))

    with pytest.raises(migrations.AmbiguousVersion, match="probe"):
        migrations.backfill_store_versions(conn)


def test_a_store_whose_tables_are_absent_is_not_backfilled(conn):
    """Absence is not version 1. A store that has never existed here has no
    version, and inventing one would claim a conversion history it never had."""
    conn.execute("DELETE FROM store_schema_versions")
    conn.execute("DROP TABLE appeals")

    recorded = migrations.backfill_store_versions(conn)

    assert "appeal" not in recorded
    assert conn.fetchone(
        "SELECT 1 FROM store_schema_versions WHERE store = 'appeal'") is None
