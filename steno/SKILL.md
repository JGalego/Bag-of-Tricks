---
name: steno
description: Expand a mind-numbingly short alias into a full, well-formed prompt for a common dev task — review, tests, explain, types, optimize, simplify, names, regex, sql, tldr, commit message, PR description — optionally running it against Claude. Use when the user references a steno alias, asks to compose a standard dev prompt quickly, or wants the alias vocabulary.
---

# steno

**two letters, and the prompt writes itself.**

steno turns short aliases into full prompts for the things you ask an LLM all
day, splicing in a file, free text, or `git diff`.

## When to use

- The user names a steno alias (e.g. "steno r app.py", "use steno to review …").
- They want a standard request composed fast: review, tests, explain, types,
  optimize, simplify, names, regex, sql, shell, tldr, commit message (`c`),
  PR description (`pr`).
- To build a prompt to pipe elsewhere, or to run directly with `--run`.

## How to run it

If installed on the `PATH` (via `just install steno`):

```bash
steno ls                      # list every alias (built-in + user)
steno r src/app.py            # review → prints the expanded prompt
steno t utils.py              # tests
steno c                       # commit message from `git diff --cached`
steno rx "match an iso date"  # free-text input instead of a file
steno r app.py --run          # send it to Claude (needs: pip install anthropic)
```

Otherwise run it from the bag-of-tricks repo: `python3 steno/steno.py`.

Input resolves as: `--text`, then file arg(s), then literal text, then stdin;
`c` and `pr` fall back to `git diff`. Add aliases in `~/.config/steno/aliases.txt`
(or `$STENO_ALIASES`): one `alias  prompt text {input}` per line.

See `README.md` in this folder for the full reference.
