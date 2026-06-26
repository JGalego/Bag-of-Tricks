<p align="center">
  <img src="logo.png" alt="squeeze" width="420">
</p>

Bring the text in, sit it down, put the squeeze on it. Model prose is more
predictable than human writing — so when you compress a passage next to a pile
of known-AI text it *folds in tight*, and next to human text it resists.
`squeeze` measures that gap with [Normalized Compression
Distance](https://en.wikipedia.org/wiki/Normalized_compression_distance) and
reports which corpus the candidate caves toward. It never reads a word; it just
weighs the bytes. It's the compression cousin of thinkst's
[`zippy`](https://github.com/thinkst/zippy) — a parlor trick with a confidence
band, not a forensics lab.

It comes in two halves:

- **`SKILL.md`** — a [Claude Code / agent skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
  that teaches the model to read the verdict honestly: the lean, the confidence,
  the two distances, and the hedge — never "proof".
- **`squeeze.py`** — a zero-dependency `stdin->stdout` detector (stdlib
  `lzma`/`zlib`/`bz2` only). Feed it text, get back a lean, an AI-likelihood
  score, and the distances behind it.

## the squeeze

```bash
echo "Certainly! It's important to note that we must delve into this rich tapestry. In conclusion, leverage robust, seamless solutions." \
  | python3 squeeze.py
# likely AI-generated (low) — ai-ncd 0.82 < human-ncd 0.87 — heuristic, not proof

# the full breakdown, with a bar (the headline example, in detail)
echo "Certainly! It's important to note that we must delve into this rich tapestry. In conclusion, leverage robust, seamless solutions." \
  | python3 squeeze.py --report
# likely AI-generated (low) — ai-ncd 0.82 < human-ncd 0.87 — heuristic, not proof
#
#   AI-likelihood   ███████████████····· 77/100
#   distance to AI corpus      0.8219  (lower = closer)
#   distance to human corpus   0.8670
#   margin (human - ai)        +0.0451  (positive leans AI)
#   compressor                 lzma   words 20   chunks 1

# the structured verdict
python3 squeeze.py --json < draft.md
```

### flags

| flag             | does                                                          |
|------------------|---------------------------------------------------------------|
| *(default)*      | print the one-line verdict (lean + confidence + distances)    |
| `--report`       | full NCD breakdown with an AI-likelihood bar                  |
| `--score`        | print just the integer AI-likelihood (0-100)                 |
| `--json`         | emit the structured dict                                     |
| `--algo`         | compressor: `lzma` (default, best signal), `zlib` (fastest), `bz2` |
| `--chunk N`      | window size in chars for long inputs (default: 2000)         |
| `--ai-corpus`    | override the known-AI reference corpus with your own file    |
| `--human-corpus` | override the known-human reference corpus                    |
| `--max N`        | exit 1 if AI-likelihood > N (gate prose in CI)               |

## how it works

[Normalized Compression Distance](https://en.wikipedia.org/wiki/Normalized_compression_distance):

```
NCD(x, y) = ( C(xy) − min(C(x), C(y)) ) / max(C(x), C(y))
```

where `C(·)` is the compressed byte-length. It runs ~0 when `x` and `y` share a
lot of structure, ~1 when they share none. `squeeze` computes `NCD(candidate,
AI_CORPUS)` and `NCD(candidate, HUMAN_CORPUS)` and reports which is smaller —
the candidate folds more tightly into whichever pile it most resembles. The
**margin** between them becomes the lean; its size and the text length set the
confidence band.

The bundled corpora are tiny, **hand-written** caricatures — stereotypical
assistant prose vs. idiosyncratic human writing. Note the irony worth owning:
the "human" pile was itself written by an AI doing an impression of casual human
writing, which is exactly the thing this tool is meant to distrust. They work as
a demo, not as ground truth. For any verdict you mean to rely on, pass larger,
*real*, on-domain samples with `--ai-corpus` / `--human-corpus` — more reference
text is the single biggest accuracy win, and the only path to a defensible call.

## install

From the repo root, [`just`](https://github.com/casey/just) symlinks the CLI onto
your `PATH` and the [skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
into `~/.claude/skills/`:

```bash
just install squeeze
echo "Certainly! Let's delve into this rich tapestry." | squeeze
```

Or run it in place: `python3 squeeze.py`.

## the detection family

Three lenses on one question — *did a machine write this?*

- [`tell`](https://github.com/JGalego/Bag-of-Tricks/tree/main/tell) reads the
  **words** — overused vocabulary, clichés, structure.
- [`mugshot`](https://github.com/JGalego/Bag-of-Tricks/tree/main/mugshot)
  matches **style** to a family — *whose* prints are these?
- `squeeze` weighs the **bytes** — word-blind and a fast, independent second
  opinion. When `tell` and `squeeze` agree, lean harder.

## a parlor trick, not proof

There is no watermark, no logprobs, no ground truth here — only how the bytes
fold. Short passages, code, tables, non-English text, heavily edited AI, AI
told to write like a human, and a human writing like a bot all throw it off.
Read "likely AI-generated" as "the bytes *smell* machine-made," never as "a
model wrote this." Fun at parties; inadmissible in court.
