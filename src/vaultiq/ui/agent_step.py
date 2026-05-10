"""Drill-down page (`/agent_step/{case_id}/{stage}`).

Opens in a new tab when the user clicks one of the stage cards on the case
journey page (`/case/{case_id}`). Walks through the substeps that happen
inside that stage — LangGraph node entry, semantic-memory recall (vector
search), the ReAct tool loop (with the actual MongoDB ops each tool runs),
the LLM call wrapped by the semantic cache, the checkpoint write, and the
routing decision — anchored in the real values for this case.

Reuses the animation CSS/JS from `case_flow.py` so substeps reveal one at
a time on the same 1.9s cadence.
"""
from __future__ import annotations

import asyncio
import html as _html
import json as _json
from typing import Any, TypedDict

from nicegui import ui

from src.vaultiq.ui.case_flow import (
    _ANIMATION_CSS,
    _ANIMATION_JS,
    _band_color,
    _fmt_amount,
    _STATUS_STYLE,
)


# Per-stage friendly metadata for the page header.
_STAGE_META: dict[str, dict[str, str]] = {
    "transaction":     {"icon": "💳", "title": "Transaction Ingest", "color": "#38bdf8"},
    "fraud_sentinel":  {"icon": "🛡",  "title": "Fraud Sentinel",     "color": "#ff6b6b"},
    "customer_trust":  {"icon": "🪪", "title": "Customer Trust",     "color": "#ffa94d"},
    "case_resolution": {"icon": "📁", "title": "Case Resolution",    "color": "#4dabf7"},
}


class _SubStep(TypedDict, total=False):
    """One substep in the stage drill-down."""
    icon: str
    title: str
    component: str        # LangChain / LangGraph class or function
    library: str          # which package / version surface it lives in
    mongo_coll: list[str] # MongoDB collections touched
    mongo_index: str      # primary index hit
    mongo_op: str         # representative aggregation / op snippet (multiline ok)
    explanation: str      # one-paragraph "what + why"
    actual: str           # what actually happened in this case (anchor in data)


def _render_substep(step: _SubStep, color: str) -> None:
    """Render one substep card. Wrapped in a `.vq-step` so the orchestrator
    JS reveals it in sequence.
    """
    with ui.column().classes("w-full vq-step gap-0"):
        with ui.card().tight().classes(
            "w-full bg-slate-900 p-3 rounded-lg"
        ).style(f"border-left:4px solid {color};--vq-glow:{color}aa"):
            with ui.row().classes("items-center w-full gap-2"):
                ui.label(step.get("icon", "•")).classes("text-lg")
                ui.label(step.get("title", "?")).classes(
                    "text-sm font-bold uppercase tracking-wide"
                ).style(f"color:{color}")
            if step.get("explanation"):
                ui.label(step["explanation"]).classes(
                    "text-xs opacity-85 mt-1 leading-relaxed"
                )

            # 2-column: LangChain side | MongoDB side
            with ui.row().classes("w-full gap-2 mt-2 flex-wrap"):
                with ui.column().classes("flex-1 min-w-[260px] gap-1 p-2 rounded bg-slate-800/60"):
                    ui.label("🔧 component").classes(
                        "text-[10px] opacity-60 font-bold uppercase tracking-wider"
                    )
                    if step.get("component"):
                        ui.label(step["component"]).classes(
                            "text-[11px] font-mono opacity-90 break-all"
                        )
                    if step.get("library"):
                        ui.label(f"📦 {step['library']}").classes(
                            "text-[10px] opacity-70 font-mono"
                        )
                if step.get("mongo_coll") or step.get("mongo_index"):
                    with ui.column().classes(
                        "flex-1 min-w-[260px] gap-1 p-2 rounded"
                    ).style("background:#022c2244;border:1px solid #10b98155"):
                        ui.label("🍃 MongoDB Atlas").classes(
                            "text-[10px] opacity-70 font-bold uppercase tracking-wider"
                        ).style("color:#10b981")
                        for c in step.get("mongo_coll") or []:
                            ui.label(f"📁 {c}").classes(
                                "text-[11px] font-mono opacity-90"
                            )
                        if step.get("mongo_index"):
                            ui.label(f"🪄 {step['mongo_index']}").classes(
                                "text-[10px] font-mono opacity-80"
                            ).style("color:#a7f3d0")

            if step.get("mongo_op"):
                ui.html(
                    '<pre style="background:#020617;padding:10px 12px;'
                    'border-radius:6px;font-size:10.5px;line-height:1.5;'
                    'color:#e2e8f0;overflow-x:auto;margin-top:10px;'
                    'border:1px solid #1e293b">'
                    f'{_html.escape(step["mongo_op"])}'
                    '</pre>'
                )

            if step.get("actual"):
                with ui.row().classes(
                    "w-full gap-2 items-start mt-2 p-2 rounded"
                ).style(f"background:{color}11;border:1px solid {color}55"):
                    ui.label("📊").classes("text-sm")
                    with ui.column().classes("flex-1 gap-0"):
                        ui.label("THIS CASE →").classes(
                            "text-[9px] opacity-70 font-bold tracking-wider"
                        ).style(f"color:{color}")
                        ui.label(step["actual"]).classes(
                            "text-[11px] opacity-95"
                        ).style(f"color:{color}")



