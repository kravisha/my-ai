"""Slot allocation, and staffing a role with more than one agent.

Judgment latency is the time to cycle the whole security universe divided by the
number of judgment agents - measured at ~235s with one agent over ten securities.
Until now the organization had no way to say "this role needs two", because
identity was hardcoded to slot 1.

The hard part is not issuing `analysis-2`. It is that the same directive - "role
X is short" - means refill an existing slot in one situation and open a new one
in another, and getting that backwards is expensive both ways: a wrong refill
attaches a new agent to somebody else's history, and a wrong new slot abandons a
crashed agent's record and quietly doubles the population.
"""

import time

import pytest

from agents.coo import _ensure_baseline_population, _spawns_in_flight
from backend import fi_db


@pytest.fixture
def db(conn):
    fi_db.init_schema(conn)
    return conn


def staff(conn, role: str, count: int, first_slot: int = 1):
    for offset in range(count):
        fi_db.register_agent(conn, f"{role}-{first_slot + offset}", role, 100 + offset)


# -- allocation ---------------------------------------------------------------

def test_the_first_agent_of_a_role_gets_slot_one(db):
    assert fi_db.allocate_slot(db, "analysis") == "analysis-1"


def test_a_slot_whose_process_died_is_refilled_under_the_same_identity(db):
    """The point of a permanent slot: the agent comes back as itself.

    Its name, assignment span and performance record are keyed to the identity,
    so issuing a new slot here would start that agent over from nothing."""
    staff(db, "analysis", 1)
    fi_db.mark_process_crashed(db, "analysis-1")

    assert fi_db.allocate_slot(db, "analysis") == "analysis-1"


def test_a_new_slot_opens_only_when_every_active_slot_is_running(db):
    staff(db, "analysis", 1)
    assert fi_db.allocate_slot(db, "analysis") == "analysis-2"


def test_the_lowest_dead_slot_is_refilled_first(db):
    """Deterministic, so a refill does not depend on row order."""
    staff(db, "analysis", 3)
    fi_db.mark_process_crashed(db, "analysis-3")
    fi_db.mark_process_crashed(db, "analysis-2")

    assert fi_db.allocate_slot(db, "analysis") == "analysis-2"


def test_a_dormant_slot_is_never_refilled(db):
    """Retirement is a decision the Controller took; respawning into it would
    silently undo it."""
    staff(db, "analysis", 1)
    fi_db.request_retirement(db, "analysis-1")

    assert fi_db.allocate_slot(db, "analysis") == "analysis-2"


def test_a_new_slot_numbers_above_the_highest_ever_used(db):
    """Above the highest EVER, not the highest currently active.

    Reusing a retired member's number would attach a new agent to another
    agent's name, assignment history and grades."""
    staff(db, "analysis", 3)
    fi_db.request_retirement(db, "analysis-2")

    assert fi_db.allocate_slot(db, "analysis") == "analysis-4"


def test_slots_are_ordered_numerically_not_as_strings(db):
    """`analysis-10` sorts after `analysis-9`, not before it.

    Invisible until a role reaches ten members, at which point a string sort
    allocates a slot that is already taken."""
    staff(db, "analysis", 10)
    assert fi_db.allocate_slot(db, "analysis") == "analysis-11"
    assert [m["identity"] for m in fi_db.role_members(db, "analysis")][-1] == "analysis-10"


def test_slot_number_of_an_unconventional_identity_is_zero(db):
    assert fi_db.slot_number("controller-1") == 1
    assert fi_db.slot_number("something-odd") == 0


# -- staffing counts ----------------------------------------------------------

def test_staffing_separates_running_from_awaiting_from_dormant(db):
    staff(db, "analysis", 3)
    fi_db.mark_process_crashed(db, "analysis-2")
    fi_db.request_retirement(db, "analysis-3")

    numbers = fi_db.staffing(db, "analysis")
    assert numbers["members"] == 3
    assert numbers["running"] == 1
    assert numbers["awaiting_process"] == 1
    assert numbers["dormant"] == 1


