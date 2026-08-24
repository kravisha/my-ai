"""Tests for the superuser gate on /admin routes (addendum 14 §7).

Deliberately driven through `backend_client`, which does NOT override
require_admin - unlike `panel_client`, which stands in an authenticated admin
so the feature tests can get on with their subject. If every test used the
override, nothing would ever exercise the real check, which is how an auth
gate rots without anyone noticing.
"""

from app import admin_auth


def _register(backend_client, username="alice", password="hunter2"):
    token = backend_client.post(
        "/auth/register", json={"username": username, "password": password}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


# Dummy values for path parameters, so a derived route like
# /admin/agents/{identity} becomes a concrete request. Auth is checked before
# any parameter is looked at, so the values only need to parse.
_PARAM_STAND_INS = {
    "username": "alice",
    "identity": "explorer-1",
    "name": "some-lens",
    "revision_id": "1",
    "request_id": "1",
    "mission_id": "m1",
    "entry_id": "1",
}


def _admin_surface():
    """Every /admin route the app actually serves, derived from its own
    routing table rather than a hand-maintained list. The first version of
    this test WAS a hand-maintained list, and it silently fell to covering
    nine of twenty-seven routes as the surface grew - which is exactly the
    rot the docstring below warns about, discovered rather than prevented."""
    from backend.main import app

    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/admin"):
            continue
        for name, value in _PARAM_STAND_INS.items():
            path = path.replace("{" + name + "}", value)
        assert "{" not in path, f"unmapped path parameter in {route.path} - extend _PARAM_STAND_INS"
        for method in route.methods - {"HEAD", "OPTIONS"}:
            yield method.lower(), path


def test_every_admin_route_refuses_an_anonymous_caller(backend_client, monkeypatch):
    """The whole surface, not a sample. A single ungated route is the same
    exposure as none of them being gated."""
    monkeypatch.setenv(admin_auth.ADMIN_USERS_ENV, "root")
    surface = list(_admin_surface())
    assert len(surface) >= 27  # the count when this went dynamic; growth is fine, shrinkage is a question
    for method, path in surface:
        kwargs = {"json": {}} if method == "post" else {}
        response = getattr(backend_client, method)(path, **kwargs)
        assert response.status_code == 401, f"{method.upper()} {path} allowed an anonymous caller"


def test_an_ordinary_logged_in_user_is_not_an_admin(backend_client, monkeypatch):
    """§7: "Ordinary external clients do not receive unrestricted UQI access to
    internal agents." A valid session is necessary but not sufficient."""
    monkeypatch.setenv(admin_auth.ADMIN_USERS_ENV, "root")
    headers = _register(backend_client, "alice")

    response = backend_client.get("/admin/agents", headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"] == admin_auth.NOT_AN_ADMIN


def test_with_no_admins_configured_the_surface_is_closed_not_open(backend_client, monkeypatch):
    """The default that matters. An auth feature that defaults open is worse
    than none, because it looks protected."""
    monkeypatch.delenv(admin_auth.ADMIN_USERS_ENV, raising=False)
    headers = _register(backend_client, "root")

    response = backend_client.get("/admin/agents", headers=headers)

    assert response.status_code == 403
    assert admin_auth.ADMIN_USERS_ENV in response.json()["detail"]  # says how to fix it


def test_a_configured_admin_is_admitted(backend_client, monkeypatch):
    monkeypatch.setenv(admin_auth.ADMIN_USERS_ENV, "root")
    headers = _register(backend_client, "root")
    assert backend_client.get("/admin/clients", headers=headers).status_code == 200


def test_admin_membership_is_case_and_whitespace_insensitive(backend_client, monkeypatch):
    """Usernames are normalized on registration, so the allowlist must be
    normalized the same way - otherwise a stray space in the environment
    variable silently locks the operator out of their own system."""
    monkeypatch.setenv(admin_auth.ADMIN_USERS_ENV, "  ROOT , someone-else ")
    headers = _register(backend_client, "root")
    assert backend_client.get("/admin/clients", headers=headers).status_code == 200


def test_an_invalid_token_is_rejected_before_the_admin_check(backend_client, monkeypatch):
    monkeypatch.setenv(admin_auth.ADMIN_USERS_ENV, "root")
    response = backend_client.get("/admin/agents", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


def test_admin_list_is_read_at_call_time_not_import_time(monkeypatch):
    """Read per call so a restarted process - or a test - sees the current
    value rather than whatever was set when the module first loaded."""
    monkeypatch.setenv(admin_auth.ADMIN_USERS_ENV, "root")
    assert admin_auth.is_admin("root")
    monkeypatch.setenv(admin_auth.ADMIN_USERS_ENV, "someone-else")
    assert not admin_auth.is_admin("root")


def test_no_admins_configured_means_nobody_is_admin(monkeypatch):
    monkeypatch.delenv(admin_auth.ADMIN_USERS_ENV, raising=False)
    assert admin_auth.admin_usernames() == set()
    assert not admin_auth.is_admin("root")


def test_health_and_auth_routes_stay_open(backend_client):
    """The gate must not swallow the routes a client needs in order to log in
    at all."""
    assert backend_client.get("/health").status_code == 200
    assert backend_client.post(
        "/auth/login", json={"username": "nobody", "password": "wrong"}
    ).status_code == 401  # reachable, and correctly rejecting - not 403
