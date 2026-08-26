"""The on-behalf-of portfolio surface, and the second check it exists to add
(TQ-69, docs/SPEC_RECONCILIATION.md §110; spec §7, §8, §9).

Before this increment the Gateway's ownership check was the *only* check. There
was no backend authorization to bypass, because there was no backend
authorization. This file is the evidence that there now is one, and it is
written to fail if that ever stops being true.

**The one to read first is
`test_a_client_cannot_receive_the_superuser_portfolio_when_it_is_the_only_one`.**
It is addendum 44 §15.5's permanent regression - §93's conversation leak in
portfolio form, where a lookup that fell back to "the only row there is" sent the
operator's entire transcript out in a client's opening frame. It already exists
as a module-level test in `test_backend_portfolios.py`; here it runs **from the
Gateway's side, through the real HTTP client, against the real backend routes**.
Spec §7: if that does not pass over the wire, the move failed whatever else is
green.

Nothing here is mocked between the Gateway and the backend. The transport is a
TestClient over `backend.main:app`, so `require_gateway`, `/auth/login`,
`portfolios.resolve` and the refusal's status code are all the production ones.
A test that asserted the JSON the client *expects* would keep passing after the
backend changed its routes, and what it would stop catching is a client
receiving somebody else's portfolio.

## What this file does not claim

Spec §4.3, restated where somebody reading the tests will see it: **none of this
defends against a compromised Gateway**, which can assert any `owner_id` it
likes. It defends against a *buggy* one - the failure this project has actually
had twice (§93, §106), neither time with a second check to catch it. A test file
that implied otherwise would be making a false security claim, which is worse
than an absent one.
"""

import re
from pathlib import Path

import pytest

from backend import holdings, portfolios
from gateway import portfolio_client, roles, store, tools


# --- the §15.5 regression, over the wire (spec §7) ----------------------------------


def test_a_client_cannot_receive_the_superuser_portfolio_when_it_is_the_only_one(
        portfolio_conn, portfolios_client):
    """**The headline test of this increment.**

    One portfolio exists in the whole database and it is the operator's. A client
    asks for theirs. The shape that has to be refused is the helpful one: "there
    is only one, it must be yours."

    Over HTTP now, which makes it a different claim than the module-level version
    in `test_backend_portfolios.py` - that one proves the guard refuses, this one
    proves the *Gateway cannot get round it*, because the Gateway no longer holds
    the table and the answer comes back from a process that checked."""
    operator = portfolios.for_superuser()
    only_row = portfolios.create(portfolio_conn, operator, display_name="House")
    assert portfolio_conn.fetchone("SELECT COUNT(*) AS n FROM portfolios")["n"] == 1

    # Asking for it by id: refused.
    with pytest.raises(portfolio_client.NotAuthorized):
        portfolios_client.resolve("avery", only_row["portfolio_id"])

    # Asking for "my portfolios": empty, not the only row there is.
    assert portfolios_client.listing("avery") == []

    # And the tool a client's own agent would call gets a portfolio of their own
    # rather than the operator's.
    theirs = portfolios_client.primary("avery")
    assert theirs["portfolio_id"] != only_row["portfolio_id"]
    assert (theirs["owner_type"], theirs["owner_id"]) == (portfolios.OWNER_CLIENT, "avery")


def test_the_backend_refuses_a_foreign_owner_even_when_the_gateway_asks(portfolio_conn,
                                                                       portfolios_client):
    """**The check that did not exist before, and the reason for the increment.**

    The Gateway is authenticated and is the authenticator, so the backend takes
    its word for *who is asking*. It does not take its word for *what they may
    reach*. A Gateway bug that asserted the wrong subject - which is exactly the
    shape of §93 and §106 - is refused here rather than served."""
    avery = portfolios.primary_for(portfolio_conn, portfolios.for_client("avery"))
    holdings.record(portfolio_conn, avery, symbol="SYN1", quantity=100, average_cost=10)

    with pytest.raises(portfolio_client.NotAuthorized):
        portfolios_client.resolve("morgan", avery["portfolio_id"])
    with pytest.raises(portfolio_client.NotAuthorized):
        portfolios_client.holdings("morgan", avery["portfolio_id"])
    with pytest.raises(portfolio_client.NotAuthorized):
        portfolios_client.record("morgan", avery["portfolio_id"], symbol="SYN9", quantity=1)
    with pytest.raises(portfolio_client.NotAuthorized):
        portfolios_client.forget("morgan", avery["portfolio_id"], "SYN1")
    with pytest.raises(portfolio_client.NotAuthorized):
        portfolios_client.analysis("morgan", avery["portfolio_id"])

    # Nothing was written by the refused calls, and nothing was removed.
    assert [h["symbol"] for h in holdings.listing(portfolio_conn, avery)] == ["SYN1"]


