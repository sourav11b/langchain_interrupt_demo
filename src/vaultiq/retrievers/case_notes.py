"""Case-notes retrievers (vector + hybrid) for prior-investigation recall."""
from __future__ import annotations

from functools import lru_cache

from langchain_core.retrievers import BaseRetriever
from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_mongodb.retrievers import MongoDBAtlasHybridSearchRetriever

from ..db.collections import C
from ..db.mongo_client import get_collection
from ..llm.factory import get_embeddings
from ..settings import settings


@lru_cache(maxsize=1)
def case_notes_vectorstore() -> MongoDBAtlasVectorSearch:
    return MongoDBAtlasVectorSearch(
        collection=get_collection("case_notes"),
        embedding=get_embeddings(),
        index_name=settings.index_names["vector_case_notes"],
        text_key="text",
        embedding_key="embedding",
        relevance_score_fn="cosine",
    )


def case_notes_vector_retriever(k: int = 4, customer_id: str | None = None) -> BaseRetriever:
    kw: dict = {"k": k}
    if customer_id:
        kw["pre_filter"] = {"customer_id": customer_id}
    return case_notes_vectorstore().as_retriever(search_kwargs=kw)


def case_notes_hybrid_retriever(k: int = 4) -> MongoDBAtlasHybridSearchRetriever:
    return MongoDBAtlasHybridSearchRetriever(
        vectorstore=case_notes_vectorstore(),
        search_index_name=settings.index_names["fts_case_notes"],
        top_k=k,
    )
