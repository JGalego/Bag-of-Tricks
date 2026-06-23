#!/usr/bin/env python3
"""fold — know when to fold.

In poker you fold a weak hand instead of bluffing it. ``fold`` is the honest
counterpart to ``bluff``: it catches *overconfident* language — a draft answer
asserting with false certainty where it should hedge or abstain. A stdin->stdout
filter: it tags each overconfidence marker like ``[FOLD:certainty]`` so the
draft can be softened, and writes a summary to stderr. It flags *tone*, not
truth — it tells you where you're bluffing, not whether you're wrong.

    echo "This will definitely always work, guaranteed." | fold.py
    -> This will [FOLD:certainty] [FOLD:absolute] work, [FOLD:no_doubt].

    cat answer.txt | fold.py --check     # exit 1 if it overclaims anywhere
    fold.py --report < answer.txt        # list the tells with offsets
"""

from __future__ import annotations

import argparse
import json
import re
import sys

# --- detectors ------------------------------------------------------------
# Each entry maps a marker type to a compiled regex. Spans are collected across
# all of them and resolved left-to-right so overlapping matches never corrupt
# offsets. Patterns lean toward high-signal certainty/bluff phrasing — we flag
# overclaiming tone, not facts, so we'd rather miss a soft one than nag every
# ordinary word. All matching is case-insensitive.

_DETECTORS: dict[str, re.Pattern[str]] = {
    # Bare certainty adverbs — the model swearing it's sure.
    "certainty": re.compile(
        r"\b(?:certainly|definitely|undoubtedly|indisputably|unquestionably|"
        r"obviously|clearly|surely|absolutely|positively)\b",
        re.IGNORECASE,
    ),
    # Doubt-erasing constructions — "without a doubt", "100%", "guaranteed".
    "no_doubt": re.compile(
        r"\b(?:without(?: a)? doubt|beyond(?: any)? doubt|"
        r"there is no question|no doubt about it|guaranteed|100\s*%)\b",
        re.IGNORECASE,
    ),
    # Sweeping absolutes. These are common words, so we only fire on the
    # universal quantifiers themselves — "always/never/every/all" — which is
    # where unearned certainty hides. ("all" is included; tune --only if noisy.)
    "absolute": re.compile(
        r"\b(?:always|never|every|all|none|everything|nothing|"
        r"everyone|nobody|impossible)\b",
        re.IGNORECASE,
    ),
    # Trust-me / appeal-to-consensus authority — confidence borrowed, not earned.
    "false_authority": re.compile(
        r"\b(?:trust me|everyone knows|everybody knows|"
        r"it(?:'s| is) (?:well[- ])?known|as everyone knows|"
        r"needless to say|it goes without saying)\b",
        re.IGNORECASE,
    ),
}

_ALL_TYPES = frozenset(_DETECTORS)

# How much of a marker to echo in a preview before the ellipsis.
_PREVIEW = 24


def _preview(match: str) -> str:
    """A short, single-line preview of a matched marker."""
    flat = " ".join(match.split())
    return flat if len(flat) <= _PREVIEW else flat[:_PREVIEW] + "…"


def fold(text: str, types: set[str] | None = None) -> tuple[str, list[dict]]:
    """Flag overconfidence markers in ``text``.

    Returns ``(tagged_text, findings)`` where each finding is
    ``{"type", "match", "start", "end"}`` against the *original* text and the
    tagged text replaces each marker with ``[FOLD:type]``. ``types`` optionally
    restricts which detectors run (default: all).

    Overlapping matches are resolved left-to-right, longest-first, so offsets
    stay sane and the rebuilt text never gets corrupted. Calibrated, hedged
    text comes back untouched with an empty findings list.
    """
    active = _ALL_TYPES if types is None else (set(types) & set(_DETECTORS))

    # Collect every span from every active detector.
    spans: list[tuple[int, int, str, str]] = []
    for name in _DETECTORS:
        if name not in active:
            continue
        for m in _DETECTORS[name].finditer(text):
            spans.append((m.start(), m.end(), name, m.group(0)))

    # Sort by start, then longest-first so we keep the widest span when two
    # detectors fire on the same region.
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))

    findings: list[dict] = []
    out: list[str] = []
    cursor = 0
    for start, end, name, match in spans:
        if start < cursor:
            # Overlaps an already-tagged span — skip to avoid double tagging.
            continue
        out.append(text[cursor:start])
        out.append(f"[FOLD:{name}]")
        findings.append({"type": name, "match": match, "start": start, "end": end})
        cursor = end
    out.append(text[cursor:])

    return "".join(out), findings


