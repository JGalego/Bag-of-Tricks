<p align="center">
  <img src="logo.png" alt="mugshot" width="420">
</p>

Bring the text in, stand it against the wall, turn on the lights. Every model
leaves prints — an "It's important to note" here, an em-dash aside there — and
once you've read enough output the families start to look distinct. `mugshot`
runs the line-up: it matches a passage against a handful of stylistic profiles
and names the one most likely to have written it, then shows you the prints it
lifted. It's a parlor trick wearing a badge, not a forensics lab.

It comes in two halves:

- **`SKILL.md`** — a [Claude Code / agent skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
  that teaches the model to read a passage's style, match it to a family, and
  name the likely author with its receipts — honestly hedged as a guess.
- **`mugshot.py`** — a zero-dependency `stdin->stdout` analyzer. Feed it text,
  get back a suspect, a confidence band, and the exact prints that matched.

## the lineup

```bash
echo "Certainly! I'd be happy to help. It's important to note that we must delve into this." \
  | python3 mugshot.py
# most likely: gpt-ish (medium confidence) — heuristic, not proof
# prints: gpt-ish:Certainly!, gpt-ish:I'd be happy to, gpt-ish:It's important to…, generic-AI:delve

# every print, with offsets
python3 mugshot.py --report < draft.md

# the full ranked scoreboard
python3 mugshot.py --all < draft.md
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

| flag        | does                                                          |
|-------------|--------------------------------------------------------------|
| *(default)* | print the verdict (suspect + confidence) and the top prints  |
| `--report`  | list every matched print (suspect + preview + offset)        |
| `--all`     | show the full ranked scoreboard of all suspects              |
| `--json`    | emit the full structured dict (verdict, confidence, scores, prints) |

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

## a parlor trick, not proof

This is entertainment with a confidence band, not a verdict. There is no
watermark, no logprobs, no ground truth here — only style, and style lies.
Models drift and mimic each other, fine-tunes and system prompts shuffle the
tells, and any human who has read enough output can stuff a paragraph with
"Certainly!" to frame an innocent. Read "most likely: gpt-ish" as "this *smells*
gpt-ish," never as "GPT wrote this." Fun at parties; inadmissible in court.
