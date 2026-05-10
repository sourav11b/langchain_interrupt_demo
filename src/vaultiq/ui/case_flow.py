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
import json as _json
from datetime import datetime, timezone
from typing import Any

from nicegui import ui


# ── animation CSS ─────────────────────────────────────────────────────────
# Scoped to `.vq-step` containers so unrelated chips/bars on the page are
# unaffected. Each stage card defaults to opacity:0 and slides up + fades in
# when the JS orchestrator adds `.vq-revealed`. The `.vq-active` class adds
# a pulsing glow that follows the playhead.
_ANIMATION_CSS = """
@keyframes vq-fade-in-up {
  0%   { opacity: 0; transform: translateY(28px) scale(0.96); }
  100% { opacity: 1; transform: translateY(0)    scale(1);    }
}
@keyframes vq-pop {
  0%   { opacity: 0; transform: scale(0.55); }
  60%  { opacity: 1; transform: scale(1.10); }
  100% { opacity: 1; transform: scale(1);    }
}
@keyframes vq-stamp {
  0%   { opacity: 0; transform: scale(2.4) rotate(-14deg); }
  55%  { opacity: 1; transform: scale(0.92) rotate(0deg);  }
  100% { opacity: 1; transform: scale(1)    rotate(0deg);  }
}
@keyframes vq-glow {
  0%, 100% { box-shadow: 0 0 0  0 transparent; }
  50%      { box-shadow: 0 0 36px 4px var(--vq-glow, #38bdf8aa); }
}
@keyframes vq-arrow-flow {
  0%   { background-position: 0 0;    }
  100% { background-position: 0 24px; }
}

.vq-step          { opacity: 0; transform: translateY(28px); }
.vq-step.vq-revealed { animation: vq-fade-in-up 0.7s ease-out forwards; }
.vq-step.vq-active   { animation: vq-fade-in-up 0.7s ease-out forwards,
                                  vq-glow 1.8s ease-in-out infinite 0.7s; }

.vq-step .vq-bar       { width: 0; transition: width 1s ease-out 0.45s; }
.vq-step.vq-revealed .vq-bar { width: var(--vq-pct, 0%); }

.vq-step .vq-chip      { opacity: 0; transform: scale(0.65); }
.vq-step.vq-revealed .vq-chip {
  animation: vq-pop 0.4s ease-out forwards;
}
.vq-step.vq-revealed .vq-chip:nth-child(1) { animation-delay: 0.55s; }
.vq-step.vq-revealed .vq-chip:nth-child(2) { animation-delay: 0.70s; }
.vq-step.vq-revealed .vq-chip:nth-child(3) { animation-delay: 0.85s; }
.vq-step.vq-revealed .vq-chip:nth-child(4) { animation-delay: 1.00s; }
.vq-step.vq-revealed .vq-chip:nth-child(5) { animation-delay: 1.15s; }
.vq-step.vq-revealed .vq-chip:nth-child(6) { animation-delay: 1.30s; }
.vq-step.vq-revealed .vq-chip:nth-child(7) { animation-delay: 1.45s; }

.vq-step .vq-stamp     { opacity: 0; }
.vq-step.vq-revealed .vq-stamp {
  animation: vq-stamp 0.7s cubic-bezier(.34,1.56,.64,1) 0.35s forwards;
}

.vq-arrow .vq-arrow-line {
  width: 3px; height: 22px;
  background: repeating-linear-gradient(180deg, #475569 0 6px, transparent 6px 12px);
  background-size: 3px 24px;
}
.vq-arrow.vq-active .vq-arrow-line {
  background: repeating-linear-gradient(180deg, #38bdf8 0 6px, transparent 6px 12px);
  background-size: 3px 24px;
  animation: vq-arrow-flow 0.8s linear infinite;
}

.vq-event { opacity: 0; transform: translateX(-12px);
            transition: opacity 0.45s ease-out, transform 0.45s ease-out; }
.vq-event.vq-revealed { opacity: 1; transform: translateX(0); }

.vq-progress-bar { transition: width 0.55s ease-out; }

/* Stages that drill down to /agent_step/{case_id}/{stage} */
a.vq-drill { display: block; text-decoration: none; cursor: pointer;
             transition: transform 0.15s ease, filter 0.15s ease; }
a.vq-drill:hover { transform: scale(1.018); filter: brightness(1.08); }
"""


