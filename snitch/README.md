<p align="center">
  <img src="logo.png" alt="snitch" width="420">
</p>

You wrote a 12-line prompt. Your agent framework sent the model 4,000 tokens of
system prompt, six tool schemas you forgot you registered, three injected
`<system-reminder>` blocks, and a memory dump. You just can't see any of it.

snitch is a transparent proxy that sits between your code and the LLM API. It
logs the **exact bytes** going upstream — system prompt, every tool schema, every
message, every injected reminder — then forwards the request unchanged and
streams the response straight back. Your agent doesn't know it's there. You do.

Zero dependencies. Standard-library Python 3.9+. Provider-agnostic — it forwards
to whatever upstream you point it at and never looks at your credentials.

> Install with [`just`](https://github.com/casey/just): `just install snitch`
> puts `snitch` on your `PATH`. Or run `python3 snitch.py` straight from this
> folder — the examples below do the latter.

## use it in 3 steps

```bash
# 1. run the snitch (defaults to forwarding api.anthropic.com)
python3 snitch.py --port 8787

# 2. point your SDK at the proxy instead of the real API
export ANTHROPIC_BASE_URL=http://localhost:8787

# 3. run your agent normally. watch the truth scroll by in the console,
#    or open the web UI:  http://localhost:8788
```

For another provider, set its upstream and its base-url env var:

```bash
python3 snitch.py --upstream https://api.openai.com --port 8787
export OPENAI_BASE_URL=http://localhost:8787/v1
```

## what you see

```
────────────────────────────────────────────────────────────────────────
  #1  →  /v1/messages
────────────────────────────────────────────────────────────────────────
  model  claude-opus-4-8
  system (~812 tok)
    You are a helpful coding assistant operating inside …
  tools  3 (~410 tok of schema): read_file, run_bash, web_search
  messages  2 turn(s):
      user.text (~6 tok)
        what time is it?
      user.tool_result (~140 tok)
        <system-reminder> the user's timezone is …
  params  {"max_tokens": 4096, "stream": true}
```

Every request is numbered. Token counts are rough (~4 chars/token) but enough to
spot the 800-token system prompt you didn't write.

## explore in the browser

The console scrolls; the web UI lets you scroll *back*. It starts automatically
on **http://localhost:8788** alongside the proxy — open it and you get:

- a live list of every captured request (#, method, path, model, message/tool
  counts, stream flag, and the upstream response status), newest first;
- click any request to open it — **collapsible sections** for the system prompt,
  tools (each schema folds open on its own), the message turns, params, and the
  raw request JSON, with **expand-all / collapse-all** buttons;
- **JSON syntax highlighting** on every schema/params/raw view (a tiny built-in
  highlighter — no CDN, works offline);
- **role + block icons** so you can skim a transcript at a glance — ⚙️ system,
  🧑 user, 🤖 assistant, 🔧 tool_use, ↩️ tool_result, 🧠 thinking, 🖼️ image;
  collapsed messages keep their role but preview the **actual text** (with 🧠/🔧
  hints when a turn also thought or called a tool); tool turns surface
  `↩️ tool_result` / `🔧 <tool>` in the preview so they're not mistaken for plain
  messages;
- a **raw toggle** to flip the whole detail pane between the structured view and
  the pretty-printed raw request JSON;
- a filter box that matches on path, model, or anything in the body.

It polls in the background, so new requests appear as your agent makes them. The
last 1,000 requests are kept in memory (it's a debug tool — nothing is persisted
unless you also pass `--log`). Disable the UI with `--no-ui`, or move it with
`--ui-port`.

## flags

| flag | effect |
|------|--------|
| `--port N` | proxy listen port (default `8787`) |
| `--ui-port N` | web UI port (default `8788`) |
| `--no-ui` | don't start the web UI |
| `--upstream URL` | where to forward (default `https://api.anthropic.com`) |
| `--log FILE` | also append each request as one JSON object per line (`.jsonl`) |
| `--full` | don't truncate long bodies; also dump full tool schemas (console) |
| `--quiet` | no console output — the UI and `--log` still capture everything |

## capture for later

```bash
python3 snitch.py --log run.snitch.jsonl --quiet
# ... run your agent ...
# then inspect:
python3 -c "import json;[print(json.loads(l)['body'].get('model')) for l in open('run.snitch.jsonl')]"
```

Each line is `{"path": ..., "method": ..., "body": {…the full request…}}`.

## skill

snitch also ships a [skill](https://docs.claude.com/en/docs/agents-and-tools/skills)
(`SKILL.md`); `just install snitch` drops it in `~/.claude/skills/snitch/` so
Claude Code reaches for snitch when you ask it to debug what an agent actually
sent.

## honest limits

- It binds to `127.0.0.1` only — both the proxy and the UI are **local debug
  tools**, not gateways. Don't put them on the open internet.
- It forwards your auth headers untouched (that's the point) but never logs them.
- Streaming (SSE) responses pass through fine — it relays the body in chunks.
- snitch is about what your agent **sends**. It captures each request in full and
  records the response *status code*, but doesn't buffer response bodies (so it
  never gets in the way of a streaming reply). The UI shows the request; the
  reply you read from your own client.
- It's a proxy, not a man-in-the-middle for TLS: you point your client at it over
  plain HTTP locally, and it makes the HTTPS call upstream for you.
