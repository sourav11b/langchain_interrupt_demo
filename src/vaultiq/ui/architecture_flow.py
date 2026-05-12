"""Architecture animation page (`/architecture`).

Self-contained SVG + CSS + JS animation that walks a single transaction
through the LangGraph orchestrator, the three LangChain ReAct agents, the
LLM call (with semantic cache) and the MongoDB Atlas writes/reads. Same
animation grammar as `case_flow.py` (vq-step, vq-revealed, vq-active,
replay button, speed dropdown).
"""
from __future__ import annotations

from nicegui import ui


_CSS = r"""
.vq-arch-canvas {
  position: relative; width: 100%; max-width: 1200px; margin: 0 auto;
  aspect-ratio: 12 / 7; background: #0b1220;
  border: 1px solid #1f2937; border-radius: 14px; overflow: hidden;
  font-family: 'Inter','Segoe UI','Roboto',sans-serif; color: #e2e8f0;
}
.vq-arch-canvas svg.vq-arch-overlay {
  position: absolute; inset: 0; width: 100%; height: 100%;
  pointer-events: none;
}
.vq-arch-node {
  position: absolute; padding: 8px 12px; border-radius: 10px;
  background: #111827; border: 1px solid #374151; color: #cbd5e1;
  font-size: 0.78rem; line-height: 1.15; box-shadow: 0 2px 8px #00000044;
  opacity: 0; transform: translateY(14px) scale(0.96);
  transition: opacity .55s ease, transform .55s ease, box-shadow .35s ease,
              border-color .35s ease, background .35s ease;
}
.vq-arch-node.vq-revealed { opacity: 1; transform: translateY(0) scale(1); }
.vq-arch-node.vq-active   { box-shadow: 0 0 28px var(--vq-glow,#38bdf8aa);
                            border-color: var(--vq-glow,#38bdf8); }
.vq-arch-node .vq-arch-title { font-weight: 600; font-size: 0.82rem;
                               color: #f1f5f9; }
.vq-arch-node .vq-arch-sub   { color: #94a3b8; font-size: 0.7rem;
                               margin-top: 2px; }
.vq-arch-node .vq-arch-chips { display: flex; flex-wrap: wrap; gap: 3px;
                               margin-top: 5px; }
.vq-arch-node .vq-arch-chip {
  padding: 1px 6px; border-radius: 4px; background: #1e293b;
  color: #94a3b8; font-size: 0.62rem; font-family: ui-monospace,monospace;
}

/* node colour accents */
.vq-arch-node.vq-langgraph { --vq-glow: #38bdf8aa; border-color: #1e40af;
                             background: linear-gradient(180deg,#1e3a8a22,#111827); }
.vq-arch-node.vq-fraud     { --vq-glow: #fb7185aa; }
.vq-arch-node.vq-kyc       { --vq-glow: #fbbf24aa; }
.vq-arch-node.vq-case      { --vq-glow: #34d399aa; }
.vq-arch-node.vq-mongo     { --vq-glow: #00ED64aa;
                             background: linear-gradient(180deg,#022c1822,#111827); }
.vq-arch-node.vq-llm       { --vq-glow: #c084fcaa;
                             background: linear-gradient(180deg,#312e8133,#111827); }

/* the MongoDB Atlas container — drawn as a big rounded rect */
.vq-arch-mongo-container {
  position: absolute; left: 18px; right: 18px; bottom: 12px; height: 178px;
  border: 2px dashed #00ED6488; border-radius: 12px; padding: 22px 12px 10px;
  opacity: 0; transition: opacity .6s ease;
}
.vq-arch-mongo-container.vq-revealed { opacity: 1; }
.vq-arch-mongo-container::before {
  content: '🍃 MongoDB Atlas — Cluster0 (M30)';
  position: absolute; top: -11px; left: 14px; padding: 0 8px;
  background: #0b1220; color: #00ED64; font-size: 0.75rem; font-weight: 600;
}

/* arrows: dashed paths that 'flow' when active via stroke-dashoffset anim */
svg.vq-arch-overlay path.vq-arch-arrow {
  fill: none; stroke: #475569; stroke-width: 1.6;
  stroke-dasharray: 5 4; opacity: 0;
  transition: opacity .35s ease, stroke .35s ease;
}
svg.vq-arch-overlay path.vq-arch-arrow.vq-revealed { opacity: 0.55; }
svg.vq-arch-overlay path.vq-arch-arrow.vq-active   {
  opacity: 1;
  stroke: var(--vq-arrow,#38bdf8); stroke-width: 2.2;
  animation: vq-arch-flow 0.8s linear infinite;
}
@keyframes vq-arch-flow { to { stroke-dashoffset: -18; } }

/* legend / hint chips above the canvas */
.vq-arch-legend { display: flex; gap: 14px; flex-wrap: wrap;
                  font-size: 0.72rem; color: #94a3b8; margin: 8px 0; }
.vq-arch-legend span { display: inline-flex; align-items: center; gap: 6px; }
.vq-arch-legend i {
  width: 14px; height: 3px; border-radius: 2px; display: inline-block;
}

/* progress + indicator — same shape as case_flow */
.vq-arch-progress { height: 4px; background: #1f2937; border-radius: 2px;
                    overflow: hidden; margin: 6px 0; }
.vq-arch-progress > div { height: 100%; width: 0%;
                          background: linear-gradient(90deg,#38bdf8,#00ED64);
                          transition: width .55s ease-out; }

/* narration card */
.vq-arch-narr { background: #0f172a; border: 1px solid #1e293b;
                border-radius: 8px; padding: 10px 12px; min-height: 56px;
                color: #cbd5e1; font-size: 0.85rem; line-height: 1.45; }
.vq-arch-narr code { background: #1e293b; padding: 1px 5px;
                     border-radius: 3px; color: #38bdf8;
                     font-size: 0.78rem; }
"""


