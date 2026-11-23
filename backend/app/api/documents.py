from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..deps import require_admin
from ..models import AuditLog, Chunk, Document, IngestionTask, KnowledgeBase, User, new_id, utcnow
from ..rag.extract import SUPPORTED_EXTENSIONS, UnsupportedFileType
from ..schemas import ChunkOut, DocumentOut, TaskOut
from ..services.ingest import delete_document_vectors, ingest_document

router = APIRouter(prefix="/api", tags=["文档管理"])

MAX_FILE_SIZE = 20 * 1024 * 1024


def _doc_out(doc: Document) -> DocumentOut:
    return DocumentOut.model_validate(doc)


@router.post(
    "/kbs/{kb_id}/documents",
    status_code=status.HTTP_202_ACCEPTED,
    summary="上传文档并触发后台入库",
)
async def upload_document(
    kb_id: str,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")

    filename = Path(file.filename or "unnamed").name
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件类型，支持：{', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件为空")
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="文件不能超过 20MB")

    file_hash = hashlib.sha256(data).hexdigest()
    duplicate = (
        await db.execute(
            select(Document).where(Document.kb_id == kb_id, Document.file_hash == file_hash)
        )
    ).scalar_one_or_none()
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"该文件已存在：{duplicate.filename}"
        )

    doc_id = new_id()
    target_dir = settings.uploads_dir / kb_id
    target_dir.mkdir(parents=True, exist_ok=True)
    stored_path = target_dir / f"{doc_id}{suffix}"
    stored_path.write_bytes(data)

    doc = Document(
        id=doc_id,
        kb_id=kb_id,
        filename=filename,
        stored_path=str(stored_path),
        file_hash=file_hash,
        mime=file.content_type or "",
        size=len(data),
        status="pending",
        uploaded_by=admin.id,
    )
    task = IngestionTask(id=new_id(), doc_id=doc_id, stage="pending", progress=0, status="running")
    db.add(doc)
    db.add(task)
    db.add(
        AuditLog(
            user_id=admin.id,
            username=admin.username,
            action="document_upload",
            target=filename,
            detail=f"kb={kb_id}",
        )
    )
    await db.commit()
    await db.refresh(doc)

    background.add_task(ingest_document, doc_id, task.id)
    return {"document": _doc_out(doc), "task_id": task.id}


@router.get("/kbs/{kb_id}/documents", response_model=list[DocumentOut], summary="文档列表")
async def list_documents(
    kb_id: str, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[Document]:
    rows = (
        await db.execute(
            select(Document).where(Document.kb_id == kb_id).order_by(Document.created_at.desc())
        )
    ).scalars().all()
    return list(rows)


@router.get("/documents/{doc_id}", response_model=DocumentOut, summary="文档详情")
async def get_document(
    doc_id: str, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> Document:
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    return doc


@router.get("/documents/{doc_id}/chunks", summary="查看切片（分页）")
async def list_chunks(
    doc_id: str,
    offset: int = 0,
    limit: int = 50,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    limit = max(1, min(limit, 200))
    total = (
        await db.execute(select(func.count(Chunk.id)).where(Chunk.doc_id == doc_id))
    ).scalar_one()
    rows = (
        await db.execute(
            select(Chunk)
            .where(Chunk.doc_id == doc_id)
            .order_by(Chunk.chunk_index)
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return {"total": int(total), "items": [ChunkOut.model_validate(c).model_dump() for c in rows]}


@router.post("/documents/{doc_id}/reindex", summary="重新入库")
async def reindex_document(
    doc_id: str,
    background: BackgroundTasks,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    if not Path(doc.stored_path).exists():
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="源文件已丢失，请重新上传")
    task = IngestionTask(
        id=new_id(), doc_id=doc_id, stage="pending", progress=0, status="running"
    )
    doc.status = "pending"
    doc.error = None
    doc.updated_at = utcnow()
    db.add(task)
    await db.commit()
    background.add_task(ingest_document, doc_id, task.id)
    return {"task_id": task.id, "message": "已开始重新入库"}


@router.delete("/documents/{doc_id}", summary="删除文档")
async def delete_document(
    doc_id: str, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    path = Path(doc.stored_path)
    await db.execute(delete(Chunk).where(Chunk.doc_id == doc_id))
    await db.execute(delete(IngestionTask).where(IngestionTask.doc_id == doc_id))
    await db.delete(doc)
    await db.commit()
    await delete_document_vectors(doc_id)
    if path.exists() and settings.uploads_dir in path.parents:
        path.unlink(missing_ok=True)
    return {"message": "文档已删除"}


@router.get("/tasks/{task_id}", response_model=TaskOut, summary="入库任务进度")
async def get_task(
    task_id: str, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> IngestionTask:
    task = await db.get(IngestionTask, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return task


@router.get("/kbs/{kb_id}/tasks", response_model=list[TaskOut], summary="知识库最近任务")
async def list_tasks(
    kb_id: str, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[IngestionTask]:
    doc_ids = (
        await db.execute(select(Document.id).where(Document.kb_id == kb_id))
    ).scalars().all()
    if not doc_ids:
        return []
    rows = (
        await db.execute(
            select(IngestionTask)
            .where(IngestionTask.doc_id.in_(doc_ids))
            .order_by(IngestionTask.started_at.desc())
            .limit(30)
        )
    ).scalars().all()
    return list(rows)
