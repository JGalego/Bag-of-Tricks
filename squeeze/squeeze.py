#!/usr/bin/env python3
"""squeeze — put the squeeze on it.

A compression-based AI-text detector, after thinkst's `zippy`. The hunch:
model prose is more predictable than human writing, so it *squeezes flatter*
against a corpus of known-AI text than against a corpus of known-human text.
We measure that with Normalized Compression Distance (NCD) — feed the candidate
to a compressor next to each corpus and see which one it folds into more
tightly. Closer to the AI corpus → leans machine.

It is a heuristic, not proof. No watermark, no logprobs, no ground truth —
only how the bytes fold. Short texts, heavy editing, code, and unusual genres
all throw it off. Treat the verdict as a hunch with a confidence band, the way
`mugshot` treats a style match: where `tell` reads the words and `mugshot`
names the model, `squeeze` never reads a word — it just weighs the bytes.

    echo "Certainly! It's important to note that we must delve into this." | squeeze.py
    -> likely AI-generated (low) — ai-ncd 0.86 < human-ncd 0.88 — heuristic, not proof

    squeeze.py --report draft.md            # the full breakdown
    squeeze.py --json draft.md              # the structured verdict
    squeeze.py --algo zlib draft.md         # faster, slightly looser
    squeeze.py --ai-corpus ai.txt draft.md  # bring your own known-AI corpus
    squeeze.py --max 60 draft.md            # exit 1 if AI-likelihood > 60 (CI gate)
"""

from __future__ import annotations

import argparse
import bz2
import json
import lzma
import re
import sys
import zlib

# --- the corpora ----------------------------------------------------------
# Two reference piles: stereotypical assistant prose, and idiosyncratic human
# writing. NCD measures how much structure the candidate shares with each — so
# these are caricatures on purpose, dense with the patterns each side tends to
# leave.
#
# Honest caveat: BOTH of these were hand-written for this file, not drawn from
# any dataset — the "human" pile in particular is an AI's impression of casual
# human writing, which is exactly the kind of thing a detector should distrust.
# They work as a demo (clear slop lights up; casual chat reads human), but they
# are not ground truth. For any verdict you mean to rely on, override them with
# REAL samples via --ai-corpus/--human-corpus — more, on-domain reference text
# is the single biggest accuracy win, and the only path to a defensible call.

AI_CORPUS = """\
Certainly! I'd be happy to help you with that. It's important to note that
there are several key factors to consider here. Let's delve into this topic and
explore the rich tapestry of possibilities. In today's fast-paced world, it is
crucial to leverage robust, scalable, and seamless solutions. Here's a
comprehensive breakdown:

1. First, it's worth noting that we should approach this carefully and
   thoughtfully, weighing all of the available options.
2. Furthermore, this serves as a testament to the ever-evolving landscape of
   modern technology and innovation.
3. Additionally, by harnessing the power of these tools, we can unlock new
   opportunities and foster meaningful growth.

It's not just about solving the problem — it's about understanding the
underlying principles that govern the system. However, it's worth remembering
that every situation is unique and nuanced. Ultimately, the goal is to navigate
the complexities of this multifaceted challenge with clarity and confidence.

In conclusion, by following these best practices, you can ensure a smooth and
effective outcome. I hope this helps! Let me know if you have any other
questions, and I'd be more than happy to assist you further. Overall, this
approach plays a crucial role in achieving long-term, sustainable success.
"""

HUMAN_CORPUS = """\
ok so I finally got around to fixing the thing last night. took way longer than
it should've, mostly because the docs are wrong about the config flag (it's
--retries not --retry, lol). anyway, works now.

honestly the whole codebase is held together with duct tape. there's a function
called doStuff2 that nobody remembers writing. I'm scared to touch it. grep says
it's called in exactly one place, from a cron job that may or may not still run.

reminds me of that old job where we shipped on fridays and prayed. good times,
bad idea. my manager back then, Dave, used to say "if it compiles, ship it" and
he was joking. mostly.

went for a walk after. cold out, rained a bit, the dog hated it. came back,
made tea, stared at the diff for twenty minutes before I realized I'd left a
print statement in. classic. removed it, pushed, went to bed.

three things I learned: read the actual source not the docs; the bug is almost
always in the part you were sure was fine; and never, ever trust a flag spelled
two different ways in two different files.
"""

# --- compressors ----------------------------------------------------------
# Each returns the compressed byte-length of its input. lzma is the default:
# best ratio, so the sharpest NCD signal, at some CPU cost. zlib is fastest.


def _lzma(b: bytes) -> int:
    return len(lzma.compress(b, preset=6))


