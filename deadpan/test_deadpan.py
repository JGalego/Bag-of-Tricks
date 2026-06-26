"""Tests for deadpan. Run: pytest (from repo root) or pytest deadpan/"""

import json

import pytest

from deadpan import _load_patterns, deadpan, main


@pytest.mark.parametrize(
    "src, want",
    [
        ("Certainly! The answer is 42.", "The answer is 42."),
        ("The answer is 42. Hope this helps!", "The answer is 42."),
        ("As an AI, I think the answer is 42.", "The answer is 42."),
        ("Great question! Basically, just use a map.", "Use a map."),
        ("Sure! Of course. The result is 7.", "The result is 7."),
    ],
)
def test_strips_fluff(src, want):
    assert deadpan(src).strip() == want


def test_emoji_removed_at_full():
    assert "\U0001f389" not in deadpan("The answer is 42 \U0001f389")


def test_emoji_kept_at_lite():
    assert "\U0001f389" in deadpan("The answer is 42 \U0001f389", level="lite")


def test_hedges_kept_at_lite():
    # "lite" keeps hedges like "I think"
    assert "think" in deadpan("I think the answer is 42.", level="lite").lower()


def test_code_fence_preserved():
    src = "Certainly! Here is code:\n```py\n# I think this is fine\nx = 1\n```\nHope this helps!"
    out = deadpan(src)
    assert "# I think this is fine" in out  # comment inside fence untouched
    assert "x = 1" in out
    assert "Certainly" not in out
    assert "Hope this helps" not in out


def test_inline_code_preserved():
    out = deadpan("Just run `pip install really cool`.")
    assert "`pip install really cool`" in out  # 'really' inside backticks survives


def test_first_letter_capitalized_after_strip():
    out = deadpan("certainly! the answer is 42.")
    assert out[0].isupper()


def test_idempotent():
    once = deadpan("Certainly! The answer is 42. Hope this helps!")
    assert deadpan(once).strip() == once.strip()


def test_trailing_newline_preserved():
    assert deadpan("The answer is 42.\n").endswith("\n")
    assert not deadpan("The answer is 42.").endswith("\n")


def test_ultra_collapses_blank_lines():
    out = deadpan("Line one.\n\n\n\nLine two.", level="ultra")
    assert "\n\n\n" not in out


# --- custom patterns ------------------------------------------------------


def _write_patterns(tmp_path, data):
    p = tmp_path / "patterns.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_custom_opener_stripped(tmp_path):
    pats = _write_patterns(tmp_path, {"openers": [r"here'?s the deal[!,. ]*"]})
    extra = _load_patterns([str(pats)])
    out = deadpan("Here's the deal: the answer is 42.", extra=extra)
    assert out.strip() == "The answer is 42."


def test_default_unchanged_without_patterns():
    # No extra -> built-in behavior; a custom phrase is NOT stripped.
    assert deadpan("Here's the deal: the answer is 42.").strip() == (
        "Here's the deal: the answer is 42."
    )


def test_builtin_openers_still_stripped_with_custom(tmp_path):
    pats = _write_patterns(tmp_path, {"openers": [r"here'?s the deal[!,. ]*"]})
    extra = _load_patterns([str(pats)])
    out = deadpan("Certainly! The answer is 42.", extra=extra)
    assert out.strip() == "The answer is 42."


def test_custom_signoff_stripped(tmp_path):
    pats = _write_patterns(tmp_path, {"signoffs": [r"cheers[!.]?\s*$"]})
    extra = _load_patterns([str(pats)])
    out = deadpan("The answer is 42. Cheers!", extra=extra)
    assert out.strip() == "The answer is 42."


def test_custom_patterns_via_main_flag(tmp_path, capsys):
    pats = _write_patterns(tmp_path, {"openers": [r"here'?s the deal[!,. ]*"]})
    src = tmp_path / "resp.md"
    src.write_text("Here's the deal: the answer is 42.\n", encoding="utf-8")
    assert main([str(src), "--patterns", str(pats)]) == 0
    out = capsys.readouterr().out
    assert out.strip() == "The answer is 42."


def test_custom_patterns_via_env_var(tmp_path, capsys, monkeypatch):
    pats = _write_patterns(tmp_path, {"openers": [r"here'?s the deal[!,. ]*"]})
    monkeypatch.setenv("DEADPAN_PATTERNS", str(pats))
    src = tmp_path / "resp.md"
    src.write_text("Here's the deal: the answer is 42.\n", encoding="utf-8")
    assert main([str(src)]) == 0
    out = capsys.readouterr().out
    assert out.strip() == "The answer is 42."
