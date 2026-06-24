#!/usr/bin/env python3
"""grill — put it in the hot seat.

Hand it an ANSWER (and optionally the original question) and it cross-examines
it: hidden assumptions, missing edge cases, internal contradictions, unsupported
claims, overconfidence, and "what would change your mind?". It generates the
sharp follow-ups that attack the answer's weak points, then (optionally) runs
them against Claude to see whether the answer holds up or cracks under
questioning. The stress-test you run on an answer before you trust it.

Cousin of strawman: strawman red-teams a PROMPT, grill cross-examines an ANSWER.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 grill.py answer.txt
    cat answer.txt | python3 grill.py
    python3 grill.py answer.txt --question "Is this migration safe?"
    python3 grill.py answer.txt --angles assumptions,sources
    python3 grill.py answer.txt --dry-run     # no API key needed

Requires: pip install anthropic   (only for a real run; --dry-run needs nothing)
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys

MODEL = "claude-opus-4-8"

# The interrogation. Each angle is an independent adversarial lens on the answer.
# `probe` is the boilerplate question grill asks under that angle in --dry-run;
# `instruction` is what it tells the model to do under that angle on a real run.
ANGLES: dict[str, dict[str, str]] = {
    "assumptions": {
        "probe": "What unstated assumptions does this answer rely on, and what happens if one is false?",
        "instruction": (
            "Surface the hidden assumptions this answer silently depends on. For "
            "the load-bearing one, ask a pointed question that exposes it and "
            "explain what breaks if the assumption does not hold."
        ),
    },
    "edge-cases": {
        "probe": "Which inputs, scales, or conditions does this answer quietly fail to cover?",
        "instruction": (
            "Find a concrete edge case, boundary, or scale the answer does not "
            "handle. Pose the question that drags it into the light and say why "
            "the answer is incomplete or wrong there."
        ),
    },
    "contradictions": {
        "probe": "Does the answer contradict itself or its own premises anywhere?",
        "instruction": (
            "Hunt for an internal contradiction or tension between claims in the "
            "answer. Quote the two parts that fight each other and ask which one "
            "the author actually means."
        ),
    },
    "sources": {
        "probe": "What's the source? Which claims are asserted but unsupported?",
        "instruction": (
            "Identify the strongest claim asserted without evidence. Ask 'what is "
            "the source?' for it and explain why it should not be taken on faith."
        ),
    },
    "overconfidence": {
        "probe": "Where is the answer more certain than the evidence warrants?",
        "instruction": (
            "Find where the answer is overconfident or miscalibrated — a hedge "
            "missing, a 'definitely' the evidence does not earn. Ask the question "
            "that forces it to state its actual confidence and why."
        ),
    },
    "falsifiability": {
        "probe": "What would change your mind? What evidence would prove this answer wrong?",
        "instruction": (
            "Ask what observation or evidence would make this answer wrong. If "
            "nothing could, say so — an unfalsifiable answer is a red flag, not a "
            "strong one."
        ),
    },
}

VERDICT_ORDER = ["holds", "weak", "shaky", "cracks"]

_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": VERDICT_ORDER},
        "angle": {"type": "string"},
        "question": {"type": "string"},
        "finding": {"type": "string"},
    },
    "required": ["verdict", "angle", "question", "finding"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are a sharp, fair cross-examiner. You are given an ANSWER (and possibly "
    "the original QUESTION it responds to). Your job is to interrogate the answer "
    "from one specific angle: ask the single most penetrating follow-up question "
    "for that angle, then report what it reveals — whether the answer holds up, "
    "is weak, is shaky, or cracks outright under that questioning. Be adversarial "
    "but honest: if the answer genuinely survives this angle, say so (verdict "
    "'holds'). Do not manufacture flaws that aren't there — a clean result is a "
    "real result. Quote the answer where it helps."
)

_C = {
    "red": "\033[31m",
    "yellow": "\033[33m",
    "green": "\033[32m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "cyan": "\033[36m",
    "reset": "\033[0m",
}


def _c(name: str, s: str) -> str:
    return s if not sys.stdout.isatty() else f"{_C[name]}{s}{_C['reset']}"


_VERDICT_COLOR = {"cracks": "red", "shaky": "red", "weak": "yellow", "holds": "green"}


def interrogation_plan(angles: list[str]) -> list[dict[str, str]]:
    """Pure, offline: the questions grill would ask, grouped by angle.

    Returns a list of {"angle", "question"} dicts. No network, no SDK.
    """
    return [{"angle": a, "question": ANGLES[a]["probe"]} for a in angles]


def _run_one(client, model: str, answer: str, question: str, name: str, instruction: str) -> dict:
    ctx = f"ORIGINAL QUESTION:\n{question}\n\n" if question.strip() else ""
    user = (
        f"{ctx}ANSWER UNDER EXAMINATION (between the markers):\n"
        f"<<<ANSWER\n{answer}\nANSWER>>>\n\n"
        f"Interrogation angle: {name}.\n{instruction}\n\n"
        f"Ask your single sharpest follow-up for this angle and report what it reveals."
    )
    resp = client.messages.create(
        model=model,
        max_tokens=4000,
        thinking={"type": "adaptive"},
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": _SCHEMA}},
        system=_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    text = next(b.text for b in resp.content if b.type == "text")
    finding = json.loads(text)
    finding["angle"] = name
    return finding


def _print_finding(f: dict) -> None:
    verdict = f.get("verdict", "holds")
    mark = "✗" if verdict in ("cracks", "shaky") else ("?" if verdict == "weak" else "✓")
    head = f"  {mark} {f['angle']:<15} [{verdict.upper()}]"
    print(_c(_VERDICT_COLOR.get(verdict, "dim"), _c("bold", head)))
    print(f"      {_c('cyan', 'asks:')}    {f.get('question', '')}")
    print(f"      {_c('dim', 'reveals:')} {f.get('finding', '')}")


def _worst(findings: list[dict]) -> str:
    worst = "holds"
    for f in findings:
        v = f.get("verdict", "holds")
        if VERDICT_ORDER.index(v) > VERDICT_ORDER.index(worst):
            worst = v
    return worst


def run(answer: str, question: str, angles: list[str], model: str = MODEL) -> int:
    try:
        import anthropic
    except ImportError:
        print(_c("red", "grill needs the anthropic SDK: pip install anthropic"), file=sys.stderr)
        print(_c("dim", "(or use --dry-run to see the interrogation plan)"), file=sys.stderr)
        return 2

    client = anthropic.Anthropic()
    print(
        _c(
            "bold",
            f"\ngrill is putting the answer in the hot seat "
            f"({len(angles)} angles, model={model})…\n",
        )
    )

    findings: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(angles)) as ex:
        futs = {
            ex.submit(_run_one, client, model, answer, question, n, ANGLES[n]["instruction"]): n
            for n in angles
        }
        for fut in concurrent.futures.as_completed(futs):
            name = futs[fut]
            try:
                findings.append(fut.result())
            except Exception as e:  # noqa: BLE001
                print(_c("red", f"  ! {name} angle errored: {e}"), file=sys.stderr)

    findings.sort(key=lambda f: VERDICT_ORDER.index(f.get("verdict", "holds")), reverse=True)
    print(_c("bold", "── cross-examination " + "─" * 51))
    for f in findings:
        _print_finding(f)

    worst = _worst(findings)
    cracked = sum(1 for f in findings if f.get("verdict") in ("shaky", "cracks"))
    print()
    verdict = f"{cracked}/{len(findings)} angles cracked it. worst: {worst.upper()}"
    print(_c(_VERDICT_COLOR.get(worst, "green"), _c("bold", "verdict: " + verdict)))

    # CI-friendly: fail if the answer cracked or went shaky anywhere.
    return 1 if VERDICT_ORDER.index(worst) >= VERDICT_ORDER.index("shaky") else 0


def dry_run(angles: list[str], question: str = "") -> int:
    print(_c("bold", "\ngrill interrogation plan (dry run — no API call):\n"))
    if question.strip():
        print(_c("dim", f"  re: {question.strip()}\n"))
    for item in interrogation_plan(angles):
        print(_c("cyan", f"  {item['angle']}"))
        print(f"    {item['question']}\n")
    print(_c("dim", "set ANTHROPIC_API_KEY and drop --dry-run to actually grill it.\n"))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="grill",
        description="put it in the hot seat.",
    )
    p.add_argument("file", nargs="?", help="answer file to interrogate (default: stdin)")
    p.add_argument(
        "--question", default="", help="the original question / context the answer responds to"
    )
    p.add_argument(
        "--angles",
        default=",".join(ANGLES),
        help=f"comma-separated subset of: {', '.join(ANGLES)}",
    )
    p.add_argument("--model", default=MODEL, help=f"model id to grill with (default: {MODEL})")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print the interrogation plan without calling the API",
    )
    args = p.parse_args(argv)

    angles = [a.strip() for a in args.angles.split(",") if a.strip()]
    bad = [a for a in angles if a not in ANGLES]
    if bad:
        print(f"unknown angle(s): {', '.join(bad)}", file=sys.stderr)
        print(f"choose from: {', '.join(ANGLES)}", file=sys.stderr)
        return 2

    if args.dry_run:
        return dry_run(angles, args.question)

    if args.file:
        answer = open(args.file, encoding="utf-8").read()
    else:
        if sys.stdin.isatty():
            print(
                "no answer given. pass a file or pipe one in. (--dry-run to just see the plan)",
                file=sys.stderr,
            )
            return 2
        answer = sys.stdin.read()

    if not answer.strip():
        print("empty answer.", file=sys.stderr)
        return 2

    return run(answer, args.question, angles, args.model)


if __name__ == "__main__":
    raise SystemExit(main())
