#!/usr/bin/env python3
"""bluff — call its bluff.

Extracts the URLs and citations from an LLM answer and checks each one
actually resolves, catching hallucinated or dead links before you trust
them. Extraction is fully offline; only the checking step hits the network
(stdlib urllib only).

    echo "See [the docs](https://example.com) and https://httpbin.org/get." | bluff.py
    bluff.py --dry-run answer.md      # just list the URLs, no network
    bluff.py --json --timeout 3 answer.md
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import urllib.error
import urllib.request

# Bare http/https URLs. We grab a generous run of non-space chars, then strip
# trailing sentence punctuation below so a URL ending a sentence isn't broken.
_URL_RE = re.compile(r"https?://[^\s<>\"'\]\)]+", re.IGNORECASE)
# Markdown link targets: [text](url) — capture the url.
_MD_RE = re.compile(r"\[[^\]]*\]\(\s*(https?://[^\s)]+)\s*\)", re.IGNORECASE)

_TRAILING = ".,;:!?)]}>\"'"

_UA = "Mozilla/5.0 (compatible; bluff/0.1; +https://github.com/JGalego/Bag-of-Tricks)"


def _strip_trailing(url: str) -> str:
    """Drop trailing punctuation that likely closes a sentence, not the URL."""
    return url.rstrip(_TRAILING)


def extract_urls(text: str) -> list[str]:
    """Find bare URLs and markdown-link targets, de-duped, order preserved.

    Fully offline. Trailing sentence punctuation (a period, comma, closing
    paren, etc.) is not treated as part of the URL.
    """
    # Collect both kinds of match with their position, then walk left-to-right
    # so the listing follows the order the URLs appear in the text. Markdown
    # targets start at the "[" (earlier than the bare URL nested in the parens),
    # so the explicitly-delimited form wins the de-dupe.
    hits = [(m.start(), _strip_trailing(m.group(1))) for m in _MD_RE.finditer(text)]
    hits += [(m.start(), _strip_trailing(m.group(0))) for m in _URL_RE.finditer(text)]
    hits.sort(key=lambda h: h[0])

    found: list[str] = []
    seen: set[str] = set()
    for _, url in hits:
        if url and url not in seen:
            seen.add(url)
            found.append(url)
    return found


def check_url(url: str, timeout: float = 5.0) -> dict:
    """Resolve a URL with HEAD (falling back to GET on 405/501).

    The ONLY function that touches the network. Treats 2xx/3xx as ok and
    reports any error instead of raising.
    """
    opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
    headers = {"User-Agent": _UA}

    def _try(method: str) -> dict:
        req = urllib.request.Request(url, method=method, headers=headers)
        with opener.open(req, timeout=timeout) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            return {"url": url, "ok": 200 <= status < 400, "status": status, "error": None}

    try:
        return _try("HEAD")
    except urllib.error.HTTPError as e:
        if e.code in (405, 501):
            try:
                return _try("GET")
            except urllib.error.HTTPError as e2:
                ok = 200 <= e2.code < 400
                return {
                    "url": url,
                    "ok": ok,
                    "status": e2.code,
                    "error": None if ok else f"HTTP {e2.code}",
                }
            except (urllib.error.URLError, socket.timeout, OSError) as e2:
                return {"url": url, "ok": False, "status": None, "error": str(e2)}
        ok = 200 <= e.code < 400
        return {"url": url, "ok": ok, "status": e.code, "error": None if ok else f"HTTP {e.code}"}
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        return {"url": url, "ok": False, "status": None, "error": str(e)}


def check_all(urls: list[str], timeout: float = 5.0, _checker=check_url) -> list[dict]:
    """Check every URL. `_checker` is injectable so tests stay offline."""
    return [_checker(u, timeout=timeout) for u in urls]


def _format(result: dict) -> str:
    mark = "✓" if result["ok"] else "✗"
    status = result["status"] if result["status"] is not None else "—"
    line = f"{mark} [{status}] {result['url']}"
    if result["error"]:
        line += f"  ({result['error']})"
    return line


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bluff", description="call its bluff.")
    p.add_argument("files", nargs="*", help="files to read (default: stdin)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="extract and list URLs only, no network, exit 0",
    )
    p.add_argument(
        "--timeout", type=float, default=5.0, help="per-URL timeout in seconds (default: 5)"
    )
    p.add_argument("--json", action="store_true", help="emit structured JSON results")
    p.add_argument("-q", "--quiet", action="store_true", help="only print the dead ones")
    args = p.parse_args(argv)

    raw = (
        "".join(open(f, encoding="utf-8").read() for f in args.files)
        if args.files
        else sys.stdin.read()
    )
    urls = extract_urls(raw)

    if args.dry_run:
        if args.json:
            sys.stdout.write(json.dumps(urls, indent=2) + "\n")
        else:
            for u in urls:
                sys.stdout.write(u + "\n")
        return 0

    results = check_all(urls, timeout=args.timeout)
    dead = [r for r in results if not r["ok"]]

    if args.json:
        sys.stdout.write(json.dumps(results, indent=2) + "\n")
    else:
        shown = dead if args.quiet else results
        for r in shown:
            sys.stdout.write(_format(r) + "\n")
        if not args.quiet:
            sys.stderr.write(f"\n[bluff] {len(urls)} link(s), {len(dead)} dead\n")

    return 1 if dead else 0


if __name__ == "__main__":
    raise SystemExit(main())
