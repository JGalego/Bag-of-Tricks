<p align="center">
  <img src="assets/bag-of-tricks-wheel.png" alt="bag of tricks" width="300">
</p>

<p align="center">
  <img alt="powered by caffeine and spite" src="https://img.shields.io/badge/rationale-powered_by_caffeine_and_spite-8A2BE2">
  <a href="https://github.com/JGalego/Bag-of-Tricks/actions/workflows/ci.yml"><img alt="ci" src="https://github.com/JGalego/Bag-of-Tricks/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="license: MIT" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
  <img alt="python 3.9+" src="https://img.shields.io/badge/python-3.9%2B-blue.svg">
  <a href="https://github.com/astral-sh/ruff"><img alt="code style: ruff" src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json"></a>
  <img alt="tricks: 10" src="https://img.shields.io/badge/tricks-10-111111.svg">
</p>

> a small bag of clever hacks for people who work with LLMs all day.

A growing set of single-idea tools. Each lives in its own folder, does one thing, installs in seconds, and has a catchphrase it has to live up to. Inspired in *tone* (not substance) by [caveman](https://github.com/juliusbrussee/caveman) and [headroom](https://github.com/headroomlabs-ai/headroom).

| trick | catchphrase | what it does |
|-------|-------------|--------------|
| [`deadpan`](deadpan/) | *the answer. nothing else.* | strips LLM replies of personality, filler, hedging, emoji, sycophancy. |
| [`snitch`](snitch/) | *see what your agent actually said behind your back.* | a transparent proxy that logs the **exact bytes** your agent sends the model. |
| [`strawman`](strawman/) | *argue with yourself before the internet does.* | red-teams your own prompt — an adversarial model tries to break it and reports where it cracked. |
| [`interrobang`](interrobang/) | *make it ask before it acts.* ‽ | flips the helpful-assistant reflex: ask one sharp question instead of guessing. |
| [`steno`](steno/) | *two letters, and the prompt writes itself.* | mind-numbingly short aliases that expand into full prompts for common dev tasks. |
| [`salvage`](salvage/) | *rip the JSON out of the chatter.* | extracts and repairs valid JSON buried in chatty model output — fences, trailing commas, Python literals. |
| [`frisk`](frisk/) | *pat it down before it ships.* | scans text headed to the model for secrets & PII (keys, tokens, private keys, emails) and redacts or flags them. |
| [`tell`](tell/) | *every AI has a tell.* | flags the giveaways in AI-written prose — "delve", "tapestry", "it's not just X, it's Y", em-dash overuse. |
| [`tollbooth`](tollbooth/) | *know the bill before the bill.* | estimates token count and dollar cost of a prompt across models before you send it. |
| [`bluff`](bluff/) | *call its bluff.* | extracts the URLs & citations from an answer and checks they actually resolve — catching hallucinated links. |

## the philosophy

Caveman cuts *tokens*. Headroom compresses *context*. This bag is about everything *else* that's annoying when you build with LLMs: they're chatty, they hide their prompts, they're easy to break, they guess when they should ask — and whatever the next annoyance turns out to be. Each trick takes on exactly one of them. New tricks get added as the irritations pile up.

Everything here is Python 3.9+, mostly standard library — most tricks have **zero dependencies** (`bluff` even checks links with nothing but `urllib`). Two tricks reach further: `strawman` needs the [`anthropic`](https://github.com/anthropics/anthropic-sdk-python) SDK to actually attack (it has a `--dry-run` that needs nothing), and `tollbooth` *optionally* uses [`tiktoken`](https://github.com/openai/tiktoken) for exact token counts, falling back to a built-in heuristic when it's absent.

```bash
git clone <this repo>
cd bag-of-tricks

# try the cheapest trick first — no API key needed
echo "Certainly! I'd be happy to help. Here is the answer: 42 🎉" | python3 deadpan/deadpan.py
# -> The answer: 42
```

Each folder has its own README with the full pitch and usage.

## install standalone

Prefer plain CLIs and skills without the plugin system? Recipes run with [`just`](https://github.com/casey/just). Installing a trick symlinks its CLI into `~/.local/bin` and its `SKILL.md` into `~/.claude/skills/`:

```bash
just install                   # install every trick
just install deadpan           # just one
just install snitch strawman   # or a few
just uninstall                 # remove them all (or name them)
```

Then run them by name (make sure `~/.local/bin` is on your `PATH`):

```bash
echo "Sure! 42 🎉" | deadpan
```

Prefer not to install? Every trick also runs straight from its folder, e.g. `python3 deadpan/deadpan.py`.

## use as a Claude Code plugin

The bag is a [plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces): each trick is a [plugin](https://code.claude.com/docs/en/plugins) that ships its skill **and** puts its CLI on the Bash tool's `PATH` while enabled — no separate install step.

```bash
# add the marketplace, then install the tricks you want
/plugin marketplace add JGalego/Bag-of-Tricks
/plugin install snitch@bag-of-tricks
/plugin install deadpan@bag-of-tricks
```

Want to try it before publishing? Load a plugin straight from a checkout:

```bash
claude --plugin-dir ./snitch
```

Plugin skills are namespaced (`/deadpan:deadpan`, `/strawman:strawman`, …), and each plugin's CLI (`snitch`, `steno`, …) is runnable while the plugin is enabled.

## development

Quality is enforced with [ruff](https://docs.astral.sh/ruff/) (lint + format) and [pytest](https://docs.pytest.org/) — each trick has a `test_<trick>.py` beside it. Everything runs with no network and no API key (`strawman`'s tests stub the SDK).

```bash
just dev          # pip install -r requirements-dev.txt (ruff + pytest)
just check        # what CI runs: ruff check + ruff format --check + pytest
just fmt          # auto-format
just test         # just the tests
just              # list every recipe
```

Or directly: `ruff check .`, `ruff format .`, `pytest`. A [Makefile](Makefile) mirrors the dev recipes (`make check`, `make dev`, …) if you'd rather use [make](https://www.gnu.org/software/make/).

CI runs the same checks on every push and PR across Python 3.9–3.12 (see [.github/workflows/ci.yml](.github/workflows/ci.yml)).

## license

MIT — see [LICENSE](LICENSE). Use them, fork them, rename them, put them in your own bag.
