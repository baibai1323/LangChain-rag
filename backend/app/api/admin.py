from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..deps import require_admin
from ..models import (
    AuditLog,
    Chunk,
    Conversation,
    Document,
    Feedback,
    KnowledgeBase,
    LlmCall,
    Message,
    User,
)
from ..schemas import AdminStats, UserAdminOut, UserUpdateIn
from ..services.cache import cache_service

router = APIRouter(prefix="/api/admin", tags=["管理"])


def _today() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)


@router.get("/stats", response_model=AdminStats, summary="平台统计")
async def stats(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> AdminStats:
    async def count(model) -> int:  # noqa: ANN001
        return int((await db.execute(select(func.count()).select_from(model))).scalar_one())

    today = _today()
    llm_calls_today = int(
        (
            await db.execute(
                select(func.count()).select_from(LlmCall).where(LlmCall.created_at >= today)
            )
        ).scalar_one()
    )
    tokens_today = int(
        (
            await db.execute(
                select(
                    func.coalesce(
                        func.sum(LlmCall.prompt_tokens + LlmCall.completion_tokens), 0
                    )
                ).where(LlmCall.created_at >= today)
            )
        ).scalar_one()
    )
    avg_latency = (
        await db.execute(
            select(func.coalesce(func.avg(Message.latency_ms), 0)).where(
                Message.role == "assistant", Message.latency_ms > 0
            )
        )
    ).scalar_one()
    positive = int(
        (
            await db.execute(
                select(func.count()).select_from(Feedback).where(Feedback.rating > 0)
            )
        ).scalar_one()
    )
    negative = int(
        (
            await db.execute(
                select(func.count()).select_from(Feedback).where(Feedback.rating < 0)
            )
        ).scalar_one()
    )
    return AdminStats(
        users=await count(User),
        conversations=await count(Conversation),
        messages=await count(Message),
        documents=await count(Document),
        chunks=await count(Chunk),
        knowledge_bases=await count(KnowledgeBase),
        llm_calls_today=llm_calls_today,
        tokens_today=tokens_today,
        avg_latency_ms=int(avg_latency or 0),
        feedback_positive=positive,
        feedback_negative=negative,
    )


@router.get("/series", summary="近 7 天使用趋势")
async def series(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> list[dict]:
    start = _today() - timedelta(days=6)
    rows = (
        await db.execute(
            select(
                func.date(Message.created_at).label("day"),
                func.count(Message.id).label("count"),
            )
            .where(Message.created_at >= start, Message.role == "user")
            .group_by("day")
            .order_by("day")
        )
    ).all()
    counts = {str(row.day): int(row.count) for row in rows}
    result = []
    for offset in range(7):
        day = (start + timedelta(days=offset)).date()
        result.append({"date": day.isoformat(), "messages": counts.get(day.isoformat(), 0)})
    return result


@router.get("/users", response_model=list[UserAdminOut], summary="用户列表")
async def list_users(
    admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[UserAdminOut]:
    users = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    rows = (
        await db.execute(
            select(Conversation.user_id, func.count(Conversation.id)).group_by(Conversation.user_id)
        )
    ).all()
    counts = {user_id: int(count) for user_id, count in rows}
    return [
        UserAdminOut.model_validate(
            {
                **UserAdminOut.model_validate(user).model_dump(),
                "conversation_count": counts.get(user.id, 0),
            }
        )
        for user in users
    ]


@router.patch("/users/{user_id}", response_model=UserAdminOut, summary="修改用户角色/状态")
async def update_user(
    user_id: str,
    data: UserUpdateIn,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserAdminOut:
    if user_id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能修改自己的角色或状态")
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if user.username == settings.admin_username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="内置管理员账号不可修改")
    if data.role:
        user.role = data.role
    if data.status:
        user.status = data.status
        user.token_version += 1
    await db.commit()
    await db.refresh(user)
    return UserAdminOut.model_validate({**UserAdminOut.model_validate(user).model_dump(), "conversation_count": 0})


@router.get("/audit-logs", summary="审计日志")
async def audit_logs(
    limit: int = 50,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    limit = max(1, min(limit, 200))
    logs = (
        await db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))
    ).scalars().all()
    return [
        {
            "id": item.id,
            "username": item.username,
            "action": item.action,
            "target": item.target,
            "detail": item.detail,
            "ip": item.ip,
            "created_at": item.created_at,
        }
        for item in logs
    ]


@router.get("/llm-calls", summary="模型调用记录")
async def llm_calls(
    limit: int = 50,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    limit = max(1, min(limit, 200))
    calls = (
        await db.execute(select(LlmCall).order_by(LlmCall.created_at.desc()).limit(limit))
    ).scalars().all()
    return [
        {
            "id": item.id,
            "purpose": item.purpose,
            "model": item.model,
            "prompt_tokens": item.prompt_tokens,
            "completion_tokens": item.completion_tokens,
            "latency_ms": item.latency_ms,
            "status": item.status,
            "created_at": item.created_at,
        }
        for item in calls
    ]


@router.get("/cache", summary="缓存状态")
async def cache_status(admin: User = Depends(require_admin)) -> dict:
    return cache_service.stats()
