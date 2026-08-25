"""The Metadata Engine (addendum 39 §7/§12/§13/§14, addendum 21's own title;
TASK_QUEUE TQ-23, docs/SPEC_RECONCILIATION.md §72).

**An engine, not an agent** — the precedent `backend/reference_data.py` sets
and this follows exactly: pure functions over a database connection, invoked
from startup orchestration, no charter, no watcher, no `organization.yaml`
entry. It does its startup work, reports, and idles (39 §12 step 10: "no need
to continuously consume resources once its startup work is complete").

## It verifies datasets that already exist — it does not create four new ones

Addendum 39 §7 names four required global datasets. Three of them are already
`asset_classes.in_universe / .in_capability / .in_focus` and the fourth is
`agent_names` (docs/SPEC_RECONCILIATION.md §70 disposition 1). Creating four
tables holding the same facts would put an asset class's implemented status in
two places free to disagree — the two-models error the Conflict Rule forbids.
So this module *verifies and reconciles*; it owns no schema of its own.

## Boot configuration is the authority

`reference_data.CAPABILITY_FOCUS_CLASSES` seeds a fresh database with the
classes the software can process, and `boot_config.implemented_asset_classes`
declares the same fact for operators. Two declarations of one fact is exactly
what this codebase refuses, so the rule is stated once, here: **boot
configuration wins.** The constant remains the seed-time default for a
database created before any metadata pass; where the database and the boot
configuration disagree, this engine changes the database and *reports the
correction as a WARNING event* rather than performing it silently.

That is not a violation of 39 §13's "destroy operator changes without explicit
instruction": `boot_config.json` is version-controlled, so it IS the explicit
instruction, and the divergence is announced rather than swallowed. A test
pins the two declarations consistent so they cannot drift apart unnoticed.

## The Focus List, honestly

39 §11's Focus List has two halves in this system, and only one is a table.
The asset-class half is `in_focus`, which exists. The development half —
`PRE_ALPHA_STARTUP_OBSERVABILITY`, `OPTION_PRICE_SIMULATION` and the rest — is
declared in `boot_config.json` and lives nowhere else on purpose: a focus
table that merely restated a version-controlled file would be a table nothing
writes to, wearing the appearance of a capability. Both halves are counted in
the summary; only the asset-class half is reconciled, because only it has
state that can drift.

## Events

39 §12 requires this engine to *publish* — starting, per-dataset verification,
a summary, and `METADATA_READY`. It does both things a publisher should: the
events go to the durable stream (`backend/status_events.py`, TQ-24/§73) under
one correlation id per startup pass, and they are also *returned*, so the
caller can print the feed without a second query and so a stream failure
cannot cost the engine its narration. See `_publish` for why recording is
best-effort while metadata startup is not.
"""

from __future__ import annotations

from backend import boot_config as boot_config_module
from backend import reference_data
from backend.boot_config import BootConfig, BootConfigError
from backend.db import Database, now_iso

ENGINE = "metadata_engine"

# 39 §12's published states, plus the failure case §12 does not name but
# addendum 38 §12 requires be visible rather than silently absent.
STATE_STARTING = "METADATA_ENGINE_STARTING"
STATE_READY = "METADATA_READY"
STATE_IDLE = "IDLE"
STATE_FAILED = "FAILED"

# addendum 38 §4.3's vocabularies, the subset this engine uses.
SEVERITY_INFO = "INFO"
SEVERITY_WARNING = "WARNING"
SEVERITY_ERROR = "ERROR"

STATUS_STARTING = "STARTING"
STATUS_RUNNING = "RUNNING"
STATUS_READY = "READY"
STATUS_IDLE = "IDLE"
STATUS_FAILED = "FAILED"

# The four datasets 39 §7 requires, named as the spec names them so a reader
# holding the specification can find each one, mapped to where it actually
# lives in this system.
DATASET_AGENT_NAMES = "Agent Names"
DATASET_GLOBAL_ASSET_CLASSES = "Global Asset Classes"
DATASET_IMPLEMENTED_LIST = "Implemented List"
DATASET_FOCUS_LIST = "Focus List"
REQUIRED_DATASETS = (
    DATASET_AGENT_NAMES,
    DATASET_GLOBAL_ASSET_CLASSES,
    DATASET_IMPLEMENTED_LIST,
    DATASET_FOCUS_LIST,
)


def _event(event_type: str, message: str, *, severity: str = SEVERITY_INFO,
           status: str = STATUS_RUNNING, lifecycle_stage: str | None = None,
           dataset: str | None = None) -> dict:
    """One status event, in the subset of addendum 38 §4.3's schema this
    engine can honestly fill. `source_agent` and `task_id` are absent rather
    than null-padded - an engine is not an agent and this work is not a
    task, and inventing empty fields to look complete is how a schema stops
    meaning anything."""
    event = {
        "timestamp": now_iso(),
        "source_engine": ENGINE,
        "event_type": event_type,
        "severity": severity,
        "status": status,
        "message": message,
    }
    if lifecycle_stage is not None:
        event["lifecycle_stage"] = lifecycle_stage
    if dataset is not None:
        event["dataset"] = dataset
    return event


