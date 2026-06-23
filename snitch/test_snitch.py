"""Tests for snitch. Run: pytest (from repo root) or pytest snitch/

Includes a real end-to-end proxy test: an in-process upstream + the snitch
proxy on ephemeral ports, exercised over HTTP.
"""

import json
import socket
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import snitch


def test_toks_is_rough_estimate():
    assert snitch._toks("") == 1  # never zero
    assert snitch._toks("a" * 40) == 10


def test_color_is_noop_without_tty(monkeypatch):
    monkeypatch.setattr("sys.stdout.isatty", lambda: False, raising=False)
    assert snitch._color("red", "hello") == "hello"


def test_log_json_round_trips(tmp_path):
    path = tmp_path / "out.jsonl"
    body = {"model": "claude-opus-4-8", "messages": [{"role": "user", "content": "hi"}]}
    snitch._log_json(str(path), {"path": "/v1/messages", "method": "POST"}, body)
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["path"] == "/v1/messages"
    assert rec["method"] == "POST"
    assert rec["body"] == body


def test_print_request_handles_rich_body(capsys):
    cfg = snitch.Config()
    body = {
        "model": "claude-opus-4-8",
        "system": "be terse",
        "tools": [{"name": "read_file"}, {"type": "web_search_20260209"}],
        "messages": [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "read_file", "input": {"path": "/x"}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "content": "file contents"},
                ],
            },
        ],
        "max_tokens": 4096,
    }
    snitch._print_request("/v1/messages", body, cfg)
    out = capsys.readouterr().out
    assert "claude-opus-4-8" in out
    assert "read_file" in out
    assert "web_search_20260209" in out
    assert "be terse" in out


def test_print_request_survives_minimal_body(capsys):
    snitch._print_request("/v1/messages", {}, snitch.Config())
    assert "?" in capsys.readouterr().out  # model defaults to "?"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Upstream(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        self.rfile.read(n)
        payload = json.dumps({"ok": True, "from": "upstream"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


def test_end_to_end_proxy(tmp_path):
    up_port = _free_port()
    proxy_port = _free_port()
    log = tmp_path / "run.jsonl"

    upstream = ThreadingHTTPServer(("127.0.0.1", up_port), _Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()

    cfg = snitch.Config()
    cfg.upstream = f"http://127.0.0.1:{up_port}"
    cfg.log_path = str(log)
    cfg.quiet = True
    proxy = ThreadingHTTPServer(("127.0.0.1", proxy_port), snitch.make_handler(cfg))
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    time.sleep(0.2)

    try:
        req_body = {"model": "claude-opus-4-8", "messages": [{"role": "user", "content": "hi"}]}
        req = urllib.request.Request(
            f"http://127.0.0.1:{proxy_port}/v1/messages",
            data=json.dumps(req_body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read())
        assert data == {"ok": True, "from": "upstream"}  # forwarded + relayed

        # and the exact request body was snitched to the log
        rec = json.loads(log.read_text().splitlines()[0])
        assert rec["body"] == req_body
    finally:
        proxy.shutdown()
        upstream.shutdown()
