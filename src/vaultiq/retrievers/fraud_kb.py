"""Fraud knowledge base retrievers (vector / full-text / hybrid).

Backed by collection `C.fraud_kb` which contains scenario playbooks, fraud
typologies, and policy snippets created by `data/seed_data.py`.
"""
from __future__ import annotations

from functools import lru_cache

from langchain_core.retrievers import BaseRetriever
from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_mongodb.retrievers import MongoDBAtlasFullTextSearchRetriever

from ..db.collections import C
from ..db.mongo_client import get_collection
from ..llm.factory import get_embeddings
from ..settings import settings
from ._auto_hybrid import AutoEmbedHybridSearchRetriever


@lru_cache(maxsize=1)
def fraud_kb_vectorstore() -> MongoDBAtlasVectorSearch:
    return MongoDBAtlasVectorSearch(
        collection=get_collection("fraud_kb"),
        embedding=get_embeddings(),
        index_name=settings.index_names["vector_fraud_kb"],
        text_key="text",
        embedding_key=None,
        relevance_score_fn=None,
        dimensions=-1,
        auto_create_index=False,
    )


def fraud_kb_vector_retriever(k: int = 5) -> BaseRetriever:
    return fraud_kb_vectorstore().as_retriever(search_kwargs={"k": k})


def fraud_kb_fts_retriever(k: int = 5) -> MongoDBAtlasFullTextSearchRetriever:
    return MongoDBAtlasFullTextSearchRetriever(
        collection=get_collection("fraud_kb"),
        search_index_name=settings.index_names["fts_fraud_kb"],
        search_field="text",
        top_k=k,
    )


def fraud_kb_hybrid_retriever(k: int = 5, vector_weight: float = 0.6) -> AutoEmbedHybridSearchRetriever:
    return AutoEmbedHybridSearchRetriever(
        vectorstore=fraud_kb_vectorstore(),
        search_index_name=settings.index_names["fts_fraud_kb"],
        top_k=k,
        vector_penalty=1.0 - vector_weight,
        fulltext_penalty=vector_weight,
    )
