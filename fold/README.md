<p align="center">
  <img src="logo.png" alt="fold" width="420">
</p>

A good poker player doesn't bluff a busted hand — they fold. Models do the
opposite: out of cards, they raise. "This will *definitely* work on *every*
platform, *guaranteed*" reads like a winner and folds the moment you call it.
fold is the honest counterpart to [`bluff`](../bluff): it catches the
overconfident tone — the absolutes, the bare certainty, the *trust me* — so a
weak hand gets played as the honest "I'm not sure" it actually is.

It comes in two halves:

- **`SKILL.md`** — a [Claude Code / agent skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
  that tells the model to fold when the evidence is thin: say "I don't know"
  instead of bluffing, earn its absolutes, and prefer calibrated uncertainty
  over a confident wrong answer.
- **`fold.py`** — a zero-dependency `stdin->stdout` filter (the `--llm` mode needs
  a provider SDK) that flags overconfidence markers in a draft and tags each one
  `[FOLD:type]` so you can
  see exactly where the answer is bluffing. Tagged text to stdout, the summary
  to stderr.

## the filter

```bash
echo "This will definitely always work, guaranteed." | python3 fold.py
# stdout: This will [FOLD:certainty] [FOLD:absolute] work, [FOLD:no_doubt].
# stderr: [fold] 3 tells: 1×absolute, 1×certainty, 1×no_doubt

# gate an "did we overclaim?" check — exits 1 if anything bluffs, prints nothing
cat answer.txt | python3 fold.py --check && echo "calibrated"

# just list the tells, with offsets
python3 fold.py --report < answer.txt
# certainty   definitely   @8
# absolute    always       @19

# a quick confidence-inflation gauge
echo "Obviously this always works, no doubt." | python3 fold.py --score
# [fold] confidence-inflation: 33.33 markers/100w (2 tells)

# let a model judge unearned confidence (catches a bluff with no tell-word)
cat answer.txt | python3 fold.py --llm
```

### flags

| flag        | does                                                          |
|-------------|--------------------------------------------------------------|
| *(default)* | tag markers to stdout, summary to stderr, exit 0             |
| `--check`   | print nothing; exit 1 if any overconfidence marker found     |
| `--report`  | list markers (type + preview + offset) to stdout, exit 0     |
| `--json`    | emit findings as JSON                                        |
| `--score`   | print one confidence-inflation score (markers per 100 words) |
| `--only t1,t2` | restrict to listed marker types                          |
| `--patterns FILE` | merge custom detectors from a JSON file (repeatable, offline only) |
| `--llm`     | judge tone vs. evidence with a model instead of regex        |
| `--provider P` / `--model M` | pick the LLM backend / model id for `--llm`  |

### the model: `--llm`

The regex detectors flag *words* (`always`, `definitely`). `--llm` flags
*statements whose confidence isn't earned by the evidence* — a bluff that uses
no tell-word at all — and leaves genuinely-backed or hedged prose alone. It
judges overconfident **tone relative to evidence**, not whether the facts are
true; calibrated text comes back clean. The model returns `{type, snippet,
reason}` items; each snippet is located verbatim in the original text to compute
offsets and tag it `[FOLD:type]`. A snippet that isn't found verbatim is still
reported as a finding (with `start`/`end` of `-1`) but left untagged. On a
provider error fold writes to stderr and exits 2.

`--llm` speaks Anthropic / OpenAI-compatible / Gemini backends via the vendored
inlined llm backend; pick one with `--provider`/`--model` or the matching
`*_API_KEY` env var. `--llm` ignores `--patterns` (it doesn't use the detector
table). Types: the four built-ins plus `unearned_confidence`.

### custom detectors: `--patterns`

Built-ins are the base; `--patterns FILE` (repeatable) merges your own regexes
on top — affecting offline mode only, not `--llm`. A pattern file is JSON:

```json
{"detectors": {"weasel": "\\b(?:basically|honestly|literally)\\b"}}
```

Each regex is compiled case-insensitively, exactly like the built-ins. A user
entry that reuses a built-in's name **overrides** it. As a fallback, set
`FOLD_PATTERNS` to an `os.pathsep`-separated list of files (used only when no
`--patterns` flag is given):

```bash
echo "This basically always works." | python3 fold.py --patterns weasel.json
export FOLD_PATTERNS=weasel.json:more.json   # fallback when --patterns is absent
```

### what it flags

- **certainty** — bare certainty adverbs: `definitely`, `certainly`,
  `obviously`, `clearly`, `undoubtedly`, `surely`, `absolutely`.
- **no_doubt** — doubt-erasing phrases: `guaranteed`, `100%`, `without a
  doubt`, `beyond any doubt`, `there is no question`.
- **absolute** — sweeping universals: `always`, `never`, `every`, `all`,
  `none`, `everyone`, `nobody`, `impossible`.
- **false_authority** — borrowed confidence: `trust me`, `everyone knows`,
  `it is well known`, `needless to say`, `it goes without saying`.

Matching is case-insensitive. Findings carry their offsets, so the original
text round-trips byte-for-byte around the tags. fold flags **tone**, not
**truth** — it shows you where the draft is bluffing, not whether it's wrong.

## install

From the repo root, [`just`](https://github.com/casey/just) symlinks the CLI
onto your `PATH` and the [skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
into `~/.claude/skills/`:

```bash
just install fold
echo "This is definitely the only correct answer." | fold
```

Or run it in place: `python3 fold.py`.

## use them together

Skill at generation time (the model folds a weak hand instead of bluffing it) +
filter at review time (anything that still overclaims gets tagged before it
ships). Pairs directly with [`bluff`](../bluff): `fold` catches the
overconfident *phrasing*, `bluff` checks whether the citations you stated so
confidently actually resolve.

## not a hedge machine

fold flags overconfidence, but over-hedging is its own failure: an answer
buried in "maybe possibly perhaps it might depend" is just as useless as a
bluff, and harder to read. The goal isn't to strip every confident word — it's
to make sure the confidence is *earned*. Treat a clean pass as "not obviously
bluffing," not "well-calibrated." And remember it reads tone, not facts — a
hedged sentence can still be flat wrong.
