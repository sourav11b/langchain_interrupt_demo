"""Graph tools using MongoDB `$graphLookup` over the `relationships` edges."""
from __future__ import annotations

from langchain_core.tools import tool

from ..db.collections import C
from ..db.mongo_client import get_db


@tool
def device_owner_graph(device_id: str, max_depth: int = 2) -> list[dict]:
    """Walk the entity graph outward from `device_id` to surface other customers
    or merchants connected within `max_depth` hops. Useful for ring detection.
    """
    db = get_db()
    pipeline = [
        {"$match": {"to": device_id}},
        {"$graphLookup": {
            "from": C.relationships,
            "startWith": "$from",
            "connectFromField": "to",
            "connectToField": "from",
            "as": "neighbours",
            "maxDepth": max_depth,
            "depthField": "depth",
        }},
        {"$project": {
            "_id": 0, "seed_from": "$from",
            "neighbours.from": 1, "neighbours.to": 1,
            "neighbours.type": 1, "neighbours.depth": 1, "neighbours.weight": 1,
        }},
        {"$limit": 25},
    ]
    return list(db[C.relationships].aggregate(pipeline))


@tool
def customer_merchant_path(customer_id: str, merchant_id: str, max_depth: int = 3) -> dict:
    """Does the customer have any (multi-hop) prior relationship with the
    merchant? Used to flag first-time-ever interactions on high-risk MCCs.
    """
    db = get_db()
    pipeline = [
        {"$match": {"from": customer_id}},
        {"$graphLookup": {
            "from": C.relationships,
            "startWith": "$to",
            "connectFromField": "to",
            "connectToField": "from",
            "as": "path",
            "maxDepth": max_depth,
            "depthField": "depth",
            "restrictSearchWithMatch": {"to": merchant_id},
        }},
        {"$match": {"path.0": {"$exists": True}}},
        {"$limit": 1},
    ]
    hit = list(db[C.relationships].aggregate(pipeline))
    return {"connected": bool(hit), "path_len": (hit[0]["path"][0]["depth"] + 1) if hit else None}
