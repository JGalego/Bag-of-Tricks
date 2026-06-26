---
name: mugshot
description: Guess which model or family likely wrote a passage from its stylistic fingerprints, and show the matched tells. Profiles common styles — gpt-ish ("Certainly!", "I'd be happy to", bold headers, numbered listicles), claude-ish (leading "I'll/Let me/Here's", em-dashes, "Great question"), and the universal AI tells (delve, tapestry, "it's not just X, it's Y") — then names the most likely suspect with a confidence band and the prints that matched. Use to ID the probable author of a chunk of AI text. Explicitly a heuristic, not forensic proof.
---

# mugshot

**we know your prints.**

When this skill is active, treat a chunk of text as a suspect at a line-up. Read
its style, match it against the known profiles, and name the family that most
likely wrote it — then show the prints you lifted, so the call is auditable, not
magic. Where `tell` flags the giveaways, mugshot uses those giveaways to *name a
suspect*.

## Rules

1. **Read the prints, not the content.** Authorship lives in style, not subject:
   openers, hedges, headers, list shapes, punctuation habits — not what the text
   is about.
2. **Know the usual suspects.** *gpt-ish*: "Certainly!", "I'd be happy to",
   "It's important to note", "However, it's worth", bolded section headers,
   numbered listicles, "In conclusion", "Overall,". *claude-ish*: leading
   "I'll …", "Let me …", "Here's …", em-dash asides, "Sure,", "Great question",
   warm hedging. *generic-AI*: the universal tells any model leaves — delve,
   tapestry, "navigate the complexities", "it's not just X, it's Y", "in today's
   fast-paced …".
3. **Weigh the prints.** A blatant opener counts more than a stray em-dash. One
   weak print is noise; a cluster of strong ones is a confession. Lean on the
   weight and the spread between suspects, not raw hit counts.
4. **Always show the prints.** Never just announce a verdict. List the specific
   matches that drove it so a reader can disagree.
5. **State the confidence — and the caveat.** Give a band (low / medium / high)
   from how far the top suspect beats the rest, and say out loud that this is a
   guess. When nothing strong matches, the honest verdict is *inconclusive /
   could be human* — say that, don't force an accusation.

## What mugshot is NOT

- It is **not** forensic proof. Even with a model in the loop it's a hunch
  dressed up as a line-up, not a chain of custody.
- It is **not** court-admissible. No watermark, no logprobs, no ground truth —
  just style.
- Models **drift and mimic each other.** Today's gpt-ish phrasing is tomorrow's
  everyone-ish phrasing; fine-tunes and system prompts move the tells around.
- A clever human can **fake any style.** Anyone who has read enough model output
  can stuff a paragraph with "Certainly!" and frame an innocent.

Read a verdict as "this *smells* like X," never "X wrote this."

## Example

> **Text:** Certainly! I'd be happy to help. It's important to note that we
> should weigh the options. In conclusion, the plan is sound.
>
> **Mugshot:** most likely **gpt-ish** (medium confidence). Prints lifted:
> "Certainly!", "I'd be happy to", "It's important to note", "In conclusion".
> Heuristic, not proof — a human could have typed every one of those.

## Output

Deliver the verdict and the lifted prints, not a narration of the line-up. Don't
explain that you ran `mugshot.py` — name the suspect, the confidence band, and
the matched prints, keep the "heuristic, not proof" caveat, and stop. No
preamble, no extra closing.

## Companion tool

`mugshot.py` in this folder runs the line-up. By **default** it asks a real model
(an LLM authorship/stylometry pass) when a provider key is configured, and falls
back to the **offline regex heuristic** otherwise — printing a note that setting
an API key (or `--llm`) unlocks real attribution. Force the path you want:

- `mugshot.py --llm` — force the model-backed pass (fails loudly, exit 2, on a
  provider error; no silent fallback). `--provider` / `--model` pick the backend.
- `mugshot.py --parlor` — force the offline regex heuristic, no network.

Every output mode reads the same verdict dict (`{verdict, confidence, scores,
prints}`) and works for both paths: readable verdict (`mugshot.py`), every
matched print with offsets (`mugshot.py --report`), the full ranked scoreboard
(`mugshot.py --all`), or the structured dict (`mugshot.py --json`).

The parlor lineup is extensible: merge custom prints with `--patterns FILE`
(repeatable) or the `MUGSHOT_PATTERNS` env var (os-path-separator-joined paths),
each a JSON `{"suspects": {"<name>": [[weight, "label", "regex"], ...]}}`.

It pairs with **tell**: `tell` finds the prints (how AI does this read?), mugshot
names the suspect (*whose* prints are these?).
