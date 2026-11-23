from __future__ import annotations

import asyncio
import threading
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from ..config import settings


class VectorStore:
    """Chroma 本地持久化向量库封装（同步客户端放到线程池执行，避免阻塞事件循环）。"""

    COLLECTION = "kb_chunks"

    def __init__(self) -> None:
        self._client: chromadb.ClientAPI | None = None
        self._collection: Any = None
        # 使用可重入锁：_col() 内部也会加锁，普通 Lock 会导致首次调用自锁死
        self._lock = threading.RLock()

    def _col(self):  # noqa: ANN202
        if self._collection is None:
            with self._lock:
                if self._collection is None:
                    self._client = chromadb.PersistentClient(
                        path=str(settings.chroma_dir),
                        settings=ChromaSettings(anonymized_telemetry=False, allow_reset=False),
                    )
                    self._collection = self._client.get_or_create_collection(
                        name=self.COLLECTION,
                        metadata={"hnsw:space": "cosine"},
                        embedding_function=None,
                    )
        return self._collection

    async def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        def run() -> None:
            with self._lock:
                self._col().upsert(
                    ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas
                )

        await asyncio.to_thread(run)

    async def query(self, kb_id: str, embedding: list[float], top_k: int) -> list[dict[str, Any]]:
        def run() -> dict[str, Any]:
            with self._lock:
                return self._col().query(
                    query_embeddings=[embedding],
                    n_results=top_k,
                    where={"kb_id": kb_id},
                    include=["documents", "metadatas", "distances"],
                )

        result = await asyncio.to_thread(run)
        ids = (result.get("ids") or [[]])[0]
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        hits: list[dict[str, Any]] = []
        for i, chunk_id in enumerate(ids):
            meta = metas[i] or {}
            hits.append(
                {
                    "chunk_id": chunk_id,
                    "doc_id": meta.get("doc_id", ""),
                    "page": int(meta.get("page", 0) or 0),
                    "document": docs[i] or "",
                    "score": 1.0 - float(distances[i]),
                }
            )
        return hits

    async def delete_doc(self, doc_id: str) -> None:
        def run() -> None:
            with self._lock:
                self._col().delete(where={"doc_id": doc_id})

        await asyncio.to_thread(run)

    async def delete_kb(self, kb_id: str) -> None:
        def run() -> None:
            with self._lock:
                self._col().delete(where={"kb_id": kb_id})

        await asyncio.to_thread(run)

    async def count(self) -> int:
        def run() -> int:
            with self._lock:
                return int(self._col().count())

        return await asyncio.to_thread(run)


vector_store = VectorStore()
