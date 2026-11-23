"""纯函数：RRF 融合与父块去重。"""

from __future__ import annotations

import pytest

from app.rag.retriever import RetrievedChunk, dedupe_by_parent, rrf_fuse


def _chunk(
    chunk_id: str,
    *,
    doc_id: str = "doc1",
    parent: str | None = "同一个父块",
    score: float = 1.0,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        doc_name="商品.md",
        page=1,
        content=f"子块-{chunk_id}",
        parent_content=parent or f"父块-{chunk_id}",
        score=score,
    )


def test_rrf_fuse_sums_reciprocal_ranks() -> None:
    fused = rrf_fuse([["a", "b"], ["b", "c"]], k=0)
    # a 只在第一路排第 1 → 1.0；b 两路都有 → 1/2 + 1/1 = 1.5
    assert fused["a"] == pytest.approx(1.0)
    assert fused["b"] == pytest.approx(1.5)
    assert fused["c"] == pytest.approx(0.5)
    assert list(fused) == ["a", "b", "c"]


def test_rrf_fuse_default_k_keeps_order() -> None:
    fused = rrf_fuse([["x", "y"]])
    assert fused["x"] > fused["y"]


def test_rrf_fuse_empty_input() -> None:
    assert rrf_fuse([]) == {}
    assert rrf_fuse([[], []]) == {}


def test_dedupe_by_parent_keeps_first_highest() -> None:
    items = [
        _chunk("c1", score=0.9),
        _chunk("c2", score=0.5),  # 同 doc 同父块 → 丢弃
        _chunk("c3", parent="另一个父块", score=0.7),
    ]
    unique = dedupe_by_parent(items)
    assert [item.chunk_id for item in unique] == ["c1", "c3"]


def test_dedupe_by_parent_distinguishes_documents() -> None:
    items = [_chunk("c1", doc_id="doc1"), _chunk("c2", doc_id="doc2")]
    assert len(dedupe_by_parent(items)) == 2


def test_dedupe_by_parent_falls_back_to_content() -> None:
    items = [
        RetrievedChunk(
            chunk_id="c1", doc_id="d", doc_name="n", page=1, content="甲", parent_content=""
        ),
        RetrievedChunk(
            chunk_id="c2", doc_id="d", doc_name="n", page=1, content="甲", parent_content=""
        ),
    ]
    assert len(dedupe_by_parent(items)) == 1
