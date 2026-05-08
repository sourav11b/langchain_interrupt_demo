"""Logical → physical collection name registry.

Lets the rest of the codebase write `C.transactions` instead of magic strings,
while the actual names live in `config/vaultiq.properties`.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..settings import settings


def _n(key: str) -> str:
    return settings.coll(key)


@dataclass(frozen=True)
class _Collections:
    # structured
    customers: str = _n("customers")
    accounts: str = _n("accounts")
    devices: str = _n("devices")
    merchants: str = _n("merchants")
    cards: str = _n("cards")
    # timeseries
    transactions: str = _n("transactions")
    agent_metrics: str = _n("agent_metrics")
    # geo
    home_locations: str = _n("home_locations")
    merchant_geo: str = _n("merchant_geo")
    transaction_geo: str = _n("transaction_geo")
    # graph
    relationships: str = _n("relationships")
    # vector / unstructured
    fraud_kb: str = _n("fraud_kb")
    case_notes: str = _n("case_notes")
    sem_memory: str = _n("sem_memory")
    # crm
    cases: str = _n("cases")
    case_events: str = _n("case_events")
    # langgraph
    checkpoints: str = _n("checkpoints")
    checkpoint_writes: str = _n("checkpoint_writes")
    store: str = _n("store")
    chat_history: str = _n("chat_history")
    # cache
    semantic_cache: str = _n("semantic_cache")
    llm_cache: str = _n("llm_cache")


C = _Collections()
