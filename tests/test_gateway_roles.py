"""The role boundary (gateway/roles.py + gateway/main.py + gateway/tools.py;
addendum 40 §13.2/§14, addendum 41 §23, addendum 43 §15/§16; TQ-34,
SPEC_RECONCILIATION §92).

Addendum 40 §14 is the sentence: "The presentation layer must never bypass
backend authorization just because information exists on the server."

Two families here, and the second is the one that would actually have been a
breach.

**Routes.** Each declares what it requires, and a tripwire walks the whole
application asserting none is reachable without one. A new route cannot quietly
join a world-readable set, because after this there is no world-readable set.

**Tools.** The sharper half. Route checks are theatre if a client can simply
*ask the agent* to read a repository file - and the agent, holding the
operator's tool list, would do it. So the tool list is filtered by role and the
execution is checked again, because a model can name a tool nobody offered it.
"""

import bcrypt
import pytest

from gateway import auth, main, roles, store, tools


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


@pytest.fixture
def three_roles(monkeypatch):
    """The environment-configured credentials, so the boundary can be crossed in
    a test the way it would be crossed in life.

    Two, not three. TQ-43 (§98) took the client role out of the environment: a
    shared variable is a fair credential for a role that is one person and a
    group password for one that is many, so clients register individually and
    are authenticated through `gateway.clients` instead."""
    for role, (user_env, hash_env) in auth.ROLE_CREDENTIAL_ENV.items():
        monkeypatch.setenv(user_env, f"{role}-user")
        monkeypatch.setenv(hash_env, _hash(f"{role}-pass"))
    return {role: (f"{role}-user", f"{role}-pass") for role in auth.ROLE_CREDENTIAL_ENV}


# --- the vocabulary fails closed ---------------------------------------------------


def test_an_unknown_role_raises_rather_than_quietly_denying(three_roles):
    """A typo that silently denies everything is indistinguishable from a
    correct lockout, and gets debugged as one."""
    with pytest.raises(roles.UnknownRole):
        roles.capabilities("adminstrator")


def test_an_unknown_capability_raises(three_roles):
    """It can only come from a route's own declaration, so raising surfaces a
    mistyped requirement in the suite instead of letting it look like a working
    restriction."""
    with pytest.raises(roles.UnknownCapability):
        roles.allows(roles.ROLE_OPERATOR, "scorebord:read")


def test_every_capability_is_described(three_roles):
    """A 403 that names what is missing is actionable; one that does not is a
    support ticket. The descriptions are also what `/auth/login` returns."""
    assert set(roles.DESCRIPTIONS) == set(roles.CAPABILITIES)
    assert all(roles.DESCRIPTIONS[cap] for cap in roles.CAPABILITIES)


def test_every_role_has_a_grant(three_roles):
    assert set(roles.GRANTS) == set(roles.ROLES)


def test_the_operator_holds_everything_and_the_client_almost_nothing():
    """41 §23: "COO / operator: Full studio… Clients do not need the entire
    executive command center."""
    assert roles.capabilities(roles.ROLE_OPERATOR) == frozenset(roles.CAPABILITIES)
    assert roles.capabilities(roles.ROLE_CLIENT) == frozenset(
        {roles.CAP_CONVERSE, roles.CAP_SESSION, roles.CAP_HOLDINGS})
    # The one that matters most: a client cannot see the organization.
    for withheld in (roles.CAP_STUDIO, roles.CAP_SYSTEM_STATUS,
                     roles.CAP_SCOREBOARD_READ, roles.CAP_REPOSITORY_READ):
        assert not roles.allows(roles.ROLE_CLIENT, withheld)


# --- the tripwire: no route may be unscoped -----------------------------------------


