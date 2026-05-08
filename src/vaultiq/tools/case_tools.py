"""Case Resolution agent tools — CRM-style case lifecycle in MongoDB."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from langchain_core.tools import tool

from ..db.collections import C
from ..db.mongo_client import get_db
from ..llm.factory import get_embeddings
from ..settings import settings
from ._common import jsonable

VALID_STATUSES = {"NEW", "PENDING_CUSTOMER", "UNDER_INVESTIGATION", "RESOLVED_FRAUD",
                  "RESOLVED_LEGITIMATE", "ESCALATED_AML"}


@tool
def open_case(customer_id: str, tx_id: str, score: float, reasons: list[str],
              initial_status: str = "NEW") -> dict:
    """Open a fraud investigation case linked to a transaction."""
    if initial_status not in VALID_STATUSES:
        initial_status = "NEW"
    case = {
        "case_id": f"CASE-{uuid.uuid4().hex[:10].upper()}",
        "customer_id": customer_id,
        "tx_id": tx_id,
        "status": initial_status,
        "score": score,
        "reasons": reasons,
        "created_at": datetime.now(tz=timezone.utc),
        "updated_at": datetime.now(tz=timezone.utc),
    }
    get_db()[C.cases].insert_one(case)
    log_case_event.invoke({"case_id": case["case_id"], "event_type": "opened",
                           "payload": {"score": score, "reasons": reasons}})
    return jsonable(case)


@tool
def update_case(case_id: str, status: str | None = None,
                fields: dict[str, Any] | None = None) -> dict:
    """Update case status and/or arbitrary fields on the case document."""
    upd: dict[str, Any] = {"updated_at": datetime.now(tz=timezone.utc)}
    if status:
        if status not in VALID_STATUSES:
            return {"error": f"invalid status {status}"}
        upd["status"] = status
    upd.update(fields or {})
    get_db()[C.cases].update_one({"case_id": case_id}, {"$set": upd})
    log_case_event.invoke({"case_id": case_id, "event_type": "updated", "payload": upd})
    doc = get_db()[C.cases].find_one({"case_id": case_id}, {"_id": 0})
    return jsonable(doc or {})


@tool
def log_case_event(case_id: str, event_type: str, payload: dict | None = None) -> dict:
    """Append an immutable event to the case timeline."""
    evt = {
        "ts": datetime.now(tz=timezone.utc),
        "case_id": case_id,
        "type": event_type,
        "payload": payload or {},
    }
    get_db()[C.case_events].insert_one(evt)
    return jsonable(evt)


@tool
def list_open_cases(customer_id: str | None = None, limit: int = 10) -> list[dict]:
    """List recent non-terminal cases (optionally filtered by customer)."""
    q: dict[str, Any] = {"status": {"$nin": ["RESOLVED_FRAUD", "RESOLVED_LEGITIMATE"]}}
    if customer_id:
        q["customer_id"] = customer_id
    cur = get_db()[C.cases].find(q, {"_id": 0}).sort("updated_at", -1).limit(limit)
    return [jsonable(d) for d in cur]


@tool
def add_case_note(case_id: str, customer_id: str, note: str) -> dict:
    """Persist an investigator note (vector-indexed for hybrid retrieval)."""
    emb = get_embeddings().embed_query(note)
    doc = {
        "case_id": case_id,
        "customer_id": customer_id,
        "ts": datetime.now(tz=timezone.utc),
        "text": note,
        "embedding": emb,
    }
    get_db()[C.case_notes].insert_one(doc)
    log_case_event.invoke({"case_id": case_id, "event_type": "note_added",
                           "payload": {"len": len(note)}})
    return {"case_id": case_id, "stored": True}
