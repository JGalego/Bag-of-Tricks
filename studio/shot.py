#!/usr/bin/env python3
"""shot — regenerate the studio screenshot in the README.

Spins up the studio server on a scratch port, drives a headless Chromium with
Playwright to load the sample routine and run it (so nodes show their status
tints and the output box fills), then writes studio/studio.png.

It's the reproducible source for the doc image — the PNG is a build artifact,
this is how to rebuild it:

    pip install playwright && playwright install chromium
    python studio/shot.py

Optional flags: --port, --out.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="shot", description="regenerate the studio screenshot")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--out", default=str(HERE / "studio.png"))
    args = ap.parse_args(argv)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.stderr.write(
            "shot: needs Playwright — pip install playwright && playwright install chromium\n"
        )
        return 1

    url = f"http://127.0.0.1:{args.port}/"
    server = subprocess.Popen(
        [sys.executable, str(HERE / "server.py"), "--port", str(args.port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(50):  # wait for the server to answer
            try:
                urllib.request.urlopen(url, timeout=1)
                break
            except OSError:
                time.sleep(0.1)

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception:  # noqa: BLE001 - fall back to a system chromium
                browser = p.chromium.launch(executable_path="/usr/bin/chromium")
            page = browser.new_page(viewport={"width": 1780, "height": 900}, device_scale_factor=2)
            page.goto(url)
            page.wait_for_selector(".chip")  # palette loaded
            page.click("#sampleBtn")  # load the sample routine
            page.wait_for_selector(".node .hd")  # nodes rendered
            page.click("#runBtn")  # run it
            page.wait_for_function(
                "document.querySelector('#outview') "
                "&& document.querySelector('#outview').querySelector('.ob')",
                timeout=8000,
            )
            page.evaluate("setZoom(0.9); stage.scrollTo(0,0);")  # fit the whole routine
            time.sleep(0.6)  # let the trace animation settle
            page.evaluate("document.getElementById('toast').classList.remove('show')")
            page.screenshot(path=args.out)
            browser.close()
        sys.stderr.write(f"shot: wrote {args.out}\n")
        return 0
    finally:
        server.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
