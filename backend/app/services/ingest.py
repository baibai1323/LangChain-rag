from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import SessionLocal
from ..models import Chunk, Document, IngestionTask, KnowledgeBase, new_id, utcnow
from ..rag.extract import extract_pages
from ..rag.splitter import split_page
from ..rag.tokens import estimate_tokens, tokenize_for_fts
from ..rag.vectorstore import vector_store
from ..llm import embed_texts
from .cache import cache_service

logger = logging.getLogger(__name__)


async def _set_task(task_id: str, **fields) -> None:  # noqa: ANN003
    async with SessionLocal() as db:
        task = await db.get(IngestionTask, task_id)
        if task is None:
            return
        for key, value in fields.items():
            setattr(task, key, value)
        await db.commit()


async def _set_doc(doc_id: str, **fields) -> None:  # noqa: ANN003
    async with SessionLocal() as db:
        doc = await db.get(Document, doc_id)
        if doc is None:
            return
        for key, value in fields.items():
            setattr(doc, key, value)
        await db.commit()


async def _build_chunks(doc: Document) -> list[dict]:
    pages = await asyncio.to_thread(extract_pages, Path(doc.stored_path), doc.filename)
    if not pages:
        raise ValueError("未能从文件中解析出有效文本，请检查文件内容或格式")
    items: list[dict] = []
    index = 0
    for page, text in pages:
        for piece in split_page(text):
            items.append(
                {
                    "id": new_id(),
                    "doc_id": doc.id,
                    "kb_id": doc.kb_id,
                    "chunk_index": index,
                    "content": piece["content"],
                    "parent_content": piece["parent_content"],
                    "page": page,
                }
            )
            index += 1
    if not items:
        raise ValueError("文本切分后没有有效片段")
    return items


async def ingest_document(doc_id: str, task_id: str) -> None:
    started = time.perf_counter()
    try:
        async with SessionLocal() as db:
            doc = await db.get(Document, doc_id)
            if doc is None:
                await _set_task(
                    task_id, status="failed", error="文档不存在", finished_at=utcnow()
                )
                return
            kb = await db.get(KnowledgeBase, doc.kb_id)
            if kb is None:
                raise ValueError("知识库不存在")
            filename, kb_id = doc.filename, doc.kb_id

        await _set_doc(doc_id, status="processing")
        await _set_task(task_id, stage="parsing", progress=5)

        async with SessionLocal() as db:
            doc = await db.get(Document, doc_id)
            assert doc is not None
            items = await _build_chunks(doc)

        await _set_task(task_id, stage="splitting", progress=15)

        # 预分词（jieba 为 CPU 密集操作，放到线程池批量处理）
        def prepare_texts(chunks: list[dict]) -> None:
            for item in chunks:
                item["content_tok"] = tokenize_for_fts(item["content"])
                item["token_count"] = estimate_tokens(item["content"])
                item["char_count"] = len(item["content"])

        await asyncio.to_thread(prepare_texts, items)
        await _set_task(task_id, stage="embedding", progress=20)

        embeddings: list[list[float]] = []
        batch = 16
        for start in range(0, len(items), batch):
            group = items[start : start + batch]
            vectors = await embed_texts([item["content"] for item in group])
            embeddings.extend(vectors)
            progress = 20 + int(60 * min(1.0, (start + len(group)) / len(items)))
            await _set_task(task_id, progress=progress)
        if len(embeddings) != len(items):
            raise RuntimeError("向量数量与切片数量不一致")

        await _set_task(task_id, stage="indexing", progress=85)

        async with SessionLocal() as db:
            await db.execute(delete(Chunk).where(Chunk.doc_id == doc_id))
            for item, embedding in zip(items, embeddings):
                db.add(
                    Chunk(
                        id=item["id"],
                        doc_id=item["doc_id"],
                        kb_id=item["kb_id"],
                        chunk_index=item["chunk_index"],
                        content=item["content"],
                        parent_content=item["parent_content"],
                        content_tok=item["content_tok"],
                        token_count=item["token_count"],
                        char_count=item["char_count"],
                        meta_json=json.dumps({"page": item["page"]}, ensure_ascii=False),
                    )
                )
            await db.commit()

        try:
            await vector_store.upsert(
                ids=[item["id"] for item in items],
                embeddings=embeddings,
                documents=[item["content"] for item in items],
                metadatas=[
                    {
                        "kb_id": item["kb_id"],
                        "doc_id": item["doc_id"],
                        "doc_name": filename,
                        "page": item["page"],
                        "chunk_index": item["chunk_index"],
                    }
                    for item in items
                ],
            )
        except Exception:
            async with SessionLocal() as db:
                await db.execute(delete(Chunk).where(Chunk.doc_id == doc_id))
                await db.commit()
            raise

        total_tokens = sum(item["token_count"] for item in items)
        await _set_doc(
            doc_id,
            status="ready",
            chunk_count=len(items),
            token_count=total_tokens,
            error=None,
        )
        elapsed = int((time.perf_counter() - started) * 1000)
        await _set_task(
            task_id,
            stage="done",
            progress=100,
            status="success",
            finished_at=utcnow(),
        )
        cache_service.invalidate_kb(kb_id)
        logger.info("文档入库完成 doc=%s chunks=%s 耗时=%sms", doc_id, len(items), elapsed)
    except Exception as exc:  # noqa: BLE001
        logger.exception("文档入库失败 doc=%s", doc_id)
        await _set_doc(doc_id, status="failed", error=str(exc)[:500])
        await _set_task(
            task_id, status="failed", error=str(exc)[:500], stage="failed", finished_at=utcnow()
        )


async def delete_document_vectors(doc_id: str) -> None:
    try:
        await vector_store.delete_doc(doc_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("删除向量失败 doc=%s: %s", doc_id, exc)


async def delete_kb_vectors(kb_id: str) -> None:
    try:
        await vector_store.delete_kb(kb_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("删除知识库向量失败 kb=%s: %s", kb_id, exc)