# ── per-stage substep builders ───────────────────────────────────────────

def _substeps_transaction(flow: dict) -> list[_SubStep]:
    tx = flow.get("transaction") or {}
    return [
        {"icon": "📡", "title": "1. Synthetic transaction generated",
         "component": "stream_runner.generate_baseline_transaction()",
         "library": "vaultiq.scenarios + vaultiq.stream_runner",
         "explanation": "Either a low-risk baseline tx or one of the scripted scenarios "
                        "(ato_sim_swap, mule_funnel, card_testing, …) per the configured fraud_ratio.",
         "actual": f"tx_id={tx.get('tx_id','?')} amount={_fmt_amount(tx.get('amount'))} "
                   f"merchant={tx.get('merchant_id','?')} country={tx.get('country','?')}"},
        {"icon": "💾", "title": "2. Persist to time-series + geo collections",
         "component": "stream_runner.persist_transaction(tx)",
         "library": "pymongo · MongoDB time-series + 2dsphere",
         "mongo_coll": ["transactions", "transaction_geo"],
         "mongo_index": "ts_meta on transactions (TS) · 2dsphere on transaction_geo.location",
         "mongo_op": "db.transactions.insert_one(tx)\n"
                     "// then, if the merchant has a geo point:\n"
                     "db.transaction_geo.insert_one({\n"
                     "  ts: tx.ts, tx_id, customer_id,\n"
                     "  location: { type: 'Point', coordinates: [lon, lat] }\n"
                     "})",
         "explanation": "Native MongoDB time-series collection (ts metaField) for fast windowed scans; "
                        "a parallel point-doc in transaction_geo so geo-velocity / distance-from-home "
                        "tools can run $geoNear without unpacking the bucketed TS doc.",
         "actual": f"inserted into transactions; geo point recorded for merchant {tx.get('merchant_id','?')}"},
        {"icon": "🟢", "title": "3. Build initial LangGraph state",
         "component": "graph.invoke({transaction, customer_id, messages, trace})",
         "library": "langgraph 1.x StateGraph",
         "mongo_coll": ["lg_checkpoints", "lg_checkpoint_writes"],
         "mongo_index": "thread_id_1_checkpoint_id_1",
         "mongo_op": "cfg = {configurable: {thread_id: 'vaultiq-<uuid>'}}\n"
                     "graph.invoke(initial_state, config=cfg)\n"
                     "// MongoDBSaver writes the first checkpoint here",
         "explanation": "LangGraph constructs the initial VaultIQState and writes checkpoint #0 via "
                        "MongoDBSaver, so the run is resumable and observable from any process.",
         "actual": f"customer_id={tx.get('customer_id','?')} → next node: fraud_sentinel"},
        {"icon": "↗️", "title": "4. Route to entry node",
         "component": "graph.add_edge(START, 'fraud_sentinel')",
         "library": "langgraph 1.x",
         "explanation": "Static edge from START → fraud_sentinel. Every transaction starts with detection.",
         "actual": "transaction is now in front of the Fraud Sentinel agent"},
    ]


