---
name: grill
description: Adversarially interrogate an answer before trusting it — generate probing follow-up questions that attack its weak points across hidden assumptions, missing edge cases, internal contradictions, unsupported claims ("what's the source?"), overconfidence, and "what would change your mind?", then optionally run them against Claude to see whether the answer holds up or cracks. Use to stress-test a draft answer or another model's output before you ship or trust it.
---

# grill

**put it in the hot seat.**

grill takes an answer and cross-examines it. It does not improve the answer or
agree with it — it interrogates it from a fixed set of angles, asks the sharpest
follow-up each angle allows, and reports where the answer holds up and where it
cracks under questioning. Run it on a draft answer (yours or another model's)
*before* you trust it, not after someone downstream finds the hole.

## When to use

- "Stress-test / pressure-test / poke holes in this answer."
- "Is this conclusion actually sound? What am I missing?"
- Vetting another model's output before you act on it.
- A self-check on a draft answer before you ship it.

## Rules — the interrogation angles

When grilling an answer, work through these distinct angles. Ask one pointed
follow-up per angle; don't soften it.

1. **assumptions** — What unstated assumptions is the answer leaning on? Name the
   load-bearing one and ask what happens if it's false.
2. **edge-cases** — Which inputs, scales, or conditions does it quietly fail to
   cover? Drag a concrete boundary case into the light.
3. **contradictions** — Does it fight itself anywhere? Quote the two parts that
   disagree and ask which one is meant.
4. **sources** — Which claims are asserted but unsupported? For the strongest
   one, ask plainly: *what's the source?*
5. **overconfidence** — Where is it more certain than the evidence earns? Force it
   to state its actual confidence and why.
6. **falsifiability** — *What would change your mind?* If nothing could, that's a
   red flag, not a strength.

Then deliver a verdict per angle: **holds**, **weak**, **shaky**, or **cracks**.

## What grill is NOT

- It is **not** a rewriter. It asks the hard questions; it doesn't patch the
  answer for you.
- It is **not** a yes-man. A flattering pass is a failed grilling — if the answer
  survives an angle honestly, say `holds`; if it doesn't, say so plainly.
- It is **not** a proof. It's a model questioning an answer — treat findings as
  strong leads to chase, not verdicts to paste.

## Example

> **Answer under examination:** "The feature is fully tested and bug-free, so we
> can ship it Friday."

grill generates:

- **assumptions** — *"Fully tested" assumes the test suite covers the failure
  modes that matter. What's the coverage on the payment path, and were the
  integration cases exercised or just the units?*
- **sources** — *What's the basis for "bug-free"? No software is bug-free; what
  you have is "no known open bugs as of the last run." Which is it?*
- **edge-cases** — *Does "tested" include the concurrent-write and timeout cases,
  or only the happy path?*
- **falsifiability** — *What would you have to see in the next 24h to call off the
  Friday ship? If the answer is "nothing," the claim isn't being tested.*

## Output

Deliver the angles with their pointed question and holds/weak/shaky/cracks
verdict, not a narration of the interrogation. Don't explain that you ran
`grill.py`. No preamble, and no closing "overall" unless a one-line verdict
genuinely changes what to do next.

## Companion tool

`grill.py` in this folder runs this mechanically. Pipe an answer through it for
the interrogation plan (`grill.py answer.txt --dry-run` — the angles and the
concrete questions it would ask, zero dependencies, no network), add
`--question "..."` to give it the original prompt for context, or drop `--dry-run`
(with `pip install anthropic` and an `ANTHROPIC_API_KEY`) to actually run the
questions against Claude and get a per-angle verdict on whether the answer
cracked.

Pairs with [`strawman`](https://github.com/JGalego/Bag-of-Tricks/tree/main/strawman),
its cousin: strawman red-teams a *prompt*, grill cross-examines an *answer*.
Reach for [`bluff`](https://github.com/JGalego/Bag-of-Tricks/tree/main/bluff) to
check whether the answer's links and citations are even real, and
[`alibi`](https://github.com/JGalego/Bag-of-Tricks/tree/main/alibi) /
[`fold`](https://github.com/JGalego/Bag-of-Tricks/tree/main/fold) as relatives in
the verification family.