def _publish(conn: Database, events: list[dict]) -> None:
    """Hand this run's narration to the durable stream (TQ-24/§73).

    Deliberately last, not per-event: the engine's job is metadata, and a
    stream that was down must not take metadata startup with it. A failure to
    record the narration is reported and swallowed - losing the story is bad,
    losing the startup because the story could not be filed is worse, and 38
    §12 asks that a failure be visible rather than fatal.

    The engine keeps returning its events either way, so the caller's printed
    feed is unaffected by whether the store accepted them."""
    from backend import status_events

    try:
        status_events.publish_many(conn, [
            {
                "event_type": event["event_type"],
                "message": event["message"],
                "severity": event["severity"],
                "status": event["status"],
                "lifecycle_stage": event.get("lifecycle_stage"),
                "engine": event["source_engine"],
                "timestamp": event["timestamp"],
                "correlation_id": events[0]["timestamp"],  # one startup pass, one trace
            }
            for event in events
        ])
    except Exception as exc:  # noqa: BLE001 - narration must not break the engine
        print(f"[metadata] status stream unavailable, events not recorded: "
              f"{exc.__class__.__name__}: {exc}")


def _verify_agent_names(conn: Database, events: list[dict]) -> int:
    """Dataset 1 (39 §8). The pool is seeded by fi_db.init_schema with
    INSERT OR IGNORE, so verification is a count rather than a re-seed:
    re-seeding here would be a second writer of the same rows, and 39 §13
    forbids overwriting existing name assignments above all else.

    Reports available names, because that is the number that runs out and
    stops agent creation."""
    total = conn.fetchone("SELECT COUNT(*) AS n FROM agent_names")["n"]
    available = conn.fetchone(
        "SELECT COUNT(*) AS n FROM agent_names WHERE assigned_to_identity IS NULL AND reserved = 0"
    )["n"]
    assigned = conn.fetchone(
        "SELECT COUNT(*) AS n FROM agent_names WHERE assigned_to_identity IS NOT NULL"
    )["n"]
    # Assigned and reserved are counted apart because they are different
    # facts and a single "in use" number reads as a puzzle: this database
    # seeds one reserved name (the CEO's) that no agent holds, so "40 of 41"
    # alone would invite the reader to look for an agent that does not exist.
    reserved = total - available - assigned
    severity = SEVERITY_INFO if available else SEVERITY_WARNING
    message = (
        f"Agent Names verified: {available} available, {assigned} assigned, "
        f"{reserved} reserved ({total} total)"
    )
    if not available:
        message += " - the pool is exhausted; no new persistent agent can be named"
    events.append(_event("dataset_verified", message, severity=severity,
                         dataset=DATASET_AGENT_NAMES))
    return available


def _verify_global_asset_classes(conn: Database, config: BootConfig, events: list[dict]) -> int:
    """Dataset 2 (39 §9): every class the boot configuration calls
    architecturally known must exist in the registry and be in the Universe.

    `boot_config.load` already refuses a class `reference_data` does not
    know, so a mismatch here means the *database* is behind the code - a
    fresh or partially-migrated database - and the fix is the registry's own
    idempotent seed rather than an insert written twice."""
    known = {row["asset_class"] for row in conn.fetchall("SELECT asset_class FROM asset_classes")}
    missing = [code for code in config.global_asset_classes if code not in known]
    if missing:
        reference_data._seed_asset_classes(conn)
        events.append(_event(
            "dataset_seeded",
            f"Global Asset Classes: seeded {len(missing)} missing class(es): {', '.join(missing)}",
            dataset=DATASET_GLOBAL_ASSET_CLASSES,
        ))
    count = conn.fetchone("SELECT COUNT(*) AS n FROM asset_classes WHERE in_universe = 1")["n"]
    events.append(_event(
        "dataset_verified", f"Global Asset Classes verified: {count} known to the architecture",
        dataset=DATASET_GLOBAL_ASSET_CLASSES,
    ))
    return count