# -- COO staffing to a target -------------------------------------------------

def spawns_for(conn, role: str) -> int:
    return conn.fetchone(
        "SELECT COUNT(*) AS n FROM coo_directives WHERE target_role = ? AND status = 'pending'",
        (role,),
    )["n"]


def test_a_role_with_a_target_of_two_gets_two_spawns(db, monkeypatch):
    monkeypatch.setitem(__import__("agents.coo", fromlist=["x"]).BASELINE_POPULATION, "analysis", 2)
    _ensure_baseline_population(db)
    assert spawns_for(db, "analysis") == 2


def test_the_second_spawn_is_not_suppressed_by_the_first(db, monkeypatch):
    """A boolean in-flight check allowed exactly one spawn per role per cycle.

    With a target above one that silently caps the role at a single agent -
    the feature would look built and never staff anything."""
    monkeypatch.setitem(__import__("agents.coo", fromlist=["x"]).BASELINE_POPULATION, "analysis", 3)
    _ensure_baseline_population(db)
    assert spawns_for(db, "analysis") == 3
    assert _spawns_in_flight(db, "analysis") == 3


def test_a_fully_staffed_role_asks_for_nothing(db, monkeypatch):
    monkeypatch.setitem(__import__("agents.coo", fromlist=["x"]).BASELINE_POPULATION, "analysis", 2)
    staff(db, "analysis", 2)
    _ensure_baseline_population(db)
    assert spawns_for(db, "analysis") == 0


def test_an_overstaffed_role_is_not_trimmed(db, monkeypatch):
    """COO staffs up, never down. Removing an agent is a retirement, which is
    the Controller's decision and carries consequences for that agent's record."""
    monkeypatch.setitem(__import__("agents.coo", fromlist=["x"]).BASELINE_POPULATION, "analysis", 1)
    staff(db, "analysis", 3)
    _ensure_baseline_population(db)

    assert spawns_for(db, "analysis") == 0
    assert fi_db.staffing(db, "analysis")["members"] == 3


def test_a_dormant_member_lowers_the_target_rather_than_being_replaced(db, monkeypatch):
    """Retirement genuinely leaves the role short.

    If COO backfilled a substitute, retiring an agent would have no visible
    effect on the workforce, which is the opposite of what it means."""
    coo = __import__("agents.coo", fromlist=["x"])
    monkeypatch.setitem(coo.BASELINE_POPULATION, "analysis", 2)
    staff(db, "analysis", 2)
    fi_db.request_retirement(db, "analysis-2")

    _ensure_baseline_population(db)
    assert spawns_for(db, "analysis") == 0


def test_a_crashed_member_of_a_multi_agent_role_is_replaced(db, monkeypatch):
    monkeypatch.setitem(__import__("agents.coo", fromlist=["x"]).BASELINE_POPULATION, "analysis", 2)
    staff(db, "analysis", 2)
    fi_db.mark_process_crashed(db, "analysis-1")

    _ensure_baseline_population(db)
    assert spawns_for(db, "analysis") == 1


def test_the_target_is_settable_from_the_environment(monkeypatch):
    """What makes one-versus-two judgment agents an experiment rather than an edit."""
    monkeypatch.setenv("FI_BASELINE_ANALYSIS", "4")
    import importlib

    import agents.coo as coo
    importlib.reload(coo)
    try:
        assert coo.BASELINE_POPULATION["analysis"] == 4
    finally:
        monkeypatch.delenv("FI_BASELINE_ANALYSIS")
        importlib.reload(coo)


def test_the_controller_is_never_a_baseline_role():
    """The Controller is the running server; asking it to spawn one would mean
    launching an agents/controller.py that deliberately does not exist."""
    import agents.coo as coo

    assert "controller" not in coo.BASELINE_POPULATION
    assert "coo" not in coo.BASELINE_POPULATION


# -- the reserved-slot race ---------------------------------------------------

