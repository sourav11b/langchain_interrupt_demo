"""Idempotent creation of every index VaultIQ needs.

Covers:
  • regular B-tree indexes (structured lookups)
  • 2dsphere geo indexes
  • time-series collections
  • Atlas Vector Search indexes (vector + filter fields)
  • Atlas Search (BM25) indexes for full-text + hybrid retrieval
"""
from __future__ import annotations

import logging
import time
from typing import Any

from pymongo import ASCENDING, DESCENDING, GEOSPHERE
from pymongo.errors import CollectionInvalid, OperationFailure

from ..settings import settings
from .collections import C
from .mongo_client import get_db

log = logging.getLogger(__name__)


# ── time-series ──────────────────────────────────────────────────────────────
def _ensure_timeseries(name: str, time_field: str, meta_field: str, granularity: str = "seconds") -> None:
    db = get_db()
    if name in db.list_collection_names():
        return
    try:
        db.create_collection(
            name,
            timeseries={"timeField": time_field, "metaField": meta_field, "granularity": granularity},
        )
        log.info("Created time-series collection %s", name)
    except CollectionInvalid:
        pass


# ── structured + geo ─────────────────────────────────────────────────────────
def _ensure_btree() -> None:
    db = get_db()
    db[C.customers].create_index([("customer_id", ASCENDING)], unique=True, name="customer_id_uniq")
    db[C.customers].create_index([("email", ASCENDING)], name="email_idx")
    db[C.accounts].create_index([("account_id", ASCENDING)], unique=True, name="account_id_uniq")
    db[C.accounts].create_index([("customer_id", ASCENDING)], name="acc_cust_idx")
    db[C.cards].create_index([("card_id", ASCENDING)], unique=True, name="card_id_uniq")
    db[C.cards].create_index([("customer_id", ASCENDING)], name="card_cust_idx")
    db[C.devices].create_index([("device_id", ASCENDING)], unique=True, name="device_id_uniq")
    db[C.merchants].create_index([("merchant_id", ASCENDING)], unique=True, name="merch_id_uniq")
    db[C.merchants].create_index([("category", ASCENDING)], name="merch_cat_idx")
    db[C.cases].create_index([("case_id", ASCENDING)], unique=True, name="case_id_uniq")
    db[C.cases].create_index([("customer_id", ASCENDING), ("status", ASCENDING)], name="case_cust_status")
    db[C.case_events].create_index([("case_id", ASCENDING), ("ts", DESCENDING)], name="case_evt_idx")
    db[C.relationships].create_index([("from", ASCENDING), ("type", ASCENDING)], name="edge_from_type")
    db[C.relationships].create_index([("to", ASCENDING), ("type", ASCENDING)], name="edge_to_type")
    log.info("B-tree indexes ready")


def _ensure_geo() -> None:
    db = get_db()
    db[C.home_locations].create_index([("location", GEOSPHERE)], name="home_geo_idx")
    db[C.merchant_geo].create_index([("location", GEOSPHERE)], name="merch_geo_idx")
    db[C.transaction_geo].create_index([("location", GEOSPHERE)], name="tx_geo_idx")
    db[C.transaction_geo].create_index([("customer_id", ASCENDING), ("ts", DESCENDING)], name="tx_geo_cust_ts")
    log.info("2dsphere geo indexes ready")


# ── Atlas Search / Vector Search ─────────────────────────────────────────────
def _vector_index_def(field: str, dims: int, filters: list[str] | None = None) -> dict[str, Any]:
    fields: list[dict[str, Any]] = [
        {"type": "vector", "path": field, "numDimensions": dims, "similarity": "cosine"}
    ]
    for f in filters or []:
        fields.append({"type": "filter", "path": f})
    return {"fields": fields}


def _fts_index_def(text_field: str) -> dict[str, Any]:
    return {
        "mappings": {
            "dynamic": False,
            "fields": {text_field: {"type": "string", "analyzer": "lucene.standard"}},
        }
    }


def _ensure_collection(name: str) -> None:
    """Create an empty collection if it does not yet exist.

    Atlas Search / Vector Search index creation requires the target
    collection to physically exist; pre-creating it makes the index step
    safe to run before any documents have been inserted.
    """
    db = get_db()
    if name in db.list_collection_names():
        return
    try:
        db.create_collection(name)
        log.info("Created empty collection %s (for search index)", name)
    except CollectionInvalid:
        pass


def _ensure_search_index(coll_name: str, index_name: str, kind: str, definition: dict[str, Any]) -> None:
    _ensure_collection(coll_name)
    db = get_db()
    coll = db[coll_name]
    try:
        existing = {ix["name"] for ix in coll.list_search_indexes()}
    except OperationFailure as exc:
        log.warning("list_search_indexes failed on %s: %s", coll_name, exc)
        existing = set()
    if index_name in existing:
        return
    try:
        coll.create_search_index({"name": index_name, "type": kind, "definition": definition})
        log.info("Created %s search index %s on %s", kind, index_name, coll_name)
    except OperationFailure as exc:
        log.warning("Could not create search index %s on %s: %s", index_name, coll_name, exc)


def _ensure_vector_indexes() -> None:
    dims = int(settings.embeddings.get("voyage_dimensions", 1024))
    idx = settings.index_names
    _ensure_search_index(
        C.fraud_kb, idx["vector_fraud_kb"], "vectorSearch",
        _vector_index_def("embedding", dims, ["category", "severity"]),
    )
    _ensure_search_index(
        C.case_notes, idx["vector_case_notes"], "vectorSearch",
        _vector_index_def("embedding", dims, ["customer_id", "case_id"]),
    )
    _ensure_search_index(
        C.sem_memory, idx["vector_sem_mem"], "vectorSearch",
        _vector_index_def("embedding", dims, ["agent", "customer_id", "namespace"]),
    )
    _ensure_search_index(C.fraud_kb, idx["fts_fraud_kb"], "search", _fts_index_def("text"))
    _ensure_search_index(C.case_notes, idx["fts_case_notes"], "search", _fts_index_def("text"))


# ── public ───────────────────────────────────────────────────────────────────
def ensure_all_indexes() -> None:
    _ensure_timeseries(C.transactions, time_field="ts", meta_field="customer_id", granularity="seconds")
    _ensure_timeseries(C.agent_metrics, time_field="ts", meta_field="agent", granularity="seconds")
    _ensure_btree()
    _ensure_geo()
    _ensure_vector_indexes()
    log.info("All VaultIQ indexes ensured.")
    time.sleep(0.5)
