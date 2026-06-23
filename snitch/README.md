# snitch

> **see what your agent actually said behind your back.**

You wrote a 12-line prompt. Your agent framework sent the model 4,000 tokens of
system prompt, six tool schemas you forgot you registered, three injected
`<system-reminder>` blocks, and a memory dump. You just can't see any of it.

snitch is a transparent proxy that sits between your code and the LLM API. It
logs the **exact bytes** going upstream — system prompt, every tool schema, every
message, every injected reminder — then forwards the request unchanged and
streams the response straight back. Your agent doesn't know it's there. You do.

Zero dependencies. Standard-library Python 3.9+. Provider-agnostic — it forwards
to whatever upstream you point it at and never looks at your credentials.

## use it in 3 steps

```bash
# 1. run the snitch (defaults to forwarding api.anthropic.com)
python3 snitch.py --port 8787

# 2. point your SDK at the proxy instead of the real API
export ANTHROPIC_BASE_URL=http://localhost:8787

# 3. run your agent normally. watch the truth scroll by.
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

## flags

| flag | effect |
|------|--------|
| `--port N` | listen port (default `8787`) |
| `--upstream URL` | where to forward (default `https://api.anthropic.com`) |
| `--log FILE` | also append each request as one JSON object per line (`.jsonl`) |
| `--full` | don't truncate long bodies; also dump full tool schemas |
| `--quiet` | no console output — pair with `--log` for headless capture |

## capture for later

```bash
python3 snitch.py --log run.snitch.jsonl --quiet
# ... run your agent ...
# then inspect:
python3 -c "import json;[print(json.loads(l)['body'].get('model')) for l in open('run.snitch.jsonl')]"
```

Each line is `{"path": ..., "method": ..., "body": {…the full request…}}`.

## honest limits

- It binds to `127.0.0.1` only — it's a **local debug tool**, not a gateway.
  Don't put it on the open internet.
- It forwards your auth headers untouched (that's the point) but never logs them.
- Streaming (SSE) responses pass through fine — it relays the body in chunks.
- It's a proxy, not a man-in-the-middle for TLS: you point your client at it over
  plain HTTP locally, and it makes the HTTPS call upstream for you.
