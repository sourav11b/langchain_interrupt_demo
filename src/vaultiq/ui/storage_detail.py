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


# (group title, accent colour, group_icon, doc_icon, [(logical, physical, blurb)])
GROUPS: list[tuple[str, str, str, str, list[tuple[str, str, str]]]] = [
    ("Structured", "#94a3b8", "📑", "👤", [
        ("customers",   C.customers,   "KYC + risk"),
        ("accounts",    C.accounts,    "Balances"),
        ("cards",       C.cards,       "Card metadata"),
        ("devices",     C.devices,     "Device fingerprints"),
        ("merchants",   C.merchants,   "MCC + risk"),
        ("cases",       C.cases,       "Fraud cases (CRM)"),
        ("case_events", C.case_events, "Case timeline"),
    ]),
    ("Time-series", "#fbbf24", "⏱", "📈", [
        ("transactions",  C.transactions,  "Live tx stream"),
        ("agent_metrics", C.agent_metrics, "Per-run latency + score"),
    ]),
    ("Geospatial (2dsphere)", "#34d399", "🌍", "📍", [
        ("home_locations",  C.home_locations,  "Customer home points"),
        ("merchant_geo",    C.merchant_geo,    "Merchant locations"),
        ("transaction_geo", C.transaction_geo, "Per-tx point cache"),
    ]),
    ("Graph ($graphLookup)", "#a78bfa", "🕸", "🔗", [
        ("relationships", C.relationships, "OWNS · USES · TRANSACTED_WITH"),
    ]),
    ("Vector + Full-text", "#ff6b6b", "🧭", "📚", [
        ("fraud_kb",   C.fraud_kb,   "Fraud-typology KB"),
        ("case_notes", C.case_notes, "Investigator notes"),
        ("sem_memory", C.sem_memory, "Per-agent memory"),
    ]),
    ("LangGraph state", "#4dabf7", "🧩", "📦", [
        ("checkpoints",       C.checkpoints,       "Checkpoint snapshots"),
        ("checkpoint_writes", C.checkpoint_writes, "Per-step deltas"),
        ("store",             C.store,             "Long-term k/v store"),
        ("chat_history",      C.chat_history,      "Per-session messages"),
    ]),
    ("LLM cache", "#f87171", "⚡", "💾", [
        ("semantic_cache", C.semantic_cache, "Similarity-keyed cache"),
        ("llm_cache",      C.llm_cache,      "Exact-match cache"),
    ]),
]


# (matcher: index dict -> (icon, label-letter, color))
def _index_badge(ix: dict[str, Any]) -> tuple[str, str, str]:
    name = (ix.get("name") or "").lower()
    typ = (ix.get("type") or "").lower()
    if "auto" in name or ix.get("autoEmbed") or "vector" in typ and ix.get("autoEmbed"):
        return ("🪄", "auto", "#a78bfa")
    if "vector" in typ:
        return ("🧭", "vec", "#ff6b6b")
    if "search" in typ or "fts" in name or "text" in name and typ != "btree":
        return ("🔍", "fts", "#fb923c")
    if "geo" in name or "2dsphere" in (ix.get("key") or "").lower():
        return ("🌍", "geo", "#34d399")
    if "_id_" in name or name == "_id_":
        return ("🔑", "pk", "#94a3b8")
    return ("🟦", "btree", "#60a5fa")


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
            defn = s.get("latestDefinition") or s.get("definition") or {}
            auto_embed = any(f.get("type") == "autoEmbed"
                             for f in (defn.get("fields") or []))
            out.append({"name": s.get("name"), "type": kind,
                        "key": "(Atlas Search index)",
                        "autoEmbed": auto_embed})
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


_PULSE_CSS = """
@keyframes vaultiq-pulse {
  0%   { transform: scale(1);    opacity: 1; }
  50%  { transform: scale(1.18); opacity: 0.7; }
  100% { transform: scale(1);    opacity: 1; }
}
@keyframes vaultiq-spin {
  from { transform: rotate(0deg); } to { transform: rotate(360deg); }
}
.vq-pulse { display:inline-block; animation: vaultiq-pulse 2.4s ease-in-out infinite; }
.vq-spin  { display:inline-block; animation: vaultiq-spin 12s linear infinite; }
.vq-pop   { transition: transform 120ms ease; }
.vq-pop:hover { transform: translateY(-2px); }
"""


