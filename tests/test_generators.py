"""The generator contract and the orchestrator that keeps generators coherent.

This is the decision that determines whether later generators are additive or a
rewrite, so the tests are about the contract's guarantees rather than about any
particular generator's output.

Three guarantees carry it: the clock decides when a generator runs, the
orchestrator decides when output becomes knowable, and coherence travels as
events rather than as calls between generators. The last one is the easiest to
build and never notice is broken - an event bus nobody emits into passes every
test and works never - so it is exercised end to end with a real producer and a
real consumer.
"""

from datetime import datetime, timedelta, timezone

import pytest

from providers.market_data import SyntheticMarketDataProvider
from providers.social_data import SyntheticSocialDataProvider
from simulation.clock import SimulationClock
from simulation.generators import GenerationRequest, GenerationResult, WorldEvent
from simulation.generators.builtin import MacroGenerator, MarketGenerator, SocialGenerator
from simulation.generators.orchestrator import Orchestrator

SESSION_OPEN = datetime(2026, 1, 5, 16, 0, tzinfo=timezone.utc)     # Monday, equity session
OVERNIGHT = datetime(2026, 1, 6, 3, 0, tzinfo=timezone.utc)         # equities shut
WALL = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def clock_at(moment, scale=1):
    return SimulationClock(epoch=moment, scale=scale, started_at=WALL)


def orchestrator_at(moment, generators, subjects=("SYN1", "SYN2"), **kwargs):
    return Orchestrator(clock_at(moment), generators, subjects=subjects, **kwargs)


class Stub:
    """A generator that produces and emits exactly what it is told to."""

    def __init__(self, name, data_classes, observations=(), events=()):
        self.name = name
        self.data_classes = data_classes
        self._observations = list(observations)
        self._events = list(events)
        self.calls = 0
        self.last_request = None

    def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls += 1
        self.last_request = request
        return GenerationResult(
            observations=[dict(o) for o in self._observations],
            events=list(self._events),
        )


# -- registration -------------------------------------------------------------

def test_a_generator_with_an_unknown_data_class_is_refused():
    """A class absent from the registry has no session and no publication lag,
    so the orchestrator could neither schedule it nor say when its output
    becomes knowable. Defaulting both would produce a generator that runs
    constantly and publishes instantly."""
    with pytest.raises(ValueError, match="cadence registry does not carry"):
        orchestrator_at(SESSION_OPEN, [Stub("bad", ("moon_phase",))])


def test_two_generators_cannot_share_a_name():
    with pytest.raises(ValueError, match="already registered"):
        orchestrator_at(SESSION_OPEN, [Stub("a", ("cpi",)), Stub("a", ("cpi",))])


# -- the clock decides when a generator runs ---------------------------------

def test_a_generator_is_not_called_while_its_market_is_shut():
    market = Stub("market", ("option_surface",))
    orchestrator_at(OVERNIGHT, [market]).tick(WALL)
    assert market.calls == 0


def test_a_generator_whose_data_never_closes_is_always_called():
    """Published statistics have no session, and chatter has no closing bell."""
    macro = Stub("macro", ("cpi",))
    social = Stub("social", ("social_post",))
    orchestrator_at(OVERNIGHT, [macro, social]).tick(WALL)
    assert (macro.calls, social.calls) == (1, 1)


def test_a_closed_data_class_is_dropped_even_when_produced():
    """A generator called because one of its classes is open does not thereby
    get to publish the others."""
    mixed = Stub(
        "mixed", ("cpi", "option_surface"),
        observations=[
            {"data_class": "cpi", "subject": "US", "value": {}},
            {"data_class": "option_surface", "subject": "SYN1", "value": {}},
        ],
    )
    produced = orchestrator_at(OVERNIGHT, [mixed]).tick(WALL)

    assert mixed.calls == 1
    assert [o.data_class for o in produced] == ["cpi"]


# -- the orchestrator decides when output is knowable -------------------------