# ── orchestrator JS ───────────────────────────────────────────────────────
# Loaded into the initial page <head> (so the browser actually executes it).
# The body is filled in via NiceGUI's WebSocket patches AFTER the head is
# sent, so we can't auto-run on DOMContentLoaded — instead we poll for
# .vq-step elements every 150 ms (with a hard 12 s timeout) and start the
# journey as soon as they appear. Step names and narration HTML are read
# from hidden #vq-names / #vq-narrs spans rendered into the body.
_ANIMATION_JS = r"""
(function () {
  var runId = 0;

  function $(id)   { return document.getElementById(id); }
  function $$(sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); }

  function readJson(elId) {
    var el = $(elId);
    if (!el) return [];
    try { return JSON.parse(el.textContent || '[]'); }
    catch (_) { return []; }
  }

  // Force the browser to commit pending style changes so the next class add
  // re-triggers CSS animations from frame 0 (otherwise browsers optimize the
  // remove+add cycle away and the cards do not re-animate on replay).
  function forceReflow(els) {
    if (els && els.length && els[0]) { void els[0].offsetWidth; }
  }

  function play() {
    var my = ++runId;
    var steps = $$('.vq-step');
    if (steps.length === 0) { console.log('[vaultiq] no .vq-step yet'); return; }
    console.log('[vaultiq] play()  steps=' + steps.length + ' run=' + my);
    var arrows = $$('.vq-arrow');
    var events = $$('.vq-event');
    var names  = readJson('vq-names');
    var narrs  = readJson('vq-narrs');

    // Reset state. forceReflow between remove and re-add (which happens in
    // next() after the 350ms timeout below) makes CSS animations restart.
    steps.forEach(function (s) { s.classList.remove('vq-revealed', 'vq-active'); });
    arrows.forEach(function (a) { a.classList.remove('vq-active'); });
    events.forEach(function (e) { e.classList.remove('vq-revealed'); });
    forceReflow(steps);

    var pbar0 = $('vq-progress-bar');
    if (pbar0) pbar0.style.width = '0%';
    var replay0 = $('vq-replay-btn');
    if (replay0) replay0.style.display = 'none';

    var i = 0;
    function next() {
      if (my !== runId) return;
      if (i >= steps.length) {
        events.forEach(function (e, j) {
          setTimeout(function () { e.classList.add('vq-revealed'); }, j * 220);
        });
        var indi2 = $('vq-step-indicator');
        if (indi2) indi2.innerHTML =
          '<span style="color:#10b981">\u2705</span> journey complete';
        var pbar2 = $('vq-progress-bar');
        if (pbar2) pbar2.style.width = '100%';
        var replay2 = $('vq-replay-btn');
        if (replay2) replay2.style.display = 'inline-flex';
        return;
      }
      if (i > 0) {
        steps[i - 1].classList.remove('vq-active');
        if (arrows[i - 1]) arrows[i - 1].classList.add('vq-active');
      }
      steps[i].classList.add('vq-revealed', 'vq-active');
      var nm = names[i] || ('step ' + (i + 1));
      var indi = $('vq-step-indicator');
      if (indi) indi.innerHTML =
        '<span style="color:#38bdf8">\u25B6</span> step ' + (i + 1) +
        ' of ' + steps.length + ' \u00B7 <b>' + nm + '</b>';
      var narrEl = $('vq-narration');
      if (narrEl && narrs[i] !== undefined) narrEl.innerHTML = narrs[i];
      var pbar = $('vq-progress-bar');
      if (pbar) pbar.style.width = (((i + 1) / steps.length) * 100) + '%';
      i += 1;
      setTimeout(next, 1900);
    }
    setTimeout(next, 350);
  }

  // Programmatic click wiring — more reliable than inline onclick across
  // NiceGUI/Vue re-renders. Idempotent via the __vqWired marker.
  function wireReplay() {
    var btn = $('vq-replay-btn');
    if (btn && !btn.__vqWired) {
      btn.addEventListener('click', function (ev) {
        ev.preventDefault();
        console.log('[vaultiq] replay clicked');
        play();
      });
      btn.__vqWired = true;
      console.log('[vaultiq] replay button wired');
    }
  }

  window.vqReplayCaseFlow = play;

  // Poll for the case body to mount (streams in via NiceGUI WebSocket patches
  // after the initial HTML response). Bail after ~12s; keep re-wiring slowly
  // in case Vue replaces the button later.
  var attempts = 0;
  function tryStart() {
    wireReplay();
    if (document.querySelectorAll('.vq-step').length > 0) {
      play();
      setInterval(wireReplay, 1500);
    } else if (attempts++ < 80) {
      setTimeout(tryStart, 150);
    } else {
      console.log('[vaultiq] gave up waiting for .vq-step elements');
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', tryStart);
  } else {
    tryStart();
  }
})();
"""

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
    """Vertical connector with an optional in-line decision label.

    The wrapper carries `vq-arrow` so the JS orchestrator can flip it to
    `vq-active` once both adjacent steps have been revealed (then the
    dashes start flowing).
    """
    with ui.column().classes("w-full items-center gap-0 my-1 vq-arrow"):
        ui.html('<div class="vq-arrow-line"></div>')
        if label:
            ui.label(label).classes(
                "text-[10px] font-mono px-2 py-0.5 rounded "
                "bg-slate-800 text-slate-300 border border-slate-700"
            )
            ui.html('<div class="vq-arrow-line"></div>')
        ui.html(
            '<div style="width:0;height:0;'
            'border-left:6px solid transparent;border-right:6px solid transparent;'
            'border-top:8px solid #475569"></div>'
        )


