---
name: salvage
description: Extract and repair valid JSON buried in chatty model output — strip the preamble, the ```json fence, the trailing comma, the // comments, the Python True/False/None, and the smart quotes, then emit clean parseable JSON. Use when a tool, downstream parser, or pipeline needs strict JSON but the source text is prose-wrapped or slightly malformed, or when you are post-processing another model's structured output. Distinct from simply prompting "respond in JSON": salvage assumes the chatter already happened and rips the JSON out of it after the fact.
---

# salvage

**rip the JSON out of the chatter.**

When this skill is active, treat any blob of model output as a haystack and find
the one valid JSON value inside it.

## Rules

1. **Find the first JSON value.** Ignore prose before and after. Strip any
   markdown code fence (```` ```json ````, `~~~`). Take the first `{` or `[`
   and read through its *balanced* matching close — counting depth, never
   counting braces or brackets that live inside string literals.
2. **Repair the usual damage** before parsing: drop trailing commas (`,}`,
   `,]`); strip `//` line comments and `/* */` block comments; rewrite the
   Python literals `True` / `False` / `None` to `true` / `false` / `null`
   (as tokens, not inside strings); normalize smart quotes `“ ” ‘ ’` to `" '`.
3. **Emit only the JSON.** No fence, no commentary, no "here is your JSON".
   Pretty-print by default; compact on request.
4. **If nothing parses, say so.** Don't invent a structure. Report that there
   is no salvageable JSON rather than guessing.

## Example

> **Before:** Certainly! Here's the data:
> ```json
> {
>   "name": "Ada",   // first name
>   "active": True,
> }
> ```
> Let me know if you need anything else!
>
> **After:** `{"name": "Ada", "active": true}`

## Output

Emit only the JSON — that's the whole point. Don't narrate running `salvage.py`,
don't fence it, don't wrap it in "here's the recovered JSON." If nothing parses,
say so in one line. Nothing before the JSON, nothing after.

## Companion tool

`salvage.py` in this folder does exactly this mechanically — pipe any chatty
output through it (`salvage.py`, `--compact`, `--extract-only`) to recover the
JSON without re-prompting the model.
