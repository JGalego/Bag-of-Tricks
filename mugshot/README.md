<p align="center">
  <img src="logo.png" alt="mugshot" width="420">
</p>

Bring the text in, stand it against the wall, turn on the lights. Every model
leaves prints — an "It's important to note" here, an em-dash aside there — and
once you've read enough output the families start to look distinct. `mugshot`
runs the line-up: it names the family most likely to have written a passage and
shows you the prints it lifted.

By **default** it asks a real model — an LLM authorship/stylometry pass — when a
provider key is configured. With no key it falls back to an **offline regex
heuristic** (the old parlor trick) and says so. Force either path: `--llm` for
the model, `--parlor` for the regex.

It comes in two halves:

- **`SKILL.md`** — a [Claude Code / agent skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
  that teaches the model to read a passage's style, match it to a family, and
  name the likely author with its receipts — honestly hedged as a guess.
- **`mugshot.py`** — a `stdin->stdout` analyzer. Feed it text, get back a
  suspect, a confidence band, and the exact prints that matched.

## the lineup

```bash
# default: model-backed if a key is set, else the offline heuristic (with a note)
echo "Certainly! I'd be happy to help. It's important to note that we must delve into this." \
  | python3 mugshot.py
# most likely: gpt-ish (high confidence) — heuristic, not proof
# prints: gpt-ish:Certainly!, gpt-ish:I'd be happy to, claude-ish:happy to help, gpt-ish:It's important to note, generic-AI:delve

# force the real model-backed attribution
python3 mugshot.py --llm draft.md
python3 mugshot.py --llm --provider anthropic --model claude-sonnet-4-6 draft.md

# force the offline regex heuristic (no network)
python3 mugshot.py --parlor draft.md

# every print, with offsets
python3 mugshot.py --report < draft.md

# the full ranked scoreboard
python3 mugshot.py --all --parlor < draft.md
# most likely: gpt-ish (medium confidence) — heuristic, not proof
#
# line-up (weighted, length-normalized):
#   gpt-ish        7.500 <-- most likely
#   generic-AI     2.000
#   claude-ish     0.000

# the structured verdict
python3 mugshot.py --json < draft.md
```

### flags

| flag                  | does                                                          |
|-----------------------|--------------------------------------------------------------|
| *(default)*           | model-backed pass if a key is configured, else the offline heuristic (with a stderr note) |
| `--llm`               | force the model-backed pass; fail loudly (exit 2) on provider error, no silent fallback |
| `--parlor`            | force the offline regex heuristic (the parlor trick)         |
| `--provider P`        | pick the LLM provider (`anthropic`, `openai`, `gemini`)      |
| `--model M`           | pick the model id for the chosen provider                    |
| `--patterns FILE`     | merge custom parlor prints from a JSON file (repeatable)     |
| `--report`            | list every matched print (suspect + preview + offset)        |
| `--all`               | show the full ranked scoreboard of all suspects              |
| `--json`              | emit the full structured dict (verdict, confidence, scores, prints) |

Every output mode (`--report`, `--all`, `--json`, default) reads the same verdict
dict, so they work for both the model and parlor paths.

### custom parlor prints

The offline lineup is a set of caricatures you can extend. Point `--patterns` at
a JSON file (repeatable; later files extend earlier ones), or set the
`MUGSHOT_PATTERNS` env var to one or more paths joined by your OS path separator
(`:` on Unix). New suspect names create new rows; existing names get more prints.

```json
{
  "suspects": {
    "robot-ish": [
      [5.0, "beep boop opener", "\\bbeep boop\\b"],
      [2.0, "does not compute", "\\bdoes not compute\\b"]
    ]
  }
}
```

Each inner triple is one print: a `weight` (number), a human `label`, and a
case-insensitive `regex`.

```bash
python3 mugshot.py --parlor --patterns my_prints.json draft.md
MUGSHOT_PATTERNS=my_prints.json python3 mugshot.py --parlor draft.md
```

### the usual suspects

| suspect       | prints it's known for |
|---------------|-----------------------|
| **gpt-ish**   | "Certainly!", "I'd be happy to", "It's important to note", "However, it's worth", bold section headers, numbered listicles, "In conclusion", "Overall," |
| **claude-ish**| leading "I'll …", "Let me …", "Here's …", "Great question", "Sure,", em-dash asides, warm hedging |
| **generic-AI**| the prints any model leaves — delve, tapestry, "navigate the complexities", "it's not just X, it's Y", "in today's fast-paced …", testament, ever-evolving |
| **human / inconclusive** | the honest verdict when nothing strong matches |

Each print carries a weight — a blatant opener counts more than a stray em-dash.
Scores are the summed weights, lightly normalized by length so a long document of
mild tells can't out-shout a short, blatant one. The top suspect wins; the
confidence band comes from how far it beats the runner-up.

## install

From the repo root, [`just`](https://github.com/casey/just) symlinks the CLI onto
your `PATH` and the [skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
into `~/.claude/skills/`:

```bash
just install mugshot
echo "Great question! Let me walk you through it. Here's the gist." | mugshot
```

Or run it in place: `python3 mugshot.py`.

## pairs with tell

[`tell`](https://github.com/JGalego/Bag-of-Tricks/tree/main/tell) finds the
prints — *how* AI does this read? `mugshot` names the suspect — *whose* prints
are these? Run `tell` to decide it's machine-written, then `mugshot` to guess
which machine.

## a guess, not proof

Even with a model in the loop this is a probabilistic guess with a confidence
band, not a verdict. There is no watermark, no logprobs, no ground truth here —
only style, and style lies. Models drift and mimic each other, fine-tunes and
system prompts shuffle the tells, and any human who has read enough output can
stuff a paragraph with "Certainly!" to frame an innocent. Read "most likely:
gpt-ish" as "this *smells* gpt-ish," never as "GPT wrote this." The model path
reads more than regexes can, but it is still a hunch — inadmissible in court.
