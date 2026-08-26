"""The Portfolio Analyst, and the transport that tasks it (TQ-79; addendum 9 §2,
§111, §115).

Two things are being tested and they pull in opposite directions, which is the
whole reason this increment was interesting:

**It has to work.** A client names several sources, the analyst fetches them,
consolidates, analyses, and a report comes back — including when one source is
down, because a client with three brokers and one outage is entitled to the two
that answered.

**It has to keep nothing.** Agents here talk through the database, and this one
handles client portfolios. The resolution is that a row is a *message*: deleted
on collection, on disconnect, and on expiry. The tests that matter assert that as
a property of the schema and the filesystem rather than by reading the code.

The one to read first is `test_a_collected_report_is_gone`. Delete-on-read is
what makes this a transport rather than a store, and it is the assertion that
fails the day somebody adds a convenient `get_report` that does not delete.
"""

import json

import pytest

from agents import portfolio_analyst
from backend import analysis_requests, portfolios


def _sources(*names, provider_type="SIMULATED"):
    return [{"provider_type": provider_type, "name": name, "owner_hint": name}
            for name in names]


def _submit(conn, session="sess-1", client="avery", sources=None,
            requested=portfolio_analyst.ANALYSIS_CONCENTRATION, **kwargs):
    return analysis_requests.submit(
        conn, session_id=session, owner=portfolios.for_client(client),
        sources=sources if sources is not None else _sources("avery"),
        requested=requested, **kwargs)


# --- the analyst does the work ------------------------------------------------------


def test_it_consolidates_several_sources_into_one_report():
    """The product (§112): several sources, one view. `avery` holds SYN2 at the
    simulated broker; the spreadsheet holds more of the same security."""
    report = portfolio_analyst.analyse({
        "requested": portfolio_analyst.ANALYSIS_CONCENTRATION,
        "sources": [
            {"provider_type": "SIMULATED", "name": "brokerage", "owner_hint": "avery"},
            {"provider_type": "MANUAL", "name": "spreadsheet",
             "positions": ({"symbol": "SYN2", "quantity": 500, "average_cost": 300.0,
                            "asset_class": "stock",
                            "as_of": "2025-06-01T00:00:00+00:00"},)},
        ],
    })

    syn2 = next(p for p in report["positions"] if p["symbol"] == "SYN2")
    assert syn2["sources"] == ["brokerage", "spreadsheet"]
    assert syn2["net_quantity"] == 3500
    assert report["complete"] is True
    assert report["analysis"]["priced"] is False


def test_one_unreachable_source_does_not_cost_the_others():
    """A client with three brokers and one outage is entitled to the two that
    answered — **provided they are told what they are looking at.** Refusing the
    whole analysis would be the kind of correctness that is useless to the person
    asking."""
    report = portfolio_analyst.analyse({
        "requested": portfolio_analyst.ANALYSIS_CONCENTRATION,
        "sources": [
            {"provider_type": "SIMULATED", "name": "brokerage", "owner_hint": "avery"},
            {"provider_type": "SCHWAB", "name": "the-one-that-is-down"},
        ],
    })

    assert report["positions"], "the source that answered was thrown away"
    assert report["complete"] is False
    assert report["failed_sources"][0]["source"] == "the-one-that-is-down"
    assert report["analysis"]["partial"] is True, (
        "a caller reading only the analysis could not tell it was partial")


def test_a_malformed_source_fails_only_itself():
    report = portfolio_analyst.analyse({
        "requested": portfolio_analyst.ANALYSIS_CONCENTRATION,
        "sources": [
            {"provider_type": "SIMULATED", "name": "brokerage", "owner_hint": "avery"},
            {"provider_type": "SIMULATED"},  # no name
        ],
    })
    assert report["complete"] is False
    assert report["positions"]


