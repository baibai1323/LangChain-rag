"""管理端接口：统计、趋势、用户管理、审计与模型调用记录。"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _auth(client: TestClient, username: str, password: str) -> dict[str, str]:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_stats_requires_admin(client: TestClient, user_headers: dict[str, str]) -> None:
    resp = client.get("/api/admin/stats", headers=user_headers)
    assert resp.status_code == 403


def test_stats_counts_seed_data(client: TestClient, admin_headers: dict[str, str]) -> None:
    resp = client.get("/api/admin/stats", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["users"] == 2
    assert data["knowledge_bases"] == 1
    assert data["documents"] == 0
    assert data["chunks"] == 0
    assert data["messages"] == 0
    assert data["llm_calls_today"] == 0
    assert data["avg_latency_ms"] == 0
    assert data["feedback_positive"] == 0


def test_series_returns_seven_days(client: TestClient, admin_headers: dict[str, str]) -> None:
    resp = client.get("/api/admin/series", headers=admin_headers)
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 7
    assert [row["date"] for row in rows] == sorted(row["date"] for row in rows)
    assert all(row["messages"] == 0 for row in rows)


def test_users_list_includes_conversation_count(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    resp = client.get("/api/admin/users", headers=admin_headers)
    assert resp.status_code == 200
    users = {item["username"]: item for item in resp.json()}
    assert set(users) == {"admin", "alice"}
    assert users["admin"]["role"] == "admin"
    assert users["alice"]["conversation_count"] == 0
    assert users["alice"]["status"] == "active"


def test_update_user_rejects_self(client: TestClient, admin_headers: dict[str, str]) -> None:
    me = client.get("/api/auth/me", headers=admin_headers).json()
    resp = client.patch(
        f"/api/admin/users/{me['id']}", json={"role": "user"}, headers=admin_headers
    )
    assert resp.status_code == 400


def test_update_user_not_found(client: TestClient, admin_headers: dict[str, str]) -> None:
    resp = client.patch(
        "/api/admin/users/not-exists", json={"role": "user"}, headers=admin_headers
    )
    assert resp.status_code == 404


def test_update_user_role_and_status(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    users = {
        item["username"]: item
        for item in client.get("/api/admin/users", headers=admin_headers).json()
    }
    alice = users["alice"]
    alice_token = _auth(client, "alice", "user123456")

    resp = client.patch(
        f"/api/admin/users/{alice['id']}",
        json={"role": "admin", "status": "disabled"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "admin"
    assert body["status"] == "disabled"

    # status 变更会让 token_version 失效，旧 token 立即 401
    assert client.get("/api/auth/me", headers=alice_token).status_code == 401


def test_builtin_admin_cannot_be_modified(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    users = {
        item["username"]: item
        for item in client.get("/api/admin/users", headers=admin_headers).json()
    }
    alice = users["alice"]

    # 把 alice 提成管理员，用她的身份去改内置 admin
    client.patch(
        f"/api/admin/users/{alice['id']}", json={"role": "admin"}, headers=admin_headers
    )
    alice_headers = _auth(client, "alice", "user123456")
    admin = users["admin"]
    assert admin["id"] == client.get("/api/auth/me", headers=admin_headers).json()["id"]
    resp = client.patch(
        f"/api/admin/users/{admin['id']}", json={"role": "user"}, headers=alice_headers
    )
    assert resp.status_code == 400


def test_audit_logs_newest_first_and_limited(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    resp = client.get("/api/admin/audit-logs?limit=500", headers=admin_headers)
    assert resp.status_code == 200
    logs = resp.json()
    assert logs, "登录应写入审计日志"
    assert len(logs) <= 200
    assert logs[0]["action"]


def test_llm_calls_and_cache(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    calls = client.get("/api/admin/llm-calls", headers=admin_headers)
    assert calls.status_code == 200
    assert calls.json() == []

    cache = client.get("/api/admin/cache", headers=admin_headers)
    assert cache.status_code == 200
    assert isinstance(cache.json(), dict)


def test_admin_endpoints_require_auth(client: TestClient) -> None:
    assert client.get("/api/admin/stats").status_code == 401
    assert client.get("/api/admin/users").status_code == 401