# Arrow SVG paths (defined in viewBox 1200x700 coords). Each path id matches
# the step that activates it. Curved bezier paths so the diagram doesn't look
# like a wiring closet.
_SVG = r"""
<svg class="vq-arch-overlay" viewBox="0 0 1200 700"
     preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="vq-arrowhead" viewBox="0 0 10 10" refX="9" refY="5"
            markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="#94a3b8"/>
    </marker>
    <marker id="vq-arrowhead-blue" viewBox="0 0 10 10" refX="9" refY="5"
            markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="#38bdf8"/>
    </marker>
    <marker id="vq-arrowhead-green" viewBox="0 0 10 10" refX="9" refY="5"
            markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="#00ED64"/>
    </marker>
  </defs>
  <!-- step 1: tx → langgraph START -->
  <path class="vq-arch-arrow" data-step="1" data-color="#38bdf8"
        d="M 130 90 L 200 90"
        marker-end="url(#vq-arrowhead-blue)"/>
  <!-- step 2: START → fraud_sentinel (lg pipeline) -->
  <path class="vq-arch-arrow" data-step="2" data-color="#38bdf8"
        d="M 290 90 L 360 90"
        marker-end="url(#vq-arrowhead-blue)"/>
  <!-- step 3: fraud_sentinel(lg) → fraud_sentinel agent (down) -->
  <path class="vq-arch-arrow" data-step="3" data-color="#fb7185"
        d="M 410 130 C 410 200, 280 200, 280 250"
        marker-end="url(#vq-arrowhead)"/>
  <!-- step 4: fraud agent → llm cloud (up) -->
  <path class="vq-arch-arrow" data-step="4" data-color="#c084fc"
        d="M 280 250 C 280 200, 600 200, 600 90"
        marker-end="url(#vq-arrowhead)"/>
  <!-- step 5: fraud agent → fraud_kb (down to mongo) -->
  <path class="vq-arch-arrow" data-step="5" data-color="#00ED64"
        d="M 280 380 L 280 480"
        marker-end="url(#vq-arrowhead-green)"/>
  <!-- step 6: fraud_sentinel lg → checkpoint write -->
  <path class="vq-arch-arrow" data-step="6" data-color="#00ED64"
        d="M 410 130 C 410 320, 720 320, 720 480"
        marker-end="url(#vq-arrowhead-green)"/>
  <!-- step 7: routing decision → customer_trust -->
  <path class="vq-arch-arrow" data-step="7" data-color="#38bdf8"
        d="M 470 90 L 530 90"
        marker-end="url(#vq-arrowhead-blue)"/>
  <!-- step 8: customer_trust(lg) → kyc agent down -->
  <path class="vq-arch-arrow" data-step="8" data-color="#fbbf24"
        d="M 580 130 C 580 200, 580 220, 580 250"
        marker-end="url(#vq-arrowhead)"/>
  <!-- step 9: routing → case_resolution -->
  <path class="vq-arch-arrow" data-step="9" data-color="#38bdf8"
        d="M 640 90 L 720 90"
        marker-end="url(#vq-arrowhead-blue)"/>
  <!-- step 10: case_resolution(lg) → case agent down -->
  <path class="vq-arch-arrow" data-step="10" data-color="#34d399"
        d="M 770 130 C 770 200, 880 200, 880 250"
        marker-end="url(#vq-arrowhead)"/>
  <!-- step 11: case agent → cases collection -->
  <path class="vq-arch-arrow" data-step="11" data-color="#00ED64"
        d="M 880 380 L 880 480"
        marker-end="url(#vq-arrowhead-green)"/>
  <!-- step 12: case_resolution → memory_writer (lg) -->
  <path class="vq-arch-arrow" data-step="12" data-color="#38bdf8"
        d="M 830 90 L 900 90"
        marker-end="url(#vq-arrowhead-blue)"/>
  <!-- step 13: memory_writer → agent_semantic_mem -->
  <path class="vq-arch-arrow" data-step="13" data-color="#00ED64"
        d="M 950 130 C 950 280, 1050 280, 1050 480"
        marker-end="url(#vq-arrowhead-green)"/>
  <!-- step 14: memory_writer(lg) → END → final state -->
  <path class="vq-arch-arrow" data-step="14" data-color="#38bdf8"
        d="M 1000 90 L 1100 90"
        marker-end="url(#vq-arrowhead-blue)"/>
</svg>
"""


