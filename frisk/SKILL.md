---
name: frisk
description: Pat text down for secrets and PII before it leaves the building. Scan prompts, context, and pasted snippets for API keys, tokens, private keys, JWTs, and emails — then redact or refuse. Use before sending context/prompts that may contain credentials to an LLM or any third party, before pasting logs into an issue, or before piping output anywhere it'll be stored.
---

# frisk

**pat it down before it ships.**

When this skill is active, treat every chunk of text headed to a model, a log,
or a third party as something that might be carrying. Check it at the door.

## Rules

1. **Frisk before you forward.** Before sending context, a prompt, or a pasted
   snippet to an LLM or any external service, scan it for credentials and PII.
2. **Know the shapes.** Watch for AWS keys (`AKIA…`), OpenAI keys (`sk-…`,
   `sk-proj-…`), GitHub tokens (`ghp_…`), Slack tokens (`xox…`), `Bearer …`
   tokens, JWTs (`eyJ….….…`), PEM private-key blocks, and email addresses.
3. **Redact, don't relay.** Replace a found secret with a tag like
   `[REDACTED:aws_key]`. Keep the structure so the model still understands the
   text; lose the secret.
4. **Never echo the secret.** When you report a finding, show its *type* and a
   masked preview (first few chars + `…`) — never the full value, not even to
   confirm it.
5. **When in doubt, stop and ask.** A false positive is cheap; a leaked
   production key is not. Flag it and check before forwarding.

## What frisk is NOT

- It is **not** a vault or a scanner of record. It's a doorman, not a SOC.
- It is **not** lossy on safe text. Redact the credential, keep everything else
  verbatim — the model needs the surrounding context.

## Example

> **Before:** Use this for auth: `AKIAIOSFODNN7EXAMPLE`, and email
> `joe@example.com` if it breaks.
>
> **After:** Use this for auth: `[REDACTED:aws_key]`, and email
> `[REDACTED:email]` if it breaks.

## Companion tool

`frisk.py` in this folder applies these checks mechanically. Pipe any text
through it to redact secrets (`frisk.py`), gate a pipeline (`frisk.py --check`,
exits 1 on a hit), or list findings with masked previews (`frisk.py --report`).
