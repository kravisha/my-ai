"""Regression tests for backend/main.py's auth routes: register/login/logout
/me over HTTP. Mirrors vibe-agent's own auth route shape (token in the JSON
body, Authorization: Bearer <token> on protected routes) but against
My AI's JSON-file-backed UserStore/SessionStore instead of SQLAlchemy."""


def test_register_returns_a_token(backend_client):
    response = backend_client.post("/auth/register", json={"username": "alice", "password": "hunter2"})
    assert response.status_code == 200
    assert "token" in response.json()


def test_register_duplicate_username_returns_400(backend_client):
    backend_client.post("/auth/register", json={"username": "alice", "password": "hunter2"})
    response = backend_client.post("/auth/register", json={"username": "alice", "password": "different"})
    assert response.status_code == 400


def test_login_with_correct_credentials_returns_a_token(backend_client):
    backend_client.post("/auth/register", json={"username": "alice", "password": "hunter2"})
    response = backend_client.post("/auth/login", json={"username": "alice", "password": "hunter2"})
    assert response.status_code == 200
    assert "token" in response.json()


def test_login_with_wrong_password_returns_401(backend_client):
    backend_client.post("/auth/register", json={"username": "alice", "password": "hunter2"})
    response = backend_client.post("/auth/login", json={"username": "alice", "password": "wrong"})
    assert response.status_code == 401


def test_login_nonexistent_user_returns_401_not_404(backend_client):
    """No user-enumeration signal - unknown username and wrong password look identical."""
    response = backend_client.post("/auth/login", json={"username": "ghost", "password": "anything"})
    assert response.status_code == 401


def test_me_with_valid_token_returns_username(backend_client):
    token = backend_client.post("/auth/register", json={"username": "alice", "password": "hunter2"}).json()["token"]
    response = backend_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["username"] == "alice"


def test_me_with_no_token_returns_401(backend_client):
    response = backend_client.get("/auth/me")
    assert response.status_code == 401


def test_me_with_invalid_token_returns_401(backend_client):
    response = backend_client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


def test_logout_revokes_the_token(backend_client):
    token = backend_client.post("/auth/register", json={"username": "alice", "password": "hunter2"}).json()["token"]
    logout_response = backend_client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout_response.status_code == 200

    me_response = backend_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_response.status_code == 401


def test_two_clients_can_be_logged_in_as_different_users_at_once(backend_client):
    """The core new capability a real server enables: two independent
    tokens, each resolving to their own account, at the same time."""
    token_a = backend_client.post("/auth/register", json={"username": "alice", "password": "pw1"}).json()["token"]
    token_b = backend_client.post("/auth/register", json={"username": "bob", "password": "pw2"}).json()["token"]

    me_a = backend_client.get("/auth/me", headers={"Authorization": f"Bearer {token_a}"})
    me_b = backend_client.get("/auth/me", headers={"Authorization": f"Bearer {token_b}"})

    assert me_a.json()["username"] == "alice"
    assert me_b.json()["username"] == "bob"
