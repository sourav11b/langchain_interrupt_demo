"""Animated SVG diagram of the VaultIQ data + agent flow path.

Returns a self-contained SVG string consumed by `ui.html(...)` in the
NiceGUI dashboard. The diagram shows the five logical stages

    Transaction → Fraud Sentinel → Customer Trust → Case Resolution → Memory

connected to a single MongoDB Atlas PolyStorage node below them, with
SMIL `animateMotion` packets perpetually flowing along every edge so the
diagram visibly conveys "the system is live" even when no run is in flight.
"""
from __future__ import annotations

# (label, accent colour, glyph, top-left x)
_NODES: list[tuple[str, str, str, int]] = [
    ("Transaction",     "#94a3b8", "📦", 30),
    ("Fraud Sentinel",  "#ff6b6b", "🛡", 240),
    ("Customer Trust",  "#ffa94d", "🪪", 450),
    ("Case Resolution", "#4dabf7", "📁", 660),
    ("Memory Writer",   "#82c91e", "🧠", 870),
]

_W, _H = 180, 70                       # node box
_NODE_Y = 40                           # top of stage row
_MONGO_W, _MONGO_H = 320, 60           # MongoDB box
_MONGO_X = 380
_MONGO_Y = 220
_VIEW_W, _VIEW_H = 1080, 320


def _node(g: tuple[str, str, str, int]) -> str:
    label, color, glyph, x = g
    cx = x + _W // 2
    return (
        f'<g transform="translate({x} {_NODE_Y})">'
        f'  <rect width="{_W}" height="{_H}" rx="12" fill="#0f172a" '
        f'stroke="{color}" stroke-width="2" filter="url(#glow)"/>'
        f'  <text x="{_W // 2}" y="30" text-anchor="middle" fill="{color}" '
        f'font-size="18" font-family="ui-sans-serif,system-ui">{glyph}</text>'
        f'  <text x="{_W // 2}" y="54" text-anchor="middle" fill="#e2e8f0" '
        f'font-size="12" font-weight="600" font-family="ui-sans-serif,system-ui">'
        f'{label}</text>'
        f'</g>'
    )
    _ = cx  # unused but kept for potential future per-node anchors


def flow_svg() -> str:
    parts: list[str] = []
    parts.append(
        f'<svg viewBox="0 0 {_VIEW_W} {_VIEW_H}" xmlns="http://www.w3.org/2000/svg" '
        f'preserveAspectRatio="xMidYMid meet" '
        f'style="width:100%;height:auto;display:block">'
    )

    # ── defs: glow filter + invisible motion paths ───────────────────────────
    parts.append(
        '<defs>'
        '<filter id="glow" x="-50%" y="-50%" width="200%" height="200%">'
        '<feGaussianBlur stdDeviation="3.5"/>'
        '<feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>'
        '</filter>'
        '<filter id="dot-glow" x="-100%" y="-100%" width="300%" height="300%">'
        '<feGaussianBlur stdDeviation="2.5"/>'
        '<feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>'
        '</filter>'
    )

    edge_y = _NODE_Y + _H // 2
    for i in range(len(_NODES) - 1):
        x1 = _NODES[i][3] + _W
        x2 = _NODES[i + 1][3]
        parts.append(f'<path id="edge{i}" d="M {x1} {edge_y} L {x2} {edge_y}"/>')

    for i, n in enumerate(_NODES[1:], start=1):  # skip the Transaction node
        nx = n[3] + _W // 2
        ny = _NODE_Y + _H
        parts.append(
            f'<path id="db{i}" d="M {nx} {ny} '
            f'C {nx} {(ny + _MONGO_Y) // 2}, '
            f'{_MONGO_X + _MONGO_W // 2} {(ny + _MONGO_Y) // 2}, '
            f'{_MONGO_X + _MONGO_W // 2} {_MONGO_Y}"/>'
        )
    parts.append('</defs>')

    # ── visible edges (dashed) ───────────────────────────────────────────────
    for i in range(len(_NODES) - 1):
        parts.append(
            f'<use href="#edge{i}" stroke="#475569" stroke-width="2" fill="none" '
            f'stroke-dasharray="4 6"/>'
        )
    for i in range(1, len(_NODES)):
        parts.append(
            f'<use href="#db{i}" stroke="#334155" stroke-width="1.4" fill="none" '
            f'stroke-dasharray="3 4" opacity="0.55"/>'
        )

    # ── stage nodes + MongoDB node ──────────────────────────────────────────
    for n in _NODES:
        parts.append(_node(n))

    parts.append(
        f'<g transform="translate({_MONGO_X} {_MONGO_Y})">'
        f'  <rect width="{_MONGO_W}" height="{_MONGO_H}" rx="14" '
        f'fill="#022c22" stroke="#10b981" stroke-width="2" filter="url(#glow)"/>'
        f'  <text x="{_MONGO_W // 2}" y="26" text-anchor="middle" fill="#10b981" '
        f'font-size="15" font-weight="700" font-family="ui-sans-serif,system-ui">'
        f'🍃 MongoDB Atlas — PolyStorage</text>'
        f'  <text x="{_MONGO_W // 2}" y="46" text-anchor="middle" fill="#94a3b8" '
        f'font-size="11" font-family="ui-sans-serif,system-ui">'
        f'vector · time-series · geo · graph · CRM · checkpoints</text>'
        f'</g>'
    )

    # ── animated packets along stage→stage edges ────────────────────────────
    for i in range(len(_NODES) - 1):
        color = _NODES[i + 1][1]
        for k in range(2):  # two staggered packets per edge
            parts.append(
                f'<circle r="5.5" fill="{color}" filter="url(#dot-glow)">'
                f'<animateMotion dur="1.8s" repeatCount="indefinite" '
                f'begin="{i * 0.25 + k * 0.9:.2f}s">'
                f'<mpath href="#edge{i}"/></animateMotion></circle>'
            )

    # ── animated packets diving down into MongoDB ───────────────────────────
    for i in range(1, len(_NODES)):
        color = _NODES[i][1]
        parts.append(
            f'<circle r="3.5" fill="{color}" opacity="0.85">'
            f'<animateMotion dur="2.6s" repeatCount="indefinite" '
            f'begin="{i * 0.35:.2f}s">'
            f'<mpath href="#db{i}"/></animateMotion></circle>'
        )

    parts.append('</svg>')
    return "".join(parts)
