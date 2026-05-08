"""Hybrid (vector + BM25) retriever for AutoEmbeddings-backed vector stores.

`langchain_mongodb.MongoDBAtlasHybridSearchRetriever` (0.11.x) calls
`embedding.embed_query()` on the client, which `AutoEmbeddings` rejects by
design. This subclass re-implements `_get_relevant_documents` using
`autoembedding_vector_search_stage`, so the vector half of the RRF pipeline
is computed by `mongot` server-side from the raw query text.
"""
from __future__ import annotations

import warnings
from typing import Any, List

from langchain_core.callbacks.manager import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_mongodb.embeddings import AutoEmbeddings
from langchain_mongodb.pipelines import (
    autoembedding_vector_search_stage,
    combine_pipelines,
    final_hybrid_stage,
    reciprocal_rank_stage,
    text_search_stage,
)
from langchain_mongodb.retrievers import MongoDBAtlasHybridSearchRetriever
from langchain_mongodb.utils import make_serializable


class AutoEmbedHybridSearchRetriever(MongoDBAtlasHybridSearchRetriever):
    """RRF-blended vector + BM25 retriever for AutoEmbeddings vector stores."""

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun, **kwargs: Any
    ) -> List[Document]:
        vs = self.vectorstore
        assert isinstance(vs._embedding, AutoEmbeddings), \
            "AutoEmbedHybridSearchRetriever requires an AutoEmbeddings vector store"

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            is_top_k_set = self.top_k is not None
        default_k = self.k if not is_top_k_set else self.top_k
        k: int = kwargs.get("k", default_k)

        pipeline: List[Any] = []

        vector_pipeline = [
            autoembedding_vector_search_stage(
                query=query,
                search_field=vs._text_key,
                index_name=vs._index_name,
                model=vs._embedding.model,
                top_k=k,
                filter=self.pre_filter,
                oversampling_factor=self.oversampling_factor,
            )
        ]
        vector_pipeline += reciprocal_rank_stage(
            score_field="vector_score",
            penalty=self.vector_penalty,
            weight=self.vector_weight,
        )
        combine_pipelines(pipeline, vector_pipeline, self.collection.name)

        text_pipeline = text_search_stage(
            query=query,
            search_field=vs._text_key,
            index_name=self.search_index_name,
            limit=k,
            filter=self.pre_filter,
        )
        text_pipeline.extend(reciprocal_rank_stage(
            score_field="fulltext_score",
            penalty=self.fulltext_penalty,
            weight=self.fulltext_weight,
        ))
        combine_pipelines(pipeline, text_pipeline, self.collection.name)

        pipeline.extend(final_hybrid_stage(
            scores_fields=["vector_score", "fulltext_score"], limit=k,
        ))
        if self.post_filter is not None:
            pipeline.extend(self.post_filter)

        cursor = self.collection.aggregate(pipeline)
        docs: List[Document] = []
        for res in cursor:
            if vs._text_key not in res:
                continue
            text = res.pop(vs._text_key)
            make_serializable(res)
            docs.append(Document(page_content=text, metadata=res))
        return docs
