#!/usr/bin/env python3
"""tollbooth — know the bill before the bill.

Estimate the token count and dollar cost of a prompt across LLM models
*before* you send it. Reads text from stdin or files, counts input tokens
(via tiktoken if installed, else a deterministic heuristic), and prints a
small table of cost per model.

    echo "summarize this report" | tollbooth.py
    tollbooth.py prompt.txt --out 800 --model claude-opus-4-8
    tollbooth.py --list-models
"""

from __future__ import annotations

import argparse
import json
import sys

# Optional dependency. If tiktoken is installed we use it for accurate counts;
# otherwise we fall back to a heuristic (see count_tokens). Guarded so ruff and
# pytest pass with zero dependencies installed.
try:
    import tiktoken  # type: ignore
except ImportError:  # pragma: no cover - exercised only when tiktoken absent
    tiktoken = None

# --- pricing --------------------------------------------------------------
# USD per 1,000,000 tokens. APPROXIMATE and EDITABLE — providers change prices
# and add models constantly. Treat these as a starting point and tweak to taste.
# Keys are short, lowercase, provider-agnostic handles.
PRICES: dict[str, dict[str, float]] = {
    # Anthropic Claude (model ids as they ship; prices per 1M tokens)
    "claude-fable-5": {"in": 10.0, "out": 50.0},
    "claude-opus-4-8": {"in": 5.0, "out": 25.0},
    "claude-opus-4-7": {"in": 5.0, "out": 25.0},
    "claude-sonnet-4-6": {"in": 3.0, "out": 15.0},
    "claude-haiku-4-5": {"in": 1.0, "out": 5.0},
    # OpenAI GPT
    "gpt-4o": {"in": 2.50, "out": 10.0},
    "gpt-4o-mini": {"in": 0.15, "out": 0.60},
}


def count_tokens(text: str) -> int:
    """Estimate the number of tokens in *text*.

    If tiktoken is importable, use it (o200k_base, a reasonable modern default;
    falls back to cl100k_base). Otherwise use a heuristic:

        tokens ~= round(max(word_count * 1.3, char_count / 4))

    English text averages ~1.3 tokens per word and ~4 characters per token;
    taking the max keeps the estimate sane for both word-light (code, URLs)
    and word-heavy input. The heuristic is deterministic and monotonic:
    appending text never lowers the estimate.
    """
    if not text:
        return 0

    if tiktoken is not None:  # pragma: no cover - depends on optional dep
        try:
            enc = tiktoken.get_encoding("o200k_base")
        except Exception:
            enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))

    words = len(text.split())
    chars = len(text)
    return round(max(words * 1.3, chars / 4))


def cost(model: str, in_tokens: int, out_tokens: int = 0) -> dict:
    """Compute the cost of a request for *model*.

    Returns a dict with model name, token counts, and USD amounts. Raises
    KeyError (with a helpful message) for unknown models.
    """
    if model not in PRICES:
        known = ", ".join(sorted(PRICES))
        raise KeyError(f"unknown model {model!r}; known models: {known}")
    if in_tokens < 0 or out_tokens < 0:
        raise ValueError("token counts must be non-negative")

    rates = PRICES[model]
    input_usd = in_tokens / 1_000_000 * rates["in"]
    output_usd = out_tokens / 1_000_000 * rates["out"]
    return {
        "model": model,
        "in_tokens": in_tokens,
        "out_tokens": out_tokens,
        "input_usd": input_usd,
        "output_usd": output_usd,
        "total_usd": input_usd + output_usd,
    }


def _read_input(files: list[str]) -> str:
    if files:
        parts = []
        for f in files:
            with open(f, encoding="utf-8") as fh:
                parts.append(fh.read())
        return "".join(parts)
    return sys.stdin.read()


def _fmt_usd(amount: float) -> str:
    # Show enough precision that sub-cent estimates aren't all "$0.00".
    return f"${amount:.4f}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="tollbooth",
        description="know the bill before the bill.",
    )
    p.add_argument("files", nargs="*", help="files to read (default: stdin)")
    p.add_argument("-m", "--model", help="restrict to one model")
    p.add_argument(
        "--out",
        type=int,
        default=0,
        metavar="N",
        help="assume N output/completion tokens in the estimate",
    )
    p.add_argument(
        "--list-models",
        action="store_true",
        help="print known models and their prices, then exit",
    )
    p.add_argument("--json", action="store_true", help="emit structured JSON results")
    p.add_argument(
        "--tokens-only",
        action="store_true",
        help="print just the input token count",
    )
    args = p.parse_args(argv)

    if args.list_models:
        if args.json:
            print(json.dumps(PRICES, indent=2, sort_keys=True))
        else:
            print(f"{'model':<16} {'in $/1M':>10} {'out $/1M':>10}")
            for name in sorted(PRICES):
                r = PRICES[name]
                print(f"{name:<16} {r['in']:>10.2f} {r['out']:>10.2f}")
        return 0

    if args.model and args.model not in PRICES:
        known = ", ".join(sorted(PRICES))
        p.error(f"unknown model {args.model!r}; known models: {known}")

    text = _read_input(args.files)
    in_tokens = count_tokens(text)

    if args.tokens_only:
        print(in_tokens)
        return 0

    models = [args.model] if args.model else sorted(PRICES)
    rows = [cost(m, in_tokens, args.out) for m in models]

    if args.json:
        print(
            json.dumps({"in_tokens": in_tokens, "out_tokens": args.out, "models": rows}, indent=2)
        )
        return 0

    out_note = f", {args.out} output" if args.out else ""
    print(f"{in_tokens} input tokens{out_note}\n")
    print(f"{'model':<16} {'input':>10} {'output':>10} {'total':>10}")
    for row in rows:
        print(
            f"{row['model']:<16} "
            f"{_fmt_usd(row['input_usd']):>10} "
            f"{_fmt_usd(row['output_usd']):>10} "
            f"{_fmt_usd(row['total_usd']):>10}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