def _zlib(b: bytes) -> int:
    return len(zlib.compress(b, level=9))


def _bz2(b: bytes) -> int:
    return len(bz2.compress(b, compresslevel=9))


_ALGOS = {"lzma": _lzma, "zlib": _zlib, "bz2": _bz2}

# Margin (in NCD units) below which we won't accuse anyone, and the bands above.
_FLOOR = 0.004  # gap this small → inconclusive
_SOFT = 0.010  # a multi-chunk consensus needs at least this margin to count
_MED = 0.015
_HIGH = 0.04
_MIN_WORDS = 40  # below this, the signal is too thin for anything but "low"
_CHUNK = 2000  # chars per window — comparable to the corpora, à la zippy


def _count_words(text: str) -> int:
    return max(1, len(re.findall(r"\b\w+\b", text)))


def _chunks(text: str, size: int) -> list[str]:
    """Split ``text`` into ~``size``-char windows, breaking on whitespace.

    Mirrors zippy's trick: a candidate far larger than the reference corpus
    would otherwise swamp it (``C(corpus+text) ≈ C(text)`` and every NCD
    saturates at 1.0). Scoring corpus-sized windows and aggregating keeps the
    signal alive on long inputs. Short text stays a single chunk.
    """
    text = text.strip()
    if len(text) <= size:
        return [text] if text else [""]
    out: list[str] = []
    start, n = 0, len(text)
    while start < n:
        if start + size >= n:
            out.append(text[start:])
            break
        end = text.rfind(" ", start, start + size + 1)
        if end <= start:  # no break point — hard cut
            end = start + size
        out.append(text[start:end])
        start = end + 1
    out = [c for c in out if c.strip()]
    return out or [text]


def _ncd(x: bytes, y: bytes, csize) -> float:
    """Normalized Compression Distance between ``x`` and ``y``.

        NCD(x, y) = (C(xy) - min(C(x), C(y))) / max(C(x), C(y))

    Ranges ~0 (identical) to ~1 (nothing shared). Symmetric-ish; we always
    pass the candidate first. Lower means the two fold together more tightly.
    """
    cx, cy = csize(x), csize(y)
    cxy = csize(x + b"\n" + y)
    return (cxy - min(cx, cy)) / max(cx, cy)


def _confidence(margin: float, words: int, chunks: int = 1, agree: float = 1.0) -> str:
    """Band a verdict from margin size, length, and cross-chunk agreement.

    A single window leans on raw margin. Many windows that agree on direction
    are strong evidence in their own right, so a consistent multi-chunk lean
    earns a higher band even at a smaller average margin.
    """
    m = abs(margin)
    if words < _MIN_WORDS:
        return "low"
    if m >= _HIGH or (chunks >= 6 and m >= _MED and agree >= 0.75):
        return "high"
    # A multi-chunk consensus earns medium, but only above a real margin —
    # thousands of windows tipping by a hair is still a near-tie, not evidence.
    if m >= _MED or (chunks >= 3 and m >= _SOFT and agree >= 0.70):
        return "medium"
    return "low"


def squeeze(
    text: str,
    algo: str = "lzma",
    ai_corpus: str = AI_CORPUS,
    human_corpus: str = HUMAN_CORPUS,
    chunk: int = _CHUNK,
) -> dict:
    """Weigh ``text`` against the AI and human corpora by compression.

    Returns a dict::

        {
          "verdict":       "likely AI-generated" | "likely human-written"
                            | "inconclusive",
          "confidence":    "low" | "medium" | "high",
          "ai_likelihood": 0-100,        # higher → more AI-like
          "ai_ncd":        float,        # distance to the AI corpus (lower=closer)
          "human_ncd":     float,        # distance to the human corpus
          "margin":        float,        # human_ncd - ai_ncd (>0 leans AI)
          "algo":          str,
          "words":         int,
          "chunks":        int,          # windows scored and aggregated
        }

    The candidate is split into corpus-sized windows; each is scored by NCD
    against both corpora and the results are length-weighted into one verdict.
    Windowing keeps the signal alive on long inputs (a whole book would
    otherwise swamp a small corpus, à la zippy). The candidate leans toward
    whichever corpus it shares more byte-structure with. This is a hunch —
    models drift, humans edit, a deliberate writer can fold either way — never
    read it as proof of authorship.
    """
    csize = _ALGOS[algo]
    ai_b = ai_corpus.encode("utf-8")
    human_b = human_corpus.encode("utf-8")
    words = _count_words(text)

    pieces = _chunks(text, chunk)
    total = sum(len(p) for p in pieces) or 1
    ai_ncd = human_ncd = margin = 0.0
    lean_ai = 0
    for p in pieces:
        b = p.encode("utf-8")
        a = _ncd(b, ai_b, csize)
        h = _ncd(b, human_b, csize)
        w = len(p) / total
        ai_ncd += a * w
        human_ncd += h * w
        margin += (h - a) * w  # > 0 -> closer to AI corpus -> leans machine
        if h - a > 0:
            lean_ai += 1

    n = len(pieces)
    # Fraction of windows that agree with the overall lean.
    if margin > 0:
        agree = lean_ai / n
    elif margin < 0:
        agree = (n - lean_ai) / n
    else:
        agree = 0.0

    # Map the (small) NCD margin onto a 0-100 lean. The scale constant is a
    # judgement call, not a calibration: a ~0.08 gap reads as a confident lean.
    ai_likelihood = round(max(0.0, min(100.0, 50.0 + margin * 600.0)))

    if abs(margin) < _FLOOR:
        verdict = "inconclusive"
    elif margin > 0:
        verdict = "likely AI-generated"
    else:
        verdict = "likely human-written"

    return {
        "verdict": verdict,
        "confidence": _confidence(margin, words, n, agree),
        "ai_likelihood": ai_likelihood,
        "ai_ncd": round(ai_ncd, 4),
        "human_ncd": round(human_ncd, 4),
        "margin": round(margin, 4),
        "algo": algo,
        "words": words,
        "chunks": n,
    }