def _reconcile_implemented(conn: Database, config: BootConfig, events: list[dict]) -> int:
    """Dataset 3 (39 §10), and the one place this engine writes policy.

    39 §10: "Nothing else should be falsely marked implemented." So the
    reconciliation runs in both directions - classes the boot configuration
    implements are switched on, and classes it does not are switched off -
    and every correction is announced (module docstring on why that is not
    a silent destruction of operator changes)."""
    declared = set(config.implemented_asset_classes)
    rows = conn.fetchall("SELECT asset_class, in_capability FROM asset_classes")
    corrections = []
    for row in rows:
        should_be = row["asset_class"] in declared
        if bool(row["in_capability"]) != should_be:
            reference_data.set_capability(conn, row["asset_class"], should_be)
            corrections.append(f"{row['asset_class']}={'on' if should_be else 'off'}")
    if corrections:
        events.append(_event(
            "dataset_reconciled",
            f"Implemented List: database disagreed with boot configuration, corrected "
            f"{len(corrections)}: {', '.join(sorted(corrections))}",
            severity=SEVERITY_WARNING, dataset=DATASET_IMPLEMENTED_LIST,
        ))
    count = conn.fetchone("SELECT COUNT(*) AS n FROM asset_classes WHERE in_capability = 1")["n"]
    events.append(_event(
        "dataset_verified", f"Implemented List verified: {count} implemented capability(ies)",
        dataset=DATASET_IMPLEMENTED_LIST,
    ))
    return count


def _verify_focus(conn: Database, config: BootConfig, events: list[dict]) -> int:
    """Dataset 4 (39 §11), both halves - see the module docstring on why only
    one of them is a table.

    The asset-class half is not reconciled against boot configuration the way
    the Implemented List is: `current_focus` names development themes
    (PRE_ALPHA_STARTUP_OBSERVABILITY and the like), not asset classes, so
    there is nothing in the boot configuration to reconcile `in_focus`
    against. It is reported, and the registry's own invariant check
    (`validate`'s registry_invariants) is what guards it."""
    asset_focus = conn.fetchone("SELECT COUNT(*) AS n FROM asset_classes WHERE in_focus = 1")["n"]
    declared_focus = len(config.current_focus) + len(config.simulation_focus)
    events.append(_event(
        "dataset_verified",
        f"Focus List verified: {asset_focus} asset class(es) in focus, "
        f"{declared_focus} declared focus item(s)",
        dataset=DATASET_FOCUS_LIST,
    ))
    return asset_focus + declared_focus


def run(conn: Database, config: BootConfig | None = None) -> dict:
    """39 §12's startup algorithm, in order, returning the report the caller
    publishes.

    Returns `{'ready': bool, 'state': ..., 'counts': {...}, 'events': [...]}`.
    `ready` is the hard gate 39 §14 puts before the Reference Data Engine -
    a caller that starts reference data on a failed metadata pass has
    ignored the one strict ordering constraint the specification has.

    A boot configuration that will not load is a FAILED metadata pass rather
    than an exception escaping into startup: addendum 38 §12 requires a
    failed component to be visible and its dependents not to falsely report
    success, which is exactly what `ready=False` plus an ERROR event
    delivers."""
    events: list[dict] = []
    events.append(_event(STATE_STARTING, "Metadata Engine starting", status=STATUS_STARTING))

    if config is None:
        try:
            config = boot_config_module.load()
        except BootConfigError as exc:
            events.append(_event(
                STATE_FAILED, f"Boot configuration could not be loaded: {exc}",
                severity=SEVERITY_ERROR, status=STATUS_FAILED,
            ))
            _publish(conn, events)
            return {"ready": False, "state": STATE_FAILED, "counts": {}, "events": events}

    events.append(_event(
        "boot_config_loaded",
        f"Boot configuration loaded: {boot_config_module.summary(config)}",
        lifecycle_stage=config.lifecycle_stage,
    ))

    counts = {
        "names_available": _verify_agent_names(conn, events),
        "global_asset_classes": _verify_global_asset_classes(conn, config, events),
        "implemented_items": _reconcile_implemented(conn, config, events),
        "active_focus_items": _verify_focus(conn, config, events),
    }

    # 39 §12 step 8's summary, as one line, in the order the spec lists them.
    events.append(_event(
        "metadata_summary",
        "names_available={names_available} global_asset_classes={global_asset_classes} "
        "implemented_items={implemented_items} active_focus_items={active_focus_items}".format(**counts),
        lifecycle_stage=config.lifecycle_stage,
    ))
    events.append(_event(STATE_READY, "Metadata ready", status=STATUS_READY,
                         lifecycle_stage=config.lifecycle_stage))
    events.append(_event(STATE_IDLE, "Metadata Engine idle", status=STATUS_IDLE))

    _publish(conn, events)
    return {"ready": True, "state": STATE_IDLE, "counts": counts, "events": events,
            "lifecycle_stage": config.lifecycle_stage}


def format_events(events: list[dict]) -> list[str]:
    """The feed lines addendum 39 §18 asks the COO to be able to display.
    Formatting lives here rather than at the call site so the eventual
    status stream (TQ-24) and today's startup print produce identical text."""
    return [
        f"[{event['timestamp']}] [{event['severity']}] {event['message']}"
        for event in events
    ]
