<p align="center">
  <img src="assets/logo.png" alt="bag of tricks" width="300">
</p>

> a small bag of clever hacks for people who work with LLMs all day.

A growing set of single-idea tools. Each lives in its own folder, does one thing,
installs in seconds, and has a catchphrase it has to live up to. Inspired in
*tone* (not substance) by [caveman](https://github.com/juliusbrussee/caveman) and
[headroom](https://github.com/headroomlabs-ai/headroom).

| trick | catchphrase | what it does |
|-------|-------------|--------------|
| [`deadpan`](deadpan/) | *the answer. nothing else.* | strips LLM replies of personality, filler, hedging, emoji, sycophancy. |
| [`snitch`](snitch/) | *see what your agent actually said behind your back.* | a transparent proxy that logs the **exact bytes** your agent sends the model. |
| [`strawman`](strawman/) | *argue with yourself before the internet does.* | red-teams your own prompt — an adversarial model tries to break it and reports where it cracked. |
| [`interrobang`](interrobang/) | *make it ask before it acts.* ‽ | flips the helpful-assistant reflex: ask one sharp question instead of guessing. |

## the philosophy

Caveman cuts *tokens*. Headroom compresses *context*. This bag is about everything
*else* that's annoying when you build with LLMs: they're chatty, they hide their
prompts, they're easy to break, they guess when they should ask — and whatever
the next annoyance turns out to be. Each trick takes on exactly one of them. New
tricks get added as the irritations pile up.

Everything here is Python 3.9+, mostly standard library — most tricks have
**zero dependencies**. The exception so far is `strawman`, which needs the
[`anthropic`](https://github.com/anthropics/anthropic-sdk-python) SDK (and only
to actually attack — it has a `--dry-run` that needs nothing).

```bash
git clone <this repo>
cd bag-of-tricks

# try the cheapest trick first — no API key needed
echo "Certainly! I'd be happy to help. Here is the answer: 42 🎉" | python3 deadpan/deadpan.py
# -> The answer: 42
```

Each folder has its own README with the full pitch and usage.

## install

Recipes run with [`just`](https://github.com/casey/just). Installing a trick
symlinks its CLI into `~/.local/bin` and, for tricks that ship one, its
[skill](https://docs.claude.com/en/docs/agents-and-tools/skills) into
`~/.claude/skills/`:

```bash
just install              # install every trick
just install deadpan      # just one
just install snitch strawman   # or a few
just uninstall            # remove them all (or name them)
```

Then run them by name (make sure `~/.local/bin` is on your `PATH`):

```bash
echo "Sure! 42 🎉" | deadpan
```

Prefer not to install? Every trick also runs straight from its folder, e.g.
`python3 deadpan/deadpan.py`.

## development

Quality is enforced with [ruff](https://docs.astral.sh/ruff/) (lint + format)
and [pytest](https://docs.pytest.org/) — each trick has a `test_<trick>.py`
beside it. Everything runs with no network and no API key (`strawman`'s tests
stub the SDK).

```bash
just dev          # pip install -r requirements-dev.txt (ruff + pytest)
just check        # what CI runs: ruff check + ruff format --check + pytest
just fmt          # auto-format
just test         # just the tests
just              # list every recipe
```

Or directly: `ruff check .`, `ruff format .`, `pytest`. A [Makefile](Makefile)
mirrors the dev recipes (`make check`, `make dev`, …) if you'd rather use
[make](https://www.gnu.org/software/make/).

CI runs the same checks on every push and PR across Python 3.9–3.12
(see [.github/workflows/ci.yml](.github/workflows/ci.yml)).

## license

MIT — see [LICENSE](LICENSE). Use them, fork them, rename them, put them in your
own bag.