def test_a_published_figure_is_not_knowable_on_the_day_it_describes():
    """The guard that makes lookahead impossible by construction.

    A generator says what it is describing; only the cadence knows when the
    world would have found out. A macro generator that published on the day it
    described would inflate everything downstream and show up nowhere."""
    macro = Stub("macro", ("cpi",), observations=[{"data_class": "cpi", "subject": "US", "value": {}}])
    produced = orchestrator_at(SESSION_OPEN, [macro]).tick(WALL)

    observation = produced[0]
    assert observation.knowable_at > observation.effective_at
    assert observation.knowable_at - observation.effective_at >= timedelta(days=14)


def test_a_traded_price_is_knowable_when_it_happens():
    market = Stub("market", ("option_surface",),
                  observations=[{"data_class": "option_surface", "subject": "SYN1", "value": {}}])
    observation = orchestrator_at(SESSION_OPEN, [market]).tick(WALL)[0]
    assert observation.knowable_at == observation.effective_at


def test_visible_hides_what_has_not_been_published_yet():
    """The consumer-side half. Generators cannot publish early; this stops a
    consumer reading early, which is the same error from the other end."""
    macro = Stub("macro", ("cpi",), observations=[{"data_class": "cpi", "subject": "US", "value": {}}])
    orchestrator = orchestrator_at(SESSION_OPEN, [macro])
    produced = orchestrator.tick(WALL)

    assert orchestrator.visible(produced, now=SESSION_OPEN) == []
    assert len(orchestrator.visible(produced, now=SESSION_OPEN + timedelta(days=20))) == 1


def test_the_generator_is_recorded_on_every_observation():
    """Provenance: which generator produced this, for a world assembled from many."""
    macro = Stub("macro", ("cpi",), observations=[{"data_class": "cpi", "subject": "US", "value": {}}])
    assert orchestrator_at(SESSION_OPEN, [macro]).tick(WALL)[0].generator == "macro"


# -- coherence travels as events ---------------------------------------------

def shock_event(magnitude=0.8):
    return WorldEvent(kind="inflation_surprise", magnitude=magnitude,
                      occurred_at=SESSION_OPEN, source="macro")


def test_an_event_is_not_visible_on_the_tick_that_emits_it():
    """Deliberate. Same-tick visibility needs an ordering among generators, and
    an ordering among ten generators is a dependency graph nobody can hold."""
    emitter = Stub("macro", ("cpi",), events=[shock_event()])
    watcher = Stub("market", ("option_surface",))
    orchestrator = orchestrator_at(SESSION_OPEN, [emitter, watcher])

    orchestrator.tick(WALL)
    assert watcher.last_request.events == ()


def test_an_event_reaches_other_generators_on_the_next_tick():
    emitter = Stub("macro", ("cpi",), events=[shock_event()])
    watcher = Stub("market", ("option_surface",))
    orchestrator = orchestrator_at(SESSION_OPEN, [emitter, watcher])

    orchestrator.tick(WALL)
    orchestrator.tick(WALL)

    assert [e.kind for e in watcher.last_request.events] == ["inflation_surprise"]


def test_an_event_ages_out_of_the_window():
    """A shock stops mattering. Without expiry the world would accumulate every
    event it ever had and read as permanently disturbed."""
    emitter = Stub("macro", ("cpi",), events=[shock_event()])
    watcher = Stub("market", ("option_surface",))
    orchestrator = Orchestrator(
        clock_at(SESSION_OPEN, scale=100_000), [emitter, watcher],
        subjects=("SYN1",), event_window=timedelta(minutes=30),
    )

    orchestrator.tick(WALL)
    orchestrator.tick(WALL + timedelta(seconds=1))
    orchestrator.tick(WALL + timedelta(seconds=5))

    assert orchestrator.events_in_flight() == ()


