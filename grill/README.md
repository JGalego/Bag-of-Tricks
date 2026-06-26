<p align="center">
  <img src="logo.png" alt="grill" width="420">
</p>

An answer arrives sounding confident — clean prose, a firm conclusion, no visible
seams. So you trust it. Then production, or a reviewer, or the next model in the
chain finds the assumption it never stated, the edge case it skipped, the claim
with no source behind it. grill is the interrogation room you put the answer
through *before* it walks out the door: sit it down, turn the lamp on, and ask
the questions it was hoping you wouldn't.

Point it at an answer. grill cross-examines it across six angles — hidden
assumptions, missing edge cases, internal contradictions, unsupported claims,
overconfidence, and "what would change your mind?" — generating the sharpest
follow-up each angle allows, then (optionally) running them against Claude to
report, per angle, whether the answer **holds**, goes **weak**, gets **shaky**,
or **cracks**.

It comes in two halves:

- **`SKILL.md`** — a [Claude Code / agent skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
  that tells the model to interrogate an answer across these angles instead of
  nodding along to it — a built-in cross-examiner for any draft answer or another
  model's output.
- **`grill.py`** — a zero-dependency CLI that prints the interrogation plan
  offline (`--dry-run`), or runs the questions against a model (the default when
  an API key is present) and reports where the answer cracked. It talks to
  Anthropic, OpenAI-compatible, and Gemini backends via each provider's official
  SDK (`pip install anthropic` / `openai` / `google-genai`), lazily imported so
  you install only the one you use.

## the interrogation angles

| angle | what it asks |
|-------|--------------|
| `assumptions` | what unstated assumptions is this leaning on, and what if one is false? |
| `edge-cases` | which inputs, scales, or conditions does it quietly fail to cover? |
| `contradictions` | does the answer fight itself anywhere? |
| `sources` | what's the source? which claims are asserted but unsupported? |
| `overconfidence` | where is it more certain than the evidence earns? |
| `falsifiability` | what would change your mind? what would prove this wrong? |

## usage

```bash
# see the questions grill would ask — no key, no network, no tokens
echo "The feature is fully tested and bug-free." | python3 grill.py --dry-run
python3 grill.py answer.txt --dry-run
python3 grill.py answer.txt --question "Is this migration safe?" --dry-run

# actually grill it against a model (needs one API key + that provider's SDK)
export ANTHROPIC_API_KEY=sk-ant-...   # or OPENAI_API_KEY, or GEMINI_API_KEY
python3 grill.py answer.txt --question "Is this migration safe?"
cat answer.txt | python3 grill.py
python3 grill.py answer.txt --angles assumptions,sources

# pick a provider / model explicitly (otherwise auto-detected from your key)
python3 grill.py answer.txt --provider openai --model gpt-4o
python3 grill.py answer.txt --provider gemini
```

Each angle runs as an **independent** call (in parallel), so it's fast and one
angle can't bias another.

## what you get

```
── cross-examination ───────────────────────────────────────────────
  ✗ sources          [CRACKS]
      asks:    "bug-free" — what's the source? When was the last run, and
               against which suites?
      reveals: The claim is asserted with no evidence; the honest version is
               "no known open bugs as of the last run."
  ✓ contradictions   [HOLDS]
      asks:    Do any two claims here disagree?
      reveals: Internally consistent.
  ...

verdict: 1/6 angles cracked it. worst: CRACKS
```

### flags

| flag | does |
|------|------|
| *(default)* | run the angles against Claude, print the cross-examination, exit non-zero if any angle goes shaky/cracks |
| `--dry-run` | print the interrogation plan (angles + questions) without calling the API — no key, no deps |
| `--question "..."` | give grill the original question/context the answer responds to |
| `--angles a,b,c` | restrict to a subset of angles (default: all six) |
| `--provider P` | `anthropic`, `openai`, or `gemini` (default: auto-detect from whichever key is set) |
| `--model ID` | model id to grill with (default: the provider's default) |

A clean grilling (everything `holds`/`weak`) exits `0`; any `shaky`/`cracks`
exits `1`, so you can gate on it.

## install

From the repo root, [`just`](https://github.com/casey/just) symlinks the CLI onto
your `PATH` and the [skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
into `~/.claude/skills/`:

```bash
just install grill
echo "Trust me, it scales fine." | grill --dry-run
```

Or run it in place: `python3 grill.py`.

## honest notes

- A real run needs an API key — any one of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
  or `GEMINI_API_KEY`, plus that provider's SDK (`pip install anthropic` / `openai` / `google-genai`). Without
  a key, grill tells you so and points at `--dry-run`, which always works with
  zero dependencies and no network.
- It's a model questioning an answer — treat findings as **strong leads, not
  proofs**. A sharp follow-up is a place to look, not a final verdict.
- grill cross-examines the *answer text*. It can't run your code, check your data,
  or follow the links — pair it with
  [`bluff`](https://github.com/JGalego/Bag-of-Tricks/tree/main/bluff) (do the
  citations resolve?) and its cousin
  [`strawman`](https://github.com/JGalego/Bag-of-Tricks/tree/main/strawman)
  (which red-teams the *prompt* instead of the answer).
