#!/usr/bin/env python3
"""snitch — see what your agent actually said behind your back.

A transparent forwarding proxy that sits between your code and an LLM API.
It logs the EXACT bytes your agent sends upstream — full system prompt, every
tool schema, every injected reminder, the whole conversation — then forwards
the request unchanged and streams the response straight back.

Agent frameworks hide a shocking amount of prompt. snitch rats them out.

Two ways to watch: the console (live, as before) and a small web UI that lets
you scroll back through every captured request and expand it. Both are on by
default. Zero dependencies (Python 3.9+ stdlib only).

    # 1. run the snitch
    python3 snitch.py --port 8787

    # 2. point your SDK at it (it forwards to api.anthropic.com by default)
    export ANTHROPIC_BASE_URL=http://localhost:8787
    #   or for OpenAI:  --upstream https://api.openai.com  + OPENAI_BASE_URL

    # 3. run your agent. watch the console — or open the web UI:
    #    http://localhost:8788

Flags:
    --port N            proxy listen port (default 8787)
    --ui-port N         web UI port (default 8788)
    --no-ui             don't start the web UI
    --upstream URL      where to forward (default https://api.anthropic.com)
    --log FILE          also append each request as JSON to FILE (.jsonl)
    --full              don't truncate long message bodies in the console
    --quiet             don't pretty-print to console (UI + log still work)
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# headers we must not forward verbatim (hop-by-hop / set by urllib)
_STRIP = {"host", "content-length", "accept-encoding", "connection"}

# ANSI — disabled automatically when stdout isn't a tty
_C = {
    "dim": "\033[2m",
    "bold": "\033[1m",
    "cyan": "\033[36m",
    "yellow": "\033[33m",
    "green": "\033[32m",
    "magenta": "\033[35m",
    "red": "\033[31m",
    "reset": "\033[0m",
}


def _color(name: str, s: str) -> str:
    if not sys.stdout.isatty():
        return s
    return f"{_C[name]}{s}{_C['reset']}"


# crude-but-useful token estimate (~4 chars/token) so you can eyeball bloat
def _toks(s: str) -> int:
    return max(1, len(s) // 4)


# --- capture store: shared between the proxy and the web UI -----------------
_EVENTS: list[dict] = []
_EVENTS_LOCK = threading.Lock()
_EVENTS_CAP = 1000  # keep the last N requests in memory
_SEQ = 0
_SEQ_LOCK = threading.Lock()


def _next_n() -> int:
    global _SEQ
    with _SEQ_LOCK:
        _SEQ += 1
        return _SEQ


def _record(rec: dict) -> None:
    with _EVENTS_LOCK:
        _EVENTS.append(rec)
        if len(_EVENTS) > _EVENTS_CAP:
            del _EVENTS[: len(_EVENTS) - _EVENTS_CAP]


def _events_since(n: int) -> list[dict]:
    with _EVENTS_LOCK:
        return [r for r in _EVENTS if r["n"] > n]


def _reset_store() -> None:  # used by tests
    global _SEQ
    with _EVENTS_LOCK:
        _EVENTS.clear()
    with _SEQ_LOCK:
        _SEQ = 0


_CORE_KEYS = ("model", "system", "tools", "messages")


def _build_record(n: int, method: str, path: str, body: dict) -> dict:
    """Turn a parsed request body into a structured, UI-friendly record."""
    tools = body.get("tools") or []
    msgs = body.get("messages") or []
    return {
        "n": n,
        "ts": time.strftime("%H:%M:%S"),
        "method": method,
        "path": path,
        "model": body.get("model", "?"),
        "stream": bool(body.get("stream")),
        "n_tools": len(tools),
        "n_messages": len(msgs),
        "status": None,  # filled in once the upstream responds
        "body": body,  # full request, for the detail view
    }


class Config:
    upstream = "https://api.anthropic.com"
    log_path = None
    full = False
    quiet = False


def _print_request(path: str, body: dict, cfg: Config, n: int | None = None) -> None:
    if n is None:
        n = _next_n()
    bar = _color("dim", "─" * 72)
    print(f"\n{bar}")
    print(_color("bold", f"  #{n}  →  {path}"))
    print(bar)

    model = body.get("model", "?")
    print(f"  {_color('cyan', 'model')}  {model}")

    # system prompt — the thing frameworks love to hide
    system = body.get("system")
    if system:
        text = system if isinstance(system, str) else json.dumps(system, indent=2)
        _block("system", text, "yellow", cfg)

    # tools — count + names + total schema size
    tools = body.get("tools") or []
    if tools:
        names = []
        for t in tools:
            names.append(t.get("name") or t.get("type") or "?")
        print(
            f"  {_color('magenta', 'tools')}  {len(tools)} "
            f"(~{_toks(json.dumps(tools))} tok of schema): "
            f"{', '.join(names)}"
        )
        if cfg.full:
            _block("tool schemas", json.dumps(tools, indent=2), "magenta", cfg)

    # messages — role-by-role
    msgs = body.get("messages") or []
    if msgs:
        print(f"  {_color('green', 'messages')}  {len(msgs)} turn(s):")
        for m in msgs:
            _print_message(m, cfg)

    # everything else that shapes the call
    extras = {k: v for k, v in body.items() if k not in _CORE_KEYS}
    if extras:
        print(f"  {_color('dim', 'params')}  {json.dumps(extras)[:200]}")


def _print_message(m: dict, cfg: Config) -> None:
    role = m.get("role", "?")
    content = m.get("content", "")
    if isinstance(content, str):
        _block(f"  {role}", content, "green", cfg, indent=4)
        return
    # structured content blocks
    for block in content:
        if not isinstance(block, dict):
            _block(f"  {role}", str(block), "green", cfg, indent=4)
            continue
        btype = block.get("type", "?")
        if btype == "text":
            _block(f"  {role}.text", block.get("text", ""), "green", cfg, indent=4)
        elif btype == "tool_use":
            print(
                f"      {_color('magenta', f'{role}.tool_use')} "
                f"{block.get('name')} {json.dumps(block.get('input', {}))[:160]}"
            )
        elif btype == "tool_result":
            c = block.get("content", "")
            c = c if isinstance(c, str) else json.dumps(c)
            _block(f"  {role}.tool_result", c, "cyan", cfg, indent=4)
        else:
            print(f"      {_color('dim', f'{role}.{btype}')} {json.dumps(block)[:160]}")


def _block(label: str, text: str, color: str, cfg: Config, indent: int = 2) -> None:
    pad = " " * indent
    head = f"{pad}{_color(color, label)} {_color('dim', f'(~{_toks(text)} tok)')}"
    print(head)
    shown = (
        text
        if (cfg.full or len(text) <= 600)
        else text[:600] + _color("dim", f"  …[+{len(text) - 600} chars, use --full]")
    )
    for line in shown.splitlines() or [""]:
        print(f"{pad}  {line}")


def _log_json(path: str, record: dict, body: dict) -> None:
    record["body"] = body
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def make_handler(cfg: Config):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # silence default access log
            pass

        def _proxy(self):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b""

            # try to parse + capture; never let logging break the proxy
            rec = None
            body = None
            if raw:
                try:
                    body = json.loads(raw)
                except Exception:
                    body = None
            if body is not None:
                try:
                    n = _next_n()
                    rec = _build_record(n, self.command, self.path, body)
                    _record(rec)
                    if not cfg.quiet:
                        _print_request(self.path, body, cfg, n)
                    if cfg.log_path:
                        _log_json(cfg.log_path, {"path": self.path, "method": self.command}, body)
                except Exception as e:  # noqa: BLE001
                    print(_color("red", f"[snitch] capture error: {e}"))

            # forward upstream, verbatim
            url = cfg.upstream.rstrip("/") + self.path
            fwd = {k: v for k, v in self.headers.items() if k.lower() not in _STRIP}
            req = urllib.request.Request(url, data=raw or None, headers=fwd, method=self.command)
            try:
                resp = urllib.request.urlopen(req)
                status = self._relay(resp)
            except urllib.error.HTTPError as e:
                status = self._relay(e)
            except Exception as e:  # noqa: BLE001
                status = 502
                msg = json.dumps({"snitch_error": str(e)}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)
            if rec is not None:
                rec["status"] = status

        def _relay(self, resp) -> int:
            status = resp.status if hasattr(resp, "status") else resp.code
            self.send_response(status)
            hop = {"transfer-encoding", "connection", "content-encoding"}
            for k, v in resp.headers.items():
                if k.lower() in hop:
                    continue
                self.send_header(k, v)
            # stream the body through in chunks (handles SSE responses too)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                self.wfile.write(f"{len(chunk):X}\r\n".encode())
                self.wfile.write(chunk)
                self.wfile.write(b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
            return status

        do_POST = _proxy
        do_GET = _proxy
        do_PUT = _proxy

    return Handler


# --- web UI ----------------------------------------------------------------

_UI_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>snitch 👂</title>
<style>
  :root { --fg:#111; --dim:#777; --line:#e5e5e5; --accent:#0a7; --bg:#fff; --panel:#fafafa; }
  * { box-sizing: border-box; }
  body { margin:0; font:14px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
         color:var(--fg); background:var(--bg); }
  header { display:flex; align-items:center; gap:12px; padding:10px 16px;
           border-bottom:1px solid var(--line); position:sticky; top:0; background:var(--bg); z-index:2; }
  header h1 { font-size:16px; margin:0; }
  header .count { color:var(--dim); }
  header input { flex:1; padding:6px 10px; border:1px solid var(--line); border-radius:6px;
                 font:inherit; }
  .wrap { display:grid; grid-template-columns:minmax(280px,360px) 1fr; height:calc(100vh - 53px); }
  .list { overflow:auto; border-right:1px solid var(--line); }
  .row { padding:8px 14px; border-bottom:1px solid var(--line); cursor:pointer; }
  .row:hover { background:var(--panel); }
  .row.sel { background:#f0f7f4; border-left:3px solid var(--accent); padding-left:11px; }
  .row .top { display:flex; justify-content:space-between; gap:8px; }
  .row .path { color:var(--fg); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .row .ts { color:var(--dim); flex:none; }
  .row .meta { color:var(--dim); font-size:12px; margin-top:2px; }
  .badge { display:inline-block; padding:0 6px; border:1px solid var(--line); border-radius:10px;
           margin-right:4px; font-size:11px; }
  .ok { color:var(--accent); } .err { color:#c00; }
  .detail { overflow:auto; padding:16px 20px; }
  .bar { display:flex; gap:8px; margin-bottom:12px; }
  .bar button { font:inherit; font-size:12px; padding:3px 10px; border:1px solid var(--line);
                background:var(--panel); border-radius:6px; cursor:pointer; color:var(--fg); }
  .bar button:hover { border-color:var(--accent); }
  .bar button.on { background:#f0f7f4; border-color:var(--accent); color:var(--accent); }
  .bar { position:sticky; top:0; background:var(--bg); padding:4px 0 8px; z-index:1; }
  pre { white-space:pre-wrap; word-break:break-word; background:var(--panel);
        border:1px solid var(--line); border-radius:6px; padding:10px; margin:0; }
  details { border:1px solid var(--line); border-radius:6px; margin-bottom:8px; background:var(--bg); }
  details > summary { cursor:pointer; padding:6px 10px; background:var(--panel);
                      border-radius:6px; user-select:none; font-size:13px; list-style:none;
                      white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  summary .role { color:var(--fg); }
  details > summary::-webkit-details-marker { display:none; }
  details > summary::before { content:'▸ '; color:var(--dim); }
  details[open] > summary::before { content:'▾ '; }
  details[open] > summary { border-bottom:1px solid var(--line); border-radius:6px 6px 0 0; }
  .sec { padding:10px; }
  .sec details { margin:6px 0; }
  .sec pre { border:0; border-radius:0; }
  .sec details pre { border:1px solid var(--line); border-radius:0 0 6px 6px; }
  .blk { margin:0 0 8px; }
  .blk:last-child { margin-bottom:0; }
  .blk .lbl { color:var(--dim); font-size:12px; margin-bottom:2px; }
  .ic { font-style:normal; }
  .tag { color:var(--dim); font-weight:normal; }
  .empty { color:var(--dim); padding:40px; text-align:center; }
  /* JSON syntax highlighting */
  .j-key { color:#1565c0; } .j-str { color:#0a7d3b; } .j-num { color:#b26a00; }
  .j-bool { color:#9c27b0; } .j-null { color:#999; }
  /* request header card (not collapsible) */
  .req { border:1px solid var(--line); border-left:3px solid var(--accent); border-radius:8px;
         padding:12px 14px; margin-bottom:14px; background:var(--panel); }
  .req-top { display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }
  .req .num { color:var(--dim); font-size:13px; }
  .req .method { font-weight:700; letter-spacing:.03em; }
  .req .path { font-size:15px; word-break:break-all; }
  .req-meta { display:flex; flex-wrap:wrap; gap:6px 22px; margin-top:10px; }
  .kv { display:flex; gap:6px; align-items:baseline; }
  .kv .k { color:var(--dim); font-size:11px; text-transform:uppercase; letter-spacing:.06em; }
  .kv .v.ok { color:var(--accent); } .kv .v.err { color:#c00; } .kv .v.pending { color:var(--dim); }
</style>
</head>
<body>
<header>
  <h1>snitch 👂</h1>
  <span class="count" id="count">0</span>
  <input id="filter" placeholder="filter by path / model / content…" autocomplete="off">
</header>
<div class="wrap">
  <div class="list" id="list"></div>
  <div class="detail" id="detail"><div class="empty">waiting for requests…</div></div>
</div>
<script>
const E = [];            // all events
let lastN = 0, sel = null, filter = "";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

const ROLE_ICON = { system:'⚙️', user:'🧑', assistant:'🤖', tool:'🔧', developer:'🛠️' };
const BLOCK_ICON = { text:'💬', tool_use:'🔧', tool_result:'↩️', thinking:'🧠',
                     redacted_thinking:'🧠', image:'🖼️', document:'📄' };
const roleIcon = (r) => ROLE_ICON[r] || '💬';
const blockIcon = (t) => BLOCK_ICON[t] || '▪️';

const snip = (s) => {
  s = String(s || "").replace(/\s+/g, " ").trim();
  return s.length > 100 ? s.slice(0, 100) + "…" : s;
};

// what to show on a collapsed message: keep the role, but prefer the actual
// text — and for tool turns surface the block (🔧/↩️) inside the preview so a
// tool_result isn't mistaken for a plain "user" message.
function summarize(m) {
  const role = m.role || "?";
  const base = { icon: roleIcon(role), label: role };
  const c = m.content;
  if (typeof c === "string") return { ...base, preview: snip(c) };
  if (!Array.isArray(c)) return { ...base, preview: snip(JSON.stringify(c)) };

  const texts = c.filter(b => b && b.type === "text").map(b => b.text || "").join(" ").trim();
  const uses = c.filter(b => b && b.type === "tool_use");
  const results = c.filter(b => b && b.type === "tool_result");
  const thinking = c.some(b => b && (b.type === "thinking" || b.type === "redacted_thinking"));

  if (!texts && results.length && !uses.length) {
    const r = results[0].content;
    const lbl = results.length > 1 ? "tool_result ×" + results.length : "tool_result";
    const body = snip(typeof r === "string" ? r : JSON.stringify(r));
    return { ...base, preview: "↩️ " + lbl + (body ? " · " + body : "") };
  }
  if (!texts && uses.length) {
    const names = uses.map(u => u.name).filter(Boolean).join(", ");
    return { ...base, preview: "🔧 " + (names || (uses.length > 1 ? "tool calls" : "tool call")) };
  }
  if (!texts && thinking) return { ...base, preview: "🧠 thinking" };

  let hint = "";
  if (thinking) hint += " 🧠";
  if (uses.length) hint += " 🔧" + (uses.length > 1 ? "×" + uses.length : "");
  return { ...base, preview: snip(texts) + hint };
}

// minimal, dependency-free JSON syntax highlighter
function highlight(json) {
  return esc(json).replace(
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?)/g,
    (m) => {
      let c = 'j-num';
      if (/^"/.test(m)) c = /:$/.test(m) ? 'j-key' : 'j-str';
      else if (/true|false/.test(m)) c = 'j-bool';
      else if (/null/.test(m)) c = 'j-null';
      return '<span class="' + c + '">' + m + '</span>';
    });
}
const jsonPre = (v) =>
  '<pre class="hl">' + highlight(typeof v === 'string' ? v : JSON.stringify(v, null, 2)) + '</pre>';

// render a string that might itself be JSON
function maybeJson(s) {
  if (typeof s === 'string') {
    try { const v = JSON.parse(s); if (v && typeof v === 'object') return jsonPre(v); } catch (e) {}
    return '<pre>' + esc(s) + '</pre>';
  }
  return jsonPre(s);
}

function section(title, open, inner) {
  return '<details' + (open ? ' open' : '') + '><summary>' + title
       + '</summary><div class="sec">' + inner + '</div></details>';
}

// fixed (non-collapsible) request header card — every attribute, easy on the eye
function reqHeader(ev, b) {
  const status = ev.status == null ? "pending" : ev.status;
  const statusCls = ev.status == null ? "pending" : (ev.status < 400 ? "ok" : "err");
  const mcolor = { POST: "#0a7d3b", GET: "#1565c0", PUT: "#b26a00", DELETE: "#c0392b" }[ev.method]
               || "var(--dim)";
  const kv = (k, v, cls) =>
    '<span class="kv"><span class="k">' + k + '</span><span class="v ' + (cls || "") + '">'
    + esc(v) + '</span></span>';
  return '<div class="req">'
    + '<div class="req-top">'
    +   '<span class="num">#' + ev.n + '</span>'
    +   '<span class="method" style="color:' + mcolor + '">' + esc(ev.method) + '</span>'
    +   '<span class="path">' + esc(ev.path) + '</span>'
    + '</div>'
    + '<div class="req-meta">'
    +   kv("model", b.model || "?")
    +   kv("status", status, statusCls)
    +   kv("stream", ev.stream ? "true" : "false")
    +   kv("time", ev.ts)
    + '</div></div>';
}

async function poll() {
  try {
    const r = await fetch("/api/events?since=" + lastN);
    const arr = await r.json();
    for (const ev of arr) { E.push(ev); lastN = Math.max(lastN, ev.n); }
    if (arr.length) { renderList(); if (sel === null) select(E[E.length-1].n); }
  } catch (e) { /* server gone; keep trying */ }
}

function matches(ev) {
  if (!filter) return true;
  const hay = (ev.path + " " + ev.model + " " + JSON.stringify(ev.body)).toLowerCase();
  return hay.includes(filter);
}

function renderList() {
  const rows = E.filter(matches).reverse();
  $("count").textContent = rows.length + " / " + E.length;
  $("list").innerHTML = rows.map(ev => {
    const stat = ev.status == null ? '<span class="tag">…</span>'
      : '<span class="' + (ev.status < 400 ? 'ok' : 'err') + '">' + ev.status + '</span>';
    return '<div class="row ' + (ev.n === sel ? 'sel' : '') + '" onclick="select(' + ev.n + ')">'
      + '<div class="top"><span class="path">#' + ev.n + ' ' + esc(ev.method) + ' ' + esc(ev.path)
      + '</span><span class="ts">' + esc(ev.ts) + '</span></div>'
      + '<div class="meta">' + esc(ev.model)
      + ' <span class="badge">' + ev.n_messages + ' msg</span>'
      + (ev.n_tools ? '<span class="badge">' + ev.n_tools + ' tools</span>' : '')
      + (ev.stream ? '<span class="badge">stream</span>' : '')
      + ' ' + stat + '</div></div>';
  }).join("") || '<div class="empty">no matches</div>';
}

function allDetails(open) {
  document.querySelectorAll('#detail details').forEach(d => d.open = open);
}

let rawMode = false;
function toggleRaw() { rawMode = !rawMode; if (sel !== null) select(sel); }

function select(n) {
  sel = n; renderList();
  const ev = E.find(e => e.n === n);
  if (!ev) return;
  const b = ev.body || {};

  let bar = '<div class="bar">';
  if (!rawMode) {
    bar += '<button onclick="allDetails(true)">⊕ expand all</button>'
         + '<button onclick="allDetails(false)">⊖ collapse all</button>';
  }
  bar += '<button class="' + (rawMode ? 'on' : '') + '" onclick="toggleRaw()">'
       + (rawMode ? '◧ structured' : '{ } raw') + '</button></div>';

  if (rawMode) { $("detail").innerHTML = bar + jsonPre(b); return; }

  let h = bar;
  h += reqHeader(ev, b);

  if (b.system) {
    const inner = typeof b.system === "string"
      ? '<pre>' + esc(b.system) + '</pre>'   // a plain prompt is prose, not JSON
      : jsonPre(b.system);                    // structured (text blocks, cache_control) → highlight
    h += section('⚙️ system', true, inner);
  }
  if (b.tools && b.tools.length) {
    const inner = b.tools.map(t =>
      '<details><summary>🔧 ' + esc(t.name || t.type || "?") + '</summary>'
      + '<div class="sec">' + jsonPre(t) + '</div></details>').join('');
    h += section('🔧 tools (' + b.tools.length + ')', true, inner);
  }
  if (b.messages && b.messages.length) {
    h += section('💬 messages (' + b.messages.length + ')', true,
                 b.messages.map(renderMsg).join(''));
  }
  const extras = {};
  for (const k in b) if (!["model","system","tools","messages"].includes(k)) extras[k] = b[k];
  if (Object.keys(extras).length) h += section('🎛️ params', false, jsonPre(extras));
  $("detail").innerHTML = h;
}

function renderMsg(m) {
  const c = m.content;
  const s = summarize(m);
  const sum = '<span class="ic">' + s.icon + '</span> <span class="role">' + esc(s.label) + '</span>'
            + (s.preview ? ' <span class="tag">' + esc(s.preview) + '</span>' : '');

  let inner = "";
  if (typeof c === "string") {
    inner = '<div class="blk"><pre>' + esc(c) + '</pre></div>';
  } else if (Array.isArray(c)) {
    for (const blk of c) {
      if (!blk || typeof blk !== "object") { inner += '<div class="blk"><pre>' + esc(String(blk)) + '</pre></div>'; continue; }
      const t = blk.type || "?";
      let body;
      if (t === "text") body = '<pre>' + esc(blk.text || "") + '</pre>';
      else if (t === "tool_use") body = jsonPre(blk.input || {});
      else if (t === "tool_result") body = maybeJson(blk.content);
      else body = jsonPre(blk);
      inner += '<div class="blk"><div class="lbl">' + blockIcon(t) + ' ' + esc(t)
             + (blk.name ? ' · ' + esc(blk.name) : '') + '</div>' + body + '</div>';
    }
  } else {
    inner = '<div class="blk">' + jsonPre(c) + '</div>';
  }
  return '<details open><summary>' + sum + '</summary><div class="sec">' + inner + '</div></details>';
}

$("filter").addEventListener("input", e => { filter = e.target.value.toLowerCase(); renderList(); });
poll(); setInterval(poll, 1500);
</script>
</body>
</html>
"""


