#!/usr/bin/env python3
"""lineup — same prompt, the whole lineup. see who did it.

Run one prompt across several models and lay the answers side by side so you can
pick the best one (or spot the odd one out). Great for model selection and for
seeing where models disagree — a quick parade you walk past, not a benchmark you
run overnight.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 lineup.py --prompt "Explain TCP in one sentence."
    cat prompt.txt | python3 lineup.py
    python3 lineup.py prompt.txt --models claude-opus-4-8,claude-haiku-4-5
    python3 lineup.py prompt.txt --judge claude-opus-4-8
    python3 lineup.py --prompt "..." --dry-run     # no API key needed

Requires: pip install anthropic   (only for a real run; --dry-run needs nothing)
"""

from __future__ import annotations

import argparse
import concurrent.futures
import sys

# The default lineup: an opus + a sonnet + a haiku tier, mirroring the model
# family strawman uses. Same prompt to each; pick the best or spot the outlier.
DEFAULT_MODELS = [
    "claude-opus-4-8",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
]

MAX_TOKENS = 1024

_C = {
    "bold": "\033[1m",
    "dim": "\033[2m",
    "cyan": "\033[36m",
    "green": "\033[32m",
    "red": "\033[31m",
    "yellow": "\033[33m",
    "reset": "\033[0m",
}


def _c(name: str, s: str) -> str:
    return s if not sys.stdout.isatty() else f"{_C[name]}{s}{_C['reset']}"


def parse_models(raw: str) -> list[str]:
    """Split a comma-separated --models string into a clean list of model ids."""
    return [m.strip() for m in raw.split(",") if m.strip()]


def plan(prompt: str, models: list[str]) -> str:
    """Pure function: render the lineup PLAN — which prompt goes to which models."""
    preview = prompt.strip()
    if len(preview) > 280:
        preview = preview[:277] + "..."
    lines = [
        f"lineup plan — 1 prompt, {len(models)} model(s) in the parade:",
        "",
        "prompt:",
    ]
    lines += [f"  | {line}" for line in preview.splitlines() or [""]]
    lines.append("")
    lines.append("would be sent — verbatim — to each of:")
    for m in models:
        lines.append(f"  • {m}")
    return "\n".join(lines)


def _call_one(client, model: str, prompt: str) -> dict:
    resp = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    usage = getattr(resp, "usage", None)
    return {
        "model": model,
        "text": text,
        "in": getattr(usage, "input_tokens", None),
        "out": getattr(usage, "output_tokens", None),
    }


def _judge(client, model: str, prompt: str, answers: list[dict]) -> str:
    roster = "\n\n".join(f"[{a['model']}]\n{a['text']}" for a in answers if not a.get("error"))
    user = (
        f"ORIGINAL PROMPT:\n{prompt}\n\n"
        f"Here are answers from different models to that prompt:\n\n{roster}\n\n"
        f"Pick the single best answer. Name the model id you picked and explain "
        f"in 2-3 sentences why it beats the others. Be specific and honest."
    )
    resp = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def _print_answer(a: dict) -> None:
    head = f"── {a['model']} "
    head = head + "─" * max(0, 72 - len(head))
    print(_c("bold", _c("cyan", head)))
    if a.get("error"):
        print(_c("red", f"  ! errored: {a['error']}"))
    else:
        body = a["text"].strip() or _c("dim", "(empty response)")
        print(body)
        if a.get("in") is not None or a.get("out") is not None:
            print(_c("dim", f"  [tokens: in={a.get('in')} out={a.get('out')}]"))
    print()


def run(prompt: str, models: list[str], judge: str | None = None) -> int:
    try:
        import anthropic
    except ImportError:
        print(_c("red", "lineup needs the anthropic SDK: pip install anthropic"), file=sys.stderr)
        print(_c("dim", "(or use --dry-run to see the lineup plan)"), file=sys.stderr)
        return 2

    client = anthropic.Anthropic()
    print(_c("bold", f"\nlineup running — same prompt across {len(models)} model(s)…\n"))

    answers: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(models)) as ex:
        futs = {ex.submit(_call_one, client, m, prompt): m for m in models}
        for fut in concurrent.futures.as_completed(futs):
            model = futs[fut]
            try:
                answers.append(fut.result())
            except Exception as e:  # noqa: BLE001
                answers.append({"model": model, "error": str(e)})

    # Keep the lineup in the order the user listed the models.
    order = {m: i for i, m in enumerate(models)}
    answers.sort(key=lambda a: order.get(a["model"], len(models)))

    for a in answers:
        _print_answer(a)

    errored = sum(1 for a in answers if a.get("error"))
    print(_c("dim", f"{len(answers) - errored}/{len(answers)} answered."))

    if judge:
        live = [a for a in answers if not a.get("error")]
        if len(live) < 2:
            print(_c("yellow", "\nnot enough answers to judge (need at least 2)."))
        else:
            print(_c("bold", f"\n── verdict (judge: {judge}) " + "─" * 40))
            try:
                print(_judge(client, judge, prompt, answers))
            except Exception as e:  # noqa: BLE001
                print(_c("red", f"judge errored: {e}"), file=sys.stderr)

    # Non-zero only if every model in the lineup failed.
    return 1 if errored == len(answers) else 0


def dry_run(prompt: str, models: list[str]) -> int:
    print(_c("bold", "\nlineup (dry run — no API call):\n"))
    print(plan(prompt, models))
    print()
    print(_c("dim", "set ANTHROPIC_API_KEY and drop --dry-run to actually run the lineup.\n"))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="lineup",
        description="same prompt, the whole lineup. see who did it.",
    )
    p.add_argument("file", nargs="?", help="prompt file (default: --prompt or stdin)")
    p.add_argument("--prompt", help="the prompt to put in front of the lineup")
    p.add_argument(
        "--models",
        default=",".join(DEFAULT_MODELS),
        help=f"comma-separated model ids (default: {', '.join(DEFAULT_MODELS)})",
    )
    p.add_argument(
        "--judge",
        metavar="MODEL",
        help="after collecting answers, ask this model to pick the best and say why",
    )
    p.add_argument(
        "--dry-run", action="store_true", help="print the lineup plan without calling the API"
    )
    args = p.parse_args(argv)

    models = parse_models(args.models)
    if not models:
        print("no models given — pass --models a,b,c", file=sys.stderr)
        return 2

    # Resolve the prompt: --prompt wins, then a file arg, then stdin.
    if args.prompt is not None:
        prompt = args.prompt
    elif args.file:
        prompt = open(args.file, encoding="utf-8").read()
    elif not sys.stdin.isatty():
        prompt = sys.stdin.read()
    else:
        print(
            "no prompt given. use --prompt, pass a file, or pipe one in. "
            "(--dry-run to just see the plan)",
            file=sys.stderr,
        )
        return 2

    if not prompt.strip():
        print("empty prompt.", file=sys.stderr)
        return 2

    if args.dry_run:
        return dry_run(prompt, models)

    return run(prompt, models, judge=args.judge)


if __name__ == "__main__":
    raise SystemExit(main())
