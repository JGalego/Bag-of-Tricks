<p align="center">
  <img src="logo.png" alt="alibi" width="420">
</p>

A RAG pipeline hands you a fluent, confident answer. Most of it is lifted
straight from the documents you retrieved — and one sentence isn't. It sounds
just as sure as the rest, but nothing in your sources says it. That's the
sentence that ships a hallucination to your users. alibi asks each claim the
only question that matters: where's your corroboration?

It comes in two halves:

- **`SKILL.md`** — a [Claude Code / agent skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
  that tells the model to treat every sentence of a generated answer as a claim
  that must be backed by the provided sources, and to flag the ones that aren't.
- **`alibi.py`** — a zero-dependency, deterministic checker. Give it an answer
  and one or more source documents; it splits the answer into sentence-level
  claims, scores each by lexical overlap with the sources, and flags every claim
  that falls below the support threshold. Verdicts to stdout, summary to stderr.
  No model calls by default — a cheap, fast first pass; an optional `--llm` mode
  (with `--provider` / `--model`) escalates to a semantic, model-backed grounding
  check when lexical overlap isn't enough.

## the check

```bash
# answer from a file, sources from a file
python3 alibi.py answer.txt --source sources.txt
# SUPPORTED   [0.94] The Eiffel Tower is 330 metres tall.
# UNSUPPORTED [0.00] It is painted bright orange every spring.
# stderr: [alibi] 2 claim(s): 1 supported, 1 unsupported

# answer on stdin, source inline
echo "The capital of France is Paris." | python3 alibi.py --source-text "Paris is the capital of France."

# multiple sources — the whole corpus is the ground truth
python3 alibi.py answer.txt --source doc1.txt --source doc2.txt

# gate a RAG pipeline — exits 1 if any claim is unsupported, prints nothing
python3 alibi.py answer.txt --source sources.txt --check && echo "grounded — safe to ship"

# just the claims that don't check out
python3 alibi.py answer.txt --source sources.txt --report
```

### flags

| flag             | does                                                          |
|------------------|--------------------------------------------------------------|
| *(default)*      | per-claim verdict + score to stdout, summary to stderr, exit 0 |
| `--source FILE`  | a source / ground-truth file (repeatable)                    |
| `--source-text T`| source text passed inline (repeatable)                       |
| `--threshold F`  | support cutoff; below it a claim is UNSUPPORTED (default 0.5) |
| `--check`        | print nothing; exit 1 if any claim is unsupported (gates pipelines) |
| `--report`       | print only the unsupported claims to stdout, exit 0          |
| `--json`         | emit structured per-claim results (claim, score, supported; plus reason with `--llm`) |

### how it scores

It's **lexical overlap**, nothing fancier. Each claim is tokenized to lowercased
content words (a small stopword set and punctuation are stripped), and the score
is the fraction of those words — sharpened by adjacent word-pair (bigram)
overlap — that appear in the source corpus. Meet the threshold and the claim is
SUPPORTED; fall short and it's UNSUPPORTED. Sentences with no real content
("Sure!") score neutral and pass.

This means a faithful **paraphrase** that reuses none of the source's words can
read as weakly supported, and a sentence that parrots the source's vocabulary in
nonsense order can read as supported. alibi is the cheap, deterministic first
pass — for borderline claims, escalate to a model judge.

## install

From the repo root, [`just`](https://github.com/casey/just) symlinks the CLI
onto your `PATH` and the [skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
into `~/.claude/skills/`:

```bash
just install alibi
alibi answer.txt --source sources.txt
```

Or run it in place: `python3 alibi.py answer.txt --source sources.txt`.

## use them together

Pairs with [bluff](https://github.com/JGalego/Bag-of-Tricks/tree/main/bluff):
bluff checks the *links* in an answer actually resolve; alibi checks the *claims*
are actually backed by your sources. bluff calls the bluff on the citations;
alibi makes the story produce its alibi. Run both before you trust an LLM
answer.

## not a fact-checker

alibi only knows the sources you hand it. "Unsupported" means *not in these
documents* — not *false*. A true statement with no source still gets flagged
(that's the point: you never grounded it), and it's lexical, so paraphrase can
fool it in either direction. Treat a clean pass as "every claim echoes the
sources," not "every claim is true."
