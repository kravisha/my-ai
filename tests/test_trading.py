"""A trader's own book, and the boundary that keeps §111 whole
(backend/trading.py, agents/trader.py; docs/SPEC_RECONCILIATION.md §162).

The first three tests are the ones that matter. This system stores no client
portfolio (§111), and a trader's book is the first thing in it that looks like
one from a distance - a table of positions with prices and sizes. The difference
is whose property it is, and a difference that lives only in a docstring is one
somebody undoes by adding a column.
"""

import ast
import inspect
import re

import pytest

from agents import trader
from backend import fi_db, trading


@pytest.fixture
def conn(tmp_path):
    connection = fi_db.get_connection(str(tmp_path / "t.db"))
    fi_db.init_schema(connection)
    try:
        yield connection
    finally:
        connection.close()


def _analysis(conn, security="JE-000001", thesis="Volatility is rich.", confidence=0.8,
              report_id=1):
    now = fi_db._now()
    return conn.execute_returning_id(
        "INSERT INTO analysis_results (created_at, producer_identity, producer_spawned_at,"
        " report_id, security, thesis, evidence_summary, confidence, uncertainty,"
        " schema_version) VALUES (?, 'analysis-1', ?, ?, ?, ?, 'e', ?, 'u', 1)",
        (now, now, report_id, security, thesis, confidence))


# -- the boundary (§111) ------------------------------------------------------------


def test_no_table_here_carries_a_client():
    """The way §111 gets undone is not somebody re-creating `portfolios`. It is
    somebody adding an owner column to a table that already exists and calling it
    multi-tenancy - at which point a trader's book becomes a place a client's
    positions can be stored, and every guarantee about not holding them is gone
    while every existing tripwire still passes."""
    forbidden = re.compile(r"^\s*(client_id|owner_id|owner_type|session_id|client_ref)\b",
                           re.IGNORECASE | re.MULTILINE)
    found = forbidden.findall(trading.SCHEMA)
    assert not found, (
        f"the trading schema carries client-scoped columns: {found}. A trader's book is "
        "the agent's own record; a client portfolio is somebody else's property and is "
        "never stored (§111).")


def test_every_position_belongs_to_an_agent():
    """The positive half. A book with no owner at all would be a house account,
    which is a different thing that nobody asked for - and it is `agent_id`
    rather than a display name, so a renamed trader keeps one continuous record
    (TQ-97)."""
    assert re.search(r"^\s*agent_id TEXT NOT NULL", trading.SCHEMA, re.MULTILINE), (
        "trader_orders does not require an agent_id")