# Deliberately tiny, and every entry earns its place out loud. Anything not here
# needs a capability, and adding to this list should feel like a decision.
PUBLIC_PATHS = {
    "/health",     # liveness plus "is this configured", and nothing else
    "/",           # the login page itself
    "/auth/login", # the door
    # The studio's empty shell. A browser navigation cannot carry an
    # Authorization header, so gating this produced a blank 401 page; the
    # alternatives were a token in the query string (rejected elsewhere in this
    # codebase for writing credentials into logs) or a cookie. The shell holds
    # no organizational data - every byte of that comes through /console/*,
    # which is gated - and the test below is what keeps that true.
    "/studio",
    "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc",
}


def test_the_public_studio_shell_contains_no_organizational_data():
    """What makes `/studio` safe to serve unauthenticated, asserted rather than
    assumed.

    The page is markup and script; the organization arrives through gated
    endpoints. If someone ever inlines state into this file - a bootstrapped
    payload, a rendered agent list, a name - it stops being a shell and this
    fails, which is the point."""
    from pathlib import Path

    page = Path(main.CONSOLE_HTML).read_text(encoding="utf-8")

    # It fetches its data rather than carrying it.
    assert "/console/overview" in page and "/console/feed" in page
    # And carries none of the things a real organization would put in it.
    for leak in ("agent_registry", "GATEWAY_PASSWORD", "Bearer ey", "sqlite"):
        assert leak not in page, f"the studio shell contains {leak!r}"
    # The only name in it is the COO's default, which the specification
    # publishes anyway and which /console/identity overrides at runtime.
    assert page.count("coo-1") == 0


def test_no_route_is_reachable_without_a_declared_capability():
    """The tripwire. This is what stops the boundary from decaying: a route
    added next year without a capability fails here rather than shipping as an
    accidental public surface.

    Checked by reading each route's dependency tree for the closure `require`
    builds, rather than by matching names - a check keyed on naming would pass
    for a route that merely *looked* protected."""
    from fastapi.routing import APIWebSocketRoute

    unscoped = []
    for route in main.app.routes:
        path = getattr(route, "path", None)
        if path is None or path in PUBLIC_PATHS:
            continue
        if isinstance(route, APIWebSocketRoute):
            # A socket cannot use Depends: its token arrives in the first frame,
            # because browsers cannot set headers on a handshake. Its check is
            # written inline and asserted by the test below - excluded by type
            # rather than by name, so a *new* websocket is excluded for the same
            # reason rather than by accident.
            continue
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        names = _dependency_names(dependant)
        if "dependency" not in names:
            unscoped.append(f"{getattr(route, 'methods', {'WS'})} {path}")
    assert not unscoped, (
        f"these routes are reachable by any authenticated session: {unscoped}. "
        "Give each one Depends(require(<capability>))."
    )


def _dependency_names(dependant) -> set[str]:
    found = set()
    for sub in getattr(dependant, "dependencies", []):
        call = getattr(sub, "call", None)
        if call is not None:
            found.add(getattr(call, "__name__", ""))
        found |= _dependency_names(sub)
    return found


def test_the_websocket_checks_the_conversation_capability():
    """The socket cannot use `Depends`, so its check is written inline and
    asserted here - the one route where the tripwire above cannot see inside."""
    import inspect

    source = inspect.getsource(main.conversation_socket)
    assert "session_role" in source
    assert "CAP_CONVERSE" in source


# --- logging in as somebody -----------------------------------------------------------


def test_each_environment_credential_resolves_to_its_own_role(three_roles):
    for role, (username, password) in three_roles.items():
        assert auth.identify(username, password) == role


def test_the_client_role_has_no_environment_credential():
    """The change TQ-43 exists for. A shared `GATEWAY_CLIENT_PASSWORD_HASH`
    would be a group password for every client at once - and leaving it
    configurable "for compatibility" would leave the hole open rather than
    provide a way out of it."""
    assert roles.ROLE_CLIENT not in auth.ROLE_CREDENTIAL_ENV
    with pytest.raises(roles.UnknownRole):
        auth.credential_for(roles.ROLE_CLIENT)
    assert roles.ROLE_CLIENT not in auth.configured_roles()


