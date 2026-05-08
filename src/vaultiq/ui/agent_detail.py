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


TOOL_ICON: dict[str, str] = {
    "score_transaction":        "⚖️",
    "get_customer_profile":     "👤",
    "get_recent_transactions":  "💳",
    "distance_from_home_km":    "📏",
    "last_tx_location":         "📍",
    "geo_velocity_anomaly":     "🚀",
    "customer_velocity":        "⚡",
    "mcc_burst":                "💥",
    "device_owner_graph":       "🕸",
    "fraud_kb_lookup":          "📚",
    "verify_identity_factors":  "🔍",
    "request_otp":              "🔢",
    "confirm_otp":              "✅",
    "flag_kyc_step_up":         "🚩",
    "list_open_cases":          "📋",
    "open_case":                "📂",
    "update_case":              "✏️",
    "add_case_note":            "📝",
    "log_case_event":           "📜",
    "MongoDB MCP tools":        "🤖",
    "SemanticMemory.remember":  "💾",
}


# ── vertical animated SVG: agent ▶ tool spine ▶ MongoDB Atlas ─────────────
def _agent_svg(a: _Agent) -> str:
    color = a["color"]
    tools = a["tools"]
    n = len(tools)

    W = 380
    agent_h, mongo_h, tool_h, gap = 96, 96, 56, 14
    pad_top, pad_mid, pad_bot = 24, 28, 28
    tools_y0 = pad_top + agent_h + pad_mid
    tools_block = n * (tool_h + gap) - gap if n else 0
    H = tools_y0 + tools_block + pad_bot + mongo_h + 20
    spine_x = W // 2
    spine_top = pad_top + agent_h
    spine_bot = H - 20 - mongo_h
    box_w = W - 60
    box_x = (W - box_w) // 2

    parts: list[str] = []
    parts.append(
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
        f'preserveAspectRatio="xMidYMin meet" '
        f'style="width:100%;height:auto;display:block">'
    )
    parts.append(
        '<defs>'
        '<filter id="ag-glow" x="-60%" y="-60%" width="220%" height="220%">'
        '<feGaussianBlur stdDeviation="2.6"/><feMerge>'
        '<feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
        f'<linearGradient id="ag-spine" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{color}"/>'
        f'<stop offset="100%" stop-color="#10b981"/></linearGradient>'
        f'<path id="ag-down" d="M {spine_x} {spine_top} L {spine_x} {spine_bot}"/>'
        f'<path id="ag-up"   d="M {spine_x} {spine_bot} L {spine_x} {spine_top}"/>'
        '</defs>'
    )

    # Spine: faint base + animated dashed overlay
    parts.append(
        f'<line x1="{spine_x}" y1="{spine_top}" x2="{spine_x}" y2="{spine_bot}" '
        f'stroke="url(#ag-spine)" stroke-width="3" opacity="0.35"/>'
        f'<line x1="{spine_x}" y1="{spine_top}" x2="{spine_x}" y2="{spine_bot}" '
        f'stroke="url(#ag-spine)" stroke-width="2" stroke-dasharray="4 8" opacity="0.9">'
        f'<animate attributeName="stroke-dashoffset" from="0" to="-72" dur="1.6s" '
        f'repeatCount="indefinite"/></line>'
    )

    # Agent box (top)
    parts.append(
        f'<g transform="translate({box_x} {pad_top})">'
        f'<rect width="{box_w}" height="{agent_h}" rx="16" fill="#0f172a" '
        f'stroke="{color}" stroke-width="2" filter="url(#ag-glow)"/>'
        f'<text x="{box_w // 2}" y="38" text-anchor="middle" fill="{color}" '
        f'font-size="22" font-weight="700">{a["icon"]} {a["name"]}</text>'
        f'<text x="{box_w // 2}" y="62" text-anchor="middle" fill="#cbd5e1" '
        f'font-size="11">🧠 LLM · 🔁 ReAct loop · 🧰 {n} tools</text>'
        f'<text x="{box_w // 2}" y="80" text-anchor="middle" fill="#64748b" '
        f'font-size="10">▼ packets stream into the tool spine</text>'
        f'</g>'
    )
    # MongoDB box (bottom)
    parts.append(
        f'<g transform="translate({box_x} {spine_bot})">'
        f'<rect width="{box_w}" height="{mongo_h}" rx="16" fill="#022c22" '
        f'stroke="#10b981" stroke-width="2" filter="url(#ag-glow)"/>'
        f'<text x="{box_w // 2}" y="36" text-anchor="middle" fill="#10b981" '
        f'font-size="18" font-weight="700">🍃 MongoDB Atlas</text>'
        f'<text x="{box_w // 2}" y="58" text-anchor="middle" fill="#a7f3d0" '
        f'font-size="11">📑 structured · ⏱ time-series · 🌍 geo · 🕸 graph · 🧭 vector</text>'
        f'<text x="{box_w // 2}" y="78" text-anchor="middle" fill="#64748b" '
        f'font-size="10">▲ tool results return up the spine</text>'
        f'</g>'
    )

    # Per-tool boxes stacked along the spine
    for i, t in enumerate(tools):
        ty = tools_y0 + i * (tool_h + gap)
        ico = TOOL_ICON.get(t["name"], "🔧")
        reads = t.get("reads", [])
        writes = t.get("writes", [])
        rd = ("📥 " + ", ".join(reads)) if reads else ""
        wr = ("📤 " + ", ".join(writes)) if writes else ""
        rw = " · ".join(x for x in (rd, wr) if x) or "— no I/O"
        parts.append(
            f'<g transform="translate({box_x} {ty})">'
            f'<rect width="{box_w}" height="{tool_h}" rx="10" fill="#1e293b" '
            f'stroke="{color}" stroke-width="1.2" opacity="0.96"/>'
            f'<text x="14" y="22" fill="#f1f5f9" font-size="14">{ico}</text>'
            f'<text x="40" y="22" fill="#e2e8f0" font-size="12" '
            f'font-family="ui-monospace,monospace" font-weight="700">{t["name"]}</text>'
            f'<text x="14" y="42" fill="#94a3b8" font-size="9.5">{rw[:60]}</text>'
            f'<circle cx="{box_w - 14}" cy="14" r="4" fill="{color}" filter="url(#ag-glow)">'
            f'<animate attributeName="opacity" values="0.3;1;0.3" dur="1.6s" '
            f'begin="{i * 0.18:.2f}s" repeatCount="indefinite"/></circle>'
            f'</g>'
        )

    # Animated packets — agent → mongo (down, agent colour) and back (up, green)
    for k in range(3):
        parts.append(
            f'<circle r="4.5" fill="{color}" filter="url(#ag-glow)">'
            f'<animateMotion dur="2.4s" begin="{k * 0.8:.2f}s" repeatCount="indefinite">'
            f'<mpath href="#ag-down"/></animateMotion></circle>'
        )
        parts.append(
            f'<circle r="3.5" fill="#10b981" opacity="0.85">'
            f'<animateMotion dur="2.6s" begin="{0.4 + k * 0.8:.2f}s" repeatCount="indefinite">'
            f'<mpath href="#ag-up"/></animateMotion></circle>'
        )
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

    # Two-column layout: tall vertical pipeline on the left (sticky), prompt
    # + tools stacked on the right.
    with ui.row().classes("w-full p-4 gap-4 no-wrap items-start"):
        # ── LEFT: vertical pipeline ──────────────────────────────────────
        with ui.column().classes("w-[420px] shrink-0 sticky top-4 self-start gap-2"):
            with ui.card().tight().classes(
                "w-full bg-slate-900 p-3 rounded-xl"
            ).style(f"border:1px solid {a['color']}55"):
                with ui.row().classes("items-center w-full gap-2"):
                    ui.label("🔬").classes("text-lg")
                    ui.label("Internal pipeline").classes("text-sm font-semibold opacity-90")
                    ui.space()
                    ui.label(f"⚙ {len(a['tools'])} tools").classes(
                        "text-[10px] opacity-70 px-2 py-0.5 rounded bg-slate-800"
                    )
                ui.html(_agent_svg(a))
                ui.label("⬇ requests · ⬆ results · 🟢 hits to MongoDB Atlas").classes(
                    "text-[10px] opacity-60 mt-1 text-center"
                )

        # ── RIGHT: prompt + tools stacked ────────────────────────────────
        with ui.column().classes("flex-1 min-w-0 gap-4"):
            with ui.card().tight().classes("w-full bg-slate-900 p-3 rounded-xl"):
                with ui.row().classes("items-center gap-2"):
                    ui.label("📜").classes("text-lg")
                    ui.label("System-prompt summary").classes("text-sm font-semibold opacity-90")
                ui.label(a["prompt"]).classes(
                    "text-sm opacity-90 whitespace-pre-wrap mt-2"
                )

            with ui.card().tight().classes("w-full bg-slate-900 p-3 rounded-xl"):
                with ui.row().classes("items-center gap-2"):
                    ui.label("🛠").classes("text-lg")
                    ui.label("Tools — read / write surface").classes(
                        "text-sm font-semibold opacity-90"
                    )
                    ui.space()
                    ui.label("📥 reads   📤 writes").classes("text-[10px] opacity-60")
                with ui.column().classes("w-full mt-2 gap-1.5"):
                    for t in a["tools"]:
                        ico = TOOL_ICON.get(t["name"], "🔧")
                        with ui.row().classes(
                            "w-full items-start gap-2 p-2 rounded-md bg-slate-800/60"
                        ):
                            ui.label(ico).classes("text-base leading-tight w-6 text-center")
                            with ui.column().classes("flex-1 min-w-0 gap-0.5"):
                                with ui.row().classes("items-center gap-2 w-full"):
                                    ui.label(t["name"]).classes(
                                        "text-xs font-mono font-bold"
                                    ).style(f"color:{a['color']}")
                                    ui.space()
                                    ui.label(t["desc"]).classes(
                                        "text-[11px] opacity-75 text-right truncate"
                                    )
                                rd = t.get("reads", [])
                                wr = t.get("writes", [])
                                with ui.row().classes("items-center gap-2 flex-wrap"):
                                    if rd:
                                        ui.label("📥").classes("text-[11px]")
                                        for c in rd:
                                            ui.label(c).classes(
                                                "text-[10px] font-mono px-1.5 py-0.5 "
                                                "rounded bg-blue-900/40 text-blue-200"
                                            )
                                    if wr:
                                        ui.label("📤").classes("text-[11px] ml-2")
                                        for c in wr:
                                            ui.label(c).classes(
                                                "text-[10px] font-mono px-1.5 py-0.5 "
                                                "rounded bg-rose-900/40 text-rose-200"
                                            )
                                    if not rd and not wr:
                                        ui.label("— pure compute").classes(
                                            "text-[10px] opacity-50"
                                        )
