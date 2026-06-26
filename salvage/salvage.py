#!/usr/bin/env python3
"""salvage — rip the JSON out of the chatter.

You asked for JSON. You got a paragraph of preamble, a ```json fence,
a trailing comma, a stray `True`, and a closing "Let me know if…".
`salvage` is a stdin->stdout filter that locates the first JSON value
in chatty LLM output, repairs the usual damage, and emits clean JSON.

    echo 'Sure! ```json\\n{"ok": True,}\\n```' | salvage.py
    -> {"ok": true}  (pretty-printed)

    salvage.py --compact reply.txt

## Custom patterns

Extend the built-in repair tables with your own JSON file via `--patterns
FILE` (repeatable) or the `SALVAGE_PATTERNS` env var (os.pathsep-separated
paths, used when the flag is absent). User entries MERGE into the built-ins
and override on key collision; built-ins remain the base. Shape::

    {
      "smart_quotes": {"«": "\\"", "»": "\\""},
      "py_literals": {"Nil": "null", "TRUE": "true"}
    }

`smart_quotes` maps any character to its replacement (run before parsing, so
it can fix string boundaries). `py_literals` maps a bare token (matched
outside strings, as a whole word) to its JSON value; the literal regex is
rebuilt from the merged keys so new tokens like `Nil` are recognized.
"""

from __future__ import annotations

import argparse
import json
import os
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


def _load_patterns(paths: list[str]) -> dict:
    """Read pattern JSON files and merge them into one config dict.

    Each file may carry `smart_quotes` and/or `py_literals` objects. Later
    files win on key collision. The result is suitable as the `extra` argument
    to `salvage` / `_repair`.
    """
    merged: dict = {"smart_quotes": {}, "py_literals": {}}
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        for section in ("smart_quotes", "py_literals"):
            entries = data.get(section)
            if entries:
                merged[section].update(entries)
    return merged


def _merge_config(extra: dict | None) -> tuple[dict, dict, re.Pattern]:
    """Combine the built-in tables with `extra` and rebuild the literal regex.

    Returns (smart_quotes, py_map, py_literal_regex). With no extra, returns
    the built-ins unchanged so default behavior is identical.
    """
    if not extra or not (extra.get("smart_quotes") or extra.get("py_literals")):
        return _SMART_QUOTES, _PY_MAP, _PY_LITERAL

    smart = {**_SMART_QUOTES, **extra.get("smart_quotes", {})}
    py_map = {**_PY_MAP, **extra.get("py_literals", {})}
    # Rebuild the alternation from the merged keys (longest first so a token
    # that is a prefix of another doesn't shadow it).
    alternation = "|".join(re.escape(k) for k in sorted(py_map, key=len, reverse=True))
    py_literal = re.compile(rf"\b({alternation})\b")
    return smart, py_map, py_literal


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


def _repair(text: str, extra: dict | None = None) -> str:
    """Clean common LLM JSON damage before json.loads.

    `extra` may carry custom `smart_quotes` / `py_literals` tables that merge
    into the built-ins (see `_load_patterns`).
    """
    smart_quotes, py_map, py_literal = _merge_config(extra)

    # Smart quotes -> straight quotes (do this first; affects string boundaries).
    for smart, straight in smart_quotes.items():
        text = text.replace(smart, straight)

    def scrub(span: str) -> str:
        span = _BLOCK_COMMENT.sub("", span)
        span = _LINE_COMMENT.sub("", span)
        span = py_literal.sub(lambda m: py_map[m.group(1)], span)
        return span

    text = _apply_outside_strings(text, scrub)
    # Trailing commas can be removed globally; commas inside strings before a
    # literal } or ] are vanishingly rare and the regex requires the bracket.
    text = _TRAILING_COMMA.sub(r"\1", text)
    return text


def salvage(text: str, indent: int | None = 2, extra: dict | None = None) -> str:
    """Extract, repair, and re-serialize the first JSON value in `text`.

    `extra` optionally extends the built-in repair tables (see `_load_patterns`).
    Raises ValueError("no salvageable JSON") if no valid JSON can be recovered.
    """
    candidate = find_json(text)
    repaired = _repair(candidate, extra=extra)
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
    p.add_argument(
        "--patterns",
        action="append",
        metavar="FILE",
        help="JSON file of custom smart_quotes/py_literals to merge in "
        "(repeatable; falls back to $SALVAGE_PATTERNS)",
    )
    args = p.parse_args(argv)

    pattern_paths = args.patterns
    if not pattern_paths:
        env = os.environ.get("SALVAGE_PATTERNS")
        pattern_paths = env.split(os.pathsep) if env else []

    try:
        extra = _load_patterns([p for p in pattern_paths if p]) if pattern_paths else None
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"[salvage] could not load patterns: {exc}\n")
        return 1

    if args.files:
        raw = "".join(open(f, encoding="utf-8").read() for f in args.files)
    else:
        raw = sys.stdin.read()

    indent = None if args.compact else args.indent

    try:
        if args.extract_only:
            out = find_json(raw)
        else:
            out = salvage(raw, indent=indent, extra=extra)
    except ValueError as exc:
        sys.stderr.write(f"[salvage] {exc}\n")
        return 1

    sys.stdout.write(out + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
