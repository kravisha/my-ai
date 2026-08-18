"""The canonical observation contract and the identity beneath it.

Two requirements pull against each other here and the tension is the design:
addendum 20 §3 wants a uniform shape so consumers cannot tell synthetic from live
by looking, and the Manifesto's §15 says data must never lie about what it is. The
resolution is that the shape is uniform and the provenance is mandatory - so most
of these tests are about what the contract *refuses*.
"""

import pytest

from backend import canonical, fi_db, identifiers
from providers.market_data import SyntheticMarketDataProvider
from simulation.cadences import CADENCES, lagged


@pytest.fixture
def conn():
    connection = fi_db.get_connection(":memory:")
    fi_db.init_schema(connection)
    yield connection
    connection.close()


# --- Identity: a symbol is not an entity --------------------------------


def test_a_ticker_can_change_hands_without_merging_two_histories(conn):
    """The case the whole module exists for, and the one a symbol-keyed system
    gets silently wrong.

    A delisted ticker reissued to an unrelated company would, in a system keyed on
    the symbol, join two companies' price histories into one series - and the join
    would look like a discovery, because the break falls exactly where the
    reassignment happened."""
    first = identifiers.create_entity(conn, "security", display_name="First Corp")
    identifiers.add_identifier(conn, first, "symbol", "ACME", source="test",
                               valid_from="2020-01-01T00:00:00+00:00")
    identifiers.retire_identifier(conn, "symbol", "ACME", valid_to="2023-01-01T00:00:00+00:00")

    second = identifiers.create_entity(conn, "security", display_name="Second Corp")
    identifiers.add_identifier(conn, second, "symbol", "ACME", source="test",
                               valid_from="2024-01-01T00:00:00+00:00")

    assert identifiers.resolve(conn, "symbol", "ACME", as_of="2021-06-01T00:00:00+00:00") == first
    assert identifiers.resolve(conn, "symbol", "ACME", as_of="2025-06-01T00:00:00+00:00") == second
    assert identifiers.resolve(conn, "symbol", "ACME") == second, "today's answer is the live holder"
    # And the gap between them belongs to nobody, which is the honest answer.
    assert identifiers.resolve(conn, "symbol", "ACME", as_of="2023-06-01T00:00:00+00:00") is None


def test_an_entity_outlives_its_names(conn):
    """FB became META and the company did not change."""
    entity = identifiers.create_entity(conn, "security", display_name="Meta Platforms")
    identifiers.add_identifier(conn, entity, "symbol", "FB", source="test",
                               valid_from="2012-05-18T00:00:00+00:00")
    identifiers.retire_identifier(conn, "symbol", "FB", valid_to="2022-06-09T00:00:00+00:00")
    identifiers.add_identifier(conn, entity, "symbol", "META", source="test",
                               valid_from="2022-06-09T00:00:00+00:00")

    assert identifiers.resolve(conn, "symbol", "FB", as_of="2015-01-01T00:00:00+00:00") == entity
    assert identifiers.resolve(conn, "symbol", "META") == entity
    assert len(identifiers.identifiers_for(conn, entity, include_retired=True)) == 2
    assert len(identifiers.identifiers_for(conn, entity)) == 1


def test_two_entities_cannot_hold_one_live_symbol(conn):
    first = identifiers.ensure_security(conn, "ACME")
    second = identifiers.create_entity(conn, "security")

    with pytest.raises(identifiers.IdentifierError, match="Retire it there first"):
        identifiers.add_identifier(conn, second, "symbol", "ACME", source="test")

    assert identifiers.resolve(conn, "symbol", "ACME") == first


def test_an_unknown_scheme_is_refused(conn):
    """A typo would silently create a second namespace that resolves nothing and
    conflicts with nothing."""
    entity = identifiers.create_entity(conn, "security")

    with pytest.raises(identifiers.IdentifierError, match="unknown scheme"):
        identifiers.add_identifier(conn, entity, "symbal", "ACME", source="test")


def test_the_bridge_from_the_symbol_keyed_world_is_idempotent(conn):
    """Every existing detector event and report names a security by symbol.
    `ensure_security` lets the entity-keyed side grow without a migration nobody
    asked for."""
    first = identifiers.ensure_security(conn, "SYN1")

    assert identifiers.ensure_security(conn, "SYN1") == first
    assert identifiers.get_entity(conn, first)["entity_type"] == "security"


# --- Provenance: the part that cannot be defaulted ----------------------


def test_an_observation_cannot_be_built_without_saying_where_it_came_from():
    with pytest.raises(TypeError):
        canonical.Provenance()  # no origin, no source

    with pytest.raises(canonical.ContractError, match="no default and no unknown"):
        canonical.Provenance(origin="unknown", source="x")

    with pytest.raises(canonical.ContractError, match="needs a source"):
        canonical.Provenance(origin="live", source="  ")


def test_real_data_cannot_wear_a_simulated_world_s_labels():
    """run_id and scenario_id describe a simulated world. On live or historical
    data they would make real observations look simulated - the same lie as §15's,
    pointing the other way."""
    for origin in ("historical", "live"):
        with pytest.raises(canonical.ContractError, match="carries no run_id"):
            canonical.Provenance(origin=origin, source="x", run_id="run-1")

    assert canonical.Provenance(origin="synthetic", source="x", run_id="run-1").is_synthetic


