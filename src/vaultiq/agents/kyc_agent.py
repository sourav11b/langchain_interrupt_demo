"""Customer Trust Agent — KYC verification + dispute confirmation."""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from ..llm.factory import get_chat_llm
from ..memory.semantic_memory import get_semantic_memory
from ..tools import (
    confirm_otp,
    flag_kyc_step_up,
    get_customer_profile,
    request_otp,
    verify_identity_factors,
)
from .state import VaultIQState

log = logging.getLogger(__name__)

SYSTEM = """You are **Customer Trust**, the VaultIQ KYC / verification agent.

You receive a flagged transaction and the Fraud Sentinel's score. In a real
deployment you would chat with the customer; in this demo you SIMULATE the
customer answer as a reasonable bank user (truthful in 80% of low/medium-risk
cases, denying obvious ATO/skim signals as "not me").

Toolkit:
- get_customer_profile     : registered identity factors
- verify_identity_factors  : check supplied factors against record
- request_otp / confirm_otp: (mock) one-time-password challenge
- flag_kyc_step_up         : persist a step-up flag

Required:
1. Always run `get_customer_profile` first.
2. If Fraud score >= 0.5, call `request_otp` and then simulate the customer
   confirming with the returned demo_code via `confirm_otp`.
3. Decide whether the customer claims the transaction.
4. Return strict JSON:
   {"verified": bool, "claims_transaction": bool, "factors_matched": int,
    "otp_used": bool, "summary": str}
"""

TOOLS = [
    get_customer_profile,
    verify_identity_factors,
    request_otp,
    confirm_otp,
    flag_kyc_step_up,
]


def _agent():
    return create_react_agent(get_chat_llm(), TOOLS, prompt=SYSTEM, name="customer_trust")


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except Exception:
        return {"verified": False, "claims_transaction": False, "factors_matched": 0,
                "otp_used": False, "summary": text[:240]}


def kyc_node(state: VaultIQState) -> VaultIQState:
    tx = state["transaction"]
    fraud = state.get("fraud", {})
    tid = threading.get_ident()
    log.info("kyc_node ENTER  tid=%s tx=%s fraud_score=%s",
             tid, tx.get("tx_id"), fraud.get("score"))
    t0 = time.time()
    mem = get_semantic_memory()
    prior = mem.recall(
        query=f"verification history for customer {tx['customer_id']}",
        agent="customer_trust", customer_id=tx["customer_id"], k=3,
    )
    log.info("kyc_node tid=%s mem.recall done in %.2fs", tid, time.time() - t0)
    prior_txt = "\n".join(f"- {d.page_content}" for d in prior) if prior else "(none)"

    user = (
        f"Transaction:\n```json\n{json.dumps(tx, default=str)}\n```\n"
        f"Fraud Sentinel: score={fraud.get('score')} band={fraud.get('band')} "
        f"reasons={fraud.get('reasons')}\n"
        f"Prior verification memory:\n{prior_txt}"
    )

    t1 = time.time()
    agent = _agent()
    out = agent.invoke({"messages": [SystemMessage(SYSTEM), HumanMessage(user)]})
    log.info("kyc_node tid=%s react-agent.invoke done in %.2fs", tid, time.time() - t1)
    final = out["messages"][-1].content
    parsed = _parse_json(final if isinstance(final, str) else str(final))
    log.info("kyc_node DONE   tid=%s tx=%s elapsed=%.2fs verified=%s",
             tid, tx.get("tx_id"), time.time() - t0, parsed.get("verified"))

    trace = state.get("trace", []) + [{
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "agent": "customer_trust",
        "verified": parsed.get("verified"),
        "claims_transaction": parsed.get("claims_transaction"),
        "summary": parsed.get("summary"),
    }]
    return {"kyc": parsed, "messages": out["messages"], "trace": trace}
