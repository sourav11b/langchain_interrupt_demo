"""Background-friendly helpers used by the Streamlit dashboard.

These are pure functions that the UI calls to:
  • generate one synthetic transaction at a time (baseline traffic)
  • run a transaction through the agent graph
  • read recent activity back from MongoDB for the live panels
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from ..agents.graph import run_once
from ..db.collections import C
from ..db.mongo_client import get_db
from ..scenarios.injector import (
    SCENARIOS,
    build_scenario_transaction,
    pick_random_customer,
)
from ..settings import settings

log = logging.getLogger(__name__)


def generate_baseline_transaction() -> dict:
    """Generate one mostly-normal transaction (with rare baseline anomalies)."""
    fraud_ratio = float(settings.stream.get("fraud_ratio", 0.05))
    if random.random() < fraud_ratio:
        scenario = random.choice([s for s in SCENARIOS if s.id != "low_risk"])
    else:
        scenario = next(s for s in SCENARIOS if s.id == "low_risk")
    return build_scenario_transaction(scenario.id)


def persist_transaction(tx: dict) -> None:
    """Append the transaction to the time-series + geo collections."""
    db = get_db()
    db[C.transactions].insert_one(tx)
    merch = db[C.merchants].find_one({"merchant_id": tx.get("merchant_id")}, {"_geo": 1})
    if merch and merch.get("_geo"):
        db[C.transaction_geo].insert_one({
            "ts": tx["ts"],
            "tx_id": tx["tx_id"],
            "customer_id": tx["customer_id"],
            "location": {"type": "Point",
                         "coordinates": [merch["_geo"]["lon"], merch["_geo"]["lat"]]},
        })


def execute_through_agents(tx: dict) -> dict[str, Any]:
    """Persist the tx then run it through the LangGraph 3-agent flow."""
    persist_transaction(tx)
    started = datetime.now(tz=timezone.utc)
    result = run_once(tx)
    elapsed = (datetime.now(tz=timezone.utc) - started).total_seconds()
    get_db()[C.agent_metrics].insert_one({
        "ts": started, "agent": "vaultiq_graph", "elapsed_s": elapsed,
        "tx_id": tx["tx_id"], "fraud_score": (result.get("fraud") or {}).get("score"),
    })
    return result


def fetch_recent_transactions(limit: int = 30) -> list[dict]:
    cur = get_db()[C.transactions].find({}, {"_id": 0}).sort("ts", -1).limit(limit)
    return list(cur)


def fetch_recent_cases(limit: int = 20) -> list[dict]:
    cur = get_db()[C.cases].find({}, {"_id": 0}).sort("updated_at", -1).limit(limit)
    return list(cur)


def fetch_recent_case_events(case_id: str | None = None, limit: int = 50) -> list[dict]:
    q: dict = {}
    if case_id:
        q["case_id"] = case_id
    cur = get_db()[C.case_events].find(q, {"_id": 0}).sort("ts", -1).limit(limit)
    return list(cur)


def fetch_collection_counts() -> dict[str, int]:
    db = get_db()
    return {
        "customers": db[C.customers].estimated_document_count(),
        "merchants": db[C.merchants].estimated_document_count(),
        "transactions": db[C.transactions].estimated_document_count(),
        "edges": db[C.relationships].estimated_document_count(),
        "fraud_kb": db[C.fraud_kb].estimated_document_count(),
        "case_notes": db[C.case_notes].estimated_document_count(),
        "cases": db[C.cases].estimated_document_count(),
        "sem_memory": db[C.sem_memory].estimated_document_count(),
        "sem_cache": db[C.semantic_cache].estimated_document_count(),
    }


def fetch_score_histogram(hours: int = 1) -> list[dict]:
    since = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    pipeline = [
        {"$match": {"ts": {"$gte": since}, "fraud_score": {"$exists": True}}},
        {"$bucket": {
            "groupBy": "$fraud_score",
            "boundaries": [0, 0.2, 0.4, 0.65, 0.9, 1.01],
            "default": "other",
            "output": {"n": {"$sum": 1}},
        }},
    ]
    return list(get_db()[C.agent_metrics].aggregate(pipeline))
