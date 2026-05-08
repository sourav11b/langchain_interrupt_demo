"""Shared graph state for the 3-agent VaultIQ flow."""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class VaultIQState(TypedDict, total=False):
    # Inputs
    transaction: dict[str, Any]
    customer_id: str

    # Inter-agent results
    fraud: dict[str, Any]      # {score, band, reasons, summary}
    kyc: dict[str, Any]        # {verified, factors_matched, otp_required, ...}
    case: dict[str, Any]       # {case_id, status, ...}

    # Conversation traces (each agent appends here)
    messages: Annotated[list[AnyMessage], add_messages]

    # Audit trail
    trace: list[dict[str, Any]]
