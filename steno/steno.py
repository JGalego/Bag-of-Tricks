#!/usr/bin/env python3
"""steno — two letters, and the prompt writes itself.

Mind-numbingly short aliases for the prompts you type all day. `steno r app.py`
expands the alias `r` into a full "review this code…" prompt with the file's
contents spliced in, and prints it — pipe it into any LLM, or pass `--run` to
send it to Claude directly.

    steno r src/app.py            # review  -> prints the expanded prompt
    steno t utils.py              # tests
    steno c                       # commit message from `git diff --cached`
    steno e parser.py | deadpan   # compose with the rest of the bag
    steno rx "match an iso date"  # free-text input instead of a file
    steno r app.py --run          # actually send it to Claude (needs anthropic)
    steno ls                      # list every alias

Add your own in one line: put `alias  the prompt text {input}` lines in
~/.config/steno/aliases.txt (or point $STENO_ALIASES at a file). User aliases
extend and override the built-ins.

Expanding needs nothing but Python 3.9+. `--run` needs:  pip install anthropic
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

MODEL = "claude-opus-4-8"

# alias -> (human name, template). {input} is where the target gets spliced in.
BUILTINS: dict[str, tuple[str, str]] = {
    "e": ("explain", "Explain what the following does, clearly and concisely.\n\n{input}"),
    "r": (
        "review",
        "Review the following code for bugs, edge cases, and clarity issues. "
        "Be specific and cite the relevant lines.\n\n{input}",
    ),
    "t": (
        "tests",
        "Write thorough tests for the following code. Cover edge cases and "
        "failure modes.\n\n{input}",
    ),
    "d": (
        "docstring",
        "Add clear docstrings and comments to the following code. Return the "
        "full updated code.\n\n{input}",
    ),
    "ty": (
        "types",
        "Add precise type annotations to the following code. Return the full "
        "updated code.\n\n{input}",
    ),
    "f": (
        "fix",
        "Find and fix the bugs in the following code. Briefly explain each fix, "
        "then return the corrected code.\n\n{input}",
    ),
    "o": (
        "optimize",
        "Optimize the following code for performance without changing its "
        "behavior. Explain the key changes.\n\n{input}",
    ),
    "s": (
        "simplify",
        "Simplify the following code for readability without changing its "
        "behavior. Return the full updated code.\n\n{input}",
    ),
    "n": (
        "names",
        "Suggest clearer names for the identifiers in the following code, with a "
        "short rationale for each.\n\n{input}",
    ),
    "rx": (
        "regex",
        "Write a regular expression for the following requirement. Explain it and "
        "give a few test cases.\n\n{input}",
    ),
    "sql": (
        "sql",
        "Write a SQL query for the following requirement. State any assumptions.\n\n{input}",
    ),
    "sh": (
        "shell",
        "Write a shell command for the following task. Briefly explain each flag.\n\n{input}",
    ),
    "tl": ("tldr", "Summarize the following in a few tight bullet points.\n\n{input}"),
    "c": (
        "commit",
        "Write a concise commit message (Conventional Commits style) for the "
        "following diff. Output only the message.\n\n{input}",
    ),
    "pr": (
        "pr",
        "Write a pull-request description (summary + bullet points of what "
        "changed and why) for the following diff.\n\n{input}",
    ),
}

# aliases that pull `git diff` when no other input is given
GIT_ALIASES = {"c", "pr"}

_C = {
    "bold": "\033[1m",
    "dim": "\033[2m",
    "cyan": "\033[36m",
    "red": "\033[31m",
    "reset": "\033[0m",
}


def _c(name: str, s: str) -> str:
    return s if not sys.stdout.isatty() else f"{_C[name]}{s}{_C['reset']}"


def _user_aliases_path(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    env = os.environ.get("STENO_ALIASES")
    if env:
        return env
    default = os.path.expanduser("~/.config/steno/aliases.txt")
    return default if os.path.isfile(default) else None


def load_aliases(path: str | None = None) -> dict[str, tuple[str, str]]:
    """Built-ins merged with a user file (one `alias  template…` per line)."""
    aliases = dict(BUILTINS)
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(None, 1)
                if len(parts) != 2:
                    continue
                alias, template = parts[0], parts[1]
                if "{input}" not in template:
                    template += "\n\n{input}"
                aliases[alias] = (alias, template)
    return aliases


def expand(aliases: dict[str, tuple[str, str]], key: str, input_text: str) -> str:
    # .replace, not .format — input may contain literal braces (code!)
    return aliases[key][1].replace("{input}", input_text)


def _git_diff() -> str:
    """Staged diff if any, else the working-tree diff."""
    for args in (["diff", "--cached"], ["diff"]):
        try:
            out = subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout
        except FileNotFoundError:
            return ""
        if out.strip():
            return out
    return ""


def gather_input(rest: list[str], text_opt: str | None) -> str | None:
    """Resolve the target: --text, then file args, then literal args, then stdin."""
    if text_opt is not None:
        return text_opt
    if rest:
        if all(os.path.isfile(a) for a in rest):
            chunks = []
            for p in rest:
                with open(p, encoding="utf-8") as f:
                    chunks.append(f"// {p}\n{f.read()}")
            return "\n\n".join(chunks)
        return " ".join(rest)
    if not sys.stdin.isatty():
        try:
            data = sys.stdin.read()
        except OSError:  # e.g. stdin unavailable / captured
            data = ""
        if data.strip():
            return data
    return None


def cmd_list(aliases: dict[str, tuple[str, str]]) -> int:
    print(_c("bold", "steno aliases (two letters, and the prompt writes itself):\n"))
    for key in sorted(aliases):
        name, template = aliases[key]
        first = template.split("\n", 1)[0]
        snippet = first if len(first) <= 60 else first[:60] + "…"
        print(f"  {_c('cyan', f'{key:>4}')}  {name:<10} {_c('dim', snippet)}")
    print(_c("dim", "\n  steno <alias> <file|text>   ·   add --run to send it to Claude"))
    return 0


def run_prompt(prompt: str, model: str) -> int:
    try:
        import anthropic
    except ImportError:
        print(_c("red", "--run needs the anthropic SDK: pip install anthropic"), file=sys.stderr)
        return 2
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )
    for block in resp.content:
        if block.type == "text":
            print(block.text)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="steno",
        description="two letters, and the prompt writes itself.",
    )
    p.add_argument("alias", nargs="?", help="an alias, or 'ls' to list them")
    p.add_argument("rest", nargs="*", help="file(s) or free text to splice in")
    p.add_argument("--text", help="use this literal text as the input")
    p.add_argument("--run", action="store_true", help="send the prompt to Claude")
    p.add_argument("--model", default=MODEL, help=f"model for --run (default {MODEL})")
    p.add_argument("--aliases", help="path to a user aliases file")
    args = p.parse_args(argv)

    aliases = load_aliases(_user_aliases_path(args.aliases))

    if args.alias in (None, "ls", "list"):
        return cmd_list(aliases)

    if args.alias not in aliases:
        print(_c("red", f"unknown alias: {args.alias}"), file=sys.stderr)
        print("run `steno ls` to see them all.", file=sys.stderr)
        return 2

    input_text = gather_input(args.rest, args.text)
    if input_text is None and args.alias in GIT_ALIASES:
        input_text = _git_diff()
        if not input_text.strip():
            print(
                _c("red", "nothing to diff (no staged or working-tree changes)."), file=sys.stderr
            )
            return 2
    if input_text is None:
        print(
            _c("red", f"alias '{args.alias}' needs input — a file, text, or piped stdin."),
            file=sys.stderr,
        )
        return 2

    prompt = expand(aliases, args.alias, input_text)
    if args.run:
        return run_prompt(prompt, args.model)
    sys.stdout.write(prompt + ("\n" if not prompt.endswith("\n") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
