"""Reproduce exactly what the Streamlit dropdown render path does, headless.

Used as a remote diagnostic. Will print a line per stage and a TRACEBACK if
any stage raises. Safe to delete after debugging.

    python -m scripts._repro_dropdown
"""
from __future__ import annotations

import json
import sys
import traceback
from pprint import pformat


def main() -> int:
    print("== stage 1: imports ==")
    from src.vaultiq.tools._common import jsonable
    from src.vaultiq.ui.stream_runner import (
        fetch_recent_case_events,
        fetch_recent_cases,
        fetch_recent_transactions,
    )

    print("== stage 2: fetch_recent_cases ==")
    cases = fetch_recent_cases(limit=15)
    print(f"  got {len(cases)} cases")
    for c in cases[:5]:
        print(f"   - {c.get('case_id')} {c.get('status')} {type(c.get('updated_at')).__name__}")

    if not cases:
        print("NO CASES — dropdown render path cannot be reproduced.")
        return 0

    sel_case = cases[0]["case_id"]
    print(f"== stage 3: fetch_recent_case_events({sel_case}) ==")
    evts = fetch_recent_case_events(sel_case, limit=20)
    print(f"  got {len(evts)} events")
    for e in evts[:3]:
        print(f"   - ts={type(e.get('ts')).__name__} type={e.get('type')} "
              f"payload_keys={list((e.get('payload') or {}).keys())}")
        for pk, pv in (e.get("payload") or {}).items():
            print(f"        payload[{pk}] -> {type(pv).__name__}")

    print("== stage 4: jsonable(payload) on every event ==")
    for i, e in enumerate(evts):
        try:
            cleaned = jsonable(e.get("payload", {}))
            json.dumps(cleaned)
        except Exception:
            print(f"  ❌ event #{i} payload jsonable+dumps FAILED:")
            print(pformat(e))
            traceback.print_exc()
            return 2
    print("  ✅ all event payloads jsonable-clean and json.dumps-clean")

    print("== stage 5: fetch_recent_transactions ==")
    txs = fetch_recent_transactions(limit=5)
    print(f"  got {len(txs)} txs")
    for t in txs[:3]:
        print(f"   - {t.get('tx_id')} ts_type={type(t.get('ts')).__name__}")

    print("\nALL CLEAR — dropdown render code path runs without error.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        print("UNCAUGHT EXCEPTION:")
        traceback.print_exc()
        sys.exit(99)
