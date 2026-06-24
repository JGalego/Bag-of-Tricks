<p align="center">
  <img src="logo.png" alt="combo" width="420">
</p>

Most real jobs aren't one trick. You don't just redact a secret — you redact it,
*then* wash the typographic prints, *then* strip the personality. A magician's
*combo* is several tricks run as one move; this is that, for the bag. combo
chains tricks into a single pipeline so the output of one flows straight into the
next, and you call the whole routine once.

There's no new machinery under it. Every trick in the bag is already a
`stdin->stdout` program, so the composition layer is just the **Unix pipe**.
combo wires the stages together, forwards each stage's one-line summary, and
stops the instant a stage fails — so a gate aborts the routine and its exit code
propagates.

It comes in two halves:

- **`SKILL.md`** — a [Claude Code / agent skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
  that teaches the model to reach for one composed pipeline when a task needs
  several tricks in sequence, instead of invoking each separately and shuttling
  text between them.
- **`combo.py`** — a zero-dependency runner that resolves each stage to a sibling
  trick (or a command on `PATH`), pipes stdout→stdin down the chain, and
  propagates the first non-zero exit.

## the routine

```bash
# redact secrets, wash the bytes, strip the chirp — one call
combo "frisk --pii | launder | deadpan" < reply.md

# bare names (no per-stage flags) is the same as quoting each one
combo frisk launder deadpan < reply.md

# wash first, then measure how AI the prose still reads (filter -> analyzer)
combo "launder | tell --score" < draft.md

# refuse to continue if a secret is present (gate -> filter)
combo "frisk --check | launder" < draft.md && echo "shipped clean"

# redact a secret living inside JSON, then rip the JSON out of the chatter
combo "frisk | salvage" < model_output.txt
```

### the three shapes

A trick's *shape* tells you where it can sit in a routine. `combo --list` tags
every trick it can find:

| shape        | emits                    | where it sits        | examples                                  |
|--------------|--------------------------|----------------------|-------------------------------------------|
| **filter**   | transformed text         | the middle           | `frisk` `launder` `salvage` `mole` `deadpan` |
| **analyzer** | a report / verdict       | the end (a sink)     | `tell` `fold` `alibi` `mugshot` `bluff` `tollbooth` |
| **gate**     | nothing (an exit code)   | first or last        | a `--check` / `--max` *mode*, not a trick |

Rule of thumb: any number of **filters**, optionally ended by **one analyzer**,
optionally fronted or closed by a **gate**. A gate isn't a separate trick — it's
a mode (`--check`, `--max`) that `frisk`, `launder`, `mole`, `fold`, `alibi`,
`tell`, and others expose to abort a pipeline.

### flags

| flag              | does                                                       |
|-------------------|------------------------------------------------------------|
| *(default)*       | run the routine, final output to stdout, summaries to stderr |
| `-l`, `--list`    | list chainable tricks tagged by shape                       |
| `-n`, `--dry-run` | resolve and print the routine without running it            |
| `-i`, `--input F` | read the head of the pipe from file `F` (default: stdin)    |
| `-v`, `--verbose` | echo each stage to stderr as it runs                        |

### two ways to write a routine

```bash
combo "frisk --pii | launder | tell --score"   # pipe-string: per-stage flags OK
combo frisk launder deadpan                     # bare list: names only
```

Per-stage flags require the quoted pipe-string form — in the bare list, combo
can't tell whose flag is whose, so it treats every word as a stage name.

## order matters

combo doesn't reorder your stages; you decide the sequence, and the sequence is
the whole point. Redact (`frisk`) **before** you extract (`salvage`) so the
secret never reaches the parser. Wash bytes (`launder`) **before** a strict
reader. Don't drop an analyzer in the middle — nothing flows out of a sink. When
the order is non-obvious, that's exactly when a named, repeatable routine earns
its keep.

## install

From the repo root, [`just`](https://github.com/casey/just) symlinks the CLI
onto your `PATH` and the [skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
into `~/.claude/skills/`:

```bash
just install combo
combo --list
```

Or run it in place: `python3 combo.py "frisk | launder" < draft.md`.
