#!/usr/bin/env python3
"""combo — pull the whole routine.

A magician's *combo* is several tricks run as one move. This is that, for the
bag: it chains tricks into a single pipeline so the output of one flows straight
into the next, and you call the whole thing once.

Every trick in the bag is a `stdin->stdout` program, so the composition layer
isn't a new framework — it's the Unix pipe. combo just wires the stages together,
forwards each stage's summary on stderr, and stops the moment a stage fails (so a
gate like `--check` aborts the routine and propagates its exit code).

Tricks come in shapes (see `--list`):

  * filter    — emits transformed text on stdout; chains in the middle of a
                routine. e.g. frisk, launder, salvage, mole, deadpan.
  * analyzer  — emits a report/verdict; a terminal stage (a sink), not a
                pass-through. e.g. tell, fold, alibi, mugshot, bluff, tollbooth.
  * gate mode — not a trick but a *mode* several tricks share (`--check`,
                `--max`): print nothing, exit non-zero to abort the routine.

    # redact, then wash the bytes, then strip the personality — one call
    combo "frisk --pii | launder | deadpan" < draft.md

    # bare names (no per-stage flags) is the same as quoting each one
    combo frisk launder deadpan < draft.md

    # a filter then an analyzer sink: clean it, then score how AI it still reads
    combo "launder | tell --score" < draft.md

    # gate a routine: refuse to continue if a secret is present
    combo "frisk --check | launder" < draft.md && echo "shipped clean"

Per-stage flags require the quoted pipe-string form ("a --x | b"); the bare-list
form (a b c) is names only, because combo can't tell whose flag is whose.
"""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

# Shape of each trick, for `--list`. (shape, has_gate_mode). This is a display
# aid, not a constraint — combo will happily chain anything that reads stdin and
# writes stdout; the shapes just tell you which stages pass text through (filter)
# and which are terminal sinks (analyzer).
SHAPES: dict[str, tuple[str, bool]] = {
    "launder": ("filter", True),
    "frisk": ("filter", True),
    "salvage": ("filter", False),
    "mole": ("filter", True),
    "deadpan": ("filter", False),
    "steno": ("filter", False),
    "tell": ("analyzer", True),
    "fold": ("analyzer", True),
    "alibi": ("analyzer", True),
    "mugshot": ("analyzer", False),
    "bluff": ("analyzer", False),
    "tollbooth": ("analyzer", False),
    "grill": ("analyzer", False),
    "strawman": ("analyzer", False),
    "lineup": ("analyzer", False),
    "interrobang": ("analyzer", True),
    "snitch": ("analyzer", False),
}


def repo_root() -> Path:
    """The bag's root — the parent of this trick's folder.

    Works in place (combo/combo.py) and after install, where ~/.local/bin/combo
    is a symlink we resolve back to the real file in the repo.
    """
    return Path(__file__).resolve().parent.parent


def parse_pipeline(tokens: list[str]) -> list[list[str]]:
    """Turn positional tokens into a list of stages, each a [cmd, *args] list.

    Two accepted forms:
      * pipe-string: one (quoted) arg containing '|', e.g. "frisk --pii | launder"
        -> split on '|', shlex each piece (per-stage flags allowed).
      * bare list:   no '|' present, e.g. frisk launder deadpan
        -> each token is its own single-word stage (names only).
    """
    spec = " ".join(tokens)
    if "|" in spec:
        stages = [shlex.split(piece) for piece in spec.split("|")]
    else:
        stages = [[tok] for tok in tokens]
    return [s for s in stages if s]


def resolve(name: str) -> list[str] | None:
    """Resolve a stage command to an argv prefix, or None if unknown.

    Prefer the sibling trick in the repo (works before install); fall back to a
    command of that name on PATH (works after install / for arbitrary filters).
    """
    cand = repo_root() / name / f"{name}.py"
    if cand.exists():
        return [sys.executable, str(cand)]
    found = shutil.which(name)
    if found:
        return [found]
    return None


def list_tricks() -> int:
    """Print the tricks combo can find, tagged by shape."""
    root = repo_root()
    found = sorted(
        p.parent.name
        for p in root.glob("*/*.py")
        if p.stem == p.parent.name and p.parent.name != "combo"
    )
    if not found:
        print("no sibling tricks found (run combo from the bag, or use PATH names)")
        return 0
    width = max(len(n) for n in found)
    print("\n  tricks combo can chain (shape · gate?):\n")
    for n in found:
        shape, gate = SHAPES.get(n, ("?", False))
        tag = f"{shape}{' +gate' if gate else ''}"
        print(f"  {n.ljust(width)}  {tag}")
    print(
        "\n  filter   = emits text, chains in the middle"
        "\n  analyzer = emits a report/verdict, a terminal sink"
        "\n  +gate    = also has a --check/--max mode that aborts the routine\n"
    )
    return 0


def run_pipeline(stages: list[list[str]], data: bytes, *, verbose: bool) -> tuple[int, bytes]:
    """Feed `data` through each stage; return (exit_code, final_stdout).

    stdout of stage N becomes stdin of stage N+1. Each stage's stderr is
    forwarded immediately (that's where the tricks put their summaries). A stage
    that exits non-zero stops the routine and its code propagates — that's how a
    gate aborts.
    """
    for stage in stages:
        prefix = resolve(stage[0])
        if prefix is None:
            sys.stderr.write(
                f"[combo] unknown trick: {stage[0]} (not a sibling trick, not on PATH)\n"
            )
            return 127, data
        cmd = prefix + stage[1:]
        if verbose:
            sys.stderr.write(f"[combo] {' '.join(stage)}\n")
        proc = subprocess.run(cmd, input=data, capture_output=True)
        if proc.stderr:
            sys.stderr.buffer.write(proc.stderr)
        if proc.returncode != 0:
            return proc.returncode, proc.stdout
        data = proc.stdout
    return 0, data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="combo",
        description="pull the whole routine — chain tricks into one pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            '  combo "frisk --pii | launder | deadpan" < draft.md\n'
            "  combo frisk launder deadpan < draft.md\n"
            '  combo "frisk --check | launder" < draft.md && echo clean\n'
        ),
    )
    parser.add_argument(
        "stages",
        nargs="*",
        help='pipeline: a quoted "a --x | b | c" string, or bare names a b c',
    )
    parser.add_argument(
        "-i", "--input", metavar="FILE", help="read initial input from FILE (default: stdin)"
    )
    parser.add_argument(
        "-l", "--list", action="store_true", help="list chainable tricks and their shapes"
    )
    parser.add_argument(
        "-n", "--dry-run", action="store_true", help="print the resolved routine; don't run it"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="echo each stage to stderr as it runs"
    )
    args = parser.parse_args(argv)

    if args.list:
        return list_tricks()

    stages = parse_pipeline(args.stages)
    if not stages:
        parser.error("no pipeline given (try: combo frisk launder, or combo --list)")

    if args.dry_run:
        print("routine:")
        for i, stage in enumerate(stages, 1):
            prefix = resolve(stage[0])
            where = " ".join(prefix) if prefix else "UNKNOWN"
            print(f"  {i}. {' '.join(stage)}   ->  {where} {' '.join(stage[1:])}".rstrip())
        return 0

    if args.input:
        data = Path(args.input).read_bytes()
    else:
        data = sys.stdin.buffer.read()

    code, out = run_pipeline(stages, data, verbose=args.verbose)
    if out:
        sys.stdout.buffer.write(out)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