def _substeps_fraud_sentinel(flow: dict) -> list[_SubStep]:
    case = flow.get("case") or {}
    tx = flow.get("transaction") or {}
    score = float(case.get("score") or 0)
    band, _ = _band_color(score)
    next_node = "customer_trust" if score >= 0.65 else "memory_writer"
    return [
        {"icon": "🟢", "title": "1. LangGraph node entry",
         "component": "fraud_node(state) — registered via g.add_node('fraud_sentinel', fraud_node)",
         "library": "langgraph 1.x StateGraph",
         "mongo_coll": ["lg_checkpoints"],
         "mongo_op": "// state hydrated from checkpointer:\n"
                     "{ transaction: {...}, customer_id, messages: [], trace: [] }",
         "explanation": "Router invokes the fraud_sentinel node. State is loaded from the last "
                        "checkpoint by MongoDBSaver, keyed by thread_id.",
         "actual": f"tx_id={tx.get('tx_id','?')} amount={_fmt_amount(tx.get('amount'))} → fraud_node()"},
        {"icon": "🧠", "title": "2. Episodic memory recall (vector search)",
         "component": "SemanticMemory.recall(query, agent='fraud_sentinel', customer_id, k=3)",
         "library": "langchain-mongodb 0.11 · MongoDBAtlasVectorSearch",
         "mongo_coll": ["agent_semantic_mem"],
         "mongo_index": "sem_mem_vector_idx (autoEmbed · voyage-4)",
         "mongo_op": "{\n"
                     "  $vectorSearch: {\n"
                     "    index: 'sem_mem_vector_idx',\n"
                     "    queryVector: <auto-embedded server-side>,\n"
                     "    path: 'embedding',\n"
                     "    filter: { agent: 'fraud_sentinel', customer_id: '<id>' },\n"
                     "    numCandidates: 50, limit: 3\n"
                     "  }\n"
                     "}",
         "explanation": "Atlas AutoEmbeddings vectorises the query string with voyage-4 inside mongot — "
                        "no client-side embed call. Pre-filter scopes to this agent + customer so we only "
                        "see relevant prior episodes.",
         "actual": f"recall scoped to customer {tx.get('customer_id','?')} (top-3 prior fraud episodes)"},
        {"icon": "🔁", "title": "3. ReAct agent invocation",
         "component": "create_react_agent(get_chat_llm(), TOOLS, prompt=SYSTEM, name='fraud_sentinel')",
         "library": "langgraph.prebuilt 1.x",
         "mongo_op": "agent.invoke({\n"
                     "  messages: [SystemMessage(SYSTEM),\n"
                     "             HumanMessage(user_with_tx_and_recall)]\n"
                     "})\n"
                     "// LLM picks tools → tools run → LLM sees results → … → final JSON",
         "explanation": "LangGraph's prebuilt ReAct loop. The LLM picks tools to call, sees their results, "
                        "and iterates until it can emit a strict JSON answer with score / band / reasons.",
         "actual": "10 tools available; agent typically picks 3–6 per run"},
        {"icon": "🛠", "title": "4. Tool calls (representative MongoDB ops)",
         "component": "@tool functions: score_transaction, get_recent_transactions, "
                      "geo_velocity_anomaly, customer_velocity, mcc_burst, "
                      "device_owner_graph, fraud_kb_lookup",
         "library": "langchain-core 1.x · pymongo · langchain-mongodb",
         "mongo_coll": ["customers", "merchants", "transactions",
                        "transaction_geo", "entity_edges", "fraud_kb"],
         "mongo_index": "btree {customer_id} · TS ts_meta · 2dsphere on geo · "
                        "$graphLookup on entity_edges · fraud_kb_vector_idx (autoEmbed)",
         "mongo_op": "// time-series velocity (customer_velocity tool)\n"
                     "db.transactions.aggregate([\n"
                     "  { $match: { customer_id, ts: { $gte: since } } },\n"
                     "  { $group: { _id: null, count, sum_amount, distinct_countries } }\n"
                     "])\n"
                     "\n"
                     "// graph traversal of shared devices (device_owner_graph tool)\n"
                     "db.entity_edges.aggregate([{ $graphLookup: {\n"
                     "  from: 'entity_edges', startWith: <device_id>,\n"
                     "  connectFromField: 'to', connectToField: 'from', as: 'reach'\n"
                     "}}])\n"
                     "\n"
                     "// hybrid (vector + BM25) over the fraud KB (fraud_kb_lookup tool)\n"
                     "AutoEmbedHybridSearchRetriever(query).invoke()  // uses\n"
                     "  $vectorSearch  +  $search (BM25)  →  RRF blend",
         "explanation": "Each @tool is a Python function that runs one MongoDB op. "
                        "AutoEmbedHybridSearchRetriever lets fraud_kb_lookup do hybrid search without "
                        "client-side embedding — mongot vectorises the query.",
         "actual": f"reasons recorded: {len(case.get('reasons') or [])} signals "
                   f"(see the chips on the journey page for the actual text)"},
        {"icon": "🤖", "title": "5. LLM call (with semantic cache)",
         "component": "ChatOpenAI / AzureChatOpenAI  +  MongoDBAtlasSemanticCache",
         "library": "langchain-openai 1.x · langchain-mongodb cache",
         "mongo_coll": ["llm_semantic_cache"],
         "mongo_index": "vaultiq_semcache_idx (autoEmbed · voyage-4)  filter:[llm_string]",
         "mongo_op": "// cache lookup before each LLM round-trip\n"
                     "{ $vectorSearch: {\n"
                     "    index: 'vaultiq_semcache_idx',\n"
                     "    queryVector: <auto-embedded prompt>,\n"
                     "    path: 'embedding', limit: 1,\n"
                     "    filter: { llm_string: '<llm-fingerprint>' }\n"
                     "} }\n"
                     "// HIT  (score ≥ 0.92) → return cached completion\n"
                     "// MISS                 → call LLM, then write back",
         "explanation": "Every LLM round-trip is wrapped by MongoDBAtlasSemanticCache. "
                        "score_threshold defaults to 0.92; on a hit we skip the LLM call entirely.",
         "actual": "cache hit/miss depends on prompt similarity to past runs"},
        {"icon": "💾", "title": "6. State write + checkpoint",
         "component": "MongoDBSaver.put(checkpoint)",
         "library": "langgraph-checkpoint-mongodb 0.3",
         "mongo_coll": ["lg_checkpoints", "lg_checkpoint_writes"],
         "mongo_index": "thread_id_1_checkpoint_id_1",
         "mongo_op": "{ $set: {\n"
                     "  state: { fraud: { score, band, reasons, summary },\n"
                     "           messages, trace },\n"
                     "  ts: Date.now()\n"
                     "} }",
         "explanation": "After fraud_node returns, LangGraph writes the new state slice to MongoDB so the "
                        "next node sees it (and so the run can be resumed mid-flight).",
         "actual": f"state.fraud = {{ score: {score:.3f}, band: '{band}', reasons: [...] }}"},
        {"icon": "↗️", "title": "7. Conditional routing",
         "component": "graph.add_conditional_edges('fraud_sentinel', _route_after_fraud, ...)",
         "library": "langgraph 1.x",
         "mongo_op": "_route_after_fraud(state):\n"
                     "  s = state.fraud.score\n"
                     "  return 'customer_trust' if s >= 0.65 else 'memory_writer'",
         "explanation": "Conditional edge: medium-or-higher risk escalates to Customer Trust; otherwise "
                        "we go straight to Memory Writer and end the run.",
         "actual": f"score {score:.2f} {'≥' if score >= 0.65 else '<'} 0.65 → next node: {next_node}"},
    ]