def complete_spawn(conn, role: str, identity: str):
    directive_id = fi_db.enqueue_directive(conn, "spawn", requested_by="coo", target_role=role)
    fi_db.complete_directive(conn, directive_id, "success", detail=identity)


def test_a_slot_already_issued_is_not_issued_again(db):
    """Regression for a duplicate-process bug reintroduced by multi-instance.

    A slot is only visible in agent_registry once its process registers. Staffing
    judgment with two agents for the first time produced two directives executed
    inside that gap, both allocated `analysis-1`, and two processes came up under
    one identity - the exact defect that once produced three concurrent agents
    racing for the same queue."""
    complete_spawn(db, "analysis", fi_db.allocate_slot(db, "analysis"))

    assert fi_db.allocate_slot(db, "analysis") == "analysis-2", (
        "the second allocation reissued a slot whose process had not registered yet"
    )


def test_a_reserved_slot_is_released_once_its_agent_registers(db):
    complete_spawn(db, "analysis", "analysis-1")
    assert fi_db.slots_awaiting_registration(db, "analysis") == {"analysis-1"}

    fi_db.register_agent(db, "analysis-1", "analysis", 111)

    assert fi_db.slots_awaiting_registration(db, "analysis") == set()


def test_a_reserved_slot_is_not_refilled_even_though_it_looks_idle(db):
    """A crashed agent being respawned must not be handed out a second time.

    Its registry row still reads 'crashed' until the new process registers, so
    the refill branch would happily return it again."""
    staff(db, "analysis", 1)
    fi_db.mark_process_crashed(db, "analysis-1")
    # completed_at is written by the archive trigger at millisecond precision
    # while spawned_at carries microseconds, so a same-instant pair compares as
    # "already registered". A real respawn always has tens of milliseconds of
    # subprocess startup in between; this reflects that rather than an
    # artificial collision. tests/test_coo.py does the same for the same reason.
    time.sleep(0.02)
    complete_spawn(db, "analysis", "analysis-1")

    assert fi_db.allocate_slot(db, "analysis") == "analysis-2"


def test_a_stale_reservation_expires(db):
    """A spawn that never landed must not reserve its slot forever, or the role
    can never be restaffed."""
    complete_spawn(db, "analysis", "analysis-1")
    assert fi_db.slots_awaiting_registration(db, "analysis", within_seconds=0) == set()


def test_coo_and_the_controller_agree_on_what_is_in_flight(db):
    """They must share the predicate.

    If COO's idea of "still coming up" and the Controller's idea of "already
    issued" drifted apart, one would ask for an agent the other was starting."""
    complete_spawn(db, "analysis", "analysis-1")

    assert _spawns_in_flight(db, "analysis") == 1
    assert fi_db.allocate_slot(db, "analysis") == "analysis-2"


def test_a_zero_width_window_contains_nothing(db):
    """The boundary, pinned because it was an intermittent failure rather than
    a theory.

    `recent_completed_spawns` compared `>=` against the cutoff, so a spawn whose
    `completed_at` equalled it counted as still in flight - and equality is the
    normal case on Windows, where two consecutive `datetime.now()` calls return
    the identical value about 19,997 times in 20,000, and where the archive
    trigger truncates `completed_at` to the second. A zero-width window has to
    be empty by definition; asking whether anything happened in no time at all
    has one correct answer."""
    complete_spawn(db, "analysis", "analysis-1")
    for _ in range(50):
        assert fi_db.recent_completed_spawns(db, "analysis", 0) == []
        assert fi_db.slots_awaiting_registration(db, "analysis", within_seconds=0) == set()


def test_a_real_window_still_catches_a_spawn_in_flight(db):
    """The other half: the guard exists because two agents once came up under
    one identity, and narrowing the comparison must not have widened that hole."""
    complete_spawn(db, "analysis", "analysis-1")
    assert fi_db.slots_awaiting_registration(db, "analysis", within_seconds=600) == {"analysis-1"}
