"""Tests for fold. Run: pytest (from repo root) or pytest fold/"""

import json

import fold as fold_mod
from fold import fold, fold_llm, load_patterns, main


def test_detect_certainty_definitely():
    out, findings = fold("This is definitely the answer.")
    assert "definitely" not in out
    assert "[FOLD:certainty]" in out
    assert any(f["type"] == "certainty" for f in findings)


def test_detect_guaranteed_no_doubt():
    out, findings = fold("It is guaranteed to work.")
    assert "guaranteed" not in out
    assert any(f["type"] == "no_doubt" for f in findings)


def test_detect_absolute_always():
    out, findings = fold("This always works.")
    assert "[FOLD:absolute]" in out
    assert any(f["type"] == "absolute" for f in findings)


def test_detect_false_authority():
    out, findings = fold("Trust me, this is right.")
    assert "Trust me" not in out
    assert any(f["type"] == "false_authority" for f in findings)


def test_clean_hedged_text_unchanged():
    text = "I'm not sure, but this might work in some cases — worth testing."
    out, findings = fold(text)
    assert out == text
    assert findings == []


def test_case_insensitive():
    _, findings = fold("DEFINITELY and Always and GUARANTEED")
    types = {f["type"] for f in findings}
    assert "certainty" in types
    assert "absolute" in types
    assert "no_doubt" in types


def test_only_restricts_types():
    text = "This always works, definitely."
    out, findings = fold(text, types={"certainty"})
    assert "always" in out  # absolute not requested -> untouched
    assert "definitely" not in out
    assert {f["type"] for f in findings} == {"certainty"}


def test_offsets_round_trip():
    text = "It is obviously always guaranteed."
    _, findings = fold(text)
    assert findings
    for f in findings:
        assert text[f["start"] : f["end"]] == f["match"]
    # Findings are in source order.
    starts = [f["start"] for f in findings]
    assert starts == sorted(starts)


def test_multiple_tells_counted():
    text = "This definitely and certainly always works."
    _, findings = fold(text)
    types = sorted(f["type"] for f in findings)
    assert types.count("certainty") == 2
    assert types.count("absolute") == 1


def test_check_exits_1_when_overconfident(tmp_path):
    p = tmp_path / "ans.txt"
    p.write_text("This will definitely always work, guaranteed.\n", encoding="utf-8")
    assert main(["--check", str(p)]) == 1


def test_check_exits_0_when_calibrated(tmp_path):
    p = tmp_path / "ans.txt"
    p.write_text("I don't know for certain; it may depend on the setup.\n", encoding="utf-8")
    assert main(["--check", str(p)]) == 0


def test_report_clean_message(tmp_path, capsys):
    p = tmp_path / "ans.txt"
    p.write_text("It might work, but I'm unsure.\n", encoding="utf-8")
    assert main(["--report", str(p)]) == 0
    out = capsys.readouterr().out
    assert "nothing to fold" in out


def test_json_mode(tmp_path, capsys):
    p = tmp_path / "ans.txt"
    p.write_text("This is definitely correct.\n", encoding="utf-8")
    assert main(["--json", str(p)]) == 0
    out = capsys.readouterr().out
    assert "certainty" in out


# --- custom --patterns: merge user detectors onto the built-ins --------------


def _write_patterns(tmp_path, detectors):
    path = tmp_path / "extra.json"
    path.write_text(json.dumps({"detectors": detectors}), encoding="utf-8")
    return path


def test_load_patterns_adds_a_detector(tmp_path):
    path = _write_patterns(tmp_path, {"weasel": r"\bbasically\b"})
    table = load_patterns([str(path)])
    assert "weasel" in table
    assert set(fold_mod._DETECTORS) <= set(table)  # built-ins kept as the base


def test_custom_pattern_matches_in_fold(tmp_path):
    path = _write_patterns(tmp_path, {"weasel": r"\bbasically\b"})
    table = load_patterns([str(path)])
    out, findings = fold("This basically works.", detectors=table)
    assert "[FOLD:weasel]" in out
    assert any(f["type"] == "weasel" for f in findings)


