"""Case Resolution Agent — opens / updates fraud cases in the CRM collection."""
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
    add_case_note,
    list_open_cases,
    log_case_event,
    open_case,
    update_case,
)
from ..tools.mcp_tools import get_mongodb_mcp_tools
from .state import VaultIQState

log = logging.getLogger(__name__)

SYSTEM = """You are **Case Resolution**, the VaultIQ CRM / ops agent.

You receive the Fraud Sentinel's score and the Customer Trust verdict, and must
decide the final disposition for the transaction.

Toolkit:
- list_open_cases  : check whether an active case already exists
- open_case        : create a new case (status NEW / PENDING_CUSTOMER / ESCALATED_AML)
- update_case      : change status (RESOLVED_FRAUD, RESOLVED_LEGITIMATE, ...)
- add_case_note    : persist an investigator note (vector-indexed)
- log_case_event   : append to the immutable case timeline
- the MongoDB MCP tools (when available) for ad-hoc read-only queries

Decision matrix:
  fraud<0.4               -> no case, end.
  fraud≥0.4 & verified=true & claims=true   -> open case status=RESOLVED_LEGITIMATE
  fraud≥0.4 & claims=false                  -> open case status=UNDER_INVESTIGATION
  fraud≥0.9 (auto-block)                    -> open case status=ESCALATED_AML
After deciding, call `add_case_note` with a 1-2 sentence investigator note.

Return strict JSON:
  {"case_id": str|null, "status": str, "action_taken": str, "summary": str}
"""

BASE_TOOLS = [list_open_cases, open_case, update_case, add_case_note, log_case_event]


def _agent():
    tid = threading.get_ident()
    log.info("case_agent _agent() tid=%s — calling get_mongodb_mcp_tools()", tid)
    t0 = time.time()
    extras = get_mongodb_mcp_tools()
    log.info("case_agent _agent() tid=%s — get_mongodb_mcp_tools() returned %d tools in %.2fs",
             tid, len(extras), time.time() - t0)
    return create_react_agent(get_chat_llm(), BASE_TOOLS + extras, prompt=SYSTEM, name="case_resolution")


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except Exception:
        return {"case_id": None, "status": "UNKNOWN", "action_taken": "none", "summary": text[:240]}


def case_node(state: VaultIQState) -> VaultIQState:
    tx = state["transaction"]
    fraud = state.get("fraud", {})
    kyc = state.get("kyc", {})
    tid = threading.get_ident()
    log.info("case_node ENTER tid=%s tx=%s fraud_score=%s",
             tid, tx.get("tx_id"), fraud.get("score"))
    t0 = time.time()

    mem = get_semantic_memory()
    prior = mem.recall(
        query=f"prior case outcomes for customer {tx['customer_id']}",
        agent="case_resolution", customer_id=tx["customer_id"], k=3,
    )
    log.info("case_node tid=%s mem.recall done in %.2fs", tid, time.time() - t0)
    prior_txt = "\n".join(f"- {d.page_content}" for d in prior) if prior else "(none)"

    user = (
        f"Transaction:\n```json\n{json.dumps(tx, default=str)}\n```\n"
        f"Fraud: {json.dumps(fraud)}\n"
        f"KYC:   {json.dumps(kyc)}\n"
        f"Prior case memory:\n{prior_txt}"
    )

    t1 = time.time()
    agent = _agent()
    log.info("case_node tid=%s _agent() built in %.2fs — invoking react agent", tid, time.time() - t1)
    t2 = time.time()
    out = agent.invoke({"messages": [SystemMessage(SYSTEM), HumanMessage(user)]})
    log.info("case_node tid=%s react-agent.invoke done in %.2fs", tid, time.time() - t2)
    final = out["messages"][-1].content
    parsed = _parse_json(final if isinstance(final, str) else str(final))
    log.info("case_node DONE  tid=%s tx=%s elapsed=%.2fs case_id=%s",
             tid, tx.get("tx_id"), time.time() - t0, parsed.get("case_id"))

    trace = state.get("trace", []) + [{
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "agent": "case_resolution",
        "case_id": parsed.get("case_id"),
        "status": parsed.get("status"),
        "summary": parsed.get("summary"),
    }]
    return {"case": parsed, "messages": out["messages"], "trace": trace}