# Each node is HTML positioned in % so it scales with the canvas.
# data-step= the step on which it is REVEALED (vq-revealed); the same
# class is also kept active on subsequent steps until a later step deactivates it.
_NODES_HTML = r"""
<!-- transaction event (entry, far left) -->
<div class="vq-arch-node" data-step="1" style="left:1%; top:9%; width:10%;">
  <div class="vq-arch-title">📥 Transaction</div>
  <div class="vq-arch-sub">tx_id · customer_id<br>amount · merchant_id · ts</div>
</div>

<!-- LangGraph orchestrator pipeline (top row) -->
<div class="vq-arch-node vq-langgraph" data-step="2"
     style="left:17%; top:9%; width:7.5%; text-align:center;">
  <div class="vq-arch-title">START</div></div>
<div class="vq-arch-node vq-langgraph" data-step="3"
     style="left:30%; top:7%; width:11%;">
  <div class="vq-arch-title">fraud_sentinel</div>
  <div class="vq-arch-sub">LangGraph node</div></div>
<div class="vq-arch-node vq-langgraph" data-step="6"
     style="left:39%; top:9%; width:6.5%; text-align:center;
            background:#1e293b; transform:rotate(45deg);">
  <div class="vq-arch-title" style="transform:rotate(-45deg); font-size:0.62rem;">
    score≥0.65?</div></div>
<div class="vq-arch-node vq-langgraph" data-step="7"
     style="left:44%; top:7%; width:11%;">
  <div class="vq-arch-title">customer_trust</div>
  <div class="vq-arch-sub">LangGraph node</div></div>
<div class="vq-arch-node vq-langgraph" data-step="9"
     style="left:60%; top:7%; width:11%;">
  <div class="vq-arch-title">case_resolution</div>
  <div class="vq-arch-sub">LangGraph node</div></div>
<div class="vq-arch-node vq-langgraph" data-step="12"
     style="left:75%; top:7%; width:11%;">
  <div class="vq-arch-title">memory_writer</div>
  <div class="vq-arch-sub">LangGraph node</div></div>
<div class="vq-arch-node vq-langgraph" data-step="14"
     style="left:91.5%; top:9%; width:7.5%; text-align:center;">
  <div class="vq-arch-title">END</div></div>

<!-- Generic LLM cloud (top center) -->
<div class="vq-arch-node vq-llm" data-step="4"
     style="left:48%; top:1%; width:14%; text-align:center;
            border-radius:30px; padding:10px 12px;">
  <div class="vq-arch-title">☁ LLM</div>
  <div class="vq-arch-sub">vendor-agnostic chat model<br>
    via langchain create_react_agent</div>
</div>

<!-- Three agent cards (middle row) -->
<div class="vq-arch-node vq-fraud" data-step="3"
     style="left:18%; top:36%; width:18%;">
  <div class="vq-arch-title">🛡 Fraud Sentinel</div>
  <div class="vq-arch-sub">LangChain ReAct agent</div>
  <div class="vq-arch-chips">
    <span class="vq-arch-chip">score_transaction</span>
    <span class="vq-arch-chip">geo_velocity</span>
    <span class="vq-arch-chip">customer_velocity</span>
    <span class="vq-arch-chip">device_graph</span>
    <span class="vq-arch-chip">fraud_kb_lookup</span>
  </div>
</div>
<div class="vq-arch-node vq-kyc" data-step="8"
     style="left:42%; top:36%; width:18%;">
  <div class="vq-arch-title">🪪 Customer Trust</div>
  <div class="vq-arch-sub">LangChain ReAct agent</div>
  <div class="vq-arch-chips">
    <span class="vq-arch-chip">verify_factors</span>
    <span class="vq-arch-chip">request_otp</span>
    <span class="vq-arch-chip">confirm_otp</span>
    <span class="vq-arch-chip">flag_step_up</span>
  </div>
</div>
<div class="vq-arch-node vq-case" data-step="10"
     style="left:66%; top:36%; width:18%;">
  <div class="vq-arch-title">📁 Case Resolution</div>
  <div class="vq-arch-sub">LangChain ReAct agent</div>
  <div class="vq-arch-chips">
    <span class="vq-arch-chip">list_open_cases</span>
    <span class="vq-arch-chip">open_case</span>
    <span class="vq-arch-chip">update_case</span>
    <span class="vq-arch-chip">add_case_note</span>
    <span class="vq-arch-chip">log_case_event</span>
  </div>
</div>

<!-- Final state (entry, far right) -->
<div class="vq-arch-node" data-step="14"
     style="left:91%; top:36%; width:8.5%;">
  <div class="vq-arch-title">✅ Final state</div>
  <div class="vq-arch-sub">fraud.score · case.status<br>case.case_id</div>
</div>

<!-- MongoDB Atlas container (bottom band) — drawn first so others overlay -->
<div class="vq-arch-mongo-container" data-step="5"></div>

<!-- Collections inside the Atlas container (4 groups, equal width) -->
<div class="vq-arch-node vq-mongo" data-step="5"
     style="left:3%; top:73%; width:21%;">
  <div class="vq-arch-title">📊 Operational + Knowledge</div>
  <div class="vq-arch-chips">
    <span class="vq-arch-chip">customers</span>
    <span class="vq-arch-chip">transactions</span>
    <span class="vq-arch-chip">fraud_kb</span>
    <span class="vq-arch-chip">vectorSearch + BM25</span>
  </div>
</div>
<div class="vq-arch-node vq-mongo" data-step="6"
     style="left:25%; top:73%; width:21%;">
  <div class="vq-arch-title">🕒 LangGraph state</div>
  <div class="vq-arch-chips">
    <span class="vq-arch-chip">lg_checkpoints</span>
    <span class="vq-arch-chip">lg_checkpoint_writes</span>
    <span class="vq-arch-chip">MongoDBSaver</span>
  </div>
</div>
<div class="vq-arch-node vq-mongo" data-step="11"
     style="left:47%; top:73%; width:21%;">
  <div class="vq-arch-title">📁 CRM</div>
  <div class="vq-arch-chips">
    <span class="vq-arch-chip">cases</span>
    <span class="vq-arch-chip">case_events</span>
    <span class="vq-arch-chip">case_notes</span>
  </div>
</div>
<div class="vq-arch-node vq-mongo" data-step="13"
     style="left:69%; top:73%; width:28%;">
  <div class="vq-arch-title">🧠 Memory + LLM cache</div>
  <div class="vq-arch-chips">
    <span class="vq-arch-chip">agent_semantic_mem</span>
    <span class="vq-arch-chip">llm_semantic_cache</span>
    <span class="vq-arch-chip">AutoEmbeddings (server-side)</span>
  </div>
</div>
"""


