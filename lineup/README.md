<p align="center"><img src="logo.png" alt="lineup" width="420"></p>

You have a prompt and three models that could answer it, and no idea which one
to trust. lineup is the identification parade: it walks all the suspects out
under the same light, asks them the same question, and stands their answers
side by side so you can pick the best one — or spot the one whose story doesn't
match the others.

Same prompt, the whole lineup. See who did it.

It comes in two halves:

- **`SKILL.md`** — a [Claude Code / agent skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
  that tells the model what lineup is for: fan one prompt across several models,
  keep every answer labeled, and read the disagreement instead of averaging it
  away.
- **`lineup.py`** — a CLI that sends one prompt to a list of models in parallel
  and prints each response under its model id (with token counts when handy).
  `--dry-run` shows the plan with zero dependencies and no network; a real run
  needs the `anthropic` SDK and a key.

## usage

```bash
export ANTHROPIC_API_KEY=sk-ant-...

# the default lineup: opus + sonnet + haiku
python3 lineup.py --prompt "Explain TCP in one sentence."

# from a file or stdin
python3 lineup.py prompt.txt
cat prompt.txt | python3 lineup.py

# pick your own lineup
python3 lineup.py --prompt "..." --models claude-opus-4-8,claude-haiku-4-5

# ask a model to pick the winner and say why
python3 lineup.py --prompt "..." --judge claude-opus-4-8

# see who'd be in the lineup without spending a token (no key required)
python3 lineup.py --prompt "Explain TCP in one sentence." --dry-run
```

Each model runs as an **independent** call, in parallel, so it's fast and one
model can't bias another. If a model errors, it's labeled as errored and the
rest still show — the lineup goes on.

### flags

| flag             | does                                                            |
|------------------|----------------------------------------------------------------|
| *(default)*      | run the prompt across the default lineup, print answers labeled |
| `--prompt TEXT`  | the prompt to put in front of the lineup                        |
| `file` (arg)     | read the prompt from a file (default: `--prompt` or stdin)      |
| `--models a,b,c` | comma-separated model ids to put in the lineup                  |
| `--judge MODEL`  | after collecting answers, ask this model to pick the best + why |
| `--dry-run`      | print the lineup plan without calling the API (no key, no deps) |

The default lineup is an opus + a sonnet + a haiku tier
(`claude-opus-4-8`, `claude-sonnet-4-6`, `claude-haiku-4-5`).

## a real run needs a key

`--dry-run` is zero-dependency and offline — it just shows which prompt would go
to which models. A real `--run` (the default when you don't pass `--dry-run`)
calls each model, so it needs:

```bash
pip install anthropic          # the SDK
export ANTHROPIC_API_KEY=sk-ant-...
```

Without the SDK or a key, run with `--dry-run` to preview the lineup for free.

## install

```bash
just install lineup            # symlinks `lineup` onto your PATH + installs the skill
pip install anthropic          # needed for a real run (not for --dry-run)
```

[`just`](https://github.com/casey/just) ·
[anthropic SDK](https://github.com/anthropics/anthropic-sdk-python). Or just run
`python3 lineup.py` from this folder.

## honest notes

- It's a quick parade, not a benchmark. Three answers tell you a lot about
  agreement and a little about quality — they don't replace a real eval.
- `--judge` is a model judging models. Treat its pick as a strong opinion, not a
  verdict — read the answers yourself.
- Costs one call per model (plus one if you `--judge`). `--dry-run` costs
  nothing.
