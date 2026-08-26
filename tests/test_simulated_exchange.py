"""The simulated exchange and the simulated client session (TQ-77; §114, §115).

Two substitutions, both at the boundary and neither inside the agent: a
simulated client asks, and a simulated exchange answers.

The property everything else rests on is
`test_no_agent_can_tell_it_is_in_a_simulation`. §115 corrected an earlier
framing that treated "training must match production" as a discipline to
maintain; it is structural. The analyst has one code path, and if any agent ever
reads a simulation flag that stops being true — quietly, and in the direction of
habits formed in training that are wrong in production.

The one to read second is `test_a_quietly_partial_broker_is_caught`. Unreachable
and malformed announce themselves. A broker that returns three of five positions
produces a consolidation that is wrong and looks right, and the only thing
between that and a client is whether anybody noticed the account did not add up.
"""

import ast
import json
from pathlib import Path

import pytest

from agents import portfolio_analyst
from backend import analysis_requests, portfolio_providers, portfolios
from simulation import client_sessions, exchange

ROOT = Path(__file__).resolve().parent.parent


def _source(name, owner_hint=None):
    return {"provider_type": exchange.PROVIDER_TYPE, "name": name,
            "owner_hint": owner_hint or name}


def _as_source(descriptor):
    return portfolio_providers.Source(**descriptor)


# --- the exchange answers, and sometimes badly --------------------------------------


def test_a_healthy_exchange_returns_the_account():
    world = exchange.SimulatedExchange()
    source = _as_source(_source("avery"))

    held = world.get_holdings(source)

    assert [h.symbol for h in held] == ["SYN2", "SYN5", "SYN2C350", "SYN2P300"]
    assert all(h.simulated for h in held)


def test_an_unreachable_exchange_refuses_rather_than_returning_nothing():
    """Empty is not the same as unreachable, and a client cannot tell them apart
    from an empty list."""
    world = exchange.SimulatedExchange.from_scenario(
        [{"source": "avery", "behaviour": exchange.BEHAVIOUR_UNREACHABLE}])

    with pytest.raises(portfolio_providers.ProviderRefused):
        world.get_holdings(_as_source(_source("avery")))


def test_a_partial_exchange_returns_part_of_the_account_without_saying_so():
    """**The fault worth having.** It does not announce itself: what comes back
    is a well-formed answer that is missing positions."""
    world = exchange.SimulatedExchange.from_scenario(
        [{"source": "avery", "behaviour": exchange.BEHAVIOUR_PARTIAL, "returns": 2}])

    held = world.get_holdings(_as_source(_source("avery")))

    assert len(held) == 2
    assert len(world.truth_for(_as_source(_source("avery")))) == 4


def test_a_malformed_answer_is_caught_by_the_canonical_shape():
    """The exchange returns something that is not a position; `Holding.from_row`
    is what has to refuse it, and asserting that here is why the behaviour
    exists."""
    world = exchange.SimulatedExchange.from_scenario(
        [{"source": "avery", "behaviour": exchange.BEHAVIOUR_MALFORMED}])

    from backend import holdings

    with pytest.raises(holdings.HoldingRefused):
        world.get_holdings(_as_source(_source("avery")))


def test_a_slow_exchange_still_answers():
    world = exchange.SimulatedExchange.from_scenario(
        [{"source": "avery", "behaviour": exchange.BEHAVIOUR_SLOW, "slow_seconds": 0.01}])
    assert world.get_holdings(_as_source(_source("avery")))


def test_an_unknown_behaviour_is_refused_when_the_scenario_loads():
    """A scenario asking for something this build cannot produce should fail when
    it is loaded, not halfway through an exercise."""
    with pytest.raises(exchange.ExchangeError):
        exchange.SimulatedExchange.from_scenario(
            [{"source": "avery", "behaviour": "returns_yesterdays_prices"}])


def test_faults_are_declared_rather_than_random():
    """Two runs of one exercise must produce the same answer, or a curriculum
    cannot grade it and a regression cannot be reproduced."""
    world = exchange.SimulatedExchange.from_scenario(
        [{"source": "avery", "behaviour": exchange.BEHAVIOUR_PARTIAL, "returns": 1}])
    source = _as_source(_source("avery"))

    assert [vars(h) for h in world.get_holdings(source)] == \
           [vars(h) for h in world.get_holdings(source)]


def test_health_reports_declared_faults_without_triggering_them():
    """Asking whether an exchange is up must not itself be the call that fails."""
    world = exchange.SimulatedExchange.from_scenario(
        [{"source": "avery", "behaviour": exchange.BEHAVIOUR_UNREACHABLE}])

    report = world.health_check()

    assert report["healthy"] is False
    assert report["faults"] == {"avery": exchange.BEHAVIOUR_UNREACHABLE}
    # And the fault did not fire.
    assert world.get_holdings(_as_source(_source("morgan")))


