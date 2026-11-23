"""改写降级与重试预算的测试：限流时不能把首字拖死。"""

from __future__ import annotations

import time

import pytest

from app.llm import _with_retry
from app.services import chat as chat_service


@pytest.fixture(autouse=True)
def _clean_cooldown():
    chat_service.reset_rewrite_cooldown()
    yield
    chat_service.reset_rewrite_cooldown()


@pytest.mark.asyncio
async def test_rewrite_skips_llm_without_history(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    async def fake_fast_chat(*args, **kwargs):  # noqa: ANN002, ANN003
        nonlocal called
        called = True
        return "改写后的问题", {}

    monkeypatch.setattr(chat_service, "fast_chat", fake_fast_chat)

    assert await chat_service.rewrite_question("原问题", []) == "原问题"
    assert called is False


def test_needs_rewrite_only_for_context_dependent_questions() -> None:
    """自包含的长问题不该再花一次模型调用。"""
    assert chat_service.needs_rewrite("云帆 Pro 14 的屏幕参数和电池续航怎么样？") is False
    assert chat_service.needs_rewrite("它的保修期多久？") is True
    assert chat_service.needs_rewrite("多少钱") is True


@pytest.mark.asyncio
async def test_rewrite_failure_opens_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def boom(*args, **kwargs):  # noqa: ANN002, ANN003
        nonlocal calls
        calls += 1
        raise RuntimeError("429 rate limit")

    monkeypatch.setattr(chat_service, "fast_chat", boom)
    history = [{"role": "user", "content": "上一轮问题"}]

    assert await chat_service.rewrite_question("问题一", history) == "问题一"
    # 冷却期内第二次直接返回原问题，不再触发模型调用
    assert await chat_service.rewrite_question("问题二", history) == "问题二"
    assert calls == 1


@pytest.mark.asyncio
async def test_rewrite_accepts_clean_result(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fast_chat(*args, **kwargs):  # noqa: ANN002, ANN003
        return "“星耀 X50 的保修政策”", {}

    monkeypatch.setattr(chat_service, "fast_chat", fake_fast_chat)

    result = await chat_service.rewrite_question(
        "它保修多久", [{"role": "user", "content": "在看 X50"}]
    )
    assert result == "星耀 X50 的保修政策"


@pytest.mark.asyncio
async def test_rewrite_rejects_too_long_result(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fast_chat(*args, **kwargs):  # noqa: ANN002, ANN003
        return "很长" * 200, {}

    monkeypatch.setattr(chat_service, "fast_chat", fake_fast_chat)

    result = await chat_service.rewrite_question(
        "原问题", [{"role": "user", "content": "上下文"}]
    )
    assert result == "原问题"


@pytest.mark.asyncio
async def test_with_retry_stops_at_attempt_limit() -> None:
    calls = 0

    async def always_fail() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await _with_retry(always_fail, attempts=3, base_delay=0.0)

    assert calls == 3


@pytest.mark.asyncio
async def test_with_retry_respects_deadline() -> None:
    calls = 0

    async def always_fail() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")

    started = time.monotonic()
    with pytest.raises(RuntimeError):
        await _with_retry(always_fail, attempts=10, base_delay=2.0, deadline=0.01)

    assert calls == 1
    assert time.monotonic() - started < 1.0
