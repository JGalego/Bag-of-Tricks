"""Tests for grill. Run: pytest (from repo root) or pytest grill/

The real run() calls a model through the inlined llm backend; these tests
stub `llm_complete` so no key or network is needed. The dry-run / plan paths
are pure and never touch a provider at all.
"""

import sys

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


def test_main_dry_run_returns_zero_without_provider(monkeypatch, capsys):
    # Guarantee a real run would explode if attempted — proves dry-run never calls a model.
    monkeypatch.setattr(
        grill, "llm_complete", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called"))
    )
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


def _stub(monkeypatch, finding):
    """Make `llm_complete` return `finding` (a parsed dict) directly."""
    monkeypatch.setattr(grill, "llm_available", lambda *a, **k: True)
    monkeypatch.setattr(grill, "llm_complete", lambda *a, **k: dict(finding))


def test_run_solid_answer_exits_zero(monkeypatch, capsys):
    finding = {"verdict": "holds", "angle": "assumptions", "question": "q", "finding": "stands"}
    _stub(monkeypatch, finding)
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
    _stub(monkeypatch, finding)
    rc = grill.run("trust me bro", "Is this true?", ["sources"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "CRACKS" in out
    assert "what's the source?" in out


def test_run_missing_key_returns_2(monkeypatch):
    monkeypatch.setattr(grill, "llm_available", lambda *a, **k: False)
    assert grill.run("answer", "", ["assumptions"]) == 2
