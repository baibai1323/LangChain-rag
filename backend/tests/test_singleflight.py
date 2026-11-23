"""single-flight 并发合并的单元测试：只执行一次、异常广播、取消隔离。"""

from __future__ import annotations

import asyncio

import pytest

from app.services.singleflight import SingleFlight


@pytest.mark.asyncio
async def test_concurrent_calls_share_one_execution() -> None:
    flight = SingleFlight()
    calls = 0

    async def factory() -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return "value"

    results = await asyncio.gather(*(flight.run("same-key", factory) for _ in range(10)))

    assert results == ["value"] * 10
    assert calls == 1
    assert flight.inflight == 0


@pytest.mark.asyncio
async def test_different_keys_run_independently() -> None:
    flight = SingleFlight()
    calls: list[str] = []

    def make(name: str):
        async def factory() -> str:
            calls.append(name)
            await asyncio.sleep(0.02)
            return name

        return factory

    results = await asyncio.gather(
        flight.run("a", make("a")),
        flight.run("b", make("b")),
    )

    assert results == ["a", "b"]
    assert sorted(calls) == ["a", "b"]


@pytest.mark.asyncio
async def test_error_propagates_to_every_waiter() -> None:
    flight = SingleFlight()
    calls = 0

    async def factory() -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.03)
        raise RuntimeError("检索失败")

    tasks = [asyncio.create_task(flight.run("boom", factory)) for _ in range(3)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    assert calls == 1
    assert all(isinstance(item, RuntimeError) for item in results)
    # 失败后必须摘除，后续请求要能重新执行而不是永远拿到旧异常
    assert flight.inflight == 0


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_cancel_shared_task() -> None:
    flight = SingleFlight()
    started = asyncio.Event()

    async def factory() -> int:
        started.set()
        await asyncio.sleep(0.08)
        return 42

    owner = asyncio.create_task(flight.run("shared", factory))
    await started.wait()

    waiter = asyncio.create_task(flight.run("shared", factory))
    await asyncio.sleep(0.01)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    # 主任务不受影响，结果仍然可用
    assert await owner == 42
    assert flight.inflight == 0