def test_provenance_cannot_be_edited_after_the_fact():
    """Provenance that can be changed is a claim rather than a record."""
    provenance = canonical.Provenance(origin="synthetic", source="x")

    with pytest.raises(Exception):
        provenance.origin = "live"


# --- The observation ----------------------------------------------------


def _observation(**overrides):
    defaults = dict(
        entity_id="JE-000001",
        data_class="option_surface",
        observed_at="2026-08-18T12:00:00+00:00",
        payload={"points": []},
        provenance=canonical.Provenance(origin="synthetic", source="test"),
    )
    return canonical.Observation(**{**defaults, **overrides})


def test_an_observation_needs_an_entity_not_a_symbol():
    with pytest.raises(canonical.ContractError, match="not a symbol"):
        _observation(entity_id="")


def test_an_unknown_data_class_is_refused_and_says_where_the_taxonomy_is():
    with pytest.raises(canonical.ContractError, match="cadences"):
        _observation(data_class="vibes")


def test_knowable_at_is_derived_from_the_publication_lag():
    """A home price index describes a month that ended two months earlier.
    Deriving this from `cadences.py` rather than asking each producer to supply it
    is what stops a simulation quietly handing the organization the future."""
    lagged_class = lagged()[0]
    lag = CADENCES[lagged_class].publication_lag
    assert lag.total_seconds() > 0, "this test needs a class that is actually lagged"

    observation = _observation(data_class=lagged_class, observed_at="2026-01-01T00:00:00+00:00")

    assert observation.knowable_at != observation.observed_at
    from backend.db import parse_timestamp
    assert parse_timestamp(observation.knowable_at) - parse_timestamp(observation.observed_at) == lag


def test_an_observation_cannot_be_knowable_before_it_was_true():
    with pytest.raises(canonical.ContractError, match="knowable before it was true"):
        _observation(observed_at="2026-08-18T12:00:00+00:00",
                     knowable_at="2026-08-18T11:00:00+00:00")


def test_the_lookahead_guard_is_a_question_the_observation_answers():
    """A rule every consumer has to remember is a rule some consumer will forget."""
    lagged_class = lagged()[0]
    observation = _observation(data_class=lagged_class, observed_at="2026-01-01T00:00:00+00:00")

    assert observation.known_by(observation.knowable_at) is True
    assert observation.known_by("2026-01-02T00:00:00+00:00") is False, (
        "the day after the fact was true is still before it was published"
    )


def test_a_record_cannot_be_passed_on_with_the_origin_dropped():
    record = _observation().as_record()

    assert record["origin"] == "synthetic"
    assert record["source"] == "test"
    assert "payload" in record and "entity_id" in record


def test_a_batch_can_refuse_origins_the_caller_did_not_expect():
    """§15 permits combining domains deliberately and transparently. This is what
    makes the deliberate case say so, at the boundary rather than in a
    conclusion."""
    synthetic = _observation()
    live = _observation(provenance=canonical.Provenance(origin="live", source="feed"))

    canonical.require_origin([synthetic], {"synthetic"})
    canonical.require_origin([synthetic, live], {"synthetic", "live"})

    with pytest.raises(canonical.ContractError, match="only \\['historical', 'live'\\]"):
        canonical.require_origin([synthetic, live], {"historical", "live"})


# --- The one real producer ----------------------------------------------


def test_the_synthetic_provider_emits_the_contract(conn):
    """A contract nothing emits is a proposal, not a foundation."""
    entity = identifiers.ensure_security(conn, "SYN1")
    provider = SyntheticMarketDataProvider(seed=42)

    observation = provider.observe(
        "SYN1", entity_id=entity, observed_at="2026-08-18T12:00:00+00:00",
        run_id="run-1", scenario_id="baseline",
    )

    assert observation.entity_id == entity
    assert observation.data_class == "option_surface"
    assert observation.payload["points"], "the surface came through"
    assert observation.provenance.origin == "synthetic"
    assert observation.provenance.run_id == "run-1"
    assert "seed=42" in observation.provenance.source, "which generator, not just which kind"


def test_the_synthetic_provider_cannot_claim_to_be_anything_else(conn):
    """§15 structurally rather than by convention: this provider makes data up, and
    no argument makes its output historical."""
    import inspect

    source = inspect.getsource(SyntheticMarketDataProvider.observe)

    assert 'origin="synthetic"' in source
    assert "origin=" not in inspect.signature(SyntheticMarketDataProvider.observe).parameters


def test_the_emitted_observation_agrees_with_the_surface_it_came_from(conn):
    entity = identifiers.ensure_security(conn, "SYN1")
    provider = SyntheticMarketDataProvider(seed=7)

    surface = provider.get_option_surface("SYN1")
    observation = provider.observe("SYN1", entity_id=entity, observed_at="2026-08-18T12:00:00+00:00")

    assert len(observation.payload["points"]) == len(surface.points)
    assert observation.payload["points"][0]["iv"] == surface.points[0].iv
