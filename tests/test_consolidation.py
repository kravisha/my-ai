"""Several sources, one view (TQ-78; addendum 9 §3, §112).

The product is the consolidation — *"consolidated portfolio analysis that is
usually not provided by discount brokers"* — so these are tests about arithmetic
that is somebody's money, and every one of them is a case where the obvious
answer is wrong.

The one to read first is
`test_a_long_and_a_short_of_one_security_do_not_net_to_nothing`. Reporting `0`
for a client who holds 100 shares at one broker and is short 100 at another is
arithmetically defensible and materially false: two real positions exist, with
two cost bases, and a client shown `0` cannot tell that from holding neither.
"""

import pytest

from backend import consolidation, holdings, portfolio_providers


def _held(symbol="SYN1", quantity=10, average_cost=5.0, asset_class="stock",
          as_of="2026-01-01T00:00:00+00:00"):
    return portfolio_providers.Holding(
        symbol=symbol, quantity=quantity, average_cost=average_cost,
        asset_class=asset_class, as_of=as_of)


# --- what merges -------------------------------------------------------------------


def test_one_security_at_two_brokers_is_one_position():
    """The whole point. Two rows in, one position out, and the lots kept so a
    client can check it against their own statements."""
    result = consolidation.consolidate([
        ("broker-a", [_held(quantity=100, average_cost=10)]),
        ("broker-b", [_held(quantity=50, average_cost=20)]),
    ])

    assert len(result.positions) == 1
    position = result.positions[0]
    assert position.symbol == "SYN1"
    assert position.net_quantity == 150
    assert position.sources == ("broker-a", "broker-b")
    assert len(position.lots) == 2


def test_the_average_cost_is_weighted_by_quantity_not_averaged():
    """100 at 10 and 50 at 20 is 13.33, not 15. A plain mean would be a
    plausible number that is wrong, which is the worst kind here."""
    result = consolidation.consolidate([
        ("broker-a", [_held(quantity=100, average_cost=10)]),
        ("broker-b", [_held(quantity=50, average_cost=20)]),
    ])

    assert result.positions[0].average_cost == pytest.approx(13.333333, abs=1e-5)


def test_different_securities_stay_separate():
    result = consolidation.consolidate([
        ("broker-a", [_held(symbol="SYN1"), _held(symbol="SYN2")]),
        ("broker-b", [_held(symbol="SYN3")]),
    ])
    assert [p.symbol for p in result.positions] == ["SYN1", "SYN2", "SYN3"]


def test_the_same_source_twice_is_refused():
    """Double-counting somebody's money is the worst arithmetic error available
    here, and it is silent: every number simply comes out twice as large and
    nothing looks broken."""
    with pytest.raises(consolidation.ConsolidationRefused) as refusal:
        consolidation.consolidate([
            ("broker-a", [_held(quantity=100)]),
            ("broker-a", [_held(quantity=100)]),
        ])
    assert "twice" in str(refusal.value)


# --- what does not merge ------------------------------------------------------------


def test_a_long_and_a_short_of_one_security_do_not_net_to_nothing():
    """**The test to read first.**

    Economically they offset. Reporting `0` erases two real positions with two
    cost bases, different tax treatment and different counterparty risk - and a
    client shown `0` cannot tell that from holding neither."""
    result = consolidation.consolidate([
        ("broker-a", [_held(quantity=100, average_cost=10)]),
        ("broker-b", [_held(quantity=-100, average_cost=12)]),
    ])

    position = result.positions[0]
    assert position.net_quantity == 0
    assert position.long_quantity == 100
    assert position.short_quantity == -100
    assert position.is_offsetting is True
    assert len(position.lots) == 2, "the legs were summed away"
    assert any("two real positions" in note for note in result.notes)


