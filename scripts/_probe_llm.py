"""Direct probe of the configured chat LLM, with hard timeout.

Bypasses LangGraph entirely. If this hangs > 30 s, the AzureChatOpenAI
endpoint / deployment / api-version is broken — that's why every agent
run hangs. Prints token-level latency so we can see where time is spent.
"""
from __future__ import annotations

import time
import threading

from langchain_core.messages import HumanMessage, SystemMessage

from src.vaultiq.llm.factory import get_chat_llm


def main() -> None:
    print("== building chat LLM ==")
    t0 = time.time()
    llm = get_chat_llm()
    print(f"  built in {time.time()-t0:.2f}s  type={type(llm).__name__}")

    # Watchdog: print every 5s while we wait for the LLM.
    done = threading.Event()

    def _heartbeat() -> None:
        i = 0
        while not done.wait(5):
            i += 5
            print(f"  ... still waiting on LLM ({i}s elapsed)")

    threading.Thread(target=_heartbeat, daemon=True).start()

    print("== invoking llm.invoke([sys, hello]) ==")
    t0 = time.time()
    try:
        out = llm.invoke([
            SystemMessage("Reply with exactly: ok"),
            HumanMessage("ping"),
        ])
        elapsed = time.time() - t0
        done.set()
        print(f"  returned in {elapsed:.2f}s")
        print(f"  type={type(out).__name__}")
        content = getattr(out, "content", out)
        print(f"  content={content!r}")
    except Exception as e:
        elapsed = time.time() - t0
        done.set()
        print(f"  FAILED after {elapsed:.2f}s")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
