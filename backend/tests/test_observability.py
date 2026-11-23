"""请求追踪与运行时指标的测试：响应头、分位数计算、管理员权限。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.observability import MetricsRegistry, metrics, normalize_path


def test_request_headers_are_injected(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert len(response.headers["x-request-id"]) == 12
    assert float(response.headers["x-response-time-ms"]) >= 0


def test_client_supplied_request_id_is_kept(client: TestClient) -> None:
    response = client.get("/api/health", headers={"X-Request-ID": "trace-abc"})

    assert response.headers["x-request-id"] == "trace-abc"


def test_metrics_endpoint_requires_admin(client: TestClient, user_headers: dict) -> None:
    assert client.get("/api/admin/metrics").status_code == 401
    assert client.get("/api/admin/metrics", headers=user_headers).status_code == 403


def test_metrics_endpoint_returns_snapshot(
    client: TestClient, admin_headers: dict
) -> None:
    metrics.reset()
    client.get("/api/health")

    body = client.get("/api/admin/metrics", headers=admin_headers).json()

    assert body["requests"] >= 1
    assert set(body["latency_ms"]) == {"avg", "p50", "p95", "max"}
    assert isinstance(body["top_paths"], list)


def test_normalize_path_collapses_ids() -> None:
    assert normalize_path("/api/kbs/0123456789abcdef0123456789abcdef") == "/api/kbs/{id}"
    assert normalize_path("/api/documents/42/chunks") == "/api/documents/{id}/chunks"
    assert normalize_path("/api/health") == "/api/health"


def test_snapshot_percentiles_and_error_rate() -> None:
    registry = MetricsRegistry()
    for index in range(1, 101):
        registry.record("GET", "/api/x", 200, float(index))
    registry.record("GET", "/api/x", 500, 1000.0)

    snapshot = registry.snapshot()

    assert snapshot["requests"] == 101
    assert snapshot["errors"] == 1
    # 最近秩法：101 个样本的 p50 是第 51 个（值 51），p95 是第 96 个（值 96）
    assert snapshot["latency_ms"]["p50"] == 51.0
    assert snapshot["latency_ms"]["p95"] == 96.0
    assert snapshot["latency_ms"]["max"] == 1000.0
    assert snapshot["status"] == {"200": 100, "500": 1}


def test_reset_clears_samples() -> None:
    metrics.record("GET", "/api/x", 200, 10.0)
    metrics.reset()

    snapshot = metrics.snapshot()

    assert snapshot["samples"] == 0
    assert snapshot["errors"] == 0
    assert snapshot["top_paths"] == []
