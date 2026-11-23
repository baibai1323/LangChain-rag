"""同一问题的并发合并（single-flight）。

场景：多个用户同时问同一个问题，或同一用户连点两次发送。此时「改写 + 向量化 +
BM25 + 重排」会被重复执行 N 次，既费 Embedding 配额又抬高首字延迟。

做法：以「知识库 + 归一化问题」为 key，第一个请求真正执行检索，后来者等待同一个
Future；结果只算一次、所有等待者共享。注意两点：

1. 用 `asyncio.shield` 等待，任一等待者取消（关页面）不会连带取消共享任务；
2. 任务结束后从表里摘除，异常会原样抛给所有等待者，不做静默降级。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")


class SingleFlight:
    """按 key 合并并发调用的极简实现。"""

    def __init__(self) -> None:
        self._inflight: dict[str, asyncio.Future[Any]] = {}

    @property
    def inflight(self) -> int:
        """当前正在执行的任务数，监控与测试用。"""
        return len(self._inflight)

    async def run(self, key: str, factory: Callable[[], Awaitable[T]]) -> T:
        """执行或复用同 key 的在途任务。"""
        existing = self._inflight.get(key)
        if existing is not None:
            return await asyncio.shield(existing)  # type: ignore[return-value]

        future: asyncio.Future[T] = asyncio.ensure_future(factory())
        self._inflight[key] = future

        def _cleanup(_: asyncio.Future[T]) -> None:
            # 只有「自己是登记者」时才摘除，避免误删后来者新建的同 key 任务
            if self._inflight.get(key) is future:
                self._inflight.pop(key, None)

        future.add_done_callback(_cleanup)
        return await asyncio.shield(future)


# 检索合并：chat 路由与检索测试共用
retrieval_flight = SingleFlight()

# 向量化合并：同一句问题的 embedding 只请求一次
embedding_flight = SingleFlight()
