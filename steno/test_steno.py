"""Tests for steno. Run: pytest (from repo root) or pytest steno/

`--run` is stubbed (via `steno.llm_complete`) so no SDK / network / key is needed.
"""

import steno


def test_builtins_present():
    for key in ("e", "r", "t", "c", "rx", "tl"):
        assert key in steno.BUILTINS
        name, template = steno.BUILTINS[key]
        assert "{input}" in template


def test_expand_splices_input():
    aliases = steno.load_aliases(None)
    out = steno.expand(aliases, "e", "print(1)")
    assert "print(1)" in out
    assert "{input}" not in out


def test_expand_preserves_literal_braces():
    # input with braces must not break templating (.replace, not .format)
    aliases = steno.load_aliases(None)
    out = steno.expand(aliases, "e", "x = {'a': 1}")
    assert "{'a': 1}" in out


def test_gather_input_text_opt_wins():
    assert steno.gather_input(["ignored"], "literal") == "literal"


def test_gather_input_literal_text():
    assert steno.gather_input(["hello", "world"], None) == "hello world"


def test_gather_input_reads_files(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    out = steno.gather_input([str(f)], None)
    assert "x = 1" in out
    assert str(f) in out  # filename header included


def test_user_aliases_extend_and_override(tmp_path):
    af = tmp_path / "aliases.txt"
    af.write_text(
        "# my aliases\nyo  Say hi about: {input}\nnoinput  This template has no placeholder\n"
    )
    aliases = steno.load_aliases(str(af))
    assert "yo" in aliases
    assert steno.expand(aliases, "yo", "cats") == "Say hi about: cats"
    # a template missing {input} gets one appended
    assert "{input}" not in aliases["noinput"][1].replace("{input}", "")
    assert steno.expand(aliases, "noinput", "X").endswith("X")
    # built-ins still there
    assert "r" in aliases


def test_main_list(capsys):
    assert steno.main(["ls"]) == 0
    out = capsys.readouterr().out
    assert "review" in out and "commit" in out


def test_main_no_args_lists(capsys):
    assert steno.main([]) == 0
    assert "aliases" in capsys.readouterr().out


def test_main_unknown_alias():
    assert steno.main(["zzz", "x"]) == 2


def test_main_expand_prints_prompt(capsys):
    rc = steno.main(["r", "--text", "def f(): pass"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Review the following code" in out
    assert "def f(): pass" in out


def test_main_missing_input_errors(monkeypatch):
    # no args, stdin is a tty -> nothing to work with
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    assert steno.main(["e"]) == 2


def test_commit_alias_uses_git_diff(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)  # interactive: no stdin
    monkeypatch.setattr(steno, "_git_diff", lambda: "diff --git a/x b/x\n+hi\n")
    rc = steno.main(["c"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "commit message" in out.lower()
    assert "+hi" in out


def test_run_uses_helper(monkeypatch, capsys):
    monkeypatch.setattr(steno, "llm_available", lambda provider=None: True)
    monkeypatch.setattr(steno, "llm_complete", lambda prompt, **kwargs: "LGTM.")
    rc = steno.main(["r", "--text", "def f(): pass", "--run"])
    assert rc == 0
    assert "LGTM." in capsys.readouterr().out


def test_run_no_key_returns_2(monkeypatch):
    monkeypatch.setattr(steno, "llm_available", lambda provider=None: False)
    assert steno.main(["r", "--text", "x", "--run"]) == 2