def test_absent_foreign_and_archived_are_one_refusal_over_http(portfolio_conn,
                                                               portfolios_client):
    """Addendum 44 §9.3 is about what a caller can *tell apart*, and a status
    code is something a caller can tell apart.

    So the three cases have to arrive identically over the wire as well as in
    process: same exception, same message, no detail. A refusal that said
    "archived" for one and "not found" for another would confirm that somebody
    else's portfolio exists, which is the fact being withheld."""
    avery = portfolios.for_client("avery")
    foreign = portfolios.create(portfolio_conn, portfolios.for_client("morgan"),
                                display_name="Portfolio")
    archived = portfolios.create(portfolio_conn, avery, display_name="Old",
                                 portfolio_type=portfolios.TYPE_SECONDARY)
    portfolios.archive(portfolio_conn, archived["portfolio_id"], avery)

    refusals = []
    for portfolio_id in ("pf-does-not-exist", foreign["portfolio_id"],
                         archived["portfolio_id"]):
        with pytest.raises(portfolio_client.NotAuthorized) as raised:
            portfolios_client.resolve("avery", portfolio_id)
        refusals.append(str(raised.value))

    assert refusals == [portfolios.REFUSAL] * 3


# --- require_gateway (spec §4.4, §9.3) ----------------------------------------------


