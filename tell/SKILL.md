---
name: tell
description: Check whether a passage reads as AI-generated and point at the specific tells to rewrite — overused words (delve, tapestry, crucial), cliché phrases ("it's not just X, it's Y", "in conclusion"), em-dash overuse, emoji, rule-of-three lists. Use when you want a diagnosis of why prose sounds like a model wrote it, not a rewrite. Pairs with deadpan: deadpan prevents tells at generation; tell detects them after.
---

# tell

**every AI has a tell.**

A model leaves fingerprints. This skill is for spotting them — reading a passage
and naming the exact words and structures that scream "generated", so they can be
rewritten by hand.

## What counts as a tell

1. **Overused words.** delve, tapestry, testament, realm, navigate, underscore,
   leverage, robust, seamless, crucial, pivotal, multifaceted, nuanced,
   intricate, bustling, vibrant, foster, harness, elevate, unlock, embark,
   landscape, beacon, treasure trove.
2. **Cliché phrases.** "it's not just X, it's Y", "not only … but also",
   "in conclusion", "in summary", "it's worth noting", "in today's fast-paced
   world", "when it comes to", "a testament to", "plays a crucial role",
   "at the end of the day", "the world of", "dive into", "rich tapestry",
   "ever-evolving", "game-changer".
3. **Structural tells.** em-dash overuse, emoji, rule-of-three comma lists
   ("fast, cheap, and reliable"), excessive **bold** runs.

A single tell is noise; a cluster is a confession. Weigh density, not just
presence.

## Example

> **Tell-ridden:** Let's delve into the rich tapestry of modern computing — a
> testament to human ingenuity. It's not just a tool, it's a revolution that
> plays a crucial role in our ever-evolving world.
>
> **Diagnosis:** delve, tapestry, testament, "it's not just X, it's Y",
> "plays a crucial role", "ever-evolving", one em-dash — score ~99/100.
> Rewrite from scratch; nothing here survives.

## Output

Deliver the diagnosis — the tells and the score — not a narration of running
`tell.py`. Don't explain the tool; list what was found and stop. No preamble, no
closing "consider rewriting" unless the user asked what to do about it.

## Companion tool

`tell.py` in this folder scores text mechanically (0-100) and lists every tell
with counts. Use it to diagnose, gate prose in CI (`tell --max 30 draft.md`), or
spot-check your own drafts. It pairs with **deadpan**: deadpan stops the tells at
generation time, tell catches the ones that slipped through.

Two modes and a knob:

- `--llm` — instead of the keyword lexicon, hand the passage to a model that
  reads it the way a human would, catching paraphrased slop and structural
  blandness the word list misses. Same `{score, hits, total}` output, so
  `--score`/`--json`/`--max` still work. `--provider` and `--model` pick the
  backend (defaults from the environment); failure exits 2, no silent fallback.
- `--patterns FILE` (repeatable) — extend the *offline* lexicon with your own
  tells from a JSON file `{"words": [...], "phrases": [[label, regex], ...]}`.
  Honors `$TELL_PATTERNS` (os.pathsep-separated) as a fallback. Your entries
  extend the built-ins; they do not affect `--llm`.