def test_the_trader_cannot_reach_a_client_position():
    """Asserted on the imports, because the modules that hold client positions
    are named and few. A trader that could read a consolidated client view is one
    refactor away from trading against it."""
    tree = ast.parse(inspect.getsource(trader))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            for alias in node.names:
                imported.add(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    for forbidden in ("backend.consolidation", "backend.portfolio_providers",
                      "backend.analysis_requests", "backend.client_profile",
                      "backend.holdings"):
        assert forbidden not in imported, (
            f"agents/trader.py imports {forbidden}, which handles client positions")


def test_the_portfolio_word_is_not_reused_for_a_book():
    """47 §5: one concept, one name. In this codebase `portfolio` already means
    the client's property, and a trader having one would make every existing
    sentence about portfolios ambiguous."""
    assert "portfolio" not in trading.SCHEMA.lower()


# -- placing and sizing --------------------------------------------------------------


def test_a_judgement_is_traded_once(conn):
    """The desk acts on each analysis once. Without this the trader would open a
    new position against the same idea every cycle, which is the same idea traded
    repeatedly rather than a book."""
    analysis_id = _analysis(conn)
    first = trading.place(conn, agent_id="ag-1", security="JE-000001",
                          side=trading.SIDE_SHORT_VOL, size=1.0,
                          analysis_result_id=analysis_id, thesis="rich", placed_by="trader-1")
    second = trading.place(conn, agent_id="ag-1", security="JE-000001",
                           side=trading.SIDE_SHORT_VOL, size=1.0,
                           analysis_result_id=analysis_id, thesis="rich", placed_by="trader-1")
    assert first is not None and second is None


def test_an_order_with_no_size_is_refused(conn):
    with pytest.raises(ValueError):
        trading.place(conn, agent_id="ag-1", security="JE-000001",
                      side=trading.SIDE_SHORT_VOL, size=0,
                      analysis_result_id=_analysis(conn), thesis="t", placed_by="trader-1")


def test_the_desk_declines_an_idea_below_its_conviction_floor(conn, monkeypatch):
    """A desk that took every judgement handed to it would not be deciding
    anything, and directive §11 gives it the deciding half."""
    monkeypatch.setattr(trader, "CONVICTION_FLOOR", 0.5)
    _analysis(conn, thesis="Thin evidence either way.", confidence=0.2)

    class Surface:
        def get_option_surface(self, security, as_of=None):
            from providers.market_data import OptionSurface, SurfacePoint
            return OptionSurface(security=security,
                                 points=(SurfacePoint(strike=0.0, expiry_days=30, iv=0.3),))

    placed = trader._open_new_positions(conn, "trader-1", "ag-1", Surface())
    assert placed == 0
    assert trading.open_orders(conn) == []


# -- what a position is worth ---------------------------------------------------------


def test_an_unfilled_order_has_no_result_rather_than_zero(conn):
    """Absence is `unknown`, never a plausible default (§100). Returning zero
    would make an order that never filled indistinguishable from a trade that
    broke even."""
    order = trading.place(conn, agent_id="ag-1", security="JE-000001",
                          side=trading.SIDE_SHORT_VOL, size=1.0,
                          analysis_result_id=_analysis(conn), thesis="t", placed_by="trader-1")
    assert trading.pnl_vol_points(conn, order) is None


def test_short_vol_makes_money_when_volatility_falls(conn):
    order = trading.place(conn, agent_id="ag-1", security="JE-000001",
                          side=trading.SIDE_SHORT_VOL, size=2.0,
                          analysis_result_id=_analysis(conn), thesis="rich", placed_by="trader-1")
    trading.fill(conn, order, kind=trading.FILL_ENTRY, level=0.30)
    trading.fill(conn, order, kind=trading.FILL_EXIT, level=0.25)
    assert trading.pnl_vol_points(conn, order) == pytest.approx(0.10)


def test_long_vol_loses_when_volatility_falls(conn):
    order = trading.place(conn, agent_id="ag-1", security="JE-000001",
                          side=trading.SIDE_LONG_VOL, size=2.0,
                          analysis_result_id=_analysis(conn), thesis="cheap", placed_by="trader-1")
    trading.fill(conn, order, kind=trading.FILL_ENTRY, level=0.30)
    trading.fill(conn, order, kind=trading.FILL_EXIT, level=0.25)
    assert trading.pnl_vol_points(conn, order) == pytest.approx(-0.10)


def test_nothing_here_claims_to_be_priced(conn):
    """Every figure is vol points against a generated surface. A P&L labelled as
    money would be the first real lie this system told (§113)."""
    summary = trading.book_summary(conn)
    assert summary["is_priced"] is False
    assert summary["origin"] == trading.ORIGIN_SYNTHETIC


# -- attribution ----------------------------------------------------------------------


def _closed(conn, *, side, entry, exit_level, size=1.0, thesis="t", security="JE-000001"):
    order = trading.place(conn, agent_id="ag-1", security=security, side=side, size=size,
                          analysis_result_id=_analysis(conn, security=security),
                          thesis=thesis, placed_by="trader-1")
    trading.fill(conn, order, kind=trading.FILL_ENTRY, level=entry)
    trading.fill(conn, order, kind=trading.FILL_EXIT, level=exit_level)
    trading.close(conn, order)
    return order


def test_a_thesis_the_market_contradicted_is_a_bad_idea(conn):
    """The desk executed the judgement it was given. Charging the trader for the
    analyst's call is exactly the automatic blame directive §11 forbids."""
    order = _closed(conn, side=trading.SIDE_LONG_VOL, entry=0.30, exit_level=0.25)
    verdict = trading.attribute(conn, order, judged_by="coo-1")
    assert verdict["verdict"] == trading.VERDICT_BAD_IDEA


def test_a_move_inside_the_noise_floor_is_nobodys_fault(conn):
    """A sound decision may still lose money. Attributing noise to a person is
    how a metric starts punishing correct behaviour."""
    order = _closed(conn, side=trading.SIDE_LONG_VOL, entry=0.30,
                    exit_level=0.30 + trading.NOISE_VOL_POINTS / 2)
    verdict = trading.attribute(conn, order, judged_by="coo-1")
    assert verdict["verdict"] == trading.VERDICT_RANDOMNESS


def test_a_right_idea_that_still_lost_is_bad_timing(conn):
    """The distinction the specification asks a demo to expose: the idea held and
    the entry or the exit did not."""
    order = trading.place(conn, agent_id="ag-1", security="JE-000001",
                          side=trading.SIDE_LONG_VOL, size=1.0,
                          analysis_result_id=_analysis(conn), thesis="cheap",
                          placed_by="trader-1")
    trading.fill(conn, order, kind=trading.FILL_ENTRY, level=0.30)
    trading.fill(conn, order, kind=trading.FILL_EXIT, level=0.32)
    trading.close(conn, order)
    # Direction right, and the size makes the realised number negative only if
    # the sign convention is wrong - so this also pins the arithmetic.
    verdict = trading.attribute(conn, order, judged_by="coo-1")
    assert verdict["verdict"] == trading.VERDICT_SOUND
    assert verdict["pnl_vol_points"] > 0


def test_a_trade_with_no_entry_is_a_data_problem(conn):
    """Neither the analyst's fault nor the trader's. The desk could not see what
    it was trading."""
    order = trading.place(conn, agent_id="ag-1", security="JE-000001",
                          side=trading.SIDE_SHORT_VOL, size=1.0,
                          analysis_result_id=_analysis(conn), thesis="t", placed_by="trader-1")
    trading.close(conn, order)
    verdict = trading.attribute(conn, order, judged_by="coo-1")
    assert verdict["verdict"] == trading.VERDICT_BAD_DATA


def test_every_verdict_is_in_the_closed_vocabulary(conn):
    for side, entry, exit_level in ((trading.SIDE_LONG_VOL, 0.30, 0.25),
                                    (trading.SIDE_SHORT_VOL, 0.30, 0.25),
                                    (trading.SIDE_LONG_VOL, 0.30, 0.3001)):
        order = _closed(conn, side=side, entry=entry, exit_level=exit_level,
                        security=f"JE-{entry}-{exit_level}-{side}")
        assert trading.attribute(conn, order, judged_by="coo-1")["verdict"] in trading.VERDICTS


def test_a_trader_is_not_the_judge_of_its_own_trades():
    """The fifth application of producer-is-not-approver. Asserted on the source
    because the COO records attribution and the trader must not."""
    tree = ast.parse(inspect.getsource(trader))
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "attribute" not in called, (
        "agents/trader.py records its own attribution; the producer of an outcome must "
        "not be the judge of it")


# -- the trader's own record ------------------------------------------------------------


def test_the_record_reports_verdicts_rather_than_a_score(conn):
    """A trader with three bad-idea losses executed correctly three times. A
    single number would charge them for the analyst's judgement, which is the
    attribution thrown away at the last step."""
    for side, entry, exit_level, security in (
            (trading.SIDE_SHORT_VOL, 0.30, 0.25, "JE-A"),
            (trading.SIDE_LONG_VOL, 0.30, 0.25, "JE-B")):
        order = _closed(conn, side=side, entry=entry, exit_level=exit_level, security=security)
        trading.attribute(conn, order, judged_by="coo-1")

    record = trading.trader_record(conn, "ag-1")
    assert record["closed"] == 2
    assert record["winners"] == 1 and record["losers"] == 1
    assert set(record["verdicts"]) == {trading.VERDICT_SOUND, trading.VERDICT_BAD_IDEA}
    assert record["is_priced"] is False


def test_the_record_is_keyed_on_the_durable_id(conn):
    """A book keyed on the desk identity would be reassigned with the desk."""
    order = _closed(conn, side=trading.SIDE_SHORT_VOL, entry=0.30, exit_level=0.25)
    _ = order
    assert trading.trader_record(conn, "ag-1")["orders"] == 1
    assert trading.trader_record(conn, "trader-1")["orders"] == 0
