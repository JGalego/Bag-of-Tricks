#!/usr/bin/env python3
"""mugshot — we know your prints.

A stylometric parlor trick. Given a chunk of text, it guesses which model or
family most likely wrote it from stylistic fingerprints, and shows the prints
it matched. It is a heuristic, not forensic proof: models drift, mimic each
other, and a deliberate human can fake any style. Treat the verdict as a hunch.

Where `tell` flags the giveaways in AI prose, mugshot uses those same prints to
*name a suspect* — it lines the families up and points at the most likely one.

    echo "Certainly! I'd be happy to help. It's important to note..." | mugshot.py
    -> most likely: gpt-ish (medium confidence) — heuristic, not proof

    mugshot.py --report draft.md   # every matched print + offset
    mugshot.py --all draft.md      # full ranked scoreboard
    mugshot.py --json draft.md     # the structured verdict
"""

from __future__ import annotations

import argparse
import json
import re
import sys

# --- the line-up ----------------------------------------------------------
# Each SUSPECT is a stylistic profile: a list of (weight, label, regex) prints.
# Weights are deliberately coarse — these are hunches, not measurements. A high
# weight means "if you see this, lean hard"; a low weight means "mild tell".
# Matches are case-insensitive. Edit these freely; they are caricatures, not
# science. Models drift and copy each other, so none of this is definitive.

# A "print" tuple: (weight, label, pattern).
_Print = tuple[float, str, str]

SUSPECTS: dict[str, list[_Print]] = {
    # The eager assistant: opener exclamations, hedging boilerplate, bolded
    # section headers, numbered listicles, tidy windups.
    "gpt-ish": [
        (3.0, "Certainly! opener", r"\bcertainly[!,]"),
        (2.5, "I'd be happy to", r"\bi'?d be happy to\b"),
        (2.5, "It's important to note", r"\bit'?s important to (?:note|remember)\b"),
        (2.0, "However, it's worth", r"\bhowever,\s+it'?s worth\b"),
        (1.5, "In conclusion", r"\bin conclusion\b"),
        (1.5, "Overall,", r"(?m)^\s*overall,"),
        (1.5, "bold header", r"(?m)^\s*\*\*[^*\n]+\*\*\s*:?\s*$"),
        (1.0, "numbered listicle", r"(?m)^\s*\d+\.\s+\S"),
        (1.0, "I hope this helps", r"\bi hope this helps\b"),
        (1.0, "Sure, here's", r"\bsure,\s+here'?s\b"),
    ],
    # The warm collaborator: first-person leads, em-dash asides, gentle
    # praise, "let me / here's" framing.
    "claude-ish": [
        (2.5, "I'll … lead", r"(?m)^\s*i'?ll\s+\w+"),
        (2.0, "Let me … lead", r"(?m)^\s*let me\s+\w+"),
        (2.0, "Here's … lead", r"(?m)^\s*here'?s\s+\w+"),
        (2.5, "Great question", r"\bgreat question\b"),
        (1.5, "Sure, opener", r"(?m)^\s*sure[!,]"),
        (1.5, "happy to help (warm)", r"\bhappy to help\b"),
        (1.0, "em-dash aside", r"—"),
        (1.0, "worth keeping in mind", r"\bworth keeping in mind\b"),
        (1.0, "a couple of things", r"\ba (?:couple|few) (?:of )?things\b"),
    ],
    # The universal tells — the prints any model leaves (borrowed from `tell`).
    # These don't pin a family; they just confirm "a model was here".
    "generic-AI": [
        (2.0, "delve", r"\bdelve\b"),
        (2.0, "tapestry", r"\btapestry\b"),
        (2.0, "navigate the complexities", r"\bnavigat\w*\s+the\s+complexit\w+\b"),
        (2.5, "it's not just X, it's Y", r"\bit'?s not just\b[^.!?\n]*?,?\s*it'?s\b"),
        (2.0, "in today's fast-paced", r"\bin today'?s fast[- ]paced\b"),
        (1.5, "testament to", r"\ba testament to\b"),
        (1.5, "ever-evolving", r"\bever[- ]evolving\b"),
        (1.0, "crucial", r"\bcrucial\b"),
        (1.0, "leverage", r"\bleverage\b"),
        (1.0, "robust", r"\brobust\b"),
    ],
}

# Score separations and absolute hit counts get bucketed into these confidence
# bands. Everything here is a judgement call, not a calibration.
_HIGH_MARGIN = 2.5  # top score must beat the runner-up by at least this …
_HIGH_HITS = 3.0  # … and the top score itself must clear this.
_MED_MARGIN = 1.0
_MED_HITS = 1.5

# Below this, we don't accuse anyone.
_FLOOR = 1.0


def _compile() -> dict[str, list[tuple[float, str, re.Pattern[str]]]]:
    """Pre-compile every suspect's prints (case-insensitive)."""
    out: dict[str, list[tuple[float, str, re.Pattern[str]]]] = {}
    for suspect, prints in SUSPECTS.items():
        out[suspect] = [
            (weight, label, re.compile(pat, re.IGNORECASE)) for weight, label, pat in prints
        ]
    return out


