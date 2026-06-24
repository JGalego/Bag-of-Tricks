#!/usr/bin/env python3
"""Reproducibly generate every logo in the bag of tricks.

One source of truth, no hand-editing of pixels. The trick list, names and
catchphrases are read from ``.claude-plugin/marketplace.json`` so everything
below is *independent of how many tricks are in the bag* — add a plugin (and an
entry to ``ICONS``) and the banners, wheel and network all grow to match.

Targets (positional, default ``all``):

  banners    one ``<trick>/logo.png`` per trick   (1000x240)
  wheel      ``assets/bag-of-tricks-wheel.png``    (1650x1650, hub + spokes)
  network    ``assets/bag-of-tricks-network.png``  (1650x1650, random graph)
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
}


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #


def load_tricks():
    """[(name, catchphrase)] in marketplace order — the single source of truth."""
    plugins = json.load(open(MARKETPLACE, encoding="utf-8"))["plugins"]
    out = []
    for p in plugins:
        catchphrase = p["description"].split(" — ", 1)[0].strip()
        out.append((p["name"], catchphrase))
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


def network_body(names, pos, edges, hub_links):
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

    for name, (x, y) in zip(names, pos):
        body += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{NET_ICON / 2 + 8:.1f}" fill="{PAPER}"/>'
        body += icon_g(name, x, y, NET_ICON)
        body += (
            f'<text x="{x:.1f}" y="{y + NET_ICON / 2 + 38:.1f}" '
            f'font-family="{MONOFONT}" font-size="30" font-weight="600" '
            f'fill="{INK}" text-anchor="middle">{name}</text>'
        )
    return body


def network_svg(tricks, seed):
    names, pos, _phase, edges, hub_links = network_layout(tricks, seed)
    return svg_doc(NET_W, NET_W, network_body(names, pos, edges, hub_links))


def network_frames(tricks, seed, frames, amp=15.0):
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
        yield svg_doc(NET_W, NET_W, network_body(names, moved, edges, hub_links))


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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
    finally:
        os.unlink(tmp)


def render(svg, path, width, height, renderer):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(render_bytes(svg, width, height, renderer))
    print(f"  wrote {os.path.relpath(path, ROOT)}")


def render_gif(svgs, path, size, duration_ms):
    """Assemble a list of frame SVGs into a looping GIF via Pillow."""
    try:
        from PIL import Image
    except ImportError:
        sys.exit("the animation target needs Pillow (pip install Pillow).")
    import io

    frames = []
    for svg in svgs:
        png = render_bytes(svg, size, size, "cairosvg" if _has_cairosvg() else "convert")
        frames.append(Image.open(io.BytesIO(png)).convert("RGB"))
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
        choices=["all", "banners", "wheel", "network", "animation", "logo"],
        help="what to build (default: all)",
    )
    ap.add_argument("--renderer", choices=["auto", "cairosvg", "convert"], default="auto")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed for network edges")
    ap.add_argument("--frames", type=int, default=48, help="animation frame count")
    ap.add_argument("--gif-size", type=int, default=720, help="animation pixel size")
    ap.add_argument("--fps", type=int, default=20, help="animation frames per second")
    args = ap.parse_args(argv)

    targets = set(args.targets) or {"all"}
    if "all" in targets:
        targets = {"banners", "wheel", "network", "animation", "logo"}
    renderer = pick_renderer(args.renderer)
    tricks = load_tricks()
    print(f"renderer: {renderer}   tricks: {len(tricks)}")

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
    if "network" in targets:
        print(f"network (seed={args.seed}):")
        render(
            network_svg(tricks, args.seed),
            os.path.join(ASSETS, "bag-of-tricks-network.png"),
            1650,
            1650,
            renderer,
        )
    if "animation" in targets:
        print(f"animation (seed={args.seed}, {args.frames} frames):")
        svgs = network_frames(tricks, args.seed, args.frames)
        render_gif(
            svgs,
            os.path.join(ASSETS, "bag-of-tricks-network.gif"),
            args.gif_size,
            max(1, round(1000 / args.fps)),
        )
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