# Per-step narration (also drives the indicator label).
_STEPS = [
    ("📥 Transaction enters",
     "A payment event arrives — `tx_id`, `customer_id`, `amount`. "
     "The dashboard hands it to <code>execute_through_agents(tx)</code>."),
    ("⚙️ LangGraph START",
     "The transaction becomes the initial <code>VaultIQState</code>. "
     "MongoDBSaver writes checkpoint #0; the run is now resumable."),
    ("🛡 Fraud Sentinel runs",
     "<code>fraud_sentinel</code> node fires. The LangChain ReAct agent "
     "is built with 5 typed tools and the chat LLM."),
    ("☁ LLM call (with semantic cache)",
     "The agent invokes the LLM. Before each call, "
     "<code>MongoDBAtlasSemanticCache</code> does a vectorSearch lookup; "
     "a cache hit short-circuits the model entirely."),
    ("🔎 Tools read MongoDB",
     "The fraud agent calls its tools — <code>fraud_kb_lookup</code> hits "
     "the hybrid BM25+vector index on <code>fraud_kb</code>; "
     "<code>get_recent_transactions</code> reads the time-series collection."),
    ("💾 LangGraph checkpoint",
     "After the node returns, MongoDBSaver writes the new state slice to "
     "<code>lg_checkpoints</code> + <code>lg_checkpoint_writes</code>."),
    ("↗ Conditional routing — high risk",
     "Score ≥ 0.65 — the conditional edge routes to <code>customer_trust</code>. "
     "(Low-risk path skips straight to memory_writer.)"),
    ("🪪 Customer Trust verifies",
     "KYC ReAct agent runs identity factors + OTP + dispute claim, then "
     "returns <code>{verified, claims_transaction, summary}</code>."),
    ("➡ Onward to Case Resolution",
     "After KYC, the conditional edge always routes to "
     "<code>case_resolution</code> on the high-risk path."),
    ("📁 Case Resolution decides",
     "The case agent uses 5 dedicated CRM tools to choose a disposition: "
     "<code>open_case</code> / <code>update_case</code> / <code>add_case_note</code>."),
    ("✍ Cases written to MongoDB",
     "The CRM tools insert into <code>cases</code> + <code>case_events</code> "
     "and add a vector-indexed note to <code>case_notes</code>."),
    ("🧠 Memory writer",
     "The graph reaches <code>memory_writer</code> — the final node before END."),
    ("📚 Persist to semantic memory",
     "<code>memory_writer</code> calls <code>mem.remember(...)</code>. "
     "The text is sent raw to <code>agent_semantic_mem</code>; Atlas embeds "
     "it server-side via <code>AutoEmbeddings</code> — no client-side vectors."),
    ("✅ Final state returned",
     "Graph hits END. The dashboard receives "
     "<code>{fraud, kyc, case, trace}</code> and renders the live tx feed."),
]


