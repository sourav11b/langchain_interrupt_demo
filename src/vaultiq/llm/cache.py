"""Install MongoDB Atlas semantic LLM cache globally for LangChain."""
from __future__ import annotations

import logging

from langchain_core.globals import set_llm_cache

from ..db.collections import C
from ..settings import settings
from .factory import get_embeddings

log = logging.getLogger(__name__)

_INSTALLED = False


def install_semantic_cache() -> None:
    """Wire `MongoDBAtlasSemanticCache` as the global LLM cache."""
    global _INSTALLED
    if _INSTALLED:
        return
    cfg = settings.section("semantic_cache")
    if not cfg.get("enabled", True):
        log.info("Semantic cache disabled by config")
        _INSTALLED = True
        return

    from langchain_mongodb.cache import MongoDBAtlasSemanticCache

    cache = MongoDBAtlasSemanticCache(
        connection_string=settings.mongo_uri,
        database_name=settings.mongo_db,
        collection_name=C.semantic_cache,
        embedding=get_embeddings(),
        index_name="vaultiq_semcache_idx",
        score_threshold=float(cfg.get("score_threshold", 0.92)),
    )
    set_llm_cache(cache)
    _INSTALLED = True
    log.info("MongoDBAtlasSemanticCache installed (collection=%s)", C.semantic_cache)
