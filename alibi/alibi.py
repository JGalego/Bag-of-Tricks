#!/usr/bin/env python3
"""alibi — does the story check out?

A grounding / faithfulness checker. Takes an ANSWER and one or more SOURCE
documents, splits the answer into sentences (claims), and flags every claim
that has no support in the sources. bluff checks the links; alibi checks the
story. Zero-dependency, deterministic, lexical — no model calls, just overlap.

    alibi.py answer.txt --source sources.txt
    cat answer.txt | alibi.py --source-text "the ground truth ..."
    alibi.py answer.txt --source a.txt --source b.txt --check   # gate a RAG run
    alibi.py answer.txt --source sources.txt --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys

# Sentence splitter: break on . ! ? followed by whitespace, but not after a
# short run that looks like an abbreviation (e.g. "U.S.", "etc.", "Dr."). This
# is deliberately simple — good enough to carve an answer into claims, not a
# linguistics project.
_ABBREV = frozenset(
    {
        "mr",
        "mrs",
        "ms",
        "dr",
        "prof",
        "sr",
        "jr",
        "st",
        "vs",
        "etc",
        "e.g",
        "i.e",
        "fig",
        "no",
        "inc",
        "ltd",
        "co",
        "corp",
        "u.s",
        "u.k",
        "approx",
    }
)

# A boundary is end-punctuation + whitespace. We split there, then stitch back
# any split that landed right after an abbreviation.
_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# Content tokens: runs of letters/digits (with internal apostrophes/hyphens).
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*")

# A small, boring stopword set. Pulling these before scoring keeps "the sky is
# blue" from scoring high against a source that merely contains "the" and "is".
# The second line is conversational filler — greetings and chatty connective
# tissue ("Sure!", "Of course, here you go.") that an LLM tacks on. Stripping
# it means a pure-greeting sentence ends up with no content words and is treated
# as neutral, not flagged as a fabricated claim.
_STOPWORDS = frozenset(
    """
    a an and are as at be been being but by can could did do does doing done
    for from had has have having he her hers him his how i if in into is it its
    me my no nor not of off on once only or other our ours out over own same she
    should so some such than that the their theirs them then there these they this
    those through to too under until up very was we were what when where which
    while who whom why will with would you your yours
    sure okay ok yes yeah yep nope hi hello hey thanks please certainly absolutely
    course here go great sorry well alright cheers
    """.split()
)


def _tokenize(text: str) -> list[str]:
    """Lowercase content words with stopwords and punctuation stripped."""
    return [w for w in (m.group(0).lower() for m in _WORD_RE.finditer(text)) if w not in _STOPWORDS]


def _bigrams(tokens: list[str]) -> list[str]:
    """Adjacent content-word pairs — cheap phrase-level signal."""
    return [f"{a} {b}" for a, b in zip(tokens, tokens[1:])]


def split_sentences(text: str) -> list[str]:
    """Carve text into sentence-shaped claims.

    Splits on .!? + whitespace, then re-joins a fragment back onto the previous
    one when the previous fragment ended in a known abbreviation (so "Dr. Smith
    agrees." stays one claim). Blank fragments are dropped.
    """
    pieces = _SPLIT_RE.split(text.strip())
    out: list[str] = []
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if out:
            last = out[-1]
            tail = last[:-1] if last and last[-1] in ".!?" else last
            last_word = _WORD_RE.findall(tail.lower())
            if last_word and last_word[-1] in _ABBREV:
                out[-1] = f"{last} {piece}"
                continue
        out.append(piece)
    return out


def _support_score(
    claim_tokens: list[str], source_unigrams: set[str], source_bigrams: set[str]
) -> float:
    """Fraction of a claim's content that the source corroborates.

    Combines unigram and bigram overlap: a claim scores high only when its
    *words* appear in the source AND (weighted) its word *pairs* do too, so a
    sentence that reuses the source's vocabulary in a different order doesn't
    sail through as easily. Pure lexical overlap — no semantics.
    """
    if not claim_tokens:
        return 1.0  # no content to corroborate — treated as neutral/supported
    uni_hits = sum(1 for t in claim_tokens if t in source_unigrams)
    uni = uni_hits / len(claim_tokens)

    bigs = _bigrams(claim_tokens)
    if bigs:
        big_hits = sum(1 for b in bigs if b in source_bigrams)
        big = big_hits / len(bigs)
        # Lean on unigrams (the primary signal); bigrams sharpen the verdict.
        return 0.75 * uni + 0.25 * big
    return uni


def alibi(answer: str, sources: str, threshold: float = 0.5) -> list[dict]:
    """Check each claim in ``answer`` against ``sources``.

    Returns one dict per claim: ``{"claim", "score", "supported"}``. A claim is
    SUPPORTED when its lexical support score meets ``threshold``. Claims with no
    content words (e.g. "Sure!") score 1.0 and pass — there's nothing to ground.

    Pure and deterministic: same inputs, same output, no network, no model.
    """
    source_tokens = _tokenize(sources)
    source_unigrams = set(source_tokens)
    source_bigrams = set(_bigrams(source_tokens))

    results: list[dict] = []
    for claim in split_sentences(answer):
        tokens = _tokenize(claim)
        score = _support_score(tokens, source_unigrams, source_bigrams)
        results.append(
            {
                "claim": claim,
                "score": round(score, 3),
                "supported": score >= threshold,
            }
        )
    return results


def _format(result: dict) -> str:
    mark = "SUPPORTED  " if result["supported"] else "UNSUPPORTED"
    return f"{mark} [{result['score']:.2f}] {result['claim']}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="alibi", description="does the story check out?")
    p.add_argument("files", nargs="*", help="answer file(s) to check (default: stdin)")
    p.add_argument(
        "--source",
        action="append",
        default=[],
        metavar="FILE",
        help="a source/ground-truth file (repeatable)",
    )
    p.add_argument(
        "--source-text",
        action="append",
        default=[],
        metavar="TEXT",
        help="source text passed inline (repeatable)",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="support cutoff; below this a claim is UNSUPPORTED (default: 0.5)",
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="print nothing; exit 1 if any claim is unsupported (gates a pipeline)",
    )
    p.add_argument(
        "--report",
        action="store_true",
        help="print only the unsupported claims to stdout; exit 0",
    )
    p.add_argument("--json", action="store_true", help="emit structured per-claim JSON results")
    args = p.parse_args(argv)

    answer = (
        "".join(open(f, encoding="utf-8").read() for f in args.files)
        if args.files
        else sys.stdin.read()
    )

    source_parts = [open(f, encoding="utf-8").read() for f in args.source]
    source_parts += list(args.source_text)
    if not source_parts:
        sys.stderr.write('[alibi] no sources given — use --source FILE or --source-text "..."\n')
        return 2
    sources = "\n".join(source_parts)

    results = alibi(answer, sources, threshold=args.threshold)
    unsupported = [r for r in results if not r["supported"]]

    if args.json:
        sys.stdout.write(json.dumps(results, indent=2) + "\n")
        return 1 if (args.check and unsupported) else 0

    if args.check:
        return 1 if unsupported else 0

    if args.report:
        if unsupported:
            sys.stdout.write("\n".join(_format(r) for r in unsupported) + "\n")
        else:
            sys.stdout.write("clean — every claim checks out\n")
        return 0

    # Default: per-claim verdict report to stdout, summary to stderr.
    for r in results:
        sys.stdout.write(_format(r) + "\n")
    supported = len(results) - len(unsupported)
    sys.stderr.write(
        f"[alibi] {len(results)} claim(s): {supported} supported, {len(unsupported)} unsupported\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
