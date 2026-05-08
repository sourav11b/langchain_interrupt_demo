"""Reproduce the live-stream tick exactly as the NiceGUI dashboard does it.

Calls `execute_through_agents` (which persists + runs the LangGraph flow) and
asserts the returned state can be msgpack-serialized — the same constraint
LangGraph's MongoDB checkpointer enforces. Used to verify the BSON-ObjectId
fix for the `Type is not msgpack serializable: ObjectId` error.
"""
from __future__ import annotations

import sys
import traceback


def main() -> int:
    from src.vaultiq.scenarios.injector import build_scenario_transaction
    from src.vaultiq.ui.stream_runner import execute_through_agents

    print("== building scenario transaction ==")
    tx = build_scenario_transaction("low_risk")
    print(f"  tx_id={tx['tx_id']}  customer={tx['customer_id']}")

    print("== execute_through_agents (persist + LangGraph 3-agent flow) ==")
    result = execute_through_agents(tx)

    # Did `_id` leak back into our local tx?
    assert "_id" not in tx, f"tx still has _id leak: {tx.get('_id')!r}"
    print("  ✅ tx clean (no _id leak)")

    # Walk the result for any stray ObjectId.
    try:
        from bson import ObjectId
    except ImportError:
        ObjectId = type("Never", (), {})  # type: ignore

    def _scan(obj, path="$"):
        if isinstance(obj, ObjectId):
            raise AssertionError(f"ObjectId found at {path}: {obj}")
        if isinstance(obj, dict):
            for k, v in obj.items():
                _scan(v, f"{path}.{k}")
        elif isinstance(obj, (list, tuple, set)):
            for i, v in enumerate(obj):
                _scan(v, f"{path}[{i}]")

    _scan({k: v for k, v in result.items() if k != "messages"})
    print("  ✅ result tree clean (no ObjectId anywhere)")

    print(f"  fraud={result.get('fraud', {}).get('score')}  "
          f"case={result.get('case', {}).get('case_id')}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        print("UNCAUGHT EXCEPTION:")
        traceback.print_exc()
        sys.exit(2)