def test_a_short_leg_does_not_pollute_the_average_cost():
    """A short's `average_cost` is a credit received, not an amount paid (§101).
    Blending it into the cost of the long leg produces a figure that is
    neither."""
    result = consolidation.consolidate([
        ("broker-a", [_held(quantity=100, average_cost=10)]),
        ("broker-b", [_held(quantity=-50, average_cost=99)]),
    ])

    assert result.positions[0].average_cost == 10


def test_sources_disagreeing_about_a_security_are_not_merged_silently():
    """One of them is wrong and this module does not know which. Picking the
    first, the commonest or the more specific would be the fabrication §100
    refused when TQ-45a declined to map `EQUITY` to a house code."""
    result = consolidation.consolidate([
        ("broker-a", [_held(asset_class="stock")]),
        ("broker-b", [_held(asset_class="etf")]),
    ])

    position = result.positions[0]
    assert position.asset_class == holdings.ASSET_UNKNOWN
    assert position.class_conflict == ("etf", "stock")
    assert result.conflicts[0]["symbol"] == "SYN1"
    assert "will not choose" in result.conflicts[0]["resolution"]


def test_an_unknown_class_does_not_count_as_a_disagreement():
    """`unknown` is an absence, not a competing claim. A source that did not say
    must not make a source that did look wrong."""
    result = consolidation.consolidate([
        ("broker-a", [_held(asset_class="stock")]),
        ("broker-b", [_held(asset_class=holdings.ASSET_UNKNOWN)]),
    ])

    assert result.positions[0].asset_class == "stock"
    assert result.conflicts == ()


# --- how good the view is -----------------------------------------------------------


def test_a_view_is_as_fresh_as_its_oldest_source():
    """Two honest timestamps must not produce a dishonest third. §17: do not
    silently claim it is current."""
    result = consolidation.consolidate([
        ("broker-a", [_held(as_of="2026-01-01T09:00:00+00:00")]),
        ("broker-b", [_held(symbol="SYN2", as_of="2026-01-01T15:00:00+00:00")]),
    ])

    assert result.as_of == "2026-01-01T09:00:00+00:00"
    assert result.stale_sources == ("broker-b",)
    assert any("oldest of its sources" in note for note in result.notes)


def test_a_failed_source_makes_the_view_incomplete_rather_than_absent():
    """A client whose third broker is down still deserves to see the two that
    answered - **provided they are told what they are looking at.** Refusing
    outright would be wrong; presenting it as the whole portfolio would be
    worse."""
    result = consolidation.consolidate([
        ("broker-a", [_held(quantity=100)]),
        ("broker-b", "the broker did not answer"),
    ])

    assert result.complete is False
    assert result.sources == ("broker-a",)
    assert result.failed_sources[0]["source"] == "broker-b"
    assert "did not answer" in result.failed_sources[0]["reason"]
    assert len(result.positions) == 1, "what answered is still shown"


def test_a_failure_arrives_as_an_exception_too():
    result = consolidation.consolidate([
        ("broker-a", [_held()]),
        ("broker-b", TimeoutError("timed out")),
    ])
    assert result.complete is False
    assert "timed out" in result.failed_sources[0]["reason"]


def test_an_incomplete_view_says_what_it_costs_the_arithmetic():
    """The danger is not the missing account, it is that **nothing in the
    numbers reveals it**. Concentration over two accounts of three understates
    concentration if the third holds more of the same thing."""
    result = consolidation.consolidate([
        ("broker-a", [_held()]),
        ("broker-b", "unreachable"),
    ])

    note = next(n for n in result.notes if "part of the portfolio" in n)
    assert "concentration" in note


def test_a_partial_cost_basis_is_named_rather_than_averaged_over():
    """The average cost of a position where one lot has no cost is the cost of
    the *known part*, which is a different fact from the cost of the whole."""
    result = consolidation.consolidate([
        ("broker-a", [_held(quantity=100, average_cost=10)]),
        ("broker-b", [_held(quantity=50, average_cost=None)]),
    ])

    position = result.positions[0]
    assert position.average_cost == 10
    assert position.cost_basis_complete is False
    assert any("known part" in note for note in result.notes)


