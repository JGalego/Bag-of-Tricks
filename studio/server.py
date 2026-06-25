#!/usr/bin/env python3
"""studio — rig the whole act.

A magician rehearses the act in the studio before the show: lay the tricks out,
wire them together, run it, watch where it breaks. This is that, for the bag —
a browser-based editor where you drag tricks onto a canvas, connect them with
arrows into a branching routine, and run the whole thing to watch the input flow
through, stage by stage.

It is the visual, multi-branch cousin of `combo`. Where combo is one straight
Unix pipe (`frisk | launder | tell`), studio lets a stage *fan out* — one
trick's output feeding several downstream branches — so you can compare routines
side by side. Each node still has a single input (one arrow in); that keeps the
data flow unambiguous, exactly like a pipe.

The server runs every trick **in-process**: it imports the sibling trick module
once and calls its `main(argv)` with stdin/stdout redirected to in-memory
buffers. No subprocess per node, no shell — just a function call with captured
streams and the trick's own exit code (so a gate like `--check` still aborts its
branch). A per-node timeout guards the network tricks.

    python studio/server.py            # serve on http://127.0.0.1:8765
    python studio/server.py --port 9000
    python studio/server.py --open     # also open a browser

Endpoints:
    GET  /            -> the editor (index.html)
    GET  /api/tricks  -> the catalog: every runnable trick, by category + shape
    POST /api/run     -> execute a routine; returns per-node output + status
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import shlex
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
EXAMPLES_DIR = HERE / "examples"

# Category palette (matches the network on the site).
CATS = {
    "output": {"color": "#3b82f6", "blurb": "shape and clean up what the model emits"},
    "debugging": {"color": "#22a55a", "blurb": "see and fix what your agent is actually doing"},
    "security": {"color": "#e5534b", "blurb": "probe prompts and context for attacks and leaks"},
    "workflow": {"color": "#a371f7", "blurb": "change how the model decides and when it acts"},
    "productivity": {"color": "#d4a017", "blurb": "everyday LLM dev chores, done faster"},
}

# The runnable bag. snitch (a long-running proxy server) and combo (the studio
# *is* the chainer) are deliberately left out. `shape`: filter = emits text and
# chains in the middle; analyzer = emits a report/verdict, a terminal sink.
# `gate`: also has a --check/--max mode that exits non-zero to abort its branch.
# `net`: calls a model / the network, so it is slow and may need an API key.
TRICKS = [
    {
        "name": "frisk",
        "cat": "security",
        "shape": "filter",
        "gate": True,
        "net": False,
        "catchphrase": "pat it down before it ships.",
        "blurb": "redact secrets and PII (API keys, tokens, private keys, emails).",
        "flags": ["--pii", "--check", "--json", "--report"],
    },
    {
        "name": "launder",
        "cat": "output",
        "shape": "filter",
        "gate": True,
        "net": False,
        "catchphrase": "wash out the prints.",
        "blurb": "strip mechanical fingerprints: zero-width chars, smart quotes, em-dashes.",
        "flags": ["--check", "--report", "--json"],
    },
    {
        "name": "salvage",
        "cat": "output",
        "shape": "filter",
        "gate": False,
        "net": False,
        "catchphrase": "rip the JSON out of the chatter.",
        "blurb": "extract and repair valid JSON buried in chatty LLM output.",
        "flags": ["--compact", "--indent", "--extract-only"],
    },
    {
        "name": "mole",
        "cat": "security",
        "shape": "filter",
        "gate": True,
        "net": False,
        "catchphrase": "find the plant.",
        "blurb": "sniff out prompt-injection hiding in untrusted input.",
        "flags": ["--check", "--quarantine", "--json"],
    },
    {
        "name": "deadpan",
        "cat": "output",
        "shape": "filter",
        "gate": False,
        "net": False,
        "catchphrase": "the answer. nothing else.",
        "blurb": "strip personality, filler, hedging, emoji, and sycophancy.",
        "flags": [],
    },
    {
        "name": "steno",
        "cat": "productivity",
        "shape": "filter",
        "gate": False,
        "net": True,
        "catchphrase": "two letters, and the prompt writes itself.",
        "blurb": "expand short aliases into full prompts for common dev tasks.",
        "flags": [],
    },
    {
        "name": "tell",
        "cat": "output",
        "shape": "analyzer",
        "gate": True,
        "net": False,
        "catchphrase": "every AI has a tell.",
        "blurb": "flag the giveaways in AI-written prose (delve, tapestry, em-dash overuse).",
        "flags": ["--score", "--json"],
    },
    {
        "name": "fold",
        "cat": "output",
        "shape": "analyzer",
        "gate": True,
        "net": False,
        "catchphrase": "know when to fold.",
        "blurb": "catch overconfident phrasing and absolutes so the model hedges.",
        "flags": ["--json"],
    },
    {
        "name": "alibi",
        "cat": "debugging",
        "shape": "analyzer",
        "gate": True,
        "net": False,
        "catchphrase": "does the story check out?",
        "blurb": "flag answer claims not supported by the sources (RAG grounding check).",
        "flags": ["--json"],
    },
    {
        "name": "mugshot",
        "cat": "output",
        "shape": "analyzer",
        "gate": False,
        "net": False,
        "catchphrase": "we know your prints.",
        "blurb": "guess which model wrote a passage from its stylistic fingerprints.",
        "flags": ["--json"],
    },
    {
        "name": "tollbooth",
        "cat": "productivity",
        "shape": "analyzer",
        "gate": False,
        "net": False,
        "catchphrase": "know the bill before the bill.",
        "blurb": "estimate token count and dollar cost of a prompt across models.",
        "flags": ["--json"],
    },
    {
        "name": "bluff",
        "cat": "debugging",
        "shape": "analyzer",
        "gate": False,
        "net": True,
        "catchphrase": "call its bluff.",
        "blurb": "extract URLs and citations and check they actually resolve.",
        "flags": ["--json"],
    },
    {
        "name": "grill",
        "cat": "debugging",
        "shape": "analyzer",
        "gate": False,
        "net": True,
        "catchphrase": "put it in the hot seat.",
        "blurb": "adversarially interrogate an answer with probing follow-ups.",
        "flags": [],
    },
    {
        "name": "lineup",
        "cat": "productivity",
        "shape": "analyzer",
        "gate": False,
        "net": True,
        "catchphrase": "same prompt, the whole lineup.",
        "blurb": "run one prompt across several models and lay the answers side by side.",
        "flags": [],
    },
    {
        "name": "strawman",
        "cat": "security",
        "shape": "analyzer",
        "gate": False,
        "net": True,
        "catchphrase": "argue with yourself before the internet does.",
        "blurb": "red-team a prompt across jailbreak, injection, derailment, extraction.",
        "flags": [],
    },
    {
        "name": "interrobang",
        "cat": "workflow",
        "shape": "analyzer",
        "gate": True,
        "net": True,
        "catchphrase": "make it ask before it acts.",
        "blurb": "ask one sharp clarifying question instead of guessing.",
        "flags": [],
    },
]
TRICK_NAMES = {t["name"] for t in TRICKS}

# In-process trick modules, loaded lazily and reused.
_MODULES: dict[str, ModuleType] = {}
# Redirecting sys.stdout/stdin is process-global, so serialize every run.
_RUN_LOCK = threading.Lock()


def load_trick(name: str) -> ModuleType:
    """Import a sibling trick module (cached) so we can call its main()."""
    mod = _MODULES.get(name)
    if mod is not None:
        return mod
    path = ROOT / name / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_trick_{name}", path)
    if spec is None or spec.loader is None:
        raise ModuleNotFoundError(f"cannot load trick {name!r} at {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _MODULES[name] = mod
    return mod


def run_node(name: str, flags: str, stdin_text: str, timeout: float) -> dict:
    """Run one trick in-process and capture its streams + exit code.

    Redirects sys.stdin/stdout/stderr to in-memory buffers, calls main(argv),
    and runs it in a daemon thread so a hung network trick can be timed out.
    Returns {stdout, stderr, code, elapsed, error?, timeout?}.
    """
    try:
        mod = load_trick(name)
    except Exception as exc:  # noqa: BLE001 - report any import failure to the UI
        return {
            "stdout": "",
            "stderr": "",
            "code": 127,
            "elapsed": 0.0,
            "error": f"{type(exc).__name__}: {exc}",
        }

    argv = shlex.split(flags) if flags else []
    out_buf, err_buf = io.StringIO(), io.StringIO()
    box: dict = {"code": 0}

    def target() -> None:
        with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
            real_stdin = sys.stdin
            sys.stdin = io.StringIO(stdin_text)
            try:
                code = mod.main(argv)
                box["code"] = code if isinstance(code, int) else 0
            except SystemExit as exc:  # argparse errors / explicit exits
                box["code"] = exc.code if isinstance(exc.code, int) else 1
            except Exception as exc:  # noqa: BLE001 - surface, don't crash the server
                box["code"] = 1
                box["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                sys.stdin = real_stdin

    thread = threading.Thread(target=target, daemon=True)
    start = time.monotonic()
    thread.start()
    thread.join(timeout)
    elapsed = time.monotonic() - start

    if thread.is_alive():
        return {
            "stdout": out_buf.getvalue(),
            "stderr": err_buf.getvalue(),
            "code": 124,
            "elapsed": elapsed,
            "timeout": True,
            "error": f"timed out after {timeout:g}s",
        }
    res = {
        "stdout": out_buf.getvalue(),
        "stderr": err_buf.getvalue(),
        "code": box["code"],
        "elapsed": elapsed,
    }
    if "error" in box:
        res["error"] = box["error"]
    return res


def execute(payload: dict) -> dict:
    """Run a whole routine: a single-input forest of trick nodes.

    payload = {input: str, timeout?: float,
               nodes: [{id, trick, flags}],
               edges: [{source, target}]}   # each target has at most one source

    Roots (no incoming edge) read the global input. A node's output feeds every
    child (fan-out). A node that exits non-zero aborts its branch: descendants
    are marked "skip". Returns {nodes: {id: result}, outputs: [{id, ...}], order}.
    """
    text = payload.get("input", "") or ""
    timeout = float(payload.get("timeout") or 20.0)
    nodes = {n["id"]: n for n in payload.get("nodes", [])}
    edges = payload.get("edges", [])

    parent: dict[str, str] = {}
    children: dict[str, list[str]] = {nid: [] for nid in nodes}
    for e in edges:
        src, tgt = e.get("source"), e.get("target")
        if src in nodes and tgt in nodes:
            parent[tgt] = src  # single-input: last wins (UI enforces uniqueness)
            children.setdefault(src, []).append(tgt)

    # Topological order (Kahn). Cycles (shouldn't happen via the UI) drop out.
    indeg = {nid: (1 if nid in parent else 0) for nid in nodes}
    queue = [nid for nid, d in indeg.items() if d == 0]
    order: list[str] = []
    while queue:
        nid = queue.pop(0)
        order.append(nid)
        for child in children.get(nid, []):
            indeg[child] -= 1
            if indeg[child] == 0:
                queue.append(child)

    results: dict[str, dict] = {}
    with _RUN_LOCK:
        for nid in order:
            node = nodes[nid]
            name = node.get("trick", "")
            src = parent.get(nid)
            if src is not None:
                up = results.get(src, {})
                # A skipped or failed parent short-circuits the branch.
                if up.get("status") in ("skip", "abort", "error"):
                    results[nid] = {
                        "status": "skip",
                        "stdout": "",
                        "stderr": "",
                        "code": None,
                        "elapsed": 0.0,
                        "reason": f"upstream {src} did not pass",
                    }
                    continue
                stdin_text = up.get("stdout", "")
            else:
                stdin_text = text

            if name not in TRICK_NAMES:
                results[nid] = {
                    "status": "error",
                    "stdout": "",
                    "stderr": "",
                    "code": 127,
                    "elapsed": 0.0,
                    "error": f"unknown trick: {name}",
                }
                continue

            r = run_node(name, node.get("flags", "") or "", stdin_text, timeout)
            if r.get("timeout"):
                status = "timeout"
            elif r.get("error"):
                status = "error"
            elif r["code"] != 0:
                status = "abort"  # a gate tripped / the trick failed
            else:
                status = "ok"
            r["status"] = status
            results[nid] = r

    # Any node with no children is a sink whose output reaches the output box.
    leaves = [nid for nid in nodes if not children.get(nid)]
    outputs = [
        {
            "id": nid,
            "trick": nodes[nid].get("trick"),
            **{k: results.get(nid, {}).get(k) for k in ("status", "stdout", "code")},
        }
        for nid in leaves
    ]
    return {"nodes": results, "outputs": outputs, "order": order}


def list_examples() -> list[dict]:
    """Read studio/examples/*.md into a list of {file, title, description, doc}.

    Each example is a Markdown doc: a `# title` heading, a description line or
    two, a ```mermaid graph, and a ```text block with the sample input. We pull
    the title/description for the menu and hand the raw doc to the browser, which
    parses the mermaid into the editor graph.
    """
    out = []
    if not EXAMPLES_DIR.is_dir():
        return out
    for path in sorted(EXAMPLES_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title, desc_lines, seen_title = path.stem, [], False
        for line in text.splitlines():
            stripped = line.strip()
            if not seen_title:
                if stripped.startswith("# "):
                    title, seen_title = stripped[2:].strip(), True
                continue
            if stripped.startswith("```"):  # description ends at the first fence
                break
            if stripped:
                desc_lines.append(stripped)
        out.append(
            {
                "file": path.name,
                "title": title,
                "description": " ".join(desc_lines),
                "doc": text,
            }
        )
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # quiet; access logs would spam stderr
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            page = HERE / "index.html"
            if page.exists():
                self._send(200, page.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(404, b"index.html not found", "text/plain")
        elif self.path == "/api/tricks":
            self._json(200, {"tricks": TRICKS, "cats": CATS})
        elif self.path == "/api/examples":
            self._json(200, {"examples": list_examples()})
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        if self.path != "/api/run":
            self._send(404, b"not found", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            self._json(200, execute(payload))
        except Exception as exc:  # noqa: BLE001 - report, never crash the loop
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="studio",
        description="rig the whole act — a visual multi-branch editor for the bag of tricks.",
    )
    p.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=8765, help="bind port (default: 8765)")
    p.add_argument("--open", action="store_true", help="open the editor in a browser")
    args = p.parse_args(argv)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    runnable = ", ".join(t["name"] for t in TRICKS)
    sys.stderr.write(
        f"studio — rig the whole act\n  {url}\n  {len(TRICKS)} runnable "
        f"tricks: {runnable}\n  Ctrl-C to stop\n"
    )
    if args.open:
        with contextlib.suppress(Exception):
            webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\nstudio: down\n")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
