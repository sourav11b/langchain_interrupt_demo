"""VaultIQ — NiceGUI live operations dashboard.

NiceGUI replaces the previous Streamlit dashboard. The reactive model means
long-running agent calls run in a thread-pool without blocking the event loop,
and any per-component error is shown as a toast — never a blank page.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from nicegui import app, ui

from scripts.reset_demo import reset as reset_demo
from src.vaultiq.db.atlas_admin import AtlasAdminError, ensure_cluster_running, get_cluster_status
from src.vaultiq.logging_setup import configure_logging
from src.vaultiq.scenarios.injector import SCENARIOS, build_scenario_transaction
from src.vaultiq.tools._common import jsonable
from src.vaultiq.ui.flow_svg import flow_svg
from src.vaultiq.ui import agent_detail as _agent_detail  # noqa: F401  registers /agent/{id}
from src.vaultiq.ui import storage_detail as _storage_detail  # noqa: F401  registers /storage
from src.vaultiq.ui import case_flow as _case_flow  # noqa: F401  registers /case/{id}
from src.vaultiq.ui import agent_step as _agent_step  # noqa: F401  registers /agent_step/{cid}/{stage}
from src.vaultiq.ui.stream_runner import (
    execute_through_agents,
    fetch_collection_counts,
    fetch_recent_case_events,
    fetch_recent_cases,
    generate_baseline_transaction,
)

configure_logging()
log = logging.getLogger(__name__)


# ── NiceGUI 3.11 timer-after-slot-deletion guard ────────────────────────────
# When a client disconnects (tab close, ws reconnect, hot-reload) NiceGUI GCs
# its slots but lets timers from that client keep firing. The first call after
# slot deletion raises `RuntimeError: The parent slot of the element has been
# deleted.` from inside `Timer._get_context`, which kills our render loops
# (e.g. render_runs → live tx feed stops repainting until a hard refresh).
# Patch `_get_context` to deactivate the orphaned timer instead of raising.
def _install_safe_timer_patch() -> None:
    from contextlib import nullcontext
    from nicegui.elements.timer import Timer

    if getattr(Timer, "_vq_safe_patch", False):
        return

    _orig_get_context = Timer._get_context

    def _safe_get_context(self):
        try:
            return _orig_get_context(self)
        except RuntimeError as exc:
            if "parent slot" in str(exc).lower():
                try:
                    self.deactivate()
                except Exception:
                    pass
                return nullcontext()
            raise

    Timer._get_context = _safe_get_context  # type: ignore[method-assign]
    Timer._vq_safe_patch = True             # type: ignore[attr-defined]
    log.info("nicegui Timer._get_context patched (slot-deletion guard active)")


_install_safe_timer_patch()


# ── process-wide state (single-tenant demo) ──────────────────────────────────
STATE: dict = {
    "runs": [],            # newest first, list of {tx, result}
    "auto_run": False,
    "selected_case": None,
    "running_jobs": 0,
    "cluster": {"state": "CHECKING", "paused": None, "ready": False, "error": None},
    "cluster_check_started": False,
}

AGENT_COLOR = {
    "fraud_sentinel":  "#ff6b6b",
    "customer_trust":  "#ffa94d",
    "case_resolution": "#4dabf7",
    "memory_writer":   "#82c91e",
}


# ── async helpers (off-loop blocking work) ───────────────────────────────────
async def _run_in_pool(fn, *args):
    return await asyncio.get_running_loop().run_in_executor(None, fn, *args)


async def ensure_cluster_task() -> None:
    """Background task: check cluster, resume if paused, poll until ready."""
    if STATE["cluster_check_started"]:
        return
    STATE["cluster_check_started"] = True

    def _cb(status: dict) -> None:
        STATE["cluster"] = {**status, "error": None}

    try:
        await _run_in_pool(ensure_cluster_running, _cb)
        log.info("Atlas cluster ready.")
    except AtlasAdminError as exc:
        log.exception("Atlas cluster check failed")
        STATE["cluster"] = {"state": "ERROR", "paused": None, "ready": False, "error": str(exc)}
    except Exception as exc:
        log.exception("Atlas cluster check raised")
        STATE["cluster"] = {"state": "ERROR", "paused": None, "ready": False, "error": repr(exc)}


def _cluster_is_ready() -> bool:
    return bool(STATE.get("cluster", {}).get("ready"))


async def inject_one(scenario_id: str) -> None:
    if not _cluster_is_ready():
        ui.notify("Atlas cluster not ready yet — please wait.", type="warning")
        return
    STATE["running_jobs"] += 1
    try:
        tx = await _run_in_pool(build_scenario_transaction, scenario_id)
        ui.notify(f"Running {tx['tx_id']} through 3-agent flow…", type="ongoing", timeout=2000)
        result = await _run_in_pool(execute_through_agents, tx)
        STATE["runs"].insert(0, {"tx": tx, "result": result})
        STATE["runs"][:] = STATE["runs"][:25]
        score = (result.get("fraud") or {}).get("score")
        case_id = (result.get("case") or {}).get("case_id")
        ui.notify(
            f"✅ {tx['tx_id']}  score={score}  case={case_id or '—'}",
            type="positive", timeout=4000,
        )
    except Exception as exc:
        log.exception("inject_one failed")
        ui.notify(f"❌ inject failed: {exc}", type="negative", timeout=8000)
    finally:
        STATE["running_jobs"] -= 1


async def do_reset(*, keep_history: bool, do_seed: bool) -> None:
    """Run scripts.reset_demo.reset off-loop with toast feedback."""
    if not _cluster_is_ready():
        ui.notify("Atlas cluster not ready yet — please wait.", type="warning")
        return
    if STATE["running_jobs"] > 0:
        ui.notify("Agent jobs in flight — try again in a moment.", type="warning")
        return

    # Pause the live stream while we wipe so no new tx lands mid-reset.
    prev_auto = STATE.get("auto_run", False)
    STATE["auto_run"] = False
    STATE["running_jobs"] += 1
    label = "wipe + reseed" + (" (keep history)" if keep_history else "")
    if not do_seed:
        label = "wipe only"
    try:
        ui.notify(f"🔄 Resetting demo data — {label}…", type="ongoing", timeout=4000)
        await _run_in_pool(
            lambda: reset_demo(
                customers=500, history_days=14,
                keep_history=keep_history, do_seed=do_seed, dry_run=False,
            )
        )
        # Clear in-memory caches so the dashboard does not show stale rows.
        STATE["runs"][:] = []
        STATE["selected_case"] = None
        ui.notify(f"✅ Reset complete — {label}.", type="positive", timeout=5000)
    except Exception as exc:
        log.exception("do_reset failed")
        ui.notify(f"❌ reset failed: {exc}", type="negative", timeout=10000)
    finally:
        STATE["running_jobs"] -= 1
        STATE["auto_run"] = prev_auto


async def stream_tick() -> None:
    if not STATE["auto_run"] or STATE["running_jobs"] > 0 or not _cluster_is_ready():
        return
    STATE["running_jobs"] += 1
    try:
        tx = await _run_in_pool(generate_baseline_transaction)
        result = await _run_in_pool(execute_through_agents, tx)
        STATE["runs"].insert(0, {"tx": tx, "result": result})
        STATE["runs"][:] = STATE["runs"][:25]
    except Exception as exc:
        log.exception("stream_tick failed")
        ui.notify(f"⚠ stream tick failed: {exc}", type="warning", timeout=4000)
    finally:
        STATE["running_jobs"] -= 1


def _safe_dt(value, fmt: str = "%H:%M:%S") -> str:
    try:
        return value.strftime(fmt)
    except Exception:
        return str(value) if value is not None else "—"


def _runs_table_rows() -> list[dict]:
    out: list[dict] = []
    for r in STATE["runs"][:25]:
        tx, res = r["tx"], r["result"]
        f = res.get("fraud") or {}
        c = res.get("case") or {}
        out.append({
            "ts":          _safe_dt(tx.get("ts")),
            "tx_id":       tx.get("tx_id"),
            "scenario":    tx.get("scenario_label", "—"),
            "customer":    tx.get("customer_id"),
            "amount":      tx.get("amount"),
            "country":     tx.get("country"),
            "score":       f.get("score"),
            "band":        f.get("band"),
            "case":        c.get("case_id") or "—",
            "case_status": c.get("status") or "—",
        })
    return out


TX_COLUMNS = [
    {"name": "ts",          "label": "time",      "field": "ts",          "align": "left"},
    {"name": "tx_id",       "label": "tx_id",     "field": "tx_id",       "align": "left"},
    {"name": "scenario",    "label": "scenario",  "field": "scenario",    "align": "left"},
    {"name": "customer",    "label": "customer",  "field": "customer",    "align": "left"},
    {"name": "amount",      "label": "amt",       "field": "amount",      "align": "right"},
    {"name": "country",     "label": "ctry",      "field": "country",     "align": "left"},
    {"name": "score",       "label": "score",     "field": "score",       "align": "right"},
    {"name": "band",        "label": "band",      "field": "band",        "align": "left"},
    {"name": "case",        "label": "case",      "field": "case",        "align": "left"},
    {"name": "case_status", "label": "status",    "field": "case_status", "align": "left"},
]


# ── page ─────────────────────────────────────────────────────────────────────
@ui.page("/")
def index() -> None:
    ui.dark_mode().enable()
    ui.add_head_html(
        "<style>"
        ".q-table tbody td{font-size:.78rem}"
        ".q-table thead th{font-size:.78rem;font-weight:600}"
        ".vq-tx-table tbody tr{cursor:pointer;transition:background-color .12s}"
        ".vq-tx-table tbody tr:hover{background-color:#1e293b !important}"
        "</style>"
    )

    # Kick off the cluster check on first ever page load.
    if not STATE["cluster_check_started"]:
        asyncio.create_task(ensure_cluster_task())

    # ── header ─────────────────────────────────────────────────────────────
    with ui.header(elevated=True).classes("items-center bg-slate-900 text-white"):
        ui.label("🛡️ VaultIQ").classes("text-2xl font-bold")
        ui.label("NextGen AI Financial Intelligence — MongoDB Atlas · LangGraph · LangSmith") \
            .classes("text-xs opacity-70 ml-3")
        ui.space()
        running_lbl = ui.label().classes("text-xs opacity-70 mr-4")
        clock_lbl = ui.label().classes("text-xs opacity-70")

        def _tick_header():
            running_lbl.set_text(f"jobs: {STATE['running_jobs']}")
            clock_lbl.set_text(datetime.now(tz=timezone.utc).strftime("%H:%M:%S UTC"))

        ui.timer(1.0, _tick_header)

    # ── cluster status banner (top of page) ────────────────────────────────
    cluster_banner = ui.html("").classes("w-full px-4 pt-3")

    def _refresh_banner():
        cs = STATE.get("cluster", {})
        state = cs.get("state", "CHECKING")
        ready = cs.get("ready", False)
        err = cs.get("error")
        if ready:
            html = (
                f'<div style="background:#2b8a3e;color:white;padding:8px 14px;'
                f'border-radius:6px;font-size:.85rem">'
                f'✅ Atlas cluster <b>IDLE</b> — agents are live.</div>'
            )
        elif err:
            html = (
                f'<div style="background:#c92a2a;color:white;padding:8px 14px;'
                f'border-radius:6px;font-size:.85rem">'
                f'❌ Atlas cluster check failed: {err}</div>'
            )
        else:
            label = "starting up" if cs.get("paused") or state in ("REPAIRING", "UPDATING") else state.lower()
            html = (
                f'<div style="background:#f59f00;color:white;padding:8px 14px;'
                f'border-radius:6px;font-size:.85rem">'
                f'🟡 <b>Atlas cluster is {label}</b> — please wait, the inject button will '
                f'enable when the cluster is ready (this can take 1–5 minutes from a paused state).</div>'
            )
        cluster_banner.set_content(html)

    ui.timer(1.5, _refresh_banner, immediate=True)

    # ── animated agent / data flow diagram ─────────────────────────────────
    with ui.row().classes("w-full px-4 pt-2 items-center"):
        ui.label("🔀 Agent + data flow").classes("text-sm font-semibold opacity-80")
        ui.space()
        flow_status = ui.label("packets flowing").classes("text-xs opacity-60")
    flow_card = ui.card().tight().classes("w-full mx-4 my-1 bg-slate-900 rounded-lg p-2 overflow-hidden")
    with flow_card:
        ui.html(flow_svg()).classes("w-full")

    def _flow_pulse():
        # Speed-up cue: brighten the card border when an agent is mid-run.
        active = STATE["running_jobs"] > 0
        flow_card.classes(replace="w-full mx-4 my-1 rounded-lg p-2 overflow-hidden "
                                  + ("bg-slate-800 ring-2 ring-rose-400 ring-offset-2 ring-offset-slate-900"
                                     if active else "bg-slate-900"))
        flow_status.set_text("⚡ live — agent run in flight" if active else "packets flowing")

    ui.timer(0.8, _flow_pulse, immediate=True)

    # ── sidebar ────────────────────────────────────────────────────────────
    with ui.left_drawer(value=True, fixed=True).classes("bg-slate-800 text-white p-4 w-72"):
        ui.label("⚙️ Controls").classes("text-lg font-semibold mb-2")

        # Sticky across hard-refreshes via per-browser server-side storage
        # (requires storage_secret in main(), which is already set).
        _saved_live = bool(app.storage.user.get("vq_live_stream", False))
        STATE["auto_run"] = _saved_live
        live_sw = ui.switch("Live stream (one tx / 6 s)", value=_saved_live)

        def _on_live_toggle(e) -> None:
            v = bool(e.value)
            STATE["auto_run"] = v
            app.storage.user["vq_live_stream"] = v

        live_sw.on_value_change(_on_live_toggle)

        ui.label("Inject scenario").classes("mt-4 font-semibold")
        scenario_options = {s.id: f"{s.label}  · hint {s.risk_hint}" for s in SCENARIOS}
        scenario_sel = ui.select(scenario_options, value="ato_sim_swap").classes("w-full")
        inject_btn = ui.button("🚀 Inject + run agents",
                               on_click=lambda: inject_one(scenario_sel.value)) \
            .classes("w-full mt-2 bg-rose-500")
        inject_btn.set_enabled(False)
        live_sw.set_enabled(False)

        def _gate_controls():
            ready = _cluster_is_ready()
            inject_btn.set_enabled(ready)
            live_sw.set_enabled(ready)
            if not ready and live_sw.value:
                live_sw.value = False
                STATE["auto_run"] = False
                app.storage.user["vq_live_stream"] = False

        ui.timer(1.5, _gate_controls, immediate=True)

        ui.separator().classes("my-4")
        ui.label("MongoDB collections").classes("text-sm opacity-70")
        counts_lbl = ui.label("loading…").classes("text-xs font-mono whitespace-pre")

        async def _refresh_counts():
            try:
                c = await _run_in_pool(fetch_collection_counts)
                counts_lbl.set_text("\n".join(f"{k:<14} {v:,}" for k, v in c.items()))
            except Exception as exc:
                counts_lbl.set_text(f"<error: {exc}>")

        ui.timer(8.0, _refresh_counts, immediate=True)

        ui.separator().classes("my-4")
        ui.label("Demo data").classes("text-sm opacity-70")

        # Confirmation dialog — built once, opened on button click.
        with ui.dialog() as reset_dialog, ui.card().classes("bg-slate-900 text-white p-4 w-96"):
            ui.label("Reset demo data?").classes("text-lg font-semibold")
            ui.label(
                "Wipes 22 collections (seed fixtures + runtime: live tx, "
                "agent metrics, semantic memory, LangGraph checkpoints, "
                "chat history, LLM caches), then re-runs ensure_all_indexes."
            ).classes("text-xs opacity-80 mt-1")
            keep_hist_cb = ui.checkbox(
                "Keep transaction history (tx + tx_geo + agent_metrics)", value=False,
            ).classes("mt-3")
            no_seed_cb = ui.checkbox(
                "Wipe only — do not reload fixture data", value=False,
            ).classes("mt-1")
            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("Cancel", on_click=reset_dialog.close) \
                    .props("flat").classes("text-slate-300")

                async def _confirm_reset() -> None:
                    keep = bool(keep_hist_cb.value)
                    seed_it = not bool(no_seed_cb.value)
                    reset_dialog.close()
                    await do_reset(keep_history=keep, do_seed=seed_it)
                    await _refresh_counts()

                ui.button("Reset", on_click=_confirm_reset).classes("bg-rose-600")

        reset_btn = ui.button("🔄 Reset demo", on_click=reset_dialog.open) \
            .classes("w-full mt-2 bg-slate-700")
        reset_btn.set_enabled(False)

        def _gate_reset():
            reset_btn.set_enabled(_cluster_is_ready() and STATE["running_jobs"] == 0)

        ui.timer(1.5, _gate_reset, immediate=True)

    # ── main grid ──────────────────────────────────────────────────────────
    with ui.row().classes("w-full no-wrap gap-4 p-4 items-stretch"):
        # left
        with ui.column().classes("flex-1 min-w-0 gap-3"):
            with ui.row().classes("w-full items-center gap-2"):
                ui.label("📡 Live transaction feed").classes("text-lg font-semibold")
                ui.label("· click a row for the full execution path") \
                    .classes("text-xs opacity-60")
            tx_table = ui.table(columns=TX_COLUMNS, rows=[], row_key="tx_id") \
                .classes("w-full vq-tx-table").props("dense flat")

            def _on_tx_row_click(e) -> None:
                # Quasar emits [native_event, row_dict, row_index]; NiceGUI
                # passes that through as e.args. Be defensive about the shape.
                row: dict | None = None
                args = getattr(e, "args", None)
                if isinstance(args, list) and len(args) >= 2 and isinstance(args[1], dict):
                    row = args[1]
                elif isinstance(args, dict):
                    row = args.get("row") if "row" in args else args
                if not row:
                    return
                cid = row.get("case")
                tx_id = row.get("tx_id") or "?"
                if cid and cid != "—":
                    ui.run_javascript(
                        f"window.open('/case/{cid}', '_blank', 'noopener')"
                    )
                else:
                    ui.notify(
                        f"No case opened for {tx_id} — fraud score below "
                        f"escalation threshold (low-risk path short-circuits "
                        f"to memory_writer).",
                        type="info", timeout=5000,
                    )

            tx_table.on("row-click", _on_tx_row_click)

            ui.label("🧠 Agent activity timeline (latest run)").classes("text-lg font-semibold mt-2")
            timeline = ui.column().classes("w-full gap-1")

        # right
        with ui.column().classes("w-1/3 gap-3"):
            ui.label("🗂️ Open cases").classes("text-lg font-semibold")
            cases_box = ui.column().classes("w-full gap-2")

    # ── reactive renderers ────────────────────────────────────────────────
    def render_runs():
        tx_table.rows = _runs_table_rows()
        tx_table.update()
        timeline.clear()
        if not STATE["runs"]:
            with timeline:
                ui.label("Inject a scenario or enable Live stream to populate.").classes("opacity-60")
            return
        sel = STATE["runs"][0]
        with timeline:
            for step in sel["result"].get("trace", []):
                color = AGENT_COLOR.get(step.get("agent"), "#adb5bd")
                with ui.card().tight().classes("w-full p-3"):
                    ui.html(
                        f'<span style="background:{color};color:white;padding:2px 8px;'
                        f'border-radius:6px;font-size:.78rem">{step.get("agent","?")}</span> '
                        f'<span style="color:#999;font-size:.75rem">{step.get("ts","")}</span>'
                    )
                    ui.label(str(step.get("summary", "")) or json.dumps(jsonable(step), indent=2)) \
                        .classes("text-sm whitespace-pre-wrap")
            with ui.expansion("🔬 Raw final state").classes("w-full"):
                state_json = jsonable({k: v for k, v in sel["result"].items() if k != "messages"})
                ui.code(json.dumps(state_json, indent=2)).classes("w-full text-xs")

    # Status -> (emoji, tailwind text colour) for the case-list rows. Kept
    # in sync with src/vaultiq/ui/case_flow.py:_STATUS_STYLE.
    _CASE_ROW_STYLE = {
        "NEW":                 ("🆕", "text-slate-300"),
        "PENDING_CUSTOMER":    ("⏳", "text-yellow-300"),
        "UNDER_INVESTIGATION": ("🔎", "text-orange-400"),
        "ESCALATED_AML":       ("🚨", "text-red-400"),
        "RESOLVED_FRAUD":      ("⛔", "text-red-400"),
        "RESOLVED_LEGITIMATE": ("✅", "text-emerald-400"),
    }

    # Memoise the last rendered case-list signature so the 6s timer only
    # rebuilds the rows when something actually changed (no more flicker).
    _cases_state: dict[str, Any] = {"sig": None}

    async def render_cases():
        try:
            cases = await _run_in_pool(fetch_recent_cases, 10)
        except Exception as exc:
            cases_box.clear()
            _cases_state["sig"] = ("__error__", str(exc))
            with cases_box:
                ui.label(f"fetch error: {exc}").classes("text-red-400")
            return
        sig = tuple(
            (c.get("case_id"), c.get("status"), c.get("score"),
             str(c.get("updated_at")))
            for c in cases
        )
        if sig == _cases_state["sig"]:
            return  # nothing changed — leave the panel alone
        _cases_state["sig"] = sig
        cases_box.clear()
        if not cases:
            with cases_box:
                ui.label("No cases yet.").classes("opacity-60")
            return
        with cases_box:
            for c in cases:
                cid = c.get("case_id", "?")
                status = (c.get("status") or "NEW").upper()
                ico, color_cls = _CASE_ROW_STYLE.get(status, ("📁", "text-slate-300"))
                score = c.get("score")
                # Plain anchor with target=_blank so the detail opens in a
                # new tab and isn't disturbed by the dashboard's auto-refresh.
                href = f"/case/{cid}"
                ui.html(
                    f'<a href="{href}" target="_blank" rel="noopener" '
                    f'class="block w-full no-underline">'
                    f'  <div class="flex items-center gap-2 px-3 py-2 rounded-lg '
                    f'bg-slate-900 hover:bg-slate-800 border border-slate-800 '
                    f'transition-colors">'
                    f'    <span class="text-base">{ico}</span>'
                    f'    <span class="font-mono text-xs font-bold {color_cls}">'
                    f'{cid}</span>'
                    f'    <span class="text-[10px] opacity-70 {color_cls}">'
                    f'{status}</span>'
                    f'    <span class="ml-auto font-mono text-xs opacity-90">'
                    f'score {score if score is not None else "—"}</span>'
                    f'    <span class="text-xs opacity-60 ml-2">↗</span>'
                    f'  </div>'
                    f'</a>'
                ).classes("w-full")

    ui.timer(2.0, render_runs, immediate=True)
    ui.timer(6.0, render_cases, immediate=True)
    ui.timer(6.0, stream_tick)


def main() -> None:
    import os
    port = int(os.getenv("VAULTIQ_PORT", "8505"))
    host = os.getenv("VAULTIQ_HOST", "0.0.0.0")
    ui.run(host=host, port=port, title="VaultIQ", reload=False, show=False,
           dark=True, storage_secret="vaultiq-demo-secret-not-for-prod")


if __name__ in {"__main__", "__mp_main__"}:
    main()
