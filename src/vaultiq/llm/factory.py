"""Chat LLM + embeddings factories.

Embeddings: Voyage finance-2 (primary) with Azure text-embedding-3-large
fallback. Both produce dense vectors used by every Atlas Vector Search index.
"""
from __future__ import annotations

import logging
import os
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
    cfg = settings.embeddings
    primary = (cfg.get("primary_provider") or "voyage").lower()
    if primary == "voyage" and cfg.get("voyage_api_key"):
        try:
            from langchain_voyageai import VoyageAIEmbeddings
            log.info("Using VoyageAIEmbeddings model=%s", cfg["voyage_model"])
            return VoyageAIEmbeddings(
                voyage_api_key=cfg["voyage_api_key"],
                model=cfg["voyage_model"],
            )
        except Exception as exc:  # pragma: no cover - fallback path
            log.warning("Voyage embeddings unavailable (%s); falling back to Azure", exc)

    from langchain_openai import AzureOpenAIEmbeddings
    log.info("Using AzureOpenAIEmbeddings deployment=%s", cfg["azure_deployment"])
    return AzureOpenAIEmbeddings(
        azure_endpoint=settings.llm["azure_endpoint"],
        api_key=settings.llm["azure_api_key"],
        api_version=settings.llm["azure_api_version"],
        azure_deployment=cfg["azure_deployment"],
    )


def embedding_dimensions() -> int:
    cfg = settings.embeddings
    primary = (cfg.get("primary_provider") or "voyage").lower()
    if primary == "voyage":
        return int(cfg.get("voyage_dimensions", 1024))
    return int(cfg.get("azure_dimensions", 3072))
