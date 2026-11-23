from __future__ import annotations

from fastapi.testclient import TestClient


def test_create_and_list_conversation(client: TestClient, user_headers: dict[str, str]) -> None:
    created = client.post("/api/conversations", headers=user_headers, json={"kb_id": "kbtest1"})
    assert created.status_code == 201, created.text
    conv = created.json()
    assert conv["title"] == "新会话"
    assert conv["message_count"] == 0

    listing = client.get("/api/conversations", headers=user_headers).json()
    assert [item["id"] for item in listing] == [conv["id"]]


def test_conversation_is_invisible_to_other_users(
    client: TestClient, user_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    conv = client.post("/api/conversations", headers=user_headers, json={"kb_id": "kbtest1"}).json()
    assert client.get(f"/api/conversations/{conv['id']}", headers=admin_headers).status_code == 404
    assert client.get("/api/conversations", headers=admin_headers).json() == []


def test_rename_and_pin_conversation(client: TestClient, user_headers: dict[str, str]) -> None:
    conv = client.post("/api/conversations", headers=user_headers, json={"kb_id": "kbtest1"}).json()
    resp = client.patch(
        f"/api/conversations/{conv['id']}",
        headers=user_headers,
        json={"title": "X50 咨询", "is_pinned": 1},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "X50 咨询"
    assert body["is_pinned"] == 1

    listing = client.get("/api/conversations", headers=user_headers).json()
    assert listing[0]["title"] == "X50 咨询"
    assert listing[0]["is_pinned"] == 1


def test_blank_title_keeps_previous_title(client: TestClient, user_headers: dict[str, str]) -> None:
    conv = client.post(
        "/api/conversations", headers=user_headers, json={"kb_id": "kbtest1", "title": "原标题"}
    ).json()
    resp = client.patch(
        f"/api/conversations/{conv['id']}", headers=user_headers, json={"title": "   "}
    )
    assert resp.json()["title"] == "原标题"


def test_messages_of_new_conversation_are_empty(client: TestClient, user_headers: dict[str, str]) -> None:
    conv = client.post("/api/conversations", headers=user_headers, json={"kb_id": "kbtest1"}).json()
    resp = client.get(f"/api/conversations/{conv['id']}/messages", headers=user_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_conversation_for_missing_kb_returns_404(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    resp = client.post("/api/conversations", headers=user_headers, json={"kb_id": "missing"})
    assert resp.status_code == 404


def test_delete_conversation_removes_it(client: TestClient, user_headers: dict[str, str]) -> None:
    conv = client.post("/api/conversations", headers=user_headers, json={"kb_id": "kbtest1"}).json()
    assert client.delete(f"/api/conversations/{conv['id']}", headers=user_headers).status_code == 200
    assert client.get(f"/api/conversations/{conv['id']}", headers=user_headers).status_code == 404
