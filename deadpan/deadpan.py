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

Custom patterns
---------------
Extend the built-in strip lists without editing the source. Pass one or more
``--patterns FILE`` flags (repeatable), or set ``DEADPAN_PATTERNS`` to an
os.pathsep-separated list of paths (used only when no flag is given). Each file
is JSON whose values are lists of regexes appended to the matching built-in
list::

    {
      "openers":  ["here'?s the deal[!,. ]*"],
      "signoffs": ["cheers[!.]?\\\\s*$"],
      "hedges":   ["\\\\bhonestly,?\\\\s*"],
      "self":     ["as your assistant[^.,!\\\\n]*[.,]?\\\\s*"]
    }

Openers are anchored to the start, sign-offs to the end of a sentence, and
hedges/self-reference are stripped inline — same handling as the built-ins.
"""

from __future__ import annotations

import argparse
import json
import os
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

# A sign-off only counts when it *begins* a sentence — at the start of a line or
# right after .!? — so a trigger phrase buried mid-sentence ("I'd be happy to
# help — your key is …") can't let the trailing `[^.!\n]*$` swallow the rest of
# a real sentence. The boundary is prepended at compile time.
_SIGNOFF_BOUNDARY = r"(?:(?<=[.!?\n])|^)\s*"
_SIGNOFFS = [
    r"i hope (?:this|that) helps[!.]?\s*$",
    r"hope (?:this|that|it) helps[!.]?\s*$",
    r"let me know if (?:you|there)[^.!\n]*[.!]?\s*$",
    r"feel free to (?:ask|reach out)[^.!\n]*[.!]?\s*$",
    r"happy to (?:help|clarify)[^.!\n]*[.!]?\s*$",
    r"is there anything else[^?\n]*\??\s*$",
    r"good luck[!.]?\s*$",
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
_EMOJI_CLASS = (
    "[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f000-\U0001f0ff"
    "\U00002190-\U000021ff\U00002b00-\U00002bff\U0000fe0f\U0000200d]"
)
_EMOJI = re.compile(_EMOJI_CLASS + "+")

LEVELS = ("lite", "full", "ultra")


def _compile(patterns: list[str], flags: int = re.IGNORECASE) -> list[re.Pattern]:
    return [re.compile(p, flags) for p in patterns]


def _compile_sets(
    openers: list[str], signoffs: list[str], self_: list[str], hedges: list[str]
) -> dict[str, list[re.Pattern]]:
    """Compile the four pattern lists with their respective anchors/flags."""
    return {
        "openers": _compile([r"^\s*(?:" + p + r")" for p in openers]),
        "signoffs": _compile(
            [_SIGNOFF_BOUNDARY + p for p in signoffs], re.IGNORECASE | re.MULTILINE
        ),
        # Same sign-offs, but anchored to a leading emoji run instead of
        # punctuation — so a trailing "🎉 Hope this helps!" is stripped before
        # emoji removal collapses that emoji to a bare (non-boundary) space.
        "signoffs_emoji": _compile(
            [r"(?:" + _EMOJI_CLASS + r")+\s*" + p for p in signoffs],
            re.IGNORECASE | re.MULTILINE,
        ),
        "self": _compile(self_),
        "hedges": _compile(hedges),
    }


# Built-in compiled lists — the default used when no custom patterns are given.
_BUILTIN_RE = _compile_sets(_OPENERS, _SIGNOFFS, _SELF, _HEDGES)
_OPENERS_RE = _BUILTIN_RE["openers"]
_SIGNOFFS_RE = _BUILTIN_RE["signoffs"]
_SELF_RE = _BUILTIN_RE["self"]
_HEDGES_RE = _BUILTIN_RE["hedges"]

# Env var carrying os.pathsep-separated pattern files when --patterns is absent.
_ENV_VAR = "DEADPAN_PATTERNS"


def _load_patterns(paths: list[str] | None) -> dict[str, list[re.Pattern]]:
    """Load + merge custom strip regexes from JSON, return compiled pattern sets.

    Appends the user regexes to the matching built-in list (``openers``,
    ``signoffs``, ``self``, ``hedges``) and recompiles. When ``paths`` is None,
    the ``DEADPAN_PATTERNS`` env var (os.pathsep-separated) is consulted instead.
    """
    openers = list(_OPENERS)
    signoffs = list(_SIGNOFFS)
    self_ = list(_SELF)
    hedges = list(_HEDGES)

    if paths is None:
        env = os.environ.get(_ENV_VAR, "")
        paths = [p for p in env.split(os.pathsep) if p] if env else []

    for path in paths:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        openers.extend(data.get("openers") or [])
        signoffs.extend(data.get("signoffs") or [])
        self_.extend(data.get("self") or [])
        hedges.extend(data.get("hedges") or [])

    return _compile_sets(openers, signoffs, self_, hedges)


def _deadpan_prose(text: str, level: str, sets: dict[str, list[re.Pattern]]) -> str:
    """Apply the strip to a chunk of prose (never to code)."""
    # Self-reference goes at every level.
    for rx in sets["self"]:
        text = rx.sub("", text)
    if level != "lite":
        # A trailing emoji is often the only separator before a sign-off
        # ("… 42 🎉 Hope this helps!"). Strip the "<emoji> sign-off" as a unit
        # first — before emoji removal erases the boundary the sign-off matcher
        # relies on (it anchors to .!?\n or start-of-line, not a bare space).
        for rx in sets["signoffs_emoji"]:
            text = rx.sub("", text)
        text = _EMOJI.sub("", text)

    # Openers: strip from the start of the whole chunk and each paragraph.
    for rx in sets["openers"]:
        text = rx.sub("", text)

    # Sign-offs: strip from the end.
    for rx in sets["signoffs"]:
        text = rx.sub("", text)

    if level in ("full", "ultra"):
        for rx in sets["hedges"]:
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


def deadpan(
    text: str, level: str = "full", extra: dict[str, list[re.Pattern]] | None = None
) -> str:
    """Strip prose while preserving fenced/inline code verbatim.

    ``extra`` optionally supplies merged compiled pattern sets (built-ins plus
    user regexes from ``_load_patterns``); defaults to the built-in lists so
    existing behavior is unchanged when no patterns are given.
    """
    sets = _BUILTIN_RE if extra is None else extra
    out = []
    last = 0
    for m in _FENCE.finditer(text):
        out.append(_deadpan_prose(text[last : m.start()], level, sets))
        out.append(m.group(0))  # code untouched
        last = m.end()
    out.append(_deadpan_prose(text[last:], level, sets))
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
    p.add_argument(
        "--patterns",
        metavar="FILE",
        action="append",
        help="JSON file of custom openers/signoffs/hedges/self regexes to merge in "
        "(repeatable; falls back to $DEADPAN_PATTERNS when absent)",
    )
    args = p.parse_args(argv)

    if args.files:
        raw = "".join(open(f, encoding="utf-8").read() for f in args.files)
    else:
        raw = sys.stdin.read()

    # Merge custom patterns (built-ins are the base; user entries extend them).
    try:
        extra = _load_patterns(args.patterns)
    except (OSError, ValueError, re.error) as e:
        sys.stderr.write(f"[deadpan] could not load patterns: {e}\n")
        return 2

    out = deadpan(raw, args.level, extra=extra)
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
