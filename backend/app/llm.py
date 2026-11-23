from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI

from .config import settings

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None
_http: httpx.AsyncClient | None = None

EMBED_BATCH = 10


def _openai() -> AsyncOpenAI:
    global _client
    if _client is None:
        # 重试统一交给 _with_retry 管：SDK 自己再重试会叠加成「4 次调用 × 3 次内部重试」，
        # 遇到 429 时首字会被拖到十几秒（实测），所以这里只保留 1 次。
        _client = AsyncOpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
            timeout=httpx.Timeout(120.0, connect=10.0),
            max_retries=1,
        )
    return _client


def _httpx() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
    return _http


async def close_llm() -> None:
    global _client, _http
    if _client is not None:
        await _client.close()
        _client = None
    if _http is not None:
        await _http.aclose()
        _http = None


def get_chat_model(streaming: bool = True, temperature: float = 0.2, model: str | None = None) -> ChatOpenAI:
    return ChatOpenAI(
        model=model or settings.qwen_chat_model,
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        temperature=temperature,
        streaming=streaming,
        stream_usage=True,
        timeout=120,
        max_retries=1,
    )


async def _with_retry(
    coro_factory,  # noqa: ANN001
    attempts: int = 4,
    base_delay: float = 0.8,
    deadline: float | None = None,
):
    """带指数退避的重试；`deadline` 是总预算（秒），超预算立即抛出，避免拖死首字。"""
    started = time.monotonic()
    last: Exception | None = None
    for i in range(attempts):
        try:
            return await coro_factory()
        except Exception as exc:  # noqa: BLE001
            last = exc
            logger.warning("qwen call failed (attempt %s/%s): %s", i + 1, attempts, exc)
            elapsed = time.monotonic() - started
            if deadline is not None and elapsed >= deadline:
                break
            if i < attempts - 1:
                delay = base_delay * (2**i)
                if deadline is not None:
                    remaining = deadline - elapsed
                    # 连一次退避都放不下就别再试了，直接把错误抛给调用方降级
                    if delay >= remaining:
                        break
                    delay = min(delay, remaining)
                await asyncio.sleep(delay)
    assert last is not None
    raise last


async def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    if not texts:
        return []
    sem = asyncio.Semaphore(4)
    batches = [list(texts[i : i + EMBED_BATCH]) for i in range(0, len(texts), EMBED_BATCH)]

    async def run(batch: list[str]) -> list[list[float]]:
        async with sem:

            async def call():
                resp = await _openai().embeddings.create(
                    model=settings.qwen_embed_model,
                    input=batch,
                    dimensions=settings.qwen_embed_dim,
                )
                return [item.embedding for item in resp.data]

            return await _with_retry(call)

    results = await asyncio.gather(*(run(b) for b in batches))
    out: list[list[float]] = []
    for r in results:
        out.extend(r)
    return out


async def embed_query(text: str) -> list[float]:
    vectors = await embed_texts([text])
    return vectors[0]


async def rerank(query: str, documents: Sequence[str], top_n: int | None = None) -> list[tuple[int, float]]:
    """返回 (原始下标, 相关性分数) 列表，按分数降序。"""
    if not documents:
        return []
    payload = {
        "model": settings.qwen_rerank_model,
        "input": {"query": query, "documents": list(documents)},
        "parameters": {"top_n": top_n or len(documents), "return_documents": False},
    }
    headers = {"Authorization": f"Bearer {settings.dashscope_api_key}", "Content-Type": "application/json"}

    async def call():
        resp = await _httpx().post(settings.qwen_rerank_url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()

    data = await _with_retry(call, attempts=3)
    results = data.get("output", {}).get("results", [])
    pairs = [(int(r["index"]), float(r["relevance_score"])) for r in results]
    pairs.sort(key=lambda x: x[1], reverse=True)
    return pairs


async def fast_chat(
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 256,
    attempts: int = 2,
    timeout_s: float = 4.0,
) -> tuple[str, dict[str, int]]:
    """非流式的小任务（改写、标题）。

    默认只给 4 秒预算、2 次尝试：这类调用失败完全可以降级（用原问题），
    不值得为了它把用户的首字延迟拖到十几秒。
    """

    async def call():
        return await _openai().chat.completions.create(
            model=model or settings.qwen_fast_model,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async with asyncio.timeout(timeout_s):
        resp = await _with_retry(
            call, attempts=attempts, base_delay=0.3, deadline=timeout_s
        )
    usage = {
        "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
        "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
    }
    return (resp.choices[0].message.content or "").strip(), usage


async def stream_answer(
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.2,
) -> AsyncIterator[dict[str, Any]]:
    """基于 LangChain ChatOpenAI 的流式输出，逐块产出 delta / usage。"""
    llm = get_chat_model(streaming=True, temperature=temperature, model=model)
    started = time.perf_counter()
    first = True
    usage: dict[str, int] = {}
    async for chunk in llm.astream(messages):  # type: ignore[arg-type]
        text = chunk.content if isinstance(chunk.content, str) else ""
        if text:
            if first:
                first = False
                yield {"type": "first_token", "ms": int((time.perf_counter() - started) * 1000)}
            yield {"type": "delta", "text": text}
        meta = getattr(chunk, "usage_metadata", None)
        if meta:
            usage = {
                "prompt_tokens": int(meta.get("input_tokens", 0)),
                "completion_tokens": int(meta.get("output_tokens", 0)),
            }
    yield {"type": "usage", "usage": usage}
