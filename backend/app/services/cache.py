from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from typing import Any

import diskcache

from ..config import settings


def _norm(question: str) -> str:
    return "".join(question.lower().split())


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


class CacheService:
    """两级缓存：精确命中（字符串哈希）+ 语义命中（向量相似度）。"""

    def __init__(self) -> None:
        self._cache = diskcache.Cache(str(settings.cache_dir))
        self._lock = threading.Lock()

    @staticmethod
    def _exact_key(kb_id: str, question: str) -> str:
        digest = hashlib.sha256(f"{kb_id}:{_norm(question)}".encode()).hexdigest()
        return f"exact:{digest}"

    @staticmethod
    def _sem_key(kb_id: str) -> str:
        return f"sem:{kb_id}"

    def get_exact(self, kb_id: str, question: str) -> dict[str, Any] | None:
        value = self._cache.get(self._exact_key(kb_id, question))
        if isinstance(value, dict) and time.time() - value.get("ts", 0) < settings.cache_ttl_seconds:
            return value
        return None

    def set_exact(self, kb_id: str, question: str, payload: dict[str, Any]) -> None:
        payload = {**payload, "ts": time.time()}
        self._cache.set(self._exact_key(kb_id, question), payload, expire=settings.cache_ttl_seconds)

    def add_semantic(
        self,
        kb_id: str,
        question: str,
        embedding: list[float],
        payload: dict[str, Any],
    ) -> None:
        with self._lock:
            entries: list[dict[str, Any]] = self._cache.get(self._sem_key(kb_id)) or []
            now = time.time()
            entries = [e for e in entries if now - e.get("ts", 0) < settings.cache_ttl_seconds]
            entries.append(
                {
                    "question": question,
                    "embedding": embedding,
                    "payload": payload,
                    "ts": now,
                }
            )
            self._cache.set(
                self._sem_key(kb_id),
                entries[-settings.semantic_cache_max_entries :],
                expire=settings.cache_ttl_seconds * 24,
            )

    def get_semantic(
        self, kb_id: str, embedding: list[float], threshold: float | None = None
    ) -> tuple[dict[str, Any], float] | None:
        threshold = settings.semantic_cache_threshold if threshold is None else threshold
        entries: list[dict[str, Any]] = self._cache.get(self._sem_key(kb_id)) or []
        now = time.time()
        best: tuple[dict[str, Any], float] | None = None
        for entry in entries:
            if now - entry.get("ts", 0) >= settings.cache_ttl_seconds:
                continue
            score = _cosine(embedding, entry.get("embedding", []))
            if score >= threshold and (best is None or score > best[1]):
                best = (entry["payload"], score)
        return best

    def invalidate_kb(self, kb_id: str) -> int:
        removed = 0
        with self._lock:
            for key in list(self._cache.iterkeys()):
                if not isinstance(key, str):
                    continue
                value = self._cache.get(key)
                if isinstance(value, dict) and value.get("kb_id") == kb_id:
                    self._cache.delete(key)
                    removed += 1
                elif key == self._sem_key(kb_id):
                    self._cache.delete(key)
                    removed += 1
        return removed

    def stats(self) -> dict[str, Any]:
        return {"entries": len(self._cache), "volume_bytes": self._cache.volume()}

    def dump_exact(self, value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False)


cache_service = CacheService()