def test_an_analysis_it_cannot_perform_is_refused_rather_than_substituted():
    """Fail closed. Quietly running a concentration report because somebody asked
    for a stress test would answer a question nobody asked."""
    with pytest.raises(portfolio_analyst.AnalysisRefused) as refusal:
        portfolio_analyst.analyse({"requested": "stress_test", "sources": _sources("avery")})
    assert "stress_test" in str(refusal.value)


def test_a_report_carries_no_price():
    """Positions come from sources, prices from the market data store (§113).
    This agent joins nothing.

    Asserted over the report's **fields** rather than its text, which is a
    correction worth keeping: the first version searched the serialised JSON for
    "gain" and failed on the sentence *"current value, gain and loss need a
    market price, which this report does not use"* — the note doing exactly its
    job. A crude scan can fail on the disclosure of the thing it is looking
    for."""
    report = portfolio_analyst.analyse({
        "requested": portfolio_analyst.ANALYSIS_CONCENTRATION,
        "sources": _sources("morgan")})

    priced_fields = ("market_price", "market_value", "gain", "pnl", "unrealized")
    for position in report["positions"]:
        assert not any(field in position for field in priced_fields)
    for weight in report["analysis"]["weights"]:
        assert not any(field in weight for field in priced_fields)
    assert report["analysis"]["priced"] is False
    # And the absence is stated rather than left to be noticed.
    assert "market price" in report["analysis"]["priced_note"]


# --- the transport is a transport ---------------------------------------------------


def test_a_collected_report_is_gone(conn):
    """**Delete-on-read is what makes this a transport rather than a store.**

    A client who needs the report twice should be given it twice by whatever held
    it — not by this system keeping a copy of their portfolio."""
    request_id = _submit(conn)
    analysis_requests.deliver(conn, request_id, {"analysis": {"positions": 4}})

    first = analysis_requests.collect(conn, session_id="sess-1", request_id=request_id)
    second = analysis_requests.collect(conn, session_id="sess-1", request_id=request_id)

    assert first["result"]["analysis"]["positions"] == 4
    assert second is None, "the report was still there after being collected"
    assert conn.fetchone(
        "SELECT COUNT(*) AS n FROM portfolio_analysis_requests")["n"] == 0


def test_a_disconnect_discards_everything_the_session_left(conn):
    """§115: *"after that all client data is discarded by the system"*. Whatever
    its status — a request still being worked on is still this client's data."""
    pending = _submit(conn, session="sess-1")
    ready = _submit(conn, session="sess-1")
    other = _submit(conn, session="sess-2")
    analysis_requests.deliver(conn, ready, {"analysis": {}})

    removed = analysis_requests.discard_session(conn, "sess-1")

    assert removed == 2
    assert analysis_requests.collect(
        conn, session_id="sess-1", request_id=pending) is None
    assert conn.fetchone(
        "SELECT COUNT(*) AS n FROM portfolio_analysis_requests")["n"] == 1
    assert analysis_requests.collect(conn, session_id="sess-2", request_id=other)


def test_expiry_is_enforced_on_read_not_only_by_a_sweeper(conn):
    """`gateway/store.session_is_valid`'s rule, and the stakes are higher here: a
    sweeper that stopped running would leave a client's report on disk
    indefinitely, which is the one thing §111 forbids outright."""
    request_id = _submit(conn, ttl_seconds=-1)
    analysis_requests.deliver(conn, request_id, {"analysis": {}})

    assert analysis_requests.collect(
        conn, session_id="sess-1", request_id=request_id) is None
    assert conn.fetchone(
        "SELECT COUNT(*) AS n FROM portfolio_analysis_requests")["n"] == 0


def test_a_request_id_alone_does_not_reach_a_report(conn):
    """Scoped by session as well as by id - the same reasoning that makes an
    owner context required rather than an id."""
    request_id = _submit(conn, session="sess-1")
    analysis_requests.deliver(conn, request_id, {"analysis": {}})

    assert analysis_requests.collect(
        conn, session_id="somebody-elses-session", request_id=request_id) is None
    # And it is still there for the session that owns it.
    assert analysis_requests.collect(
        conn, session_id="sess-1", request_id=request_id)["result"]


