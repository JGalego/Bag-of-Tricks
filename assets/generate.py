#!/usr/bin/env python3
"""Reproducibly generate every logo in the bag of tricks.

One source of truth, no hand-editing of pixels. The trick list, names and
catchphrases are read from ``.claude-plugin/marketplace.json`` so everything
below is *independent of how many tricks are in the bag* — add a plugin (and an
entry to ``ICONS``) and the banners, wheel and network all grow to match.

Targets (positional, default ``all``):

  banners    one ``<trick>/logo.png`` per trick   (1000x240)
  wheel      ``assets/bag-of-tricks-wheel.png``    (1650x1650, hub + spokes)
  network    ``assets/bag-of-tricks-network.png``  (1650x1650, category clusters;
             --no-category-nodes for the original random graph)
  animation  ``assets/bag-of-tricks-network.gif``  (looping graph, nodes float)
  logo       ``assets/logo.png`` from logo.svg     (800x800)

Each asset is built as an SVG string, then rasterised. Two renderers are
supported and auto-detected (``--renderer``): cairosvg (pure-Python) or the
ImageMagick ``convert`` binary. The "random" edges in the network — and the
nodes' floating orbits in the animation — are drawn from a seeded RNG
(``--seed``), so the output is deterministic: random-looking but stable.

Usage:
    python assets/generate.py                 # everything, auto renderer
    python assets/generate.py wheel network   # just those two
    python assets/generate.py animation --frames 60 --fps 24 --gif-size 800
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
MARKETPLACE = os.path.join(ROOT, ".claude-plugin", "marketplace.json")
LOGO_SVG = os.path.join(ASSETS, "logo.svg")

INK = "#111111"
PAPER = "#ffffff"
GREY = "#8a8a8a"
EDGE = "#d8d8d8"

# dark "dev" theme for the interactive web page
WEB_BG = "#0d1117"
WEB_FG = "#e6edf3"

# repo coordinates baked into the page (install commands, download + repo links)
REPO_SLUG = "JGalego/Bag-of-Tricks"
REPO_REF = "main"

# Names whose wordmark is set in monospace rather than the bold sans default —
# preserves the typographic split in the hand-made originals.
MONO = {"snitch", "steno", "strawman", "interrobang"}

SANS = "'DejaVu Sans', 'Liberation Sans', 'Helvetica Neue', Arial, sans-serif"
MONOFONT = "'DejaVu Sans Mono', 'Liberation Mono', ui-monospace, Menlo, Consolas, monospace"
SERIF = "Georgia, 'DejaVu Serif', 'Times New Roman', serif"


# --------------------------------------------------------------------------- #
# Icons. Each entry is SVG markup drawn in a 0..100 box, centred on (50, 50).
# Badged icons paint their own black disc/square; bare glyphs are pure ink.
# --------------------------------------------------------------------------- #

_BADGE = f'<circle cx="50" cy="50" r="46" fill="{INK}"/>'

ICONS = {
    # --- badged (white glyph on a black disc) --- #
    "bluff": _BADGE
    + (
        '<path d="M50 24 C40 40 26 46 26 58 C26 67 33 72 40 70 C44 69 47 66 49 63 '
        "C48 70 45 76 40 80 L60 80 C55 76 52 70 51 63 C53 66 56 69 60 70 C67 72 74 67 "
        '74 58 C74 46 60 40 50 24 Z" fill="#fff"/>'
    ),
    "deadpan": (
        f'<rect x="8" y="8" width="84" height="84" rx="22" fill="{INK}"/>'
        '<rect x="29" y="38" width="12" height="12" rx="3" fill="#fff"/>'
        '<rect x="59" y="38" width="12" height="12" rx="3" fill="#fff"/>'
        '<rect x="30" y="64" width="40" height="7" rx="3" fill="#fff"/>'
    ),
    "frisk": _BADGE
    + (
        '<path d="M50 26 L72 34 L72 54 C72 68 62 76 50 82 C38 76 28 68 28 54 L28 34 Z" '
        'fill="#fff"/>'
        f'<circle cx="50" cy="50" r="7" fill="{INK}"/>'
        f'<path d="M47 50 L53 50 L55 69 L45 69 Z" fill="{INK}"/>'
    ),
    "salvage": _BADGE
    + (
        f'<text x="33" y="68" font-family="{MONOFONT}" font-size="58" font-weight="700" '
        'fill="#fff" text-anchor="middle">{</text>'
        f'<text x="67" y="68" font-family="{MONOFONT}" font-size="58" font-weight="700" '
        'fill="#fff" text-anchor="middle">}</text>'
    ),
    "tell": _BADGE
    + (
        '<ellipse cx="50" cy="50" rx="30" ry="18" fill="#fff"/>'
        f'<circle cx="50" cy="50" r="11" fill="{INK}"/>'
        '<circle cx="55" cy="45" r="3.5" fill="#fff"/>'
    ),
    "tollbooth": _BADGE
    + (
        f'<text x="50" y="73" font-family="{SANS}" font-size="64" font-weight="700" '
        'fill="#fff" text-anchor="middle">$</text>'
    ),
    "mole": _BADGE
    + (
        '<circle cx="44" cy="44" r="15" fill="none" stroke="#fff" stroke-width="7"/>'
        '<line x1="55" y1="55" x2="73" y2="73" stroke="#fff" stroke-width="9" '
        'stroke-linecap="round"/>'
    ),
    "launder": _BADGE
    + (
        '<path d="M50 24 C50 24 32 47 32 60 A18 18 0 1 0 68 60 C68 47 50 24 50 24 Z" '
        'fill="#fff"/>'
        f'<circle cx="50" cy="62" r="7" fill="{INK}"/>'
    ),
    "alibi": _BADGE
    + (
        '<path d="M30 52 L44 66 L72 33" fill="none" stroke="#fff" stroke-width="10" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    "fold": _BADGE
    + (
        '<path d="M33 31 H67 V58 L57 68 H33 Z" fill="#fff"/>'
        f'<path d="M67 58 H57 V68 Z" fill="{INK}" opacity="0.45"/>'
    ),
    "grill": _BADGE
    + (
        '<g stroke="#fff" stroke-width="5" stroke-linecap="round">'
        '<line x1="35" y1="29" x2="35" y2="71"/>'
        '<line x1="45" y1="29" x2="45" y2="71"/>'
        '<line x1="55" y1="29" x2="55" y2="71"/>'
        '<line x1="65" y1="29" x2="65" y2="71"/>'
        '<line x1="30" y1="42" x2="70" y2="42"/>'
        '<line x1="30" y1="58" x2="70" y2="58"/>'
        "</g>"
    ),
    "lineup": _BADGE
    + (
        '<g fill="#fff">'
        '<rect x="33" y="52" width="8" height="20"/>'
        '<rect x="44" y="40" width="8" height="32"/>'
        '<rect x="55" y="47" width="8" height="25"/>'
        '<rect x="65" y="34" width="6" height="38"/>'
        '<rect x="30" y="74" width="42" height="4"/>'
        "</g>"
    ),
    "mugshot": _BADGE
    + (
        '<rect x="32" y="30" width="36" height="42" fill="none" stroke="#fff" '
        'stroke-width="4"/>'
        '<circle cx="50" cy="47" r="8" fill="#fff"/>'
        '<path d="M37 70 C37 60 44 56 50 56 C56 56 63 60 63 70 Z" fill="#fff"/>'
    ),
    "squeeze": _BADGE
    + (
        # two jaws pressing inward on a compressed stack of text lines — a vice
        '<path d="M24 34 L24 66 L39 50 Z" fill="#fff"/>'
        '<path d="M76 34 L76 66 L61 50 Z" fill="#fff"/>'
        '<g stroke="#fff" stroke-width="4" stroke-linecap="round">'
        '<line x1="44" y1="42" x2="56" y2="42"/>'
        '<line x1="44" y1="50" x2="56" y2="50"/>'
        '<line x1="44" y1="58" x2="56" y2="58"/>'
        "</g>"
    ),
    "interrobang": _BADGE
    + (
        f'<text x="50" y="74" font-family="{SERIF}" font-size="74" fill="#fff" '
        'text-anchor="middle">&#8253;</text>'
    ),
    "steno": _BADGE
    + (
        '<path d="M34 26 L66 26 L50 80 Z" fill="#fff"/>'
        f'<circle cx="50" cy="44" r="4.5" fill="{INK}"/>'
        f'<line x1="50" y1="48" x2="50" y2="70" stroke="{INK}" stroke-width="3"/>'
    ),
    "strawman": _BADGE
    + (
        '<circle cx="50" cy="32" r="9" fill="#fff"/>'
        '<line x1="50" y1="40" x2="50" y2="78" stroke="#fff" stroke-width="7" '
        'stroke-linecap="round"/>'
        '<line x1="34" y1="53" x2="66" y2="53" stroke="#fff" stroke-width="7" '
        'stroke-linecap="round"/>'
    ),
    "snitch": _BADGE
    + (
        '<ellipse cx="50" cy="50" rx="32" ry="19" fill="none" stroke="#fff" '
        'stroke-width="6"/>'
        '<circle cx="50" cy="50" r="11" fill="#fff"/>'
    ),
    "combo": _BADGE
    + (
        # three stages chained by flow chevrons — a pipeline
        '<circle cx="28" cy="50" r="7" fill="#fff"/>'
        '<circle cx="72" cy="50" r="7" fill="#fff"/>'
        '<path d="M40 40 L50 50 L40 60" fill="none" stroke="#fff" stroke-width="6" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        '<path d="M52 40 L62 50 L52 60" fill="none" stroke="#fff" stroke-width="6" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
    ),
}


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #


def load_tricks():
    """[(name, catchphrase)] in marketplace order — the single source of truth."""
    return [(t["name"], t["catchphrase"]) for t in load_tricks_full()]


def load_tricks_full():
    """[{name, catchphrase, description}] — splits the marketplace "catchphrase.
    — long description." convention into its two halves."""
    plugins = json.load(open(MARKETPLACE, encoding="utf-8"))["plugins"]
    out = []
    for p in plugins:
        cap, _, desc = p["description"].partition(" — ")
        out.append({"name": p["name"], "catchphrase": cap.strip(), "description": desc.strip()})
    return out


