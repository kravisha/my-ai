"""Tests for providers/stored_data.py - the read-side translation from the
Data Store's stored Observations back into the shapes Explorer and
Speculator's existing flows expect. Pure round-trip: store a small mission
world, read it back, and check it against the world's own answer_key rather
than against hand-picked numbers."""

from backend import fi_db
from backend import reference_data as rd
from backend.arbitrage import CostConfig, scan_chain
from providers.stored_data import StoredChainProvider, StoredPost, StoredSocialProvider, chain_snapshots
from simulation import parity_world as pw

MISSION_KWARGS = dict(run_mode="simulation", strategy="put_call_parity_arbitrage")


def _config(mission_id, seed, **overrides):
    kwargs = dict(MISSION_KWARGS)
    kwargs.update(mission_id=mission_id, seed=seed)
    kwargs.update(overrides)
    return pw.MissionConfig(**kwargs)


def _store(conn, mission_id, seed, tmp_path, **overrides):
    rd.run_reference_engine(conn)
    config = _config(mission_id, seed, **overrides)
    pw.store_world(conn, config, runs_dir=tmp_path)
    return config


# --- StoredChainProvider -----------------------------------------------------


def test_latest_chain_is_none_with_nothing_stored(conn):
    rd.run_reference_engine(conn)
    entity_id = rd.list_focus_assets(conn)[0]["entity_id"]
    assert StoredChainProvider(conn).latest_chain(entity_id) is None


def test_latest_chain_returns_the_newest_chain_for_the_entity(conn, tmp_path):
    """Two missions stored back to back for the same entity, the second's
    observed_at strictly after the first's - latest_chain must return the
    second, not the first."""
    rd.run_reference_engine(conn)
    entity_id = rd.list_focus_assets(conn)[0]["entity_id"]

    early = pw.MissionConfig(
        mission_id="m-early", run_mode="simulation", strategy="put_call_parity_arbitrage",
        seed=1, n_scenarios=1, base_time="2026-01-01T00:00:00+00:00",
    )
    late = pw.MissionConfig(
        mission_id="m-late", run_mode="simulation", strategy="put_call_parity_arbitrage",
        seed=1, n_scenarios=1, base_time="2026-02-01T00:00:00+00:00",
    )
    focus_assets = rd.list_focus_assets(conn)
    early_scenario = pw._build_scenario(early, focus_assets, 0)
    late_scenario = pw._build_scenario(late, focus_assets, 0)
    # Force both scenarios onto the same entity so latest_chain has a real
    # choice to make.
    from dataclasses import replace as _replace
    early_scenario = _replace(early_scenario, entity_id=entity_id)
    late_scenario = _replace(late_scenario, entity_id=entity_id)

    from backend import observations as observation_store
    observation_store.store(conn, pw.build_option_chain_observation(early_scenario, early))
    observation_store.store(conn, pw.build_option_chain_observation(late_scenario, late))

    latest = StoredChainProvider(conn).latest_chain(entity_id)
    assert latest.observed_at == late.base_time
    assert latest.provenance.run_id == "m-late"


def test_snapshots_reconstruct_parity_snapshots_matching_the_answer_key(conn, tmp_path):
    """The round-trip the whole module exists for: scan_chain over the
    ChainSnapshots providers/stored_data.py's `chain_snapshots` decodes from
    a stored chain must agree exactly with scan_chain over the world's own
    in-memory ChainRows (simulation/parity_world.py's `answer_key`), for
    whichever scenario actually landed in the store (see the entity-collision
    note below).

    Deviation from the pre-existing form of this test (which compared
    detect_arb001 alone on both sides): answer_key now runs scan_chain, not
    per-row detect_arb001 (this increment's own switch, SS45) - the
    reconstructed-vs-in-memory comparison is updated to the same engine on
    both sides, which is what "matching the answer key" now means."""
    config = _store(conn, "m-snapshots", seed=42, tmp_path=tmp_path, n_scenarios=6, scenario_mix={"genuine": 1.0})
    focus_assets = rd.list_focus_assets(conn)
    # Rebuild the exact worlds store_world stored: it assigns one distinct
    # focus asset per scenario (seeded sample, no replacement) so the Data
    # Store's idempotency key can never collapse two scenarios' chains -
    # rebuilding without the same assignment would compare against a world
    # that was never stored.
    import random as _random
    assignment = _random.Random(f"{config.seed}:assignment").sample(focus_assets, k=config.n_scenarios)
    scenarios = {
        s.scenario_id: s
        for s in (
            pw._build_scenario(config, focus_assets, i, forced_asset=assignment[i])
            for i in range(config.n_scenarios)
        )
    }

    provider = StoredChainProvider(conn)
    checked_any = False
    for entity_id in {s.entity_id for s in scenarios.values()}:
        observation = provider.latest_chain(entity_id)
        assert observation is not None
        scenario = scenarios[observation.provenance.scenario_id]

        got = [
            (r.detector_id, r.direction, round(r.net_edge_per_share, 6))
            for chain in chain_snapshots(observation)
            for r in scan_chain(chain, CostConfig(), stale_tolerance_seconds=config.stale_tolerance_seconds)
        ]
        expected = [
            (r.detector_id, r.direction, round(r.net_edge_per_share, 6))
            for r in pw.answer_key(scenario, config)
        ]
        assert got == expected
        checked_any = True
    assert checked_any


# --- StoredSocialProvider -----------------------------------------------------


def test_fetch_recent_is_empty_with_nothing_stored(conn):
    rd.run_reference_engine(conn)
    entity_id = rd.list_focus_assets(conn)[0]["entity_id"]
    assert StoredSocialProvider(conn).fetch_recent(entity_id) == []


def test_fetch_recent_returns_mission_chatter_oldest_first_with_a_working_cursor(conn, tmp_path):
    config = _store(conn, "m-chatter", seed=5, tmp_path=tmp_path, n_scenarios=4, scenario_mix={"genuine": 1.0})
    focus_assets = rd.list_focus_assets(conn)
    scenarios = [pw._build_scenario(config, focus_assets, i) for i in range(config.n_scenarios)]

    social = StoredSocialProvider(conn)
    checked_any = False
    for entity_id in {s.entity_id for s in scenarios}:
        posts = social.fetch_recent(entity_id)
        if not posts:
            continue
        checked_any = True
        assert all(isinstance(p, StoredPost) for p in posts)
        assert [p.posted_at for p in posts] == sorted(p.posted_at for p in posts)

        # A second call with since=the last post's timestamp returns nothing -
        # the cursor semantics agents/speculator.py's flow relies on.
        again = social.fetch_recent(entity_id, since=posts[-1].posted_at)
        assert again == []

        # A cursor at the first post excludes it but keeps the rest.
        if len(posts) > 1:
            partial = social.fetch_recent(entity_id, since=posts[0].posted_at)
            assert partial == posts[1:]
    assert checked_any


def test_stored_post_satisfies_the_attribute_interface_speculator_needs():
    """agents/speculator.py's `seen` window is read via .engagement_score,
    .text, .author, .posted_at (_source_dispersion/_read_stance/the
    cross-check answer path) - a StoredPost must carry exactly those."""
    post = StoredPost(source="mission_chatter", author="user1000", posted_at="2026-01-01T00:00:00+00:00",
                       text="chatter", engagement_score=0.5)
    assert post.source == "mission_chatter"
    assert post.author == "user1000"
    assert post.posted_at == "2026-01-01T00:00:00+00:00"
    assert post.text == "chatter"
    assert post.engagement_score == 0.5
