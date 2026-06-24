---
name: launder
description: Wash the mechanical fingerprints out of text — zero-width and invisible characters, smart quotes, em/en dashes, the unicode ellipsis, non-breaking and exotic spaces, soft hyphens — so the bytes read like a human typed them. It scrubs typography, it does NOT rewrite prose (that's the model's job) or detect word-level tells (that's `tell`'s). Use before pasting model output where invisible characters or fancy punctuation would give it away, corrupt a diff, or break a downstream parser.
---

# launder

**wash out the prints.**

A model doesn't just pick suspicious *words* — it leaves suspicious *bytes*.
Zero-width spaces sprinkled mid-word, curly quotes, em-dashes, that one
non-breaking space, the unicode ellipsis. None of it is visible; all of it
marks the text as machine-produced (and some of it is literally watermarking).
This skill is for washing those prints off — touching the typography, never the
words.

launder is the cleanup sibling of `tell`. **`tell` detects the AI smell;
launder washes out the invisible and typographic giveaways.** `tell` reads the
prose and names the overused words; launder scrubs the bytes underneath it.

## Rules

1. **Scrub the invisibles.** Strip zero-width spaces, word joiners, the BOM,
   and soft hyphens. They carry no glyph — only a fingerprint. Delete them.
2. **Straighten the punctuation.** Curly quotes → straight, em-dash → `--`,
   en-dash → `-`, unicode ellipsis → `...`, non-breaking and exotic spaces →
   a plain ASCII space. Normalize the typography to what a keyboard produces.
3. **Don't touch the words.** Re-phrasing, de-clichéing, killing "delve" — that
   is not laundering, that is rewriting, and it is not this skill's job. launder
   changes bytes, never meaning.
4. **Leave clean text alone.** Plain ASCII passes through byte-for-byte. If
   there are no prints to wash, do nothing and say so.
5. **Homoglyphs are opt-in.** Mapping Cyrillic/Greek look-alikes (`а`→`a`,
   `о`→`o`) back to ASCII is lossy — a genuinely Cyrillic word would be
   mangled — so only do it when explicitly asked (`--homoglyphs`).

## What launder is NOT

- It is **not** a paraphraser. It will not reword a sentence, vary your
  vocabulary, or restructure a paragraph. It only normalizes characters.
- It is **not** a `tell` replacement. `tell` finds the word-level tells;
  launder finds the byte-level ones. Run `tell` to know *why* prose reads as
  AI; run launder to remove the *typographic* evidence.
- It is **not** a cloak. Honest note: stripping zero-width characters and
  smart quotes removes formatting artifacts — it does **not** make machine text
  "undetectable" and is not a way to defeat plagiarism or AI-detection checks.
  The words still read like the model wrote them. launder cleans bytes; it does
  not launder authorship.

## Example

> **Before:** `he said “hi”⁠` — with curly quotes and a zero-width word joiner
> after the closing quote (invisible here, but present in the bytes).
>
> **After:** `he said "hi"` — straight quotes, the invisible character gone,
> nothing else changed.

## Output

Deliver the laundered text, not a report on laundering it. Don't narrate running
`launder.py`. If the text was already clean, say so in one line; if asked what
was found, give the category list plainly. No preamble, no closing note.

## Companion tool

`launder.py` in this folder applies these scrubbers mechanically. Pipe text
through it to clean it (`launder.py`), gate a pipeline (`launder.py --check`,
exits 1 if any fingerprint is present), list what it found by category
(`launder.py --report`), or get a structured summary (`launder.py --json`).
Add `--homoglyphs` to also normalize confusables. It pairs with **`tell`**:
`tell` diagnoses the AI prose, launder washes the AI typography.
