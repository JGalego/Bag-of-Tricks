#!/usr/bin/env python3
"""deadpan — the answer. nothing else.

Strips an LLM response of personality: openers ("Certainly!"), hedges
("I think maybe"), sign-offs ("Hope this helps!"), self-reference
("As an AI..."), and emoji. caveman makes it *short*; deadpan makes it
*shut up*.

Reads text from stdin (or files) and writes the deadpan version to stdout.
Zero dependencies. Code fences are left untouched — we trim the prose, not
your snippets.

    echo "Certainly! Here's the answer: 42 🎉 Hope this helps!" | deadpan.py
    -> Here's the answer: 42

    deadpan.py --level ultra notes.md --stats
"""

from __future__ import annotations

import argparse
import re
import sys

# --- patterns -------------------------------------------------------------
# Each entry is a (compiled regex, replacement) applied to non-code text.
# Order matters: openers/sign-offs first, then inline hedges.

_OPENERS = [
    r"certainly[!,. ]*",
    r"sure[!,. ]*",
    r"absolutely[!,. ]*",
    r"of course[!,. ]*",
    r"great question[!,. ]*",
    r"good question[!,. ]*",
    r"i'?d be happy to help[!,. ]*",
    r"i'?d be glad to[^.!\n]*[.!]?\s*",
    r"happy to help[!,. ]*",
    r"let'?s dive in[!,. ]*",
    r"let me help you[^.!\n]*[.!]?\s*",
    r"thanks for (?:your |the )?(?:question|message)[!,. ]*",
    r"no problem[!,. ]*",
]

_SIGNOFFS = [
    r"\s*i hope (?:this|that) helps[!.]?\s*$",
    r"\s*hope (?:this|that|it) helps[!.]?\s*$",
    r"\s*let me know if (?:you|there)[^.!\n]*[.!]?\s*$",
    r"\s*feel free to (?:ask|reach out)[^.!\n]*[.!]?\s*$",
    r"\s*happy to (?:help|clarify)[^.!\n]*[.!]?\s*$",
    r"\s*is there anything else[^?\n]*\??\s*$",
    r"\s*good luck[!.]?\s*$",
]

# Sycophancy / self-reference — killed at any level.
_SELF = [
    r"as an ai(?: language model)?[^.,!\n]*[.,]?\s*",
    r"i'?m just an ai[^.,!\n]*[.,]?\s*",
    r"as a large language model[^.,!\n]*[.,]?\s*",
]

# Inline hedges — softeners that add nothing. Removed at full/ultra.
_HEDGES = [
    r"\bi think (?:that )?\b",
    r"\bi believe (?:that )?\b",
    r"\bin my opinion,?\s*",
    r"\bit'?s worth noting that\b",
    r"\bit'?s important to (?:note|remember|understand) that\b",
    r"\bplease note that\b",
    r"\bkeep in mind that\b",
    r"\bbasically,?\s*",
    r"\bessentially,?\s*",
    r"\bactually,?\s*",
    r"\bjust\b",
    r"\bvery\b",
    r"\breally\b",
    r"\bsort of\b",
    r"\bkind of\b",
    r"\bperhaps\b",
    r"\bmaybe\b",
    r"\bsimply\b",
]

# Emoji + decorative symbols. Removed at every level above "lite".
_EMOJI = re.compile(
    "[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f000-\U0001f0ff"
    "\U00002190-\U000021ff\U00002b00-\U00002bff\U0000fe0f\U0000200d]+"
)

LEVELS = ("lite", "full", "ultra")


def _compile(patterns: list[str], flags: int = re.IGNORECASE) -> list[re.Pattern]:
    return [re.compile(p, flags) for p in patterns]


_OPENERS_RE = _compile([r"^\s*(?:" + p + r")" for p in _OPENERS])
_SIGNOFFS_RE = _compile(_SIGNOFFS, re.IGNORECASE | re.MULTILINE)
_SELF_RE = _compile(_SELF)
_HEDGES_RE = _compile(_HEDGES)


def _deadpan_prose(text: str, level: str) -> str:
    """Apply the strip to a chunk of prose (never to code)."""
    # Self-reference and emoji go at every level.
    for rx in _SELF_RE:
        text = rx.sub("", text)
    if level != "lite":
        text = _EMOJI.sub("", text)

    # Openers: strip from the start of the whole chunk and each paragraph.
    for rx in _OPENERS_RE:
        text = rx.sub("", text)

    # Sign-offs: strip from the end.
    for rx in _SIGNOFFS_RE:
        text = rx.sub("", text)

    if level in ("full", "ultra"):
        for rx in _HEDGES_RE:
            text = rx.sub("", text)

    if level == "ultra":
        # collapse blank lines and trailing spaces hard
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)

    # Tidy: fix capitalization after a leading strip, drop double spaces,
    # trim stray leading punctuation left behind.
    text = re.sub(r"^[\s,.:;!-]+", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" +([.,;:!?])", r"\1", text)
    return text


_FENCE = re.compile(r"(```.*?```|~~~.*?~~~|`[^`\n]+`)", re.DOTALL)


def deadpan(text: str, level: str = "full") -> str:
    """Strip prose while preserving fenced/inline code verbatim."""
    out = []
    last = 0
    for m in _FENCE.finditer(text):
        out.append(_deadpan_prose(text[last : m.start()], level))
        out.append(m.group(0))  # code untouched
        last = m.end()
    out.append(_deadpan_prose(text[last:], level))
    result = "".join(out)
    # Capitalize the very first letter if a strip lowercased the opener.
    result = result.lstrip()
    if result:
        result = result[0].upper() + result[1:]
    return result.rstrip() + ("\n" if text.endswith("\n") else "")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="deadpan",
        description="the answer. nothing else.",
    )
    p.add_argument("files", nargs="*", help="files to read (default: stdin)")
    p.add_argument(
        "-l",
        "--level",
        choices=LEVELS,
        default="full",
        help="lite: keep emoji+hedges, drop fluff | full (default) | ultra: also crush whitespace",
    )
    p.add_argument(
        "-s",
        "--stats",
        action="store_true",
        help="print bytes/chars saved to stderr",
    )
    args = p.parse_args(argv)

    if args.files:
        raw = "".join(open(f, encoding="utf-8").read() for f in args.files)
    else:
        raw = sys.stdin.read()

    out = deadpan(raw, args.level)
    sys.stdout.write(out)

    if args.stats:
        before, after = len(raw), len(out)
        saved = before - after
        pct = (saved / before * 100) if before else 0.0
        sys.stderr.write(
            f"\n[deadpan] {before} -> {after} chars  ({saved} cut, {pct:.0f}% quieter)\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
