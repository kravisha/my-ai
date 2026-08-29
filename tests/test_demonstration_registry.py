"""The demo registry must describe this system and not a remembered one
(demonstration/; Demonstration Engine Specification; SPEC_RECONCILIATION §158).

The specification's central rule is that a demo must not fake capability that
does not exist. That cuts both ways, and **the second direction is the one
nothing else guards**:

- A capability claimed and absent produces a demo that fails loudly. Somebody
  notices within one run.
- A capability listed as *absent* and since built produces nothing at all. The
  demo simply never shows it, the registry keeps saying it is missing, and the
  system looks less capable than it is - for as long as nobody rereads the file.

So `ABSENT` entries name the module or table whose absence makes them true, and
this file fails the moment one appears. That is the same shape as
`agent_identity.REACHABLE_STATES` and `test_claim_recovery`'s registry: a list
somebody would otherwise have to remember to update becomes a list the suite
updates them about.
"""

import importlib

import pytest

from backend import fi_db, migrations
from demonstration import capabilities as registry
from demonstration import engine
from simulation import scenario as scenario_module


def test_every_demonstrable_capability_names_a_real_scenario():
    """A capability pointing at a scenario that does not exist is an act that
    reports UNAVAILABLE forever while the registry claims the capability."""
    scenarios = set(scenario_module.load_all())
    for capability in registry.DEMONSTRABLE:
        if capability.scenario is not None:
            assert capability.scenario in scenarios, (
                f"capability {capability.id!r} names scenario {capability.scenario!r}, "
                f"which is not in the library: {sorted(scenarios)}")


def test_every_demonstrable_capability_says_where_to_look():
    """`evidence` is the difference between showing something and asserting it.

    A demo that cannot say which table to read afterwards has not demonstrated
    anything - it has narrated."""
    for capability in registry.DEMONSTRABLE:
        assert capability.evidence.strip(), f"{capability.id} claims no evidence"
        assert len(capability.evidence) > 30, (
            f"{capability.id}'s evidence is too thin to check against")


@pytest.mark.parametrize("absent", registry.ABSENT, ids=lambda a: a.id)
def test_absent_capabilities_are_actually_absent(absent):
    """The half of the registry that rots.

    Each ABSENT entry names what makes it true. When that module or table
    arrives, this fails and the entry has to move to DEMONSTRABLE - which is the
    only mechanism that stops the demo under-reporting the system."""
    for module_name in absent.missing_modules:
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(module_name)

    if absent.missing_tables:
        declared = set()
        for schema in fi_db.SCHEMA_SOURCES:
            declared.update(migrations.tables_in(schema))
        present = sorted(set(absent.missing_tables) & declared)
        assert not present, (
            f"{absent.id!r} is listed as not implemented, but {present} now exist. "
            "Move it to DEMONSTRABLE and give it an act, or the demo will keep "
            "reporting a capability this system has as one it lacks.")


def test_every_absent_entry_explains_itself():
    """A bare "not implemented" is not usable by anybody deciding what to build."""
    for absent in registry.ABSENT:
        assert len(absent.why) > 40, f"{absent.id} does not say why it is absent"


def test_the_two_halves_do_not_overlap():
    """A capability cannot be both demonstrable and absent, and a registry that
    allowed it would report whichever half was read first."""
    overlap = set(registry.demonstrable_ids()) & set(registry.absent_ids())
    assert not overlap, f"declared both present and absent: {sorted(overlap)}"


def test_every_act_names_a_registered_capability():
    """The demo cannot claim to have shown something the registry does not
    define, because the report is assembled from capability ids."""
    known = set(registry.demonstrable_ids())
    for act in engine.FULL_DEMO:
        assert act.capability in known, (
            f"act {act.title!r} names capability {act.capability!r}, which is not in "
            "the registry")


def test_every_act_has_exactly_one_witness():
    """An act with no witness would report SHOWN on the strength of having run,
    which is the failure the witness exists to prevent: a scenario can pass every
    property while the thing the act set out to show never happened."""
    for act in engine.FULL_DEMO:
        witnesses = [w for w in (act.witness, act.continuity_witness) if w is not None]
        assert len(witnesses) == 1, (
            f"act {act.title!r} has {len(witnesses)} witnesses; it needs exactly one")


def test_no_capability_is_client_safe_yet():
    """Not a style rule. No external client has been onboarded, the presentation
    boundary has never been exercised, and `PUBLIC_PRIVATE_BOUNDARY.md` is
    explicit that classification is a decision somebody records rather than a
    default. The day one is marked safe, that should be a deliberate edit that
    fails this test and makes somebody justify it."""
    marked = [c.id for c in registry.DEMONSTRABLE if c.client_safe]
    assert not marked, (
        f"{marked} are marked client-safe. Nothing has been through a presentation "
        "review, and a capability exposed to an external viewer by default is the "
        "accident the specification's security section exists to prevent.")


def test_witnesses_report_nothing_on_an_empty_run(tmp_path):
    """The anti-tautology check for the demo itself.

    A witness that returned True regardless would make every act report SHOWN,
    and the demo would be exactly the mockup the specification forbids. Against a
    database where the organization did nothing, every witness must say so."""
    conn = fi_db.get_connection(str(tmp_path / "empty.db"))
    try:
        fi_db.init_schema(conn)
        from simulation import metrics
        empty = metrics.collect_from(conn)
    finally:
        conn.close()

    for act in engine.FULL_DEMO:
        if act.witness is None:
            continue
        observed, _ = act.witness(empty)
        assert observed is False, (
            f"act {act.title!r} reports its capability as shown against a run in "
            "which nothing happened")
