"""Tests for grill. Run: pytest (from repo root) or pytest grill/

The real run() calls the Anthropic API; these tests stub the `anthropic`
module so no key or network is needed. The dry-run / plan paths are pure and
never import anthropic at all.
"""

import json
import sys
import types

import grill


def test_interrogation_plan_produces_a_question_per_angle():
    angles = ["assumptions", "sources"]
    plan = grill.interrogation_plan(angles)
    assert [item["angle"] for item in plan] == angles
    for item in plan:
        assert item["question"]  # non-empty probing question
        assert item["question"].endswith("?") or "?" in item["question"]


def test_interrogation_plan_covers_every_angle():
    plan = grill.interrogation_plan(list(grill.ANGLES))
    assert len(plan) == len(grill.ANGLES)


def test_worst_picks_highest_verdict():
    findings = [{"verdict": "weak"}, {"verdict": "cracks"}, {"verdict": "shaky"}]
    assert grill._worst(findings) == "cracks"


def test_worst_empty_is_holds():
    assert grill._worst([]) == "holds"


def test_verdict_order_is_ascending():
    idx = grill.VERDICT_ORDER.index
    assert idx("holds") < idx("weak") < idx("shaky") < idx("cracks")


def test_dry_run_lists_angles_and_questions(capsys):
    rc = grill.dry_run(["assumptions", "sources"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "assumptions" in out
    assert "sources" in out
    assert "source" in out.lower()  # the probing question text shows up


def test_main_dry_run_returns_zero_without_anthropic(monkeypatch, capsys):
    # Guarantee a real run would explode if attempted — proves dry-run never imports it.
    monkeypatch.setitem(sys.modules, "anthropic", None)
    rc = grill.main(["--dry-run", "--angles", "assumptions"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "assumptions" in out


def test_main_dry_run_via_stdin(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert grill.main(["--dry-run"]) == 0


def test_main_unknown_angle_returns_2():
    assert grill.main(["--dry-run", "--angles", "bogus"]) == 2


def test_main_passes_question_through(capsys):
    rc = grill.main(["--dry-run", "--angles", "assumptions", "--question", "Is it safe?"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Is it safe?" in out


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


def test_run_solid_answer_exits_zero(monkeypatch, capsys):
    finding = {"verdict": "holds", "angle": "assumptions", "question": "q", "finding": "stands"}
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic(finding))
    rc = grill.run("a careful, well-sourced answer", "", ["assumptions", "sources"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "HOLDS" in out
    assert "0/2 angles cracked" in out


def test_run_cracking_answer_exits_one(monkeypatch, capsys):
    finding = {
        "verdict": "cracks",
        "angle": "sources",
        "question": "what's the source?",
        "finding": "asserted with no evidence",
    }
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic(finding))
    rc = grill.run("trust me bro", "Is this true?", ["sources"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "CRACKS" in out
    assert "what's the source?" in out


def test_run_missing_sdk_returns_2(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    assert grill.run("answer", "", ["assumptions"]) == 2
