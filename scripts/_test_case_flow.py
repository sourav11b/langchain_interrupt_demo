"""Smoke-test the new fetch_case_flow + render_case_flow path against live data.

Pulls a few recent cases from MongoDB and prints the structure that the new
visual will receive. Doesn't mount any UI; just validates the data wiring.
"""
from __future__ import annotations

import sys
from src.vaultiq.ui.stream_runner import fetch_recent_cases, fetch_case_flow


def main() -> int:
    cases = fetch_recent_cases(5)
    print(f"recent cases in DB: {len(cases)}")
    if not cases:
        print("(no cases yet — run a scenario via the dashboard or "
              "`python -m scripts.run_one --scenario ato_sim_swap`)")
        return 0

    for c in cases[:3]:
        cid = c.get("case_id")
        print(f"\n--- {cid} ---")
        flow = fetch_case_flow(cid)
        case = flow["case"] or {}
        print(f"  status   = {case.get('status')}")
        print(f"  score    = {case.get('score')}")
        reasons = case.get("reasons") or []
        print(f"  reasons  = {reasons[:4]}{'…' if len(reasons) > 4 else ''}")
        print(f"  events   = {len(flow['events'])}")
        print(f"  tx?      = {flow['transaction'] is not None}")
        print(f"  cust?    = {flow['customer'] is not None}")
        tx = flow["transaction"]
        if tx:
            print(f"    tx.amount   = {tx.get('amount')}")
            print(f"    tx.merchant = {tx.get('merchant_id')}")
            print(f"    tx.id       = {tx.get('tx_id')}")
        for e in flow["events"]:
            print(f"    evt {e.get('ts')} {e.get('type')} payload={e.get('payload')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
