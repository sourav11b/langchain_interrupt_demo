"""Bisect: which step of the agent flow hangs?

Tests in order, each with a 30s watchdog:
  1. semantic_memory.recall (vectorSearch on agent_semantic_mem)
  2. install_semantic_cache + llm.invoke (vectorSearch on llm_semantic_cache)
  3. fraud_kb_lookup (hybrid retrieval on fraud_kb)
  4. mem.remember (insert into agent_semantic_mem)
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


def _step(label: str, fn) -> bool:
    print(f"\n== {label} ==")
    done = threading.Event()
    threading.Thread(target=_hb, args=(label, done), daemon=True).start()
    t0 = time.time()
    try:
        out = fn()
        elapsed = time.time() - t0
        done.set()
        print(f"  OK in {elapsed:.2f}s  -> {repr(out)[:200]}")
        return True
    except Exception as e:
        elapsed = time.time() - t0
        done.set()
        print(f"  FAILED in {elapsed:.2f}s")
        traceback.print_exc()
        return False


def main() -> None:
    from langchain_core.messages import HumanMessage, SystemMessage

    from src.vaultiq.agents.fraud_agent import _agent as fraud_agent_factory  # noqa: F401
    from src.vaultiq.llm.cache import install_semantic_cache
    from src.vaultiq.llm.factory import get_chat_llm
    from src.vaultiq.memory.semantic_memory import get_semantic_memory
    from src.vaultiq.tools.fraud_tools import fraud_kb_lookup

    # Step 1: semantic_memory.recall — FIRST thing fraud_node does
    mem = get_semantic_memory()
    _step(
        "1. semantic_memory.recall (vectorSearch agent_semantic_mem)",
        lambda: list(mem.recall(query="test query", agent="fraud_sentinel",
                                customer_id="CUST000001", k=3)),
    )

    # Step 2: install_semantic_cache + llm.invoke (cache lookup hits llm_semantic_cache)
    install_semantic_cache()
    print("  cache installed")
    llm = get_chat_llm()
    _step(
        "2. llm.invoke with semantic cache wired (vectorSearch llm_semantic_cache)",
        lambda: llm.invoke([SystemMessage("Reply: ok"), HumanMessage("ping")]).content,
    )

    # Step 3: fraud_kb_lookup — hybrid retrieval on fraud_kb (10 docs)
    _step(
        "3. fraud_kb_lookup (hybrid vector+BM25 on fraud_kb)",
        lambda: fraud_kb_lookup.invoke({"query": "account takeover SIM swap", "k": 3}),
    )

    # Step 4: mem.remember (insert into agent_semantic_mem)
    _step(
        "4. semantic_memory.remember (INSERT agent_semantic_mem with autoEmbed)",
        lambda: mem.remember(
            text="probe: tx for CUST000001 amount=10",
            agent="fraud_sentinel", customer_id="CUST000001",
            metadata={"tx_id": "PROBE", "scenario": "probe"},
        ),
    )


if __name__ == "__main__":
    main()
