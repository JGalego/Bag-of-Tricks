---
name: lineup
description: Run one prompt across multiple models and compare the answers side by side. Use for model selection, spotting disagreement between models, or sanity-checking an answer against what other models say. Fans the same prompt out to an opus/sonnet/haiku lineup (or any model ids you name) and lays the responses out labeled, so you can pick the best one or spot the odd one out.
---

# lineup

**same prompt, the whole lineup.**

lineup sends one prompt to several models at once and stands their answers next
to each other, each clearly labeled, so you can pick the best one — or spot the
suspect that doesn't match the others.

## When to use

- "Which model should I use for this prompt?" — run the lineup, compare.
- "Do the models agree on this?" — disagreement is the signal.
- "Is this answer right?" — put it next to two other models and look.
- A quick model bake-off before committing a prompt to one model.

## Rules

1. **One prompt, the whole lineup.** Every model in the lineup gets the *exact*
   same prompt, verbatim — no per-model tweaking. A fair lineup is the point.
2. **Label every suspect.** Each answer is printed under its model id. Never
   merge or anonymize them — the whole value is knowing who said what.
3. **One failure doesn't spoil the lineup.** If a model errors, it's labeled as
   errored and the rest still show. Only an all-fail run is a failure.
4. **You're the witness.** lineup lays the answers out; it doesn't tell you who
   did it. Read them yourself — or pass `--judge MODEL` to ask one model to pick.
5. **Pick a sensible lineup.** Default is an opus + a sonnet + a haiku tier. Name
   your own with `--models a,b,c` when you want a specific comparison.

## What lineup is NOT

- It is **not** a benchmark or an eval harness. It's a parade you walk past
  once, not a scored leaderboard you run overnight.
- It is **not** an ensemble that merges answers into one. It keeps them separate
  on purpose — the disagreement is the information.
- It is **not** a judge by default. With no `--judge`, it shows; it doesn't pick.

## Example

Dry-run plan (no API call, no key — just shows who'd be in the lineup):

```
$ echo "Explain TCP in one sentence." | lineup --dry-run

lineup plan — 1 prompt, 3 model(s) in the parade:

prompt:
  | Explain TCP in one sentence.

would be sent — verbatim — to each of:
  • claude-opus-4-8
  • claude-sonnet-4-6
  • claude-haiku-4-5
```

A real run lines the answers up, each under its model id:

```
── claude-opus-4-8 ───────────────────────────────────────
TCP is a connection-oriented protocol that delivers an ordered, reliable
byte stream by acknowledging and retransmitting lost segments.
  [tokens: in=14 out=31]

── claude-sonnet-4-6 ─────────────────────────────────────
TCP reliably delivers an ordered stream of bytes between two hosts...
  [tokens: in=14 out=27]

── claude-haiku-4-5 ──────────────────────────────────────
TCP is a protocol that makes sure data arrives in order and intact.
  [tokens: in=14 out=18]

3/3 answered.
```

## Output

Deliver the lineup itself — each answer under its model id, as laid out — not a
narration of running it. Don't explain that you ran `lineup.py`. If asked to
pick, give the pick in one line; otherwise let the answers stand. No preamble, no
closing synthesis the user didn't ask for.

## Companion tool

`lineup.py` in this folder runs the fan-out mechanically. Pipe or pass a prompt
(`lineup.py --prompt "..."`), set the lineup with `--models a,b,c`, preview
without spending a token (`lineup.py --dry-run`), or ask a model to pick the
winner (`lineup.py --judge claude-opus-4-8`). A real run needs
`pip install anthropic` and `ANTHROPIC_API_KEY`; `--dry-run` needs neither.
