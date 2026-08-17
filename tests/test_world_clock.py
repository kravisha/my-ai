"""The world clock the organization shares, and what it deliberately does not touch.

**Two kinds of time.** Operational time is wall-clock - heartbeats, process
state, claims, spawn grace, shutdown - because those are facts about OS
processes. World time is simulated: when an observation happened, whether a
session is open. Every timing constant in this system is operational, and every
one would be wrong reinterpreted as simulated seconds; at the default scale a
45-second staleness threshold becomes 0.16 wall seconds and the whole workforce
is marked crashed on its first cycle.

So the clock adds a shared answer to "what time is it in the world" and changes
nothing about process liveness. These tests hold that boundary as much as they
hold the arithmetic.
"""

from datetime import datetime, timedelta, timezone

import pytest

from backend import fi_db

# A Monday at 16:00 UTC, which is inside the 14:30-21:00 equity session. The
# first version of this said 14:00 and called it in-session, which is half an
# hour before the open - the kind of fixture error that makes a session test
# assert the opposite of what it claims.
EPOCH = datetime(2026, 1, 5, 16, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(conn):
    fi_db.init_schema(conn)
    return conn


def started(seconds_ago: float = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)


# -- no clock configured ------------------------------------------------------

def test_without_a_clock_the_world_runs_in_real_time(db):
    """Not a special case: real time is scale 1 with the epoch at start, so the
    same arithmetic gives the same answer and an ordinary server is untouched."""
    now = datetime.now(timezone.utc)
    assert abs((fi_db.simulated_now(db) - now).total_seconds()) < 5


def test_without_a_clock_every_market_is_open(db):
    """Session enforcement is opt-in.

    Otherwise behaviour would depend on the wall-clock hour a run began, and a
    suite that passes in the morning and fails at night is worse than one that
    does not test sessions at all."""
    for data_class in ("option_surface", "equity_price", "mutual_fund_nav"):
        assert fi_db.market_is_open(db, data_class) is True


def test_no_clock_row_exists_until_one_is_set(db):
    assert fi_db.get_simulation_clock(db) is None


# -- a configured clock -------------------------------------------------------

def test_simulated_time_runs_at_the_configured_scale(db):
    fi_db.set_simulation_clock(db, epoch=EPOCH, scale=288, started_at=started(10))

    elapsed = (fi_db.simulated_now(db) - EPOCH).total_seconds()
    assert elapsed == pytest.approx(10 * 288, rel=0.05)


def test_every_process_reading_the_same_database_agrees_on_the_time(db):
    """The reason the clock is persisted rather than constructed.

    Six processes each deriving a clock would agree on the rate and disagree
    about when the run started, which is the same as disagreeing about the
    date."""
    fi_db.set_simulation_clock(db, epoch=EPOCH, scale=288, started_at=started(30))
    moment = datetime.now(timezone.utc)

    first = fi_db.simulated_now(db, wall=moment)
    second = fi_db.simulated_now(db, wall=moment)
    assert first == second


def test_setting_the_clock_twice_leaves_one_answer(db):
    """A run has one clock. A second row would mean two answers to what time it is."""
    fi_db.set_simulation_clock(db, epoch=EPOCH, scale=288)
    fi_db.set_simulation_clock(db, epoch=EPOCH, scale=10)

    assert db.fetchone("SELECT COUNT(*) AS n FROM simulation_clock")["n"] == 1
    assert fi_db.get_simulation_clock(db)["scale"] == 10


# -- sessions -----------------------------------------------------------------

def test_the_equity_market_is_shut_overnight_when_sessions_are_enforced(db):
    overnight = datetime(2026, 1, 6, 3, 0, tzinfo=timezone.utc)
    fi_db.set_simulation_clock(db, epoch=overnight, scale=1, enforce_sessions=True)

    assert fi_db.market_is_open(db, "option_surface") is False


def test_markets_do_not_close_together(db):
    """The reason sessions are per data class rather than one calendar."""
    overnight = datetime(2026, 1, 6, 3, 0, tzinfo=timezone.utc)
    fi_db.set_simulation_clock(db, epoch=overnight, scale=1, enforce_sessions=True)

    assert fi_db.market_is_open(db, "option_surface") is False
    assert fi_db.market_is_open(db, "commodity_price") is True


def test_social_chatter_never_closes(db):
    """Deliberate, and the point of the whole per-class design.

    An organization that went quiet with the exchange would miss the overnight
    chatter that is often the most informative part of the day."""
    overnight = datetime(2026, 1, 6, 3, 0, tzinfo=timezone.utc)
    fi_db.set_simulation_clock(db, epoch=overnight, scale=1, enforce_sessions=True)

    assert fi_db.market_is_open(db, "social_post") is True


def test_the_equity_market_is_open_mid_session(db):
    fi_db.set_simulation_clock(db, epoch=EPOCH, scale=1, enforce_sessions=True)
    assert fi_db.market_is_open(db, "option_surface") is True


def test_a_clock_without_enforcement_leaves_every_market_open(db):
    """Simulated time and session gating are separate switches: a scenario may
    want a world clock without agents standing down."""
    overnight = datetime(2026, 1, 6, 3, 0, tzinfo=timezone.utc)
    fi_db.set_simulation_clock(db, epoch=overnight, scale=1, enforce_sessions=False)

    assert fi_db.market_is_open(db, "option_surface") is True


def test_an_unknown_data_class_is_treated_as_open(db):
    """A class the taxonomy does not yet cover must not silently stop an agent.

    Failing open is right here: the cost of scanning something that was shut is a
    wasted cycle, and the cost of standing down forever is an agent that appears
    healthy and does nothing."""
    fi_db.set_simulation_clock(db, epoch=EPOCH, scale=1, enforce_sessions=True)
    assert fi_db.market_is_open(db, "something_not_in_the_taxonomy") is True


# -- the boundary that must not move -----------------------------------------

def test_operational_timing_constants_are_untouched_by_the_world_clock():
    """The load-bearing separation.

    If heartbeat staleness were ever reinterpreted as simulated seconds, at the
    default scale the 45-second threshold would become 0.16 wall seconds and
    every agent would be marked crashed on its first cycle. These constants are
    about processes, not about the market."""
    from agents import coo
    from backend import controller
    from simulation.clock import DEFAULT_SCALE

    assert coo.HEALTH_STALE_THRESHOLD_SECONDS == 45.0
    assert controller.AGENT_STOP_GRACE_SECONDS > 0
    assert fi_db.CLAIM_TIMEOUT_SECONDS > 0

    # The invariant, stated so it survives a change of rate. This previously
    # asserted the misread threshold would be sub-second, which was true at 288
    # and false at 24 - it was pinning an artefact of the scale rather than the
    # property that matters.
    #
    # What matters at any scale above 1: reading a wall-clock constant as
    # simulated time compresses it by the scale factor, and 45 wall seconds was
    # chosen because it exceeds real model latency. At 24x the misreading gives
    # 1.9 wall seconds - not sub-second, and still short enough to mark every
    # busy agent crashed on its first cycle.
    assert DEFAULT_SCALE > 1.0
    misread = coo.HEALTH_STALE_THRESHOLD_SECONDS / DEFAULT_SCALE
    assert misread < coo.HEALTH_STALE_THRESHOLD_SECONDS
    assert misread < 5.0, (
        "a wall-clock threshold read as simulated time would still be far below real model latency"
    )


def test_heartbeats_stay_on_wall_clock_time(db):
    """A heartbeat is a claim that a process is alive now, in the real world."""
    fi_db.set_simulation_clock(db, epoch=EPOCH, scale=288, started_at=started(0))
    fi_db.register_agent(db, "dummy-1", "dummy", 100)
    fi_db.record_heartbeat(db, "dummy-1")

    recorded = fi_db.parse_timestamp(fi_db.get_agent(db, "dummy-1")["last_heartbeat_at"])
    drift = abs((recorded - datetime.now(timezone.utc)).total_seconds())
    assert drift < 5, "a heartbeat was recorded in simulated time"


def test_heartbeat_age_is_not_inflated_by_the_scale(db):
    """The concrete failure this boundary prevents.

    With a scale of 288, an agent that heartbeat one wall second ago would look
    288 seconds stale if the comparison were made in simulated time - well past
    the 45-second threshold, so a healthy agent is respawned every cycle."""
    fi_db.set_simulation_clock(db, epoch=EPOCH, scale=288, started_at=started(0))
    fi_db.register_agent(db, "dummy-1", "dummy", 100)
    fi_db.record_heartbeat(db, "dummy-1")

    age = fi_db.heartbeat_age_seconds(fi_db.get_agent(db, "dummy-1"))
    assert age < 5