def test_nothing_the_exchange_returns_is_priced():
    """§6.2's mechanism is not a label somebody remembered: a SIMULATED source is
    not LIVE."""
    world = exchange.SimulatedExchange()
    source = _as_source(_source("morgan"))

    assert world.get_account(source)["priced"] is False
    assert world.get_balances(source)["priced"] is False
    assert portfolios.is_priced({"data_mode": source.data_mode}) is False


def test_the_ground_truth_is_not_reachable_through_the_provider_interface():
    """An analyst that could ask an exchange what it *really* holds would be one
    that never has to notice a partial answer."""
    for method in portfolio_providers.PortfolioProvider.__annotations__:
        assert method != "truth_for"
    assert "truth_for" not in dir(portfolio_providers.SimulatedPortfolioProvider)


# --- the agent cannot tell -----------------------------------------------------------


def test_no_agent_can_tell_it_is_in_a_simulation():
    """**The property TQ-77 exists to guarantee**, and §115's correction made
    structural.

    An agent that can branch on the mode is an agent whose training and
    production behaviour can diverge — and it would diverge silently, in the
    direction of habits rewarded in training that are wrong in production.

    Scanned over the import graph and the environment, because those are the two
    ways a mode reaches a process. `simulation/harness.py` chooses the
    environment a run comes up in; what it must never do is hand an agent a
    switch."""
    offenders = []
    for path in sorted((ROOT / "agents").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [alias.name for alias in node.names]
                module = getattr(node, "module", "") or ""
                if module.startswith("simulation") or any(
                        n.startswith("simulation") for n in names):
                    offenders.append(f"{path.name}: imports {module or names}")
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in ("simulation", "SIMULATION_MODE", "FI_SIMULATION",
                                  "run_mode"):
                    offenders.append(f"{path.name}: names {node.value!r}")

    assert not offenders, (
        "these let an agent know it is in a simulation:\n  " + "\n  ".join(offenders)
        + "\nThe substitution is at the boundary. An agent has one code path, and what "
          "changes between training and production is what answers its call."
    )


def test_the_exchange_is_reached_through_the_ordinary_provider_lookup():
    """No special case in the analyst: it fetches from whatever the request names,
    and `for_source` finds the provider."""
    source = _as_source(_source("avery"))
    assert portfolio_providers.for_source(source).provider_type == exchange.PROVIDER_TYPE


# --- a whole simulated session -------------------------------------------------------


def _client(conn, name="avery", sources=None, world=None):
    world = world or exchange.SimulatedExchange()
    descriptors = sources if sources is not None else [_source(name)]
    truth = {}
    for descriptor in descriptors:
        try:
            truth[descriptor["name"]] = world.truth_for(_as_source(descriptor))
        except Exception:  # noqa: BLE001 - a source with no fixture has nothing
            truth[descriptor["name"]] = []
    return client_sessions.SimulatedClient(
        client_id=name, session_id=f"sess-{name}", sources=descriptors, truth=truth)


def test_a_satisfied_client_asks_gets_an_answer_and_leaves(conn):
    client = _client(conn)

    verdict = client_sessions.run_session(
        conn, client, lambda c: portfolio_analyst._analyst_work(c, "analyst-1"))

    assert verdict["verdict"] == client_sessions.VERDICT_SATISFIED
    assert verdict["complaints"] == []


def test_the_session_leaves_nothing_behind(conn):
    """§115: *"after that all client data is discarded"*. The disconnect is part
    of the client rather than something the harness remembers."""
    client = _client(conn)

    client_sessions.run_session(conn, client, lambda c: portfolio_analyst._analyst_work(c, "analyst-1"))

    assert analysis_requests.outstanding(conn)["clean"] is True
    assert conn.fetchone(
        "SELECT COUNT(*) AS n FROM portfolio_analysis_requests")["n"] == 0


def test_the_session_discards_even_when_the_exercise_fails(conn):
    """A failed exercise that left a client's report on disk would be the worst
    possible outcome of a test written to prove that does not happen."""
    client = _client(conn)

    def explode(_conn):
        raise RuntimeError("the analyst fell over")

    with pytest.raises(RuntimeError):
        client_sessions.run_session(conn, client, explode)

    assert conn.fetchone(
        "SELECT COUNT(*) AS n FROM portfolio_analysis_requests")["n"] == 0


def test_a_client_notices_an_account_that_silently_vanished(conn):
    """The failure that looks like success."""
    client = _client(conn, sources=[_source("avery"), _source("morgan")])
    verdict = client.judge({"status": analysis_requests.STATUS_READY, "result": {
        "sources": ["avery"], "failed_sources": [], "complete": True,
        "positions": [{"symbol": h.symbol} for h in client.truth["avery"]],
        "analysis": {"priced": False}}})

    assert verdict["verdict"] == client_sessions.VERDICT_DISAPPOINTED
    assert verdict["complaints"][0]["code"] == "account_vanished"


def test_a_client_accepts_a_partial_answer_that_says_it_is_partial(conn):
    """A partial answer is fine. A partial answer presented as complete is
    not."""
    client = _client(conn, sources=[_source("avery"), _source("morgan")])
    verdict = client.judge({"status": analysis_requests.STATUS_READY, "result": {
        "sources": ["avery"], "failed_sources": [{"source": "morgan", "reason": "down"}],
        "complete": False,
        "positions": [{"symbol": h.symbol} for h in client.truth["avery"]],
        "analysis": {"priced": False}}})

    assert verdict["verdict"] == client_sessions.VERDICT_SATISFIED


def test_a_client_is_disappointed_by_a_partial_answer_presented_as_complete(conn):
    client = _client(conn, sources=[_source("avery"), _source("morgan")])
    verdict = client.judge({"status": analysis_requests.STATUS_READY, "result": {
        "sources": ["avery"], "failed_sources": [{"source": "morgan", "reason": "down"}],
        "complete": True,
        "positions": [{"symbol": h.symbol} for h in client.truth["avery"]],
        "analysis": {"priced": False}}})

    codes = {complaint["code"] for complaint in verdict["complaints"]}
    assert "partial_presented_as_complete" in codes


def test_a_quietly_partial_broker_is_caught(conn):
    """**The one to read second.**

    The exchange returns two of avery's four positions and says nothing. The
    report is well-formed, `complete` is True because no source *failed*, and
    every number in it is wrong. The client notices because they know what they
    hold - which is the whole reason a simulated client can grade and a real one
    cannot."""
    world = exchange.SimulatedExchange.from_scenario(
        [{"source": "avery", "behaviour": exchange.BEHAVIOUR_PARTIAL, "returns": 2}])
    client = _client(conn, world=world)

    report = {
        "sources": ["avery"], "failed_sources": [], "complete": True,
        "positions": [{"symbol": h.symbol}
                      for h in world.get_holdings(_as_source(_source("avery")))],
        "analysis": {"priced": False},
    }
    verdict = client.judge({"status": analysis_requests.STATUS_READY, "result": report})

    codes = {complaint["code"] for complaint in verdict["complaints"]}
    assert "positions_missing" in codes
    assert any("looks right" in complaint["rule"]
               for complaint in verdict["complaints"])


def test_a_client_notices_a_position_it_does_not_hold(conn):
    client = _client(conn)
    verdict = client.judge({"status": analysis_requests.STATUS_READY, "result": {
        "sources": ["avery"], "failed_sources": [], "complete": True,
        "positions": [{"symbol": h.symbol} for h in client.truth["avery"]]
                     + [{"symbol": "NOTMINE"}],
        "analysis": {"priced": False}}})

    codes = {complaint["code"] for complaint in verdict["complaints"]}
    assert "positions_invented" in codes


def test_a_client_notices_a_valuation_nobody_can_make(conn):
    """§101/§113: a simulated price on real positions is synthetic output
    presented as somebody's money."""
    client = _client(conn)
    verdict = client.judge({"status": analysis_requests.STATUS_READY, "result": {
        "sources": ["avery"], "failed_sources": [], "complete": True,
        "positions": [{"symbol": h.symbol} for h in client.truth["avery"]],
        "analysis": {"priced": True}}})

    codes = {complaint["code"] for complaint in verdict["complaints"]}
    assert "priced_without_prices" in codes


def test_a_client_who_never_got_an_answer_says_so(conn):
    client = _client(conn)
    assert client.judge(None)["complaints"][0]["code"] == "no_answer"


def test_every_complaint_names_the_rule_it_is_about(conn):
    """*"Disappointed, 0.4"* tells a curriculum nothing it can train against. A
    complaint that names its rule is a behaviour TQ-76 can grade."""
    client = _client(conn, sources=[_source("avery"), _source("morgan")])
    verdict = client.judge({"status": analysis_requests.STATUS_READY, "result": {
        "sources": [], "failed_sources": [], "complete": True,
        "positions": [{"symbol": "NOTMINE"}], "analysis": {"priced": True}}})

    assert len(verdict["complaints"]) >= 3
    for complaint in verdict["complaints"]:
        assert complaint["rule"] and complaint["detail"]
        assert complaint["code"]


def test_a_verdict_carries_no_positions(conn):
    """The verdict travels to a curriculum. It must be a grade, not a copy of
    somebody's portfolio."""
    client = _client(conn)
    verdict = client_sessions.run_session(conn, client, lambda c: portfolio_analyst._analyst_work(c, "analyst-1"))

    dumped = json.dumps(verdict)
    for symbol in ("SYN2", "SYN5", "SYN2C350"):
        assert symbol not in dumped
