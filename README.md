# bag of tricks

> a small bag of clever hacks for people who work with LLMs all day.

Four single-idea tools. Each lives in its own folder, does one thing, installs in
seconds, and has a catchphrase it has to live up to. Inspired in *tone* (not
substance) by [caveman](https://github.com/juliusbrussee/caveman) and
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
prompts, they're easy to break, and they guess when they should ask. Each trick
takes exactly one of those on.

Everything here is Python 3.9+, mostly standard library. `deadpan`, `snitch`, and
`interrobang` have **zero dependencies**. `strawman` needs the `anthropic` SDK
(and only to actually attack — it has a `--dry-run` that needs nothing).

```bash
git clone <this repo>
cd bag-of-tricks

# try the cheapest trick first — no API key needed
echo "Certainly! I'd be happy to help. Here is the answer: 42 🎉" | python3 deadpan/deadpan.py
# -> The answer: 42
```

Each folder has its own README with the full pitch and usage.

## development

Quality is enforced with [ruff](https://docs.astral.sh/ruff/) (lint + format)
and [pytest](https://docs.pytest.org/) — each trick has a `test_<trick>.py`
beside it. Everything runs with no network and no API key (`strawman`'s tests
stub the SDK).

```bash
make install      # pip install -r requirements-dev.txt
make check        # what CI runs: ruff check + ruff format --check + pytest
make fmt          # auto-format
make test         # just the tests
```

Or directly: `ruff check .`, `ruff format .`, `pytest`.

CI runs `make check` on every push and PR across Python 3.9–3.12
(see [.github/workflows/ci.yml](.github/workflows/ci.yml)).

## license

MIT — see [LICENSE](LICENSE). Use them, fork them, rename them, put them in your
own bag.
