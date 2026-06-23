#!/usr/bin/env python3
"""snitch — see what your agent actually said behind your back.

A transparent forwarding proxy that sits between your code and an LLM API.
It logs the EXACT bytes your agent sends upstream — full system prompt, every
tool schema, every injected reminder, the whole conversation — then forwards
the request unchanged and streams the response straight back.

Agent frameworks hide a shocking amount of prompt. snitch rats them out.

Zero dependencies (Python 3.9+ stdlib only). Provider-agnostic: it forwards
to whatever upstream you point it at and never inspects credentials.

    # 1. run the snitch
    python3 snitch.py --port 8787

    # 2. point your SDK at it (it forwards to api.anthropic.com by default)
    export ANTHROPIC_BASE_URL=http://localhost:8787
    #   or for OpenAI:  --upstream https://api.openai.com  + OPENAI_BASE_URL

    # 3. run your agent. watch the truth scroll by.

Flags:
    --port N            listen port (default 8787)
    --upstream URL      where to forward (default https://api.anthropic.com)
    --log FILE          also append each request as JSON to FILE (.jsonl)
    --full              don't truncate long message bodies in the console
    --quiet             don't pretty-print to console (use with --log)
"""

from __future__ import annotations

import argparse
import json
import sys
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


class Config:
    upstream = "https://api.anthropic.com"
    log_path = None
    full = False
    quiet = False
    _n = 0


def _print_request(path: str, body: dict, cfg: Config) -> None:
    Config._n += 1
    n = Config._n
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
    extras = {k: v for k, v in body.items() if k not in ("model", "system", "tools", "messages")}
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

            # try to parse + report; never let logging break the proxy
            body = None
            if raw:
                try:
                    body = json.loads(raw)
                except Exception:
                    body = None
            if body is not None:
                try:
                    if not cfg.quiet:
                        _print_request(self.path, body, cfg)
                    if cfg.log_path:
                        _log_json(cfg.log_path, {"path": self.path, "method": self.command}, body)
                except Exception as e:  # noqa: BLE001
                    print(_color("red", f"[snitch] report error: {e}"))

            # forward upstream, verbatim
            url = cfg.upstream.rstrip("/") + self.path
            fwd = {k: v for k, v in self.headers.items() if k.lower() not in _STRIP}
            req = urllib.request.Request(url, data=raw or None, headers=fwd, method=self.command)
            try:
                resp = urllib.request.urlopen(req)
                self._relay(resp)
            except urllib.error.HTTPError as e:
                self._relay(e)
            except Exception as e:  # noqa: BLE001
                msg = json.dumps({"snitch_error": str(e)}).encode()
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)

        def _relay(self, resp):
            self.send_response(resp.status if hasattr(resp, "status") else resp.code)
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

        do_POST = _proxy
        do_GET = _proxy
        do_PUT = _proxy

    return Handler


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="snitch",
        description="see what your agent actually said behind your back.",
    )
    p.add_argument("--port", type=int, default=8787)
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
    p.add_argument("--quiet", action="store_true", help="no console output (pair with --log)")
    args = p.parse_args(argv)

    cfg = Config()
    cfg.upstream = args.upstream
    cfg.log_path = args.log
    cfg.full = args.full
    cfg.quiet = args.quiet

    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(cfg))
    print(_color("bold", "snitch is listening 👂"))
    print(f"  proxy:    http://localhost:{args.port}")
    print(f"  upstream: {cfg.upstream}")
    if cfg.log_path:
        print(f"  logging:  {cfg.log_path}")
    print(_color("dim", "  point ANTHROPIC_BASE_URL (or your SDK's base url) at the proxy.\n"))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[snitch] done snitching.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
