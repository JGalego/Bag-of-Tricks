#!/usr/bin/env python3
"""salvage — rip the JSON out of the chatter.

You asked for JSON. You got a paragraph of preamble, a ```json fence,
a trailing comma, a stray `True`, and a closing "Let me know if…".
`salvage` is a stdin->stdout filter that locates the first JSON value
in chatty LLM output, repairs the usual damage, and emits clean JSON.

    echo 'Sure! ```json\\n{"ok": True,}\\n```' | salvage.py
    -> {"ok": true}  (pretty-printed)

    salvage.py --compact reply.txt
"""

from __future__ import annotations

import argparse
import json
import re
import sys

# --- locate ---------------------------------------------------------------

_FENCE = re.compile(r"```(?:json|json5|jsonc)?\s*\n?(.*?)```|~~~(?:json)?\s*\n?(.*?)~~~", re.DOTALL)

_SMART_QUOTES = {
    "“": '"',  # left double
    "”": '"',  # right double
    "‘": "'",  # left single
    "’": "'",  # right single
}


def _strip_fences(text: str) -> str:
    """Return the contents of the first markdown code fence, or the text as-is."""
    m = _FENCE.search(text)
    if m:
        return m.group(1) if m.group(1) is not None else m.group(2)
    return text


def find_json(text: str) -> str:
    """Locate the first JSON value and return its balanced substring.

    Strips markdown code fences, then scans for the first `{` or `[` and
    returns the substring through its matching close brace/bracket. String
    literals (and their backslash escapes) are tracked so braces or brackets
    inside strings do not throw off the balance count.
    """
    src = _strip_fences(text)

    start = -1
    for i, ch in enumerate(src):
        if ch in "{[":
            start = i
            break
    if start < 0:
        raise ValueError("no salvageable JSON")

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(src)):
        ch = src[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]

    raise ValueError("no salvageable JSON")


# --- repair ---------------------------------------------------------------

_LINE_COMMENT = re.compile(r"//[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_PY_LITERAL = re.compile(r"\b(True|False|None)\b")
_PY_MAP = {"True": "true", "False": "false", "None": "null"}


def _apply_outside_strings(text: str, fn) -> str:
    """Run `fn` on the non-string spans of `text`, leaving string literals alone."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            # consume a full string literal, honoring escapes
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    j += 1
                    break
                j += 1
            out.append(text[i:j])
            i = j
        else:
            j = i
            while j < n and text[j] != '"':
                j += 1
            out.append(fn(text[i:j]))
            i = j
    return "".join(out)


def _repair(text: str) -> str:
    """Clean common LLM JSON damage before json.loads."""
    # Smart quotes -> straight quotes (do this first; affects string boundaries).
    for smart, straight in _SMART_QUOTES.items():
        text = text.replace(smart, straight)

    def scrub(span: str) -> str:
        span = _BLOCK_COMMENT.sub("", span)
        span = _LINE_COMMENT.sub("", span)
        span = _PY_LITERAL.sub(lambda m: _PY_MAP[m.group(1)], span)
        return span

    text = _apply_outside_strings(text, scrub)
    # Trailing commas can be removed globally; commas inside strings before a
    # literal } or ] are vanishingly rare and the regex requires the bracket.
    text = _TRAILING_COMMA.sub(r"\1", text)
    return text


def salvage(text: str, indent: int | None = 2) -> str:
    """Extract, repair, and re-serialize the first JSON value in `text`.

    Raises ValueError("no salvageable JSON") if no valid JSON can be recovered.
    """
    candidate = find_json(text)
    repaired = _repair(candidate)
    try:
        value = json.loads(repaired)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("no salvageable JSON") from exc
    if indent is None:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return json.dumps(value, indent=indent, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="salvage", description="rip the JSON out of the chatter.")
    p.add_argument("files", nargs="*", help="files to read (default: stdin)")
    p.add_argument(
        "-c",
        "--compact",
        action="store_true",
        help="emit one-line JSON (indent=None)",
    )
    p.add_argument(
        "--indent",
        type=int,
        default=2,
        help="indent width for pretty output (default: 2)",
    )
    p.add_argument(
        "--extract-only",
        action="store_true",
        help="locate the JSON substring but do NOT repair or reformat it",
    )
    args = p.parse_args(argv)

    if args.files:
        raw = "".join(open(f, encoding="utf-8").read() for f in args.files)
    else:
        raw = sys.stdin.read()

    indent = None if args.compact else args.indent

    try:
        if args.extract_only:
            out = find_json(raw)
        else:
            out = salvage(raw, indent=indent)
    except ValueError as exc:
        sys.stderr.write(f"[salvage] {exc}\n")
        return 1

    sys.stdout.write(out + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
