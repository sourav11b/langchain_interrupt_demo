"""Per-agent drill-down page (`/agent/{agent_id}`).

Each agent has a registry entry describing its prompt summary, the tools it
uses (with read/write collection annotations), and an animated SVG pipeline.
"""
from __future__ import annotations

from typing import TypedDict

from nicegui import ui


class _Tool(TypedDict, total=False):
    name: str
    desc: str
    reads: list[str]
    writes: list[str]


class _Agent(TypedDict):
    name: str
    color: str
    icon: str
    role: str
    prompt: str
    tools: list[_Tool]


AGENT_DETAILS: dict[str, _Agent] = {
    "fraud_sentinel": {
        "name": "Fraud Sentinel", "color": "#ff6b6b", "icon": "🛡",
        "role": "First-line fraud detection — calibrated score + JSON verdict.",
        "prompt": ("ReAct loop. Always call `score_transaction` first. If score < 0.4, "
                   "stop. Otherwise blend in geo / velocity / graph / KB context."),
        "tools": [
            {"name": "score_transaction",       "desc": "Deterministic baseline score + reasons.",
             "reads": ["customers", "merchants", "devices", "transaction_geo", "home_locations"], "writes": []},
            {"name": "get_customer_profile",    "desc": "Structured KYC + risk score.",
             "reads": ["customers"], "writes": []},
            {"name": "get_recent_transactions", "desc": "Time-series velocity context.",
             "reads": ["transactions"], "writes": []},
            {"name": "distance_from_home_km",   "desc": "Haversine vs. customer home.",
             "reads": ["customer_geo"], "writes": []},
            {"name": "last_tx_location",        "desc": "Most recent tx geo point.",
             "reads": ["transaction_geo"], "writes": []},
            {"name": "geo_velocity_anomaly",    "desc": "Speed (km/h) needed since last tx.",
             "reads": ["transaction_geo"], "writes": []},
            {"name": "customer_velocity",       "desc": "TS aggregate over the customer.",
             "reads": ["transactions"], "writes": []},
            {"name": "mcc_burst",               "desc": "Burst detection per MCC.",
             "reads": ["transactions"], "writes": []},
            {"name": "device_owner_graph",      "desc": "$graphLookup over edges.",
             "reads": ["entity_edges"], "writes": []},
            {"name": "fraud_kb_lookup",         "desc": "Hybrid (vector + BM25) over fraud KB.",
             "reads": ["fraud_kb"], "writes": []},
        ],
    },
    "customer_trust": {
        "name": "Customer Trust", "color": "#ffa94d", "icon": "🪪",
        "role": "KYC verification + customer dispute / OTP step-up.",
        "prompt": ("Always call `get_customer_profile` first. If fraud≥0.5, OTP step-up. "
                   "Decide whether the customer claims the transaction."),
        "tools": [
            {"name": "get_customer_profile",    "desc": "Structured identity factors.",
             "reads": ["customers"], "writes": []},
            {"name": "verify_identity_factors", "desc": "Compare supplied vs. registered.",
             "reads": ["customers"], "writes": []},
            {"name": "request_otp",             "desc": "(mock) deterministic OTP.",
             "reads": ["customers"], "writes": ["case_events"]},
            {"name": "confirm_otp",             "desc": "Validate the OTP.",
             "reads": [], "writes": []},
            {"name": "flag_kyc_step_up",        "desc": "Persist a step-up flag on the profile.",
             "reads": [], "writes": ["customers"]},
        ],
    },
    "case_resolution": {
        "name": "Case Resolution", "color": "#4dabf7", "icon": "📁",
        "role": "Open / update fraud cases + log evidence in the CRM.",
        "prompt": ("Apply the fraud-score × KYC-claim decision matrix. Always "
                   "`add_case_note` after deciding. Use MongoDB MCP for ad-hoc reads."),
        "tools": [
            {"name": "list_open_cases",  "desc": "Find any active case for the customer.",
             "reads": ["cases"], "writes": []},
            {"name": "open_case",        "desc": "Create a new case (NEW/PENDING/UNDER/ESCALATED).",
             "reads": [], "writes": ["cases", "case_events"]},
            {"name": "update_case",      "desc": "Move a case through status transitions.",
             "reads": ["cases"], "writes": ["cases", "case_events"]},
            {"name": "add_case_note",    "desc": "Vector-indexed investigator note.",
             "reads": [], "writes": ["case_notes", "case_events"]},
            {"name": "log_case_event",   "desc": "Immutable event in the case timeline.",
             "reads": [], "writes": ["case_events"]},
            {"name": "MongoDB MCP tools","desc": "Ad-hoc read-only queries via mongodb-mcp-server.",
             "reads": ["*"], "writes": []},
        ],
    },
    "memory_writer": {
        "name": "Memory Writer", "color": "#82c91e", "icon": "🧠",
        "role": "Write episodic memory at end of every run for future recall.",
        "prompt": "Compact one-paragraph summary embedded + persisted per agent.",
        "tools": [
            {"name": "SemanticMemory.remember",
             "desc": "Embeds + writes one Document per agent into the vector store.",
             "reads": [], "writes": ["agent_semantic_mem"]},
        ],
    },
}