def test_an_ordinary_backend_user_cannot_reach_the_portfolio_surface(portfolio_backend,
                                                                     portfolio_conn):
    """**A surface that accepts an asserted subject from anyone is worse than no
    surface**, because it lets any authenticated backend user read any client's
    portfolio simply by naming them.

    An ordinary account, correctly authenticated, refused at every route."""
    avery = portfolios.primary_for(portfolio_conn, portfolios.for_client("avery"))
    portfolio_backend.post("/auth/register",
                           json={"username": "ordinary", "password": "ordinary-password"})
    token = portfolio_backend.post(
        "/auth/login",
        json={"username": "ordinary", "password": "ordinary-password"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    owner = {"owner_type": "CLIENT", "owner_id": "avery"}
    pid = avery["portfolio_id"]

    refused = [
        portfolio_backend.get("/portfolios", params=owner, headers=headers),
        portfolio_backend.post("/portfolios/resolve",
                               json={**owner, "portfolio_id": pid}, headers=headers),
        portfolio_backend.post("/portfolios/primary", json=owner, headers=headers),
        portfolio_backend.get(f"/portfolios/{pid}/holdings", params=owner, headers=headers),
        portfolio_backend.post(f"/portfolios/{pid}/holdings",
                               json={**owner, "symbol": "SYN1", "quantity": 1},
                               headers=headers),
        portfolio_backend.delete(f"/portfolios/{pid}/holdings/SYN1",
                                 params=owner, headers=headers),
        portfolio_backend.get(f"/portfolios/{pid}/balances", params=owner, headers=headers),
        portfolio_backend.get(f"/portfolios/{pid}/analysis", params=owner, headers=headers),
        portfolio_backend.post(f"/portfolios/{pid}/refresh", json=owner, headers=headers),
        portfolio_backend.post("/portfolios/purge", json=owner, headers=headers),
    ]

    assert [r.status_code for r in refused] == [403] * len(refused)
    assert all("may not act on behalf of another owner" in r.json()["detail"]
               for r in refused)


def test_an_anonymous_caller_cannot_reach_the_portfolio_surface(portfolio_backend):
    assert portfolio_backend.get(
        "/portfolios", params={"owner_type": "CLIENT", "owner_id": "avery"}
    ).status_code == 401


def test_the_surface_is_closed_when_no_gateway_account_is_configured(portfolio_backend,
                                                                     monkeypatch):
    """`admin_auth`'s rule: an authorization check that defaults open is worse
    than none, because it looks protected. Unset refuses everybody, including
    the account that would otherwise be the Gateway, and the message says what
    to set."""
    from app import gateway_auth
    from tests.conftest import GATEWAY_BACKEND_PASSWORD, GATEWAY_BACKEND_USER

    token = portfolio_backend.post(
        "/auth/login",
        json={"username": GATEWAY_BACKEND_USER,
              "password": GATEWAY_BACKEND_PASSWORD}).json()["token"]
    monkeypatch.delenv(gateway_auth.GATEWAY_USER_ENV, raising=False)

    response = portfolio_backend.get(
        "/portfolios", params={"owner_type": "CLIENT", "owner_id": "avery"},
        headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert gateway_auth.GATEWAY_USER_ENV in response.json()["detail"]


def test_the_gateway_gate_is_not_the_admin_gate(portfolio_backend, monkeypatch):
    """They name the same account in this deployment and they answer different
    questions. Collapsing them would mean adding an operator to
    `MY_AI_ADMIN_USERS` silently granted them every client's portfolio."""
    from app import gateway_auth
    from tests.conftest import GATEWAY_BACKEND_PASSWORD, GATEWAY_BACKEND_USER

    token = portfolio_backend.post(
        "/auth/login",
        json={"username": GATEWAY_BACKEND_USER,
              "password": GATEWAY_BACKEND_PASSWORD}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    # An admin who is not the Gateway.
    monkeypatch.setenv(gateway_auth.GATEWAY_USER_ENV, "some-other-service")

    assert portfolio_backend.get("/admin/portfolios/simulated",
                                 headers=headers).status_code == 200
    assert portfolio_backend.get(
        "/portfolios", params={"owner_type": "CLIENT", "owner_id": "avery"},
        headers=headers).status_code == 403


# --- no ownerless route (spec §4.4, §8.3) -------------------------------------------


def test_no_portfolio_route_is_ownerless():
    """Addendum 44 §16.7's rule, applied to the new surface **before** it can be
    broken rather than after.

    §16.7 exists because `app/tools/portfolio.py` has a retrieval function with
    no owner argument, and TQ-46 is the increment that has to unpick it. The
    lesson taken here is that the cheap moment to enforce "every retrieval names
    an owner" is while the surface is one commit old.

    Scanned from the application's own route table rather than from the source
    text, so a route added by any means - a decorator, a router, a loop - is
    still checked. A regex over `@app.get(...)` would be a scan of one way of
    writing routes."""
    import backend.main as backend_main

    ownerless = []
    for route in backend_main.app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/portfolios"):
            continue
        parameters = set(getattr(route, "endpoint").__annotations__)
        fields = set()
        for name, annotation in getattr(route, "endpoint").__annotations__.items():
            model_fields = getattr(annotation, "model_fields", None)
            if model_fields:
                fields |= set(model_fields)
        if not ({"owner_type", "owner_id"} <= (parameters | fields)):
            ownerless.append(f"{sorted(route.methods)} {path}")

    assert not ownerless, (
        "these portfolio routes do not take an owner:\n  " + "\n  ".join(ownerless)
        + "\nEvery route on this surface authorizes an asserted owner. A route that "
          "returns portfolio data without one is the ownerless retrieval addendum 44 "
          "§16.7 exists to remove."
    )


def test_every_portfolio_route_is_gated_by_require_gateway():
    """The other half: a route can take an owner and still let anybody assert
    one. `require_gateway` is what makes an asserted subject safe to accept at
    all, and spec §9.3 says it is not optional."""
    import backend.main as backend_main

    ungated = []
    for route in backend_main.app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/portfolios"):
            continue
        gates = {getattr(d.call, "__name__", None)
                 for d in getattr(route, "dependant").dependencies}
        if "require_gateway" not in gates:
            ungated.append(f"{sorted(route.methods)} {path}")

    assert not ungated, (
        "these portfolio routes are not behind require_gateway:\n  "
        + "\n  ".join(ungated))


def test_the_client_has_no_method_that_reaches_data_without_a_subject():
    """The same rule at the other end of the wire. The backend refuses an
    ownerless call anyway - but a client that *could* form one is a client
    somebody could accidentally use, and the shape of an interface is what
    people build against.

    `simulated` is the deliberate exception and is not on this surface: it is
    demo-data hygiene on `/admin`, returns ids and counts and no positions, and
    is owner-scoped by nothing because it is not a client's question."""
    exempt = {"simulated"}
    offenders = []
    for name in dir(portfolio_client.PortfolioClient):
        if name.startswith("_") or name in exempt:
            continue
        member = getattr(portfolio_client.PortfolioClient, name)
        if not callable(member):
            continue
        if "subject" not in member.__code__.co_varnames[:member.__code__.co_argcount]:
            offenders.append(name)

    assert not offenders, (
        f"PortfolioClient.{offenders} reach portfolio data without naming a subject.")


# --- failure behaviour: no stale data (spec §4.5, Risk 3) ---------------------------


class _DeadBackend:
    """A backend that is not there. Used only where the *client's* behaviour is
    under test; the refusal path is also exercised against a genuinely stopped
    process in the spec's §13 live check, which is the version that cannot be
    fooled by a stub."""

    def __init__(self, exception):
        self.exception = exception

    def __call__(self, method, path, *, params=None, json=None, token=None):
        raise self.exception


def test_the_gateway_refuses_in_words_when_the_backend_is_unreachable(monkeypatch):
    """The credentials are set deliberately, and that is not housekeeping.

    Without them this test passed against a mutation that removed the refusal
    entirely - because `_call` checks `is_configured()` first, and the
    *unconfigured* message happens to contain the same two words this asserts.
    It was green, and it was testing nothing. Found by mutation-testing rather
    than by reading, which is the whole argument for doing it."""
    import requests

    monkeypatch.setenv(portfolio_client.BACKEND_USER_ENV, "gateway-service")
    monkeypatch.setenv(portfolio_client.BACKEND_PASSWORD_ENV, "irrelevant")
    client = portfolio_client.PortfolioClient(
        transport=_DeadBackend(requests.ConnectionError("no route to host")))

    with pytest.raises(portfolio_client.BackendUnavailable) as refusal:
        client.holdings("avery", "pf-anything")

    said = str(refusal.value)
    assert "did not answer" in said, (
        "the refusal must name the backend as unreachable, not merely unconfigured")
    assert "out of date" in said


def test_a_holdings_tool_serves_nothing_stale_when_the_backend_is_down(gateway_conn,
                                                                       monkeypatch):
    """**§4.5, and the failure path spec Risk 3 says nobody tests.**

    The Gateway keeps no cache, so there is nothing to fall back to - and that
    is the design rather than an accident. Showing somebody last week's
    positions as though they were current is the same class of wrong as serving
    a simulated price as a real one (§101), and worse than showing nothing.

    What the tool must **not** do is return `{"holdings": []}`. An empty list
    reads as "you hold nothing", which is a false answer about somebody's money
    delivered in the voice of a true one."""
    import requests

    monkeypatch.setenv(portfolio_client.BACKEND_USER_ENV, "gateway-service")
    monkeypatch.setenv(portfolio_client.BACKEND_PASSWORD_ENV, "irrelevant")
    dead = portfolio_client.PortfolioClient(
        transport=_DeadBackend(requests.ConnectionError("connection refused")))

    for name in ("list_holdings", "analyse_holdings", "portfolio_balances"):
        outcome = tools.execute(gateway_conn, name, {}, role=roles.ROLE_CLIENT,
                                subject="avery", portfolios_client=dead)

        assert "error" in outcome, f"{name} answered instead of refusing"
        assert outcome["unavailable"] is True
        assert "backend" in outcome["error"].lower()
        assert "holdings" not in outcome and "analysis" not in outcome \
            and "balances" not in outcome


def test_a_recorded_holding_is_not_quietly_accepted_when_the_backend_is_down(gateway_conn,
                                                                            monkeypatch):
    """The write half of the same rule. "Noted" for something that was not
    stored is worse than a refusal, because the client stops repeating it."""
    import requests

    monkeypatch.setenv(portfolio_client.BACKEND_USER_ENV, "gateway-service")
    monkeypatch.setenv(portfolio_client.BACKEND_PASSWORD_ENV, "irrelevant")
    dead = portfolio_client.PortfolioClient(
        transport=_DeadBackend(requests.ConnectionError("connection refused")))

    outcome = tools.execute(gateway_conn, "record_holding",
                            {"symbol": "SYN1", "quantity": 10},
                            role=roles.ROLE_CLIENT, subject="avery",
                            portfolios_client=dead)

    assert "recorded" not in outcome
    assert outcome["unavailable"] is True


def test_an_unconfigured_gateway_refuses_rather_than_answering_emptily(monkeypatch):
    monkeypatch.delenv(portfolio_client.BACKEND_USER_ENV, raising=False)
    monkeypatch.delenv(portfolio_client.BACKEND_PASSWORD_ENV, raising=False)

    with pytest.raises(portfolio_client.BackendUnavailable) as refusal:
        portfolio_client.PortfolioClient().listing("avery")

    assert portfolio_client.BACKEND_USER_ENV in str(refusal.value)


# --- the Gateway holds no portfolio data (spec §7, §8.1) ----------------------------


def test_the_gateway_holds_no_portfolio_table(gateway_conn):
    """Spec §8.1: the tables are in `financial_intelligence.db` **and nowhere
    else**.

    Risk 2 is what this guards: if some reads went over HTTP and others still
    hit gateway.db there would be two sources of truth for one fact, which is
    the problem this project has refused four times. The Gateway had to stop
    *creating* those tables in the same increment it stopped reading them."""
    tables = {row["name"] for row in gateway_conn.fetchall(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}

    assert "portfolios" not in tables
    assert "portfolio_holdings" not in tables
    # The two that do belong here, so this fails if the fixture ever stops
    # building a real Gateway database and starts passing vacuously.
    assert {"sessions", "clients"} <= tables


def test_no_gateway_module_imports_the_backends_portfolio_subsystem():
    """The tripwire TQ-69 needs and TQ-44 did not.

    The table scan in `test_backend_portfolios.py` catches SQL. It does not catch
    a Gateway module that imports `backend.portfolios` and calls
    `resolve(gateway_conn, ...)` - which would look entirely reasonable, would
    pass every other check here, and would put the guard back on the wrong side
    of the boundary this increment moved it across.

    **Read from the import graph rather than from the source text**, and that is
    not a stylistic preference. The first version of this scan matched the string
    `backend.portfolios`, went green, and missed `from backend import portfolios`
    - the ordinary spelling, and the one a person would actually write. Found by
    mutation-testing rather than by reading it, which is now the fourth time in
    this project a scanner has been wrong while the module it guarded was right
    (§101, §104, §107). An import is a node in a tree; matching how somebody
    happened to spell it is guessing.

    **One exception, and it is a rule rather than a capability:**
    `gateway/clients.py` imports `normalise`, so that there is one definition of
    when two owner ids are the same person. A second normalisation that drifted
    would make one client into two owners, and no ownership comparison could
    detect it - both comparisons would be correct, about different people. The
    exception is narrow enough to state, so it is stated, and
    `test_no_gateway_module_reaches_the_backends_portfolio_subsystem` in
    `test_backend_portfolios.py` checks that nothing more than that one function
    is taken."""
    import ast

    forbidden = {"portfolios", "holdings", "portfolio_providers", "portfolio_migration"}
    allowed_module = "clients.py"
    offenders = []

    for path in sorted((Path(__file__).resolve().parent.parent / "gateway").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            named = set()
            if isinstance(node, ast.ImportFrom) and (node.module or "") == "backend":
                named = {alias.name for alias in node.names} & forbidden
            elif isinstance(node, ast.ImportFrom) and \
                    (node.module or "").startswith("backend."):
                named = {node.module.split(".", 1)[1].split(".")[0]} & forbidden
            elif isinstance(node, ast.Import):
                named = {alias.name.split(".", 1)[1].split(".")[0]
                         for alias in node.names
                         if alias.name.startswith("backend.")} & forbidden
            if named and path.name != allowed_module:
                offenders.append(f"{path.name}: backend.{sorted(named)}")

    assert not offenders, (
        "these Gateway modules import the backend's portfolio subsystem:\n  "
        + "\n  ".join(offenders)
        + "\nThe Gateway reaches portfolios over HTTP, through "
          "gateway/portfolio_client.py. Importing those modules is how the ownership "
          "guard ends up back on the Gateway's side of the boundary - it would not "
          "look like a bypass, it would look like a convenience."
    )


def test_the_gateway_source_declares_no_portfolio_schema():
    """A schema string is how the table would come back. Checked in the source
    rather than only in a built database, because a `CREATE TABLE` that only
    runs on a code path no test takes would still be there waiting."""
    root = Path(__file__).resolve().parent.parent
    offenders = []
    for path in sorted((root / "gateway").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(
                r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+(portfolios|portfolio_holdings)\b",
                text, re.IGNORECASE):
            offenders.append(f"{path.name}: {match.group(0)}")

    assert not offenders, (
        "the Gateway declares portfolio tables:\n  " + "\n  ".join(offenders)
        + "\nThey live in financial_intelligence.db. A second, empty copy here is two "
          "sources of truth for whose money this is."
    )


def test_the_wire_vocabulary_matches_the_backends():
    """`gateway/portfolio_client.py` writes out the three portfolio words it has
    a reason to send, rather than importing the backend's module. This is what
    keeps that from being a second definition: two spellings, one fact, and
    something that fails when that stops being true (§70, §100, §104)."""
    assert portfolio_client.OWNER_CLIENT == portfolios.OWNER_CLIENT
    assert portfolio_client.PROVIDER_SIMULATED == portfolios.PROVIDER_SIMULATED
    assert portfolio_client.MODE_SIMULATED == portfolios.MODE_SIMULATED


def test_the_gateway_never_caches_a_holding(gateway_conn, portfolio_conn,
                                            portfolios_client):
    """§4.5 as a property of the database rather than of the code path.

    A read that landed rows in gateway.db would be a cache whether anybody
    called it one, and the next backend outage would serve them."""
    avery = portfolios.primary_for(portfolio_conn, portfolios.for_client("avery"))
    holdings.record(portfolio_conn, avery, symbol="SYN1", quantity=100, average_cost=10)

    read = tools.execute(gateway_conn, "list_holdings", {}, role=roles.ROLE_CLIENT,
                         subject="avery", portfolios_client=portfolios_client)
    assert [h["symbol"] for h in read["holdings"]] == ["SYN1"]

    after = {row["name"] for row in gateway_conn.fetchall(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert not any("portfolio" in name or "holding" in name for name in after), (
        f"the Gateway kept portfolio data after a read: {sorted(after)}")


# --- the tools, end to end over the wire --------------------------------------------


def test_the_holdings_tools_work_through_the_backend(gateway_conn, portfolio_conn,
                                                     portfolios_client):
    """The ordinary path, asserted end to end: what a client tells their
    representative goes to the backend, comes back through the guard, and is
    counted by arithmetic the backend computed."""
    def run(name, arguments=None):
        return tools.execute(gateway_conn, name, arguments or {},
                             role=roles.ROLE_CLIENT, subject="avery",
                             portfolios_client=portfolios_client)

    run("record_holding", {"symbol": "syn1", "quantity": 100, "average_cost": 10})
    run("record_holding", {"symbol": "SYN2", "quantity": 50, "average_cost": 2})

    assert [h["symbol"] for h in run("list_holdings")["holdings"]] == ["SYN1", "SYN2"]

    analysis = run("analyse_holdings")["analysis"]
    assert analysis["known_cost"] == 1100
    # The one pricing rule, reported over the wire exactly as in process.
    assert analysis["priced"] is False

    assert run("forget_holding", {"symbol": "SYN1"})["forgotten"] is True
    assert [h["symbol"] for h in run("list_holdings")["holdings"]] == ["SYN2"]

    # Written where the backend can see it, and only there.
    avery = portfolios.primary_for(portfolio_conn, portfolios.for_client("avery"))
    assert [h["symbol"] for h in holdings.listing(portfolio_conn, avery)] == ["SYN2"]


def test_a_provider_that_cannot_answer_says_why_over_the_wire(gateway_conn,
                                                              portfolios_client):
    """A refusal with a reason, carried across HTTP as a reason rather than
    flattened into an error code. `{}` would read as "no cash" and `0` would be
    a fabrication; this is a sentence the agent can repeat aloud."""
    outcome = tools.execute(gateway_conn, "portfolio_balances", {},
                            role=roles.ROLE_CLIENT, subject="avery",
                            portfolios_client=portfolios_client)

    assert outcome["unavailable"] is True
    assert "told me" in outcome["error"]


def test_a_holding_the_backend_refuses_comes_back_as_the_backends_reason(gateway_conn,
                                                                        portfolios_client):
    """Validation stays in one place - the backend - and its words reach the
    client unmodified. A Gateway that revalidated would be a second definition
    of what a holding is, and the two would drift."""
    outcome = tools.execute(gateway_conn, "record_holding",
                            {"symbol": "SYN1", "quantity": 0},
                            role=roles.ROLE_CLIENT, subject="avery",
                            portfolios_client=portfolios_client)

    assert "recorded" not in outcome
    assert "zero is not a position" in outcome["error"]


def test_the_gateway_still_refuses_a_holdings_tool_with_no_subject(gateway_conn,
                                                                   portfolios_client):
    """The Gateway's own check, unchanged by the move and still first: a
    holdings tool with no subject has nobody to answer for, and picking somebody
    would be the bug. It never reaches the network."""
    for nobody in (None, "", "  "):
        outcome = tools.execute(gateway_conn, "list_holdings", {},
                                role=roles.ROLE_CLIENT, subject=nobody,
                                portfolios_client=portfolios_client)
        assert "whose" in outcome["error"]
