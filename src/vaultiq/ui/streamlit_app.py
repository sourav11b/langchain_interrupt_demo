"""VaultIQ — live operations dashboard.

Run with:  streamlit run src/vaultiq/ui/streamlit_app.py
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from src.vaultiq.logging_setup import configure_logging
from src.vaultiq.scenarios.injector import (
    SCENARIOS,
    build_scenario_transaction,
)
from src.vaultiq.ui.stream_runner import (
    execute_through_agents,
    fetch_collection_counts,
    fetch_recent_case_events,
    fetch_recent_cases,
    fetch_recent_transactions,
    generate_baseline_transaction,
)

configure_logging()

st.set_page_config(
    page_title="VaultIQ — Live Fraud Operations",
    page_icon="🛡️",
    layout="wide",
)


# ── session state ────────────────────────────────────────────────────────────
def _init_state() -> None:
    ss = st.session_state
    ss.setdefault("auto_run", False)
    ss.setdefault("last_runs", [])           # list of result dicts
    ss.setdefault("inject_queue", [])        # list of pending injected scenarios
    ss.setdefault("tick", 0)


_init_state()


# ── header ───────────────────────────────────────────────────────────────────
st.markdown(
    """
    <div style='display:flex;align-items:center;gap:12px;'>
        <h1 style='margin:0'>🛡️ VaultIQ</h1>
        <span style='color:#888;font-size:0.95rem'>NextGen AI Financial Intelligence — MongoDB Atlas · LangGraph · LangSmith</span>
    </div>
    """,
    unsafe_allow_html=True,
)


# ── sidebar controls ─────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Controls")
    st.session_state["auto_run"] = st.toggle(
        "▶ Live stream (1 tx / refresh)", value=st.session_state["auto_run"]
    )
    refresh_secs = st.slider("Refresh interval (s)", 2, 15, 4)

    st.markdown("---")
    st.subheader("💉 Inject fraud scenario")
    chosen = st.selectbox(
        "Scenario",
        options=[s.id for s in SCENARIOS],
        format_func=lambda i: next(f"{s.label} (hint {s.risk_hint})" for s in SCENARIOS if s.id == i),
    )
    target_random = st.checkbox("Random target customer", value=True)
    target_id = None
    if not target_random:
        target_id = st.text_input("customer_id", value="CUST000001")
    if st.button("🚀 Inject + run agents", use_container_width=True):
        cust = None if target_random else {"customer_id": target_id, "country": "US"}
        try:
            tx = build_scenario_transaction(chosen, customer=cust)
            with st.spinner(f"Running 3-agent flow on {tx['tx_id']}…"):
                result = execute_through_agents(tx)
            st.session_state["last_runs"].insert(0, {"tx": tx, "result": result})
            st.session_state["last_runs"] = st.session_state["last_runs"][:25]
            st.success(f"Injected {tx['tx_id']}")
        except Exception as exc:
            st.error(f"Injection failed: {exc}")

    st.markdown("---")
    st.caption("MongoDB collections")
    counts = fetch_collection_counts()
    for k, v in counts.items():
        st.caption(f"`{k}` → **{v:,}**")


# ── auto-refresh tick ────────────────────────────────────────────────────────
if st.session_state["auto_run"]:
    st_autorefresh(interval=refresh_secs * 1000, key="vaultiq_tick")
    try:
        tx = generate_baseline_transaction()
        result = execute_through_agents(tx)
        st.session_state["last_runs"].insert(0, {"tx": tx, "result": result})
        st.session_state["last_runs"] = st.session_state["last_runs"][:25]
    except Exception as exc:
        st.warning(f"Stream tick failed: {exc}")


# ── KPI strip ────────────────────────────────────────────────────────────────
runs = st.session_state["last_runs"]
k1, k2, k3, k4 = st.columns(4)
k1.metric("Recent runs (session)", len(runs))
high = sum(1 for r in runs if (r["result"].get("fraud") or {}).get("score", 0) >= 0.65)
k2.metric("High/critical scores", high)
cases_open = sum(1 for r in runs if (r["result"].get("case") or {}).get("case_id"))
k3.metric("Cases opened", cases_open)
k4.metric("Last tick", datetime.now(tz=timezone.utc).strftime("%H:%M:%S UTC"))


# ── main panes ───────────────────────────────────────────────────────────────
left, right = st.columns([3, 2])

with left:
    st.subheader("📡 Live transaction feed")
    rows = []
    for r in runs[:20]:
        tx, res = r["tx"], r["result"]
        f = res.get("fraud") or {}
        c = res.get("case") or {}
        rows.append({
            "ts": tx["ts"].strftime("%H:%M:%S") if hasattr(tx["ts"], "strftime") else str(tx["ts"]),
            "tx_id": tx["tx_id"],
            "scenario": tx.get("scenario_label", "—"),
            "customer": tx["customer_id"],
            "amount": tx["amount"],
            "country": tx.get("country"),
            "score": f.get("score"),
            "band": f.get("band"),
            "case": c.get("case_id"),
            "case_status": c.get("status"),
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=420)
    else:
        st.info("No runs yet — toggle live stream or inject a scenario from the sidebar.")

    st.subheader("🧠 Agent activity timeline")
    if runs:
        sel_idx = st.selectbox(
            "Inspect run",
            options=list(range(len(runs[:20]))),
            format_func=lambda i: f"{runs[i]['tx']['tx_id']}  ·  {runs[i]['tx'].get('scenario_label')}",
            key="run_sel",
        )
        sel = runs[sel_idx]
        for step in sel["result"].get("trace", []):
            agent = step.get("agent", "?")
            color = {
                "fraud_sentinel": "#ff6b6b",
                "customer_trust": "#ffa94d",
                "case_resolution": "#4dabf7",
                "memory_writer": "#82c91e",
            }.get(agent, "#adb5bd")
            with st.container(border=True):
                st.markdown(
                    f"<span style='background:{color};color:white;"
                    f"padding:2px 8px;border-radius:6px;font-size:0.78rem'>{agent}</span> "
                    f"<span style='color:#666;font-size:0.78rem'>{step.get('ts','')}</span>",
                    unsafe_allow_html=True,
                )
                st.write(step.get("summary") or step)
        with st.expander("🔬 Raw final state"):
            st.json({k: v for k, v in sel["result"].items() if k != "messages"})


with right:
    st.subheader("🗂️ Open cases")
    cases = fetch_recent_cases(limit=15)
    if cases:
        case_df = pd.DataFrame([
            {
                "case_id": c["case_id"],
                "status": c["status"],
                "score": c.get("score"),
                "customer": c["customer_id"],
                "tx": c.get("tx_id"),
                "updated": c["updated_at"].strftime("%H:%M:%S")
                if hasattr(c.get("updated_at"), "strftime") else str(c.get("updated_at")),
            } for c in cases
        ])
        st.dataframe(case_df, use_container_width=True, hide_index=True, height=260)
        sel_case = st.selectbox("Case events", options=[c["case_id"] for c in cases])
        evts = fetch_recent_case_events(sel_case, limit=20)
        for e in evts:
            with st.container(border=True):
                st.caption(f"{e['ts']} · {e['type']}")
                st.json(e.get("payload", {}))
    else:
        st.info("No cases yet.")

    st.subheader("📊 Score distribution (recent)")
    if runs:
        scores = [
            (r["result"].get("fraud") or {}).get("score") or 0
            for r in runs
        ]
        bands = pd.Series(pd.cut(
            scores,
            bins=[-0.01, 0.4, 0.65, 0.9, 1.01],
            labels=["low", "medium", "high", "critical"],
        )).value_counts().reindex(["low", "medium", "high", "critical"], fill_value=0)
        st.bar_chart(bands)
    else:
        st.caption("Run something to see the distribution.")
