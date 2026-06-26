"""Tests for interrobang. Run: pytest (from repo root) or pytest interrobang/"""

import interrobang


def test_lint_flags_assumptions():
    text = "Sure! I'll assume you mean production and drop the table."
    hits = interrobang.lint(text)
    assert len(hits) == 1
    line_no, phrase, _ = hits[0]
    assert line_no == 1
    assert phrase.lower().startswith("i'll assume")


def test_lint_flags_multiple_lines():
    text = "I'll assume X.\nNothing here.\nDefaulting to UTC.\n"
    hits = interrobang.lint(text)
    assert {h[0] for h in hits} == {1, 3}


def test_lint_clean_text_returns_nothing():
    assert interrobang.lint("Which database should I use, Postgres or SQLite?") == []


def test_lint_one_hit_per_line():
    # a line with two guess phrases is reported once
    hits = interrobang.lint("I'll assume and I'll just go ahead.")
    assert len(hits) == 1


def test_check_exit_codes(tmp_path):
    clean = tmp_path / "clean.txt"
    clean.write_text("What timezone should I use?")
    assert interrobang.cmd_check(str(clean)) == 0

    dirty = tmp_path / "dirty.txt"
    dirty.write_text("I'll assume UTC.")
    assert interrobang.cmd_check(str(dirty)) == 1


def test_prompt_mode_emits_addendum(capsys):
    rc = interrobang.cmd_prompt()
    out = capsys.readouterr().out
    assert rc == 0
    assert interrobang.GLYPH in out
    assert "ask" in out.lower()


def test_glyph_is_interrobang():
    assert interrobang.GLYPH == "‽"


def test_main_no_subcommand_returns_2():
    assert interrobang.main([]) == 2


def test_main_check_via_stdin(monkeypatch, capsys):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("I'll assume the default.\n"))
    # stdin from StringIO has no isatty; interrobang guards with isatty() -> attr error?
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    rc = interrobang.main(["check"])
    assert rc == 1


# --- custom --patterns: merged into the offline check, no network ------------


def test_custom_patterns_flag_flags_new_phrase(tmp_path):
    import json

    pat = tmp_path / "p.json"
    pat.write_text(json.dumps({"patterns": [r"\byolo it\b"]}), encoding="utf-8")
    # Not a built-in phrase, so plain lint misses it...
    assert interrobang.lint("We'll yolo it and ship.") == []
    # ...but with the custom pattern merged in, it gets flagged.
    rules = interrobang._load_patterns([str(pat)])
    hits = interrobang.lint("We'll yolo it and ship.", patterns=rules)
    assert len(hits) == 1
    assert hits[0][1].lower() == "yolo it"


def test_custom_patterns_keep_builtins(tmp_path):
    import json

    pat = tmp_path / "p.json"
    pat.write_text(json.dumps({"patterns": [r"\byolo it\b"]}), encoding="utf-8")
    rules = interrobang._load_patterns([str(pat)])
    # built-in phrase still flagged alongside the custom one
    hits = interrobang.lint("I'll assume X.\nWe'll yolo it.\n", patterns=rules)
    assert {h[0] for h in hits} == {1, 2}


def test_custom_patterns_via_env(tmp_path, monkeypatch):
    import json

    pat = tmp_path / "p.json"
    pat.write_text(json.dumps({"patterns": [r"\byolo it\b"]}), encoding="utf-8")
    monkeypatch.setenv("INTERROBANG_PATTERNS", str(pat))
    rules = interrobang._load_patterns(None)
    hits = interrobang.lint("We'll yolo it.", patterns=rules)
    assert len(hits) == 1


def test_check_uses_custom_patterns(tmp_path):
    import json

    pat = tmp_path / "p.json"
    pat.write_text(json.dumps({"patterns": [r"\byolo it\b"]}), encoding="utf-8")
    target = tmp_path / "t.txt"
    target.write_text("We'll yolo it and ship.\n", encoding="utf-8")
    # without the pattern it's clean (exit 0); with it, flagged (exit 1)
    assert interrobang.main(["check", str(target)]) == 0
    assert interrobang.main(["check", str(target), "--patterns", str(pat)]) == 1


# --- model-backed (--llm) mode: stub the network seam, never call out --------


def _stub_complete(monkeypatch, guesses):
    """Make lint_llm's model return the given guesses (list of dicts)."""

    def fake_complete(prompt, **kwargs):
        return {"guesses": guesses}

    monkeypatch.setattr(interrobang, "llm_complete", fake_complete)


def test_llm_mode_maps_to_tuple_shape(monkeypatch):
    _stub_complete(
        monkeypatch,
        [{"line": 2, "phrase": "went with UTC", "snippet": "So I just went with UTC."}],
    )
    hits = interrobang.lint_llm("Pick a timezone.\nSo I just went with UTC.")
    assert hits == [(2, "went with UTC", "So I just went with UTC.")]


def test_main_llm_flag_routes_to_model(monkeypatch, tmp_path):
    _stub_complete(
        monkeypatch,
        [{"line": 1, "phrase": "went with UTC", "snippet": "I went with UTC."}],
    )
    target = tmp_path / "t.txt"
    target.write_text("I went with UTC.\n", encoding="utf-8")
    assert interrobang.main(["check", "--llm", str(target)]) == 1


def test_main_llm_clean_returns_0(monkeypatch, tmp_path):
    _stub_complete(monkeypatch, [])
    target = tmp_path / "t.txt"
    target.write_text("Which timezone should I use?\n", encoding="utf-8")
    assert interrobang.main(["check", "--llm", str(target)]) == 0


def test_main_llm_failure_returns_2(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise interrobang.LLMError("no key")

    monkeypatch.setattr(interrobang, "llm_complete", boom)
    target = tmp_path / "t.txt"
    target.write_text("I went with UTC.\n", encoding="utf-8")
    assert interrobang.main(["check", "--llm", str(target)]) == 2
