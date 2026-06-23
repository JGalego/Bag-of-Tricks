"""Tests for fold. Run: pytest (from repo root) or pytest fold/"""

from fold import fold, main


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
