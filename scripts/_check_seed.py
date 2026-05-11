"""One-off check for the new cluster: counts + search-index state."""
from __future__ import annotations

from src.vaultiq.db.collections import C
from src.vaultiq.db.mongo_client import get_db


def main() -> None:
    db = get_db()
    existing = set(db.list_collection_names())

    print("--- Collection counts (all 22 the app touches) ---")
    groups = {
        "Seed": [
            C.customers, C.accounts, C.cards, C.devices, C.merchants,
            C.home_locations, C.merchant_geo, C.transaction_geo,
            C.relationships, C.fraud_kb, C.case_notes, C.cases, C.case_events,
        ],
        "Time-series": [C.transactions, C.agent_metrics],
        "Runtime / agent state": [
            C.sem_memory, C.checkpoints, C.checkpoint_writes,
            C.store, C.chat_history, C.semantic_cache, C.llm_cache,
        ],
    }
    for label, names in groups.items():
        print(f"  [{label}]")
        for n in names:
            present = n in existing
            count = db[n].estimated_document_count() if present else 0
            marker = "[x]" if present else "[ ]"
            print(f"    {marker} {n:<30} {count:>8} docs")

    print()
    print("--- Atlas Search indexes ---")
    for coll_name in [C.fraud_kb, C.case_notes, C.sem_memory, C.semantic_cache]:
        if coll_name not in existing:
            print(f"  {coll_name}: collection missing")
            continue
        try:
            idxs = list(db[coll_name].list_search_indexes())
        except Exception as e:
            print(f"  {coll_name}: list_search_indexes failed -> {e}")
            continue
        if not idxs:
            print(f"  {coll_name}: (no search indexes)")
            continue
        for ix in idxs:
            kind = ix.get("type", "?")
            name = ix.get("name", "?")
            status = ix.get("status", "?")
            queryable = ix.get("queryable", "?")
            print(f"  {coll_name:<25} {kind:<13} {name:<30} status={status} queryable={queryable}")


if __name__ == "__main__":
    main()
