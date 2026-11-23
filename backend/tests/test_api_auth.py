from __future__ import annotations

from fastapi.testclient import TestClient

ADMIN_PASSWORD = "admin123456"
USER_PASSWORD = "user123456"


def test_register_returns_tokens_and_user(client: TestClient) -> None:
    resp = client.post("/api/auth/register", json={"username": "newbie", "password": "pass123456"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["username"] == "newbie"
    assert body["user"]["role"] == "user"
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200


def test_register_duplicate_username_is_case_insensitive(client: TestClient) -> None:
    resp = client.post("/api/auth/register", json={"username": "ALICE", "password": "pass123456"})
    assert resp.status_code == 409


def test_login_wrong_password_returns_401(client: TestClient) -> None:
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "wrong-pass"})
    assert resp.status_code == 401


def test_me_without_token_returns_401(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401


def test_refresh_token_returns_new_access_token(client: TestClient) -> None:
    login = client.post("/api/auth/login", json={"username": "alice", "password": USER_PASSWORD})
    refresh_token = login.json()["refresh_token"]
    resp = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    assert resp.json()["access_token"]


def test_access_token_cannot_be_used_as_refresh_token(client: TestClient) -> None:
    login = client.post("/api/auth/login", json={"username": "alice", "password": USER_PASSWORD})
    access_token = login.json()["access_token"]
    resp = client.post("/api/auth/refresh", json={"refresh_token": access_token})
    assert resp.status_code == 401


def test_change_password_invalidates_old_access_token(client: TestClient, user_headers: dict[str, str]) -> None:
    resp = client.post(
        "/api/auth/password",
        headers=user_headers,
        json={"old_password": USER_PASSWORD, "new_password": "newpass123456"},
    )
    assert resp.status_code == 200, resp.text
    # 旧 token 的 tv 已过期
    assert client.get("/api/auth/me", headers=user_headers).status_code == 401
    # 新 token 可用，新密码可登录
    assert client.post(
        "/api/auth/login", json={"username": "alice", "password": "newpass123456"}
    ).status_code == 200


def test_change_password_rejects_wrong_old_password(client: TestClient, user_headers: dict[str, str]) -> None:
    resp = client.post(
        "/api/auth/password",
        headers=user_headers,
        json={"old_password": "bad-old", "new_password": "newpass123456"},
    )
    assert resp.status_code == 400


def test_admin_can_login_with_seeded_password(client: TestClient) -> None:
    resp = client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "admin"
