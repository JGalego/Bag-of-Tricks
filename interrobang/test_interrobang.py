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