def hat_inner(keep_wordmark=True):
    """The bag-of-tricks mark itself, lifted from logo.svg (sans the <svg> shell
    and white background) so the hat has exactly one definition. Designed in an
    800x800 box centred near (400, 400)."""
    raw = open(LOGO_SVG, encoding="utf-8").read()
    inner = raw[raw.index(">", raw.index("<svg")) + 1 : raw.rindex("</svg>")]
    # drop the full-bleed background rect; the canvas underneath is already white
    inner = inner.replace('<rect width="800" height="800" fill="#ffffff"/>', "", 1)
    if not keep_wordmark:
        start = inner.find("<!-- wordmark -->")
        if start != -1:
            inner = inner[:start]
    return inner


# --------------------------------------------------------------------------- #
# SVG builders
# --------------------------------------------------------------------------- #


def icon_g(name, cx, cy, size):
    """Place an icon centred on (cx, cy), scaled so it spans `size` px."""
    markup = ICONS[name]
    s = size / 100.0
    return (
        f'<g transform="translate({cx - size / 2:.2f},{cy - size / 2:.2f}) '
        f'scale({s:.4f})">{markup}</g>'
    )


def svg_doc(width, height, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect width="{width}" height="{height}" fill="{PAPER}"/>'
        f"{body}</svg>"
    )


def fit_size(text, mono, max_width, max_size, min_size=20):
    """Largest font size (<= max_size) whose estimated run fits max_width."""
    factor = 0.6 if mono else 0.5  # rough advance width per char, in em
    size = max_width / (max(len(text), 1) * factor)
    return int(max(min_size, min(max_size, size)))


def banner_svg(name, catchphrase):
    mono = name in MONO
    name_font = MONOFONT if mono else SANS
    text_x = 255
    margin = 28
    avail = 1000 - text_x - margin
    name_size = fit_size(name, mono, avail, 86 if mono else 96)
    cap_size = fit_size(catchphrase, mono, avail, 44)
    body = icon_g(name, cx=120, cy=120, size=190)
    body += (
        f'<text x="{text_x}" y="{132 if mono else 130}" font-family="{name_font}" '
        f'font-size="{name_size}" font-weight="{700 if mono else 800}" '
        f'fill="{INK}">{esc(name)}</text>'
    )
    body += (
        f'<text x="{text_x + 3}" y="190" font-family="{name_font}" font-size="{cap_size}" '
        f'font-style="italic" fill="{GREY}">{esc(catchphrase)}</text>'
    )
    return svg_doc(1000, 240, body)


def wheel_svg(tricks):
    W = 1650
    c = W / 2
    n = len(tricks)
    radius = 600
    icon_size = 150
    body = ""

    # spokes first, so icons sit on top
    for i, _ in enumerate(tricks):
        a = math.radians(-90 + i * 360 / n)
        x1, y1 = c + 215 * math.cos(a), c + 215 * math.sin(a)
        x2, y2 = c + (radius - 95) * math.cos(a), c + (radius - 95) * math.sin(a)
        body += (
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{EDGE}" stroke-width="3"/>'
        )

    # central mark (hat + sparkles + wordmark), lifted from logo.svg
    scale = 0.66
    tx, ty = c - 400 * scale, c - 400 * scale
    body += f'<g transform="translate({tx:.1f},{ty:.1f}) scale({scale})">{hat_inner()}</g>'

    # the ring of tricks
    for i, (name, _) in enumerate(tricks):
        a = math.radians(-90 + i * 360 / n)
        cx, cy = c + radius * math.cos(a), c + radius * math.sin(a)
        body += icon_g(name, cx, cy, icon_size)
        body += (
            f'<text x="{cx:.1f}" y="{cy + icon_size / 2 + 42:.1f}" '
            f'font-family="{MONOFONT}" font-size="34" font-weight="600" '
            f'fill="{INK}" text-anchor="middle">{name}</text>'
        )
    return svg_doc(W, W, body)


NET_W = 1650
NET_ICON = 132


