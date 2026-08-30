"""What this system can actually be shown doing, and what it cannot
(Demonstration Engine Specification; docs/SPEC_RECONCILIATION.md §158).

The specification's core rule is the reason this file is the first thing the Demo
Engine reads:

> *"It must not fake capability that does not exist. If a feature is implemented,
> the demo should exercise the real feature. If a feature is not implemented, the
> demo must not pretend that it exists."*

So the registry has two halves, and **the second half is the one that rots**. A
list of what exists is corrected constantly, because somebody notices when a demo
fails. A list of what is *absent* is never exercised by anything, so it silently
becomes a lie the moment a capability lands — and a demo that claims a working
feature is missing is as dishonest as one that claims a missing feature works.

Both halves are therefore asserted against the codebase by
`tests/test_demonstration_registry.py`. An ABSENT entry names the import or the
table whose absence makes it true, and the test fails when that thing appears.

## Derived where derivable

The specification asks for automatic discovery. Three sources already answer it
and are already kept honest by other tests, so nothing here restates them:

- **roles** from `docs/organization.yaml`, which `tests/test_organization_model.py`
  asserts against the code role by role;
- **persistence surfaces** from `migrations.stores()`, which TQ-110 made complete
  and `tests/test_migrations.py` keeps that way;
- **scenarios** from `simulation/scenario.load_all()`.

What is *not* derivable is the judgement connecting a capability to the act that
shows it, and whether that act is safe to put in front of a client. Those are
declared, and declared things are tested.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Capability:
    """One thing the organization can be shown doing.

    `evidence` is what a viewer should be able to point at afterwards - a table,
    a log line, a property - rather than a claim about what happened. A demo that
    cannot say where to look has not demonstrated anything."""

    id: str
    name: str
    scenario: str | None
    evidence: str
    # Whether this could be put in front of an external viewer. Nothing is today
    # (no client has been onboarded and the boundary is untested), so this is
    # declared false everywhere and the field exists so that stays a decision.
    client_safe: bool = False


@dataclass(frozen=True)
class Absent:
    """Something the specification asks a demo to show, which does not exist.

    `proof` is how the absence is checked. Either a module attribute that must
    not resolve, or a table that must not be in any registered schema - so this
    entry fails the suite on the day the capability arrives, and the registry
    cannot quietly keep claiming it is missing."""

    id: str
    name: str
    why: str
    missing_tables: tuple[str, ...] = ()
    missing_modules: tuple[str, ...] = ()
    missing_attributes: tuple[tuple[str, str], ...] = field(default_factory=tuple)


# --- what can be shown ------------------------------------------------------------

DEMONSTRABLE = (
    Capability(
        id="startup",
        name="The organization starts and staffs itself",
        scenario="baseline_steady_state",
        evidence="agent_registry: the Controller bootstraps the COO, which spawns the "
                 "baseline population and reports it each cycle",
    ),
    Capability(
        id="discovery",
        name="Explorer and Speculator go looking, differently",
        scenario="baseline_steady_state",
        evidence="discovery_reports and discovery_reports_completed, with the detector "
                 "event and the lens that produced each",
    ),
    Capability(
        id="collaboration",
        name="One agent asks another and waits for an answer",
        scenario="baseline_steady_state",
        evidence="cross_check_requests: the asker's own finding is recorded before the "
                 "question, so agreement can be told from an echo",
    ),
    Capability(
        id="judgment",
        name="Analysis grades what the others produced",
        scenario="baseline_steady_state",
        evidence="analysis_results and grades, each carrying a rationale the graded "
                 "agent can read",
    ),
    Capability(
        id="governance",
        name="A rule carried by vote changes what agents do, with no code change",
        scenario="governed_organization",
        evidence="governed_items in force, and discovery_reports.governed_by naming the "
                 "instrument each report was filed under",
    ),
    Capability(
        id="misdrafted_rule",
        name="A rule that forbids its own subject is visible rather than silent",
        scenario="misdrafted_instrument",
        evidence="governed_refusals counted and attributed to the instrument, so zero "
                 "filed and ninety refused is distinguishable from a quiet market",
    ),
    Capability(
        id="release_rollback",
        name="A governed change is applied, judged unhealthy, and reversed",
        scenario="release_and_rollback",
        evidence="releases and release_changes, with the reversal restoring the "
                 "superseded instrument rather than re-adopting it",
    ),
    Capability(
        id="executive_recovery",
        name="The organization survives losing its executive",
        scenario="executive_failure",
        evidence="incidents: the Controller detects the dead COO and restarts it; the "
                 "population continues",
    ),
    Capability(
        id="slow_not_dead",
        name="An agent that is slow is not mistaken for one that is dead",
        scenario="slow_agent",
        evidence="population.slow_reported and slow_recovered, with zero respawns - "
                 "liveness and progress are separate signals",
    ),
    Capability(
        id="persistence",
        name="Identity and knowledge survive a restart",
        scenario=None,  # demonstrated by chaining two runs, not by one scenario
        evidence="coo_identity and agent_identities carried across a second run started "
                 "from the first run's database, with knowledge_records intact",
    ),
    Capability(
        id="trading",
        name="A trader takes a position on the analysis and owns the result",
        scenario="baseline_steady_state",
        evidence="trader_orders and trader_fills: one order per analysis result, keyed on "
                 "the trader's durable agent_id, entry and exit levels from the same "
                 "surface provider every other agent reads",
    ),
    Capability(
        id="pnl",
        name="Trades have a result, in vol points and never in money",
        scenario="baseline_steady_state",
        evidence="trading.pnl_vol_points, derived from the fills rather than stored; "
                 "book_summary reports is_priced false and origin synthetic, because "
                 "every level comes from a generated surface (§113)",
    ),
    Capability(
        id="attribution",
        name="A losing trade is diagnosed rather than blamed on the nearest role",
        scenario="baseline_steady_state",
        evidence="trader_attributions: bad_idea, bad_timing, bad_data, market_randomness "
                 "or sound_and_profitable, recorded by the COO because a trader does not "
                 "judge its own trades",
    ),
    Capability(
        id="training",
        name="Agents are examined against a curriculum",
        scenario=None,  # the curriculum is its own runner
        evidence="curriculum_results: six exercises, with a KNOWN_GAP exercise that must "
                 "fail or the curriculum is reported out of date",
    ),
)


# --- what the specification asks for and this system does not have ------------------

ABSENT = (
    Absent(
        id="real_prices",
        name="Real market data",
        why="Measured rather than assumed: every observation carries "
            "origin='synthetic' against a security master whose identifiers are "
            "JE-000001 and not AAPL. TQ-75, unheld.",
    ),
    Absent(
        id="knowledge_store",
        name="The Knowledge Store as specified",
        why="knowledge_records exists and holds lessons and open questions, with "
            "provenance and supersession. What the Knowledge Store specification asks "
            "for - a validation lifecycle, relationships, a keyword dictionary, a "
            "retrieval contract - is not built, and every record is authoritative on "
            "arrival (§153). Three writers, one real reader.",
        missing_modules=("backend.knowledge_graph",),
    ),
    Absent(
        id="software_evolution",
        name="The self-improvement loop, end to end",
        why="The Software Department has five gates, a DBA that opens issues and a QA "
            "reader, and nothing that corrects or verifies - those steps need an agent "
            "that writes code, which this architecture forbids (T1). Separately, "
            "engineering.receive has no production caller, so no directive can reach "
            "the department at all (§155).",
    ),
    Absent(
        id="superuser_score",
        name="Superuser rating and feedback",
        why="Directive §10 wants feedback attached to a system state, feature, "
            "department, demo or change - five subjects. A demo-only score table would "
            "be the wrong shape for four of them, so it is named rather than "
            "half-built.",
        missing_tables=("superuser_feedback",),
    ),
    Absent(
        id="business_performance",
        name="Viewership, revenue, advertising, engagement",
        why="Directive §11 and the specification both ask for these. No department "
            "produces any of them; Providence names them as direction, not as build.",
    ),
    Absent(
        id="historical_replay",
        name="Historical-data operation",
        why="Addendum 46 §27 and addendum 47 §6 both require it and nothing implements "
            "it. Every run is synthetic and generated, never replayed.",
    ),
)


def demonstrable_ids() -> tuple[str, ...]:
    return tuple(c.id for c in DEMONSTRABLE)


def absent_ids() -> tuple[str, ...]:
    return tuple(a.id for a in ABSENT)


def discovered_roles() -> list[dict]:
    """Roles the organization actually implements, from the model that is already
    asserted against the code."""
    import yaml

    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "docs" / "organization.yaml"
    model = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [r for r in model.get("roles", []) if r.get("status") == "implemented"]


def discovered_stores() -> list[str]:
    """Persistence surfaces the migration engine governs. Complete since TQ-110.

    `fi_db` is imported for its side effect: it registers its own store, because
    `migrations` sits below it and cannot import it. Reading the registry without
    that import returns a registry short by one and says nothing about it - which
    is the kind of quiet incompleteness this whole file exists to prevent."""
    from backend import fi_db, migrations  # noqa: F401 - fi_db registers on import

    return [store.name for store in migrations.stores()]


def discovered_scenarios() -> dict:
    from simulation import scenario as scenario_module

    return scenario_module.load_all()
