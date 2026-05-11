"""Run a single tx through fraud_node, then full graph, with watchdog.

Bisects whether the hang is in the react-agent tool loop, the kyc_node
LLM step, or the case_resolution_node MCP/MongoDB tool loop.
"""
from __future__ import annotations

import threading
import time
import traceback


def _hb(label: str, done: threading.Event) -> None:
    i = 0
    while not done.wait(5):
        i += 5
        print(f"  ... [{label}] still waiting ({i}s)")


def _step(label: str, fn) -> object:
    print(f"\n== {label} ==")
    done = threading.Event()
    threading.Thread(target=_hb, args=(label, done), daemon=True).start()
    t0 = time.time()
    try:
        out = fn()
        elapsed = time.time() - t0
        done.set()
        print(f"  OK in {elapsed:.2f}s")
        return out
    except Exception:
        elapsed = time.time() - t0
        done.set()
        print(f"  FAILED in {elapsed:.2f}s")
        traceback.print_exc()
        return None


def main() -> None:
    from src.vaultiq.agents.fraud_agent import fraud_node
    from src.vaultiq.agents.graph import run_once
    from src.vaultiq.ui.stream_runner import generate_baseline_transaction

    tx = generate_baseline_transaction()
    print(f"tx_id={tx['tx_id']} customer={tx['customer_id']} amt={tx['amount']}")

    # Step A: fraud_node alone (react-agent tool loop on Azure LLM)
    state_a = _step(
        "A. fraud_node(state) — react agent + tools",
        lambda: fraud_node({
            "transaction": tx,
            "customer_id": tx["customer_id"],
            "messages": [],
            "trace": [],
        }),
    )
    if isinstance(state_a, dict):
        f = state_a.get("fraud") or {}
        print(f"  fraud.score={f.get('score')} band={f.get('band')}")

    # Step B: full graph (fraud + maybe kyc/case + memory_writer)
    _step("B. run_once(tx) — full graph end-to-end",
          lambda: run_once(tx))


if __name__ == "__main__":
    main()