def test_a_registered_client_logs_in_as_itself(gateway_conn, three_roles):
    """And the identity it gets is the registry's, not the string it typed."""
    from gateway import clients

    _, password = clients.register(gateway_conn, "alice", display_name="Alice")

    assert clients.authenticate(gateway_conn, "alice", password) == "alice"
    # The environment path does not know about them at all.
    assert auth.identify("alice", password) is None


def test_a_wrong_password_resolves_to_nobody(three_roles):
    assert auth.identify("operator-user", "internal-pass") is None


def test_an_unconfigured_role_cannot_log_in(monkeypatch):
    """Unset means that door is shut, the same rule the Super User has always
    had. A second credential is exactly as much of a boundary as the first."""
    for user_env, hash_env in auth.ROLE_CREDENTIAL_ENV.values():
        monkeypatch.delenv(user_env, raising=False)
        monkeypatch.delenv(hash_env, raising=False)
    monkeypatch.setenv("GATEWAY_SUPER_USER", "boss")
    monkeypatch.setenv("GATEWAY_PASSWORD_HASH", _hash("secret"))

    assert auth.configured_roles() == [roles.ROLE_OPERATOR]
    assert auth.identify("boss", "secret") == roles.ROLE_OPERATOR
    assert auth.identify("anyone", "secret") is None


def test_a_malformed_hash_refuses_rather_than_raising(monkeypatch):
    """A typo in the environment must not become a 500 that leaks a stack trace
    to an external client."""
    monkeypatch.setenv("GATEWAY_INTERNAL_USER", "c")
    monkeypatch.setenv("GATEWAY_INTERNAL_PASSWORD_HASH", "not-a-bcrypt-hash")
    assert auth.identify("c", "anything") is None


# --- sessions carry the role, and fail closed without one -------------------------------


def test_a_session_remembers_which_role_opened_it(gateway_conn):
    token, _ = store.create_session(gateway_conn, 60, roles.ROLE_CLIENT)
    assert store.session_role(gateway_conn, token) == roles.ROLE_CLIENT


def test_a_session_predating_roles_is_refused_not_promoted(gateway_conn):
    """The upgrade case, and the one outcome a security column must not have.
    Defaulting the new column to the operator would silently promote every
    session that existed before the boundary did."""
    token, _ = store.create_session(gateway_conn, 60, roles.ROLE_OPERATOR)
    gateway_conn.execute("UPDATE sessions SET role = NULL")
    assert store.session_role(gateway_conn, token) is None


def test_a_session_carrying_an_unknown_role_is_refused(gateway_conn):
    token, _ = store.create_session(gateway_conn, 60, roles.ROLE_OPERATOR)
    gateway_conn.execute("UPDATE sessions SET role = 'superuser'")
    assert store.session_role(gateway_conn, token) is None


def test_an_expired_session_has_no_role(gateway_conn):
    token, _ = store.create_session(gateway_conn, -1, roles.ROLE_OPERATOR)
    assert store.session_role(gateway_conn, token) is None


def test_a_session_cannot_be_issued_for_a_role_that_does_not_exist(gateway_conn):
    with pytest.raises(roles.UnknownRole):
        store.create_session(gateway_conn, 60, "root")


# --- the half that would have been the breach ---------------------------------------------


def test_a_client_is_offered_no_portfolio_tool_in_this_build(gateway_conn):
    """This asserted `== []` until TQ-41, then a set of five holdings tools, and
    now `== []` again — which is not going backwards.

    TQ-41 gave a client the holdings tools because §96 answered "where do a
    client's holdings come from" with *the client tells you, and you remember*.
    §111 and §115 retired both halves: a client names an external source and
    supplies credentials, and nothing is remembered. So the five tools were
    withdrawn rather than left refusing (TQ-72), because their *shape* is wrong,
    not just their implementation — declaring `record_holding` as "coming soon"
    would promise a tool this system has decided not to have.

    **`CAP_HOLDINGS` is deliberately still declared** with nothing mapped to it.
    The capability and the role matrix around it were decided carefully in §92
    and are still right; what is gone is this build's answer to them. TQ-73's
    analysis tools map to it, and that decision does not get made twice."""
    from gateway import tools

    offered = {tool["name"] for tool in tools.for_role(roles.ROLE_CLIENT)}
    assert offered == set(), (
        f"a client is offered {offered}; this build has no portfolio tool to give")

    # The capability survives the tools that used it.
    assert roles.CAP_HOLDINGS in roles.CAPABILITIES
    assert roles.allows(roles.ROLE_CLIENT, roles.CAP_HOLDINGS)
    assert not any(required == roles.CAP_HOLDINGS
                   for required in tools.TOOL_CAPABILITY.values()), (
        "a tool claims CAP_HOLDINGS again - if TQ-73 has landed, this test is the "
        "one to update deliberately")


