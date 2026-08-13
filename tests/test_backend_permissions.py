"""Regression tests for GET /permissions, POST /permissions/grant, POST
/permissions/revoke - thin wiring tests, since PermissionManager itself is
already covered by tests/test_permissions.py; these mainly confirm auth
enforcement and route shape."""


def _auth_header(backend_client, username="alice"):
    token = backend_client.post("/auth/register", json={"username": username, "password": "hunter2"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_list_permissions_starts_not_granted(backend_client):
    headers = _auth_header(backend_client)
    response = backend_client.get("/permissions", headers=headers)
    assert response.status_code == 200
    assert response.json()["portfolio"] is False


def test_grant_then_list_shows_granted(backend_client):
    headers = _auth_header(backend_client)
    grant_response = backend_client.post("/permissions/grant", json={"resource": "portfolio"}, headers=headers)
    assert grant_response.status_code == 200
    assert backend_client.get("/permissions", headers=headers).json()["portfolio"] is True


def test_revoke_after_grant_shows_not_granted(backend_client):
    headers = _auth_header(backend_client)
    backend_client.post("/permissions/grant", json={"resource": "portfolio"}, headers=headers)
    backend_client.post("/permissions/revoke", json={"resource": "portfolio"}, headers=headers)
    assert backend_client.get("/permissions", headers=headers).json()["portfolio"] is False


def test_grant_unknown_resource_returns_400(backend_client):
    headers = _auth_header(backend_client)
    response = backend_client.post("/permissions/grant", json={"resource": "not_a_real_resource"}, headers=headers)
    assert response.status_code == 400


def test_permissions_routes_require_authentication(backend_client):
    assert backend_client.get("/permissions").status_code == 401
    assert backend_client.post("/permissions/grant", json={"resource": "portfolio"}).status_code == 401


def test_two_users_permissions_are_isolated(backend_client):
    headers_a = _auth_header(backend_client, "alice")
    headers_b = _auth_header(backend_client, "bob")

    backend_client.post("/permissions/grant", json={"resource": "portfolio"}, headers=headers_a)

    assert backend_client.get("/permissions", headers=headers_a).json()["portfolio"] is True
    assert backend_client.get("/permissions", headers=headers_b).json()["portfolio"] is False
