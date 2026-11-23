from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import SessionLocal, get_db
from ..deps import get_current_user
from ..models import (
    Conversation,
    KnowledgeBase,
    LlmCall,
    Message,
    MessageCitation,
    User,
    new_id,
    utcnow,
)
from ..llm import embed_query, stream_answer
from ..rag.prompt import build_context, build_messages
from ..rag.retriever import retrieve
from ..schemas import ChatIn
from ..services.cache import cache_service
from ..services.chat import (
    build_cache_payload,
    load_history,
    now_ms,
    rewrite_question,
    title_needed,
    usage_dict,
)
from ..services.ratelimit import chat_limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["问答"])

NO_HIT_ANSWER = (
    "抱歉，我在当前知识库中没有找到与该问题相关的内容。\n\n"
    "建议您：\n1. 换一种说法或补充商品名称、型号等关键词；\n"
    "2. 联系人工客服进一步确认。"
)


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _persist(
    assistant_id: str,
    conversation_id: str,
    answer: str,
    status_value: str,
    citations: list[dict],
    usage: dict[str, int],
    first_token_ms: int,
    latency_ms: int,
    from_cache: bool,
    question: str,
) -> str:
    async with SessionLocal() as db:
        message = await db.get(Message, assistant_id)
        if message is not None:
            message.content = answer
            message.status = status_value
            message.prompt_tokens, message.completion_tokens = usage_dict(usage)
            message.first_token_ms = first_token_ms
            message.latency_ms = latency_ms
            message.from_cache = 1 if from_cache else 0
            for item in citations:
                db.add(MessageCitation(message_id=assistant_id, **item))
        conv = await db.get(Conversation, conversation_id)
        if conv is not None:
            conv.updated_at = utcnow()
            if title_needed(conv.title):
                conv.title = question.strip()[:20] or "新会话"
        db.add(
            LlmCall(
                user_id=None,
                conversation_id=conversation_id,
                purpose="chat",
                model=settings.qwen_chat_model,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                latency_ms=latency_ms,
                status=status_value,
            )
        )
        await db.commit()
        return conv.title if conv is not None else ""


@router.post("/stream", summary="知识库问答（SSE 流式）")
async def chat_stream(
    data: ChatIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    chat_limiter.check(user.id)
    question = data.question.strip()
    if not question:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="问题不能为空")

    conv = await db.get(Conversation, data.conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    kb = await db.get(KnowledgeBase, conv.kb_id)
    if kb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")

    history = await load_history(db, conv.id)
    assistant_id = new_id()
    db.add(Message(conversation_id=conv.id, role="user", content=question, status="done"))
    db.add(
        Message(
            id=assistant_id,
            conversation_id=conv.id,
            role="assistant",
            content="",
            status="streaming",
            model=settings.qwen_chat_model,
        )
    )
    conv.updated_at = utcnow()
    if title_needed(conv.title):
        conv.title = question[:20]
    await db.commit()
    kb_id = kb.id
    conv_id = conv.id

    async def generator() -> AsyncIterator[str]:
        started = time.perf_counter()
        answer_parts: list[str] = []
        citations: list[dict] = []
        usage: dict[str, int] = {}
        first_token_ms = 0
        from_cache = False
        status_value = "done"
        finalized = False
        try:
            exact = cache_service.get_exact(kb_id, question) if data.use_cache else None
            embedding: list[float] | None = None
            cached = exact
            if cached is None:
                embedding = await embed_query(question)
                if data.use_cache:
                    semantic = cache_service.get_semantic(kb_id, embedding)
                    if semantic:
                        cached, similarity = semantic
                        logger.info("语义缓存命中 kb=%s score=%.3f", kb_id, similarity)

            if cached and cached.get("answer"):
                from_cache = True
                answer = cached["answer"]
                citations = cached.get("citations", [])
                yield sse("retrieval", {"hits": citations, "cached": True})
                step = 24
                for index in range(0, len(answer), step):
                    yield sse("delta", {"text": answer[index : index + step]})
                    await asyncio.sleep(0.008)
                answer_parts.append(answer)
                first_token_ms = now_ms(started)
                usage = cached.get("usage", {})
            else:
                yield sse("status", {"stage": "rewrite", "message": "正在理解问题…"})
                rewritten = await rewrite_question(question, history)
                if await request.is_disconnected():
                    raise asyncio.CancelledError

                yield sse("status", {"stage": "retrieval", "message": "正在检索知识库…"})
                # 生成器在响应返回后才执行，不能再复用请求作用域的 session
                async with SessionLocal() as sdb:
                    hits = await retrieve(sdb, kb_id, rewritten, query_embedding=embedding)
                context, selected = build_context(hits)
                citations = [
                    {
                        "chunk_id": hit.chunk_id,
                        "doc_id": hit.doc_id,
                        "doc_name": hit.doc_name,
                        "page": hit.page,
                        "rank": index,
                        "score": float(hit.rerank_score if hit.rerank_score is not None else hit.score),
                        "quote": hit.content[:300],
                    }
                    for index, hit in enumerate(selected, start=1)
                ]
                yield sse(
                    "retrieval",
                    {"hits": citations, "rewritten": rewritten, "cached": False},
                )

                if not selected:
                    answer = NO_HIT_ANSWER
                    yield sse("delta", {"text": answer})
                    answer_parts.append(answer)
                else:
                    messages = build_messages(question, context, history)
                    async for event in stream_answer(messages):
                        if event["type"] == "first_token":
                            first_token_ms = event["ms"]
                            yield sse("status", {"stage": "generating", "message": "正在生成回答…"})
                        elif event["type"] == "delta":
                            answer_parts.append(event["text"])
                            yield sse("delta", {"text": event["text"]})
                        elif event["type"] == "usage":
                            usage = event.get("usage", {})

            answer = "".join(answer_parts)
            latency_ms = now_ms(started)
            if not from_cache and answer and citations:
                payload = build_cache_payload(kb_id, answer, selected, settings.qwen_chat_model)
                cache_service.set_exact(kb_id, question, payload)
                if embedding is not None:
                    cache_service.add_semantic(kb_id, question, embedding, payload)

            title = await _persist(
                assistant_id,
                conv_id,
                answer,
                "done",
                citations,
                usage,
                first_token_ms,
                latency_ms,
                from_cache,
                question,
            )
            finalized = True
            yield sse(
                "done",
                {
                    "message_id": assistant_id,
                    "conversation_id": conv_id,
                    "conversation_title": title,
                    "latency_ms": latency_ms,
                    "first_token_ms": first_token_ms,
                    "usage": usage,
                    "from_cache": from_cache,
                    "citations": citations,
                },
            )
        except asyncio.CancelledError:
            if not finalized:
                await _persist(
                    assistant_id,
                    conv_id,
                    "".join(answer_parts),
                    "cancelled",
                    citations,
                    usage,
                    first_token_ms,
                    now_ms(started),
                    from_cache,
                    question,
                )
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("问答失败")
            status_value = "failed"
            if not finalized:
                await _persist(
                    assistant_id,
                    conv_id,
                    "".join(answer_parts),
                    "failed",
                    citations,
                    usage,
                    first_token_ms,
                    now_ms(started),
                    from_cache,
                    question,
                )
            yield sse("error", {"message": f"生成回答失败：{exc}"})

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/", include_in_schema=False)
async def chat_placeholder() -> dict[str, str]:
    return {"message": "请使用 /api/chat/stream"}