def test_a_request_still_being_worked_on_reports_its_status(conn):
    """Nothing is invented for a caller who asks early."""
    request_id = _submit(conn)
    answer = analysis_requests.collect(conn, session_id="sess-1", request_id=request_id)

    assert answer["status"] == analysis_requests.STATUS_PENDING
    assert answer["result"] is None
    assert conn.fetchone(
        "SELECT COUNT(*) AS n FROM portfolio_analysis_requests")["n"] == 1


def test_a_request_needs_a_session_and_a_source(conn):
    owner = portfolios.for_client("avery")
    with pytest.raises(analysis_requests.RequestRefused):
        analysis_requests.submit(conn, session_id="", owner=owner,
                                 sources=_sources("avery"), requested="concentration")
    with pytest.raises(analysis_requests.RequestRefused):
        analysis_requests.submit(conn, session_id="s", owner=owner, sources=[],
                                 requested="concentration")


def test_a_request_needs_a_resolved_owner(conn):
    with pytest.raises(TypeError):
        analysis_requests.submit(conn, session_id="s", owner="avery",
                                 sources=_sources("avery"), requested="concentration")


@pytest.mark.parametrize("key", ["credentials", "password", "access_token", "api_key"])
def test_a_source_carrying_a_secret_is_refused(conn, key):
    """**A credential written to disk stays written**, and this table is the
    obvious place somebody would put one when TQ-73 needs a fetch authenticated.

    Checked by key name rather than by value: a secret is identified by what it
    is for, and a check that tried to recognise a token by its shape would miss
    the first one that did not match."""
    with pytest.raises(analysis_requests.RequestRefused) as refusal:
        _submit(conn, sources=[{"provider_type": "SCHWAB", "name": "b", key: "hunter2"}])
    assert "credential" in str(refusal.value).lower()


def test_a_claimed_request_is_not_offered_again(conn):
    """The easy half: once claimed, it is no longer pending."""
    _submit(conn)
    first = analysis_requests.claim_next(conn, "analyst-1")
    second = analysis_requests.claim_next(conn, "analyst-2")

    assert first is not None
    assert second is None


def test_two_analysts_racing_for_one_request_cannot_both_win(conn):
    """**The half the sequential test above does not reach**, and mutation
    testing is how that was found: removing the `AND status = 'pending'` guard
    from the claiming UPDATE left `test_a_claimed_request_is_not_offered_again`
    passing, because that test never exercises the guard — the second call's
    SELECT filters the row out before the UPDATE runs.

    The real race is two analysts that have *both already read* the pending row
    and then both try to take it. That window is the length of a fetch, and
    losing it would mean fetching one client's portfolio twice and delivering
    two reports for one request.

    Simulated by claiming the same row twice from the same read, which is what
    the two processes would be doing. `fi_db.claim_next_report` guards the same
    way and for the same reason."""
    request_id = _submit(conn)
    pending = conn.fetchall(
        "SELECT request_id FROM portfolio_analysis_requests WHERE status = ?",
        (analysis_requests.STATUS_PENDING,))
    assert [row["request_id"] for row in pending] == [request_id]

    def claim(identity):
        return conn.execute_returning_rowcount(
            "UPDATE portfolio_analysis_requests SET status = ?, claimed_by = ? "
            "WHERE request_id = ? AND status = ?",
            (analysis_requests.STATUS_IN_PROGRESS, identity, request_id,
             analysis_requests.STATUS_PENDING))

    assert claim("analyst-1") == 1
    assert claim("analyst-2") == 0, (
        "a second analyst took a request that was already claimed - the guarded "
        "UPDATE is what stops one client's portfolio being fetched twice")
    assert conn.fetchone(
        "SELECT claimed_by FROM portfolio_analysis_requests WHERE request_id = ?",
        (request_id,))["claimed_by"] == "analyst-1"


