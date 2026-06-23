#!/usr/bin/env python3
"""interrobang ‽ — make it ask before it acts.

The default LLM reflex is to be helpful by answering immediately — which means
guessing when a request is underspecified. interrobang flips that: when the
ask is ambiguous, fire ONE sharp clarifying question first.

Two modes, zero dependencies:

    interrobang.py prompt
        Print the system-prompt addendum that installs the reflex flip.
        Prepend it to your agent's system prompt.

    interrobang.py check transcript.txt
        Lint an assistant response (or transcript) for places it likely
        GUESSED instead of asking — "I'll assume…", "presumably…",
        "I'll go with…". Heuristic, fast, catches the obvious ones.

The glyph is ‽ (U+203D, the interrobang). That's the whole brand.
"""

from __future__ import annotations

import argparse
import re
import sys

GLYPH = "‽"  # ‽

ADDENDUM = """\
## Ask before you act ‽

When a request is underspecified in a way that changes what you would do,
ask ONE sharp clarifying question before acting — do not guess.

- A choice changes the outcome and you can't infer it from context → ask.
- The request is missing a fact you need and can't safely default → ask.
- The action is hard to reverse (deletes, sends, deploys, spends) and the
  scope is unclear → ask.

But do NOT ask when:
- The answer is obvious from context, the codebase, or convention.
- There's a sane default and the cost of guessing wrong is low → pick the
  default, state it in one line, and proceed.
- You'd be asking just to confirm something the user already made clear.

Ask exactly ONE question — the one whose answer unblocks the most. Make it
specific and answerable in a sentence; offer the likely options if you can.
Then stop and wait. One sharp question beats five paragraphs of assumptions.
"""

# Phrases that usually mean "I guessed instead of asking."
_GUESS_PATTERNS = [
    r"\bi'?ll assume\b",
    r"\bi'?ll go with\b",
    r"\bi'?ll just\b",
    r"\bassuming (?:that |you )",
    r"\bi'?m assuming\b",
    r"\bpresumably\b",
    r"\bi'?ll take it that\b",
    r"\bi'?ll interpret (?:this|that|it) as\b",
    r"\blikely you (?:mean|want)\b",
    r"\bi'?ll guess\b",
    r"\bdefaulting to\b",
    r"\bif (?:i|we) had to guess\b",
    r"\bi'?ll proceed (?:as if|assuming)\b",
]
_GUESS_RE = [re.compile(p, re.IGNORECASE) for p in _GUESS_PATTERNS]

_C = {
    "yellow": "\033[33m",
    "green": "\033[32m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "reset": "\033[0m",
}


def _c(name: str, s: str) -> str:
    return s if not sys.stdout.isatty() else f"{_C[name]}{s}{_C['reset']}"


def lint(text: str) -> list[tuple[int, str, str]]:
    """Return (line_no, matched_phrase, line) for likely guesses."""
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        for rx in _GUESS_RE:
            m = rx.search(line)
            if m:
                hits.append((i, m.group(0), line.strip()))
                break
    return hits


def cmd_prompt() -> int:
    sys.stdout.write(ADDENDUM)
    return 0


def cmd_check(path: str | None) -> int:
    if path:
        text = open(path, encoding="utf-8").read()
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        print("nothing to check. pass a file or pipe text in.", file=sys.stderr)
        return 2

    hits = lint(text)
    asked = text.count("?")
    if not hits:
        print(
            _c("green", f"{GLYPH} no obvious guesses found ({asked} question mark(s) in the text).")
        )
        return 0

    print(
        _c(
            "bold",
            _c("yellow", f"{GLYPH} {len(hits)} likely guess(es) — should it have asked instead?\n"),
        )
    )
    for line_no, phrase, line in hits:
        print(f"  {_c('dim', f'L{line_no}')}  …{_c('yellow', phrase)}…")
        print(f"        {line}")
    print(_c("dim", f"\n({asked} question mark(s) total — did it ask, or just assume?)"))
    # non-zero so it can gate a review
    return 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="interrobang",
        description="make it ask before it acts. ‽",
    )
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("prompt", help="print the system-prompt addendum")
    c = sub.add_parser("check", help="lint text for guesses-instead-of-questions")
    c.add_argument("file", nargs="?", help="file to check (default: stdin)")
    args = p.parse_args(argv)

    if args.cmd == "prompt":
        return cmd_prompt()
    if args.cmd == "check":
        return cmd_check(args.file)
    p.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
