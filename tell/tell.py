#!/usr/bin/env python3
"""tell — every AI has a tell.

Reads a passage and scores how "AI-written" it reads, listing the specific
tells it found (overused words, cliché phrases, em-dash overuse, emoji, …).
It does not rewrite — it diagnoses. deadpan prevents tells at generation;
tell finds them after.

    echo "Let's delve into this rich tapestry — it's a testament." | tell.py
    -> score 90/100, hits: delve, tapestry, testament, em-dash …

    tell.py --json draft.md
    tell.py --max 30 draft.md   # exit 1 in CI if the prose reads too AI
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys

# --- tell lexicon ---------------------------------------------------------
# Edit these freely. Word lists are matched case-insensitively on word
# boundaries; phrases are regexes; structural tells are counted separately.

# Single words that pattern-match LLM prose. Word-boundary, case-insensitive.
OVERUSED_WORDS = [
    "delve",
    "tapestry",
    "testament",
    "realm",
    "navigate",
    "underscore",
    "leverage",
    "robust",
    "seamless",
    "crucial",
    "pivotal",
    "multifaceted",
    "nuanced",
    "intricate",
    "bustling",
    "vibrant",
    "foster",
    "harness",
    "elevate",
    "unlock",
    "embark",
    "landscape",
    "beacon",
    "treasure trove",
]

# Cliché phrases / constructions. Each entry is (label, regex).
CLICHE_PHRASES = [
    ("it's not just X, it's Y", r"\bit'?s not just\b[^.!?\n]*?,?\s*it'?s\b"),
    ("not only … but also", r"\bnot only\b[^.!?\n]*?\bbut also\b"),
    ("in conclusion", r"\bin conclusion\b"),
    ("in summary", r"\bin summary\b"),
    ("it's worth noting", r"\bit'?s worth noting\b"),
    ("in today's fast-paced world", r"\bin today'?s fast[- ]paced world\b"),
    ("when it comes to", r"\bwhen it comes to\b"),
    ("a testament to", r"\ba testament to\b"),
    ("plays a crucial role", r"\bplays? a (?:crucial|pivotal|vital|key) role\b"),
    ("at the end of the day", r"\bat the end of the day\b"),
    ("the world of", r"\bthe world of\b"),
    ("dive into", r"\bdive into\b"),
    ("rich tapestry", r"\brich tapestry\b"),
    ("ever-evolving", r"\bever[- ]evolving\b"),
    ("game-changer", r"\bgame[- ]changer\b"),
]

# Emoji + decorative symbols (same range used by deadpan).
_EMOJI = re.compile(
    "[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f000-\U0001f0ff"
    "\U00002190-\U000021ff\U00002b00-\U00002bff\U0000fe0f\U0000200d]+"
)

# Rule-of-three: "a, b, and c" — three comma-separated items capped by "and"/"or".
_RULE_OF_THREE = re.compile(r"\b[\w'-]+,\s+[\w'-]+,\s+(?:and|or)\s+[\w'-]+\b", re.IGNORECASE)

# Bold runs: **like this** (markdown emphasis).
_BOLD_RUN = re.compile(r"\*\*[^*\n]+\*\*")


def _count_words(text: str) -> int:
    return max(1, len(re.findall(r"\b\w+\b", text)))


def _word_hits(text: str) -> list[dict]:
    hits = []
    for word in OVERUSED_WORDS:
        # word-boundary, case-insensitive; allow space inside multiword terms.
        rx = re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
        n = len(rx.findall(text))
        if n:
            hits.append({"category": "overused word", "tell": word, "count": n})
    return hits


def _phrase_hits(text: str) -> list[dict]:
    hits = []
    for label, pat in CLICHE_PHRASES:
        n = len(re.findall(pat, text, re.IGNORECASE))
        if n:
            hits.append({"category": "cliché phrase", "tell": label, "count": n})
    return hits


def _structural_hits(text: str) -> list[dict]:
    hits = []
    em = text.count("—")
    if em:
        hits.append({"category": "structural", "tell": "em-dash", "count": em})
    emoji = sum(len(m.group(0)) for m in _EMOJI.finditer(text))
    if emoji:
        hits.append({"category": "structural", "tell": "emoji", "count": emoji})
    three = len(_RULE_OF_THREE.findall(text))
    if three:
        hits.append({"category": "structural", "tell": "rule-of-three list", "count": three})
    bold = len(_BOLD_RUN.findall(text))
    if bold:
        hits.append({"category": "structural", "tell": "bold run", "count": bold})
    return hits


def tell(text: str) -> dict:
    """Diagnose how 'AI-written' ``text`` reads.

    Returns ``{"score": 0-100, "hits": [...], "total": int}`` where each hit is
    ``{"category", "tell", "count"}``.

    Score formula (deterministic, monotonic in total tells):
        density = total_tells / words * 100      # tells per 100 words
        score   = round(100 * (1 - exp(-density / 6)))
    Saturating so it stays in 0-100; more tells never lowers the score for a
    fixed word count. ~6 tells/100 words lands around 63; it climbs from there.
    """
    hits = _word_hits(text) + _phrase_hits(text) + _structural_hits(text)
    total = sum(h["count"] for h in hits)
    words = _count_words(text)

    density = total / words * 100.0
    # 1 - exp(-x) is monotonic increasing, bounded in [0, 1).
    score = round(100 * (1 - math.exp(-density / 6.0)))
    score = max(0, min(100, score))

    # Sort hits: highest count first, then category, then tell — stable report.
    hits.sort(key=lambda h: (-h["count"], h["category"], h["tell"]))
    return {"score": score, "hits": hits, "total": total}


def _report(result: dict) -> str:
    lines = [f"score {result['score']}/100  ({result['total']} tells)"]
    by_cat: dict[str, list[dict]] = {}
    for h in result["hits"]:
        by_cat.setdefault(h["category"], []).append(h)
    if not result["hits"]:
        lines.append("  no tells found — reads clean.")
    for cat in ("overused word", "cliché phrase", "structural"):
        items = by_cat.get(cat)
        if not items:
            continue
        lines.append(f"\n{cat}s:")
        for h in items:
            lines.append(f"  {h['tell']} ×{h['count']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tell", description="every AI has a tell.")
    p.add_argument("files", nargs="*", help="files to read (default: stdin)")
    p.add_argument("--score", action="store_true", help="print just the integer score")
    p.add_argument("--json", action="store_true", help="emit the result dict as JSON")
    p.add_argument(
        "--max",
        type=int,
        default=None,
        metavar="N",
        help="exit 1 if score > N (gate prose in CI)",
    )
    args = p.parse_args(argv)

    if args.files:
        raw = "".join(open(f, encoding="utf-8").read() for f in args.files)
    else:
        raw = sys.stdin.read()

    result = tell(raw)

    if args.json:
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    elif args.score:
        sys.stdout.write(f"{result['score']}\n")
    else:
        sys.stdout.write(_report(result))

    if args.max is not None and result["score"] > args.max:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
