---
name: strawman
description: Red-team a prompt or system message before shipping — adversarially attack it across jailbreak, instruction-injection, scope-derailment, prompt/secret-extraction, and ambiguity, then report where it cracks, how badly, and how to harden it. Use when asked to stress-test, harden, audit, or find weaknesses in a prompt or system message.
---

# strawman

**argue with yourself before the internet does.**

strawman points an adversarial model at a target prompt and tries to break it,
then reports per-lens findings (cracked? severity? example attack? fix?). Run it
before shipping a system prompt, not after a user finds the hole.

## When to use

- "Harden / stress-test / red-team this prompt (or system message)."
- "What are the weaknesses in this prompt?"
- "Could someone jailbreak / prompt-inject / extract the system prompt here?"
- A pre-ship gate for any prompt that faces untrusted input.

## How to run it

Needs `ANTHROPIC_API_KEY` and the `anthropic` SDK (`pip install anthropic`).
If installed on the `PATH` (via `just install strawman`):

```bash
strawman my_system_prompt.txt              # full battery
strawman prompt.txt --attacks jailbreak,injection
cat prompt.txt | strawman                  # from stdin
strawman prompt.txt --dry-run              # show the attacks, no API call / key
```

Otherwise run it from the bag-of-tricks repo: `python3 strawman/strawman.py`.

## Reading the result

- Each lens reports `cracked`, a `severity` (none→critical), the example
  `attack`, what breaks, and a suggested `fix`.
- Exit code is **non-zero if any HIGH or CRITICAL** weakness is found — usable as
  a CI gate.
- Treat findings as strong leads, not proofs (a model judging a model); read the
  fixes before applying them.

See `README.md` in this folder for the full reference.
