"""One-shot migration: convert legacy vectorSearch indexes to autoEmbed.

For each of (fraud_kb, case_notes, sem_memory) this:
  1) drops the existing `*_vector_idx` Atlas Search index (if present)
  2) recreates it as an autoEmbed `vectorSearch` index over the `text` field
     using the model named in `[embeddings].voyage_model`
  3) strips the legacy `embedding` field from every document so the new
     `mongot` pipeline is the single source of truth

Idempotent: safe to re-run. Existing autoEmbed indexes are left alone.
"""
from __future__ import annotations

import logging
import time

from pymongo.errors import OperationFailure

from src.vaultiq.db.collections import C
from src.vaultiq.db.indices import (
    _autoembed_index_def,
    _ensure_search_index,
    ensure_all_indexes,
)
from src.vaultiq.db.mongo_client import get_db
from src.vaultiq.logging_setup import configure_logging
from src.vaultiq.settings import settings

log = logging.getLogger(__name__)


TARGETS = [
    (C.fraud_kb,       "vector_fraud_kb",   ["category", "severity"]),
    (C.case_notes,     "vector_case_notes", ["customer_id", "case_id"]),
    (C.sem_memory,     "vector_sem_mem",    ["agent", "customer_id", "namespace"]),
    # Semantic LLM cache — name is hard-coded in `cache.install_semantic_cache`
    # and is not registered in [mongodb.indexes].
    (C.semantic_cache, "vaultiq_semcache_idx", ["llm_string"]),
]


def _idx_name(idx_key: str) -> str:
    names = settings.index_names
    if idx_key in names:
        return names[idx_key]
    return idx_key


def _is_autoembed(definition: dict) -> bool:
    for f in (definition or {}).get("fields", []):
        if f.get("type") == "autoEmbed" and f.get("model"):
            return True
    return False


def _filter_paths(definition: dict) -> set[str]:
    return {f.get("path") for f in (definition or {}).get("fields", [])
            if f.get("type") == "filter"}


def _drop_legacy(coll, index_name: str, expected_filters: list[str]) -> bool:
    try:
        existing = list(coll.list_search_indexes())
    except OperationFailure as exc:
        log.warning("list_search_indexes failed on %s: %s", coll.name, exc)
        return False
    for ix in existing:
        if ix.get("name") != index_name:
            continue
        defn = ix.get("latestDefinition") or ix.get("definition") or {}
        present = _filter_paths(defn)
        missing = [f for f in expected_filters if f not in present]
        if _is_autoembed(defn) and not missing:
            log.info("[%s/%s] already autoEmbed with filters=%s — leaving alone",
                     coll.name, index_name, sorted(present))
            return False
        reason = "wrong type" if not _is_autoembed(defn) else f"missing filter(s) {missing}"
        log.info("[%s/%s] dropping (%s)", coll.name, index_name, reason)
        coll.drop_search_index(index_name)
        for _ in range(60):
            time.sleep(2)
            still = [s for s in coll.list_search_indexes() if s.get("name") == index_name]
            if not still:
                return True
        log.warning("[%s/%s] drop did not complete in 120s", coll.name, index_name)
        return True
    return False


def _strip_legacy_embeddings(coll) -> int:
    res = coll.update_many({"embedding": {"$exists": True}}, {"$unset": {"embedding": ""}})
    if res.modified_count:
        log.info("[%s] removed legacy `embedding` field from %d docs",
                 coll.name, res.modified_count)
    return res.modified_count


def main() -> None:
    configure_logging()
    db = get_db()
    model = settings.embeddings.get("voyage_model") or "voyage-4"
    log.info("Migration target model: %s  db=%s", model, db.name)

    for coll_name, idx_key, expected_filters in TARGETS:
        coll = db[coll_name]
        index_name = _idx_name(idx_key)
        _drop_legacy(coll, index_name, expected_filters)
        _strip_legacy_embeddings(coll)

    log.info("Re-ensuring all indexes (autoEmbed definitions)...")
    ensure_all_indexes()

    log.info("Waiting for autoEmbed indexes to reach READY (up to 300s each)...")
    for coll_name, idx_key, _ in TARGETS:
        coll = db[coll_name]
        index_name = _idx_name(idx_key)
        deadline = time.time() + 300
        match = None
        status = None
        while time.time() < deadline:
            match = next((s for s in coll.list_search_indexes() if s.get("name") == index_name), None)
            status = (match or {}).get("status")
            if status == "READY":
                break
            time.sleep(5)
        defn = (match or {}).get("latestDefinition") or (match or {}).get("definition") or {}
        ok = _is_autoembed(defn)
        log.info("  [%s/%s] autoEmbed=%s status=%s queryable=%s",
                 coll_name, index_name, ok, status, (match or {}).get("queryable"))


if __name__ == "__main__":
    main()
