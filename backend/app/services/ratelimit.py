from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, status

from ..config import settings


class RateLimiter:
    """进程内滑动窗口限流（单机 SQLite 部署足够；多实例可替换为 Redis）。"""

    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        bucket = self._hits[key]
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()
        if len(bucket) >= self.limit:
            retry_after = int(self.window - (now - bucket[0])) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"请求过于频繁，请 {retry_after} 秒后再试",
                headers={"Retry-After": str(retry_after)},
            )
        bucket.append(now)


chat_limiter = RateLimiter(settings.chat_rate_limit_per_minute)
auth_limiter = RateLimiter(10)