@ui.page("/storage")
def storage_page() -> None:
    ui.dark_mode().enable()
    ui.add_head_html(f"<style>{_PULSE_CSS}</style>")
    with ui.header(elevated=True).classes("items-center bg-slate-900 text-white"):
        ui.html('<span class="vq-spin" style="display:inline-block">🍃</span>').classes("text-xl")
        ui.label("MongoDB Atlas — PolyStorage").classes("text-xl font-bold ml-2")
        ui.label("1 cluster · 7 shapes · 1 query language").classes(
            "text-xs opacity-70 ml-3"
        )
        ui.space()
        ui.link("← back", "/").classes("text-xs opacity-80")

    container = ui.column().classes("w-full p-4 gap-5")

    async def _render():
        with container:
            container.clear()
            for group_title, color, group_icon, doc_icon, members in GROUPS:
                with ui.row().classes("w-full items-center gap-2"):
                    ui.html(f'<span class="vq-pulse" style="font-size:20px">{group_icon}</span>')
                    ui.label(group_title).classes("text-lg font-semibold").style(
                        f"color:{color}"
                    )
                    ui.label(f"× {len(members)}").classes(
                        "text-[10px] opacity-60 px-2 py-0.5 rounded bg-slate-800"
                    )
                with ui.row().classes("w-full gap-3 flex-wrap"):
                    for logical, physical, blurb in members:
                        try:
                            cnt = await asyncio.get_running_loop().run_in_executor(None, _count, physical)
                            indices = await asyncio.get_running_loop().run_in_executor(None, _list_indexes, physical)
                            sample = await asyncio.get_running_loop().run_in_executor(None, _sample_doc, physical)
                        except Exception as exc:
                            cnt, indices, sample = "?", [], {"_error": str(exc)}
                        _render_card(physical, blurb, color, doc_icon, cnt, indices, sample)

    asyncio.create_task(_render())


def _render_card(physical: str, blurb: str, color: str, doc_icon: str,
                 cnt: int | str, indices: list[dict[str, Any]],
                 sample: dict[str, Any] | None) -> None:
    n = f"{cnt:,}" if isinstance(cnt, int) else str(cnt)
    with ui.card().tight().classes(
        "vq-pop w-[260px] bg-slate-900 p-3 rounded-xl"
    ).style(f"border-top:3px solid {color}"):
        with ui.row().classes("items-center w-full gap-2"):
            ui.label(doc_icon).classes("text-xl")
            ui.label(physical).classes("text-xs font-mono font-bold truncate flex-1") \
                .style(f"color:{color}")
        ui.label(blurb).classes("text-[11px] opacity-70 mt-0.5 truncate")
        with ui.row().classes("items-center w-full gap-2 mt-2"):
            ui.label("📄").classes("text-sm")
            ui.label(n).classes("text-base font-bold")
            ui.label("docs").classes("text-[10px] opacity-60")
            ui.space()
            ui.label(f"🗂 {len(indices)}").classes(
                "text-[11px] opacity-80 px-2 py-0.5 rounded bg-slate-800"
            )
        # icon-only index strip — hover for full name
        with ui.row().classes("items-center w-full flex-wrap gap-1 mt-2"):
            for ix in indices:
                ico, lbl, c = _index_badge(ix)
                tip = f"{ix.get('name')} ({lbl})"
                if ix.get("key"):
                    tip += f"  {ix.get('key')}"
                ui.html(
                    f'<span title="{tip}" '
                    f'style="display:inline-flex;align-items:center;gap:2px;'
                    f'padding:1px 6px;border-radius:6px;background:{c}22;'
                    f'border:1px solid {c}55;font-size:11px;color:{c}">'
                    f'{ico}<span style="font-size:9px;opacity:0.85">{lbl}</span></span>'
                )
        with ui.expansion("📄 sample doc").classes("w-full mt-2 text-[11px]"):
            if sample is None:
                ui.label("(empty)").classes("opacity-60 text-xs")
            else:
                import json
                ui.code(json.dumps(sample, indent=2, default=str)) \
                    .classes("w-full text-[10px]")