# ── animated SVG: LLM ▶ ReAct loop ▶ tools ▶ MongoDB ──────────────────────
def _agent_svg(a: _Agent) -> str:
    color = a["color"]
    tools = a["tools"]
    # vertical layout: tools fan out to the right of the agent, each linked
    # to a per-tool MongoDB collection box at the bottom row.
    n = len(tools)
    tool_w, tool_h, gap = 220, 38, 8
    height = max(280, 60 + n * (tool_h + gap) + 40)
    parts: list[str] = []
    parts.append(f'<svg viewBox="0 0 980 {height}" xmlns="http://www.w3.org/2000/svg" '
                 f'preserveAspectRatio="xMidYMid meet" style="width:100%;height:auto;display:block">')
    parts.append(
        '<defs>'
        '<filter id="ag-glow" x="-50%" y="-50%" width="200%" height="200%">'
        '<feGaussianBlur stdDeviation="3"/><feMerge><feMergeNode/>'
        '<feMergeNode in="SourceGraphic"/></feMerge></filter>'
    )
    # motion paths: agent->each tool, tool->mongo
    agent_x, agent_y = 30, 60
    agent_w, agent_h = 220, 80
    tool_x = agent_x + agent_w + 80
    mongo_x, mongo_y, mongo_w, mongo_h = 660, 60, 280, 80
    for i, _ in enumerate(tools):
        ty = 50 + i * (tool_h + gap)
        parts.append(f'<path id="t2t{i}" d="M {agent_x + agent_w} {agent_y + agent_h // 2} '
                     f'C {tool_x - 30} {agent_y + agent_h // 2}, '
                     f'{tool_x - 30} {ty + tool_h // 2}, {tool_x} {ty + tool_h // 2}"/>')
        parts.append(f'<path id="t2m{i}" d="M {tool_x + tool_w} {ty + tool_h // 2} '
                     f'L {mongo_x} {mongo_y + mongo_h // 2}"/>')
    parts.append('</defs>')

    # Agent box
    parts.append(
        f'<g transform="translate({agent_x} {agent_y})">'
        f'<rect width="{agent_w}" height="{agent_h}" rx="14" fill="#0f172a" '
        f'stroke="{color}" stroke-width="2" filter="url(#ag-glow)"/>'
        f'<text x="{agent_w // 2}" y="34" text-anchor="middle" fill="{color}" '
        f'font-size="20">{a["icon"]} {a["name"]}</text>'
        f'<text x="{agent_w // 2}" y="58" text-anchor="middle" fill="#94a3b8" '
        f'font-size="11">LLM + ReAct loop</text>'
        f'</g>'
    )
    # Mongo box
    parts.append(
        f'<g transform="translate({mongo_x} {mongo_y})">'
        f'<rect width="{mongo_w}" height="{mongo_h}" rx="14" fill="#022c22" '
        f'stroke="#10b981" stroke-width="2" filter="url(#ag-glow)"/>'
        f'<text x="{mongo_w // 2}" y="34" text-anchor="middle" fill="#10b981" '
        f'font-size="16">🍃 MongoDB Atlas</text>'
        f'<text x="{mongo_w // 2}" y="56" text-anchor="middle" fill="#94a3b8" '
        f'font-size="11">collections involved by this agent</text>'
        f'</g>'
    )
    # Per-tool boxes + edges + animated packets
    for i, t in enumerate(tools):
        ty = 50 + i * (tool_h + gap)
        rw = ", ".join(t.get("reads", []) + [f"+{x}" for x in t.get("writes", [])]) or "—"
        parts.append(f'<use href="#t2t{i}" stroke="#475569" stroke-width="1.5" fill="none" '
                     f'stroke-dasharray="3 4"/>')
        parts.append(f'<use href="#t2m{i}" stroke="#334155" stroke-width="1.2" fill="none" '
                     f'stroke-dasharray="3 4" opacity="0.7"/>')
        parts.append(
            f'<g transform="translate({tool_x} {ty})">'
            f'<rect width="{tool_w}" height="{tool_h}" rx="8" fill="#1e293b" '
            f'stroke="{color}" stroke-width="1"/>'
            f'<text x="10" y="16" fill="#e2e8f0" font-size="11" '
            f'font-family="ui-monospace,monospace" font-weight="700">{t["name"]}</text>'
            f'<text x="10" y="30" fill="#94a3b8" font-size="9.5">{rw[:48]}</text>'
            f'</g>'
        )
        parts.append(f'<circle r="3.5" fill="{color}" filter="url(#ag-glow)">'
                     f'<animateMotion dur="1.6s" repeatCount="indefinite" '
                     f'begin="{i * 0.18:.2f}s"><mpath href="#t2t{i}"/></animateMotion></circle>')
        parts.append(f'<circle r="3" fill="#10b981" opacity="0.85">'
                     f'<animateMotion dur="2.0s" repeatCount="indefinite" '
                     f'begin="{i * 0.22:.2f}s"><mpath href="#t2m{i}"/></animateMotion></circle>')
    parts.append('</svg>')
    return "".join(parts)