_JS_TEMPLATE = r"""
(function () {
  var runId = 0;
  var STEPS = __NSTEPS__;

  function $(id)   { return document.getElementById(id); }
  function $$(sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); }

  function getSpeed() {
    var s = parseFloat(window.vqSpeed);
    if (!isFinite(s) || s <= 0) s = 1;
    return s;
  }
  function delay(ms) { return Math.max(60, Math.round(ms / getSpeed())); }

  try {
    var saved = parseFloat(localStorage.getItem('vqSpeed'));
    if (isFinite(saved) && saved > 0) window.vqSpeed = saved;
  } catch (_) {}

  function nodesAt(step)  { return $$('.vq-arch-canvas [data-step="' + step + '"]'); }
  function arrowAt(step)  { return $$('.vq-arch-overlay path[data-step="' + step + '"]'); }
  function allNodes()     { return $$('.vq-arch-canvas [data-step]'); }
  function allArrows()    { return $$('.vq-arch-overlay path[data-step]'); }

  function reset() {
    allNodes().forEach(function (n) { n.classList.remove('vq-revealed','vq-active'); });
    allArrows().forEach(function (a) {
      a.classList.remove('vq-revealed','vq-active');
      a.style.removeProperty('--vq-arrow');
    });
    var pb = $('vq-arch-pb'); if (pb) pb.style.width = '0%';
  }

  function play(narrations, names) {
    var my = ++runId;
    var canvas = document.querySelector('.vq-arch-canvas');
    if (!canvas) { console.log('[arch] no canvas'); return; }
    reset();
    var i = 1;
    function step() {
      if (my !== runId) return;
      if (i > STEPS) {
        var ind = $('vq-arch-ind');
        if (ind) ind.innerHTML = '<span style="color:#10b981">✅</span> flow complete';
        var rb = $('vq-arch-replay'); if (rb) rb.style.display = 'inline-flex';
        return;
      }
      // Deactivate previous arrow but keep it revealed.
      arrowAt(i - 1).forEach(function (a) { a.classList.remove('vq-active'); });
      // Reveal everything for this step.
      nodesAt(i).forEach(function (n) {
        n.classList.add('vq-revealed','vq-active');
        // dim previous step's active glow
        nodesAt(i - 1).forEach(function (p) { p.classList.remove('vq-active'); });
      });
      arrowAt(i).forEach(function (a) {
        a.classList.add('vq-revealed','vq-active');
        var c = a.getAttribute('data-color');
        if (c) a.style.setProperty('--vq-arrow', c);
      });
      var ind = $('vq-arch-ind');
      if (ind) ind.innerHTML =
        '<span style="color:#38bdf8">▶</span> step ' + i + ' of ' + STEPS +
        ' · <b>' + (names[i-1] || '') + '</b>';
      var nr = $('vq-arch-narr');
      if (nr && narrations[i-1] !== undefined) nr.innerHTML = narrations[i-1];
      var pb = $('vq-arch-pb'); if (pb) pb.style.width = ((i / STEPS) * 100) + '%';
      i += 1;
      setTimeout(step, delay(1700));
    }
    var rb = $('vq-arch-replay'); if (rb) rb.style.display = 'none';
    setTimeout(step, delay(300));
  }

  // Wire replay button + speed dropdown, poll for canvas (NiceGUI loads via WS).
  var tries = 0;
  var iv = setInterval(function () {
    tries += 1;
    var canvas = document.querySelector('.vq-arch-canvas');
    if (!canvas && tries < 80) return;
    clearInterval(iv);
    if (!canvas) { console.log('[arch] canvas never appeared'); return; }
    var narrs = JSON.parse(document.getElementById('vq-arch-narrs').textContent || '[]');
    var names = JSON.parse(document.getElementById('vq-arch-names').textContent || '[]');
    var rb = $('vq-arch-replay');
    if (rb) rb.addEventListener('click', function () { play(narrs, names); });
    var ss = $('vq-arch-speed');
    if (ss) {
      ss.addEventListener('change', function () {
        var v = parseFloat(ss.value); if (isFinite(v) && v > 0) {
          window.vqSpeed = v;
          try { localStorage.setItem('vqSpeed', String(v)); } catch (_) {}
        }
      });
      try { var sv = parseFloat(localStorage.getItem('vqSpeed'));
            if (isFinite(sv) && sv > 0) ss.value = String(sv); } catch (_) {}
    }
    play(narrs, names);
  }, 150);
})();
"""


