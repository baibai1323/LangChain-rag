from __future__ import annotations

from fastapi.testclient import TestClient


def test_normal_user_cannot_create_kb(client: TestClient, user_headers: dict[str, str]) -> None:
    resp = client.post("/api/kbs", headers=user_headers, json={"name": "越权库"})
    assert resp.status_code == 403


def test_admin_creates_kb_and_sees_it_in_list(client: TestClient, admin_headers: dict[str, str]) -> None:
    created = client.post("/api/kbs", headers=admin_headers, json={"name": "新品库", "description": "上新"})
    assert created.status_code == 201, created.text
    kb = created.json()
    assert kb["name"] == "新品库"
    assert kb["document_count"] == 0

    listing = client.get("/api/kbs", headers=admin_headers).json()
    names = {item["name"] for item in listing}
    assert {"测试知识库", "新品库"} <= names


def test_admin_cannot_create_duplicate_kb_name(client: TestClient, admin_headers: dict[str, str]) -> None:
    resp = client.post("/api/kbs", headers=admin_headers, json={"name": "测试知识库"})
    assert resp.status_code == 409


def test_user_can_read_kb_list_but_not_stats(client: TestClient, user_headers: dict[str, str]) -> None:
    assert client.get("/api/kbs", headers=user_headers).status_code == 200
    assert client.get("/api/kbs/kbtest1/stats", headers=user_headers).status_code == 403


def test_kb_stats_returns_zero_counts_for_empty_kb(client: TestClient, admin_headers: dict[str, str]) -> None:
    resp = client.get("/api/kbs/kbtest1/stats", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json() == {
        "kb_id": "kbtest1",
        "documents": 0,
        "ready_documents": 0,
        "chunks": 0,
        "tokens": 0,
    }


def test_missing_kb_returns_404(client: TestClient, admin_headers: dict[str, str]) -> None:
    assert client.get("/api/kbs/not-exist", headers=admin_headers).status_code == 404


def test_unauthenticated_kb_list_returns_401(client: TestClient) -> None:
    assert client.get("/api/kbs").status_code == 401
