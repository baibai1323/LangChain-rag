"""文档接口的校验分支：类型、空文件、权限、404。"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_upload_requires_admin(client: TestClient, user_headers: dict[str, str]) -> None:
    resp = client.post(
        "/api/kbs/kbtest1/documents",
        headers=user_headers,
        files={"file": ("a.txt", b"hello world", "text/plain")},
    )
    assert resp.status_code == 403


def test_upload_unknown_kb_returns_404(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    resp = client.post(
        "/api/kbs/no-such-kb/documents",
        headers=admin_headers,
        files={"file": ("a.txt", b"hello world", "text/plain")},
    )
    assert resp.status_code == 404


def test_upload_rejects_unsupported_type(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    resp = client.post(
        "/api/kbs/kbtest1/documents",
        headers=admin_headers,
        files={"file": ("evil.exe", b"MZ....", "application/octet-stream")},
    )
    assert resp.status_code == 400
    assert "不支持的文件类型" in resp.json()["detail"]


def test_upload_rejects_empty_file(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    resp = client.post(
        "/api/kbs/kbtest1/documents",
        headers=admin_headers,
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert resp.status_code == 400


def test_upload_without_file_is_422(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    resp = client.post("/api/kbs/kbtest1/documents", headers=admin_headers)
    assert resp.status_code == 422


def test_list_documents_requires_admin(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    assert client.get("/api/kbs/kbtest1/documents", headers=user_headers).status_code == 403


def test_list_documents_empty(client: TestClient, admin_headers: dict[str, str]) -> None:
    resp = client.get("/api/kbs/kbtest1/documents", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_chunks_of_unknown_document_returns_404(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    assert client.get("/api/documents/nope/chunks", headers=admin_headers).status_code == 404


def test_task_of_unknown_id_returns_404(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    assert client.get("/api/tasks/nope", headers=admin_headers).status_code == 404
