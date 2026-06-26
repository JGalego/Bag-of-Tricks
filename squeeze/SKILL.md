---
name: squeeze
description: Detect AI-generated text by how it compresses — model prose is more predictable, so it squeezes flatter against a known-AI corpus than against a known-human one (Normalized Compression Distance), after thinkst's zippy. Use to get a fast, word-blind second opinion on whether a passage reads as machine-written, distinct from tell (which reads the words) and mugshot (which names the model). A heuristic with a confidence band, not proof.
---

# squeeze

**put the squeeze on it.**

Model prose is more predictable than human writing. Compress a passage next to a
pile of known-AI text and it folds in tightly; compress it next to human text
and it resists. `squeeze` measures that gap with **Normalized Compression
Distance** and reports which corpus the candidate caves toward. It never reads a
word — it just weighs the bytes.

This is the compression cousin of thinkst's [`zippy`](https://github.com/thinkst/zippy).

## how it reads

- **distance to AI corpus** (`ai_ncd`) — lower means the bytes fold into known-AI
  text tightly: shared clichés, rhythms, scaffolding.
- **distance to human corpus** (`human_ncd`) — lower means it folds into
  idiosyncratic human writing instead.
- **margin** = `human_ncd − ai_ncd`. Positive leans machine, negative leans human.
- **AI-likelihood** 0-100 and a **confidence band** (low/medium/high) from how
  decisively one corpus won, tempered by length.

NCD ≈ 0 means "nearly identical structure", ≈ 1 means "nothing shared". The
absolute numbers run high for short text — what matters is the *gap* between them.

## example

> **Input:** "Certainly! It's important to note that we must delve into this
> rich tapestry. In conclusion, leverage robust, seamless solutions."
>
> **Verdict:** likely AI-generated (low) — ai-ncd 0.82 < human-ncd 0.87.
> The prose folds into the known-AI corpus a little more tightly than the human one.

## Output

Deliver the verdict — the lean, the confidence, and the two distances — not a
narration of running `squeeze.py`. Always carry the hedge: this is a hunch from
how the bytes compress, never proof of authorship. Don't explain the tool; report
what it found and stop.

## when it's unreliable (say so)

- **Short text** (< ~40 words): too little signal; force confidence to low.
- **Code, tables, logs, non-English:** the corpora are English prose; off-genre
  input compresses oddly.
- **Heavily edited AI / AI mimicking a human / a human writing like a bot:** all
  fold the wrong way. Style lies, and so do bytes.
- The built-in corpora are tiny, hand-written caricatures — and the "human" one
  was itself written by an AI imitating casual human prose, which is precisely
  what this tool should distrust. They're a demo, not ground truth. For any
  verdict you mean to rely on, pass larger, *real*, on-domain `--ai-corpus` /
  `--human-corpus` files — more reference text is the single biggest accuracy win.
- **Long inputs are chunked** into corpus-sized windows and length-weighted into
  one verdict (like zippy), so a big file can't swamp the small corpus. On
  off-genre bulk (e.g. the complete works of Shakespeare) expect a weak lean at
  *low* confidence — read that as "don't trust me here," not a real call.

## Companion tool

`squeeze.py` in this folder is a zero-dependency `stdin→stdout` detector (stdlib
`lzma`/`zlib`/`bz2` only).

    echo "…text…" | squeeze.py              # the one-line verdict
    squeeze.py --report draft.md            # full NCD breakdown + bar
    squeeze.py --json draft.md              # the structured verdict
    squeeze.py --algo zlib draft.md         # faster, slightly looser signal
    squeeze.py --ai-corpus ai.txt draft.md  # bring your own reference corpus
    squeeze.py --max 60 draft.md            # exit 1 if AI-likelihood > 60 (CI gate)

## the detection family

Three different lenses on the same question — *did a machine write this?*

- **`tell`** reads the *words* — overused vocabulary, clichés, structure.
- **`mugshot`** matches *style* to a family — *whose* prints are these?
- **`squeeze`** weighs the *bytes* — word-blind, language-agnostic-ish, a fast
  independent second opinion. When `tell` and `squeeze` agree, lean harder.