def _verdict_line(r: dict) -> str:
    if r["verdict"] == "inconclusive":
        return (
            f"inconclusive ({r['confidence']}) — "
            f"ai-ncd {r['ai_ncd']:.2f} ≈ human-ncd {r['human_ncd']:.2f} — "
            "too close to call. (heuristic, not proof)"
        )
    rel = "<" if r["margin"] > 0 else ">"
    return (
        f"{r['verdict']} ({r['confidence']}) — "
        f"ai-ncd {r['ai_ncd']:.2f} {rel} human-ncd {r['human_ncd']:.2f} — "
        "heuristic, not proof"
    )


def _report_lines(r: dict) -> list[str]:
    bar_n = round(r["ai_likelihood"] / 5)
    bar = "█" * bar_n + "·" * (20 - bar_n)
    return [
        _verdict_line(r),
        "",
        f"  AI-likelihood   {bar} {r['ai_likelihood']}/100",
        f"  distance to AI corpus      {r['ai_ncd']:.4f}  (lower = closer)",
        f"  distance to human corpus   {r['human_ncd']:.4f}",
        f"  margin (human - ai)        {r['margin']:+.4f}  (positive leans AI)",
        f"  compressor                 {r['algo']}   words {r['words']}   chunks {r['chunks']}",
    ]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="squeeze", description="put the squeeze on it.")
    p.add_argument("files", nargs="*", help="files to read (default: stdin)")
    p.add_argument(
        "--algo",
        choices=sorted(_ALGOS),
        default="lzma",
        help="compressor (default: lzma — best signal; zlib is fastest)",
    )
    p.add_argument("--ai-corpus", metavar="FILE", help="override the known-AI corpus")
    p.add_argument("--human-corpus", metavar="FILE", help="override the known-human corpus")
    p.add_argument(
        "--chunk",
        type=int,
        default=_CHUNK,
        metavar="N",
        help=f"window size in chars for long inputs (default: {_CHUNK})",
    )
    p.add_argument("--report", action="store_true", help="show the full NCD breakdown")
    p.add_argument(
        "--score",
        action="store_true",
        help="print just the integer AI-likelihood (0-100)",
    )
    p.add_argument("--json", action="store_true", help="emit the verdict dict as JSON")
    p.add_argument(
        "--max",
        type=int,
        default=None,
        metavar="N",
        help="exit 1 if AI-likelihood > N (gate prose in CI)",
    )
    args = p.parse_args(argv)

    if args.files:
        raw = "".join(open(f, encoding="utf-8").read() for f in args.files)
    else:
        raw = sys.stdin.read()

    ai = open(args.ai_corpus, encoding="utf-8").read() if args.ai_corpus else AI_CORPUS
    human = open(args.human_corpus, encoding="utf-8").read() if args.human_corpus else HUMAN_CORPUS

    result = squeeze(raw, algo=args.algo, ai_corpus=ai, human_corpus=human, chunk=args.chunk)

    if args.json:
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    elif args.score:
        sys.stdout.write(f"{result['ai_likelihood']}\n")
    elif args.report:
        sys.stdout.write("\n".join(_report_lines(result)) + "\n")
    else:
        sys.stdout.write(_verdict_line(result) + "\n")

    if args.max is not None and result["ai_likelihood"] > args.max:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
