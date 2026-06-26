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
  and prints each response under its model id. The lineup is **multi-provider**:
  each model id routes to the right backend by its prefix (`claude*` → Anthropic,
  `gpt*`/`o1*`/`o3*`/`chatgpt*` → OpenAI, `gemini*` → Gemini), or you can be
  explicit with a `provider:model` id. `--dry-run` shows the plan with zero
  dependencies and no network; a real run needs the matching API key plus that
  provider's SDK installed.

## usage

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # and/or OPENAI_API_KEY / GEMINI_API_KEY

# the default lineup: opus + sonnet + haiku
python3 lineup.py --prompt "Explain TCP in one sentence."

# from a file or stdin
python3 lineup.py prompt.txt
cat prompt.txt | python3 lineup.py

# a cross-provider lineup — ids route by prefix
python3 lineup.py --prompt "..." --models claude-opus-4-8,gpt-4o,gemini-2.5-flash

# be explicit with provider:model ids
python3 lineup.py --prompt "..." --models "openai:gpt-4o,anthropic:claude-haiku-4-5"

# pin a default provider for ids that don't name one
python3 lineup.py --prompt "..." --models my-model --provider openai

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
| `--models a,b,c` | comma-separated model ids (mix providers; `provider:model` ok) |
| `--judge MODEL`  | after collecting answers, ask this model to pick the best + why |
| `--provider P`   | default provider for ids that don't name one (else auto-detect) |
| `--dry-run`      | print the lineup plan without calling the API (no key, no deps) |

The default lineup is an opus + a sonnet + a haiku tier
(`claude-opus-4-8`, `claude-sonnet-4-6`, `claude-haiku-4-5`).

Each id routes to a provider by its prefix (`claude*`/`anthropic*` → Anthropic,
`gpt*`/`o1*`/`o3*`/`chatgpt*` → OpenAI, `gemini*`/`models/gemini*` → Gemini).
Use a `provider:model` id (e.g. `openai:gpt-4o`) to be explicit, or `--provider`
to set the fallback for ids that don't match any prefix.

## a real run needs a key

`--dry-run` is zero-dependency and offline — it just shows which prompt would go
to which models. A real run (the default when you don't pass `--dry-run`) calls
each model, so it needs whichever key matches the providers in your lineup:

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # for claude-* ids
export OPENAI_API_KEY=sk-...          # for gpt-*/o1/o3 ids
export GEMINI_API_KEY=...             # for gemini-* ids
```

Install the matching SDK for the providers in your lineup (`pip install
anthropic` / `openai` / `google-genai`); the shared helper imports each lazily.
Without a key, run with `--dry-run` to preview the lineup for free.

## install

```bash
just install lineup            # symlinks `lineup` onto your PATH + installs the skill
```

[`just`](https://github.com/casey/just). Or just run `python3 lineup.py` from
this folder. A real run needs one of `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` /
`GEMINI_API_KEY` plus that provider's SDK installed; `--dry-run` needs neither a
key nor any dependency.

## honest notes

- It's a quick parade, not a benchmark. Three answers tell you a lot about
  agreement and a little about quality — they don't replace a real eval.
- `--judge` is a model judging models. Treat its pick as a strong opinion, not a
  verdict — read the answers yourself.
- Costs one call per model (plus one if you `--judge`). `--dry-run` costs
  nothing.