def _kyc_from_events(events: list[dict]) -> dict:
    out: dict = {}
    for e in events:
        if e.get("type") in ("CASE_DECISION", "CASE_AUTO_ESCALATED"):
            p = e.get("payload") or {}
            for k in ("verified", "claims_transaction"):
                if k in p and k not in out:
                    out[k] = p[k]
    return out


def _substeps_customer_trust(flow: dict) -> list[_SubStep]:
    case = flow.get("case") or {}
    tx = flow.get("transaction") or {}
    cust = flow.get("customer") or {}
    score = float(case.get("score") or 0)
    kyc = _kyc_from_events(flow.get("events") or [])
    verified = kyc.get("verified")
    claims = kyc.get("claims_transaction")
    return [
        {"icon": "🟢", "title": "1. LangGraph node entry",
         "component": "kyc_node(state) — registered via g.add_node('customer_trust', kyc_node)",
         "library": "langgraph 1.x StateGraph",
         "mongo_coll": ["lg_checkpoints"],
         "mongo_op": "// state hydrated, now contains:\n"
                     "{ transaction, fraud: { score, band, reasons }, ... }",
         "explanation": "Reached only when fraud.score ≥ 0.65. The fraud verdict is now in state and "
                        "informs the dialogue plan.",
         "actual": f"score={score:.2f} arrived at kyc_node()"},
        {"icon": "🧠", "title": "2. Verification-history recall",
         "component": "SemanticMemory.recall(query='verification history for customer …', "
                      "agent='customer_trust', customer_id, k=3)",
         "library": "langchain-mongodb 0.11 · MongoDBAtlasVectorSearch",
         "mongo_coll": ["agent_semantic_mem"],
         "mongo_index": "sem_mem_vector_idx (autoEmbed · voyage-4)",
         "mongo_op": "{ $vectorSearch: { index: 'sem_mem_vector_idx',\n"
                     "    queryVector: <auto-embedded>, path: 'embedding',\n"
                     "    filter: { agent: 'customer_trust', customer_id },\n"
                     "    numCandidates: 50, limit: 3 } }",
         "explanation": "Pull prior KYC episodes for this customer so the LLM can reason about whether "
                        "they tend to claim or dispute (and how they responded to past OTP step-ups).",
         "actual": f"recall scoped to {tx.get('customer_id','?')}"},
        {"icon": "🛠", "title": "3. Tool calls (KYC toolkit)",
         "component": "@tool: get_customer_profile, verify_identity_factors, "
                      "request_otp, confirm_otp, flag_kyc_step_up",
         "library": "langchain-core 1.x · pymongo",
         "mongo_coll": ["customers", "case_events"],
         "mongo_index": "btree {customer_id} on customers · ts on case_events",
         "mongo_op": "// 1) read profile\n"
                     "db.customers.find_one({customer_id})\n"
                     "// 2) (if score >= 0.5) request OTP — write a case_event\n"
                     "db.case_events.insert_one({ ts, customer_id,\n"
                     "  type: 'otp_sent', code_hash: <sha256[:12]> })\n"
                     "// 3) simulate confirm_otp(code) → {valid: true|false}\n"
                     "// 4) optional flag_kyc_step_up:\n"
                     "db.customers.update_one({customer_id},\n"
                     "  { $set: { kyc_step_up: true, kyc_step_up_reason: '…' } })",
         "explanation": "Always reads the profile first. If score ≥ 0.5 it triggers an OTP step-up "
                        "(audited as a case_event). The customer answer is simulated by the LLM as a "
                        "reasonable bank user — truthful in low-risk, denying obvious ATO signals.",
         "actual": f"customer kyc_status: {cust.get('kyc_status','—')}, "
                   f"step-up triggered (score ≥ 0.5)"},
        {"icon": "🤖", "title": "4. LLM call (with semantic cache)",
         "component": "ChatOpenAI / AzureChatOpenAI  +  MongoDBAtlasSemanticCache",
         "library": "langchain-openai 1.x · langchain-mongodb cache",
         "mongo_coll": ["llm_semantic_cache"],
         "mongo_index": "vaultiq_semcache_idx (autoEmbed)",
         "mongo_op": "// same cache wrapper as Fraud Sentinel; may HIT on similar KYC dialogues",
         "explanation": "Returns strict JSON: {verified, claims_transaction, factors_matched, otp_used, summary}.",
         "actual": f"verified={verified} · claims_transaction={claims}"},
        {"icon": "💾", "title": "5. State write + checkpoint",
         "component": "MongoDBSaver.put(checkpoint)",
         "library": "langgraph-checkpoint-mongodb 0.3",
         "mongo_coll": ["lg_checkpoints", "lg_checkpoint_writes"],
         "mongo_op": "{ $set: { state: { ..., kyc: { verified, claims_transaction, ... } } } }",
         "explanation": "Writes the KYC verdict back into VaultIQState so case_node can use it.",
         "actual": f"state.kyc = {{ verified: {verified}, claims_transaction: {claims} }}"},
        {"icon": "↗️", "title": "6. Edge → Case Resolution",
         "component": "graph.add_conditional_edges('customer_trust', _route_after_kyc, ...)",
         "library": "langgraph 1.x",
         "mongo_op": "_route_after_kyc(_):  return 'case_resolution'   // unconditional",
         "explanation": "After Customer Trust there's always a Case Resolution decision to record.",
         "actual": "next node: case_resolution"},
    ]


