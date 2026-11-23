from __future__ import annotations

import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..llm import fast_chat
from ..models import Message
from ..rag.prompt import REWRITE_PROMPT, TITLE_PROMPT

logger = logging.getLogger(__name__)

# 改写是「锦上添花」：一旦 qwen-turbo 被限流，冷却 60 秒内直接用原问题，
# 避免每一轮都先交 3 秒重试学费，首字延迟可以稳定下来。
REWRITE_COOLDOWN_S = 60.0
_rewrite_blocked_until = 0.0


def reset_rewrite_cooldown() -> None:
    """清空改写冷却，测试和长连接复用场景用。"""
    global _rewrite_blocked_until
    _rewrite_blocked_until = 0.0


async def load_history(db: AsyncSession, conversation_id: str, limit: int = 8) -> list[dict[str, str]]:
    rows = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.status == "done")
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    messages = [{"role": m.role, "content": m.content} for m in reversed(rows) if m.content.strip()]
    return messages


_REWRITE_HINTS = (
    "它",
    "这个",
    "那个",
    "这些",
    "那些",
    "该",
    "这款",
    "那款",
    "上面",
    "刚才",
    "之前",
    "还有",
    "呢",
)


def needs_rewrite(question: str) -> bool:
    """判断问题是否依赖上下文：只有带指代/省略的短问句才值得多花一次模型调用。"""
    text = question.strip()
    if len(text) >= 12 and not any(hint in text for hint in _REWRITE_HINTS):
        return False
    return any(hint in text for hint in _REWRITE_HINTS) or len(text) <= 8


async def rewrite_question(question: str, history: list[dict[str, str]]) -> str:
    global _rewrite_blocked_until

    if not history:
        return question
    # 自包含的问题直接跳过，省一次调用、也避开高并发下的 429
    if not needs_rewrite(question):
        return question
    # 上一轮刚被限流：直接跳过，别让每个请求都先等一轮重试
    if time.monotonic() < _rewrite_blocked_until:
        return question

    snippet = "\n".join(f"{m['role']}: {m['content'][:200]}" for m in history[-4:])
    try:
        rewritten, _ = await fast_chat(
            [
                {"role": "system", "content": REWRITE_PROMPT},
                {"role": "user", "content": f"对话历史：\n{snippet}\n\n最新问题：{question}"},
            ],
            max_tokens=128,
            attempts=1,
            timeout_s=3.0,
        )
        rewritten = rewritten.strip().strip('"').strip("“”")
        return rewritten if 2 <= len(rewritten) <= 200 else question
    except Exception as exc:  # noqa: BLE001  改写失败时使用原问题
        _rewrite_blocked_until = time.monotonic() + REWRITE_COOLDOWN_S
        logger.warning(
            "查询改写失败，%ss 内跳过改写并使用原问题: %s", int(REWRITE_COOLDOWN_S), exc
        )
        return question


async def make_title(question: str) -> str:
    fallback = question.strip()[:20] or "新会话"
    try:
        title, _ = await fast_chat(
            [
                {"role": "system", "content": TITLE_PROMPT},
                {"role": "user", "content": question[:300]},
            ],
            max_tokens=32,
            attempts=1,
            timeout_s=2.5,
        )
        title = title.strip().strip('"').strip("“”").replace("\n", " ")
        return title[:20] or fallback
    except Exception:  # noqa: BLE001
        return fallback


def now_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def usage_dict(usage: dict[str, int] | None) -> tuple[int, int]:
    usage = usage or {}
    return int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))


def build_cache_payload(
    kb_id: str,
    answer: str,
    hits: list,
    model: str,
) -> dict:
    return {
        "kb_id": kb_id,
        "answer": answer,
        "model": model,
        "citations": [
            {
                "chunk_id": hit.chunk_id,
                "doc_id": hit.doc_id,
                "doc_name": hit.doc_name,
                "page": hit.page,
                "rank": index,
                "score": float(hit.rerank_score if hit.rerank_score is not None else hit.score),
                "quote": hit.content[:300],
            }
            for index, hit in enumerate(hits, start=1)
        ],
    }


def new_message_id() -> str:
    from ..models import new_id

    return new_id()


def title_needed(title: str) -> bool:
    return title in {"新会话", ""}


DEFAULT_MODEL = settings.qwen_chat_model