_COMPILED = _compile()


def _count_words(text: str) -> int:
    return max(1, len(re.findall(r"\b\w+\b", text)))


def _confidence(top: float, runner_up: float) -> str:
    """Bucket a verdict into low/medium/high from absolute score + separation."""
    margin = top - runner_up
    if top >= _HIGH_HITS and margin >= _HIGH_MARGIN:
        return "high"
    if top >= _MED_HITS and margin >= _MED_MARGIN:
        return "medium"
    return "low"


def mugshot(text: str) -> dict:
    """Guess who wrote ``text`` from stylistic fingerprints.

    Returns a dict::

        {
          "verdict":    <suspect name or "human / inconclusive">,
          "confidence": "low" | "medium" | "high",
          "scores":     {suspect: weighted_score, ...},
          "prints":     [{"suspect", "match", "label", "start", "weight"}, ...],
        }

    Scores are the summed weights of matched prints, lightly normalized by
    length so a long document of mild tells doesn't out-shout a short, blatant
    one. This is a heuristic guess — models drift and mimic each other, and a
    human can fake any style — never read it as proof of authorship.
    """
    words = _count_words(text)
    # Gentle length normalization: long texts naturally accrue more raw hits,
    # so divide the raw weight by a slow function of length. sqrt keeps short
    # damning passages punchy while not letting essays win on volume alone.
    norm = (words / 100.0) ** 0.5
    norm = norm if norm >= 1.0 else 1.0

    prints: list[dict] = []
    raw: dict[str, float] = {}
    for suspect, compiled in _COMPILED.items():
        total = 0.0
        for weight, label, rx in compiled:
            for m in rx.finditer(text):
                total += weight
                prints.append(
                    {
                        "suspect": suspect,
                        "match": m.group(0),
                        "label": label,
                        "start": m.start(),
                        "weight": weight,
                    }
                )
        raw[suspect] = total

    scores = {s: round(v / norm, 3) for s, v in raw.items()}

    # Rank: highest score first; ties broken by suspect name for determinism.
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    top_name, top_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0

    if top_score < _FLOOR:
        verdict = "human / inconclusive"
        confidence = "low"
    else:
        verdict = top_name
        confidence = _confidence(top_score, runner_up)

    # Prints sorted by offset for a stable, readable report.
    prints.sort(key=lambda p: (p["start"], p["suspect"]))

    return {
        "verdict": verdict,
        "confidence": confidence,
        "scores": scores,
        "prints": prints,
    }


_PREVIEW = 32


def _preview(match: str) -> str:
    """A short, single-line preview of a matched print."""
    one_line = " ".join(match.split())
    if len(one_line) > _PREVIEW:
        return one_line[:_PREVIEW] + "…"
    return one_line


def _verdict_line(result: dict) -> str:
    verdict = result["verdict"]
    if verdict == "human / inconclusive":
        return "inconclusive — no strong prints; could be human. (heuristic, not proof)"
    return f"most likely: {verdict} ({result['confidence']} confidence) — heuristic, not proof"


def _report_lines(result: dict) -> list[str]:
    """Every matched print: suspect, preview, offset."""
    lines = [_verdict_line(result), ""]
    if not result["prints"]:
        lines.append("no prints lifted — clean.")
        return lines
    lines.append("prints lifted:")
    for p in result["prints"]:
        lines.append(f"  {p['suspect']:<12} {_preview(p['match']):<34} @{p['start']}")
    return lines


def _scoreboard_lines(result: dict) -> list[str]:
    """The full ranked line-up of every suspect."""
    lines = [_verdict_line(result), "", "line-up (weighted, length-normalized):"]
    ranked = sorted(result["scores"].items(), key=lambda kv: (-kv[1], kv[0]))
    for suspect, score in ranked:
        marker = " <-- most likely" if suspect == result["verdict"] else ""
        lines.append(f"  {suspect:<12} {score:>7.3f}{marker}")
    return lines


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mugshot", description="we know your prints.")
    p.add_argument("files", nargs="*", help="files to read (default: stdin)")
    p.add_argument(
        "--report",
        action="store_true",
        help="list every matched print (suspect + preview + offset)",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="show the full ranked scoreboard of all suspects",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="emit the full structured verdict as JSON",
    )
    args = p.parse_args(argv)

    if args.files:
        raw = "".join(open(f, encoding="utf-8").read() for f in args.files)
    else:
        raw = sys.stdin.read()

    result = mugshot(raw)

    if args.json:
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    elif args.report:
        sys.stdout.write("\n".join(_report_lines(result)) + "\n")
    elif args.all:
        sys.stdout.write("\n".join(_scoreboard_lines(result)) + "\n")
    else:
        sys.stdout.write(_verdict_line(result) + "\n")
        if result["prints"]:
            shown = ", ".join(
                f"{p['suspect']}:{_preview(p['match'])}" for p in result["prints"][:6]
            )
            sys.stdout.write(f"prints: {shown}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
