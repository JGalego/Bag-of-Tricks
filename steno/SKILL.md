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
steno r app.py --run          # send it to an LLM (auto-detects the provider)
steno r app.py --run --provider gemini   # or name a provider/--model
```

`--run` works with any of `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` /
`GEMINI_API_KEY`, plus that provider's SDK. It auto-detects the provider from the key
that's set; override with `--provider {anthropic,openai,gemini}` and `--model`.

Otherwise run it from the bag-of-tricks repo: `python3 steno/steno.py`.

Input resolves as: `--text`, then file arg(s), then literal text, then stdin;
`c` and `pr` fall back to `git diff`. Add aliases in `~/.config/steno/aliases.txt`
(or `$STENO_ALIASES`): one `alias  prompt text {input}` per line.

## Output

In Claude Code you *are* the model steno would call, so don't stop at the
expanded prompt — answer it and deliver that result (the commit message, the
review, the regex). Don't narrate running `steno`, no preamble, no closing note.
Hand back the bare expanded prompt only when the user explicitly wants the
prompt text itself to pipe or paste elsewhere. (Standalone in a terminal,
`--run` is what sends it to the API; in chat that step is just you answering.)

See `README.md` in this folder for the full reference.
