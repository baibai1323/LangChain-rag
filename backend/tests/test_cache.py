from __future__ import annotations

import pytest

from app.config import settings
from app.services.cache import CacheService


@pytest.fixture()
def cache(monkeypatch: pytest.MonkeyPatch, tmp_path) -> CacheService:
    # cache_dir 是派生属性，只能替换 data_dir
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return CacheService()


def test_exact_cache_normalizes_case_and_spaces(cache: CacheService) -> None:
    cache.set_exact("kb1", "X50  多少钱", {"kb_id": "kb1", "answer": "3999"})
    hit = cache.get_exact("kb1", "x50多少钱")
    assert hit is not None
    assert hit["answer"] == "3999"


def test_exact_cache_is_scoped_by_kb(cache: CacheService) -> None:
    cache.set_exact("kb1", "问题", {"kb_id": "kb1", "answer": "A"})
    assert cache.get_exact("kb2", "问题") is None


def test_exact_cache_rejects_stale_timestamp(cache: CacheService) -> None:
    """绕过磁盘 TTL，直接写入 ts=0 的旧值，验证业务层的时间判断。"""
    key = cache._exact_key("kb1", "问题")
    cache._cache.set(key, {"kb_id": "kb1", "answer": "旧答案", "ts": 0})
    assert cache.get_exact("kb1", "问题") is None


def test_semantic_cache_hits_above_threshold(cache: CacheService) -> None:
    cache.add_semantic("kb1", "问题A", [1.0, 0.0], {"kb_id": "kb1", "answer": "A"})
    hit = cache.get_semantic("kb1", [1.0, 0.0], threshold=0.95)
    assert hit is not None
    payload, score = hit
    assert payload["answer"] == "A"
    assert score == pytest.approx(1.0)


def test_semantic_cache_misses_below_threshold(cache: CacheService) -> None:
    cache.add_semantic("kb1", "问题A", [1.0, 0.0], {"kb_id": "kb1", "answer": "A"})
    assert cache.get_semantic("kb1", [0.0, 1.0], threshold=0.95) is None


def test_invalidate_kb_removes_exact_and_semantic_entries(cache: CacheService) -> None:
    cache.set_exact("kb1", "问题", {"kb_id": "kb1", "answer": "A"})
    cache.add_semantic("kb1", "问题", [1.0, 0.0], {"kb_id": "kb1", "answer": "A"})
    assert cache.invalidate_kb("kb1") >= 2
    assert cache.get_exact("kb1", "问题") is None
    assert cache.get_semantic("kb1", [1.0, 0.0]) is None
