"""Tests for snitch. Run: pytest (from repo root) or pytest snitch/

Includes real end-to-end tests: an in-process upstream + the snitch proxy, and
the web-UI server, all on ephemeral ports and exercised over HTTP.
"""

import json
import socket
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import snitch


@pytest.fixture(autouse=True)
def _clean_store():
    snitch._reset_store()
    yield
    snitch._reset_store()


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


def test_build_record_derives_summary():
    body = {
        "model": "claude-opus-4-8",
        "system": "be terse",
        "tools": [{"name": "a"}, {"name": "b"}],
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
        "max_tokens": 10,
    }
    rec = snitch._build_record(1, "POST", "/v1/messages", body)
    assert rec["n"] == 1
    assert rec["model"] == "claude-opus-4-8"
    assert rec["n_tools"] == 2
    assert rec["n_messages"] == 1
    assert rec["stream"] is True
    assert rec["status"] is None
    assert rec["body"] == body


def test_store_and_events_since():
    snitch._record(snitch._build_record(1, "POST", "/a", {"model": "x"}))
    snitch._record(snitch._build_record(2, "POST", "/b", {"model": "y"}))
    assert [r["n"] for r in snitch._events_since(0)] == [1, 2]
    assert [r["n"] for r in snitch._events_since(1)] == [2]
    assert snitch._events_since(2) == []


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


def _serve(handler_cls_or_factory):
    """Start a server on a free port; return (server, port)."""
    port = _free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler_cls_or_factory)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


def test_end_to_end_proxy_forwards_and_captures(tmp_path):
    upstream, up_port = _serve(_Upstream)
    log = tmp_path / "run.jsonl"

    cfg = snitch.Config()
    cfg.upstream = f"http://127.0.0.1:{up_port}"
    cfg.log_path = str(log)
    cfg.quiet = True
    proxy, proxy_port = _serve(snitch.make_handler(cfg))
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

        # exact request body snitched to the log
        rec = json.loads(log.read_text().splitlines()[0])
        assert rec["body"] == req_body

        # ...and captured into the in-memory store with its response status
        events = snitch._events_since(0)
        assert len(events) == 1
        assert events[0]["body"] == req_body
        assert events[0]["status"] == 200
    finally:
        proxy.shutdown()
        upstream.shutdown()


def test_ui_serves_page_and_events():
    ui, ui_port = _serve(snitch.make_ui_handler())
    time.sleep(0.2)
    try:
        # seed a captured event
        snitch._record(
            snitch._build_record(1, "POST", "/v1/messages", {"model": "claude-opus-4-8"})
        )

        # index page
        html = urllib.request.urlopen(f"http://127.0.0.1:{ui_port}/", timeout=5).read().decode()
        assert "snitch" in html
        assert "/api/events" in html  # the page polls this

        # events API
        raw = urllib.request.urlopen(
            f"http://127.0.0.1:{ui_port}/api/events?since=0", timeout=5
        ).read()
        events = json.loads(raw)
        assert len(events) == 1
        assert events[0]["model"] == "claude-opus-4-8"

        # incremental: nothing newer than n=1
        raw2 = urllib.request.urlopen(
            f"http://127.0.0.1:{ui_port}/api/events?since=1", timeout=5
        ).read()
        assert json.loads(raw2) == []
    finally:
        ui.shutdown()