def test_every_tool_a_client_can_reach_takes_its_subject_from_the_session(three_roles):
    """The property that makes the holdings tools safe to grant at all: none of
    them accepts a client id as an argument, so "read somebody else's positions"
    is not a call the model is able to construct (TQ-41, §96)."""
    for tool in tools.for_role(roles.ROLE_CLIENT):
        properties = set((tool.get("input_schema") or {}).get("properties") or {})
        for forbidden in ("client_id", "client", "subject", "owner", "user"):
            assert forbidden not in properties, (
                f"{tool['name']} lets the model name whose data to read")


def test_an_operator_is_offered_every_tool(three_roles):
    offered = {tool["name"] for tool in tools.for_role(roles.ROLE_OPERATOR)}
    assert offered == set(tools.TOOL_CAPABILITY)


def test_a_client_cannot_reach_the_repository_by_asking_the_agent(gateway_conn):
    """The breach this whole module exists to prevent, stated as one assertion.

    Every route check in the Gateway is theatre if a client can ask the
    conversational agent to read a file for them - §14's rule applies with more
    force to a tool list than to a dashboard, because a model will reach for
    anything it is offered."""
    refusal = tools.execute(gateway_conn, "read_repository_file",
                            {"path": "docs/anything.md"}, role=roles.ROLE_CLIENT)
    assert "error" in refusal
    assert "Not permitted" in refusal["error"]


@pytest.mark.parametrize("tool_name", [
    "read_repository_file", "list_repository_files", "publish_document",
    "list_scoreboard_items", "file_scoreboard_item", "jarvis_status",
    "technology_review",
])
def test_no_tool_at_all_executes_for_a_client(gateway_conn, tool_name):
    """Checked at execution and not only at offering, because a model can name
    a tool nobody put in front of it - filtering the list is presentation, and
    §14 says presentation is not authorization."""
    outcome = tools.execute(gateway_conn, tool_name, {}, role=roles.ROLE_CLIENT)
    assert "error" in outcome and "Not permitted" in outcome["error"]


def test_an_unmapped_tool_is_refused_for_everybody(gateway_conn):
    """A tool added without a capability is a mistake, and the safe reading of a
    mistake is "nobody", not "everybody"."""
    assert not tools.permitted(roles.ROLE_OPERATOR, "delete_everything")


def test_every_declared_tool_has_a_capability():
    """Otherwise `for_role` silently drops it from every role's list and the
    tool becomes dead code that looks live."""
    declared = {tool["name"] for tool in tools.TOOLS}
    assert declared == set(tools.TOOL_CAPABILITY), (
        f"unmapped: {sorted(declared - set(tools.TOOL_CAPABILITY))}; "
        f"mapped but not declared: {sorted(set(tools.TOOL_CAPABILITY) - declared)}"
    )


def test_the_turn_refuses_a_role_it_was_not_given():
    """`run_turn` has no default role. A caller that forgot to pass one would
    otherwise get the most permissive behaviour, on the path a client reaches."""
    import inspect

    from gateway import conversation

    signature = inspect.signature(conversation.run_turn)
    assert signature.parameters["role"].default is inspect.Parameter.empty
    assert signature.parameters["role"].kind is inspect.Parameter.KEYWORD_ONLY