def test_the_claim_is_guarded_in_the_statement_itself(conn):
    """Structural, because the behavioural test above has to simulate the race.
    A claim written as read-then-write would pass every behavioural test in this
    file and lose the window anyway."""
    import inspect

    source = inspect.getsource(analysis_requests.claim_next)
    update = source[source.index("UPDATE portfolio_analysis_requests"):]
    assert "AND status = ?" in update, (
        "the claiming UPDATE has no status guard, so two analysts that both read "
        "the row can both take it")


def test_outstanding_reports_counts_and_never_contents(conn):
    """A hygiene check that printed a client's report to prove it was there would
    be the problem it exists to detect."""
    request_id = _submit(conn)
    analysis_requests.deliver(conn, request_id, {"analysis": {"secret": "SYN2"}})

    report = analysis_requests.outstanding(conn)

    assert report["clean"] is False
    assert report["held"] == 1
    assert "SYN2" not in json.dumps(report)


def test_nothing_is_held_once_everything_is_collected(conn):
    request_id = _submit(conn)
    analysis_requests.deliver(conn, request_id, {"analysis": {}})
    analysis_requests.collect(conn, session_id="sess-1", request_id=request_id)

    assert analysis_requests.outstanding(conn)["clean"] is True


# --- the agent's cycle ---------------------------------------------------------------


def test_the_agent_does_nothing_when_nobody_has_asked(conn):
    """§115: it works only when tasked. An idle cycle is correct here, not
    suspicious - which is a different meaning from an idle Explorer."""
    portfolio_analyst._analyst_work(conn, "analyst-1")
    assert analysis_requests.outstanding(conn)["clean"] is True


def test_the_agent_delivers_a_report_for_a_claimed_request(conn):
    request_id = _submit(conn, sources=_sources("avery"))

    portfolio_analyst._analyst_work(conn, "analyst-1")

    answer = analysis_requests.collect(conn, session_id="sess-1", request_id=request_id)
    assert answer["status"] == analysis_requests.STATUS_READY
    assert answer["result"]["analysis"]["positions"] == 4


def test_the_agent_fails_a_request_it_cannot_perform_rather_than_leaving_it(conn):
    """A client left waiting forever is worse than a client told no."""
    request_id = _submit(conn, requested="stress_test")

    portfolio_analyst._analyst_work(conn, "analyst-1")

    answer = analysis_requests.collect(conn, session_id="sess-1", request_id=request_id)
    assert answer["status"] == analysis_requests.STATUS_FAILED
    assert "stress_test" in answer["detail"]


def test_the_agent_writes_no_position_anywhere(conn, tmp_path):
    """§111 as a property of the schema and the filesystem rather than of the
    code path. The positions exist in one local variable for one cycle."""
    _submit(conn, sources=_sources("avery"))
    before = {p for p in tmp_path.rglob("*")}

    portfolio_analyst._analyst_work(conn, "analyst-1")

    assert {p for p in tmp_path.rglob("*")} == before
    tables = {row["name"] for row in conn.fetchall(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "portfolios" not in tables and "portfolio_holdings" not in tables
    # The only client-derived row is the report, awaiting collection.
    held = conn.fetchall("SELECT status FROM portfolio_analysis_requests")
    assert [row["status"] for row in held] == [analysis_requests.STATUS_READY]


def test_the_role_is_declared_with_what_it_may_not_do():
    """A charter that only lists what a role does is a charter nobody consults
    when deciding what it may not."""
    from backend import fi_db

    charter = fi_db.ROLE_CHARTERS[portfolio_analyst.ROLE]
    forbidden = " ".join(charter["not_allowed"]).lower()

    assert "unasked" in forbidden
    assert "cache" in forbidden
    assert "trade" in forbidden
