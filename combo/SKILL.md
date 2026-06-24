---
name: combo
description: Chain several tricks into one pipeline so the output of one flows straight into the next — redact then wash then strip, or wash then score — and run the whole routine in a single call. Use when a task needs more than one trick in sequence (clean-and-check, extract-and-analyze, gate-then-transform) instead of invoking each trick separately. Built on the Unix pipe: every trick is a stdin→stdout program, and combo wires the stages together, forwards each stage's summary, and aborts the moment a gate fails.
---

# combo

**pull the whole routine.**

A magician's *combo* is several tricks performed as one move. This is that, for
the bag. Most real jobs aren't one trick — they're a sequence: redact the
secrets, *then* wash the typographic prints, *then* strip the personality. combo
runs that sequence as a single pipeline so you don't invoke three tricks by hand
and shuttle text between them.

There is no new framework here. Every trick in the bag is already a
`stdin→stdout` program, so the composition layer is just the **Unix pipe**.
combo wires the stages together, forwards each stage's one-line summary (the
tricks write those to stderr), and stops the instant a stage fails — so a gate
aborts the whole routine and its exit code propagates.

## The three shapes

Tricks fall into shapes, and the shape tells you where a trick can sit in a
routine:

1. **filter** — emits transformed *text* on stdout, so it chains in the
   **middle** of a routine. `frisk` (redact), `launder` (wash bytes), `salvage`
   (rip out JSON), `mole` (tag injections), `deadpan` (strip personality).
2. **analyzer** — emits a *report or verdict*, so it's a **terminal** stage (a
   sink): nothing useful flows out of it into another trick. `tell` (AI-smell
   score), `fold` (overconfidence), `alibi` (grounding), `mugshot`, `bluff`,
   `tollbooth`.
3. **gate mode** — not a separate trick but a *mode* several tricks share
   (`--check`, `--max`): print nothing, exit non-zero to **abort** the routine.
   Put a gate first to refuse bad input, or last to fail a build.

Rule of thumb: any number of **filters**, optionally ended by **one analyzer**
or fronted/closed by a **gate**.

## Rules

1. **Order matters — think about what each stage consumes.** Redact (`frisk`)
   before you extract (`salvage`) so the secret never reaches the parser. Wash
   bytes (`launder`) before a strict reader. Don't put an analyzer in the
   middle — nothing flows out of a sink.
2. **Per-stage flags need the quoted form.** `combo "frisk --pii | launder"`.
   The bare-list form `combo frisk launder` is names only, because combo can't
   tell whose flag is whose.
3. **A gate stops the routine.** If any stage exits non-zero (a `--check` that
   tripped, a missing trick), combo stops there and returns that code. Use
   `&&` to act only on a clean routine.
4. **Don't hand-simulate a pipeline.** When the task is two or more tricks in
   sequence, call combo once rather than running each trick and pasting output
   between them.

## Examples

```bash
# redact secrets, wash the bytes, strip the chirp — one call
combo "frisk --pii | launder | deadpan" < reply.md

# wash first, then measure how AI the prose still reads (filter -> analyzer)
combo "launder | tell --score" < draft.md

# refuse to continue if a secret is present (gate -> filter)
combo "frisk --check | launder" < draft.md && echo "shipped clean"

# redact a secret living inside JSON, then rip the JSON out of the chatter
combo "frisk | salvage" < model_output.txt

# see the shapes, or preview a routine without running it
combo --list
combo --dry-run "frisk | launder | tell"
```

## Output

Deliver the routine's final output, not a narration of the stages. combo already
forwards each stage's summary to stderr; don't restate them. If a gate aborted
the routine, say which stage failed and why (the stderr line tells you), not a
generic "it failed". Pick the pipeline order deliberately and, if it's
non-obvious, name the reason in one line (e.g. "redact before extract").

## Companion tool

`combo.py` in this folder is the runner. It resolves each stage to the sibling
trick in the bag (or a command on PATH), pipes stdout→stdin down the chain, and
propagates the first non-zero exit. Flags: `--list` (tricks by shape), `--dry-run`
(resolve the routine without running it), `--input FILE` (read the head of the
pipe from a file), `--verbose` (echo each stage as it runs).
