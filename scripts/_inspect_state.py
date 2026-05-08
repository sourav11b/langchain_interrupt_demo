"""Quick remote diagnostic: counts + most-recent docs across the live DB."""
from __future__ import annotations

from pprint import pformat

from src.vaultiq.db.collections import C
from src.vaultiq.db.mongo_client import get_db


def main() -> None:
    db = get_db()
    for c in (C.transactions, C.cases, C.case_events, C.agent_metrics,
              C.fraud_kb, C.case_notes, C.sem_memory):
        try:
            n = db[c].count_documents({})
        except Exception as exc:
            n = f"ERR {exc!r}"
        print(f"{c:30s} {n}")

    print("\n--- last agent_metric ---")
    last = list(db[C.agent_metrics].find({}, {"_id": 0}).sort("ts", -1).limit(1))
    print(pformat(last[0]) if last else "(none)")

    print("\n--- last 3 cases ---")
    for c in db[C.cases].find({}, {"_id": 0}).sort("updated_at", -1).limit(3):
        print(pformat(c))

    print("\n--- last 5 case events ---")
    for e in db[C.case_events].find({}, {"_id": 0}).sort("ts", -1).limit(5):
        print(pformat(e))


if __name__ == "__main__":
    main()