def _stage_card(*, icon: str, title: str, color: str,
                accent_text: str | None = None,
                body_lines: list[str] | None = None,
                chips: list[tuple[str, str]] | None = None,
                muted: bool = False,
                drill_hint: bool = False) -> None:
    """One stage of the pipeline.

    Chips and the accent badge are tagged with `vq-chip` / `vq-stamp` so
    they get popped/stamped in by the orchestrator when the parent step is
    revealed. Outside a `.vq-step` wrapper they render normally because the
    animation CSS is scoped under `.vq-step`.

    `drill_hint=True` shows a small `🔍` cue indicating the card is a
    clickable drill-down link (visual affordance for the wrapping `<a>`).
    """
    op = "opacity-50" if muted else ""
    with ui.card().tight().classes(
        f"w-full bg-slate-900 p-2.5 rounded-lg {op}"
    ).style(f"border-left:4px solid {color};--vq-glow:{color}aa"):
        with ui.row().classes("items-center w-full gap-2"):
            ui.label(icon).classes("text-base")
            ui.label(title).classes("text-xs font-bold uppercase tracking-wide") \
                .style(f"color:{color}")
            ui.space()
            if accent_text:
                ui.label(accent_text).classes(
                    "vq-stamp text-[10px] font-mono px-1.5 py-0.5 rounded"
                ).style(f"background:{color}22;color:{color};border:1px solid {color}55")
            if drill_hint:
                ui.label("🔍").classes("text-[11px] opacity-60 ml-1") \
                    .tooltip("click for technical drill-down")
        for line in body_lines or []:
            ui.label(line).classes("text-[11px] opacity-85 mt-0.5 break-all")
        if chips:
            with ui.row().classes("w-full flex-wrap gap-1 mt-1"):
                for txt, c in chips:
                    ui.label(txt).classes(
                        "vq-chip text-[10px] font-mono px-1.5 py-0.5 rounded"
                    ).style(f"background:{c}22;color:{c};border:1px solid {c}55")


