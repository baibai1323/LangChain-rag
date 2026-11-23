"""进程内轻量指标与请求追踪。

为什么不用 Prometheus：本项目是单进程部署，引一个 exporter 只会让依赖变重；
面试/答辩时更需要的是「能拿出数字」，所以这里用固定窗口保存最近 N 次请求的
延迟与状态码，`/api/admin/metrics` 直接返回 p50/p95、错误率和热点路径。

注意：指标只活在进程内存里，重启即清空；多进程部署时应换成 Prometheus/OpenTelemetry。
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import Counter, deque
from uuid import uuid4

from starlette.datastructures import Headers

# 只保留最近 2000 次请求，内存占用可忽略，也避免长跑后分位数被历史数据拖平
MAX_SAMPLES = 2000

# 把路径里的 uuid / 数字 id 归一化，避免 /api/kbs/abc 和 /api/kbs/def 各占一个桶
_ID_PATTERN = re.compile(r"/(?:[0-9a-fA-F]{16,}|\d+)(?=/|$)")


def normalize_path(path: str) -> str:
    """把动态 id 段替换为 {id}，让指标按路由聚合而不是按实例聚合。"""
    return _ID_PATTERN.sub("/{id}", path)


class MetricsRegistry:
    """线程安全的请求指标收集器。"""

    def __init__(self, max_samples: int = MAX_SAMPLES) -> None:
        self._durations: deque[float] = deque(maxlen=max_samples)
        self._paths: Counter[str] = Counter()
        self._path_ms: Counter[str] = Counter()
        self._errors: Counter[str] = Counter()
        self._status: Counter[int] = Counter()
        self._lock = threading.Lock()
        self._started = time.time()

    def record(self, method: str, path: str, status: int, duration_ms: float) -> None:
        """记录一次请求。路径先归一化，5xx 单独计数。"""
        key = f"{method} {normalize_path(path)}"
        with self._lock:
            self._durations.append(duration_ms)
            self._paths[key] += 1
            self._path_ms[key] += duration_ms
            self._status[status] += 1
            if status >= 500:
                self._errors[key] += 1

    @staticmethod
    def _percentile(sorted_values: list[float], ratio: float) -> float:
        """最近秩法取分位数；样本为空时返回 0。"""
        if not sorted_values:
            return 0.0
        index = min(len(sorted_values) - 1, int(round(ratio * (len(sorted_values) - 1))))
        return round(sorted_values[index], 2)

    def snapshot(self) -> dict:
        """返回可直接 JSON 序列化的指标快照。"""
        with self._lock:
            durations = sorted(self._durations)
            paths = self._paths.most_common(10)
            total = len(durations)
            errors = sum(self._errors.values())
            payload = {
                "uptime_seconds": round(time.time() - self._started, 1),
                "samples": total,
                "requests": sum(self._paths.values()),
                "errors": errors,
                "error_rate": round(errors / total, 4) if total else 0.0,
                "latency_ms": {
                    "avg": round(sum(durations) / total, 2) if total else 0.0,
                    "p50": self._percentile(durations, 0.50),
                    "p95": self._percentile(durations, 0.95),
                    "max": round(durations[-1], 2) if total else 0.0,
                },
                "status": {str(code): count for code, count in sorted(self._status.items())},
                "top_paths": [
                    {
                        "path": path,
                        "count": count,
                        "avg_ms": round(self._path_ms[path] / count, 2),
                    }
                    for path, count in paths
                ],
            }
        return payload

    def reset(self) -> None:
        """清空样本，测试与压测前用。"""
        with self._lock:
            self._durations.clear()
            self._paths.clear()
            self._path_ms.clear()
            self._errors.clear()
            self._status.clear()
            self._started = time.time()


# 全局单例：main.py 的中间件与 admin 路由共用
metrics = MetricsRegistry()

logger = logging.getLogger("app.request")


class RequestContextMiddleware:
    """纯 ASGI 中间件：写 request id、响应耗时和访问日志。

    刻意不用 BaseHTTPMiddleware：后者会包一层 anyio 任务组，长连接的 SSE
    容易出现「客户端断开后生成器没被取消」的问题；直接包 ASGI 消息更稳。
    """

    def __init__(self, app) -> None:  # noqa: ANN001 - ASGI app 类型由 starlette 提供
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = Headers(scope=scope).get("x-request-id") or uuid4().hex[:12]
        path = scope.get("path", "")
        method = scope.get("method", "")
        started = time.perf_counter()
        status_code = {"code": 500}

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                status_code["code"] = message["status"]
                elapsed_ms = (time.perf_counter() - started) * 1000
                headers = [
                    (key, value)
                    for key, value in (message.get("headers") or [])
                    if key.lower() not in (b"x-request-id", b"x-response-time-ms")
                ]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                headers.append((b"x-response-time-ms", f"{elapsed_ms:.1f}".encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            total_ms = (time.perf_counter() - started) * 1000
            if not path.startswith(("/assets/", "/favicon")):
                status = status_code["code"]
                metrics.record(method, path, status, total_ms)
                logger.info(
                    "%s %s %s %.1fms rid=%s", method, path, status, total_ms, request_id
                )