def make_ui_handler():
    class UI(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
                self._send(200, _UI_HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif parsed.path == "/api/events":
                qs = urllib.parse.parse_qs(parsed.query)
                since = int(qs.get("since", ["0"])[0] or 0)
                payload = json.dumps(_events_since(since)).encode("utf-8")
                self._send(200, payload, "application/json")
            else:
                self._send(404, b"not found", "text/plain")

    return UI


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="snitch",
        description="see what your agent actually said behind your back.",
    )
    p.add_argument("--port", type=int, default=8787, help="proxy listen port (default 8787)")
    p.add_argument("--ui-port", type=int, default=8788, help="web UI port (default 8788)")
    p.add_argument("--no-ui", action="store_true", help="don't start the web UI")
    p.add_argument(
        "--upstream",
        default="https://api.anthropic.com",
        help="API to forward to (default: api.anthropic.com)",
    )
    p.add_argument(
        "--log", dest="log", default=None, help="append each request as JSON to this .jsonl file"
    )
    p.add_argument(
        "--full", action="store_true", help="don't truncate long bodies / show tool schemas"
    )
    p.add_argument("--quiet", action="store_true", help="no console output (UI + log still work)")
    args = p.parse_args(argv)

    cfg = Config()
    cfg.upstream = args.upstream
    cfg.log_path = args.log
    cfg.full = args.full
    cfg.quiet = args.quiet

    proxy = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(cfg))
    print(_color("bold", "snitch is listening 👂"))
    print(f"  proxy:    http://localhost:{args.port}")
    print(f"  upstream: {cfg.upstream}")
    if cfg.log_path:
        print(f"  logging:  {cfg.log_path}")

    ui = None
    if not args.no_ui:
        ui = ThreadingHTTPServer(("127.0.0.1", args.ui_port), make_ui_handler())
        threading.Thread(target=ui.serve_forever, daemon=True).start()
        print(f"  web UI:   {_color('cyan', f'http://localhost:{args.ui_port}')}")

    print(_color("dim", "  point ANTHROPIC_BASE_URL (or your SDK's base url) at the proxy.\n"))
    try:
        proxy.serve_forever()
    except KeyboardInterrupt:
        print("\n[snitch] done snitching.")
    finally:
        if ui is not None:
            ui.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