def _score_bar(score: float | None, color: str) -> None:
    """Inline 0-1 score bar that animates from 0 to target inside a vq-step."""
    pct = max(0.0, min(1.0, float(score or 0.0))) * 100.0
    ui.html(
        f'<div style="width:100%;height:6px;background:#1e293b;'
        f'border-radius:3px;overflow:hidden;margin-top:4px;'
        f'--vq-pct:{pct:.1f}%">'
        f'<div class="vq-bar" style="height:100%;background:{color}"></div>'
        f'</div>'
    )



def _step(name: str, narration_html: str,
          step_names: list[str], narrations: list[str],
          drill_href: str | None = None):
    """Open a `.vq-step` wrapper and record its name/narration.

    If `drill_href` is given, the wrapper is an `<a target="_blank">` so the
    whole card becomes a clickable link to the technical drill-down. Otherwise
    a plain column. Either way the wrapper carries `.vq-step` so the journey
    orchestrator JS reveals it in sequence.
    """
    step_names.append(name)
    narrations.append(narration_html)
    if drill_href:
        return ui.link(target=drill_href, new_tab=True).classes(
            "w-full vq-step vq-drill gap-0"
        )
    return ui.column().classes("w-full vq-step gap-0")


def render_case_flow(flow: dict) -> None:
    """Render the case journey as an animated playback into the current parent.

    Inject the animation CSS, build a sticky playback control bar (step
    indicator + narration + progress bar + replay button), then walk each
    stage wrapped in a `.vq-step` div. The orchestrator JS at the end of
    the body then steps through them on a 1.9s cadence.
    """
    case = flow.get("case") or {}
    events = flow.get("events") or []
    tx = flow.get("transaction") or {}
    cust = flow.get("customer") or {}

    score = case.get("score")
    band, sc_color = _band_color(score)
    status = (case.get("status") or "NEW").upper()
    st_icon, st_color = _STATUS_STYLE.get(status, ("📁", "#94a3b8"))
    escalated = float(score or 0.0) >= _MED
    kyc = _kyc_from_events(events)
    cid = case.get("case_id", "")

    step_names: list[str] = []
    narrations: list[str] = []

    def _drill(stage: str) -> str | None:
        return f"/agent_step/{cid}/{stage}" if cid else None

    # CSS + orchestrator JS are injected once into <head> by case_page (so
    # they actually execute). Here we just build the body content.

    # ── Sticky playback control bar ──────────────────────────────────────
    with ui.card().tight().classes(
        "w-full bg-slate-900 p-3 rounded-xl sticky top-2 z-10"
    ).style(f"border:1px solid {sc_color}55"):
        with ui.row().classes("items-center w-full gap-3"):
            ui.label("🎬").classes("text-xl")
            ui.html(
                '<div id="vq-step-indicator" class="text-sm font-semibold">'
                '<span style="color:#38bdf8">▶</span> starting…</div>'
            )
            ui.space()
            # Click is wired programmatically by _ANIMATION_JS.wireReplay().
            ui.html(
                '<button id="vq-replay-btn" type="button" '
                'style="display:none;background:#1e293b;color:#e2e8f0;'
                'border:1px solid #334155;border-radius:6px;padding:4px 10px;'
                'font-size:12px;cursor:pointer">↻ replay</button>'
            )
        ui.html(
            '<div style="width:100%;height:4px;background:#1e293b;'
            'border-radius:2px;margin-top:8px;overflow:hidden">'
            f'<div id="vq-progress-bar" class="vq-progress-bar" '
            f'style="width:0%;height:100%;background:linear-gradient'
            f'(90deg,#38bdf8,{sc_color},{st_color})"></div></div>'
        )
        ui.html(
            '<div id="vq-narration" '
            'style="margin-top:10px;padding:8px 10px;background:#0f172a;'
            'border-left:3px solid #38bdf8;border-radius:4px;'
            'font-size:12px;line-height:1.5;min-height:38px;color:#e2e8f0">'
            'Playing back the agent journey for this case… '
            '<span style="opacity:0.7">'
            '🔍 click any stage card for the LangChain · LangGraph · '
            'Atlas drill-down (opens in a new tab).'
            '</span></div>'
        )

    # ── Pipeline body: each stage is a .vq-step wrapper ──────────────────
    with ui.column().classes("w-full gap-0 mt-4"):

        # 1) Transaction
        cust_name = cust.get("name") or case.get("customer_id", "?")
        tx_lines: list[str] = []
        if tx.get("tx_id"):
            tx_lines.append(f"🆔 {tx['tx_id']}")
        if tx.get("merchant_id"):
            tx_lines.append(f"🏪 {tx['merchant_id']}")
        if cust.get("name"):
            tx_lines.append(f"👤 {cust['name']}  ({cust.get('customer_id','?')})")
        elif case.get("customer_id"):
            tx_lines.append(f"👤 {case['customer_id']}")
        narr_tx = (
            f"💳 A <b>{_fmt_amount(tx.get('amount'))}</b> payment from "
            f"<b>{cust_name}</b> just hit the system "
            f"(merchant <code>{tx.get('merchant_id','?')}</code>). "
            f"It enters the LangGraph at the Fraud Sentinel node."
        )
        with _step("Transaction", narr_tx, step_names, narrations,
                   drill_href=_drill("transaction")):
            _stage_card(
                icon="💳", title="Transaction", color="#38bdf8",
                accent_text=_fmt_amount(tx.get("amount")),
                body_lines=tx_lines or ["(transaction not found)"],
                drill_hint=bool(cid),
            )

        _arrow()

        # 2) Fraud Sentinel
        reason_chips = [(r, sc_color) for r in (case.get("reasons") or [])[:6]]
        first_reason = (case.get("reasons") or ["(no reason recorded)"])[0]
        narr_fs = (
            f"🛡 The Fraud Sentinel agent ran its toolkit (score_transaction, "
            f"geo, velocity, KB lookup, …) and assigned "
            f"<b style='color:{sc_color}'>{float(score or 0):.2f}</b> "
            f"<span style='color:{sc_color}'>({band})</span>. "
            f"Top reason: <i>{first_reason[:140]}</i>"
        )
        with _step("Fraud Sentinel", narr_fs, step_names, narrations,
                   drill_href=_drill("fraud_sentinel")):
            _stage_card(
                icon="🛡", title="Fraud Sentinel", color=sc_color,
                accent_text=f"{float(score or 0):.2f} · {band}",
                body_lines=None,
                chips=reason_chips or None,
                drill_hint=bool(cid),
            )
            # Score bar lives outside the chips row — render after the card
            # so it animates inside the same .vq-step wrapper.
            _score_bar(score, sc_color)

        # 3) Routing + Customer Trust (sequential, both as their own steps)
        if escalated:
            _arrow(f"score ≥ {_MED:g} · escalate")
            verified = kyc.get("verified")
            claims = kyc.get("claims_transaction")
            kyc_chips: list[tuple[str, str]] = []
            if verified is not None:
                kyc_chips.append(
                    ("✅ verified" if verified else "❌ not verified",
                     "#10b981" if verified else "#ef4444"))
            if claims is not None:
                kyc_chips.append(
                    ("👍 claims tx" if claims else "👎 disputes tx",
                     "#10b981" if claims else "#ef4444"))
            v_txt = "verified" if verified else ("could not verify" if verified is False else "—")
            c_txt = "claimed it" if claims else ("disputed it" if claims is False else "—")
            narr_kyc = (
                f"🪪 Score crossed the {_MED:g} threshold, so LangGraph routed "
                f"to <b>Customer Trust</b>. Identity factors were checked and "
                f"the customer was contacted for OTP step-up — outcome: "
                f"<b>{v_txt}</b>, and the customer <b>{c_txt}</b>."
            )
            with _step("Customer Trust", narr_kyc, step_names, narrations,
                       drill_href=_drill("customer_trust")):
                _stage_card(
                    icon="🪪", title="Customer Trust", color="#ffa94d",
                    accent_text="verdict logged" if kyc_chips else "KYC step-up",
                    body_lines=[
                        "identity check · OTP step-up · disputed-or-claimed",
                        f"customer kyc_status: {cust.get('kyc_status', '—')}",
                    ],
                    chips=kyc_chips or None,
                    drill_hint=bool(cid),
                )
            _arrow()
        else:
            _arrow(f"score < {_MED:g} · skip KYC")
            narr_skip = (
                f"🪪 Score stayed below {_MED:g}, so the LangGraph router "
                f"<b>bypassed Customer Trust</b> and went straight to Case "
                f"Resolution. No customer contact needed for this transaction."
            )
            with _step("Customer Trust (skipped)", narr_skip, step_names, narrations,
                       drill_href=_drill("customer_trust")):
                _stage_card(
                    icon="🪪", title="Customer Trust", color="#475569",
                    accent_text="skipped", muted=True,
                    body_lines=["routing bypassed this stage"],
                    drill_hint=bool(cid),
                )
            _arrow()

        # 4) Case Resolution
        narr_case = (
            f"📁 Case Resolution applied the decision matrix and recorded the "
            f"final disposition: <b style='color:{st_color}'>{st_icon} {status}</b> "
            f"on case <code>{case.get('case_id','?')}</code>. An investigator "
            f"note was vector-indexed for future recall."
        )
        with _step("Case Resolution", narr_case, step_names, narrations,
                   drill_href=_drill("case_resolution")):
            _stage_card(
                icon="📁", title="Case Resolution", color=st_color,
                accent_text=f"{st_icon} {status}",
                body_lines=[
                    f"🆔 {case.get('case_id', '—')}",
                    f"📅 opened {_fmt_ts(case.get('created_at'))} · "
                    f"updated {_fmt_ts(case.get('updated_at'))}",
                ],
                drill_hint=bool(cid),
            )

    # ── Event timeline strip — each event slides in after the journey ─────
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
                with ui.row().classes("items-center w-full gap-2 vq-event"):
                    ui.label(_fmt_ts(e.get("ts"))).classes(
                        "text-[10px] font-mono opacity-60 w-16"
                    )
                    ui.label(ico).classes("text-xs")
                    ui.label(f"{e.get('type','?')}{tail}").classes(
                        "text-[11px] opacity-85"
                    )

    # ── Hand off step names + narrations to the JS orchestrator ───────────
    # Hidden text spans (not <script> tags) because NiceGUI's ui.html injects
    # via Vue's v-html → innerHTML, and innerHTML-set scripts never execute.
    # The orchestrator (loaded into <head> by case_page) reads these via
    # `.textContent` and `JSON.parse`.
    import html as _html
    ui.html(
        '<div id="vq-data" style="display:none">'
        f'<span id="vq-names">{_html.escape(_json.dumps(step_names))}</span>'
        f'<span id="vq-narrs">{_html.escape(_json.dumps(narrations))}</span>'
        '</div>'
    )



# ── dedicated full-page case-flow view (`/case/{case_id}`) ────────────────
# Opened in a new browser tab from the dashboard's '🗂️ Open cases' panel
# so the auto-refreshing case list never destroys the detail you're reading.

@ui.page("/case/{case_id}")
def case_page(case_id: str) -> None:
    from src.vaultiq.ui.stream_runner import fetch_case_flow  # local: avoid cycle

    ui.dark_mode().enable()
    # Inject animation CSS + orchestrator JS into the initial page <head>.
    # ui.html() inside the body would not execute the script (innerHTML
    # injection skips <script> tags), so we add it here where it lands in
    # the initial HTML response and the browser parses it normally.
    ui.add_head_html(f"<style>{_ANIMATION_CSS}</style>")
    ui.add_head_html(f"<script>{_ANIMATION_JS}</script>")
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
