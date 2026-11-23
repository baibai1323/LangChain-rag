from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services import ratelimit as ratelimit_module
from app.services.ratelimit import RateLimiter


def test_allows_up_to_limit_then_raises_429(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 1000.0
    monkeypatch.setattr(ratelimit_module.time, "monotonic", lambda: now)
    limiter = RateLimiter(limit=3, window_seconds=60)
    for _ in range(3):
        limiter.check("ip")
    with pytest.raises(HTTPException) as excinfo:
        limiter.check("ip")
    assert excinfo.value.status_code == 429
    assert excinfo.value.headers["Retry-After"] == "61"


def test_window_slides_after_time_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 1000.0
    monkeypatch.setattr(ratelimit_module.time, "monotonic", lambda: now)
    limiter = RateLimiter(limit=1, window_seconds=60)
    limiter.check("ip")
    now += 61
    limiter.check("ip")  # 不应抛 429


def test_keys_are_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ratelimit_module.time, "monotonic", lambda: 1000.0)
    limiter = RateLimiter(limit=1, window_seconds=60)
    limiter.check("ip-a")
    limiter.check("ip-b")  # 不同 key 互不影响
