---
name: bluff
description: Verify that the URLs and citations in an answer actually resolve, catching hallucinated or dead links before you trust or ship them. Extract every link (bare and markdown), check each over the network, and flag the ones that don't exist. Use when an LLM produced links/citations and you need to confirm they're real, not plausible-looking fiction.
---

# bluff

**call its bluff.**

LLMs are fluent liars about URLs. They produce a citation that *looks* exactly
right — correct domain, plausible path, confident tone — and it 404s, or never
existed. When this skill is active, don't take a link on faith: pull every URL
out of the answer and confirm it resolves before presenting it as a source.

## What it checks

- **Bare URLs** — `https://…` anywhere in the text.
- **Markdown links** — the target inside `[text](url)`.
- For each: does it actually resolve? 2xx/3xx = real, anything else (404, DNS
  failure, timeout, connection refused) = a bluff to flag.

It de-dupes and ignores trailing sentence punctuation, so a URL ending a
sentence isn't mangled.

## Example

> **Answer under review:** "Per the [official spec](https://example.com/spec)
> and https://docs.example.com/v2, the limit is 100."
>
> **bluff:** ✓ [200] https://example.com/spec — ✗ [404]
> https://docs.example.com/v2. The second citation does not exist; do not ship
> it as a source.

## Output

Deliver the link check, not a description of running it. Don't narrate running
`bluff.py` — the tool card already shows it. List each URL with its ✓/✗ and
status, surface the bluffs first, and stop. No preamble, no closing paragraph.

## Companion tool

`bluff.py` in this folder does this mechanically. Pipe an answer in and it
reports each link with a ✓/✗, status code, and error.

- It **needs network** to actually verify links.
- `--dry-run` extracts and lists the URLs with **no network at all** — handy
  when you just want to see what was cited. Extraction is always offline.
