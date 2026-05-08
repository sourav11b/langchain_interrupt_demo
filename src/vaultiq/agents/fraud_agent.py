"""Fraud Sentinel Agent — detection + scoring."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from ..llm.factory import get_chat_llm
from ..memory.semantic_memory import get_semantic_memory
from ..tools import (
    customer_velocity,
    device_owner_graph,
    distance_from_home_km,
    fraud_kb_lookup,
    geo_velocity_anomaly,
    get_customer_profile,
    get_recent_transactions,
    last_tx_location,
    mcc_burst,
    score_transaction,
)
from .state import VaultIQState

log = logging.getLogger(__name__)

SYSTEM = """You are **Fraud Sentinel**, the VaultIQ first-line fraud detection agent.

Mission: given a single payment transaction, decide a calibrated fraud score
(0.0–1.0) and a short justification.

Your toolkit (use freely, in any order):
- score_transaction        : deterministic baseline score + reasons
- get_customer_profile     : structured KYC + risk_score
- get_recent_transactions  : time-series velocity context
- distance_from_home_km / last_tx_location / geo_velocity_anomaly : geospatial
- device_owner_graph       : graph traversal over devices/customers
- customer_velocity / mcc_burst : time-series aggregates
- fraud_kb_lookup          : hybrid search across the fraud knowledge base

Steps:
1. Always call `score_transaction` first.
2. If score < 0.4, briefly justify and stop.
3. Otherwise blend in geo / velocity / graph / KB context as needed.
4. Final answer MUST be valid JSON with keys:
   {"score": float, "band": "low|medium|high|critical", "reasons": [str], "summary": str}
"""

TOOLS = [
    score_transaction,
    get_customer_profile,
    get_recent_transactions,
    distance_from_home_km,
    last_tx_location,
    geo_velocity_anomaly,
    customer_velocity,
    mcc_burst,
    device_owner_graph,
    fraud_kb_lookup,
]


def _agent():
    return create_react_agent(get_chat_llm(), TOOLS, prompt=SYSTEM, name="fraud_sentinel")


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except Exception:
        return {"score": 0.0, "band": "low", "reasons": ["unparseable"], "summary": text[:240]}


def fraud_node(state: VaultIQState) -> VaultIQState:
    tx = state["transaction"]
    mem = get_semantic_memory()
    recall = mem.recall(
        query=f"prior fraud episodes for customer {tx['customer_id']} amount {tx['amount']}",
        agent="fraud_sentinel",
        customer_id=tx["customer_id"],
        k=3,
    )
    prior = "\n".join(f"- {d.page_content}" for d in recall) if recall else "(none)"
    user = (
        f"Score this transaction:\n```json\n{json.dumps(tx, default=str)}\n```\n\n"
        f"Relevant prior agent memory:\n{prior}"
    )

    agent = _agent()
    out = agent.invoke({"messages": [SystemMessage(SYSTEM), HumanMessage(user)]})
    final = out["messages"][-1].content
    parsed = _parse_json(final if isinstance(final, str) else str(final))

    trace = state.get("trace", []) + [{
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "agent": "fraud_sentinel",
        "score": parsed.get("score"),
        "band": parsed.get("band"),
        "summary": parsed.get("summary"),
    }]
    return {"fraud": parsed, "messages": out["messages"], "trace": trace}
