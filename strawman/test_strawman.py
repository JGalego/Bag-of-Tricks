"""Tests for strawman. Run: pytest (from repo root) or pytest strawman/

The real run() calls a model through the inlined llm backend; these tests
stub `llm_complete` so no key or network is needed.
"""

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


def _stub(monkeypatch, finding):
    """Make `llm_complete` return `finding` (a parsed dict) directly."""
    monkeypatch.setattr(strawman, "llm_available", lambda *a, **k: True)
    monkeypatch.setattr(strawman, "llm_complete", lambda *a, **k: dict(finding))


def test_run_clean_prompt_exits_zero(monkeypatch, capsys):
    finding = {"cracked": False, "severity": "none", "attack": "-", "what_happens": "-", "fix": "-"}
    _stub(monkeypatch, finding)
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
    _stub(monkeypatch, finding)
    rc = strawman.run("a leaky prompt", ["extraction"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "HIGH" in out
    assert "harden it" in out


def test_run_missing_key_returns_2(monkeypatch):
    monkeypatch.setattr(strawman, "llm_available", lambda *a, **k: False)
    assert strawman.run("prompt", ["jailbreak"]) == 2
