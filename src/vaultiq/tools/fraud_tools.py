"""Fraud Sentinel tools — scoring + recall."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from langchain_core.tools import tool

from ..db.collections import C
from ..db.mongo_client import get_db
from ..retrievers.fraud_kb import fraud_kb_hybrid_retriever
from ._common import jsonable
from .geo_tools import _distance_km, _home_point, _last_tx_point


@tool
def get_customer_profile(customer_id: str) -> dict:
    """Return the structured customer profile (KYC level, country, etc.)."""
    doc = get_db()[C.customers].find_one({"customer_id": customer_id}, {"_id": 0, "_geo": 0})
    return jsonable(doc or {})


@tool
def get_recent_transactions(customer_id: str, hours: int = 24, limit: int = 25) -> list[dict]:
    """Pull the customer's most recent transactions from the time-series collection."""
    since = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    cur = (
        get_db()[C.transactions]
        .find({"customer_id": customer_id, "ts": {"$gte": since}}, {"_id": 0})
        .sort("ts", -1)
        .limit(limit)
    )
    return [jsonable(d) for d in cur]


@tool
def fraud_kb_lookup(query: str, k: int = 4) -> list[dict]:
    """Hybrid (vector + BM25) search over the fraud knowledge base."""
    docs = fraud_kb_hybrid_retriever(k=k).invoke(query)
    return [{"title": d.metadata.get("title"),
             "category": d.metadata.get("category"),
             "severity": d.metadata.get("severity"),
             "text": d.page_content} for d in docs]


def _heuristic_score(tx: dict) -> tuple[float, list[str]]:
    """Cheap, deterministic features the LLM can blend with KB context."""
    reasons: list[str] = []
    score = 0.0

    amt = float(tx.get("amount", 0))
    if amt > 1000:
        score += 0.25; reasons.append(f"high amount ${amt:.2f}")
    if amt < 5 and tx.get("channel") == "ecom":
        score += 0.25; reasons.append("micro CNP probe charge")

    cust = get_db()[C.customers].find_one({"customer_id": tx["customer_id"]}, {"country": 1, "risk_score": 1})
    if cust:
        if tx.get("country") and tx["country"] != cust.get("country"):
            score += 0.20; reasons.append(f"foreign country {tx['country']} vs home {cust.get('country')}")
        score += float(cust.get("risk_score", 0)) * 0.5

    if tx.get("merchant_category") in {"gambling", "crypto", "wire"}:
        score += 0.15; reasons.append(f"high-risk MCC ({tx['merchant_category']})")

    home = _home_point(tx["customer_id"])
    last = _last_tx_point(tx["customer_id"])
    if last and home:
        # If injected tx itself has merchant geo, use that
        merch = get_db()[C.merchants].find_one({"merchant_id": tx.get("merchant_id")}, {"_geo": 1})
        if merch and merch.get("_geo"):
            d = _distance_km(last, (merch["_geo"]["lon"], merch["_geo"]["lat"]))
            if d > 1500:
                score += 0.30; reasons.append(f"geo-velocity jump {d:.0f}km from last tx")

    dev = get_db()[C.devices].find_one({"device_id": tx.get("device_id"), "customer_id": tx["customer_id"]})
    if dev is None:
        score += 0.20; reasons.append("unrecognised device")
    elif not dev.get("trusted"):
        score += 0.05; reasons.append("untrusted device")

    return min(1.0, round(score, 3)), reasons


@tool
def score_transaction(transaction: dict) -> dict:
    """Compute a deterministic baseline fraud score with explanations.

    The Fraud Sentinel agent calls this first, then optionally refines with
    `fraud_kb_lookup` to combine policy context.
    """
    score, reasons = _heuristic_score(transaction)
    band = "low" if score < 0.4 else ("medium" if score < 0.65 else ("high" if score < 0.9 else "critical"))
    return {
        "tx_id": transaction.get("tx_id"),
        "customer_id": transaction.get("customer_id"),
        "score": score,
        "band": band,
        "reasons": reasons,
    }
