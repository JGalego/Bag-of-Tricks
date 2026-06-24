---
name: snitch
description: Inspect the exact bytes an LLM agent or SDK sends upstream — the full system prompt, every tool schema, and all messages — via a local transparent proxy with a live web UI. Use when debugging why an agent misbehaves, auditing hidden or injected prompt/tools, checking how much context a framework actually sends, or verifying the real request behind an SDK call.
---

# snitch

**see what your agent actually said behind your back.**

snitch is a transparent proxy that logs the exact request your code sends to an
LLM API, then forwards it unchanged. Use it to reveal the system prompt, tool
schemas, and injected context a framework hides.

## When to use

- "Why is my agent doing X?" → see the actual prompt/tools it was sent.
- "Is something injecting instructions/tools?" → audit the raw request.
- "How many tokens of system prompt / tools is this framework adding?"
- "What does the SDK actually send for this call?"

## How to run it

If installed on the `PATH` (via `just install snitch`):

```bash
snitch --port 8787            # starts proxy + web UI on http://localhost:8788
```

Otherwise run it from the bag-of-tricks repo: `python3 snitch/snitch.py`.

Then point the client at the proxy and run the agent normally:

```bash
export ANTHROPIC_BASE_URL=http://localhost:8787   # or OPENAI_BASE_URL, etc.
```

- Console prints each request live; the **web UI** (`http://localhost:8788`)
  lets you scroll back, expand, and filter captured requests.
- `--upstream URL` forwards to another provider; `--log FILE` appends each
  request as JSON; `--quiet` silences the console (UI + log still capture);
  `--no-ui` disables the web UI.

It captures the **request** in full and records the response status (it doesn't
buffer response bodies). It binds to `127.0.0.1` only — a local debug tool.

## Output

If you run snitch or report what it captured, deliver the captured request
plainly — don't narrate the proxy mechanics or wrap the bytes in analysis the
user didn't ask for, and point them at the web UI for the rest. No preamble, no
closing summary.

See `README.md` in this folder for the full reference.