def test_custom_pattern_overrides_builtin_by_name(tmp_path):
    path = _write_patterns(tmp_path, {"certainty": r"\byep\b"})
    table = load_patterns([str(path)])
    _, findings = fold("yep, definitely.", detectors=table)
    # The override replaced the built-in certainty regex, so "yep" hits and
    # "definitely" no longer does.
    matches = {f["match"].lower() for f in findings}
    assert "yep" in matches
    assert "definitely" not in matches


def test_main_patterns_flag_matches(tmp_path, capsys):
    path = _write_patterns(tmp_path, {"weasel": r"\bbasically\b"})
    ans = tmp_path / "ans.txt"
    ans.write_text("This basically works.\n", encoding="utf-8")
    assert main(["--json", "--patterns", str(path), str(ans)]) == 0
    out = capsys.readouterr().out
    assert "weasel" in out


def test_main_patterns_env_fallback(tmp_path, monkeypatch, capsys):
    path = _write_patterns(tmp_path, {"weasel": r"\bbasically\b"})
    monkeypatch.setenv("FOLD_PATTERNS", str(path))
    ans = tmp_path / "ans.txt"
    ans.write_text("This basically works.\n", encoding="utf-8")
    assert main(["--json", str(ans)]) == 0
    assert "weasel" in capsys.readouterr().out


def test_main_bad_patterns_returns_2(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    ans = tmp_path / "ans.txt"
    ans.write_text("hi\n", encoding="utf-8")
    assert main(["--patterns", str(bad), str(ans)]) == 2


# --- model-backed (--llm) mode: stub the network seam, never call out --------


def _stub_complete(monkeypatch, findings):
    """Make fold_llm's model return the given {type, snippet, reason} findings."""

    def fake_complete(prompt, **kwargs):
        return {"findings": findings}

    monkeypatch.setattr(fold_mod, "llm_complete", fake_complete)


def test_llm_mode_tags_located_snippet(monkeypatch):
    text = "This approach scales to any workload."
    _stub_complete(
        monkeypatch,
        [
            {
                "type": "unearned_confidence",
                "snippet": "scales to any workload",
                "reason": "no proof",
            }
        ],
    )
    tagged, findings = fold_llm(text)
    assert "[FOLD:unearned_confidence]" in tagged
    assert len(findings) == 1
    f = findings[0]
    assert text[f["start"] : f["end"]] == "scales to any workload"


def test_llm_mode_unlocated_snippet_is_reported_not_tagged(monkeypatch):
    text = "This approach is solid."
    _stub_complete(
        monkeypatch,
        [{"type": "absolute", "snippet": "not in the text at all", "reason": "x"}],
    )
    tagged, findings = fold_llm(text)
    assert tagged == text  # nothing tagged
    assert findings == [
        {"type": "absolute", "match": "not in the text at all", "start": -1, "end": -1}
    ]


def test_llm_mode_calibrated_returns_empty(monkeypatch):
    _stub_complete(monkeypatch, [])
    tagged, findings = fold_llm("It might work, but I'm not sure.")
    assert findings == []
    assert tagged == "It might work, but I'm not sure."


def test_main_llm_flag_routes_to_model(monkeypatch, tmp_path):
    _stub_complete(
        monkeypatch,
        [{"type": "absolute", "snippet": "works on every platform", "reason": "y"}],
    )
    ans = tmp_path / "ans.txt"
    ans.write_text("This works on every platform.\n", encoding="utf-8")
    assert main(["--llm", "--check", str(ans)]) == 1


def test_main_llm_failure_returns_2(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise fold_mod.LLMError("no key")

    monkeypatch.setattr(fold_mod, "llm_complete", boom)
    ans = tmp_path / "ans.txt"
    ans.write_text("Some draft.\n", encoding="utf-8")
    assert main(["--llm", str(ans)]) == 2
