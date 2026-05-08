"""Time-series tools — velocity / burst detection over the `transactions` TS coll."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from langchain_core.tools import tool

from ..db.collections import C
from ..db.mongo_client import get_db


@tool
def customer_velocity(customer_id: str, minutes: int = 60) -> dict:
    """Count + sum of transactions for the customer in the last `minutes`."""
    since = datetime.now(tz=timezone.utc) - timedelta(minutes=minutes)
    pipeline = [
        {"$match": {"customer_id": customer_id, "ts": {"$gte": since}}},
        {"$group": {
            "_id": None,
            "count": {"$sum": 1},
            "sum_amount": {"$sum": "$amount"},
            "max_amount": {"$max": "$amount"},
            "distinct_countries": {"$addToSet": "$country"},
        }},
        {"$project": {
            "_id": 0, "count": 1, "sum_amount": 1, "max_amount": 1,
            "distinct_country_count": {"$size": "$distinct_countries"},
        }},
    ]
    docs = list(get_db()[C.transactions].aggregate(pipeline))
    return docs[0] if docs else {"count": 0, "sum_amount": 0, "max_amount": 0, "distinct_country_count": 0}


@tool
def mcc_burst(merchant_category: str, minutes: int = 15, min_count: int = 5) -> dict:
    """Detect a burst of transactions in a given MCC across all customers
    (BIN-attack / coordinated abuse signal)."""
    since = datetime.now(tz=timezone.utc) - timedelta(minutes=minutes)
    pipeline = [
        {"$match": {"merchant_category": merchant_category, "ts": {"$gte": since}}},
        {"$group": {
            "_id": "$customer_id",
            "n": {"$sum": 1},
            "total": {"$sum": "$amount"},
        }},
        {"$match": {"n": {"$gte": 1}}},
    ]
    rows = list(get_db()[C.transactions].aggregate(pipeline))
    burst = sum(r["n"] for r in rows)
    return {
        "merchant_category": merchant_category,
        "window_minutes": minutes,
        "tx_count": burst,
        "unique_customers": len(rows),
        "burst": burst >= min_count,
    }
