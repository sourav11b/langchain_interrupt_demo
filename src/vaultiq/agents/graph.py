"""Top-level LangGraph wiring for the VaultIQ 3-agent flow.

   transaction ─▶ Fraud Sentinel ─┬▶ low risk ─▶ persist memory ─▶ END
                                  └▶ medium/high ─▶ Customer Trust ─▶ Case Resolution ─▶ persist memory ─▶ END

Setting `VAULTIQ_USE_DEEP_AGENT=1` swaps `run_once` over to the alternative
Deep Agents (a2a) supervisor in `deep_supervisor.py` while keeping the same
return shape for the dashboard / scripts.
"""
from __future__ import annotations

import json
import logging
import os
import re
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


# Runtime override settable from the UI — when not None it wins over the env var.
_ORCHESTRATOR_OVERRIDE: bool | None = None


def _env_says_deep() -> bool:
    return os.getenv("VAULTIQ_USE_DEEP_AGENT", "").strip().lower() in {"1", "true", "yes", "on"}


def _use_deep_agent() -> bool:
    return _ORCHESTRATOR_OVERRIDE if _ORCHESTRATOR_OVERRIDE is not None else _env_says_deep()


def set_orchestrator_override(use_deep: bool | None) -> None:
    """UI hook: force `deep` (True), `standard` (False), or clear back to env (None)."""
    global _ORCHESTRATOR_OVERRIDE
    _ORCHESTRATOR_OVERRIDE = use_deep
    log.info("orchestrator override -> %s (env=%s, effective=%s)",
             _ORCHESTRATOR_OVERRIDE, _env_says_deep(), _use_deep_agent())


def get_orchestrator_state() -> dict:
    """Snapshot for UI rendering: env vs override vs effective choice."""
    return {
        "env_deep": _env_says_deep(),
        "override": _ORCHESTRATOR_OVERRIDE,
        "active": "deep_agent" if _use_deep_agent() else "standard",
    }


# Cached supervisor — building it pulls in MCP tools and is not cheap.
_DEEP_SUPERVISOR = None


def _get_deep_supervisor():
    global _DEEP_SUPERVISOR
    if _DEEP_SUPERVISOR is None:
        from .deep_supervisor import build_deep_supervisor
        _DEEP_SUPERVISOR = build_deep_supervisor()
    return _DEEP_SUPERVISOR


_JSON_BLOB_RE = re.compile(r"\{[^{}]*\}")


def _extract_json_blobs(messages: list) -> list[dict]:
    """Pull every parseable JSON object out of the supervisor's message stream."""
    out: list[dict] = []
    for m in messages:
        content = getattr(m, "content", m if isinstance(m, str) else "")
        if not isinstance(content, str):
            continue
        for blob in _JSON_BLOB_RE.findall(content):
            try:
                obj = json.loads(blob)
            except Exception:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def _project_deep_result(transaction: dict, raw: dict) -> VaultIQState:
    """Coerce the deep supervisor's `{messages: [...]}` output into VaultIQState."""
    messages = raw.get("messages", []) if isinstance(raw, dict) else []
    blobs = _extract_json_blobs(messages)
    fraud, kyc, case = {}, {}, {}
    for obj in blobs:
        if not fraud and "score" in obj and "band" in obj:
            fraud = obj
        elif not kyc and ("verified" in obj or "claims_transaction" in obj):
            kyc = obj
        elif not case and ("case_id" in obj or "status" in obj):
            case = obj

    trace = [{
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "agent": "deep_supervisor",
        "summary": f"deep-agent run · msgs={len(messages)} · json_blobs={len(blobs)}",
        "score": fraud.get("score"),
        "band": fraud.get("band"),
    }]
    state: VaultIQState = {
        "transaction": transaction,
        "customer_id": transaction["customer_id"],
        "messages": messages,
        "trace": trace,
    }
    if fraud:
        state["fraud"] = fraud
    if kyc:
        state["kyc"] = kyc
    if case:
        state["case"] = case
    return state


def _run_once_deep(transaction: dict, thread_id: str | None) -> VaultIQState:
    sup = _get_deep_supervisor()
    cfg = {"configurable": {"thread_id": thread_id or f"vaultiq-deep-{uuid.uuid4().hex[:8]}"}}
    user = (
        "Investigate this payment transaction end-to-end. Dispatch the sub-agents "
        "in order (fraud_sentinel → customer_trust if score≥0.65 → case_resolution) "
        "and return each sub-agent's JSON verbatim.\n\n"
        f"```json\n{json.dumps(transaction, default=str)}\n```"
    )
    raw = sup.invoke({"messages": [{"role": "user", "content": user}]}, config=cfg)
    return _project_deep_result(transaction, raw)


def run_once(transaction: dict, thread_id: str | None = None) -> VaultIQState:
    """Execute the full graph for a single transaction. Returns the final state."""
    if _use_deep_agent():
        log.info("VaultIQ run via Deep Agents supervisor (VAULTIQ_USE_DEEP_AGENT=1)")
        result = _run_once_deep(transaction, thread_id)
        log.info("VaultIQ deep-agent run done | tx=%s fraud=%s case=%s",
                 transaction.get("tx_id"),
                 result.get("fraud", {}).get("score"),
                 result.get("case", {}).get("case_id"))
        return result

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