@ui.page("/architecture")
def architecture_page() -> None:
    """Animated walk-through of the LangChain + LangGraph + MongoDB flow."""
    import json as _json
    ui.dark_mode().enable()
    ui.add_head_html(f"<style>{_CSS}</style>")

    with ui.column().classes("w-full p-4 gap-3"):
        with ui.row().classes("w-full items-center justify-between"):
            with ui.column().classes("gap-0"):
                ui.label("VaultIQ — End-to-end flow").classes(
                    "text-2xl font-semibold")
                ui.label("LangChain ReAct agents · LangGraph orchestration · "
                         "MongoDB Atlas persistence").classes(
                    "text-sm opacity-70")
            with ui.row().classes("items-center gap-3"):
                ui.html(
                    '<select id="vq-arch-speed" '
                    'style="background:#0f172a; color:#cbd5e1; '
                    'border:1px solid #334155; border-radius:6px; '
                    'padding:4px 8px; font-size:0.8rem;">'
                    '  <option value="0.5">0.5x</option>'
                    '  <option value="1" selected>1x</option>'
                    '  <option value="1.5">1.5x</option>'
                    '  <option value="2">2x</option>'
                    '  <option value="3">3x</option>'
                    '</select>'
                )
                ui.html(
                    '<button id="vq-arch-replay" '
                    'style="display:none; background:#1e40af; color:#f1f5f9; '
                    'border:none; border-radius:6px; padding:6px 14px; '
                    'font-size:0.8rem; cursor:pointer;">↻ Replay</button>'
                )
                ui.link("← back to dashboard", "/").classes("text-sm")

        ui.html('<div class="vq-arch-legend">'
                '<span><i style="background:#38bdf8"></i> LangGraph routing</span>'
                '<span><i style="background:#c084fc"></i> LLM call</span>'
                '<span><i style="background:#fb7185"></i> Fraud agent</span>'
                '<span><i style="background:#fbbf24"></i> KYC agent</span>'
                '<span><i style="background:#34d399"></i> Case agent</span>'
                '<span><i style="background:#00ED64"></i> MongoDB read/write</span>'
                '</div>')

        ui.html(
            '<div id="vq-arch-ind" class="text-sm" '
            'style="color:#94a3b8; min-height:1.4em;">step 0 — ready</div>'
            '<div class="vq-arch-progress"><div id="vq-arch-pb"></div></div>'
        )

        # Canvas with overlay arrows + positioned nodes.
        ui.html(
            f'<div class="vq-arch-canvas">{_SVG}{_NODES_HTML}</div>'
        )

        # Narration card below canvas.
        ui.html(
            '<div id="vq-arch-narr" class="vq-arch-narr">'
            'Press <b>Replay</b> to walk a transaction through the system.'
            '</div>'
        )

        # Hidden JSON payloads + orchestrator JS — NiceGUI blocks <script>
        # tags inside ui.html(), so they go through add_body_html() instead
        # (runs once at page load, well after the canvas markup is in DOM).
        names = _json.dumps([s[0] for s in _STEPS])
        narrs = _json.dumps([s[1] for s in _STEPS])
        ui.add_body_html(
            f'<script type="application/json" id="vq-arch-names">{names}</script>'
            f'<script type="application/json" id="vq-arch-narrs">{narrs}</script>'
            '<script>'
            + _JS_TEMPLATE.replace("__NSTEPS__", str(len(_STEPS)))
            + '</script>'
        )



