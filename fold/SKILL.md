---
name: fold
description: Catch overconfident phrasing in an answer and prefer calibrated uncertainty or honest abstention. Flag absolutes (always/never/guaranteed), bare certainty (definitely/obviously), and false authority (trust me / everyone knows) where the evidence is thin. Use when reviewing a draft answer for unwarranted certainty, or as a reflex to fold a weak hand — say "I don't know" — instead of confabulating a confident wrong answer.
---

# fold

**know when to fold.**

In poker you fold a weak hand instead of bluffing it. This skill is the honest
counterpart to `bluff`: when the evidence is thin, don't dress a guess up in
confident language — fold. When this skill is active, treat unearned certainty
as a tell. A confident wrong answer costs more than an honest "I'm not sure."

## Rules

1. **Weak hand, fold it.** When you don't actually know, say "I don't know" (or
   "I'm not certain", "this is a guess") rather than bluff a plausible-sounding
   answer. Abstaining is a valid, often *better*, move.
2. **Earn your absolutes.** "always", "never", "every", "guaranteed",
   "impossible" claim there are zero exceptions. Use them only when you can name
   the proof. Otherwise downgrade: "usually", "in most cases", "I'm not aware
   of an exception, but…".
3. **Drop the borrowed swagger.** "obviously", "clearly", "definitely",
   "without a doubt", "trust me", "everyone knows" add confidence, not evidence.
   If the claim stands, it stands without them; if it needs them, it's shaky.
4. **Hedge honestly — but don't hedge everything.** Calibrate. State what you're
   sure of plainly, flag what you're not, and don't drown a solid answer in
   reflexive "maybe"s. Over-hedging is its own failure (see below).
5. **A confident wrong answer is the worst outcome.** It's the one the reader
   acts on without checking. When stakes are high and your hand is weak, fold.

## What fold is NOT

- It is **not** a license to hedge everything into mush. Turning every sentence
  into "it might possibly perhaps depend" is *also* miscalibration — and just as
  useless. Fold the weak hands; play the strong ones plainly.
- It is **not** a fact-checker. It flags **tone and stance** — where you're
  *asserting* like you're sure — not whether the underlying claim is true. A
  hedged sentence can still be wrong; a confident one can be right. Fold tells
  you where you're bluffing, not where you're mistaken.

## Example

> **Before:** This will definitely work on every platform — guaranteed, no
> question.
>
> **After:** This should work on the platforms I've tested (Linux, macOS); I
> haven't verified Windows, so confirm there before relying on it.

The facts didn't change. The stance did — from a bluff to a calibrated claim
the reader can actually trust.

## Output

Deliver the folded text, not a report on folding it. Don't narrate running
`fold.py` — the tool card already shows it. Give the calibrated rewrite (or, if
that's what was asked, the flagged tells) and stop. No preamble explaining what
fold does, no closing tally of how many tells it caught.

## Companion tool

`fold.py` in this folder applies these checks mechanically. Pipe a draft
answer through it to tag each overconfidence marker `[FOLD:type]` (`fold.py`),
gate an overclaim check (`fold.py --check`, exits 1 on a hit), list the tells
with offsets (`fold.py --report`), or get a quick confidence-inflation gauge
(`fold.py --score`).

Pairs directly with [`bluff`](../bluff), its counterpart: `fold` catches the
overconfident *phrasing*, `bluff` checks whether the *links and citations* you
cited so confidently actually resolve. Relatives: [`tell`](../tell) flags
AI-tell phrasing, and [`alibi`](../alibi) keeps your claims accountable.
