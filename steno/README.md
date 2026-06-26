<p align="center">
  <img src="logo.png" alt="steno" width="420">
</p>

You type the same prompts all day — "review this code", "write tests for this",
"explain what this does". steno gives them mind-numbingly short aliases that
expand into full, well-formed prompts with your file (or text, or `git diff`)
spliced in. By default it just prints the prompt — pipe it anywhere — or pass
`--run` to send it straight to an LLM (Anthropic, OpenAI-compatible, or Gemini).

It's the caveman move applied to *your* side of the conversation: why type a
whole prompt when two letters do the trick.

## install

```bash
just install steno          # symlinks `steno` onto your PATH
```

[`just`](https://github.com/casey/just). Or run `python3 steno.py` from this
folder. Expanding needs nothing but Python 3.9+; `--run` just needs one of
`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` in the environment —
install only the provider SDK you use (anthropic / openai / google-genai).

## usage

```bash
steno r src/app.py            # review  → prints the expanded prompt
steno t utils.py              # tests
steno e parser.py | deadpan   # compose with the rest of the bag
steno rx "match an iso date"  # free text instead of a file
steno c                       # commit message from `git diff --cached`
steno r app.py --run          # actually send it to an LLM
steno r app.py --run --provider openai --model gpt-4o   # pick a provider/model
steno ls                      # list every alias
```

`--run` auto-detects the provider from whichever API key is set. Override it
with `--provider {anthropic,openai,gemini}` and/or `--model <id>`; with neither,
the provider's default model is used.

Input is resolved in this order: `--text`, then file arg(s) (contents are read
in, with a filename header), then anything else as literal text, then piped
**stdin**. The `c` and `pr` aliases fall back to `git diff` when you give no
input.

## the built-in aliases

| alias | does |
|-------|------|
| `e` | explain what the code does |
| `r` | review for bugs, edge cases, clarity |
| `t` | write thorough tests |
| `d` | add docstrings / comments |
| `ty` | add type annotations |
| `f` | find and fix bugs |
| `o` | optimize without changing behavior |
| `s` | simplify for readability |
| `n` | suggest clearer names |
| `rx` | write a regex (with test cases) |
| `sql` | write a SQL query |
| `sh` | write a shell command |
| `tl` | tl;dr / summarize |
| `c` | commit message from a diff |
| `pr` | PR description from a diff |

`steno ls` prints the live list (including your own).

## add your own

One line per alias in `~/.config/steno/aliases.txt` (or point `$STENO_ALIASES`
at a file). The first token is the alias, the rest is the template; `{input}` is
where the target gets spliced in (if you omit it, it's appended):

```
# ~/.config/steno/aliases.txt
adr   Write an Architecture Decision Record for: {input}
oops  Explain this stack trace and the most likely root cause:\n\n{input}
```

User aliases extend and override the built-ins.

## skill

steno ships a [skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
(`SKILL.md`); `just install steno` puts it in `~/.claude/skills/steno/` so Claude
Code knows the alias vocabulary when you reference one.

## composes with the bag

steno writes the prompt; the other tricks shape it:

```bash
steno r app.py | deadpan            # terse, no-fluff review prompt
steno e mod.py --run | deadpan      # run it (any provider), then strip the chatter
```
