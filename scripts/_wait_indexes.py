"""Poll Atlas Search indexes until they're queryable, or 3 min timeout."""
from __future__ import annotations

import time

from src.vaultiq.db.collections import C
from src.vaultiq.db.mongo_client import get_db


def main() -> None:
    db = get_db()
    targets = [
        (C.sem_memory, "sem_mem_vector_idx"),
        (C.semantic_cache, "vaultiq_semcache_idx"),
    ]
    deadline = time.time() + 180
    while time.time() < deadline:
        pending = []
        for coll, name in targets:
            idxs = list(db[coll].list_search_indexes())
            ix = next((i for i in idxs if i.get("name") == name), None)
            if ix is None:
                pending.append((coll, name, "MISSING"))
                continue
            if not ix.get("queryable"):
                pending.append((coll, name, ix.get("status"), ix.get("queryable")))
        if not pending:
            print("all vectorSearch indexes READY + queryable")
            break
        ts = time.strftime("%H:%M:%S")
        print(f"  {ts} still building: {pending}")
        time.sleep(8)
    else:
        print("TIMED OUT after 180s — still building, not blocking the seed")

    print()
    print("--- final state ---")
    for coll, name in targets:
        idxs = list(db[coll].list_search_indexes())
        ix = next((i for i in idxs if i.get("name") == name), None)
        if ix:
            print(
                f"  {coll:<25} {name:<30} "
                f"status={ix.get('status')} queryable={ix.get('queryable')}"
            )
        else:
            print(f"  {coll:<25} {name:<30} MISSING")


if __name__ == "__main__":
    main()
