from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import get_current_user
from ..models import (
    Conversation,
    Feedback,
    KnowledgeBase,
    Message,
    MessageCitation,
    User,
    utcnow,
)
from ..schemas import (
    CitationOut,
    ConversationCreateIn,
    ConversationOut,
    ConversationUpdateIn,
    FeedbackIn,
    MessageOut,
)

router = APIRouter(prefix="/api", tags=["会话"])


async def _get_conversation(db: AsyncSession, conv_id: str, user: User) -> Conversation:
    conv = await db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    return conv


@router.get("/conversations", response_model=list[ConversationOut], summary="会话列表")
async def list_conversations(
    kb_id: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationOut]:
    stmt = select(Conversation).where(Conversation.user_id == user.id)
    if kb_id:
        stmt = stmt.where(Conversation.kb_id == kb_id)
    stmt = stmt.order_by(Conversation.is_pinned.desc(), Conversation.updated_at.desc()).limit(200)
    conversations = (await db.execute(stmt)).scalars().all()
    if not conversations:
        return []
    ids = [c.id for c in conversations]
    rows = (
        await db.execute(
            select(Message.conversation_id, func.count(Message.id))
            .where(Message.conversation_id.in_(ids), Message.role == "user")
            .group_by(Message.conversation_id)
        )
    ).all()
    counts = {cid: int(count) for cid, count in rows}
    return [
        ConversationOut(
            **{c: getattr(conv, c) for c in ("id", "kb_id", "title", "is_pinned", "created_at", "updated_at")},
            message_count=counts.get(conv.id, 0),
        )
        for conv in conversations
    ]


@router.post("/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    data: ConversationCreateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationOut:
    kb = await db.get(KnowledgeBase, data.kb_id)
    if kb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    conv = Conversation(
        user_id=user.id, kb_id=data.kb_id, title=data.title or "新会话"
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return ConversationOut(
        **{c: getattr(conv, c) for c in ("id", "kb_id", "title", "is_pinned", "created_at", "updated_at")},
        message_count=0,
    )


@router.get("/conversations/{conv_id}", response_model=ConversationOut, summary="会话详情")
async def get_conversation(
    conv_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ConversationOut:
    conv = await _get_conversation(db, conv_id, user)
    count = (
        await db.execute(
            select(func.count(Message.id)).where(
                Message.conversation_id == conv_id, Message.role == "user"
            )
        )
    ).scalar_one()
    return ConversationOut(
        **{c: getattr(conv, c) for c in ("id", "kb_id", "title", "is_pinned", "created_at", "updated_at")},
        message_count=int(count),
    )


@router.patch("/conversations/{conv_id}", response_model=ConversationOut, summary="重命名/置顶")
async def update_conversation(
    conv_id: str,
    data: ConversationUpdateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationOut:
    conv = await _get_conversation(db, conv_id, user)
    if data.title is not None:
        conv.title = data.title.strip() or conv.title
    if data.is_pinned is not None:
        conv.is_pinned = 1 if data.is_pinned else 0
    conv.updated_at = utcnow()
    await db.commit()
    await db.refresh(conv)
    count = (
        await db.execute(
            select(func.count(Message.id)).where(
                Message.conversation_id == conv_id, Message.role == "user"
            )
        )
    ).scalar_one()
    return ConversationOut(
        **{c: getattr(conv, c) for c in ("id", "kb_id", "title", "is_pinned", "created_at", "updated_at")},
        message_count=int(count),
    )


@router.delete("/conversations/{conv_id}", summary="删除会话")
async def delete_conversation(
    conv_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    conv = await _get_conversation(db, conv_id, user)
    message_ids = (
        await db.execute(select(Message.id).where(Message.conversation_id == conv_id))
    ).scalars().all()
    if message_ids:
        await db.execute(delete(MessageCitation).where(MessageCitation.message_id.in_(message_ids)))
        await db.execute(delete(Feedback).where(Feedback.message_id.in_(message_ids)))
        await db.execute(delete(Message).where(Message.id.in_(message_ids)))
    await db.delete(conv)
    await db.commit()
    return {"message": "会话已删除"}


@router.get("/conversations/{conv_id}/messages", response_model=list[MessageOut], summary="历史消息")
async def list_messages(
    conv_id: str,
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MessageOut]:
    await _get_conversation(db, conv_id, user)
    limit = max(1, min(limit, 500))
    rows = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conv_id, Message.status.in_(["done", "cancelled"]))
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    messages = list(reversed(rows))
    if not messages:
        return []
    ids = [m.id for m in messages]
    citations = (
        await db.execute(
            select(MessageCitation)
            .where(MessageCitation.message_id.in_(ids))
            .order_by(MessageCitation.rank)
        )
    ).scalars().all()
    grouped: dict[str, list[CitationOut]] = {}
    for item in citations:
        grouped.setdefault(item.message_id, []).append(CitationOut.model_validate(item))
    return [
        MessageOut(
            **{
                c: getattr(m, c)
                for c in (
                    "id",
                    "conversation_id",
                    "role",
                    "content",
                    "status",
                    "model",
                    "prompt_tokens",
                    "completion_tokens",
                    "first_token_ms",
                    "latency_ms",
                    "from_cache",
                    "created_at",
                )
            },
            citations=grouped.get(m.id, []),
        )
        for m in messages
    ]


@router.post("/messages/{message_id}/feedback", summary="消息反馈")
async def submit_feedback(
    message_id: str,
    data: FeedbackIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    message = await db.get(Message, message_id)
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="消息不存在")
    conv = await db.get(Conversation, message.conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作该消息")
    existing = (
        await db.execute(
            select(Feedback).where(Feedback.message_id == message_id, Feedback.user_id == user.id)
        )
    ).scalar_one_or_none()
    if existing:
        existing.rating = data.rating
        existing.comment = data.comment
    else:
        db.add(
            Feedback(
                message_id=message_id, user_id=user.id, rating=data.rating, comment=data.comment
            )
        )
    await db.commit()
    return {"message": "感谢反馈"}
