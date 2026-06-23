"""Tests for strawman. Run: pytest (from repo root) or pytest strawman/

The real run() calls the Anthropic API; these tests stub the `anthropic`
module so no key or network is needed.
"""

import json
import sys
import types

import strawman


def test_worst_picks_highest_severity():
    findings = [
        {"severity": "low"},
        {"severity": "critical"},
        {"severity": "medium"},
    ]
    assert strawman._worst(findings) == "critical"


def test_worst_empty_is_none():
    assert strawman._worst([]) == "none"


def test_severity_order_is_ascending():
    idx = strawman.SEVERITY_ORDER.index
    assert idx("none") < idx("low") < idx("medium") < idx("high") < idx("critical")


def test_dry_run_lists_attacks(capsys):
    rc = strawman.dry_run(["jailbreak", "injection"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "jailbreak" in out
    assert "injection" in out


def test_main_dry_run_returns_zero():
    assert strawman.main(["--dry-run", "--attacks", "jailbreak"]) == 0


def test_main_unknown_attack_returns_2():
    assert strawman.main(["--dry-run", "--attacks", "bogus"]) == 2


def _fake_anthropic(finding: dict):
    """Build a stand-in `anthropic` module whose client returns `finding`."""
    text = json.dumps(finding)

    class _Block:
        type = "text"

        def __init__(self, t):
            self.text = t

    class _Resp:
        content = [_Block(text)]

    class _Messages:
        def create(self, **kwargs):
            return _Resp()

    class _Client:
        messages = _Messages()

    mod = types.ModuleType("anthropic")
    mod.Anthropic = lambda *a, **k: _Client()
    return mod


def test_run_clean_prompt_exits_zero(monkeypatch, capsys):
    finding = {"cracked": False, "severity": "none", "attack": "-", "what_happens": "-", "fix": "-"}
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic(finding))
    rc = strawman.run("a solid prompt", ["jailbreak", "injection"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "NONE" in out
    assert "0/2 categories cracked" in out


def test_run_high_severity_exits_one(monkeypatch, capsys):
    finding = {
        "cracked": True,
        "severity": "high",
        "attack": "x",
        "what_happens": "leaks",
        "fix": "harden it",
    }
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic(finding))
    rc = strawman.run("a leaky prompt", ["extraction"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "HIGH" in out
    assert "harden it" in out


def test_run_missing_sdk_returns_2(monkeypatch):
    # simulate anthropic not being installed
    monkeypatch.setitem(sys.modules, "anthropic", None)
    assert strawman.run("prompt", ["jailbreak"]) == 2
