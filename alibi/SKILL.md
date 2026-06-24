---
name: alibi
description: Verify that an answer's claims are actually grounded in the provided sources, flagging fabricated or unsupported statements before you trust the output. Split the answer into sentence-level claims and check each one for lexical support in the source documents. Use after RAG or summarization, before trusting or shipping the result, to catch the sentence the model invented that the sources never said.
---

# alibi

**does the story check out?**

An alibi is only as good as the evidence that backs it. When this skill is
active, treat every sentence of a generated answer as a claim that has to be
corroborated by the sources you actually gave the model — not by what sounds
plausible. A confident sentence with no support in the sources is a fabrication
waiting to be shipped. Make it produce its alibi.

## Rules

1. **Every claim needs a corroborating source.** Split the answer into
   sentences and treat each as a separate claim. A claim is only as trustworthy
   as the source text that backs it.
2. **No source, no alibi — flag it.** A sentence whose content has no support in
   the provided documents is unsupported. Surface it; don't let it pass just
   because it reads well.
3. **Check against YOUR sources, not the world.** This is lexical
   corroboration, not a fact-checker of the universe. A claim can be true in
   reality and still be *unsupported* here because you never handed the model a
   source for it — that gap is exactly what you want to see.
4. **Score, then judge.** Each claim gets a support score (how much of its
   content the sources echo). Below the threshold = unsupported. Tune the
   threshold to the cost of a hallucination slipping through.
5. **Greetings and filler are neutral.** A sentence with no real content
   ("Sure!", "Here you go.") has nothing to corroborate — skip it, don't flag
   it.

## What alibi is NOT

- It is **not** a fact-checker against the open world. It only knows the sources
  you give it. "Unsupported" means *not in these documents*, not *false*.
- It is **not** semantic. It is lexical overlap, so a faithful paraphrase that
  reuses none of the source's words can read as weakly supported. For borderline
  claims, pair it with a model judge — let alibi do the cheap, deterministic
  first pass and escalate only the close calls.
- It is **not** a grader of writing quality. A beautifully written claim with no
  source is still a bluff.

## Example

> **Sources:** "The Eiffel Tower is 330 metres tall and was completed in 1889."
>
> **Answer under review:** "The Eiffel Tower is 330 metres tall. It is painted
> bright orange every spring."
>
> **alibi:** ✓ the height claim is corroborated by the source — ✗ the painting
> claim has no support in the source; do not present it as grounded.

## Output

Deliver the verdict, not a write-up of how you reached it. Don't narrate running
`alibi.py` — the tool card already shows it. List the flagged claims with their
SUPPORTED/UNSUPPORTED call, lead with the unsupported ones (those are what the
reader acts on), and stop. No preamble, no closing summary of what it all means.

## Companion tool

`alibi.py` in this folder does this mechanically. Feed it the answer plus one or
more `--source` files and it reports each claim with a SUPPORTED/UNSUPPORTED
verdict and score (`alibi.py answer.txt --source sources.txt`), gates a RAG
pipeline (`alibi.py … --check`, exits 1 if any claim is unsupported), lists just
the claims that don't check out (`--report`), or emits structured results
(`--json`).

Pairs with [bluff](https://github.com/JGalego/Bag-of-Tricks/tree/main/bluff):
bluff confirms the *links* in an answer resolve; alibi confirms the *claims* are
backed by your sources. Links real, story grounded — check both before you ship.
