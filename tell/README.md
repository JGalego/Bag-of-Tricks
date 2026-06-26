<p align="center">
  <img src="logo.png" alt="tell" width="420">
</p>

Every AI has a tell. A poker player's eyes; a model's *delve*. The prose is
grammatical, confident, and — once you've read enough of it — instantly
recognizable. `tell` reads a passage and tells you how AI it sounds, then points
at the exact words and structures giving it away. It does not rewrite. It
diagnoses.

It comes in two halves:

- **`SKILL.md`** — a [Claude Code / agent skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
  that teaches the model to spot its own fingerprints in a passage.
- **`tell.py`** — a zero-dependency scorer. Feed it text, get back a number and a
  list of receipts.

## the scorer

```bash
echo "Let's delve into this rich tapestry — a testament to the realm." \
  | python3 tell.py
# score 90/100  (5 tells)
#
# overused words:
#   delve ×1
#   tapestry ×1
#   testament ×1
#   realm ×1
#
# structurals:
#   em-dash ×1

# just the number, for scripts
tell.py --score draft.md

# the full receipts as JSON
tell.py --json draft.md

# gate prose in CI: exit 1 if it reads too AI
tell.py --max 30 draft.md
```

## the model's eyes

The lexicon only catches the words and shapes it was told about. `--llm` hands
the passage to a model that reads it the way a human would — catching paraphrased
slop, hollow even-handedness, and mechanical rhythm the keyword list misses, then
naming the specific tells with counts. Same output shape, so `--score`, `--json`,
and `--max` all keep working off it.

```bash
tell.py --llm draft.md
tell.py --llm --provider anthropic --model claude-opus-4-8 --json draft.md
tell.py --llm --max 40 draft.md      # gate on the model's verdict
```

Set the provider key in the environment (e.g. `ANTHROPIC_API_KEY`). On a provider
failure `tell` exits 2 and writes to stderr — it never silently falls back.

## bring your own tells

The offline lexical mode starts from the built-ins and can be extended with your
own. Point `--patterns` (repeatable) at a JSON file, or set `TELL_PATTERNS` to an
`os.pathsep`-separated list of files as a fallback:

```bash
tell.py --patterns house-style.json draft.md
TELL_PATTERNS=a.json:b.json tell.py draft.md
```

```json
{
  "words": ["synergize", "thought leader"],
  "phrases": [
    ["circle back", "\\bcircle back\\b"],
    ["needle-mover", "\\bneedle[- ]mover\\b"]
  ]
}
```

`words` match case-insensitively on word boundaries (spaces allowed for multiword
terms); `phrases` are `[label, regex]` pairs. Your entries *extend* the built-ins,
they don't replace them. Custom patterns only affect the offline lexical mode —
not `--llm`, which reads the raw passage.

## what it catches

| category    | examples |
|-------------|----------|
| overused words | delve, tapestry, testament, crucial, robust, seamless, leverage, vibrant, … |
| cliché phrases | "it's not just X, it's Y", "in conclusion", "when it comes to", "ever-evolving" |
| structural     | em-dash overuse, emoji, rule-of-three lists, **bold** runs |

## the score

A bounded, deterministic heuristic: tells per 100 words, run through
`100 × (1 − e^(−density/6))`. More tells never lowers the score for the same
length, and it saturates well before infinity. Clean technical prose lands near
zero; a paragraph stuffed with *delve* and *tapestry* pins the meter.

## install

From the repo root, [`just`](https://github.com/casey/just) symlinks the CLI onto
your `PATH` and the [skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
into `~/.claude/skills/`:

```bash
just install tell
echo "Let's delve into the realm." | tell
```

Or run it in place: `python3 tell.py`.

## pairs with deadpan

[`deadpan`](https://github.com/JGalego/Bag-of-Tricks/tree/main/deadpan) stops the
tells at generation time. `tell` catches the ones that slipped through. Belt and
suspenders for people who can't stand reading "in today's fast-paced world" one
more time.

## not a verdict

A score is a smell, not proof. Human writers say *crucial* too. `tell` flags the
density of giveaways so you know where to look — it doesn't certify authorship.
