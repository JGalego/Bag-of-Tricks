"""Tests for launder. Run: pytest (from repo root) or pytest launder/"""

import json

from launder import _load_patterns, launder, main

ZWSP = "​"  # ZERO WIDTH SPACE
WORD_JOINER = "⁠"
BOM = "﻿"
NBSP = " "
THIN = " "
SOFT = "­"
CYR_A = "а"  # Cyrillic 'а'


def test_zero_width_stripped():
    out, findings = launder(f"he{ZWSP}llo{WORD_JOINER}{BOM}")
    assert out == "hello"
    assert all(f["type"] == "zero_width" for f in findings)
    assert len(findings) == 3


def test_smart_quotes_straightened():
    out, findings = launder("he said “hi” and ‘bye’")
    assert out == "he said \"hi\" and 'bye'"
    assert {f["type"] for f in findings} == {"smart_quote"}
    assert len(findings) == 4


def test_em_dash_normalized():
    out, findings = launder("wait—stop")
    assert out == "wait--stop"  # em-dash -> "--" by default
    assert any(f["type"] == "em_dash" for f in findings)


def test_en_dash_normalized():
    out, findings = launder("pages 1–9")
    assert out == "pages 1-9"  # en-dash -> "-" by default
    assert any(f["type"] == "en_dash" for f in findings)


def test_ellipsis_normalized():
    out, _ = launder("wait…")
    assert out == "wait..."


def test_exotic_spaces_normalized():
    out, findings = launder(f"a{NBSP}b{THIN}c")
    assert out == "a b c"
    assert all(f["type"] == "exotic_space" for f in findings)


def test_soft_hyphen_removed():
    out, findings = launder(f"sof{SOFT}t")
    assert out == "soft"
    assert findings and findings[0]["type"] == "soft_hyphen"


def test_clean_ascii_unchanged():
    text = "just words, numbers 12345, and 'plain' quotes -- dashes."
    out, findings = launder(text)
    assert out == text  # byte-for-byte
    assert findings == []


def test_empty_text():
    out, findings = launder("")
    assert out == ""
    assert findings == []


def test_homoglyphs_off_by_default():
    # A Cyrillic 'а' that looks like ASCII 'a' is left alone unless asked.
    text = f"sc{CYR_A}m"
    out, findings = launder(text)
    assert out == text
    assert findings == []


def test_homoglyphs_opt_in():
    text = f"sc{CYR_A}m"
    out, findings = launder(text, homoglyphs=True)
    assert out == "scam"
    assert any(f["type"] == "homoglyph" for f in findings)


def test_offsets_sane():
    text = f"a{ZWSP}b“c”"
    _, findings = launder(text)
    for f in findings:
        assert text[f["start"]] == f["char"]
    # Findings are in source order.
    starts = [f["start"] for f in findings]
    assert starts == sorted(starts)


def test_check_exits_1_when_fingerprint_present(tmp_path):
    p = tmp_path / "draft.txt"
    p.write_text(f"he said {ZWSP}hi\n", encoding="utf-8")
    assert main(["--check", str(p)]) == 1


def test_check_exits_0_when_clean(tmp_path):
    p = tmp_path / "draft.txt"
    p.write_text("plain ascii only\n", encoding="utf-8")
    assert main(["--check", str(p)]) == 0


def test_default_prints_cleaned_text(tmp_path, capsys):
    p = tmp_path / "draft.txt"
    p.write_text("he said “hi”\n", encoding="utf-8")
    assert main([str(p)]) == 0
    out = capsys.readouterr().out
    assert out == 'he said "hi"\n'


def test_report_lists_categories(tmp_path, capsys):
    p = tmp_path / "draft.txt"
    p.write_text(f"a{ZWSP}b“c”\n", encoding="utf-8")
    assert main(["--report", str(p)]) == 0
    out = capsys.readouterr().out
    assert "zero_width" in out
    assert "smart_quote" in out


# --- custom patterns ------------------------------------------------------


def _write_patterns(tmp_path, data):
    p = tmp_path / "patterns.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def test_custom_category_scrubbed_and_reported(tmp_path):
    pats = _write_patterns(tmp_path, {"bullet": {"•": "-"}})
    extra = _load_patterns([str(pats)])
    out, findings = launder("• item", extra=extra)
    assert out == "- item"
    assert any(f["type"] == "bullet" for f in findings)


def test_custom_extends_known_category(tmp_path):
    pats = _write_patterns(tmp_path, {"smart_quote": {"«": '"', "»": '"'}})
    extra = _load_patterns([str(pats)])
    out, findings = launder("«hi»", extra=extra)
    assert out == '"hi"'
    assert {f["type"] for f in findings} == {"smart_quote"}


def test_builtins_still_work_with_custom_patterns(tmp_path):
    pats = _write_patterns(tmp_path, {"bullet": {"•": "-"}})
    extra = _load_patterns([str(pats)])
    out, findings = launder("he said “hi”", extra=extra)
    assert out == 'he said "hi"'
    assert {f["type"] for f in findings} == {"smart_quote"}


def test_pure_ascii_round_trips_with_custom_patterns(tmp_path):
    pats = _write_patterns(tmp_path, {"bullet": {"•": "-"}})
    extra = _load_patterns([str(pats)])
    text = "just plain ascii, nothing fancy."
    out, findings = launder(text, extra=extra)
    assert out == text
    assert findings == []


def test_custom_patterns_via_main_flag(tmp_path, capsys):
    pats = _write_patterns(tmp_path, {"bullet": {"•": "-"}})
    src = tmp_path / "draft.txt"
    src.write_text("• item\n", encoding="utf-8")
    assert main(["--patterns", str(pats), str(src)]) == 0
    out = capsys.readouterr().out
    assert out == "- item\n"


def test_custom_patterns_via_env_var(tmp_path, capsys, monkeypatch):
    pats = _write_patterns(tmp_path, {"bullet": {"•": "-"}})
    monkeypatch.setenv("LAUNDER_PATTERNS", str(pats))
    src = tmp_path / "draft.txt"
    src.write_text("• item\n", encoding="utf-8")
    assert main([str(src)]) == 0
    out = capsys.readouterr().out
    assert out == "- item\n"
