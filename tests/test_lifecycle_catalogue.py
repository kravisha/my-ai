"""The lifecycle catalogue must stay honest about the system it describes.

A catalogue of what can happen to an agent is only useful if it cannot quietly
drift from the code, and if the holes in it stay countable. These tests hold
three things: entries are well-formed, every metric an entry claims to be
observable in actually exists, and the number of events with no defined
response is pinned so a new hole must be declared deliberately.

The observability check is the one that earns its place. An entry claiming a
metric that does not exist would produce a scenario asserting nothing, which is
the failure mode the whole simulation subsystem exists to stop repeating.
"""

import pytest

from backend import fi_db
from simulation import lifecycle, metrics


REQUIRED_KEYS = {"phase", "trigger", "expected_response", "observable", "injectable", "handled_by"}


@pytest.fixture(scope="module")
def metric_names(request):
    """Every dotted metric path the metric layer produces, from a real collection."""
    conn = fi_db.get_connection(":memory:")
    fi_db.init_schema(conn)
    try:
        collected = metrics.collect_from(conn)
    finally:
        conn.close()

    names = set()
    for family, values in collected.items():
        names.add(family)
        for key in values:
            names.add(f"{family}.{key}")
    return names


def test_every_entry_is_well_formed():
    for key, event in lifecycle.EVENTS.items():
        missing = REQUIRED_KEYS - set(event)
        assert not missing, f"{key} is missing {sorted(missing)}"
        assert event["phase"] in lifecycle.PHASES, f"{key} has unknown phase {event['phase']!r}"
        assert event["trigger"].strip(), f"{key} has no trigger"
        assert isinstance(event["injectable"], bool)
        assert isinstance(event["handled_by"], list)


def test_handling_roles_exist():
    """An event handled by a role that does not exist describes another system."""
    for key, event in lifecycle.EVENTS.items():
        for role in event["handled_by"]:
            assert role in fi_db.ROLE_CHARTERS, f"{key} names handler {role!r}, which has no charter"


def test_an_event_with_no_response_says_why():
    """A blank expected_response is a finding, and a finding needs its reason."""
    for key, event in lifecycle.unhandled().items():
        reason = event.get("no_response_reason", "")
        assert len(reason.split()) >= 15, (
            f"{key} has no defined response and no explanation of why. An open loop is recorded so "
            "it can be argued about later, which needs the diagnosis, not the label."
        )


def test_an_event_with_no_response_names_no_handler():
    """If something handled it, it would have a response."""
    for key, event in lifecycle.unhandled().items():
        assert event["handled_by"] == [], f"{key} claims a handler but defines no response"


def test_observable_metrics_actually_exist(metric_names):
    """The check that stops a scenario asserting nothing."""
    for key, event in lifecycle.EVENTS.items():
        path = event["observable"]
        if path is not None:
            assert path in metric_names, (
                f"{key} claims to be observable at {path!r}, which the metric layer does not produce"
            )


def test_unhandled_count_is_pinned():
    """The ratchet.

    A new event with no defined response fails until the count is raised on
    purpose; closing one fails until it is lowered. The number only moves when
    somebody means it to."""
    holes = sorted(lifecycle.unhandled())
    assert len(holes) == lifecycle.UNHANDLED_COUNT, (
        f"catalogue pins UNHANDLED_COUNT={lifecycle.UNHANDLED_COUNT} but {len(holes)} events define "
        f"no response: {holes}"
    )


def test_every_phase_of_a_life_is_covered():
    """An agent's life runs creation to termination; a phase with no events
    means the catalogue stopped paying attention rather than that nothing
    happens there."""
    for phase in lifecycle.PHASES:
        assert lifecycle.by_phase(phase), f"no events catalogued for the {phase!r} phase"


def test_most_events_can_be_caused_on_demand():
    """A catalogue of events nothing can trigger would describe a system that
    cannot be tested. Not all are injectable - a heartbeat can only be waited
    for - but the great majority must be."""
    injectable = len(lifecycle.injectable())
    assert injectable >= 0.8 * len(lifecycle.EVENTS), (
        f"only {injectable}/{len(lifecycle.EVENTS)} events can be caused on demand"
    )


def test_defined_responses_are_mostly_checkable():
    """How much of the catalogue is assertion versus measurement.

    Deliberately a floor rather than a requirement of totality: some responses
    are genuinely not visible in aggregate metrics, and pretending otherwise
    would push work into inventing a metric to satisfy a test."""
    defined = {k: e for k, e in lifecycle.EVENTS.items() if e["expected_response"] is not None}
    checkable = lifecycle.observable_events()
    assert len(checkable) >= 0.5 * len(defined), (
        f"only {len(checkable)}/{len(defined)} defined responses have an observable"
    )
