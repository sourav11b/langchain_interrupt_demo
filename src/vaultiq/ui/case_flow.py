"""Visual case-flow renderer used by the dashboard's '🗂️ Open cases' panel.

Replaces the per-case JSON dump with a vertical pipeline that shows how the
transaction moved through the agent graph (Fraud Sentinel → routing → optional
Customer Trust → Case Resolution) and a compact event timeline strip.

All data is read-only and reconstructed from MongoDB:
  * `cases.{score, reasons, status}`           → Fraud + Case nodes
  * `case_events`                               → timeline strip
  * `transactions.{amount, merchant_id, ts}`    → top "TRANSACTION" card
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from nicegui import ui

# Score thresholds (kept in sync with `_route_after_fraud` in agents/graph.py
# and the decision matrix in agents/case_agent.py).
_LOW, _MED, _HIGH, _CRIT = 0.40, 0.65, 0.90, 1.00

# Status → (emoji, accent colour). Anything unknown falls back to slate.
_STATUS_STYLE: dict[str, tuple[str, str]] = {
    "NEW":                  ("🆕", "#94a3b8"),
    "PENDING_CUSTOMER":     ("⏳", "#fbbf24"),
    "UNDER_INVESTIGATION":  ("🔎", "#fb923c"),
    "ESCALATED_AML":        ("🚨", "#ef4444"),
    "RESOLVED_FRAUD":       ("⛔", "#ef4444"),
    "RESOLVED_LEGITIMATE":  ("✅", "#10b981"),
}

# Per-event-type icons for the timeline strip.
_EVT_ICON: dict[str, str] = {
    "opened":              "🆕",
    "updated":             "🔄",
    "note_added":          "📝",
    "CASE_DECISION":       "⚖️",
    "CASE_AUTO_ESCALATED": "🚨",
}


def _kyc_from_events(events: list[dict]) -> dict[str, Any]:
    """Pull the KYC verdict out of the case-events stream.

    The Case Resolution agent persists `verified` and `claims_transaction`
    inside the payload of `CASE_DECISION` / `CASE_AUTO_ESCALATED` events, so
    we can display the real KYC outcome on the Customer Trust card instead
    of a generic 'step-up requested' placeholder.
    """
    out: dict[str, Any] = {}
    for e in events:
        if e.get("type") in ("CASE_DECISION", "CASE_AUTO_ESCALATED"):
            p = e.get("payload") or {}
            for k in ("verified", "claims_transaction"):
                if k in p and k not in out:
                    out[k] = p[k]
    return out


def _band_color(score: float | None) -> tuple[str, str]:
    """(label, hex) for a given fraud score."""
    s = float(score or 0.0)
    if s >= _HIGH:
        return ("CRITICAL", "#ef4444")
    if s >= _MED:
        return ("HIGH", "#fb923c")
    if s >= _LOW:
        return ("MEDIUM", "#fbbf24")
    return ("LOW", "#10b981")


def _fmt_ts(ts: Any) -> str:
    if isinstance(ts, datetime):
        return ts.astimezone(timezone.utc).strftime("%H:%M:%S")
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")) \
                .astimezone(timezone.utc).strftime("%H:%M:%S")
        except Exception:
            return ts[:19]
    return "—"


def _fmt_amount(amt: Any) -> str:
    try:
        return f"${float(amt):,.2f}"
    except Exception:
        return str(amt or "—")


def _arrow(label: str = "") -> None:
    """Vertical connector with an optional in-line decision label."""
    with ui.column().classes("w-full items-center gap-0 my-1"):
        ui.html('<div style="width:2px;height:14px;background:#475569"></div>')
        if label:
            ui.label(label).classes(
                "text-[10px] font-mono px-2 py-0.5 rounded "
                "bg-slate-800 text-slate-300 border border-slate-700"
            )
            ui.html('<div style="width:2px;height:14px;background:#475569"></div>')
        ui.html(
            '<div style="width:0;height:0;'
            'border-left:6px solid transparent;border-right:6px solid transparent;'
            'border-top:8px solid #475569"></div>'
        )


def _stage_card(*, icon: str, title: str, color: str,
                accent_text: str | None = None,
                body_lines: list[str] | None = None,
                chips: list[tuple[str, str]] | None = None,
                muted: bool = False) -> None:
    """One stage of the pipeline."""
    op = "opacity-50" if muted else ""
    with ui.card().tight().classes(
        f"w-full bg-slate-900 p-2.5 rounded-lg {op}"
    ).style(f"border-left:4px solid {color}"):
        with ui.row().classes("items-center w-full gap-2"):
            ui.label(icon).classes("text-base")
            ui.label(title).classes("text-xs font-bold uppercase tracking-wide") \
                .style(f"color:{color}")
            ui.space()
            if accent_text:
                ui.label(accent_text).classes(
                    "text-[10px] font-mono px-1.5 py-0.5 rounded"
                ).style(f"background:{color}22;color:{color};border:1px solid {color}55")
        for line in body_lines or []:
            ui.label(line).classes("text-[11px] opacity-85 mt-0.5 break-all")
        if chips:
            with ui.row().classes("w-full flex-wrap gap-1 mt-1"):
                for txt, c in chips:
                    ui.label(txt).classes(
                        "text-[10px] font-mono px-1.5 py-0.5 rounded"
                    ).style(f"background:{c}22;color:{c};border:1px solid {c}55")


def _score_bar(score: float | None, color: str) -> None:
    """Inline 0-1 score bar."""
    pct = max(0.0, min(1.0, float(score or 0.0))) * 100.0
    ui.html(
        f'<div style="width:100%;height:6px;background:#1e293b;'
        f'border-radius:3px;overflow:hidden;margin-top:4px">'
        f'<div style="width:{pct:.1f}%;height:100%;background:{color}"></div>'
        f'</div>'
    )



def render_case_flow(flow: dict) -> None:
    """Render the visual flow for one case into the current NiceGUI parent.

    `flow` is the dict returned by `stream_runner.fetch_case_flow(case_id)`.
    """
    case = flow.get("case") or {}
    events = flow.get("events") or []
    tx = flow.get("transaction") or {}
    cust = flow.get("customer") or {}

    score = case.get("score")
    band, sc_color = _band_color(score)
    status = (case.get("status") or "NEW").upper()
    st_icon, st_color = _STATUS_STYLE.get(status, ("📁", "#94a3b8"))

    # Did the run cross the medium-risk threshold? That's the routing decision
    # the LangGraph `_route_after_fraud` actually made.
    escalated = float(score or 0.0) >= _MED
    kyc = _kyc_from_events(events)

    with ui.column().classes("w-full gap-0"):

        # ── 1) Transaction (the input) ─────────────────────────────────
        tx_lines = []
        if tx.get("tx_id"):
            tx_lines.append(f"🆔 {tx['tx_id']}")
        if tx.get("merchant_id"):
            tx_lines.append(f"🏪 {tx['merchant_id']}")
        if cust.get("name"):
            tx_lines.append(f"👤 {cust['name']}  ({cust.get('customer_id','?')})")
        elif case.get("customer_id"):
            tx_lines.append(f"👤 {case['customer_id']}")
        _stage_card(
            icon="💳", title="Transaction", color="#38bdf8",
            accent_text=_fmt_amount(tx.get("amount")),
            body_lines=tx_lines or ["(transaction not found)"],
        )

        _arrow()

        # ── 2) Fraud Sentinel (always runs) ────────────────────────────
        reason_chips = [(r, sc_color) for r in (case.get("reasons") or [])[:6]]
        with ui.card().tight().classes(
            "w-full bg-slate-900 p-2.5 rounded-lg"
        ).style(f"border-left:4px solid {sc_color}"):
            with ui.row().classes("items-center w-full gap-2"):
                ui.label("🛡").classes("text-base")
                ui.label("Fraud Sentinel").classes(
                    "text-xs font-bold uppercase tracking-wide"
                ).style(f"color:{sc_color}")
                ui.space()
                ui.label(f"{float(score or 0):.2f} · {band}").classes(
                    "text-[10px] font-mono px-1.5 py-0.5 rounded"
                ).style(
                    f"background:{sc_color}22;color:{sc_color};"
                    f"border:1px solid {sc_color}55"
                )
            _score_bar(score, sc_color)
            if reason_chips:
                with ui.row().classes("w-full flex-wrap gap-1 mt-1.5"):
                    for txt, c in reason_chips:
                        ui.label(txt).classes(
                            "text-[10px] font-mono px-1.5 py-0.5 rounded"
                        ).style(
                            f"background:{c}22;color:{c};border:1px solid {c}55"
                        )

        # ── 3) Routing decision ────────────────────────────────────────
        if escalated:
            _arrow(f"score ≥ {_MED:g} · escalate")
            verified = kyc.get("verified")
            claims = kyc.get("claims_transaction")
            kyc_chips: list[tuple[str, str]] = []
            if verified is not None:
                kyc_chips.append(
                    ("✅ verified" if verified else "❌ not verified",
                     "#10b981" if verified else "#ef4444")
                )
            if claims is not None:
                kyc_chips.append(
                    ("👍 claims tx" if claims else "👎 disputes tx",
                     "#10b981" if claims else "#ef4444")
                )
            kyc_accent = "verdict logged" if kyc_chips else "KYC step-up"
            _stage_card(
                icon="🪪", title="Customer Trust", color="#ffa94d",
                accent_text=kyc_accent,
                body_lines=[
                    "identity check · OTP step-up · disputed-or-claimed",
                    f"customer kyc_status: {cust.get('kyc_status', '—')}",
                ],
                chips=kyc_chips or None,
            )
            _arrow()
        else:
            _arrow(f"score < {_MED:g} · skip KYC")
            _stage_card(
                icon="🪪", title="Customer Trust", color="#475569",
                accent_text="skipped", muted=True,
                body_lines=["routing bypassed this stage"],
            )
            _arrow()

        # ── 4) Case Resolution (final disposition) ─────────────────────
        _stage_card(
            icon="📁", title="Case Resolution", color=st_color,
            accent_text=f"{st_icon} {status}",
            body_lines=[
                f"🆔 {case.get('case_id', '—')}",
                f"📅 opened {_fmt_ts(case.get('created_at'))} · "
                f"updated {_fmt_ts(case.get('updated_at'))}",
            ],
        )

    # ── Event timeline strip ──────────────────────────────────────────
    if events:
        ui.label("⏱ event timeline").classes("text-[10px] opacity-60 mt-3")
        with ui.column().classes("w-full gap-0.5 mt-1"):
            for e in events:
                ico = _EVT_ICON.get(e.get("type", ""), "•")
                payload = e.get("payload") or {}
                summary_bits: list[str] = []
                if "score" in payload:
                    summary_bits.append(f"score={payload['score']}")
                if "fraud_score" in payload:
                    summary_bits.append(f"score={payload['fraud_score']}")
                if "decision" in payload:
                    summary_bits.append(f"→ {payload['decision']}")
                if "status" in payload:
                    summary_bits.append(f"→ {payload['status']}")
                if "verified" in payload:
                    summary_bits.append("verified" if payload["verified"] else "not-verified")
                if "claims_transaction" in payload:
                    summary_bits.append("claimed" if payload["claims_transaction"] else "disputed")
                if "len" in payload:
                    summary_bits.append(f"{payload['len']} chars")
                tail = ("  " + " · ".join(summary_bits)) if summary_bits else ""
                with ui.row().classes("items-center w-full gap-2"):
                    ui.label(_fmt_ts(e.get("ts"))).classes(
                        "text-[10px] font-mono opacity-60 w-16"
                    )
                    ui.label(ico).classes("text-xs")
                    ui.label(f"{e.get('type','?')}{tail}").classes(
                        "text-[11px] opacity-85"
                    )



# ── dedicated full-page case-flow view (`/case/{case_id}`) ────────────────
# Opened in a new browser tab from the dashboard's '🗂️ Open cases' panel
# so the auto-refreshing case list never destroys the detail you're reading.

@ui.page("/case/{case_id}")
def case_page(case_id: str) -> None:
    from src.vaultiq.ui.stream_runner import fetch_case_flow  # local: avoid cycle

    ui.dark_mode().enable()
    with ui.header(elevated=True).classes("items-center bg-slate-900 text-white"):
        ui.label("📁").classes("text-xl")
        ui.label(case_id).classes("text-base font-mono font-bold ml-2")
        ui.label("agent flow & decision trace").classes(
            "text-xs opacity-70 ml-3"
        )
        ui.space()
        ui.link("← back to dashboard", "/").classes("text-xs opacity-80")

    body = ui.column().classes("w-full max-w-3xl mx-auto p-4 gap-3")
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
            render_case_flow(flow)

    asyncio.create_task(_load())