def test_a_generator_can_respond_to_an_event_it_has_never_heard_of():
    """`shock()` sums whatever is in flight, so a generator stays coherent with
    event kinds added after it was written. One that only reacted to kinds it
    recognised would silently ignore every new one - which is the failure that
    makes a coherence layer look like it works."""
    unknown = WorldEvent(kind="a_kind_invented_later", magnitude=0.5,
                         occurred_at=SESSION_OPEN, source="future")
    request = GenerationRequest(now=SESSION_OPEN, since=None, subjects=(), events=(unknown,))
    assert request.shock() == 0.5


# -- the real generators, and coherence end to end ---------------------------

def real_orchestrator(**kwargs):
    return Orchestrator(
        clock_at(SESSION_OPEN),
        [
            MarketGenerator(SyntheticMarketDataProvider(seed=42)),
            SocialGenerator(SyntheticSocialDataProvider(seed=7)),
            MacroGenerator(seed=1, **kwargs),
        ],
        subjects=("SYN1", "SYN2"),
    )


def test_the_existing_providers_produce_through_the_contract():
    """The adapters are proved against the real providers, not against something
    written to fit the contract."""
    produced = real_orchestrator(surprise_probability=0.0).tick(WALL)
    classes = {o.data_class for o in produced}

    assert "option_surface" in classes
    assert "social_post" in classes
    assert all(o.value for o in produced), "an observation carried no value"


def test_the_market_adapter_reads_the_surface_it_was_given():
    """Regression: the first version looked for `implied_volatility` and the
    attribute is `iv`, so it would have emitted nothing while appearing to work."""
    produced = real_orchestrator(surprise_probability=0.0).tick(WALL)
    surfaces = [o for o in produced if o.data_class == "option_surface"]

    assert surfaces, "no surface observations were produced at all"
    assert all(o.value["points"] > 0 and o.value["mean_iv"] > 0 for o in surfaces)


def test_a_macro_shock_moves_the_market_on_the_following_tick():
    """The coherence proof.

    An event bus that no generator emits into and none reads from passes every
    other test in this file and works never. This is the arrangement that can
    actually fail."""
    orchestrator = real_orchestrator(surprise_probability=1.0)

    first = orchestrator.tick(WALL)
    assert any(o.data_class == "cpi" for o in first)
    quiet = [o for o in first if o.data_class == "option_surface"][0]
    assert quiet.value["shock_applied"] == 0.0

    second = orchestrator.tick(WALL)
    moved = [o for o in second if o.data_class == "option_surface"][0]

    assert moved.value["shock_applied"] > 0.0, "a macro surprise did not reach the market generator"
    assert moved.value["mean_iv"] > quiet.value["mean_iv"]


def test_no_shock_leaves_the_market_alone():
    """The other side, so the coherence test cannot pass by always widening."""
    orchestrator = real_orchestrator(surprise_probability=0.0)
    orchestrator.tick(WALL)
    second = orchestrator.tick(WALL)

    surfaces = [o for o in second if o.data_class == "option_surface"]
    assert all(o.value["shock_applied"] == 0.0 for o in surfaces)


# -- state, for a world that has to survive a rollover ------------------------

def test_generator_state_persists_between_ticks():
    """The macro generator releases monthly, which it can only know by
    remembering when it last did."""
    orchestrator = real_orchestrator(surprise_probability=1.0)
    orchestrator.tick(WALL)
    second = orchestrator.tick(WALL)

    assert "last_release" in orchestrator.state()["macro"]
    assert not [o for o in second if o.data_class == "cpi"], "released twice within a month"


def test_state_can_be_restored_into_a_fresh_orchestrator():
    """What a continuously advancing world needs: a price level that reset each
    morning would not be a price level."""
    first = real_orchestrator(surprise_probability=1.0)
    first.tick(WALL)
    carried = first.state()

    second = real_orchestrator(surprise_probability=1.0)
    second.restore(carried)

    assert second.state()["macro"]["last_release"] == carried["macro"]["last_release"]
    assert not [o for o in second.tick(WALL) if o.data_class == "cpi"]