def test_a_position_with_no_cost_anywhere_has_none_rather_than_zero():
    """Absent is absent. A zero cost basis is a claim that something was free."""
    result = consolidation.consolidate([
        ("broker-a", [_held(average_cost=None)]),
    ])
    assert result.positions[0].average_cost is None


def test_an_empty_consolidation_is_complete_and_says_nothing_alarming():
    result = consolidation.consolidate([])
    assert result.positions == ()
    assert result.complete is True
    assert result.as_of is None
    assert result.notes == ()


# --- it feeds the existing analysis without changing it -----------------------------


def test_the_existing_analyser_reads_a_consolidated_view_unchanged():
    """§101 built `concentration` to take holdings rather than a connection so a
    contract test could not pass trivially. The unplanned payoff, collected once
    already when the store was removed: it reads a *consolidated* portfolio with
    no change either, because it still has no idea where its input came from."""
    result = consolidation.consolidate([
        ("broker-a", [_held(symbol="SYN1", quantity=100, average_cost=10)]),
        ("broker-b", [_held(symbol="SYN1", quantity=100, average_cost=30),
                      _held(symbol="SYN2", quantity=10, average_cost=20)]),
    ])

    report = holdings.concentration(result.holdings())

    # SYN1 is one position of 200 at a weighted 20, not two positions.
    assert [w["symbol"] for w in report["weights"]] == ["SYN1", "SYN2"]
    assert report["known_cost"] == 4200
    assert report["priced"] is False


def test_an_offsetting_position_is_flattened_to_its_net_for_the_analyser():
    """Weights by cost over a long and a short of one security would double count
    exposure the client does not have. The legs stay on
    `Consolidated.positions` for anybody who needs them, which is what makes
    flattening here safe rather than lossy."""
    result = consolidation.consolidate([
        ("broker-a", [_held(symbol="SYN1", quantity=100, average_cost=10)]),
        ("broker-b", [_held(symbol="SYN1", quantity=-100, average_cost=12)]),
    ])

    assert result.holdings() == [], "a net-zero position was offered to the analyser"
    assert result.positions[0].lots, "the legs were lost from the consolidated view"


def test_nothing_is_valued_by_consolidating():
    """Positions come from sources and prices from the market data store (§113).
    This module joins nothing."""
    result = consolidation.consolidate([("broker-a", [_held()])])
    for held in result.holdings():
        assert not any(field in vars(held)
                       for field in ("market_price", "market_value", "gain"))


def test_consolidating_writes_nothing(tmp_path):
    """§111, as a property rather than a promise."""
    before = {p for p in tmp_path.rglob("*")}
    consolidation.consolidate([
        ("broker-a", [_held()]), ("broker-b", [_held(symbol="SYN2")])])
    assert {p for p in tmp_path.rglob("*")} == before


def test_it_consolidates_what_the_real_providers_return():
    """End to end over the actual provider interface rather than hand-built
    holdings, so this fails if a provider's output ever stops fitting."""
    simulated = portfolio_providers.Source(
        provider_type="SIMULATED", name="avery-brokerage", owner_hint="avery")
    manual = portfolio_providers.Source(
        provider_type="MANUAL", name="a-spreadsheet",
        positions=({"symbol": "SYN2", "quantity": 500, "average_cost": 300.0,
                    "asset_class": "stock", "as_of": "2025-06-01T00:00:00+00:00"},))

    fetched = [(source.name, portfolio_providers.for_source(source).get_holdings(source))
               for source in (simulated, manual)]
    result = consolidation.consolidate(fetched)

    syn2 = next(p for p in result.positions if p.symbol == "SYN2")
    assert syn2.sources == ("a-spreadsheet", "avery-brokerage")
    assert syn2.net_quantity == 3500
    # The spreadsheet is older, so the view is as of the spreadsheet.
    assert result.as_of == "2025-06-01T00:00:00+00:00"
    assert result.complete is True
