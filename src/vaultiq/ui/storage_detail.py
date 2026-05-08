"""PolyStorage drill-down page (`/storage`).

Shows every collection in the `langchain_interrupt_demo` database grouped by
storage shape (structured, time-series, geospatial, graph, vector + FTS,
LangGraph state, cache), with live document counts, real Atlas indices
discovered via `list_indexes()` + `list_search_indexes()`, and a sample doc.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from nicegui import ui

from src.vaultiq.db.collections import C
from src.vaultiq.db.mongo_client import get_db
from src.vaultiq.tools._common import jsonable

log = logging.getLogger(__name__)


# (group title, accent colour, [(logical_name, physical_name, blurb), …])
GROUPS: list[tuple[str, str, list[tuple[str, str, str]]]] = [
    ("Structured (B-tree)", "#94a3b8", [
        ("customers",       C.customers,       "KYC profile, risk score, country."),
        ("accounts",        C.accounts,        "Account balance + open date."),
        ("cards",           C.cards,           "Per-customer card metadata."),
        ("devices",         C.devices,         "Customer device fingerprints."),
        ("merchants",       C.merchants,       "MCC + risk + home geo."),
        ("cases",           C.cases,           "Open / closed fraud cases (CRM)."),
        ("case_events",     C.case_events,     "Immutable per-case event timeline."),
    ]),
    ("Time-series", "#fbbf24", [
        ("transactions",    C.transactions,    "Live tx stream (timeField=ts, meta=customer_id)."),
        ("agent_metrics",   C.agent_metrics,   "Per-graph-run latency + score."),
    ]),
    ("Geospatial (2dsphere)", "#34d399", [
        ("home_locations",   C.home_locations,   "Customer home points (GeoJSON Point)."),
        ("merchant_geo",     C.merchant_geo,     "Merchant locations."),
        ("transaction_geo",  C.transaction_geo,  "Per-tx point cache for $near / Haversine."),
    ]),
    ("Graph (edges + $graphLookup)", "#a78bfa", [
        ("relationships",    C.relationships,    "Edges: OWNS_CARD, USES_DEVICE, TRANSACTED_WITH."),
    ]),
    ("Vector + Full-text (Atlas Search)", "#ff6b6b", [
        ("fraud_kb",         C.fraud_kb,         "Fraud-typology KB (vector + BM25)."),
        ("case_notes",       C.case_notes,       "Investigator notes (vector + BM25)."),
        ("sem_memory",       C.sem_memory,       "Long-term per-agent semantic memory."),
    ]),
    ("LangGraph state", "#4dabf7", [
        ("checkpoints",       C.checkpoints,       "MongoDBSaver checkpoint snapshots."),
        ("checkpoint_writes", C.checkpoint_writes, "Per-step delta writes."),
        ("store",             C.store,             "Long-term MongoDB store key/value."),
        ("chat_history",      C.chat_history,      "MongoDBChatMessageHistory per session."),
    ]),
    ("LLM cache", "#f87171", [
        ("semantic_cache",   C.semantic_cache,   "MongoDBAtlasSemanticCache (similarity-keyed LLM cache)."),
        ("llm_cache",        C.llm_cache,        "Optional exact-match LLM cache."),
    ]),
]


def _list_indexes(coll_name: str) -> list[dict[str, Any]]:
    db = get_db()
    out: list[dict[str, Any]] = []
    try:
        for idx in db[coll_name].list_indexes():
            out.append({"name": idx.get("name"), "type": "btree",
                        "key": ", ".join(f"{k}:{v}" for k, v in (idx.get("key") or {}).items())})
    except Exception as exc:
        out.append({"name": "<error>", "type": "?", "key": str(exc)})
    try:
        for s in db[coll_name].list_search_indexes():
            kind = s.get("type") or "search"
            out.append({"name": s.get("name"), "type": kind,
                        "key": "(Atlas Search index)"})
    except Exception:
        pass
    return out


def _sample_doc(coll_name: str) -> dict[str, Any] | None:
    try:
        doc = get_db()[coll_name].find_one({}, {"embedding": 0})
    except Exception as exc:
        return {"_error": str(exc)}
    if not doc:
        return None
    return jsonable(doc)


def _count(coll_name: str) -> int | str:
    try:
        return get_db()[coll_name].estimated_document_count()
    except Exception as exc:
        return f"err: {exc}"


@ui.page("/storage")
def storage_page() -> None:
    ui.dark_mode().enable()
    with ui.header(elevated=True).classes("items-center bg-slate-900 text-white"):
        ui.label("🍃 MongoDB Atlas — PolyStorage").classes("text-xl font-bold")
        ui.label("one cluster · seven storage shapes · one query language").classes("text-xs opacity-70 ml-3")
        ui.space()
        ui.link("← back", "/").classes("text-xs opacity-80")

    container = ui.column().classes("w-full p-4 gap-5")

    async def _render():
        with container:
            container.clear()
            for group_title, color, members in GROUPS:
                ui.label(group_title).classes("text-lg font-semibold").style(f"color:{color}")
                with ui.row().classes("w-full no-wrap gap-3 flex-wrap"):
                    for logical, physical, blurb in members:
                        try:
                            cnt = await asyncio.get_running_loop().run_in_executor(None, _count, physical)
                            indices = await asyncio.get_running_loop().run_in_executor(None, _list_indexes, physical)
                            sample = await asyncio.get_running_loop().run_in_executor(None, _sample_doc, physical)
                        except Exception as exc:
                            cnt, indices, sample = "?", [], {"_error": str(exc)}
                        with ui.card().tight().classes("min-w-[320px] flex-1 bg-slate-900 p-3 rounded-lg"):
                            ui.label(physical).classes("text-sm font-mono font-bold").style(f"color:{color}")
                            ui.label(blurb).classes("text-xs opacity-70 mt-1")
                            ui.label(f"docs: {cnt:,}" if isinstance(cnt, int) else f"docs: {cnt}") \
                                .classes("text-xs mt-2 opacity-80")
                            ui.label("indexes:").classes("text-xs mt-2 font-semibold opacity-80")
                            for ix in indices:
                                badge = "🟦" if ix["type"] == "btree" else ("🟩" if "vector" in ix["type"] else "🟧")
                                ui.label(f"{badge} {ix['name']}  ({ix['type']})  {ix.get('key','')}") \
                                    .classes("text-xs opacity-80 font-mono whitespace-pre-wrap")
                            with ui.expansion("sample document").classes("w-full mt-2 text-xs"):
                                if sample is None:
                                    ui.label("(empty collection)").classes("opacity-60")
                                else:
                                    import json
                                    ui.code(json.dumps(sample, indent=2, default=str)) \
                                        .classes("w-full text-xs")

    asyncio.create_task(_render())
