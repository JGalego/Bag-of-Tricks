<p align="center">
  <img src="logo.png" alt="launder" width="420">
</p>

The text looks fine. But somewhere in those bytes is a zero-width space the
model dropped mid-word, a curly quote, an em-dash, a non-breaking space — none
of it visible, all of it a fingerprint that says *a machine touched this*. Paste
it into a code review, a commit message, or a strict JSON parser and it gives
you away, corrupts the diff, or throws. launder runs the bytes through the wash:
the prints come out, the words stay exactly as they were.

It comes in two halves:

- **`SKILL.md`** — a [Claude Code / agent skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
  that tells the model to scrub the typographic giveaways out of text before it
  hands it over — without rewriting a single word.
- **`launder.py`** — a zero-dependency `stdin->stdout` filter that strips
  zero-width and invisible characters, straightens smart quotes, normalizes
  em/en dashes and the unicode ellipsis, flattens non-breaking and exotic
  spaces, and drops soft hyphens. Cleaned text to stdout, the summary to stderr.

## the filter

```bash
printf 'he said \xe2\x80\x9chi\xe2\x80\x9d\xe2\x80\x8b' | python3 launder.py
# stdout: he said "hi"
# stderr: [launder] scrubbed 3: 2×smart_quote, 1×zero_width

# gate a pipeline / pre-commit — exits 1 if any fingerprint is present
cat draft.md | python3 launder.py --check && echo "clean bytes"

# just list what it found, by category
python3 launder.py --report < draft.md
# smart_quote   2   @8
# zero_width    1   @12

# normalize confusable look-alikes too (opt-in, lossy)
echo "sсam" | python3 launder.py --homoglyphs   # that 'с' is Cyrillic
# stdout: scam
```

### flags

| flag           | does                                                        |
|----------------|------------------------------------------------------------|
| *(default)*    | clean to stdout, summary to stderr, exit 0                  |
| `--check`      | print nothing; exit 1 if any fingerprint present (gates pipelines) |
| `--report`     | list findings by category (count + first offset), exit 0   |
| `--json`       | emit a structured summary (counts + findings) as JSON       |
| `--homoglyphs` | also normalize confusable Cyrillic/Greek look-alikes (opt-in; lossy) |

### what it scrubs

| category       | what                                                       |
|----------------|------------------------------------------------------------|
| `zero_width`   | U+200B ZWSP, U+200C, U+200D, U+2060 word joiner, U+FEFF BOM — stripped |
| `soft_hyphen`  | U+00AD soft hyphen — removed                                |
| `smart_quote`  | `“ ” „` → `"`, `‘ ’ ‚` → `'`                                |
| `em_dash`      | `—` → `--` (default)                                        |
| `en_dash`      | `–` `−` → `-`                                               |
| `ellipsis`     | `…` (U+2026) → `...`                                        |
| `exotic_space` | U+00A0 NBSP, U+2009 thin, U+202F narrow NBSP, U+2007, … → a plain space |
| `homoglyph`    | Cyrillic/Greek look-alikes (`а`→`a`, `о`→`o`, `р`→`p`) — **opt-in** |

Em-dash maps to `--` by default (an em-dash is two hyphens' worth of pause);
en-dash maps to `-`. Findings carry their offsets against the original text, and
clean ASCII round-trips byte-for-byte with an empty findings list.

## install

From the repo root, [`just`](https://github.com/casey/just) symlinks the CLI
onto your `PATH` and the [skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
into `~/.claude/skills/`:

```bash
just install launder
printf 'em—dash\xe2\x80\xa6' | launder
```

Or run it in place: `python3 launder.py`.

## use it with tell

`tell` reads the *words* and tells you why the prose sounds like a model wrote
it; launder scrubs the *bytes* that give it away typographically. Run
[tell](https://github.com/JGalego/Bag-of-Tricks/tree/main/tell) to diagnose the
AI smell, then launder to wash out the invisible and typographic prints. Two
halves of cleaning up after a model: one for the prose, one for the bytes.

## not a cloak

launder removes formatting artifacts — zero-width characters, smart quotes,
fancy dashes. It does **not** rewrite a single word, and it does **not** make
machine-written text pass as human or defeat an AI/plagiarism detector. The
prose still reads like the model wrote it. Treat a clean pass as "the bytes look
hand-typed," not "this can't be detected as AI."
