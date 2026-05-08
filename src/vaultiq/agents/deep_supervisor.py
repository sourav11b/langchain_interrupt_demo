"""Optional Deep Agents (a2a) supervisor over the same three roles.

Builds a `deepagents.create_deep_agent` whose sub-agents are direct wrappers
around our Fraud Sentinel / Customer Trust / Case Resolution tool sets. This
gives an alternative entry point that demonstrates the Deep Agents
agent-to-agent pattern while reusing the rest of the VaultIQ stack.

Usage:
    from src.vaultiq.agents.deep_supervisor import build_deep_supervisor
    sup = build_deep_supervisor()
    sup.invoke({"messages": [{"role": "user", "content": "Investigate tx ..."}]})
"""
from __future__ import annotations

import logging
from typing import Any

from ..llm.factory import get_chat_llm
from ..tools import (
    add_case_note,
    confirm_otp,
    customer_velocity,
    device_owner_graph,
    distance_from_home_km,
    flag_kyc_step_up,
    fraud_kb_lookup,
    geo_velocity_anomaly,
    get_customer_profile,
    get_recent_transactions,
    last_tx_location,
    list_open_cases,
    log_case_event,
    mcc_burst,
    open_case,
    request_otp,
    score_transaction,
    update_case,
    verify_identity_factors,
)
from ..tools.mcp_tools import get_mongodb_mcp_tools

log = logging.getLogger(__name__)

SUPERVISOR_PROMPT = """You are the **VaultIQ supervisor** orchestrating three
specialist sub-agents:
  • fraud_sentinel  — scores suspicious transactions
  • customer_trust  — KYC verifies the customer
  • case_resolution — opens / updates the CRM case

For every transaction, dispatch in order: fraud_sentinel → (if score≥0.65)
customer_trust → case_resolution. Then summarise the final disposition."""


def build_deep_supervisor() -> Any:
    try:
        from deepagents import create_deep_agent
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("deepagents package not installed") from exc

    fraud_tools = [
        score_transaction, get_customer_profile, get_recent_transactions,
        distance_from_home_km, last_tx_location, geo_velocity_anomaly,
        customer_velocity, mcc_burst, device_owner_graph, fraud_kb_lookup,
    ]
    kyc_tools = [
        get_customer_profile, verify_identity_factors,
        request_otp, confirm_otp, flag_kyc_step_up,
    ]
    case_tools = [
        list_open_cases, open_case, update_case,
        add_case_note, log_case_event,
    ] + get_mongodb_mcp_tools()

    subagents = [
        {
            "name": "fraud_sentinel",
            "description": "Score and explain suspicion for a single transaction.",
            "prompt": "Score the transaction and return JSON {score, band, reasons, summary}.",
            "tools": fraud_tools,
        },
        {
            "name": "customer_trust",
            "description": "Verify the customer and confirm whether they made the transaction.",
            "prompt": "Run KYC factors + OTP, then return JSON {verified, claims_transaction, summary}.",
            "tools": kyc_tools,
        },
        {
            "name": "case_resolution",
            "description": "Open / update the fraud case and log evidence.",
            "prompt": "Decide case disposition and return JSON {case_id, status, action_taken, summary}.",
            "tools": case_tools,
        },
    ]

    return create_deep_agent(
        model=get_chat_llm(),
        tools=[],            # supervisor delegates everything to sub-agents
        instructions=SUPERVISOR_PROMPT,
        subagents=subagents,
    )
