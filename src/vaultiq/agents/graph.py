"""Top-level LangGraph wiring for the VaultIQ 3-agent flow.

   transaction ─▶ Fraud Sentinel ─┬▶ low risk ─▶ persist memory ─▶ END
                                  └▶ medium/high ─▶ Customer Trust ─▶ Case Resolution ─▶ persist memory ─▶ END
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from langgraph.graph import END, START, StateGraph

from ..llm.cache import install_semantic_cache
from ..memory.checkpointer import get_checkpointer
from ..memory.semantic_memory import get_semantic_memory
from ..settings import settings
from .case_agent import case_node
from .fraud_agent import fraud_node
from .kyc_agent import kyc_node
from .state import VaultIQState

log = logging.getLogger(__name__)


def _route_after_fraud(state: VaultIQState) -> str:
    score = float(state.get("fraud", {}).get("score") or 0.0)
    threshold = float(settings.section("agents.fraud_sentinel").get("score_threshold", 0.65))
    return "customer_trust" if score >= threshold else "memory_writer"


def _route_after_kyc(_: VaultIQState) -> str:
    return "case_resolution"


def _memory_writer_node(state: VaultIQState) -> VaultIQState:
    """Persist a one-paragraph episodic memory at the end of the run."""
    mem = get_semantic_memory()
    tx = state.get("transaction", {})
    fraud = state.get("fraud", {})
    kyc = state.get("kyc", {})
    case = state.get("case", {})
    summary_parts = [
        f"tx={tx.get('tx_id')} amount={tx.get('amount')} merchant={tx.get('merchant_id')}",
        f"fraud_score={fraud.get('score')} band={fraud.get('band')}",
        f"reasons={fraud.get('reasons')}",
    ]
    if kyc:
        summary_parts.append(f"kyc verified={kyc.get('verified')} claims={kyc.get('claims_transaction')}")
    if case:
        summary_parts.append(f"case={case.get('case_id')} status={case.get('status')}")
    text = " | ".join(str(p) for p in summary_parts)

    for agent in ("fraud_sentinel", "customer_trust", "case_resolution"):
        if agent == "customer_trust" and not kyc:
            continue
        if agent == "case_resolution" and not case:
            continue
        try:
            mem.remember(text, agent=agent, customer_id=tx.get("customer_id"),
                         metadata={"tx_id": tx.get("tx_id"), "scenario": tx.get("scenario_id")})
        except Exception as exc:  # pragma: no cover
            log.warning("semantic_memory.remember failed for %s: %s", agent, exc)

    trace = state.get("trace", []) + [{
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "agent": "memory_writer",
        "summary": text,
    }]
    return {"trace": trace}


def build_graph():
    install_semantic_cache()
    g = StateGraph(VaultIQState)
    g.add_node("fraud_sentinel", fraud_node)
    g.add_node("customer_trust", kyc_node)
    g.add_node("case_resolution", case_node)
    g.add_node("memory_writer", _memory_writer_node)

    g.add_edge(START, "fraud_sentinel")
    g.add_conditional_edges("fraud_sentinel", _route_after_fraud,
                            {"customer_trust": "customer_trust", "memory_writer": "memory_writer"})
    g.add_conditional_edges("customer_trust", _route_after_kyc,
                            {"case_resolution": "case_resolution"})
    g.add_edge("case_resolution", "memory_writer")
    g.add_edge("memory_writer", END)
    return g.compile(checkpointer=get_checkpointer())


def run_once(transaction: dict, thread_id: str | None = None) -> VaultIQState:
    """Execute the full graph for a single transaction. Returns the final state."""
    graph = build_graph()
    cfg = {"configurable": {"thread_id": thread_id or f"vaultiq-{uuid.uuid4().hex[:8]}"}}
    initial: VaultIQState = {
        "transaction": transaction,
        "customer_id": transaction["customer_id"],
        "messages": [],
        "trace": [],
    }
    result = graph.invoke(initial, config=cfg)
    log.info("VaultIQ run done | tx=%s fraud=%s case=%s",
             transaction.get("tx_id"),
             result.get("fraud", {}).get("score"),
             result.get("case", {}).get("case_id"))
    return result
