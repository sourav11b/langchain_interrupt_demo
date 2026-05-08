"""Shared helpers for tools (json-safe coercion, customer lookups)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any


def jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items() if not k.startswith("_") or k == "_geo"}
    if isinstance(obj, list):
        return [jsonable(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    try:
        json.dumps(obj)
        return obj
    except TypeError:
        return str(obj)
