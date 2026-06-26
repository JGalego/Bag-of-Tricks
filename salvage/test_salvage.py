"""Tests for salvage. Run: pytest (from repo root) or pytest salvage/"""

import pytest

from salvage import find_json, salvage


def test_fenced_json_block():
    src = 'Sure, here you go:\n```json\n{"ok": true}\n```\nHope this helps!'
    assert salvage(src, indent=None) == '{"ok":true}'


def test_trailing_comma():
    assert salvage('{"a": 1, "b": 2,}', indent=None) == '{"a":1,"b":2}'
    assert salvage("[1, 2, 3,]", indent=None) == "[1,2,3]"


def test_python_literals():
    out = salvage('{"a": True, "b": False, "c": None}', indent=None)
    assert out == '{"a":true,"b":false,"c":null}'


def test_prose_before_and_after():
    src = 'The result is below.\n{"answer": 42}\nLet me know if you need more!'
    assert salvage(src, indent=None) == '{"answer":42}'


def test_top_level_array():
    src = "Here are the items: [1, 2, 3] and that's all."
    assert salvage(src, indent=None) == "[1,2,3]"


def test_brace_inside_string_value():
    src = '{"note": "use {curly} and [square] brackets", "n": 1}'
    out = salvage(src, indent=None)
    assert out == '{"note":"use {curly} and [square] brackets","n":1}'


def test_brace_inside_string_does_not_truncate():
    # The literal close brace inside the string must not end the object early.
    raw = find_json('prefix {"a": "}", "b": 2} suffix')
    assert raw == '{"a": "}", "b": 2}'


def test_escaped_quote_in_string():
    src = '{"q": "she said \\"hi\\"", "ok": true}'
    out = salvage(src, indent=None)
    assert out == '{"q":"she said \\"hi\\"","ok":true}'


def test_comments_stripped():
    src = """{
        // a line comment
        "a": 1, /* block */ "b": 2
    }"""
    assert salvage(src, indent=None) == '{"a":1,"b":2}'


def test_smart_quotes():
    src = "{“key”: “value”}"
    assert salvage(src, indent=None) == '{"key":"value"}'


def test_compact_vs_indented():
    compact = salvage('{"a": 1}', indent=None)
    pretty = salvage('{"a": 1}', indent=2)
    assert compact == '{"a":1}'
    assert "\n" in pretty
    assert pretty == '{\n  "a": 1\n}'


def test_extract_only_does_not_repair():
    # find_json locates but leaves the trailing comma / Python literal intact.
    assert find_json('blah {"a": True,} blah') == '{"a": True,}'


def test_unsalvageable_raises():
    with pytest.raises(ValueError, match="no salvageable JSON"):
        salvage("there is no json here at all")
    with pytest.raises(ValueError, match="no salvageable JSON"):
        find_json("nothing structured here")


def test_unsalvageable_invalid_json_raises():
    # Has braces but cannot be parsed even after repair.
    with pytest.raises(ValueError, match="no salvageable JSON"):
        salvage("{this is not : valid json ::}")


def test_cli_returns_1_on_bad_file(tmp_path):
    from salvage import main

    bad = tmp_path / "bad.txt"
    bad.write_text("no json in this file", encoding="utf-8")
    assert main([str(bad)]) == 1


def test_cli_returns_0_on_good_file(tmp_path):
    from salvage import main

    good = tmp_path / "good.txt"
    good.write_text('blah {"x": 1,} blah', encoding="utf-8")
    assert main([str(good), "--compact"]) == 0


# --- custom patterns ------------------------------------------------------


def test_custom_smart_quote_pair_makes_invalid_json_parse():
    # «» are not built-in smart quotes; without the custom pair this would fail.
    extra = {"smart_quotes": {"«": '"', "»": '"'}}
    src = "{«key»: «value»}"
    assert salvage(src, indent=None, extra=extra) == '{"key":"value"}'


def test_custom_py_literal_converted():
    extra = {"py_literals": {"Nil": "null"}}
    out = salvage('{"a": Nil}', indent=None, extra=extra)
    assert out == '{"a":null}'


def test_custom_py_literal_does_not_touch_strings():
    extra = {"py_literals": {"Nil": "null"}}
    out = salvage('{"a": Nil, "b": "Nil"}', indent=None, extra=extra)
    assert out == '{"a":null,"b":"Nil"}'


def test_builtins_still_work_with_custom_patterns():
    # Built-in True/False/None still convert when extra is supplied.
    extra = {"py_literals": {"Nil": "null"}}
    out = salvage('{"a": True, "b": Nil, "c": None}', indent=None, extra=extra)
    assert out == '{"a":true,"b":null,"c":null}'


def test_default_behavior_unchanged_without_patterns():
    # «» stay as-is (invalid) -> unsalvageable when no custom patterns given.
    with pytest.raises(ValueError, match="no salvageable JSON"):
        salvage("{«key»: «value»}")


def test_load_patterns_merges_files(tmp_path):
    from salvage import _load_patterns

    f1 = tmp_path / "a.json"
    f1.write_text('{"smart_quotes": {"«": "\\""}}', encoding="utf-8")
    f2 = tmp_path / "b.json"
    f2.write_text('{"py_literals": {"Nil": "null"}}', encoding="utf-8")
    merged = _load_patterns([str(f1), str(f2)])
    assert merged["smart_quotes"] == {"«": '"'}
    assert merged["py_literals"] == {"Nil": "null"}


def test_cli_patterns_flag(tmp_path):
    from salvage import main

    pats = tmp_path / "pats.json"
    pats.write_text('{"py_literals": {"Nil": "null"}}', encoding="utf-8")
    data = tmp_path / "data.txt"
    data.write_text('{"a": Nil}', encoding="utf-8")
    assert main(["--patterns", str(pats), "--compact", str(data)]) == 0


def test_cli_patterns_env(tmp_path, monkeypatch, capsys):
    from salvage import main

    pats = tmp_path / "pats.json"
    pats.write_text('{"py_literals": {"Nil": "null"}}', encoding="utf-8")
    data = tmp_path / "data.txt"
    data.write_text('{"a": Nil}', encoding="utf-8")
    monkeypatch.setenv("SALVAGE_PATTERNS", str(pats))
    rc = main(["--compact", str(data)])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip() == '{"a":null}'