def _substeps_case_resolution(flow: dict) -> list[_SubStep]:
    case = flow.get("case") or {}
    tx = flow.get("transaction") or {}
    status = (case.get("status") or "NEW").upper()
    return [
        {"icon": "🟢", "title": "1. LangGraph node entry",
         "component": "case_node(state) — registered via g.add_node('case_resolution', case_node)",
         "library": "langgraph 1.x StateGraph",
         "mongo_coll": ["lg_checkpoints"],
         "mongo_op": "// state has:\n{ transaction, fraud: {...}, kyc: {...} }",
         "explanation": "Receives the full picture (fraud verdict + KYC outcome) and decides the case.",
         "actual": f"state.fraud.score={case.get('score'):.2f} state.kyc=… → case_node()" if case.get("score") is not None else "case_node()"},
        {"icon": "🧠", "title": "2. Prior-case recall (vector search)",
         "component": "SemanticMemory.recall(query='prior case outcomes for customer …', "
                      "agent='case_resolution', customer_id, k=3)",
         "library": "langchain-mongodb 0.11",
         "mongo_coll": ["agent_semantic_mem"],
         "mongo_index": "sem_mem_vector_idx (autoEmbed)",
         "mongo_op": "{ $vectorSearch: { index: 'sem_mem_vector_idx',\n"
                     "    queryVector: <auto-embedded>, path: 'embedding',\n"
                     "    filter: { agent: 'case_resolution', customer_id },\n"
                     "    numCandidates: 50, limit: 3 } }",
         "explanation": "Pulls prior case outcomes for this customer so repeat patterns inform the verdict.",
         "actual": f"recall scoped to {tx.get('customer_id','?')}"},
        {"icon": "🛠", "title": "3. CRM tool calls + MCP",
         "component": "@tool: list_open_cases, open_case, update_case, add_case_note, log_case_event "
                      "(+ MongoDB MCP tools when available)",
         "library": "langchain-core 1.x · langchain-mcp-adapters · pymongo",
         "mongo_coll": ["cases", "case_events", "case_notes"],
         "mongo_index": "btree {customer_id, status} on cases · ts_-1 on case_events · "
                        "case_notes_vector_idx (autoEmbed) for the note write",
         "mongo_op": "// 1) check existing cases\n"
                     "db.cases.find({ customer_id, status: { $nin: ['RESOLVED_FRAUD','RESOLVED_LEGITIMATE'] } })\n"
                     "// 2) open / update the case\n"
                     "db.cases.insert_one({ case_id, customer_id, tx_id, status,\n"
                     "                      score, reasons, created_at, updated_at })\n"
                     "// 3) audit + note\n"
                     "db.case_events.insert_one({ ts, case_id, type: 'opened',\n"
                     "                            payload: { score, reasons } })\n"
                     "db.case_notes.insert_one({ case_id, customer_id, ts, text })\n"
                     "// case_notes is autoEmbed — mongot vectorises 'text' for future hybrid search",
         "explanation": "Investigator note is vector-indexed by mongot (no client embed). MongoDB MCP "
                        "tools are bridged in via langchain-mcp-adapters for ad-hoc read-only queries.",
         "actual": f"case_id={case.get('case_id','—')} opened with status={status}"},
        {"icon": "🤖", "title": "4. LLM call (with semantic cache)",
         "component": "ChatOpenAI / AzureChatOpenAI  +  MongoDBAtlasSemanticCache",
         "library": "langchain-openai 1.x · langchain-mongodb cache",
         "mongo_coll": ["llm_semantic_cache"],
         "mongo_op": "// returns JSON: { case_id, status, action_taken, summary }",
         "explanation": "Applies the decision matrix (score × KYC) and emits the final disposition JSON.",
         "actual": f"final status: {status}"},
        {"icon": "💾", "title": "5. State write + checkpoint",
         "component": "MongoDBSaver.put(checkpoint)",
         "library": "langgraph-checkpoint-mongodb 0.3",
         "mongo_coll": ["lg_checkpoints", "lg_checkpoint_writes"],
         "mongo_op": "{ $set: { state: { ..., case: { case_id, status, summary } } } }",
         "explanation": "Final state slice; the run is now ready for the Memory Writer node.",
         "actual": f"state.case = {{ case_id: '{case.get('case_id','—')}', status: '{status}' }}"},
    ]



