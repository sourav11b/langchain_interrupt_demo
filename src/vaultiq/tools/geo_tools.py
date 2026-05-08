"""Geo tools — 2dsphere lookups + Haversine on PolyStorage geo collections."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from langchain_core.tools import tool

from ..db.collections import C
from ..db.mongo_client import get_db


def _home_point(customer_id: str) -> tuple[float, float] | None:
    doc = get_db()[C.home_locations].find_one({"customer_id": customer_id})
    if not doc:
        return None
    lon, lat = doc["location"]["coordinates"]
    return (lon, lat)


def _last_tx_point(customer_id: str) -> tuple[float, float] | None:
    doc = (
        get_db()[C.transaction_geo]
        .find({"customer_id": customer_id})
        .sort("ts", -1)
        .limit(1)
    )
    docs = list(doc)
    if not docs:
        return None
    lon, lat = docs[0]["location"]["coordinates"]
    return (lon, lat)


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = math.radians(a[0]), math.radians(a[1])
    lon2, lat2 = math.radians(b[0]), math.radians(b[1])
    dlon, dlat = lon2 - lon1, lat2 - lat1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


@tool
def distance_from_home_km(customer_id: str, lon: float, lat: float) -> float:
    """Great-circle distance (km) from customer's home location to (lon,lat)."""
    home = _home_point(customer_id)
    if not home:
        return -1.0
    return round(_distance_km(home, (lon, lat)), 2)


@tool
def last_tx_location(customer_id: str) -> dict:
    """Most recent transaction location stored in `transaction_geo`."""
    p = _last_tx_point(customer_id)
    if not p:
        return {}
    return {"lon": p[0], "lat": p[1]}


@tool
def geo_velocity_anomaly(customer_id: str, lon: float, lat: float,
                         window_minutes: int = 120) -> dict:
    """Return implied speed (km/h) needed to travel from last tx to (lon,lat)
    within `window_minutes`. >800 km/h is physically impossible."""
    db = get_db()
    last = list(
        db[C.transaction_geo].find({"customer_id": customer_id}).sort("ts", -1).limit(1)
    )
    if not last:
        return {"speed_kmh": 0.0, "anomaly": False}
    prev = last[0]
    prev_pt = tuple(prev["location"]["coordinates"])
    dt = datetime.now(tz=timezone.utc) - prev["ts"]
    hours = max(dt.total_seconds() / 3600, 1 / 60)
    dist = _distance_km(prev_pt, (lon, lat))
    speed = dist / hours
    return {
        "distance_km": round(dist, 2),
        "elapsed_minutes": round(dt.total_seconds() / 60, 1),
        "speed_kmh": round(speed, 1),
        "anomaly": speed > 800 and dt < timedelta(minutes=window_minutes),
    }