def network_layout(tricks, seed):
    """Deterministic graph layout: relaxed (non-overlapping) node positions plus
    a random-but-seeded edge set. Shared by the still and the animation so both
    show the same graph. Returns (names, base_pos, drift_phase, edges, hub_links)."""
    c = NET_W / 2
    n = len(tricks)
    rng = random.Random(seed)

    # scatter nodes on a jittered ring so the graph reads organic, not clock-like
    base = 560
    pos = []
    for i in range(n):
        ang = math.radians(-90 + i * 360 / n + rng.uniform(-12, 12))
        r = base + rng.uniform(-70, 90)
        pos.append([c + r * math.cos(ang), c + r * math.sin(ang)])

    # relax: push apart any pair that overlaps, and keep nodes off the central
    # logo and inside the canvas. Deterministic, so the layout is reproducible.
    min_dist = NET_ICON + 58  # centre-to-centre clearance (halo + drift headroom)
    r_min, r_max = 370, 690  # clear of the hub logo / inside the frame
    for _ in range(400):
        for i in range(n):
            for j in range(i + 1, n):
                dx, dy = pos[j][0] - pos[i][0], pos[j][1] - pos[i][1]
                d = math.hypot(dx, dy) or 0.01
                if d < min_dist:
                    push = (min_dist - d) / 2
                    ux, uy = dx / d, dy / d
                    pos[i][0] -= ux * push
                    pos[i][1] -= uy * push
                    pos[j][0] += ux * push
                    pos[j][1] += uy * push
        for p in pos:
            dx, dy = p[0] - c, p[1] - c
            d = math.hypot(dx, dy) or 0.01
            clamped = max(r_min, min(r_max, d))
            if clamped != d:
                p[0] = c + dx / d * clamped
                p[1] = c + dy / d * clamped

    # per-node drift phases for the animation (unused by the still)
    phase = [(rng.uniform(0, 2 * math.pi), rng.uniform(0, 2 * math.pi)) for _ in range(n)]

    # random edges: every node gets 1-3 links to others, deduped & undirected
    seen, edges = set(), []
    for i in range(n):
        for _ in range(rng.randint(1, 3)):
            j = rng.randrange(n)
            if j == i:
                continue
            key = (min(i, j), max(i, j))
            if key not in seen:
                seen.add(key)
                edges.append(key)
    # a few faint links into the hub so the centre feels connected too
    hub_links = rng.sample(range(n), k=min(n, max(3, n // 3)))

    names = [t[0] for t in tricks]
    return names, [tuple(p) for p in pos], phase, edges, hub_links


def network_body(names, pos, edges, hub_links, rings=False):
    """Render the graph body for one set of node positions (still or one frame)."""
    c = NET_W / 2
    body = ""
    for i, j in edges:
        x1, y1 = pos[i]
        x2, y2 = pos[j]
        body += (
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{EDGE}" stroke-width="2.5"/>'
        )
    for i in hub_links:
        x, y = pos[i]
        body += (
            f'<line x1="{c}" y1="{c}" x2="{x:.1f}" y2="{y:.1f}" '
            f'stroke="{EDGE}" stroke-width="2" stroke-dasharray="6 8"/>'
        )

    # bigger, central bag-of-tricks logo on top of the web
    scale = 0.95
    tx, ty = c - 400 * scale, c - 400 * scale
    body += f'<g transform="translate({tx:.1f},{ty:.1f}) scale({scale})">{hat_inner()}</g>'

    pal, cat_of = (category_palette(), category_of()) if rings else (None, None)
    r = NET_ICON / 2 + 8
    for name, (x, y) in zip(names, pos):
        body += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{PAPER}"/>'
        body += icon_g(name, x, y, NET_ICON)
        if rings:  # category colour, no category node
            body += (
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="none" '
                f'stroke="{pal[cat_of[name]]}" stroke-width="4"/>'
            )
        body += (
            f'<text x="{x:.1f}" y="{y + NET_ICON / 2 + 38:.1f}" '
            f'font-family="{MONOFONT}" font-size="30" font-weight="600" '
            f'fill="{INK}" text-anchor="middle">{name}</text>'
        )
    return body


def network_svg(tricks, seed, rings=False):
    names, pos, _phase, edges, hub_links = network_layout(tricks, seed)
    return svg_doc(NET_W, NET_W, network_body(names, pos, edges, hub_links, rings))


def network_frames(tricks, seed, frames, amp=15.0, rings=False):
    """Yield one SVG per animation frame. Each node floats on a small looping
    orbit around its base position (sin/cos over a full turn → seamless loop)."""
    names, pos, phase, edges, hub_links = network_layout(tricks, seed)
    for f in range(frames):
        t = 2 * math.pi * f / frames
        moved = []
        for (x, y), (px, py) in zip(pos, phase):
            dx = amp * math.sin(t + px) + 0.4 * amp * math.sin(2 * t + py)
            dy = amp * math.cos(t + py) + 0.4 * amp * math.cos(2 * t + px)
            moved.append((x + dx, y + dy))
        yield svg_doc(NET_W, NET_W, network_body(names, moved, edges, hub_links, rings))


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --------------------------------------------------------------------------- #
# Category-cluster graph: each category is its own node and its tricks clump
# around it (a "force cluster"), with one colour per category. Drives the
# default network/animation graph (opt out with --no-category-nodes) and the page.
# --------------------------------------------------------------------------- #

# one colour per category, assigned in marketplace order (cycles if needed)
CAT_COLORS = ["#3b82f6", "#22a55a", "#e5534b", "#a371f7", "#d4a017", "#e36fb0", "#1f9aa8"]

# short blurb per category (marketplace categories are bare strings); a category
# without an entry falls back to a trick count
CAT_DESC = {
    "output": "shape and clean up what the model emits",
    "debugging": "see and fix what your agent is actually doing",
    "security": "probe prompts and context for attacks and leaks",
    "workflow": "change how the model decides and when it acts",
    "productivity": "everyday LLM dev chores, done faster",
}


def categories_in_order():
    plugins = json.load(open(MARKETPLACE, encoding="utf-8"))["plugins"]
    cats = []
    for p in plugins:
        c = p.get("category")
        if c and c not in cats:
            cats.append(c)
    return cats


def category_of():
    plugins = json.load(open(MARKETPLACE, encoding="utf-8"))["plugins"]
    return {p["name"]: p.get("category") for p in plugins}


def category_palette():
    return {c: CAT_COLORS[k % len(CAT_COLORS)] for k, c in enumerate(categories_in_order())}


def cluster_layout(names, seed, W, H):
    """Place category nodes around the frame and clump each category's tricks
    around it, then relax so nothing overlaps. Deterministic for a given seed.
    Returns (cpos {cat: [x, y]}, tpos {trick: [x, y]}, members, cats)."""
    rng = random.Random(seed * 13 + 5)
    cats = categories_in_order()
    cat_of = category_of()
    cx, cy = W / 2, H / 2
    k = len(cats)
    rx, ry = W * 0.33, H * 0.33
    cpos = {}
    for idx, c in enumerate(cats):
        a = -math.pi / 2 + 2 * math.pi * idx / k
        cpos[c] = [cx + rx * math.cos(a), cy + ry * math.sin(a)]
    members = {c: [n for n in names if cat_of[n] == c] for c in cats}

    # how far tricks must sit from their hub: clear the (text) pill + the icon
    t_min = {c: pill_half_w(c) + NET_ICON / 2 + 26 for c in cats}
    t_max = {c: t_min[c] + 78 + len(members[c]) * 20 for c in cats}

    tpos = {}
    for c in cats:
        mem = members[c]
        m = max(len(mem), 1)
        outward = math.atan2(cpos[c][1] - cy, cpos[c][0] - cx)  # point away from centre
        spread = math.pi * 1.15
        for i, n in enumerate(mem):
            frac = (i + 0.5) / m - 0.5  # -0.5 .. 0.5 across the fan
            a = outward + frac * spread + rng.uniform(-0.12, 0.12)
            r = (t_min[c] + t_max[c]) / 2 * (0.85 + 0.3 * rng.random())
            tpos[n] = [cpos[c][0] + r * math.cos(a), cpos[c][1] + r * math.sin(a)]

    min_tt = NET_ICON + 26  # trick-to-trick clearance
    keepout = 380  # central disc reserved for the (big) hat
    margin = 90
    keys = list(tpos)
    for _ in range(420):
        for ii in range(len(keys)):
            for jj in range(ii + 1, len(keys)):
                a, b = tpos[keys[ii]], tpos[keys[jj]]
                dx, dy = b[0] - a[0], b[1] - a[1]
                d = math.hypot(dx, dy) or 0.01
                if d < min_tt:
                    f = (min_tt - d) / 2
                    ux, uy = dx / d, dy / d
                    a[0] -= ux * f
                    a[1] -= uy * f
                    b[0] += ux * f
                    b[1] += uy * f
        for n in tpos:
            p, c = tpos[n], cat_of[n]
            ccx, ccy = cpos[c]
            dx, dy = p[0] - ccx, p[1] - ccy
            d = math.hypot(dx, dy) or 0.01
            if d < t_min[c]:
                p[0], p[1] = ccx + dx / d * t_min[c], ccy + dy / d * t_min[c]
            elif d > t_max[c]:
                p[0], p[1] = ccx + dx / d * t_max[c], ccy + dy / d * t_max[c]
            for c2 in cats:  # keep off other clusters' pills
                if c2 == c:
                    continue
                ox, oy = cpos[c2]
                ex, ey = p[0] - ox, p[1] - oy
                ed = math.hypot(ex, ey) or 0.01
                clear = pill_half_w(c2) + NET_ICON / 2 + 20
                if ed < clear:
                    p[0], p[1] = ox + ex / ed * clear, oy + ey / ed * clear
            gx, gy = p[0] - cx, p[1] - cy  # keep clear of the central hat
            gd = math.hypot(gx, gy) or 0.01
            if gd < keepout:
                p[0], p[1] = cx + gx / gd * keepout, cy + gy / gd * keepout
            p[0] = max(margin, min(W - margin, p[0]))
            p[1] = max(margin, min(H - margin, p[1]))
    return cpos, tpos, members, cats


PILL_FS = 36  # category pill font size (px in the 1650 box)


def pill_half_w(name):
    return (len(name) * PILL_FS * 0.6 + 44) / 2


def cluster_body(cpos, tpos, members, cats, rings=True):
    """Render the cluster graph (light theme, for the PNG/GIF). `tpos` may hold
    jittered positions for an animation frame. `rings` draws the per-category
    coloured ring on each trick (optional; see also --no-rings)."""
    pal = category_palette()
    c0 = NET_W / 2
    body = ""
    for c in cats:  # category → central hub links
        col, (ccx, ccy) = pal[c], cpos[c]
        body += (
            f'<line x1="{c0:.1f}" y1="{c0:.1f}" x2="{ccx:.1f}" y2="{ccy:.1f}" '
            f'stroke="{col}" stroke-width="6" opacity="0.55"/>'
        )
    for c in cats:  # coloured trick→category links
        col, (ccx, ccy) = pal[c], cpos[c]
        for n in members[c]:
            x, y = tpos[n]
            body += (
                f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{ccx:.1f}" y2="{ccy:.1f}" '
                f'stroke="{col}" stroke-width="3.5" opacity="0.4"/>'
            )
    # central bag-of-tricks logo (big), on top of the spokes
    hs = 0.85
    body += f'<g transform="translate({c0 - 400 * hs:.0f},{c0 - 400 * hs:.0f}) scale({hs})">{hat_inner()}</g>'
    for c in cats:  # trick icons (optionally ringed)
        col = pal[c]
        for n in members[c]:
            x, y = tpos[n]
            r = NET_ICON / 2 + 11
            body += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{PAPER}"/>'
            body += icon_g(n, x, y, NET_ICON)
            if rings:
                body += (
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="none" '
                    f'stroke="{col}" stroke-width="4"/>'
                )
            body += (
                f'<text x="{x:.1f}" y="{y + r + 30:.1f}" font-family="{MONOFONT}" '
                f'font-size="28" font-weight="600" fill="{INK}" text-anchor="middle">{n}</text>'
            )
    for c in cats:  # category pill hubs, on top
        x, y = cpos[c]
        col = pal[c]
        hw, hh = pill_half_w(c), 34
        body += (
            f'<rect x="{x - hw:.1f}" y="{y - hh:.1f}" width="{2 * hw:.1f}" height="{2 * hh}" '
            f'rx="{hh}" fill="{col}"/>'
            f'<text x="{x:.1f}" y="{y + PILL_FS * 0.34:.1f}" font-family="{MONOFONT}" '
            f'font-size="{PILL_FS}" font-weight="700" fill="{PAPER}" '
            f'text-anchor="middle">{c}</text>'
        )
    return body


def cluster_svg(tricks, seed, rings=True):
    names = [t[0] for t in tricks]
    cpos, tpos, members, cats = cluster_layout(names, seed, NET_W, NET_W)
    return svg_doc(NET_W, NET_W, cluster_body(cpos, tpos, members, cats, rings))


def cluster_frames(tricks, seed, frames, amp=14.0, rings=True):
    names = [t[0] for t in tricks]
    cpos, tpos, members, cats = cluster_layout(names, seed, NET_W, NET_W)
    rng = random.Random(seed * 3 + 9)
    phase = {n: (rng.uniform(0, 2 * math.pi), rng.uniform(0, 2 * math.pi)) for n in names}
    for f in range(frames):
        t = 2 * math.pi * f / frames
        moved = {}
        for n, (px, py) in phase.items():
            bx, by = tpos[n]
            moved[n] = (
                bx + amp * math.sin(t + px) + 0.4 * amp * math.sin(2 * t + py),
                by + amp * math.cos(t + py) + 0.4 * amp * math.cos(2 * t + px),
            )
        yield svg_doc(NET_W, NET_W, cluster_body(cpos, moved, members, cats, rings))


# --------------------------------------------------------------------------- #
# Interactive web page (dark "dev" theme). Self-contained HTML: the same icons
# (colour-inverted for dark) and the trick data baked in, animated with a tiny
# vanilla-JS force sim. Nodes drift freely; hovering one freezes the graph and
# shows a terminal-style card with the catchphrase + full description.
# --------------------------------------------------------------------------- #


def invert(markup):
    """Swap the black/white palette so an icon reads on a dark background:
    the disc becomes light, the glyph becomes the page background colour."""
    markup = markup.replace("#111111", "\0L").replace("#ffffff", "\0D")
    # bare 3-digit white, but only as a whole token — never the prefix of a
    # longer hex like #fffabc (\b after the final 'f' requires a non-hex delimiter).
    markup = re.sub(r"#fff\b", "\0D", markup)
    return markup.replace("\0L", WEB_FG).replace("\0D", WEB_BG)


WEB_PILL_FS = 18  # category pill font size on the page (px)


def web_pill_half(name):
    return (len(name) * WEB_PILL_FS * 0.6 + 36) / 2


def web_html(tricks, seed):
    """Self-contained dark page: the category-cluster graph (central bag-of-tricks
    → category pills → tricks), laid out client-side so it fills the viewport and
    re-flows on resize. Tricks jitter around fixed homes; hovering freezes the
    graph and shows a terminal-style card. One colour per category throughout."""
    names = [t[0] for t in tricks]
    full = {t["name"]: t for t in load_tricks_full()}
    cat_of = category_of()
    cats = categories_in_order()
    pal = category_palette()
    catidx = {c: k for k, c in enumerate(cats)}
    icon = 60

    nodes_svg = ""
    for idx, name in enumerate(names):
        col = pal[cat_of[name]]
        glyph = invert(ICONS[name])
        r = icon / 2 + 9
        nodes_svg += (
            f'<g class="node" id="node{idx}" transform="translate(0,0)">'
            f'<circle r="{r:.0f}" fill="{WEB_BG}"/>'
            f'<g transform="translate({-icon / 2},{-icon / 2}) scale({icon / 100:.3f})">{glyph}</g>'
            f'<circle class="ring" r="{r:.0f}" fill="none" stroke="{col}" stroke-width="3"/>'
            f'<circle class="hit" r="{r + 5:.0f}"/>'
            f'<text y="{r + 22:.0f}">{esc(name)}</text>'
            f"</g>"
        )
    tedges_svg = "".join(
        f'<line class="te" id="te{idx}" stroke="{pal[cat_of[n]]}"/>' for idx, n in enumerate(names)
    )
    cedges_svg = "".join(
        f'<line class="ce" id="ce{k}" stroke="{pal[c]}"/>' for k, c in enumerate(cats)
    )
    pills_svg = ""
    for k, c in enumerate(cats):
        hw = web_pill_half(c)
        pills_svg += (
            f'<g class="cat" id="cat{k}" transform="translate(0,0)">'
            f'<rect x="{-hw:.0f}" y="-24" width="{2 * hw:.0f}" height="48" rx="24" fill="{pal[c]}"/>'
            f'<text y="6">{esc(c)}</text>'
            f'<rect class="hit" x="{-hw:.0f}" y="-24" width="{2 * hw:.0f}" height="48" rx="24"/>'
            f"</g>"
        )
    hat = f'<g class="hat" id="hat">{invert(hat_inner())}</g>'

    tdata = [
        {
            "name": n,
            "cat": cat_of[n],
            "color": pal[cat_of[n]],
            "catchphrase": full[n]["catchphrase"],
            "description": full[n]["description"],
        }
        for n in names
    ]
    cdata = []
    for c in cats:
        mem = [n for n in names if cat_of[n] == c]
        blurb = CAT_DESC.get(c, f"{len(mem)} tricks")
        cdata.append({"name": c, "color": pal[c], "blurb": blurb, "members": mem})
    catof = [catidx[cat_of[n]] for n in names]

    return (
        WEB_TEMPLATE.replace("__BG__", WEB_BG)
        .replace("__FG__", WEB_FG)
        .replace("__HAT__", hat)
        .replace("__CEDGES_SVG__", cedges_svg)
        .replace("__TEDGES_SVG__", tedges_svg)
        .replace("__NODES_SVG__", nodes_svg)
        .replace("__PILLS_SVG__", pills_svg)
        .replace("__TRICKS__", json.dumps(tdata))
        .replace("__CATS__", json.dumps(cdata))
        .replace("__CATOF__", json.dumps(catof))
        .replace("__SEED__", str(seed))
        .replace("__REPO__", REPO_SLUG)
        .replace("__REF__", REPO_REF)
    )


WEB_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>bag of tricks — network</title>
<style>
  :root{
    --bg:__BG__; --fg:__FG__; --panel:#161b22; --line:#30363d;
    --muted:#8b949e; --accent:#58a6ff; --accent2:#3fb950;
    --mono:ui-monospace,'SF Mono',Menlo,Consolas,'DejaVu Sans Mono',monospace;
  }
  *{box-sizing:border-box}
  html,body{margin:0;height:100%;width:100%;overflow:hidden;
    background:var(--bg);color:var(--fg);font-family:var(--mono)}
  #wrap{position:fixed;top:0;left:0;width:100vw;height:100vh;overflow:hidden;
    display:flex;flex-direction:column}
  header{padding:12px 20px;border-bottom:1px solid var(--line);display:flex;
    gap:12px 18px;align-items:center;justify-content:space-between;flex-wrap:wrap}
  header .hl{display:flex;flex-direction:column;gap:2px;min-width:0}
  header .t{font-weight:700;letter-spacing:.5px}
  header .s{color:var(--muted);font-size:13px}
  header .hr{display:flex;align-items:center;gap:10px}
  .ghl{display:inline-flex;align-items:center;gap:7px;color:var(--fg);text-decoration:none;
    border:1px solid var(--line);border-radius:8px;padding:6px 11px;font-size:13px;background:#161b22}
  .ghl:hover{border-color:var(--muted)}
  .ghl .stars{color:var(--muted)}
  .ghl .stars:not(:empty)::before{content:"★ ";color:var(--accent2)}
  .inst{position:relative}
  .ibtn{font-family:var(--mono);font-size:13px;font-weight:700;color:var(--bg);
    background:var(--fg);border:0;border-radius:8px;padding:7px 12px;cursor:pointer}
  .ibtn .car{opacity:.7}
  .menu{position:absolute;right:0;top:calc(100% + 8px);width:300px;background:var(--panel);
    border:1px solid var(--line);border-radius:10px;padding:8px;z-index:20;display:none;
    box-shadow:0 14px 40px rgba(0,0,0,.6)}
  .menu.open{display:block}
  .menu .mh{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.6px;padding:6px 8px}
  .menu .cmd{display:block;width:100%;text-align:left;background:transparent;border:0;
    border-radius:7px;padding:8px;cursor:pointer;color:var(--fg)}
  .menu .cmd:hover{background:#1b2230}
  .menu .cmd b{display:block;font-size:13px;margin-bottom:2px}
  .menu .cmd code{display:block;color:var(--muted);font-size:11.5px;white-space:nowrap;
    overflow:hidden;text-overflow:ellipsis}
  .menu .cmd.copied b::after{content:" ✓ copied";color:var(--accent2)}
  @media (max-width:560px){header .s{display:none} .ghl span:not(.stars){display:none} .menu{width:270px}}
  #stage{flex:1;position:relative;overflow:hidden;min-width:0;min-height:0}
  .grid{position:absolute;inset:0;pointer-events:none;opacity:.22;
    background-image:radial-gradient(var(--line) 1px,transparent 1px);background-size:28px 28px}
  #net{width:100%;height:100%;display:block;touch-action:none}
  .ce{stroke-width:5;opacity:.5;pointer-events:none;transition:opacity .15s}
  .te{stroke-width:2.2;opacity:.36;pointer-events:none;transition:opacity .15s}
  .ce.lit,.te.lit{opacity:.95}
  .hat{pointer-events:none}
  .node{cursor:pointer}
  .node > text{fill:var(--muted);font-size:14px;font-weight:600;text-anchor:middle}
  .node .ring{transition:stroke-width .12s}
  .hit{fill:transparent}
  .node:hover > text,.node.active > text{fill:var(--fg)}
  .node:hover .ring,.node.active .ring{stroke-width:5}
  .cat{cursor:pointer}
  .cat text{fill:var(--bg);font-size:18px;font-weight:700;text-anchor:middle;pointer-events:none}
  .cat:hover,.cat.active{filter:brightness(1.15)}
  body.frozen .te,body.frozen .ce{opacity:.12}
  body.frozen .te.lit,body.frozen .ce.lit{opacity:.95}
  #panel{position:absolute;max-width:330px;background:var(--panel);
    border:1px solid var(--line);border-radius:10px;padding:0;opacity:0;
    transform:translateY(6px);transition:opacity .12s,transform .12s;
    pointer-events:none;box-shadow:0 12px 34px rgba(0,0,0,.55);overflow:hidden}
  #panel.show{opacity:1;transform:none}
  #panel .bar{display:flex;align-items:center;gap:7px;padding:9px 13px;
    border-bottom:1px solid var(--line);background:#1b2230}
  #panel .bar i{width:11px;height:11px;border-radius:50%;background:#3a4150;display:inline-block}
  #panel .bar i:nth-child(1){background:#ff5f56}
  #panel .bar i:nth-child(2){background:#ffbd2e}
  #panel .bar i:nth-child(3){background:#27c93f}
  #panel .bar .f{margin-left:6px;color:var(--muted);font-size:12px}
  #panel .body{padding:14px 16px}
  #panel .h{color:var(--accent);font-weight:700;margin-bottom:8px}
  #panel .h .p{color:var(--accent2)}
  #panel .cap{font-style:italic;color:var(--fg);margin:0 0 10px;line-height:1.4}
  #panel .desc{color:var(--muted);font-size:13px;line-height:1.55;margin:0}
</style>
</head>
<body>
<div id="wrap">
  <header>
    <div class="hl">
      <span class="t">bag of tricks</span>
      <span class="s">single-idea LLM hacks — hover a trick to inspect · click to download</span>
    </div>
    <div class="hr">
      <a class="ghl" href="https://github.com/__REPO__" target="_blank" rel="noopener">
        <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.6 7.6 0 012-.27c.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
        <span>__REPO__</span><span class="stars" id="stars"></span>
      </a>
      <div class="inst">
        <button class="ibtn" id="instbtn">&#9889; install <span class="car">&#9662;</span></button>
        <div class="menu" id="instmenu">
          <div class="mh">run the whole bag</div>
          <button class="cmd" data-cmd="curl -fsSL https://raw.githubusercontent.com/__REPO__/__REF__/install.sh | bash">
            <b>curl · every trick</b><code>curl -fsSL …/install.sh | bash</code></button>
          <button class="cmd" data-cmd="/plugin marketplace add __REPO__">
            <b>Claude Code plugin</b><code>/plugin marketplace add __REPO__</code></button>
          <button class="cmd" data-cmd="git clone https://github.com/__REPO__ &amp;&amp; cd Bag-of-Tricks &amp;&amp; just install">
            <b>clone &amp; just install</b><code>git clone … &amp;&amp; just install</code></button>
        </div>
      </div>
    </div>
  </header>
  <div id="stage">
    <div class="grid"></div>
    <svg id="net" preserveAspectRatio="xMidYMid meet">
      <g id="cedges">__CEDGES_SVG__</g>
      <g id="tedges">__TEDGES_SVG__</g>
      __HAT__
      <g id="nodes">__NODES_SVG__</g>
      <g id="cats">__PILLS_SVG__</g>
    </svg>
    <div id="panel">
      <div class="bar"><i></i><i></i><i></i><span class="f" id="pfile"></span></div>
      <div class="body">
        <div class="h"><span class="p">&#10095;</span> <span id="pname"></span></div>
        <p class="cap" id="pcap"></p>
        <p class="desc" id="pdesc"></p>
      </div>
    </div>
  </div>
</div>
<script>
const T = __TRICKS__, CATS = __CATS__, CATOF = __CATOF__, SEED = __SEED__;
const REPO = "__REPO__", REF = "__REF__";
const NODES = [...document.querySelectorAll('.node')];
const PILLS = CATS.map((_, k) => document.getElementById('cat' + k));
const teEls = T.map((_, i) => document.getElementById('te' + i));
const ceEls = CATS.map((_, k) => document.getElementById('ce' + k));
const hat = document.getElementById('hat');
const svg = document.getElementById('net'), stage = document.getElementById('stage');
const panel = document.getElementById('panel');
const ICON = 60, PILLFS = 18, HAT_SC = .85, D = 1100;              // design units
const WANDER = .03, SPRING = .012, DAMP = .9, MAXV = .32, ROAM = 15;  // gentle jiggle
let paused = false, active = null, cpos = [], st = [];
const rnd = () => Math.random();
const pillHalf = (name) => (name.length * PILLFS * 0.6 + 36) / 2;

// Category-cluster layout, computed once in a fixed DxD design space (mirrors
// the Python generator): category hubs ring the centre, each category's tricks
// fan outward, relaxed so nothing overlaps and all clear the central hat. The
// SVG viewBox is then fitted to the result, so it scales to any window / phone.
function layout() {
  const cx = D / 2, cy = D / 2, K = CATS.length;
  const rx = D * 0.30, ry = D * 0.33;
  const cp = CATS.map((_, k) => { const a = -Math.PI / 2 + 2 * Math.PI * k / K;
    return [cx + rx * Math.cos(a), cy + ry * Math.sin(a)]; });
  const mem = CATS.map(() => []); CATOF.forEach((ci, i) => mem[ci].push(i));
  const tmin = CATS.map((c) => pillHalf(c.name) + ICON / 2 + 22);
  const tmax = CATS.map((c, k) => tmin[k] + 64 + mem[k].length * 16);
  let s = SEED * 13 + 5; const r = () => (s = (s * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;
  const tp = new Array(T.length);
  CATS.forEach((c, k) => {
    const m = Math.max(mem[k].length, 1), out = Math.atan2(cp[k][1] - cy, cp[k][0] - cx);
    mem[k].forEach((ti, i) => {
      const a = out + ((i + 0.5) / m - 0.5) * Math.PI * 1.15 + (r() - .5) * 0.24;
      const rr = (tmin[k] + tmax[k]) / 2 * (0.85 + 0.3 * r());
      tp[ti] = [cp[k][0] + rr * Math.cos(a), cp[k][1] + rr * Math.sin(a)];
    });
  });
  const MINTT = ICON + 22, MARG = 50, KEEP = 330;
  for (let it = 0; it < 420; it++) {
    for (let i = 0; i < tp.length; i++) for (let j = i + 1; j < tp.length; j++) {
      let a = tp[i], b = tp[j], dx = b[0] - a[0], dy = b[1] - a[1], d = Math.hypot(dx, dy) || .01;
      if (d < MINTT) { const f = (MINTT - d) / 2; dx /= d; dy /= d;
        a[0] -= dx * f; a[1] -= dy * f; b[0] += dx * f; b[1] += dy * f; }
    }
    for (let i = 0; i < tp.length; i++) {
      const ci = CATOF[i], p = tp[i], ccx = cp[ci][0], ccy = cp[ci][1];
      let dx = p[0] - ccx, dy = p[1] - ccy, d = Math.hypot(dx, dy) || .01;
      if (d < tmin[ci]) { p[0] = ccx + dx / d * tmin[ci]; p[1] = ccy + dy / d * tmin[ci]; }
      else if (d > tmax[ci]) { p[0] = ccx + dx / d * tmax[ci]; p[1] = ccy + dy / d * tmax[ci]; }
      for (let k = 0; k < K; k++) { if (k === ci) continue;
        let ex = p[0] - cp[k][0], ey = p[1] - cp[k][1], ed = Math.hypot(ex, ey) || .01;
        const cl = pillHalf(CATS[k].name) + ICON / 2 + 16;
        if (ed < cl) { p[0] = cp[k][0] + ex / ed * cl; p[1] = cp[k][1] + ey / ed * cl; } }
      let gx = p[0] - cx, gy = p[1] - cy, gd = Math.hypot(gx, gy) || .01;
      if (gd < KEEP) { p[0] = cx + gx / gd * KEEP; p[1] = cy + gy / gd * KEEP; }
      p[0] = Math.max(MARG, Math.min(D - MARG, p[0])); p[1] = Math.max(MARG, Math.min(D - MARG, p[1]));
    }
  }
  return {cp, tp};
}

function fitViewBox() {
  let a = 1e9, b = 1e9, c = -1e9, e = -1e9;
  const inc = (x, y) => { a = Math.min(a, x); b = Math.min(b, y); c = Math.max(c, x); e = Math.max(e, y); };
  st.forEach((p, i) => {                                           // node + its centred label
    const r = ICON / 2 + 12, lab = Math.max(r, T[i].name.length * 14 * 0.6 / 2);
    inc(p.hx - lab, p.hy - r); inc(p.hx + lab, p.hy + r + 26);
  });
  CATS.forEach((cc, k) => { const hw = pillHalf(cc.name); inc(cpos[k][0] - hw, cpos[k][1] - 24); inc(cpos[k][0] + hw, cpos[k][1] + 24); });
  const o = D / 2 - 400 * HAT_SC;                                   // hat art bounds (~185..710, 110..690)
  inc(o + 185 * HAT_SC, o + 110 * HAT_SC); inc(o + 710 * HAT_SC, o + 690 * HAT_SC);
  const pad = 26 + ROAM;
  svg.setAttribute('viewBox', `${(a - pad).toFixed(0)} ${(b - pad).toFixed(0)} ${(c - a + 2 * pad).toFixed(0)} ${(e - b + 2 * pad).toFixed(0)}`);
}

function render() {
  for (let i = 0; i < NODES.length; i++) {
    NODES[i].setAttribute('transform', `translate(${st[i].x.toFixed(2)},${st[i].y.toFixed(2)})`);
    const ci = CATOF[i], e = teEls[i];
    e.setAttribute('x1', st[i].x.toFixed(1)); e.setAttribute('y1', st[i].y.toFixed(1));
    e.setAttribute('x2', cpos[ci][0].toFixed(1)); e.setAttribute('y2', cpos[ci][1].toFixed(1));
  }
}

function step() {
  if (!paused) {
    for (const a of st) {
      a.vx += (rnd() - .5) * WANDER; a.vy += (rnd() - .5) * WANDER;   // random nudge
      a.vx += (a.hx - a.x) * SPRING; a.vy += (a.hy - a.y) * SPRING;   // pull home
      a.vx *= DAMP; a.vy *= DAMP;
      const sp = Math.hypot(a.vx, a.vy);
      if (sp > MAXV) { a.vx *= MAXV / sp; a.vy *= MAXV / sp; }
      a.x += a.vx; a.y += a.vy;
      const dx = a.x - a.hx, dy = a.y - a.hy, d = Math.hypot(dx, dy);
      if (d > ROAM) { a.x = a.hx + dx / d * ROAM; a.y = a.hy + dy / d * ROAM; }  // never far
    }
  }
  render();
  requestAnimationFrame(step);
}

// build once (layout is fixed; the viewBox makes it responsive)
const L = layout(); cpos = L.cp;
const C = D / 2;
hat.setAttribute('transform', `translate(${C - 400 * HAT_SC},${C - 400 * HAT_SC}) scale(${HAT_SC})`);
PILLS.forEach((g, k) => g.setAttribute('transform', `translate(${cpos[k][0].toFixed(1)},${cpos[k][1].toFixed(1)})`));
ceEls.forEach((e, k) => { e.setAttribute('x1', C); e.setAttribute('y1', C);
  e.setAttribute('x2', cpos[k][0].toFixed(1)); e.setAttribute('y2', cpos[k][1].toFixed(1)); });
st = L.tp.map(([hx, hy]) => ({x: hx, y: hy, hx, hy, vx: 0, vy: 0}));
fitViewBox();
requestAnimationFrame(step);

function clearActive() {
  teEls.forEach(e => e.classList.remove('lit'));
  ceEls.forEach(e => e.classList.remove('lit'));
  NODES.forEach(n => n.classList.remove('active'));
  PILLS.forEach(p => p.classList.remove('active'));
}
function placePanel(wx, wy) {
  const pt = new DOMPoint(wx, wy).matrixTransform(svg.getScreenCTM());
  const r = stage.getBoundingClientRect(), pw = panel.offsetWidth, ph = panel.offsetHeight;
  let px = pt.x - r.left + 34, py = pt.y - r.top - ph / 2;
  if (px + pw > r.width - 12) px = pt.x - r.left - 34 - pw;
  panel.style.left = Math.max(8, Math.min(px, r.width - pw - 8)) + 'px';
  panel.style.top = Math.max(8, Math.min(py, r.height - ph - 8)) + 'px';
}
function openPanel(color, file, name, cap, desc) {
  paused = true; document.body.classList.add('frozen');
  const h = document.getElementById('pname').parentElement;
  h.style.color = color;
  document.getElementById('pname').textContent = name;
  document.getElementById('pfile').textContent = file;
  document.getElementById('pcap').textContent = cap;
  document.getElementById('pdesc').textContent = desc;
  panel.style.borderColor = color;
  panel.classList.add('show');
}
function showTrick(i) {
  clearActive(); active = i;
  const t = T[i], ci = CATOF[i];
  NODES[i].classList.add('active'); teEls[i].classList.add('lit');
  ceEls[ci].classList.add('lit'); PILLS[ci].classList.add('active');
  openPanel(t.color, t.name + '/SKILL.md', t.name, t.catchphrase,
            t.description + '\n\ncategory: ' + t.cat);
  placePanel(st[i].x, st[i].y);
}
function showCat(k) {
  clearActive(); active = 'c' + k;
  const c = CATS[k];
  ceEls[k].classList.add('lit'); PILLS[k].classList.add('active');
  CATOF.forEach((ci, i) => { if (ci === k) { teEls[i].classList.add('lit'); NODES[i].classList.add('active'); } });
  openPanel(c.color, 'category · ' + c.members.length + ' tricks', c.name, c.blurb, c.members.join(' · '));
  placePanel(cpos[k][0], cpos[k][1]);
}
function hide() {
  paused = false; document.body.classList.remove('frozen');
  clearActive(); active = null; panel.classList.remove('show');
}
// click a trick to download just that trick as a .zip (via download-directory)
function download(name) {
  const url = 'https://github.com/' + REPO + '/tree/' + REF + '/' + name;
  window.open('https://download-directory.github.io/?url=' + encodeURIComponent(url), '_blank', 'noopener');
}
NODES.forEach((n, i) => {
  n.addEventListener('mouseenter', () => showTrick(i));
  n.addEventListener('mouseleave', hide);
  n.addEventListener('focus', () => showTrick(i));
  n.addEventListener('blur', hide);
  n.addEventListener('click', () => download(T[i].name));
  n.setAttribute('tabindex', '0');
});
PILLS.forEach((p, k) => {
  p.addEventListener('mouseenter', () => showCat(k));
  p.addEventListener('mouseleave', hide);
});

// install dropdown: toggle + copy-to-clipboard
const instbtn = document.getElementById('instbtn'), instmenu = document.getElementById('instmenu');
instbtn.addEventListener('click', (e) => { e.stopPropagation(); instmenu.classList.toggle('open'); });
document.addEventListener('click', () => instmenu.classList.remove('open'));
instmenu.addEventListener('click', (e) => e.stopPropagation());
document.querySelectorAll('.cmd').forEach(b => b.addEventListener('click', () => {
  navigator.clipboard && navigator.clipboard.writeText(b.dataset.cmd);
  b.classList.add('copied'); setTimeout(() => b.classList.remove('copied'), 1400);
}));

// live star count (best-effort; silently skipped offline)
fetch('https://api.github.com/repos/' + REPO).then(r => r.json()).then(d => {
  if (d && typeof d.stargazers_count === 'number') {
    const s = d.stargazers_count;
    document.getElementById('stars').textContent = s >= 1000 ? (s / 1000).toFixed(1) + 'k' : s;
  }
}).catch(() => {});
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def pick_renderer(choice):
    if choice == "cairosvg" or (choice == "auto" and _has_cairosvg()):
        return "cairosvg"
    if choice == "convert" or (choice == "auto" and shutil.which("convert")):
        return "convert"
    sys.exit(
        "no SVG renderer found. install cairosvg (pip install cairosvg) "
        "or ImageMagick (provides `convert`), or pass --renderer."
    )


def _has_cairosvg():
    try:
        import cairosvg  # noqa: F401

        return True
    except ImportError:
        return False


def render_bytes(svg, width, height, renderer):
    """Rasterise an SVG string to PNG bytes."""
    if renderer == "cairosvg":
        import cairosvg

        return cairosvg.svg2png(
            bytestring=svg.encode("utf-8"),
            output_width=width,
            output_height=height,
            background_color="white",
        )
    with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False) as f:
        f.write(svg)
        tmp = f.name
    try:
        return subprocess.run(
            [
                "convert",
                "-background",
                "white",
                "-density",
                "144",
                tmp,
                "-resize",
                f"{width}x{height}",
                "png:-",
            ],
            check=True,
            stdout=subprocess.PIPE,
        ).stdout
    except subprocess.CalledProcessError as e:
        # ImageMagick's SVG/Freetype path can't parse the quoted, comma-separated
        # CSS font-family these logos use and aborts with an opaque font error.
        raise SystemExit(
            "ImageMagick `convert` failed to rasterise the SVG (it does not parse "
            "the comma-separated CSS font-family used here). Install cairosvg "
            "instead — `pip install cairosvg` — which handles it."
        ) from e
    finally:
        os.unlink(tmp)


def render(svg, path, width, height, renderer):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(render_bytes(svg, width, height, renderer))
    print(f"  wrote {os.path.relpath(path, ROOT)}")


def render_gif(svgs, path, size, duration_ms, renderer):
    """Assemble a list of frame SVGs into a looping GIF via Pillow."""
    try:
        from PIL import Image
    except ImportError:
        sys.exit("the animation target needs Pillow (pip install Pillow).")
    import io

    frames = []
    for svg in svgs:
        png = render_bytes(svg, size, size, renderer)
        frames.append(Image.open(io.BytesIO(png)).convert("RGB"))
    if not frames:
        sys.exit("animation needs at least 1 frame (use --frames >= 1).")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        format="GIF",
        duration=duration_ms,
        loop=0,
        optimize=True,
        disposal=2,
    )
    print(f"  wrote {os.path.relpath(path, ROOT)} ({len(frames)} frames)")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "targets",
        nargs="*",
        choices=["all", "banners", "wheel", "network", "animation", "web", "logo"],
        help="what to build (default: all)",
    )
    ap.add_argument("--renderer", choices=["auto", "cairosvg", "convert"], default="auto")
    ap.add_argument(
        "--no-category-nodes",
        action="store_true",
        help="network/animation: drop the category clusters and fall back to the "
        "original randomly-connected graph",
    )
    ap.add_argument(
        "--no-rings",
        action="store_true",
        help="clusters graph: drop the per-category coloured ring on each trick",
    )
    ap.add_argument("--seed", type=int, default=42, help="RNG seed for layout")
    ap.add_argument("--frames", type=int, default=48, help="animation frame count")
    ap.add_argument("--gif-size", type=int, default=720, help="animation pixel size")
    ap.add_argument("--fps", type=int, default=20, help="animation frames per second")
    args = ap.parse_args(argv)

    targets = set(args.targets) or {"all"}
    if "all" in targets:
        targets = {"banners", "wheel", "network", "animation", "web", "logo"}
    tricks = load_tricks()
    # "web" is pure text; only reach for a rasteriser when a raster target is asked
    raster = targets & {"banners", "wheel", "network", "animation", "logo"}
    renderer = pick_renderer(args.renderer) if raster else None
    print(f"renderer: {renderer or 'n/a'}   tricks: {len(tricks)}")

    if "banners" in targets:
        print("banners:")
        for name, catchphrase in tricks:
            render(
                banner_svg(name, catchphrase),
                os.path.join(ROOT, name, "logo.png"),
                1000,
                240,
                renderer,
            )
    if "wheel" in targets:
        print("wheel:")
        render(
            wheel_svg(tricks), os.path.join(ASSETS, "bag-of-tricks-wheel.png"), 1650, 1650, renderer
        )
    # default: category clusters. --no-category-nodes reverts to the original
    # randomly-connected network graph.
    clusters, rings = not args.no_category_nodes, not args.no_rings
    graph = "clusters" if clusters else "random"
    if "network" in targets:
        print(f"network (graph={graph}, rings={rings}, seed={args.seed}):")
        svg = (
            cluster_svg(tricks, args.seed, rings)
            if clusters
            else network_svg(tricks, args.seed, rings)
        )
        render(svg, os.path.join(ASSETS, "bag-of-tricks-network.png"), 1650, 1650, renderer)
    if "animation" in targets:
        print(f"animation (graph={graph}, rings={rings}, seed={args.seed}, {args.frames} frames):")
        svgs = (
            cluster_frames(tricks, args.seed, args.frames, rings=rings)
            if clusters
            else network_frames(tricks, args.seed, args.frames, rings=rings)
        )
        render_gif(
            svgs,
            os.path.join(ASSETS, "bag-of-tricks-network.gif"),
            args.gif_size,
            max(1, round(1000 / args.fps)),
            renderer,
        )
    if "web" in targets:
        print(f"web (seed={args.seed}):")
        out = os.path.join(ROOT, "index.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write(web_html(tricks, args.seed))
        print(f"  wrote {os.path.relpath(out, ROOT)}")
    if "logo" in targets:
        print("logo:")
        render(
            open(LOGO_SVG, encoding="utf-8").read(),
            os.path.join(ASSETS, "logo.png"),
            800,
            800,
            renderer,
        )


if __name__ == "__main__":
    main()