# ── full-page route ──────────────────────────────────────────────────────

_BUILDERS = {
    "transaction":     _substeps_transaction,
    "fraud_sentinel":  _substeps_fraud_sentinel,
    "customer_trust":  _substeps_customer_trust,
    "case_resolution": _substeps_case_resolution,
}


@ui.page("/agent_step/{case_id}/{stage}")
def agent_step_page(case_id: str, stage: str) -> None:
    """Drill-down for one stage of the agent journey, opened in a new tab."""
    from src.vaultiq.ui.stream_runner import fetch_case_flow  # local: avoid cycle

    ui.dark_mode().enable()
    ui.add_head_html(f"<style>{_ANIMATION_CSS}</style>")
    ui.add_head_html(f"<script>{_ANIMATION_JS}</script>")

    meta = _STAGE_META.get(stage, {"icon": "🔬", "title": stage, "color": "#94a3b8"})

    with ui.header(elevated=True).classes("items-center bg-slate-900 text-white"):
        ui.label(meta["icon"]).classes("text-xl")
        ui.label(meta["title"]).classes("text-base font-bold ml-2") \
            .style(f"color:{meta['color']}")
        ui.label(f"· technical drill-down · case {case_id}").classes(
            "text-xs opacity-70 ml-3"
        )
        ui.space()
        ui.link("← back to journey", f"/case/{case_id}").classes("text-xs opacity-80")

    body = ui.column().classes("w-full max-w-4xl mx-auto p-4 gap-3")
    with body:
        ui.label("loading…").classes("opacity-60")

    async def _load() -> None:
        try:
            flow = await asyncio.get_running_loop().run_in_executor(
                None, fetch_case_flow, case_id
            )
        except Exception as exc:
            body.clear()
            with body:
                ui.label(f"flow fetch error: {exc}").classes("text-red-400")
            return
        body.clear()
        with body:
            if not flow.get("case"):
                ui.label(f"Unknown case: {case_id}").classes("text-red-400")
                return
            builder = _BUILDERS.get(stage)
            if builder is None:
                ui.label(f"Unknown stage: {stage}").classes("text-red-400")
                return
            substeps = builder(flow)

            # Sticky playback control bar (reuses the case-flow pattern).
            with ui.card().tight().classes(
                "w-full bg-slate-900 p-3 rounded-xl sticky top-2 z-10"
            ).style(f"border:1px solid {meta['color']}55"):
                with ui.row().classes("items-center w-full gap-3"):
                    ui.label("🔬").classes("text-xl")
                    ui.html(
                        '<div id="vq-step-indicator" class="text-sm font-semibold">'
                        '<span style="color:#38bdf8">▶</span> starting…</div>'
                    )
                    ui.space()
                    # Click wired programmatically in _ANIMATION_JS.wireReplay()
                    ui.html(
                        '<button id="vq-replay-btn" type="button" '
                        'style="display:none;background:#1e293b;color:#e2e8f0;'
                        'border:1px solid #334155;border-radius:6px;padding:4px 10px;'
                        'font-size:12px;cursor:pointer">↻ replay</button>'
                    )
                ui.html(
                    '<div style="width:100%;height:4px;background:#1e293b;'
                    'border-radius:2px;margin-top:8px;overflow:hidden">'
                    '<div id="vq-progress-bar" class="vq-progress-bar" '
                    f'style="width:0%;height:100%;background:linear-gradient'
                    f'(90deg,#38bdf8,{meta["color"]},#10b981)"></div></div>'
                )
                ui.html(
                    '<div id="vq-narration" '
                    'style="margin-top:10px;padding:8px 10px;background:#0f172a;'
                    'border-left:3px solid #38bdf8;border-radius:4px;'
                    'font-size:12px;line-height:1.5;min-height:38px;color:#e2e8f0">'
                    f'Walking through the {len(substeps)} substeps inside '
                    f'<b style="color:{meta["color"]}">{meta["title"]}</b>…</div>'
                )

            # Substeps
            with ui.column().classes("w-full gap-2 mt-3"):
                for s in substeps:
                    _render_substep(s, meta["color"])

            # Hand off step names + narrations to the JS orchestrator.
            names = [s.get("title", "?") for s in substeps]
            narrs = [
                f'<b style="color:{meta["color"]}">{_html.escape(s.get("title",""))}</b><br>'
                f'<span style="opacity:0.85">{_html.escape(s.get("explanation",""))}</span>'
                for s in substeps
            ]
            ui.html(
                '<div id="vq-data" style="display:none">'
                f'<span id="vq-names">{_html.escape(_json.dumps(names))}</span>'
                f'<span id="vq-narrs">{_html.escape(_json.dumps(narrs))}</span>'
                '</div>'
            )

    asyncio.create_task(_load())
