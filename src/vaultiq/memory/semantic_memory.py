"""Long-term semantic memory for VaultIQ agents.

Each agent can `recall(query)` similar past episodes and, at the end of every
graph run, the orchestrator calls `remember(...)` to persist a compact summary
into Atlas Vector Search.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from langchain_core.documents import Document
from langchain_mongodb import MongoDBAtlasVectorSearch

from ..db.collections import C
from ..db.mongo_client import get_collection
from ..llm.factory import get_embeddings
from ..settings import settings

log = logging.getLogger(__name__)


class SemanticMemory:
    """Thin wrapper over `MongoDBAtlasVectorSearch` for episodic agent memory."""

    def __init__(self) -> None:
        self._coll = get_collection("sem_memory")
        self._store = MongoDBAtlasVectorSearch(
            collection=self._coll,
            embedding=get_embeddings(),
            index_name=settings.index_names["vector_sem_mem"],
            text_key="text",
            embedding_key="embedding",
            relevance_score_fn="cosine",
        )

    # ── write ────────────────────────────────────────────────────────────────
    def remember(
        self,
        text: str,
        *,
        agent: str,
        customer_id: str | None = None,
        namespace: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        meta = {
            "agent": agent,
            "namespace": namespace,
            "customer_id": customer_id,
            "ts": datetime.now(tz=timezone.utc),
            **(metadata or {}),
        }
        ids = self._store.add_texts([text], metadatas=[meta])
        log.debug("semantic_memory.remember agent=%s id=%s", agent, ids[0])
        return ids[0]

    # ── read ─────────────────────────────────────────────────────────────────
    def recall(
        self,
        query: str,
        *,
        agent: str | None = None,
        customer_id: str | None = None,
        k: int | None = None,
    ) -> list[Document]:
        k = k or int(settings.section("semantic_memory").get("top_k", 4))
        pre_filter: dict[str, Any] = {}
        if agent:
            pre_filter["agent"] = agent
        if customer_id:
            pre_filter["customer_id"] = customer_id
        try:
            return self._store.similarity_search(query, k=k, pre_filter=pre_filter or None)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("semantic_memory.recall failed: %s", exc)
            return []


@lru_cache(maxsize=1)
def get_semantic_memory() -> SemanticMemory:
    return SemanticMemory()
