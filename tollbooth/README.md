<p align="center">
  <img src="logo.png" alt="tollbooth" width="420">
</p>

**know the bill before the bill.** you wouldn't merge onto a toll road without
glancing at the rate sign. tollbooth is that sign for your prompts — it counts
the tokens and tots up the dollars *before* you send anything upstream.

It comes in two halves:

- **`SKILL.md`** — a [Claude Code / agent skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
  for when you want to size a request, compare models, or sanity-check a budget.
- **`tollbooth.py`** — a zero-dependency CLI that reads text (stdin or files),
  counts input tokens, and prints a per-model cost table.

Tokens are counted with [`tiktoken`](https://github.com/openai/tiktoken) when
it's installed, and with a deterministic, monotonic heuristic when it isn't —
so it runs anywhere with nothing but the standard library.

## the meter

```bash
# pipe a prompt, see input cost per model
echo "summarize this report and flag anything odd" | python3 tollbooth.py

# a real file, with an assumed completion length
python3 tollbooth.py prompt.txt --out 800

# one model only
python3 tollbooth.py prompt.txt --model claude-opus-4-8

# just the number
python3 tollbooth.py prompt.txt --tokens-only
# -> 412

# the rate sign itself
python3 tollbooth.py --list-models

# structured output for scripts
python3 tollbooth.py prompt.txt --out 500 --json
```

## install

From the repo root, [`just`](https://github.com/casey/just) symlinks the CLI onto
your `PATH` and the [skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
into `~/.claude/skills/`:

```bash
just install tollbooth
echo "hello there" | tollbooth --tokens-only
```

Or run it in place: `python3 tollbooth.py`. Want sharper counts?
`pip install tiktoken` and tollbooth picks it up automatically.

## the prices are approximate

The dollar figures come from a `PRICES` table near the top of `tollbooth.py`,
in USD per 1,000,000 tokens. They're **ballpark, current-ish, and editable** —
providers change rates and ship new models faster than any README can keep up.
Open the file, tweak the numbers, add your own model. The math is exact; the
rate sign is yours to repaint.
