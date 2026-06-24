---
name: tollbooth
description: Estimate the token count and dollar cost of a prompt or context before sending it. Use to size a request, compare model costs side by side, or sanity-check a budget. Counts tokens with tiktoken when available, else a deterministic heuristic, and prices the request across a small editable table of current-ish models.
---

# tollbooth

**know the bill before the bill.**

tollbooth tells you what a prompt will cost *before* you spend it. Feed it text,
it counts the input tokens and prints a per-model table of estimated dollars —
input-only by default, or include an assumed completion length to see the full
round trip.

## What it does

- Counts input tokens (tiktoken if installed, otherwise a deterministic, monotonic heuristic).
- Prices the request across a handful of models — Claude (Opus / Sonnet / Haiku) and OpenAI GPT (4o / 4o-mini).
- Lets you restrict to one model, assume N output tokens, dump JSON, or print just the token count.

Prices live in an editable `PRICES` table in `tollbooth.py` and are
**approximate** — adjust them when providers move the goalposts.

## Example

```
$ echo "Summarize this 12-page contract and flag risky clauses." | tollbooth.py --out 600
13 input tokens, 600 output

model                 input     output      total
claude-opus-4-8      $0.0002    $0.0450    $0.0452
claude-sonnet-4-6    $0.0000    $0.0090    $0.0090
claude-haiku-4-5     $0.0000    $0.0024    $0.0024
gpt-4o               $0.0000    $0.0060    $0.0060
gpt-4o-mini          $0.0000    $0.0004    $0.0004
```

## Output

Deliver the token count and the per-model cost table, not a narration of running
`tollbooth.py`. Don't explain the tool; show the numbers and stop. No preamble,
no closing take on which model to pick unless asked.

## Companion tool

`tollbooth.py` in this folder does the counting and the arithmetic. Pipe a
prompt or context file through it whenever you want the bill before the bill.
