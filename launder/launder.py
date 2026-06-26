#!/usr/bin/env python3
"""launder — wash out the prints.

Strips the *mechanical* fingerprints that mark text as machine-produced:
zero-width and invisible characters, smart quotes, fancy dashes, the unicode
ellipsis, non-breaking and exotic spaces, soft hyphens. It does NOT rewrite
prose — detecting word-level tells is `tell`'s job, and rephrasing is the
model's. launder only touches the bytes, never the words. A stdin->stdout
filter: cleaned text to stdout, a one-line summary to stderr.

    printf 'he said \xe2\x80\x9chi\xe2\x80\x9d\xe2\x80\x8b' | launder.py
    -> he said "hi"          (summary on stderr)

    cat draft.md | launder.py --check     # exit 1 if any fingerprint present
    launder.py --report < draft.md        # list what it found by category

Custom patterns
---------------
Extend the scrub table without editing the source. Pass one or more
``--patterns FILE`` flags (repeatable), or set ``LAUNDER_PATTERNS`` to an
os.pathsep-separated list of paths (used only when no flag is given). Each file
is JSON mapping a category to a ``char -> replacement`` map::

    {"smart_quote": {"«": "\\"", "»": "\\""},
     "bullet":      {"•": "-"}}

Known categories extend the built-in maps; brand-new categories (like
``bullet``) are allowed and show up in reports/findings under that name. User
entries override the built-ins on character collision.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# --- character-level scrubbers --------------------------------------------
# Each entry maps an original character to its ASCII replacement (""=delete).
# The *type* (left of the tuple) is the category reported in summaries/JSON.
# This is the whole laundry list — one dict, easy to read, easy to extend.

# Zero-width / invisible characters. These carry no glyph; they only mark text
# as machine-pasted (or worse, watermark it). Strip them entirely.
_ZERO_WIDTH: dict[str, str] = {
    "​": "",  # ZERO WIDTH SPACE
    "‌": "",  # ZERO WIDTH NON-JOINER
    "‍": "",  # ZERO WIDTH JOINER
    "⁠": "",  # WORD JOINER
    "﻿": "",  # BOM / ZERO WIDTH NO-BREAK SPACE
}

# Soft hyphen: an invisible "you may break here" marker. Just remove it.
_SOFT_HYPHEN: dict[str, str] = {
    "­": "",  # SOFT HYPHEN
}

# Curly/smart quotes -> straight ASCII quotes.
_SMART_QUOTE: dict[str, str] = {
    "“": '"',  # LEFT DOUBLE QUOTATION MARK
    "”": '"',  # RIGHT DOUBLE QUOTATION MARK
    "„": '"',  # DOUBLE LOW-9 QUOTATION MARK
    "‟": '"',  # DOUBLE HIGH-REVERSED-9 QUOTATION MARK
    "‘": "'",  # LEFT SINGLE QUOTATION MARK
    "’": "'",  # RIGHT SINGLE QUOTATION MARK (also the typographic apostrophe)
    "‚": "'",  # SINGLE LOW-9 QUOTATION MARK
    "‛": "'",  # SINGLE HIGH-REVERSED-9 QUOTATION MARK
}

# Em-dash defaults to "--", en-dash to "-". Both are configurable, but these
# are the documented defaults: an em-dash is two hyphens' worth of pause.
_EM_DASH_DEFAULT = "--"
_EN_DASH_DEFAULT = "-"

_DASH: dict[str, str] = {
    "—": _EM_DASH_DEFAULT,  # EM DASH
    "–": _EN_DASH_DEFAULT,  # EN DASH
    "‒": _EN_DASH_DEFAULT,  # FIGURE DASH
    "―": _EM_DASH_DEFAULT,  # HORIZONTAL BAR
    "−": "-",  # MINUS SIGN
}

# Unicode horizontal ellipsis -> three ASCII dots.
_ELLIPSIS: dict[str, str] = {
    "…": "...",  # HORIZONTAL ELLIPSIS
}

# Non-breaking and other exotic spaces -> a plain ASCII space.
_EXOTIC_SPACE: dict[str, str] = {
    " ": " ",  # NO-BREAK SPACE
    " ": " ",  # FIGURE SPACE
    " ": " ",  # THIN SPACE
    " ": " ",  # HAIR SPACE
    " ": " ",  # EN SPACE
    " ": " ",  # EM SPACE
    " ": " ",  # THREE-PER-EM SPACE
    " ": " ",  # FOUR-PER-EM SPACE
    " ": " ",  # SIX-PER-EM SPACE
    " ": " ",  # PUNCTUATION SPACE
    " ": " ",  # NARROW NO-BREAK SPACE
    " ": " ",  # MEDIUM MATHEMATICAL SPACE
    "　": " ",  # IDEOGRAPHIC SPACE
}

# Homoglyphs: confusable Cyrillic/Greek look-alikes that read as ASCII Latin.
# OPT-IN ONLY (--homoglyphs): this is lossy — a real Cyrillic word would be
# mangled — so we never run it unless the caller asks. Maps the common
# single-letter confusables back to their ASCII twins.
_HOMOGLYPH: dict[str, str] = {
    # Cyrillic -> Latin
    "а": "a",  # CYRILLIC SMALL A
    "А": "A",  # CYRILLIC CAPITAL A
    "е": "e",  # CYRILLIC SMALL IE
    "Е": "E",  # CYRILLIC CAPITAL IE
    "о": "o",  # CYRILLIC SMALL O
    "О": "O",  # CYRILLIC CAPITAL O
    "р": "p",  # CYRILLIC SMALL ER
    "Р": "P",  # CYRILLIC CAPITAL ER
    "с": "c",  # CYRILLIC SMALL ES
    "С": "C",  # CYRILLIC CAPITAL ES
    "х": "x",  # CYRILLIC SMALL HA
    "Х": "X",  # CYRILLIC CAPITAL HA
    "у": "y",  # CYRILLIC SMALL U
    "У": "Y",  # CYRILLIC CAPITAL U
    "і": "i",  # CYRILLIC SMALL BYELORUSSIAN-UKRAINIAN I
    "І": "I",  # CYRILLIC CAPITAL BYELORUSSIAN-UKRAINIAN I
    "ј": "j",  # CYRILLIC SMALL JE
    "һ": "h",  # CYRILLIC SMALL SHHA
    "ԁ": "d",  # CYRILLIC SMALL KOMI DE
    "ԛ": "q",  # CYRILLIC SMALL QA
    "ѕ": "s",  # CYRILLIC SMALL DZE
    "в": "b",  # CYRILLIC SMALL VE (loose)
    # Greek -> Latin
    "ο": "o",  # GREEK SMALL OMICRON
    "Ο": "O",  # GREEK CAPITAL OMICRON
    "α": "a",  # GREEK SMALL ALPHA
    "Α": "A",  # GREEK CAPITAL ALPHA
    "Β": "B",  # GREEK CAPITAL BETA
    "Ε": "E",  # GREEK CAPITAL EPSILON
    "Η": "H",  # GREEK CAPITAL ETA
    "Ι": "I",  # GREEK CAPITAL IOTA
    "Κ": "K",  # GREEK CAPITAL KAPPA
    "Μ": "M",  # GREEK CAPITAL MU
    "Ν": "N",  # GREEK CAPITAL NU
    "Ρ": "P",  # GREEK CAPITAL RHO
    "Τ": "T",  # GREEK CAPITAL TAU
    "Υ": "Y",  # GREEK CAPITAL UPSILON
    "Χ": "X",  # GREEK CAPITAL CHI
    "ν": "v",  # GREEK SMALL NU (loose)
}

# Category name -> the substitution map it draws from. Order here is the order
# categories are reported; lookups below are flattened into one table.
_BASE_MAPS: dict[str, dict[str, str]] = {
    "zero_width": _ZERO_WIDTH,
    "soft_hyphen": _SOFT_HYPHEN,
    "smart_quote": _SMART_QUOTE,
    "em_dash": {"—": _EM_DASH_DEFAULT, "―": _EM_DASH_DEFAULT},
    "en_dash": {"–": _EN_DASH_DEFAULT, "‒": _EN_DASH_DEFAULT, "−": "-"},
    "ellipsis": _ELLIPSIS,
    "exotic_space": _EXOTIC_SPACE,
}


# Env var carrying os.pathsep-separated pattern files when --patterns is absent.
_ENV_VAR = "LAUNDER_PATTERNS"


def _load_patterns(paths: list[str] | None) -> dict[str, dict[str, str]]:
    """Load + merge custom ``{category: {char: replacement}}`` maps from JSON.

    Returns a merged map keyed by category. When ``paths`` is None, the
    ``LAUNDER_PATTERNS`` env var (os.pathsep-separated) is consulted instead.
    Known categories extend the built-ins; new categories are allowed.
    """
    extra: dict[str, dict[str, str]] = {}

    if paths is None:
        env = os.environ.get(_ENV_VAR, "")
        paths = [p for p in env.split(os.pathsep) if p] if env else []

    for path in paths:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        for category, mapping in data.items():
            extra.setdefault(category, {}).update(mapping)
    return extra


def _build_table(
    homoglyphs: bool, extra: dict[str, dict[str, str]] | None = None
) -> dict[str, tuple[str, str]]:
    """Flatten the per-category maps into ``char -> (category, replacement)``.

    The dash maps overlap conceptually with ``_DASH``; we build straight from
    the per-category maps so each character reports the right category. ``extra``
    is a merged ``{category: {char: replacement}}`` map of user patterns: known
    categories extend the built-ins, new categories are added, and per-character
    collisions let the user entry win (it is applied last).
    """
    table: dict[str, tuple[str, str]] = {}
    for category, mapping in _BASE_MAPS.items():
        for char, repl in mapping.items():
            table[char] = (category, repl)
    if homoglyphs:
        for char, repl in _HOMOGLYPH.items():
            table[char] = ("homoglyph", repl)
    if extra:
        for category, mapping in extra.items():
            for char, repl in mapping.items():
                table[char] = (category, repl)
    return table


def launder(
    text: str, homoglyphs: bool = False, extra: dict[str, dict[str, str]] | None = None
) -> tuple[str, list[dict]]:
    """Wash the mechanical fingerprints out of ``text``.

    Returns ``(cleaned_text, findings)`` where each finding is
    ``{"type", "char", "start"}`` against the *original* text. ``type`` is the
    category (``zero_width``, ``smart_quote``, ``em_dash``, …); ``char`` is the
    offending character; ``start`` is its offset in the original.

    Pure ASCII text round-trips byte-for-byte with an empty findings list.
    ``homoglyphs=True`` additionally normalizes confusable Cyrillic/Greek
    look-alikes back to ASCII — opt-in, because it is lossy. ``extra`` is a
    merged ``{category: {char: replacement}}`` map of user patterns (see
    ``_load_patterns``); characters in custom categories report under that name.
    """
    table = _build_table(homoglyphs, extra)
    out: list[str] = []
    findings: list[dict] = []
    for i, ch in enumerate(text):
        hit = table.get(ch)
        if hit is None:
            out.append(ch)
            continue
        category, repl = hit
        findings.append({"type": category, "char": ch, "start": i})
        out.append(repl)
    return "".join(out), findings


def _counts(findings: list[dict]) -> dict[str, int]:
    """Tally findings by category, preserving first-seen order."""
    counts: dict[str, int] = {}
    for f in findings:
        counts[f["type"]] = counts.get(f["type"], 0) + 1
    return counts


def _report_lines(findings: list[dict]) -> list[str]:
    """One line per category: ``category  count  @first_offset``."""
    counts = _counts(findings)
    first: dict[str, int] = {}
    for f in findings:
        first.setdefault(f["type"], f["start"])
    lines = []
    for category in sorted(counts):
        lines.append(f"{category}\t{counts[category]}\t@{first[category]}")
    return lines


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="launder",
        description="wash out the prints.",
    )
    p.add_argument("files", nargs="*", help="files to read (default: stdin)")
    p.add_argument(
        "--check",
        action="store_true",
        help="print nothing; exit 1 if any fingerprint present (gates a pipeline)",
    )
    p.add_argument(
        "--report",
        action="store_true",
        help="list findings by category (count + first offset) to stdout; exit 0",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="emit a structured summary (counts + findings) as JSON",
    )
    p.add_argument(
        "--homoglyphs",
        action="store_true",
        help="also normalize confusable Cyrillic/Greek look-alikes (opt-in; lossy)",
    )
    p.add_argument(
        "--patterns",
        metavar="FILE",
        action="append",
        help="JSON file of custom {category: {char: replacement}} maps to merge in "
        "(repeatable; falls back to $LAUNDER_PATTERNS when absent)",
    )
    args = p.parse_args(argv)

    if args.files:
        raw = "".join(open(f, encoding="utf-8").read() for f in args.files)
    else:
        raw = sys.stdin.read()

    # Merge custom patterns (built-ins are the base; user entries extend/override).
    try:
        extra = _load_patterns(args.patterns)
    except (OSError, ValueError) as e:
        sys.stderr.write(f"[launder] could not load patterns: {e}\n")
        return 2

    cleaned, findings = launder(raw, homoglyphs=args.homoglyphs, extra=extra)

    # --json: structured summary to stdout.
    if args.json:
        payload = {
            "count": len(findings),
            "counts": _counts(findings),
            "findings": findings,
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 1 if (args.check and findings) else 0

    # --report: list findings by category to stdout, exit 0.
    if args.report:
        if findings:
            sys.stdout.write("\n".join(_report_lines(findings)) + "\n")
        else:
            sys.stdout.write("clean — no fingerprints\n")
        return 0

    # Summary to stderr in every non-json mode.
    if findings:
        counts = _counts(findings)
        tally = ", ".join(f"{n}×{t}" for t, n in counts.items())
        sys.stderr.write(f"[launder] scrubbed {len(findings)}: {tally}\n")
    else:
        sys.stderr.write("[launder] clean\n")

    # --check: gate mode. No cleaned text, exit 1 on any finding.
    if args.check:
        return 1 if findings else 0

    # Default: print the cleaned text.
    sys.stdout.write(cleaned)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
