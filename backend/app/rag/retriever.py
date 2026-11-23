from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..llm import embed_query, rerank
from ..models import Chunk, Document
from .tokens import build_fts_query, tokens
from .vectorstore import vector_store

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    doc_name: str
    page: int
    content: str
    parent_content: str
    score: float = 0.0
    rrf_score: float = 0.0
    rerank_score: float | None = None
    source: str = "hybrid"
    vector_rank: int | None = None
    bm25_rank: int | None = None
    extra: dict = field(default_factory=dict)


async def bm25_search(
    db: AsyncSession, kb_id: str, query: str, limit: int
) -> list[tuple[str, float]]:
    match = build_fts_query(query)
    if not match:
        return []
    sql = text(
        """
        SELECT c.id AS id, bm25(chunks_fts) AS score
        FROM chunks_fts
        JOIN chunks c ON c.rowid = chunks_fts.rowid
        WHERE chunks_fts MATCH :match AND c.kb_id = :kb_id
        ORDER BY score
        LIMIT :limit
        """
    )
    try:
        rows = (await db.execute(sql, {"match": match, "kb_id": kb_id, "limit": limit})).all()
    except Exception as exc:  # noqa: BLE001  FTS 语法异常时降级为纯向量检索
        logger.warning("BM25 检索失败，降级为向量检索: %s", exc)
        return []
    return [(row.id, -float(row.score)) for row in rows]


def dedupe_by_parent(items: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """同一父块下的多个子块只保留得分最高的一个，避免引用重复。"""
    seen: set[tuple[str, str]] = set()
    unique: list[RetrievedChunk] = []
    for item in items:
        key = (item.doc_id, item.parent_content or item.content)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def rrf_fuse(rank_lists: list[list[str]], k: int | None = None) -> dict[str, float]:
    k = settings.rrf_k if k is None else k
    scores: dict[str, float] = {}
    for ids in rank_lists:
        for rank, chunk_id in enumerate(ids):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    return scores


async def retrieve(
    db: AsyncSession,
    kb_id: str,
    query: str,
    top_k: int | None = None,
    use_rerank: bool = True,
    query_embedding: list[float] | None = None,
) -> list[RetrievedChunk]:
    top_k = top_k or settings.rerank_top_n
    vector_hits: list[dict] = []
    try:
        embedding = query_embedding or await embed_query(query)
        vector_hits = await vector_store.query(kb_id, embedding, settings.vector_top_k)
    except Exception as exc:  # noqa: BLE001  向量检索不可用时保留 BM25
        logger.warning("向量检索失败: %s", exc)

    bm25_hits = await bm25_search(db, kb_id, query, settings.bm25_top_k)

    vector_ids = [h["chunk_id"] for h in vector_hits]
    bm25_ids = [cid for cid, _ in bm25_hits]
    fused = rrf_fuse([vector_ids, bm25_ids])
    if not fused:
        return []

    ordered_ids = sorted(fused.keys(), key=lambda cid: fused[cid], reverse=True)[: settings.vector_top_k]
    rows = (
        await db.execute(
            select(Chunk, Document.filename)
            .join(Document, Document.id == Chunk.doc_id)
            .where(Chunk.id.in_(ordered_ids))
        )
    ).all()
    chunk_map: dict[str, tuple[Chunk, str]] = {chunk.id: (chunk, name) for chunk, name in rows}

    candidates: list[RetrievedChunk] = []
    for chunk_id in ordered_ids:
        item = chunk_map.get(chunk_id)
        if item is None:
            continue
        chunk, doc_name = item
        try:
            meta = json.loads(chunk.meta_json or "{}")
        except json.JSONDecodeError:
            meta = {}
        candidates.append(
            RetrievedChunk(
                chunk_id=chunk.id,
                doc_id=chunk.doc_id,
                doc_name=doc_name,
                page=int(meta.get("page", 0) or 0),
                content=chunk.content,
                parent_content=chunk.parent_content or chunk.content,
                score=fused[chunk_id],
                rrf_score=fused[chunk_id],
                vector_rank=vector_ids.index(chunk_id) + 1 if chunk_id in vector_ids else None,
                bm25_rank=bm25_ids.index(chunk_id) + 1 if chunk_id in bm25_ids else None,
            )
        )

    if use_rerank and candidates:
        try:
            pairs = await rerank(
                query,
                [c.content for c in candidates],
                top_n=min(max(top_k * 2, top_k), len(candidates)),
            )
            query_terms = [t for t in tokens(query) if len(t) >= 2]
            reranked: list[RetrievedChunk] = []
            for index, score in pairs:
                if index >= len(candidates):
                    continue
                item = candidates[index]
                item.rerank_score = score
                # 标题命中词加分：商品名/型号出现在文档名中时，排序更贴近用户所指商品
                name_hits = sum(1 for term in query_terms if term in item.doc_name.lower())
                item.score = score + min(0.08, 0.04 * name_hits)
                if item.score >= settings.min_rerank_score:
                    reranked.append(item)
            reranked.sort(key=lambda c: c.score, reverse=True)
            reranked = dedupe_by_parent(reranked)
            if reranked:
                return reranked[:top_k]
        except Exception as exc:  # noqa: BLE001  重排失败则使用 RRF 顺序
            logger.warning("重排失败，使用 RRF 排序: %s", exc)

    return dedupe_by_parent(candidates)[:top_k]
