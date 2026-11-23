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


async def rewrite_question(question: str, history: list[dict[str, str]]) -> str:
    if not history:
        return question
    snippet = "\n".join(f"{m['role']}: {m['content'][:200]}" for m in history[-4:])
    try:
        rewritten, _ = await fast_chat(
            [
                {"role": "system", "content": REWRITE_PROMPT},
                {"role": "user", "content": f"对话历史：\n{snippet}\n\n最新问题：{question}"},
            ],
            max_tokens=128,
        )
        rewritten = rewritten.strip().strip('"').strip("“”")
        return rewritten if 2 <= len(rewritten) <= 200 else question
    except Exception as exc:  # noqa: BLE001  改写失败时使用原问题
        logger.warning("查询改写失败，使用原问题: %s", exc)
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
