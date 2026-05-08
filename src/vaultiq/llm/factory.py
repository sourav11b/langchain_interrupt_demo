"""Chat LLM + embeddings factories.

Embeddings: `langchain_mongodb.AutoEmbeddings` — vectors are generated and
stored server-side by MongoDB Atlas (`mongot` calls Voyage AI directly), so
no client-side embedding library is required.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel

from ..settings import settings

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_chat_llm() -> BaseChatModel:
    cfg = settings.llm
    from langchain_openai import AzureChatOpenAI
    return AzureChatOpenAI(
        azure_endpoint=cfg["azure_endpoint"],
        api_key=cfg["azure_api_key"],
        api_version=cfg["azure_api_version"],
        azure_deployment=cfg["azure_deployment"],
        temperature=float(cfg.get("temperature", 0.1)),
        max_tokens=int(cfg.get("max_tokens", 1024)),
        timeout=60,
    )


@lru_cache(maxsize=1)
def get_embeddings() -> Embeddings:
    """Return an `AutoEmbeddings` instance bound to the configured Voyage model.

    With AutoEmbeddings the client never embeds text — `MongoDBAtlasVectorSearch`
    detects the type and forwards raw text to Atlas's `$vectorSearch` stage,
    which embeds and indexes server-side via the model named here.
    """
    from langchain_mongodb.embeddings import AutoEmbeddings
    model = settings.embeddings.get("voyage_model") or "voyage-4"
    log.info("Using AutoEmbeddings model=%s (Atlas-managed)", model)
    return AutoEmbeddings(model=model)