def _summary_lines(findings: list[dict]) -> list[str]:
    """Human-readable lines for a findings list: type, preview, offset."""
    return [f"{f['type']}\t{_preview(f['match'])}\t@{f['start']}" for f in findings]


def _tally(findings: list[dict]) -> str:
    """A `2×certainty, 1×absolute` style tally, sorted by type."""
    counts: dict[str, int] = {}
    for f in findings:
        counts[f["type"]] = counts.get(f["type"], 0) + 1
    return ", ".join(f"{n}×{t}" for t, n in sorted(counts.items()))


def _inflation_score(text: str, findings: list[dict]) -> float:
    """Confidence-inflation: overconfidence markers per 100 words."""
    words = len(text.split())
    if not words:
        return 0.0
    return round(len(findings) * 100.0 / words, 2)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="fold",
        description="know when to fold.",
    )
    p.add_argument("files", nargs="*", help="files to read (default: stdin)")
    p.add_argument(
        "--check",
        action="store_true",
        help="print nothing; exit 1 if any overconfidence marker is found (gates a check)",
    )
    p.add_argument(
        "--report",
        action="store_true",
        help="list markers (type + preview + offset) to stdout; exit 0",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="emit findings as JSON",
    )
    p.add_argument(
        "--score",
        action="store_true",
        help="print a single confidence-inflation score (markers per 100 words)",
    )
    p.add_argument(
        "--only",
        metavar="t1,t2",
        help="restrict to a comma-separated list of marker types",
    )
    args = p.parse_args(argv)

    if args.files:
        raw = "".join(open(f, encoding="utf-8").read() for f in args.files)
    else:
        raw = sys.stdin.read()

    # Resolve which detectors run.
    if args.only:
        wanted = {t.strip() for t in args.only.split(",") if t.strip()}
        unknown = wanted - set(_DETECTORS)
        if unknown:
            sys.stderr.write(
                f"[fold] unknown marker(s): {', '.join(sorted(unknown))}\n"
                f"[fold] known: {', '.join(sorted(_DETECTORS))}\n"
            )
            return 2
        types: set[str] | None = wanted
    else:
        types = None

    tagged, findings = fold(raw, types)

    # --score: a quick gauge of how much the draft is bluffing.
    if args.score:
        score = _inflation_score(raw, findings)
        sys.stdout.write(
            f"[fold] confidence-inflation: {score} markers/100w ({len(findings)} tells)\n"
        )
        return 1 if (args.check and findings) else 0

    # --json: structured findings to stdout.
    if args.json:
        payload = [
            {
                "type": f["type"],
                "preview": _preview(f["match"]),
                "start": f["start"],
                "end": f["end"],
            }
            for f in findings
        ]
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 1 if (args.check and findings) else 0

    # --report: list the tells to stdout, exit 0.
    if args.report:
        if findings:
            sys.stdout.write("\n".join(_summary_lines(findings)) + "\n")
        else:
            sys.stdout.write("clean — nothing to fold\n")
        return 0

    # Summary to stderr in every non-json, non-report mode.
    if findings:
        sys.stderr.write(f"[fold] {len(findings)} tells: {_tally(findings)}\n")
    else:
        sys.stderr.write("[fold] clean — nothing to fold\n")

    # --check: gate mode. No tagged text, exit 1 on any tell.
    if args.check:
        return 1 if findings else 0

    # Default: print the tagged text so the bluffing spots are visible.
    sys.stdout.write(tagged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