@ui.page("/agent/{agent_id}")
def agent_page(agent_id: str) -> None:
    ui.dark_mode().enable()
    if agent_id not in AGENT_DETAILS:
        ui.label(f"Unknown agent: {agent_id}").classes("text-red-400 m-4")
        ui.link("← back to dashboard", "/").classes("m-4")
        return
    a = AGENT_DETAILS[agent_id]
    with ui.header(elevated=True).classes("items-center bg-slate-900 text-white"):
        ui.label(f"{a['icon']} {a['name']}").classes("text-xl font-bold")
        ui.label(a["role"]).classes("text-xs opacity-70 ml-3")
        ui.space()
        ui.link("← back", "/").classes("text-xs opacity-80")

    with ui.column().classes("w-full p-4 gap-4"):
        with ui.card().tight().classes("w-full bg-slate-900 p-3 rounded-lg"):
            ui.label("🔬 Internal pipeline").classes("text-sm font-semibold opacity-80 mb-2")
            ui.html(_agent_svg(a))

        with ui.card().tight().classes("w-full bg-slate-900 p-3 rounded-lg"):
            ui.label("📜 System-prompt summary").classes("text-sm font-semibold opacity-80")
            ui.label(a["prompt"]).classes("text-sm opacity-90 whitespace-pre-wrap")

        with ui.card().tight().classes("w-full bg-slate-900 p-3 rounded-lg"):
            ui.label("🛠 Tools — read / write surface").classes("text-sm font-semibold opacity-80")
            cols = [
                {"name": "tool",   "label": "tool",   "field": "name"},
                {"name": "desc",   "label": "purpose", "field": "desc"},
                {"name": "reads",  "label": "reads",  "field": "reads"},
                {"name": "writes", "label": "writes", "field": "writes"},
            ]
            rows = [
                {"name": t["name"], "desc": t["desc"],
                 "reads":  ", ".join(t.get("reads",  [])) or "—",
                 "writes": ", ".join(t.get("writes", [])) or "—"}
                for t in a["tools"]
            ]
            ui.table(columns=cols, rows=rows, row_key="name").classes("w-full").props("dense flat")
