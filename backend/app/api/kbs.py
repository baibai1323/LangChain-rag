from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import (
    AuditLog,
    Chunk,
    Conversation,
    Document,
    KnowledgeBase,
    Message,
    User,
    utcnow,
)
from ..rag.retriever import retrieve
from ..schemas import KbIn, KbOut, KbUpdateIn, SearchHit, SearchTestIn
from ..services.ingest import delete_kb_vectors

router = APIRouter(prefix="/api/kbs", tags=["知识库"])


async def _counts(db: AsyncSession, kb_ids: list[str]) -> dict[str, tuple[int, int]]:
    if not kb_ids:
        return {}
    doc_rows = (
        await db.execute(
            select(Document.kb_id, func.count(Document.id))
            .where(Document.kb_id.in_(kb_ids))
            .group_by(Document.kb_id)
        )
    ).all()
    chunk_rows = (
        await db.execute(
            select(Chunk.kb_id, func.count(Chunk.id))
            .where(Chunk.kb_id.in_(kb_ids))
            .group_by(Chunk.kb_id)
        )
    ).all()
    docs = {kb_id: int(count) for kb_id, count in doc_rows}
    chunks = {kb_id: int(count) for kb_id, count in chunk_rows}
    return {kb_id: (docs.get(kb_id, 0), chunks.get(kb_id, 0)) for kb_id in kb_ids}


def _kb_out(kb: KnowledgeBase, counts: tuple[int, int]) -> KbOut:
    return KbOut(
        **{c: getattr(kb, c) for c in ("id", "name", "description", "embedding_model", "embedding_dim", "version", "created_at", "updated_at")},
        document_count=counts[0],
        chunk_count=counts[1],
    )


@router.get("", response_model=list[KbOut], summary="知识库列表（登录用户可见）")
async def list_kbs(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[KbOut]:
    kbs = (await db.execute(select(KnowledgeBase).order_by(KnowledgeBase.created_at))).scalars().all()
    counts = await _counts(db, [kb.id for kb in kbs])
    return [_kb_out(kb, counts.get(kb.id, (0, 0))) for kb in kbs]


@router.get("/{kb_id}", response_model=KbOut, summary="知识库详情")
async def get_kb(
    kb_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> KbOut:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    counts = await _counts(db, [kb_id])
    return _kb_out(kb, counts.get(kb_id, (0, 0)))


@router.post("", response_model=KbOut, status_code=status.HTTP_201_CREATED, summary="创建知识库")
async def create_kb(
    data: KbIn,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> KbOut:
    exists = (
        await db.execute(select(KnowledgeBase).where(func.lower(KnowledgeBase.name) == data.name.strip().lower()))
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="知识库名称已存在")
    kb = KnowledgeBase(name=data.name.strip(), description=data.description, created_by=admin.id)
    db.add(kb)
    db.add(AuditLog(user_id=admin.id, username=admin.username, action="kb_create", target=data.name, ip=request.client.host if request.client else ""))
    await db.commit()
    await db.refresh(kb)
    return _kb_out(kb, (0, 0))


@router.patch("/{kb_id}", response_model=KbOut, summary="更新知识库")
async def update_kb(
    kb_id: str,
    data: KbUpdateIn,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> KbOut:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    if data.name:
        duplicate = (
            await db.execute(
                select(KnowledgeBase).where(
                    func.lower(KnowledgeBase.name) == data.name.strip().lower(), KnowledgeBase.id != kb_id
                )
            )
        ).scalar_one_or_none()
        if duplicate:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="知识库名称已存在")
        kb.name = data.name.strip()
    if data.description is not None:
        kb.description = data.description
    kb.updated_at = utcnow()
    await db.commit()
    await db.refresh(kb)
    counts = await _counts(db, [kb_id])
    return _kb_out(kb, counts.get(kb_id, (0, 0)))


@router.delete("/{kb_id}", summary="删除知识库")
async def delete_kb(
    kb_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    conv_ids = (
        await db.execute(select(Conversation.id).where(Conversation.kb_id == kb_id))
    ).scalars().all()
    if conv_ids:
        await db.execute(delete(Message).where(Message.conversation_id.in_(conv_ids)))
        await db.execute(delete(Conversation).where(Conversation.id.in_(conv_ids)))
    await db.execute(delete(Chunk).where(Chunk.kb_id == kb_id))
    await db.execute(delete(Document).where(Document.kb_id == kb_id))
    await db.delete(kb)
    await db.commit()
    await delete_kb_vectors(kb_id)
    return {"message": "知识库已删除"}


@router.get("/{kb_id}/stats", summary="知识库统计")
async def kb_stats(
    kb_id: str, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    doc_count = (
        await db.execute(select(func.count(Document.id)).where(Document.kb_id == kb_id))
    ).scalar_one()
    ready_count = (
        await db.execute(
            select(func.count(Document.id)).where(Document.kb_id == kb_id, Document.status == "ready")
        )
    ).scalar_one()
    chunk_count = (
        await db.execute(select(func.count(Chunk.id)).where(Chunk.kb_id == kb_id))
    ).scalar_one()
    token_sum = (
        await db.execute(select(func.coalesce(func.sum(Chunk.token_count), 0)).where(Chunk.kb_id == kb_id))
    ).scalar_one()
    return {
        "kb_id": kb_id,
        "documents": int(doc_count),
        "ready_documents": int(ready_count),
        "chunks": int(chunk_count),
        "tokens": int(token_sum),
    }


@router.post("/{kb_id}/search-test", response_model=list[SearchHit], summary="检索测试（管理员）")
async def search_test(
    kb_id: str,
    data: SearchTestIn,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[SearchHit]:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    hits = await retrieve(db, kb_id, data.query, top_k=data.top_k)
    return [
        SearchHit(
            chunk_id=hit.chunk_id,
            doc_id=hit.doc_id,
            doc_name=hit.doc_name,
            page=hit.page,
            content=hit.parent_content[:600],
            score=float(hit.score),
            rerank_score=hit.rerank_score,
            source="hybrid",
        )
        for hit in hits
    ]
