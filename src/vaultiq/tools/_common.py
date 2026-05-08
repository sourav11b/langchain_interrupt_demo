"""Shared helpers for tools (json-safe coercion, customer lookups)."""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

try:
    from bson import ObjectId
except ImportError:  # pragma: no cover
    ObjectId = None  # type: ignore[assignment]


def jsonable(obj: Any) -> Any:
    """Recursively coerce arbitrary objects to JSON-serializable primitives.

    Handles dict / list / tuple / set, datetime, date, Decimal, UUID,
    and BSON ObjectId. Anything else falls back to ``str(obj)``.
    """
    if obj is None or isinstance(obj, (str, bool, int, float)):
        return obj
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()
                if not (isinstance(k, str) and k.startswith("_") and k != "_geo")}
    if isinstance(obj, (list, tuple, set)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, UUID):
        return str(obj)
    if ObjectId is not None and isinstance(obj, ObjectId):
        return str(obj)
    try:
        json.dumps(obj)
        return obj
    except TypeError:
        return str(obj)
